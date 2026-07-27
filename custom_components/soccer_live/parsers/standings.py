import logging
_LOGGER = logging.getLogger(__name__)
from dateutil import parser
from datetime import datetime

def _as_dict(v):
    return v if isinstance(v, dict) else {}

def standings_data(data):
    standings_list = []

    for child in (data.get("children", []) or []):
        if not isinstance(child, dict):
            _LOGGER.warning("Skipping malformed standings child (not a dict)")
            continue
        standings_entries = (child.get("standings") or {}).get("entries", []) or []
        standings = []

        for index, entry in enumerate(standings_entries, start=1):
            if not isinstance(entry, dict):
                _LOGGER.warning("Skipping malformed standings entry (not a dict)")
                continue
            try:
                team = _as_dict(entry.get("team"))
                raw_stats = entry.get("stats") or []
                stats = {s["name"]: s["displayValue"] for s in raw_stats if isinstance(s, dict) and "name" in s}

                note = _as_dict(entry.get("note"))
                rank = note.get("rank", index)
                zone_color = note.get("color", "")
                zone_label = note.get("description", "")
                zone_abbrev = note.get("abbreviation", "")

                logos = [x for x in (team.get("logos") or []) if isinstance(x, dict)]
                team_logo = logos[0].get("href", "N/A") if logos else "N/A"

                standings.append({
                    "rank": rank,
                    "team_id": team.get("id"),
                    "team_name": team.get("displayName"),
                    "team_logo": team_logo,
                    "points": stats.get("points", "N/A"),
                    "games_played": stats.get("gamesPlayed", "N/A"),
                    "wins": stats.get("wins", "N/A"),
                    "draws": stats.get("ties", "N/A"),
                    "losses": stats.get("losses", "N/A"),
                    "goals_for": stats.get("pointsFor", "N/A"),
                    "goals_against": stats.get("pointsAgainst", "N/A"),
                    "goal_difference": stats.get("pointDifferential", "N/A"),
                    "zone_color": f"#{zone_color}" if zone_color else "",
                    "zone_label": zone_label,
                    "zone_abbrev": zone_abbrev,
                })
            except Exception as e:
                _LOGGER.warning(f"Skipping standings entry due to parse error: {e}")

        child_standings = child.get("standings") or {}
        links = child_standings.get("links") or []
        full_table_link = links[0].get("href", "N/A") if links and isinstance(links[0], dict) else "N/A"

        standings_list.append({
            "name": child.get("name", "Unknown"),
            "standings": standings,
            "full_table_link": full_table_link
        })

    try:
        # ESPN exposes season as either a "seasons" array or a singular "season" object
        seasons_data = data.get("seasons") or []
        if not seasons_data:
            singular = data.get("season")
            if isinstance(singular, dict):
                seasons_data = [singular]
        current_year = datetime.now().year
        current_season = (
            next((s for s in seasons_data if isinstance(s, dict) and s.get("year") == current_year), None)
            or next((s for s in seasons_data if isinstance(s, dict) and s.get("year") == current_year - 1), None)
            or (seasons_data[-1] if seasons_data and isinstance(seasons_data[-1], dict) else None)
        )

        season_display_name = current_season.get("displayName", "N/A") if current_season else "N/A"
        season_start = _parse_date(current_season.get("startDate", "N/A")) if current_season else None
        season_end = _parse_date(current_season.get("endDate", "N/A")) if current_season else None

        # ESPN puts name/abbreviation at the top level for some endpoints and under leagues[0]
        _leagues = [x for x in (data.get("leagues") or []) if isinstance(x, dict)]
        _first_league = _leagues[0] if _leagues else {}
        league_name = data.get("name") or _first_league.get("name", "N/A") or "N/A"
        league_abbreviation = data.get("abbreviation") or _first_league.get("abbreviation", "N/A") or "N/A"

        logo_sources = (
            data.get("logos")
            or (_first_league.get("logos") if _first_league else None)
            or (data.get("sport") or {}).get("logos")
            or []
        )
        valid_logos = [x for x in logo_sources if isinstance(x, dict)]
        league_logo = valid_logos[0].get("href", "") if valid_logos else ""
    except Exception as e:
        _LOGGER.error(f"Error extracting standings metadata: {e}")
        season_display_name = "N/A"
        season_start = None
        season_end = None
        league_name = "N/A"
        league_abbreviation = "N/A"
        league_logo = ""

    return {
        "season": season_display_name,
        "season_start": season_start,
        "season_end": season_end,
        "league_name": league_name,
        "league_abbreviation": league_abbreviation,
        "league_logo": league_logo,
        "standings_groups": standings_list
    }


def _parse_date(date_str):
    try:
        parsed_date = parser.isoparse(date_str)
        return parsed_date.strftime("%d-%m-%Y")
    except (ValueError, TypeError) as e:
        _LOGGER.error(f"Error parsing date {date_str}: {e}")
        return None
