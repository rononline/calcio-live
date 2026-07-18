import logging
from datetime import timezone
from zoneinfo import ZoneInfo

from dateutil import parser

_LOGGER = logging.getLogger(__name__)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


_CLUB_FRIENDLIES = {
    "en": "Club Friendlies",
    "nl": "Oefenwedstrijd",
    "de": "Vereinsfreundschaftsspiele",
    "es": "Amistosos de clubes",
    "fr": "Matchs amicaux clubs",
    "it": "Amichevoli club",
    "pt": "Amistosos de clubes",
}
_FRIENDLIES = {
    "en": "Friendlies",
    "nl": "Oefenwedstrijden",
    "de": "Freundschaftsspiele",
    "es": "Amistosos",
    "fr": "Matchs amicaux",
    "it": "Amichevoli",
    "pt": "Amistosos",
}
_CLUB_FRIENDLY_KEYS = {
    "friendlies clubs", "friendlies club", "friendly clubs", "friendly club",
    "club friendlies", "club friendly",
}
_FRIENDLY_KEYS = {"friendlies", "friendly"}


def normalize_competition_name(name, lang="en"):
    """Localize provider competition names the same way the card does.

    Mirrors the frontend ``displayCompetitionName`` so the sensor's
    ``league_name`` reads sensibly in automations (e.g. API-Football's
    "Friendlies Clubs" becomes the Dutch "Oefenwedstrijd"). Unknown names are
    returned unchanged."""
    raw = str(name or "").strip()
    if not raw or raw == "N/A":
        return raw
    key = " ".join(raw.lower().replace("_", " ").replace("-", " ").split())
    lang = (lang or "en").split("-")[0].lower()
    if key in _CLUB_FRIENDLY_KEYS:
        return _CLUB_FRIENDLIES.get(lang, _CLUB_FRIENDLIES["en"])
    if key in _FRIENDLY_KEYS:
        return _FRIENDLIES.get(lang, _FRIENDLIES["en"])
    return raw


def extract_error(data):
    """Return a human-readable API-Football error message, or None on success.

    API-Football answers with HTTP 200 even for auth, parameter and quota
    errors, placing the reason in a top-level ``errors`` field. That field is a
    dict of ``field -> message`` (e.g. ``{"token": "..."}``,
    ``{"requests": "You have reached the request limit for the day"}``,
    ``{"rateLimit": "..."}``) or occasionally a list. An empty dict/list means
    the call succeeded."""
    if not isinstance(data, dict):
        return None
    errors = data.get("errors")
    if not errors:
        return None
    if isinstance(errors, dict):
        parts = [str(v) for v in errors.values() if v]
        return "; ".join(parts) if parts else None
    if isinstance(errors, list):
        parts = [str(e) for e in errors if e]
        return "; ".join(parts) if parts else None
    return str(errors)


def _status_state(status_short):
    short = (status_short or "").upper()
    if short in {"NS", "TBD", "PST", "CANC", "ABD", "AWD", "WO"}:
        return "pre"
    if short in {"FT", "AET", "PEN"}:
        return "post"
    if short in {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}:
        return "in"
    return "pre"


