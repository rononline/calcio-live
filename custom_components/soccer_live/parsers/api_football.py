import logging
from datetime import timezone
from zoneinfo import ZoneInfo

from dateutil import parser

_LOGGER = logging.getLogger(__name__)


def _as_dict(value):
    return value if isinstance(value, dict) else {}


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
        if "penalty" in detail_lower:
            return f"Penalty - Scored - {minute_text}: {player}"
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
        "scoring_play": event_type.lower() == "goal",
    }


def _clean_percent(value):
    if isinstance(value, str):
        return value.replace("%", "").strip()
    return value


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
                "clock": status.get("elapsed") if state == "in" else "N/A",
                "venue": venue.get("name", "N/A"),
                "attendance": fixture.get("attendance", "N/A"),
                "neutral_site": False,
                "league_name": league_name or "N/A",
                "league_logo": league.get("logo", ""),
                "competition_name": league_name or "N/A",
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
        first_stats = stats[0] if stats else {}
        team = _as_dict(first_stats.get("team"))
        league = _as_dict(first_stats.get("league"))
        goals = _as_dict(first_stats.get("goals"))
        if not league_name:
            league_name = league.get("name", "")
            league_logo = league.get("logo", "")
        scorers.append({
            "rank": index,
            "goals": goals.get("total", "0"),
            "player": player.get("name", ""),
            "short_name": player.get("name", ""),
            "headshot": player.get("photo", ""),
            "team_name": team.get("name", ""),
            "team_logo": team.get("logo", "") or "",
            "assists": goals.get("assists", "N/A"),
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
