import logging
_LOGGER = logging.getLogger(__name__)
from dateutil import parser
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta, timezone

def _as_dict(v):
    """Return v if it is a dict, otherwise return {}.  Guards against ESPN returning
    null or a scalar where an object is expected (e.g. "team": null, "league": "N/A")."""
    return v if isinstance(v, dict) else {}

def _score_value(value):
    """Normalize an ESPN competitor score to a plain scalar.

    ESPN usually returns a string like "2", but for in-progress matches the
    score can arrive as an object ({"value": 2, "displayValue": "2"}). Passing
    that straight through renders as "[object Object]" in the cards, so extract
    the display value here."""
    if isinstance(value, dict):
        display = value.get("displayValue")
        if display is not None:
            return display
        inner = value.get("value")
        return inner if inner is not None else "N/A"
    return value if value is not None else "N/A"

def process_league_data(data, hass=None):
    leagues_data = data.get("leagues", []) or []
    league_info = []
    for league in leagues_data:
        if not isinstance(league, dict):
            _LOGGER.warning("Skipping malformed league entry (not a dict)")
            continue
        season = _as_dict(league.get("season"))
        logos = [x for x in (league.get("logos") or []) if isinstance(x, dict)]
        league_info.append({
            "name": league.get("name", ""),
            "abbreviation": league.get("abbreviation", "N/A"),
            "startDate": _parse_date(hass, season.get("startDate", "N/A"), show_time=False),
            "endDate": _parse_date(hass, season.get("endDate", "N/A"), show_time=False),
            "logo_href": logos[0].get("href", "N/A") if logos else "N/A",
        })
    return league_info

def get_season_slug_or_displayname(match):
    season_data = _as_dict(match.get("season"))

    # Check for 'slug' first
    slug = season_data.get("slug")
    if slug:
        return slug
    
    # Fall back to 'displayName' if no slug
    display_name = season_data.get("displayName")
    return display_name
    
# Curated ESPN CDN logo overrides for leagues where id != logo file number.
# Avoids guessing with 500/{id}.png (unreliable) while keeping logos for
# the most common international competitions.
_LEAGUE_LOGO_OVERRIDES = {
    "606":   "https://a.espncdn.com/i/leaguelogos/soccer/500/4.png",      # FIFA World Cup
    "775":   "https://a.espncdn.com/i/leaguelogos/soccer/500/2.png",      # UEFA Champions League
    "776":   "https://a.espncdn.com/i/leaguelogos/soccer/500/2310.png",   # UEFA Europa League
    "20296": "https://a.espncdn.com/i/leaguelogos/soccer/500/20296.png",  # UEFA Conference League
    "781":   "https://a.espncdn.com/i/leaguelogos/soccer/500/74.png",     # UEFA Euro
    "780":   "https://a.espncdn.com/i/leaguelogos/soccer/500/83.png",     # Copa America
}

def _first_logo_href(obj):
    logos = (obj or {}).get("logos", []) or []
    return logos[0].get("href", "") if logos else ""