def _format_date(hass, value):
    if not value:
        return "N/A"
    try:
        dt = parser.isoparse(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        user_timezone = getattr(getattr(hass, "config", None), "time_zone", None) or "UTC"
        try:
            local_tz = ZoneInfo(user_timezone)
        except Exception:
            local_tz = timezone.utc
        return dt.astimezone(local_tz).strftime("%d-%m-%Y %H:%M")
    except Exception:
        return "N/A"


def _score(value):
    return "N/A" if value is None else str(value)


def _as_int(value):
    """Coerce API-Football numeric fields (may be int, str or None) to int."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _minute(time_info):
    """Return (elapsed, extra) from an API-Football time object.

    API-Football reports pre-match incidents (e.g. a card shown in the tunnel)
    with a negative ``elapsed`` such as -5. That is not a meaningful match
    minute, so it is normalized to None rather than rendered as "-5'"."""
    time_info = _as_dict(time_info)
    elapsed = time_info.get("elapsed")
    if isinstance(elapsed, (int, float)) and elapsed < 0:
        elapsed = None
    return elapsed, time_info.get("extra")


def _minute_text(time_info):
    """Human-readable match minute, including stoppage time (e.g. '90+7')."""
    elapsed, extra = _minute(time_info)
    if elapsed is None:
        return "N/A"
    return f"{elapsed}+{extra}" if extra else f"{elapsed}"


def _event_detail(event):
    event = _as_dict(event)
    player = _as_dict(event.get("player")).get("name", "N/A")
    event_type = event.get("type") or ""
    detail = event.get("detail") or event_type or "Event"
    minute = _minute_text(event.get("time"))
    minute_text = minute if minute == "N/A" else f"{minute}'"
    event_type_lower = event_type.lower()
    detail_lower = detail.lower()
    if event_type_lower == "goal":
        # API-Football uses type "Goal" with detail "Missed Penalty" for a miss,
        # which is NOT a goal — keep "Goal" out of the string so downstream goal
        # detection ignores it.
        if "missed" in detail_lower:
            return f"Penalty - Missed - {minute_text}: {player}"
        if "penalty" in detail_lower:
            # Keep "Goal" in the text so score-change goal detection can attribute
            # the scorer (it matches on the "Goal" token).
            return f"Goal - Penalty - {minute_text}: {player}"
        if "own goal" in detail_lower:
            return f"Goal - {minute_text}: {player} (own goal)"
        return f"Goal - {minute_text}: {player}"
    if event_type_lower == "card":
        if "red" in detail_lower:
            return f"Red Card - {minute_text}: {player}"
        return f"Yellow Card - {minute_text}: {player}"
    return f"{detail} - {minute_text}: {player}"


def _key_event(event):
    event = _as_dict(event)
    team = _as_dict(event.get("team"))
    player = _as_dict(event.get("player"))
    assist = _as_dict(event.get("assist"))
    event_type = event.get("type") or ""
    detail = event.get("detail") or event_type
    elapsed, extra = _minute(event.get("time"))
    minute = f"{elapsed}+{extra}" if elapsed is not None and extra else (str(elapsed) if elapsed is not None else "")
    # A missed penalty has type "Goal" but must not count as a scoring play.
    is_missed_penalty = "missed" in str(detail).lower()
    return {
        "type": event_type,
        "type_text": detail,
        "short_text": detail,
        "clock": minute,
        "minute": minute,
        "team": team.get("name", ""),
        "team_id": team.get("id"),
        "player": player.get("name", ""),
        "athletes": [name for name in [player.get("name", ""), assist.get("name", "")] if name],
        "assist": assist.get("name", ""),
        "scoring_play": event_type.lower() == "goal" and not is_missed_penalty,
    }


def _clean_percent(value):
    if isinstance(value, str):
        return value.replace("%", "").strip()
    return value


def _percent_int(value):
    """Parse an API-Football percentage ("45%") to an int, or None."""
    cleaned = _clean_percent(value)
    try:
        return int(float(cleaned))
    except (TypeError, ValueError):
        return None


def _as_float(value):
    """Coerce a numeric string/number to float, or None."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def process_odds_data(data):
    """Normalize an API-Football /odds response to averaged 1X2 odds.

    Averages the "Match Winner" (home/draw/away) odds across all bookmakers.
    Returns None when no such odds are present, so callers attach it only when
    real data exists (API-Football only carries odds 1-14 days pre-match)."""
    response = data.get("response", []) if isinstance(data, dict) else []
    first = _as_dict(response[0]) if response else {}
    homes, draws, aways = [], [], []
    for bookmaker in (first.get("bookmakers") or []):
        if not isinstance(bookmaker, dict):
            continue
        for bet in (bookmaker.get("bets") or []):
            if not isinstance(bet, dict) or (bet.get("name") or "").lower() != "match winner":
                continue
            for entry in (bet.get("values") or []):
                if not isinstance(entry, dict):
                    continue
                odd = _as_float(entry.get("odd"))
                if odd is None:
                    continue
                label = (entry.get("value") or "").lower()
                if label == "home":
                    homes.append(odd)
                elif label == "draw":
                    draws.append(odd)
                elif label == "away":
                    aways.append(odd)
            break  # one Match Winner market per bookmaker

    def _avg(values):
        return round(sum(values) / len(values), 2) if values else None

    home, draw, away = _avg(homes), _avg(draws), _avg(aways)
    if home is None and draw is None and away is None:
        return None
    return {
        "home": home,
        "draw": draw,
        "away": away,
        "bookmaker_count": max(len(homes), len(draws), len(aways)),
    }


def process_prediction_data(data):
    """Normalize an API-Football /predictions response to a compact prediction.

    Returns None when there is no usable prediction, so callers can attach it
    only when data actually exists."""
    response = data.get("response", []) if isinstance(data, dict) else []
    first = _as_dict(response[0]) if response else {}
    predictions = _as_dict(first.get("predictions"))
    if not predictions:
        return None
    percent = _as_dict(predictions.get("percent"))
    winner = _as_dict(predictions.get("winner"))
    home = _percent_int(percent.get("home"))
    draw = _percent_int(percent.get("draw"))
    away = _percent_int(percent.get("away"))
    advice = predictions.get("advice") or ""
    winner_name = winner.get("name") or ""
    # Nothing worth showing.
    if home is None and draw is None and away is None and not advice and not winner_name:
        return None
    # API-Football returns a neutral placeholder (e.g. 33/33/33 with no winner)
    # for matches that are still too far out or pre-season to predict — that is
    # not a real lean, so don't surface it.
    if not winner_name and home is not None and home == draw == away:
        return None
    return {
        "percent_home": home,
        "percent_draw": draw,
        "percent_away": away,
        "advice": advice,
        "winner_name": winner_name,
        "winner_comment": winner.get("comment") or "",
    }


def process_injuries_data(data, home_team_id=None, away_team_id=None):
    """Normalize an API-Football /injuries response into per-team absentee lists.

    Each entry carries the player, the reason (e.g. an injury description or
    "Suspended") and a ``suspended`` flag. Returns None when neither team has a
    listed absentee, so callers attach it only when data exists."""
    response = data.get("response", []) if isinstance(data, dict) else []
    home, away = [], []
    for item in response or []:
        item = _as_dict(item)
        player = _as_dict(item.get("player"))
        name = player.get("name")
        if not name:
            continue
        reason = player.get("reason") or ""
        entry = {
            "player": name,
            "reason": reason,
            "type": player.get("type") or "",
            "suspended": "suspend" in reason.lower(),
        }
        team_id = _as_dict(item.get("team")).get("id")
        if home_team_id is not None and str(team_id) == str(home_team_id):
            home.append(entry)
        elif away_team_id is not None and str(team_id) == str(away_team_id):
            away.append(entry)
    if not home and not away:
        return None
    return {"injuries_home": home, "injuries_away": away}


# API-Football stat name -> (normalized key, optional value transform).
_STAT_KEY_MAP = {
    "Ball Possession": ("possessionPct", _clean_percent),
    "Total Shots": ("totalShots", None),
    "Shots on Goal": ("shotsOnTarget", None),
    "Fouls": ("foulsCommitted", None),
    "Corner Kicks": ("cornerKicks", None),
    "Offsides": ("offsides", None),
    "Yellow Cards": ("yellowCards", None),
    "Red Cards": ("redCards", None),
    "expected_goals": ("expectedGoals", None),
}


def _normalize_stat_key(name, value):
    entry = _STAT_KEY_MAP.get(name)
    if not entry:
        return None
    key, transform = entry
    return key, (transform(value) if transform else value)


def process_fixture_data(data, hass=None, team_name=None, team_id=None, include_friendlies=True):
    """Normalize API-Football /fixtures responses to Soccer Live's ESPN-shaped model."""
    matches = []
    team_logo = None
    lang = getattr(getattr(hass, "config", None), "language", None) or "en"
    response = data.get("response", []) if isinstance(data, dict) else []
    for item in response or []:
        try:
            item = _as_dict(item)
            fixture = _as_dict(item.get("fixture"))
            league = _as_dict(item.get("league"))
            teams = _as_dict(item.get("teams"))
            goals = _as_dict(item.get("goals"))
            status = _as_dict(fixture.get("status"))
            home = _as_dict(teams.get("home"))
            away = _as_dict(teams.get("away"))
            if not home or not away:
                continue

            league_name = league.get("name", "")
            if not include_friendlies and "friendl" in league_name.lower():
                continue
            league_name_display = normalize_competition_name(league_name, lang)

            selected_team_id = str(team_id or "")
            if selected_team_id and selected_team_id not in {str(home.get("id", "")), str(away.get("id", ""))}:
                continue
            if team_name and not selected_team_id:
                names = {str(home.get("name", "")).lower(), str(away.get("name", "")).lower()}
                if team_name.lower() not in names:
                    continue

            if selected_team_id == str(home.get("id", "")):
                team_logo = home.get("logo") or team_logo
            elif selected_team_id == str(away.get("id", "")):
                team_logo = away.get("logo") or team_logo

            events = [_as_dict(e) for e in (item.get("events") or []) if isinstance(e, dict)]
            match_details = [_event_detail(e) for e in events]
            key_events = [_key_event(e) for e in events]
            state = _status_state(status.get("short"))
            venue = _as_dict(fixture.get("venue"))

            matches.append({
                "event_id": str(fixture.get("id", "")),
                "date_iso": fixture.get("date", ""),
                "date": _format_date(hass, fixture.get("date")),
                "home_id": home.get("id"),
                "away_id": away.get("id"),
                "home_team": home.get("name", "N/A"),
                "away_team": away.get("name", "N/A"),
                "home_abbrev": home.get("code") or home.get("name", "N/A"),
                "away_abbrev": away.get("code") or away.get("name", "N/A"),
                "home_logo": home.get("logo", "N/A"),
                "away_logo": away.get("logo", "N/A"),
                "home_color": "N/A",
                "away_color": "N/A",
                "home_score": _score(goals.get("home")),
                "away_score": _score(goals.get("away")),
                "state": state,
                "status": status.get("long") or status.get("short") or "N/A",
                "period": status.get("short", "N/A"),
                "clock": _minute_text(status) if state == "in" else "N/A",
                "venue": venue.get("name", "N/A"),
                "attendance": fixture.get("attendance", "N/A"),
                "neutral_site": False,
                "league_name": league_name_display or "N/A",
                "league_id": league.get("id"),
                "league_logo": league.get("logo", ""),
                "competition_name": league_name_display or "N/A",
                "season_info": league.get("season", ""),
                "week_number": None,
                "match_details": match_details,
                "key_events": key_events,
                "has_commentary": bool(events),
                "has_stats": False,
                "home_statistics": {},
                "away_statistics": {},
                "broadcasts": [],
                "links": [],
                "provider": "api_football",
            })
        except Exception as err:
            _LOGGER.warning("Skipping malformed API-Football fixture: %s", err)

    return {
        "matches": sorted(matches, key=lambda m: m.get("date_iso") or ""),
        "league_info": _league_info(response),
        "team_name": team_name or "",
        "team_logo": team_logo or "N/A",
        "provider": "api_football",
    }


def _league_info(response):
    seen = set()
    leagues = []
    for item in response or []:
        league = _as_dict(_as_dict(item).get("league"))
        league_id = league.get("id")
        if league_id in seen:
            continue
        seen.add(league_id)
        if league:
            country = league.get("country", "")
            abbreviation = league.get("name", "") if country == "World" else country
            leagues.append({
                "name": league.get("name", ""),
                "abbreviation": abbreviation,
                "startDate": "N/A",
                "endDate": "N/A",
                "logo_href": league.get("logo", "N/A"),
            })
    return leagues


def extract_team_standing(data, team_id):
    """Return a team's league standing as structured data ``{"rank", "points"}``,
    or None when the team isn't in the standings (e.g. friendlies have none).

    Structured fields (rather than a pre-formatted string) let the card format
    and localize the label itself."""
    if team_id is None:
        return None
    response = data.get("response", []) if isinstance(data, dict) else []
    league = _as_dict(_as_dict(response[0]).get("league")) if response else {}
    for group in (league.get("standings", []) or []):
        for entry in (group or []):
            if not isinstance(entry, dict):
                continue
            if str(_as_dict(entry.get("team")).get("id")) == str(team_id):
                rank = entry.get("rank")
                if rank is None:
                    return None
                return {"rank": rank, "points": entry.get("points")}
    return None


def process_standings_data(data):
    response = data.get("response", []) if isinstance(data, dict) else []
    league_block = _as_dict(response[0]).get("league", {}) if response else {}
    league = _as_dict(league_block)
    raw_groups = league.get("standings", []) or []
    standings_groups = []

    for index, group in enumerate(raw_groups, start=1):
        standings = []
        group_name = ""
        for entry in group or []:
            if not isinstance(entry, dict):
                continue
            team = _as_dict(entry.get("team"))
            all_stats = _as_dict(entry.get("all"))
            goals = _as_dict(all_stats.get("goals"))
            group_name = group_name or entry.get("group", "") or f"Group {index}"
            standings.append({
                "rank": entry.get("rank", len(standings) + 1),
                "team_id": team.get("id"),
                "team_name": team.get("name"),
                "team_logo": team.get("logo", "N/A"),
                "points": entry.get("points", "N/A"),
                "games_played": all_stats.get("played", "N/A"),
                "wins": all_stats.get("win", "N/A"),
                "draws": all_stats.get("draw", "N/A"),
                "losses": all_stats.get("lose", "N/A"),
                "goals_for": goals.get("for", "N/A"),
                "goals_against": goals.get("against", "N/A"),
                "goal_difference": entry.get("goalsDiff", "N/A"),
                "form": entry.get("form", ""),
                "zone_color": "",
                "zone_label": entry.get("description", "") or "",
                "zone_abbrev": "",
            })
        if standings:
            standings_groups.append({
                "name": group_name or f"Group {index}",
                "standings": standings,
                "full_table_link": "N/A",
            })

    return {
        "season": str(league.get("season", "N/A")),
        "season_start": None,
        "season_end": None,
        "league_name": league.get("name", "N/A"),
        "league_abbreviation": league.get("country", "N/A"),
        "league_logo": league.get("logo", ""),
        "standings_groups": standings_groups,
        "provider": "api_football",
    }


def process_scorers_data(data):
    response = data.get("response", []) if isinstance(data, dict) else []
    scorers = []
    league_name = ""
    league_logo = ""
    for index, item in enumerate(response or [], start=1):
        item = _as_dict(item)
        player = _as_dict(item.get("player"))
        stats = [_as_dict(s) for s in (item.get("statistics") or []) if isinstance(s, dict)]
        # A player transferred mid-season appears with one statistics entry per
        # club, so totals must be summed across all of them; team/league come
        # from the entry where the player scored the most.
        total_goals = sum(_as_int(_as_dict(s.get("goals")).get("total")) for s in stats)
        total_assists = sum(_as_int(_as_dict(s.get("goals")).get("assists")) for s in stats)
        primary = max(
            stats,
            key=lambda s: _as_int(_as_dict(s.get("goals")).get("total")),
            default={},
        )
        team = _as_dict(primary.get("team"))
        league = _as_dict(primary.get("league"))
        if not league_name:
            league_name = league.get("name", "")
            league_logo = league.get("logo", "")
        scorers.append({
            "rank": index,
            "goals": total_goals,
            "player": player.get("name", ""),
            "short_name": player.get("name", ""),
            "headshot": player.get("photo", ""),
            "team_name": team.get("name", ""),
            "team_logo": team.get("logo", "") or "",
            "assists": total_assists,
            "provider": "api_football",
        })
    return {
        "scorers": scorers,
        "league_name": league_name,
        "league_logo": league_logo,
        "provider": "api_football",
    }


def process_fixture_enrichment(events_data=None, statistics_data=None, lineups_data=None, home_team_id=None, away_team_id=None):
    events = [_as_dict(e) for e in (_as_dict(events_data).get("response", []) or []) if isinstance(e, dict)]
    stats = [_as_dict(s) for s in (_as_dict(statistics_data).get("response", []) or []) if isinstance(s, dict)]
    lineups = [_as_dict(l) for l in (_as_dict(lineups_data).get("response", []) or []) if isinstance(l, dict)]

    out = {
        "match_details": [],
        "key_events": [],
        "home_statistics": {},
        "away_statistics": {},
        "lineup_home": [],
        "lineup_away": [],
        "formation_home": "",
        "formation_away": "",
        "has_stats": bool(stats),
        "has_commentary": bool(events),
    }

    if home_team_id is None and lineups:
        home_team_id = _as_dict(lineups[0].get("team")).get("id")
    if away_team_id is None and len(lineups) > 1:
        away_team_id = _as_dict(lineups[1].get("team")).get("id")

    out["match_details"] = [_event_detail(e) for e in events]
    out["key_events"] = [_key_event(e) for e in events]

    for index, item in enumerate(stats[:2]):
        api_team_id = _as_dict(item.get("team")).get("id")
        team_stats = {}
        for stat in item.get("statistics", []) or []:
            if isinstance(stat, dict):
                name = stat.get("type")
                if name:
                    value = stat.get("value", "N/A")
                    team_stats[name] = value
                    normalized = _normalize_stat_key(name, value)
                    if normalized:
                        normalized_key, normalized_value = normalized
                        team_stats[normalized_key] = normalized_value
        if home_team_id is not None and str(api_team_id) == str(home_team_id):
            out["home_statistics"] = team_stats
        elif away_team_id is not None and str(api_team_id) == str(away_team_id):
            out["away_statistics"] = team_stats
        elif index == 0 and not out["home_statistics"]:
            out["home_statistics"] = team_stats
        elif index == 1 and not out["away_statistics"]:
            out["away_statistics"] = team_stats

    for index, item in enumerate(lineups[:2]):
        api_team_id = _as_dict(item.get("team")).get("id")
        formation = item.get("formation", "")
        players = []
        start_xi = item.get("startXI", []) or []
        subs = item.get("substitutes", []) or []
        for raw_player, is_starter in [(p, True) for p in start_xi] + [(p, False) for p in subs]:
            player = _as_dict(_as_dict(raw_player).get("player"))
            if not player:
                continue
            players.append({
                "name": player.get("name", ""),
                "short_name": player.get("name", ""),
                "jersey": player.get("number", ""),
                "position": player.get("pos", ""),
                "starter": is_starter,
                "headshot": "",
            })
        if home_team_id is not None and str(api_team_id) == str(home_team_id):
            out["lineup_home"] = players
            out["formation_home"] = formation
        elif away_team_id is not None and str(api_team_id) == str(away_team_id):
            out["lineup_away"] = players
            out["formation_away"] = formation
        elif index == 0 and not out["lineup_home"]:
            out["lineup_home"] = players
            out["formation_home"] = formation
        elif index == 1 and not out["lineup_away"]:
            out["lineup_away"] = players
            out["formation_away"] = formation

    return out


def process_team_profile(data):
    """Normalize an API-Football /teams response to a compact club profile."""
    response = data.get("response", []) if isinstance(data, dict) else []
    first = _as_dict(response[0]) if response else {}
    team = _as_dict(first.get("team"))
    if not team:
        return None
    venue = _as_dict(first.get("venue"))
    return {
        "name": team.get("name", ""),
        "logo": team.get("logo", ""),
        "founded": team.get("founded"),
        "country": team.get("country", ""),
        "venue": venue.get("name", ""),
        "venue_city": venue.get("city", ""),
        "venue_capacity": venue.get("capacity"),
    }


def process_coach(data):
    """Return the current coach's name from an API-Football /coachs response.

    The endpoint lists coaches most-recent first; prefer one whose career shows
    this team without an end date, otherwise fall back to the first entry."""
    response = data.get("response", []) if isinstance(data, dict) else []
    for coach in response or []:
        coach = _as_dict(coach)
        for spell in (coach.get("career") or []):
            spell = _as_dict(spell)
            if spell.get("end") in (None, "") and coach.get("name"):
                return coach.get("name")
    first = _as_dict(response[0]) if response else {}
    return first.get("name") or ""


_POSITION_ORDER = {"Goalkeeper": 0, "Defender": 1, "Midfielder": 2, "Attacker": 3}


def process_squad(data):
    """Normalize an API-Football /players/squads response to a player list,
    sorted by position (GK, DEF, MID, ATT) then shirt number."""
    response = data.get("response", []) if isinstance(data, dict) else []
    first = _as_dict(response[0]) if response else {}
    players = []
    for player in (first.get("players") or []):
        player = _as_dict(player)
        name = player.get("name")
        if not name:
            continue
        players.append({
            "name": name,
            "number": player.get("number"),
            "position": player.get("position", ""),
            "age": player.get("age"),
            "photo": player.get("photo", ""),
        })
    players.sort(key=lambda p: (
        _POSITION_ORDER.get(p["position"], 9),
        p["number"] if isinstance(p["number"], int) else 999,
    ))
    return players


def process_transfers(data, team_id, limit=15):
    """Flatten an API-Football /transfers response to recent transfers for the
    given team (most recent first), each tagged in/out relative to the team."""
    response = data.get("response", []) if isinstance(data, dict) else []
    items = []
    for entry in response or []:
        entry = _as_dict(entry)
        player = _as_dict(entry.get("player")).get("name", "")
        for transfer in (entry.get("transfers") or []):
            transfer = _as_dict(transfer)
            teams = _as_dict(transfer.get("teams"))
            team_in = _as_dict(teams.get("in"))
            team_out = _as_dict(teams.get("out"))
            if str(team_in.get("id")) == str(team_id):
                direction = "in"
            elif str(team_out.get("id")) == str(team_id):
                direction = "out"
            else:
                continue
            items.append({
                "player": player,
                "date": transfer.get("date") or "",
                "type": transfer.get("type") or "",
                "from": team_out.get("name", ""),
                "to": team_in.get("name", ""),
                "direction": direction,
            })
    items.sort(key=lambda x: x["date"], reverse=True)
    return items[:limit]