def process_match_data(data, hass, team_name=None, team_id=None, next_match_only=False, start_date=None, end_date=None, recent_match_hours=24):
    try:
        matches_data = data.get("events", [])
        league_info = process_league_data(data, hass)
        matches = []
        team_logo = None

        # Build id-keyed lookup so per-match league resolution works for multi-league
        # endpoints like /all/scoreboard (which has many leagues in the top-level array)
        top_leagues = data.get("leagues", []) or []
        leagues_by_id = {}
        for _lg in top_leagues:
            if not isinstance(_lg, dict):
                continue
            _lid = str(_lg.get("id", "") or "")
            if _lid:
                leagues_by_id[_lid] = {
                    "name": _lg.get("name") or _lg.get("abbreviation") or "",
                    "logo": _first_logo_href(_lg),
                }
        # For single-league endpoints use the name directly as before
        top_league_name = top_leagues[0].get("name", "N/A") if len(top_leagues) == 1 and isinstance(top_leagues[0], dict) else "N/A"

        # Interpret user-supplied date strings in the HA timezone so that a match
        # at 00:30 local time is not filtered by the wrong UTC day boundary.
        _tz = ZoneInfo(hass.config.time_zone) if (hass and hass.config.time_zone) else timezone.utc
        if isinstance(start_date, str):
            start_date = datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=_tz).astimezone(timezone.utc)
        if isinstance(end_date, str):
            end_date = datetime.strptime(end_date, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=_tz).astimezone(timezone.utc)

        team_id_str = str(team_id) if team_id else None

        for match in (matches_data or []):
            if not isinstance(match, dict):
                _LOGGER.warning("Skipping malformed match entry (not a dict)")
                continue
            # When team_id is available prefer ID matching (done after extracting competitors).
            # Fall back to name pre-filter only when we have no ID.
            if team_name and not team_id_str:
                match_name = match.get("name", "").lower()
                if team_name.lower() not in match_name:
                    continue

            match_date_str = match.get("date", "")
            try:
                match_date = parser.isoparse(match_date_str).astimezone(timezone.utc) if match_date_str else None
                if start_date and match_date and match_date < start_date:
                    continue
                if end_date and match_date and match_date > end_date:
                    continue

                # Only for mixed sensor type
                season_info = get_season_slug_or_displayname(match)
                week_number = _as_dict(match.get("week")).get("number")

                competitions = [c for c in (match.get("competitions", []) or []) if isinstance(c, dict)]
                comp = competitions[0] if competitions else {}
                comp_league = _as_dict(comp.get("league"))
                # team schedule endpoint (/all/teams/{id}/schedule) puts league at event level
                event_league = _as_dict(match.get("league"))
                league_id = str(comp_league.get("id", "") or event_league.get("id", "") or "")

                # For /all/scoreboard the league id is encoded in the competition uid:
                # e.g. "s:600~l:ned.1~e:700001" -> league_id = "ned.1"
                if not league_id:
                    comp_uid = comp.get("uid", "") or match.get("uid", "") or ""
                    for _part in comp_uid.split("~"):
                        if _part.startswith("l:"):
                            league_id = _part[2:]
                            break

                # /all/scoreboard: comp.altGameNote = "FIFA World Cup, Group F" -> league name
                alt_note = (comp.get("altGameNote") or "").strip()
                league_name_from_note = alt_note.split(",")[0].strip() if alt_note else ""

                league_name = (
                    comp_league.get("displayName")
                    or comp_league.get("name")
                    or event_league.get("displayName")
                    or event_league.get("name")
                    or (leagues_by_id.get(league_id, {}).get("name") if league_id else None)
                    or league_name_from_note
                    or (top_league_name if top_league_name != "N/A" else None)
                    or "N/A"
                )
                league_logo = (
                    _first_logo_href(comp_league)
                    or _first_logo_href(event_league)
                    or (leagues_by_id.get(league_id, {}).get("logo") if league_id else None)
                    or ""
                )
                if not league_logo and league_id:
                    league_logo = _LEAGUE_LOGO_OVERRIDES.get(league_id, "")
                _LOGGER.debug(
                    "league_resolve: event=%s uid=%s league_id=%s comp_league=%s -> name=%s",
                    match.get("id"), comp.get("uid", match.get("uid", "")), league_id, comp_league, league_name
                )

                competitors = [c for c in (comp.get("competitors", []) or []) if isinstance(c, dict)]
                if len(competitors) < 2:
                    _LOGGER.debug(f"Skipping match with fewer than 2 competitors: {match.get('name', 'unknown')}")
                    continue

                # Use the homeAway field to identify home and away; fall back to index order
                home_comp = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away_comp = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

                home_team_data = _as_dict(home_comp.get("team"))
                if team_id_str:
                    _home_id = str(home_team_data.get("id", ""))
                    _away_id = str(_as_dict(away_comp.get("team")).get("id", ""))
                    if _home_id != team_id_str and _away_id != team_id_str:
                        continue
                home_team = home_team_data.get("displayName", "N/A")
                home_logo = home_team_data.get("logo", None)
                if not home_logo:
                    home_logos = [x for x in (home_team_data.get("logos") or []) if isinstance(x, dict)]
                    home_logo = home_logos[0].get("href", "N/A") if home_logos else "N/A"
                home_form = home_comp.get("form") or ""
                home_score = _score_value(home_comp.get("score", "N/A"))
                home_statistics = _get_statistics(home_comp)

                away_team_data = _as_dict(away_comp.get("team"))
                away_team = away_team_data.get("displayName", "N/A")
                away_logo = away_team_data.get("logo", None)
                if not away_logo:
                    away_logos = [x for x in (away_team_data.get("logos") or []) if isinstance(x, dict)]
                    away_logo = away_logos[0].get("href", "N/A") if away_logos else "N/A"
                away_form = away_comp.get("form") or ""
                away_score = _score_value(away_comp.get("score", "N/A"))
                away_statistics = _get_statistics(away_comp)

                # Prefer competition-level status (more reliable for live clock/period);
                # fall back to event-level status for basic pre/post state.
                status_obj = _as_dict(comp.get("status") or match.get("status"))
                status_type = _as_dict(status_obj.get("type"))
                match_state = status_type.get("state", "N/A")
                match_status = status_type.get("description", "N/A")
                status_detail = status_type.get("detail", "N/A")
                clock = status_obj.get("displayClock", "N/A")
                period = status_obj.get("period", "N/A")

                venue_obj = _as_dict(comp.get("venue"))
                venue = venue_obj.get("fullName", "N/A")
                venue_address = _as_dict(venue_obj.get("address"))
                venue_city = venue_address.get("city", "N/A")
                venue_country = venue_address.get("country", "N/A")

                home_abbrev = home_team_data.get("abbreviation", "N/A")
                home_color = home_team_data.get("color", "N/A")
                home_record = _get_record(home_comp)
                home_top_scorer = _get_top_scorer(home_comp)
                home_record_summary = home_comp.get("recordSummary", "")
                home_standing_summary = home_comp.get("standingSummary", "")

                away_abbrev = away_team_data.get("abbreviation", "N/A")
                away_color = away_team_data.get("color", "N/A")
                away_record = _get_record(away_comp)
                away_top_scorer = _get_top_scorer(away_comp)
                away_record_summary = away_comp.get("recordSummary", "")
                away_standing_summary = away_comp.get("standingSummary", "")

                broadcast = _get_broadcast(comp)
                broadcasts = _get_broadcasts(comp)
                neutral_site = comp.get("neutralSite", False)
                tickets_available = comp.get("ticketsAvailable", False)
                attendance = comp.get("attendance", 0)
                has_stats = comp.get("boxscoreAvailable", False)
                has_commentary = comp.get("playByPlayAvailable", False)
                match_links = _get_links(comp)

                match_details = _get_details(comp.get("details", []))

                if team_name and (team_name.lower() in home_team.lower() or team_name.lower() in away_team.lower()):
                    team_logo = home_logo if team_name.lower() in home_team.lower() else away_logo

                matches.append({
                    "event_id": match.get("id"),
                    "date": _parse_date(hass, match.get("date")),
                    "date_iso": match.get("date", ""),
                    "season_info": season_info,
                    "week_number": week_number,
                    "league_name": league_name,
                    "league_logo": league_logo,
                    "home_team": home_team,
                    "home_abbrev": home_abbrev,
                    "home_color": home_color,
                    "home_logo": home_logo,
                    "home_form": home_form,
                    "home_score": home_score,
                    "home_statistics": home_statistics,
                    "home_record": home_record,
                    "home_top_scorer": home_top_scorer,
                    "home_record_summary": home_record_summary,
                    "home_standing_summary": home_standing_summary,
                    "away_team": away_team,
                    "away_abbrev": away_abbrev,
                    "away_color": away_color,
                    "away_logo": away_logo,
                    "away_form": away_form,
                    "away_score": away_score,
                    "away_statistics": away_statistics,
                    "away_record": away_record,
                    "away_top_scorer": away_top_scorer,
                    "away_record_summary": away_record_summary,
                    "away_standing_summary": away_standing_summary,
                    "state": match_state,
                    "status": match_status,
                    "status_detail": status_detail,
                    "clock": clock,
                    "period": period,
                    "venue": venue,
                    "venue_city": venue_city,
                    "venue_country": venue_country,
                    "broadcast": broadcast,
                    "broadcasts": broadcasts,
                    "neutral_site": neutral_site,
                    "tickets_available": tickets_available,
                    "attendance": attendance,
                    "has_stats": has_stats,
                    "has_commentary": has_commentary,
                    "links": match_links,
                    "match_details": match_details,
                })
            except Exception as _exc:
                _LOGGER.warning(f"Skipping match {match.get('id', 'unknown')} due to parse error: {_exc}")

        if next_match_only:
            # Priority 1: Live matches
            live_matches = [m for m in matches if m["state"] == "in"]
            if live_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "All matches",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [live_matches[0]]
                }

            # Priority 2: Recently finished matches (within the configured window, default 48h)
            # ESPN returns events in chronological order, so [-1] is the most recent.
            recent_finished_matches = [m for m in matches
                if m["state"] == "post" and is_within_recent_window(m["date"], recent_match_hours)
            ]

            if recent_finished_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "All matches",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [recent_finished_matches[-1]]
                }

            # Priority 3: Upcoming matches
            upcoming_matches = [m for m in matches if m["state"] == "pre"]
            if upcoming_matches:
                return {
                    "league_info": league_info,
                    "team_name": team_name if team_name else "All matches",
                    "team_logo": team_logo if team_logo else "N/A",
                    "matches": [upcoming_matches[0]]
                }

            # Off-season: no live/recent/upcoming match — return empty so sensor
            # does not fall back to the full season list (oldest match first = wrong).
            return {
                "league_info": league_info,
                "team_name": team_name if team_name else "All matches",
                "team_logo": team_logo if team_logo else "N/A",
                "matches": []
            }

        return {
            "league_info": league_info,
            "team_name": team_name if team_name else "All matches",
            "team_logo": team_logo if team_logo else "N/A",
            "matches": matches
        }

    except Exception as e:
        _LOGGER.error(f"Error processing match data: {e}")
        return {
            "league_info": [],
            "team_name": team_name if team_name else "All matches",
            "team_logo": "N/A",
            "matches": []
        }

def is_within_recent_window(end_time, hours=24):
    """Return True if the match kickoff happened within the last `hours`."""
    try:
        if isinstance(end_time, str):
            # The stored string is local time formatted by _parse_date(); compare as naive
            end_time_dt = datetime.strptime(end_time, "%d-%m-%Y %H:%M")
        elif isinstance(end_time, datetime):
            end_time_dt = end_time.replace(tzinfo=None)
        else:
            raise ValueError("Expected a string or datetime value")
        current_time = datetime.now()
        # end_time is the kickoff; add 2 h for typical match duration so the window
        # is measured from the approximate end of the match, not the start.
        return current_time - end_time_dt <= timedelta(hours=hours + 2)
    except Exception as e:
        _LOGGER.error(f"Error calculating recent interval ({hours}h): {e}")
        return False

# Backwards-compat alias
def is_within_last_48_hours(end_time):
    return is_within_recent_window(end_time, 48)

def _get_statistics(competitor):
    statistics = {}
    stats = competitor.get("statistics", []) or []
    for stat in stats:
        if not isinstance(stat, dict):
            continue
        stat_name = stat.get("name", "Unknown")
        stat_value = stat.get("displayValue", "N/A")
        statistics[stat_name] = stat_value
    return statistics

def _get_record(competitor):
    """Return the team's season record, e.g. '14-6-14'."""
    records = [r for r in (competitor.get("records", []) or []) if isinstance(r, dict)]
    if records:
        return records[0].get("summary", "")
    return ""

def _get_top_scorer(competitor):
    """Return the team's top scorer as {name, short_name, value}."""
    leaders = competitor.get("leaders", []) or []
    for ldr in leaders:
        if not isinstance(ldr, dict):
            continue
        if ldr.get("name") == "goals":
            tops = [t for t in (ldr.get("leaders", []) or []) if isinstance(t, dict)]
            if tops:
                t = tops[0]
                athlete = _as_dict(t.get("athlete"))
                return {
                    "name": athlete.get("displayName", ""),
                    "short_name": athlete.get("shortName", ""),
                    "value": t.get("displayValue", ""),
                }
    return None

def _get_broadcast(competition):
    """Returns the first broadcast channel name (backwards-compatible)."""
    gbs = [g for g in (competition.get("geoBroadcasts", []) or []) if isinstance(g, dict)]
    if gbs:
        media = _as_dict(gbs[0].get("media"))
        return media.get("shortName", "")
    return ""

def _get_broadcasts(competition):
    """Returns all broadcast channel names from geoBroadcasts."""
    gbs = competition.get("geoBroadcasts", []) or []
    channels = []
    for gb in gbs:
        if not isinstance(gb, dict):
            continue
        name = _as_dict(gb.get("media")).get("shortName", "")
        if name and name not in channels:
            channels.append(name)
    return channels

def _get_links(competition):
    """Extract compact links dict from competition.links for stats/commentary/video."""
    links_raw = competition.get("links", []) or []
    result = {}
    key_map = {
        "summary":     ["summary", "gamecenter"],
        "commentary":  ["commentary", "playbyplay"],
        "stats":       ["boxscore", "stats"],
        "video":       ["video", "highlights"],
    }
    for link in links_raw:
        if not isinstance(link, dict):
            continue
        rel = [r.lower() for r in (link.get("rel") or [])]
        href = link.get("href", "")
        if not href:
            continue
        for key, patterns in key_map.items():
            if key not in result and any(p in rel for p in patterns):
                result[key] = href
    return result

def process_summary_data(data):
    """Extract lineups, formations, key events, and head-to-head data from summary.
    Return a dict with lineup_home, lineup_away, formation_home, formation_away,
    key_events, and head_to_head."""
    out = {
        "lineup_home": [],
        "lineup_away": [],
        "formation_home": "",
        "formation_away": "",
        "key_events": [],
        "head_to_head": [],
    }
    # Each section is isolated so a single malformed subfield (e.g. a null
    # roster entry) cannot wipe out the other, valid sections.
    try:
        rosters = data.get("rosters", []) or []
        for r in rosters:
            if not isinstance(r, dict):
                continue
            home_away = r.get("homeAway", "")
            formation = r.get("formation", "")
            roster = r.get("roster", []) or []
            players = []
            for p in roster:
                if not isinstance(p, dict):
                    continue
                a = _as_dict(p.get("athlete"))
                players.append({
                    "name": a.get("displayName", ""),
                    "short_name": a.get("shortName", ""),
                    "jersey": p.get("jersey", ""),
                    "position": _as_dict(p.get("position")).get("abbreviation", ""),
                    "starter": p.get("starter", False),
                    "headshot": _as_dict(a.get("headshot")).get("href", ""),
                })
            if home_away == "home":
                out["lineup_home"] = players
                out["formation_home"] = formation
            elif home_away == "away":
                out["lineup_away"] = players
                out["formation_away"] = formation
    except Exception as e:
        _LOGGER.warning(f"Error processing summary lineups: {e}")

    try:
        key_events = data.get("keyEvents", []) or []
        for ev in key_events:
            if not isinstance(ev, dict):
                continue
            t = _as_dict(ev.get("type"))
            clock = _as_dict(ev.get("clock")).get("displayValue", "")
            team = _as_dict(ev.get("team")).get("displayName", "")
            participants = ev.get("participants", []) or []
            athletes = []
            for p in participants:
                if not isinstance(p, dict):
                    continue
                athletes.append(_as_dict(p.get("athlete")).get("displayName", ""))
            out["key_events"].append({
                "type": t.get("type", ""),
                "type_text": t.get("text", ""),
                "short_text": ev.get("shortText", ""),
                "clock": clock,
                "team": team,
                "athletes": athletes,
                "scoring_play": ev.get("scoringPlay", False),
            })
    except Exception as e:
        _LOGGER.warning(f"Error processing summary key events: {e}")

    try:
        # The Team card shows at most 8 h2h matches and does not use logos;
        # limit to 10 entries and omit home_logo/away_logo to stay well
        # under the 16384-byte recorder payload limit.
        H2H_MAX = 10
        h2h = data.get("headToHeadGames", []) or []
        for game in h2h:
            if len(out["head_to_head"]) >= H2H_MAX:
                break
            if not isinstance(game, dict):
                continue
            events = game.get("events", []) or []
            for e in events:
                if len(out["head_to_head"]) >= H2H_MAX:
                    break
                if not isinstance(e, dict):
                    continue
                comps = [c for c in (e.get("competitions", []) or []) if isinstance(c, dict)]
                comp = comps[0] if comps else {}
                competitors = [c for c in (comp.get("competitors", []) or []) if isinstance(c, dict)]
                if len(competitors) < 2:
                    continue
                home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                out["head_to_head"].append({
                    "date": e.get("date", ""),
                    "home_team": _as_dict(home_c.get("team")).get("displayName", ""),
                    "home_score": _score_value(home_c.get("score", "")),
                    "away_team": _as_dict(away_c.get("team")).get("displayName", ""),
                    "away_score": _score_value(away_c.get("score", "")),
                })
    except Exception as e:
        _LOGGER.warning(f"Error processing summary head-to-head: {e}")

    try:
        # Recent form: boxscore.participants[].statistics contains lastFiveGames
        for participant in _as_dict(data.get("boxscore")).get("players", []) or []:
            if not isinstance(participant, dict):
                continue
            home_away = participant.get("homeAway", "")
            stats = participant.get("statistics", []) or []
            form_key = "last_five_home" if home_away == "home" else "last_five_away"
            for stat_group in stats:
                if not isinstance(stat_group, dict):
                    continue
                for stat in (stat_group.get("stats", []) or []):
                    if isinstance(stat, dict) and stat.get("name") == "lastFiveGames":
                        out[form_key] = stat.get("displayValue", "")
                        break
    except Exception as e:
        _LOGGER.warning(f"Error processing summary recent form: {e}")

    return out

def process_news_data(data):
    articles = []
    items = data.get("articles", []) or []
    for a in items:
        try:
            images = a.get("images", []) or []
            img_obj = images[0] if images else {}
            img = img_obj.get("url", "")
            img_caption = img_obj.get("caption", "")
            img_credit = img_obj.get("credit", "")

            categories = a.get("categories", []) or []
            tags = []
            league_name = ""
            for c in categories:
                desc = c.get("description", "") or ""
                if c.get("type") == "league" and not league_name:
                    league_name = desc or (c.get("league", {}) or {}).get("description", "")
                if desc and desc not in tags:
                    tags.append(desc)

            byline = ""
            for contributor in (a.get("contributors", []) or []):
                name = contributor.get("name", "") or (contributor.get("athlete", {}) or {}).get("displayName", "")
                if name:
                    byline = name
                    break

            articles.append({
                "headline": a.get("headline", ""),
                "description": a.get("description", ""),
                "byline": byline,
                "published": a.get("published", ""),
                "last_modified": a.get("lastModified", ""),
                "image": img,
                "image_caption": img_caption,
                "image_credit": img_credit,
                "link": (a.get("links", {}) or {}).get("web", {}).get("href", "") or a.get("link", ""),
                "category": league_name,
                "tags": tags[:5],
                "type": a.get("type", ""),
                "premium": a.get("premium", False),
            })
        except Exception as e:
            _LOGGER.warning(f"Skipping malformed news article: {e}")
    return articles

def _get_details(details):
    events = []
    for detail in (details or []):
        if not isinstance(detail, dict):
            continue
        event_type = _as_dict(detail.get("type")).get("text", "Unknown")
        clock = _as_dict(detail.get("clock")).get("displayValue", "N/A")
        athletes = [a.get("displayName", "Unknown") for a in (detail.get("athletesInvolved") or []) if isinstance(a, dict)]
        athletes_str = ", ".join(athletes) if athletes else "N/A"
        team_abbr = _as_dict(detail.get("team")).get("abbreviation", "")
        team_str = f" [{team_abbr}]" if team_abbr else ""
        events.append(f"{event_type}{team_str} - {clock}: {athletes_str}")
    return events

def process_scorers_data(data):
    """Extracts top scorers list from ESPN /leaders endpoint."""
    scorers = []
    for section in (data.get("leaders", []) or []):
        try:
            if "goal" not in section.get("name", "").lower():
                continue
            for entry in (section.get("leaders", []) or []):
                try:
                    athlete = entry.get("athlete", {}) or {}
                    team = entry.get("team", {}) or {}
                    scorers.append({
                        "rank": entry.get("rank", len(scorers) + 1),
                        "goals": entry.get("displayValue", "0"),
                        "player": athlete.get("displayName", ""),
                        "short_name": athlete.get("shortName", ""),
                        "headshot": (athlete.get("headshot", {}) or {}).get("href", ""),
                        "team_name": team.get("displayName", ""),
                        "team_logo": team.get("logo", "") or "",
                    })
                except Exception as e:
                    _LOGGER.warning(f"Skipping malformed scorer entry: {e}")
            break
        except Exception as e:
            _LOGGER.warning(f"Skipping malformed leaders section: {e}")
    return scorers


def _parse_date(hass, date_str, show_time=True):
    try:
        # Fall back to UTC when hass or its configured time zone is unavailable
        # (e.g. during tests or very early startup).
        user_timezone = getattr(getattr(hass, "config", None), "time_zone", None) or "UTC"
        dt = parser.isoparse(date_str)
        parsed_date = dt.astimezone(timezone.utc) if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
        try:
            local_tz = ZoneInfo(user_timezone)
        except Exception:
            local_tz = timezone.utc
        local_date = parsed_date.astimezone(local_tz)

        if show_time:
            return local_date.strftime("%d-%m-%Y %H:%M")
        else:
            return local_date.strftime("%d-%m-%Y")
    except (ValueError, TypeError) as e:

        return "N/A"
