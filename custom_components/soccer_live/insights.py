"""Provider-neutral derived insights for Soccer Live sensors."""

from __future__ import annotations

import re
from datetime import datetime, timezone


def _present(value) -> bool:
    if value in (None, "", [], {}):
        return False
    if isinstance(value, str):
        return value.strip().casefold() not in {"n/a", "unknown", "none", "null", "-"}
    return True


def match_completeness(match: dict | None) -> dict:
    """Describe which commonly useful parts of a match payload are available."""
    match = match or {}
    checks = {
        "identity": bool(match.get("event_id") and match.get("date_iso")),
        "teams": bool(match.get("home_team") and match.get("away_team")),
        "competition": _present(match.get("competition_name") or match.get("league_name")),
        "venue": _present(match.get("venue")),
        "score": match.get("state") == "pre" or (
            _present(match.get("home_score")) and _present(match.get("away_score"))
        ),
        "timeline": bool(match.get("key_events")),
        "lineup": bool(match.get("lineup_home") or match.get("lineup_away")),
        "statistics": bool(
            match.get("has_stats")
            or match.get("home_statistics")
            or match.get("away_statistics")
        ),
        "head_to_head": bool(match.get("head_to_head")),
        "prematch": bool(
            match.get("prediction")
            or match.get("odds")
            or match.get("injuries_home")
            or match.get("injuries_away")
        ),
    }
    weights = {
        "identity": 15,
        "teams": 15,
        "competition": 10,
        "venue": 5,
        "score": 10,
        "timeline": 10,
        "lineup": 15,
        "statistics": 10,
        "head_to_head": 5,
        "prematch": 5,
    }
    score = sum(weights[key] for key, available in checks.items() if available)
    level = "excellent" if score >= 85 else "good" if score >= 65 else "partial" if score >= 40 else "limited"
    return {
        "score": score,
        "level": level,
        "available": [key for key, available in checks.items() if available],
        "missing": [key for key, available in checks.items() if not available],
    }


def match_readiness(match: dict | None) -> dict:
    """Summarise useful pre-match preparation data without inventing coverage.

    Completeness describes the whole payload, including live/post-match fields.
    Readiness deliberately looks only at information that is useful before
    kick-off, so a scheduled fixture can reach 100% without statistics/events.
    """
    match = match or {}
    checks = {
        "kickoff": _present(match.get("date_iso") or match.get("date")),
        "competition": _present(match.get("competition_name") or match.get("league_name")),
        "venue": _present(match.get("venue")),
        "broadcasts": bool(match.get("broadcasts")),
        "weather": bool(
            match.get("weather")
            or match.get("temperature")
            or match.get("venue_lat")
            or match.get("venue_lon")
        ),
        "head_to_head": bool(match.get("head_to_head")),
        "prediction": bool(match.get("prediction")),
        "odds": bool(match.get("odds")),
        "absences": bool(
            match.get("injuries_home")
            or match.get("injuries_away")
            or match.get("absences")
        ),
        "lineup": bool(
            match.get("lineup_home")
            or match.get("lineup_away")
            or match.get("expected_lineup_home")
            or match.get("expected_lineup_away")
        ),
    }
    weights = {
        "kickoff": 15,
        "competition": 10,
        "venue": 10,
        "broadcasts": 5,
        "weather": 5,
        "head_to_head": 10,
        "prediction": 10,
        "odds": 10,
        "absences": 10,
        "lineup": 15,
    }
    score = sum(weights[key] for key, available in checks.items() if available)
    level = (
        "ready" if score >= 80
        else "good" if score >= 55
        else "building" if score >= 30
        else "early"
    )
    return {
        "score": score,
        "level": level,
        "available": [key for key, available in checks.items() if available],
        "missing": [key for key, available in checks.items() if not available],
    }


def source_sections(match: dict, provider=None, updated_at=None) -> dict:
    """Describe availability, provider and freshness per visible card block."""
    fields = {
        "schedule": ("date", "date_iso", "venue", "competition_name", "league_name", "broadcasts"),
        "preview": ("head_to_head", "prediction", "odds", "injuries_home", "injuries_away", "weather"),
        "lineup": ("lineup_home", "lineup_away", "formation_home", "formation_away"),
        "timeline": ("key_events", "match_details"),
        "statistics": ("home_statistics", "away_statistics", "momentum", "shotmap"),
        "review": ("review", "player_of_the_match", "team_of_the_match", "match_story"),
    }
    return {
        section: {
            "available": any(_present(match.get(key)) for key in keys),
            "provider": provider,
            "updated_at": updated_at,
            "enriched": False,
        }
        for section, keys in fields.items()
    }


def annotate_completeness(
    matches: list[dict] | None,
    provider=None,
    updated_at=None,
) -> list[dict]:
    """Return copied match objects with a compact completeness descriptor."""
    return [
        {
            **match,
            "data_completeness": match_completeness(match),
            "match_readiness": match_readiness(match),
            "source_sections": source_sections(match, provider, updated_at),
        }
        for match in (matches or [])
        if isinstance(match, dict)
    ]


def data_quality(matches, provider, last_successful_update=None, last_error=None) -> dict:
    """Build a provider-neutral quality summary without inventing missing data."""
    matches = matches or []
    scores = [
        (match.get("data_completeness") or match_completeness(match))["score"]
        for match in matches
        if isinstance(match, dict)
    ]
    average = round(sum(scores) / len(scores)) if scores else 0
    issues = []
    if not matches:
        issues.append("no_matches")
    if last_error:
        issues.append("provider_error")
    if matches and average < 40:
        issues.append("limited_coverage")
    conflicts = []
    for match in matches:
        if match.get("state") == "pre" and (
            str(match.get("home_score") or "0") not in ("", "0")
            or str(match.get("away_score") or "0") not in ("", "0")
        ):
            conflicts.append({
                "event_id": match.get("event_id"),
                "field": "score",
                "reason": "scheduled_match_has_score",
            })
    return {
        "provider": provider,
        "updated_at": last_successful_update,
        "match_count": len(matches),
        "average_completeness": average,
        "level": "excellent" if average >= 85 else "good" if average >= 65 else "partial" if average >= 40 else "limited",
        "issues": issues,
        "conflicts": conflicts,
    }


def matchday_summary(matches: list[dict] | None) -> dict | None:
    """Summarise the most relevant calendar day represented by the payload."""
    matches = [match for match in (matches or []) if isinstance(match, dict)]
    if not matches:
        return None
    live = [match for match in matches if match.get("state") in ("in", "live")]
    upcoming = [match for match in matches if match.get("state") == "pre"]
    finished = [match for match in matches if match.get("state") == "post"]
    focus = (live or upcoming or list(reversed(finished)))[0]
    date = str(focus.get("date_iso") or focus.get("date") or "")[:10]
    same_day = [
        match for match in matches
        if str(match.get("date_iso") or match.get("date") or "")[:10] == date
    ]
    return {
        "date": date or None,
        "competition": focus.get("competition_name") or focus.get("league_name"),
        "focus_event_id": focus.get("event_id"),
        "phase": "live" if live else "upcoming" if upcoming else "finished",
        "matches": same_day,
        "total": len(same_day),
        "live": sum(match.get("state") in ("in", "live") for match in same_day),
        "upcoming": sum(match.get("state") == "pre" for match in same_day),
        "finished": sum(match.get("state") == "post" for match in same_day),
    }


def player_watchlist(club: dict | None, names: str | list[str] | None) -> list[dict]:
    """Resolve configured player names against the current squad."""
    if isinstance(names, str):
        names = [part.strip() for part in names.split(",") if part.strip()]
    wanted = {str(name).casefold() for name in (names or [])}
    if not wanted:
        return []
    squad = (club or {}).get("squad") or []
    results = []
    for player in squad:
        name = str(player.get("name") or "")
        if name.casefold() not in wanted:
            continue
        results.append({
            key: player.get(key)
            for key in (
                "id", "name", "photo", "number", "position", "age", "injured",
                "goals", "assists", "rating",
            )
            if player.get(key) is not None
        })
    return results


def archive_snapshot(match: dict, provider: str) -> dict:
    """Create a bounded, recorder-friendly historical match record."""
    snapshot = {
        key: match.get(key)
        for key in (
            "event_id", "date", "date_iso", "competition_name", "league_name",
            "home_team", "away_team", "home_logo", "away_logo", "home_score",
            "away_score", "status", "venue", "season_info", "round",
            "home_id", "away_id", "is_friendly",
        )
        if match.get(key) is not None
    }
    snapshot["season"] = archive_season(snapshot)
    return snapshot | {
        "provider": provider,
        "archived_at": datetime.now(timezone.utc).isoformat(),
    }


def archive_season(match: dict) -> str:
    """Return a stable season label from provider data or the fixture date."""
    raw = match.get("season") or match.get("season_info")
    if isinstance(raw, dict):
        raw = raw.get("displayName") or raw.get("name") or raw.get("year")
    if raw not in (None, "", "N/A"):
        text = str(raw).strip()
        years = re.findall(r"(?:19|20)\d{2}", text)
        if len(years) >= 2:
            return f"{years[0]}/{years[1][-2:]}"
        if len(years) == 1:
            year = int(years[0])
            return f"{year}/{str(year + 1)[-2:]}"
        return text
    raw_date = str(match.get("date_iso") or match.get("date") or "")
    found = re.search(r"((?:19|20)\d{2})-(\d{2})", raw_date)
    if not found:
        return "unknown"
    year, month = int(found.group(1)), int(found.group(2))
    start = year if month >= 7 else year - 1
    return f"{start}/{str(start + 1)[-2:]}"


def _tracked_result(match: dict, team_name: str | None) -> tuple[int, int] | None:
    """Return goals for/against for a tracked team, or home/away as fallback."""
    try:
        home_score = int(match.get("home_score"))
        away_score = int(match.get("away_score"))
    except (TypeError, ValueError):
        return None
    team = str(team_name or "").casefold().strip()
    home = str(match.get("home_team") or "").casefold()
    away = str(match.get("away_team") or "").casefold()
    def same(left, right):
        return (
            left == right
            or (
                len(left) >= 4
                and len(right) >= 4
                and (left in right or right in left)
            )
        )
    if team and same(team, away):
        return away_score, home_score
    if not team or same(team, home):
        return home_score, away_score
    return None


def archive_statistics(
    matches: list[dict] | None,
    team_name: str | None = None,
    season: str | None = None,
    competition: str | None = None,
) -> dict:
    """Calculate compact archive statistics for one optional filter."""
    selected = []
    for match in matches or []:
        if not isinstance(match, dict):
            continue
        if season and archive_season(match) != season:
            continue
        name = match.get("competition_name") or match.get("league_name") or ""
        if competition and name != competition:
            continue
        result = _tracked_result(match, team_name)
        if result is not None:
            selected.append((match, result))

    won = drawn = lost = goals_for = goals_against = clean_sheets = 0
    current_unbeaten = longest_unbeaten = current_wins = longest_wins = 0
    for _match, (own, other) in reversed(selected):
        goals_for += own
        goals_against += other
        clean_sheets += other == 0
        if own > other:
            won += 1
            current_wins += 1
            current_unbeaten += 1
        elif own == other:
            drawn += 1
            current_wins = 0
            current_unbeaten += 1
        else:
            lost += 1
            current_wins = 0
            current_unbeaten = 0
        longest_wins = max(longest_wins, current_wins)
        longest_unbeaten = max(longest_unbeaten, current_unbeaten)
    total = len(selected)
    return {
        "matches": total,
        "won": won,
        "drawn": drawn,
        "lost": lost,
        "win_percentage": round((won / total) * 100) if total else 0,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "goal_difference": goals_for - goals_against,
        "clean_sheets": clean_sheets,
        "longest_unbeaten": longest_unbeaten,
        "longest_winning": longest_wins,
    }


def archive_summary(matches: list[dict] | None, team_name: str | None = None) -> dict:
    """Describe filters and all-time statistics for the local archive."""
    matches = [match for match in (matches or []) if isinstance(match, dict)]
    seasons = sorted(
        {archive_season(match) for match in matches if archive_season(match) != "unknown"},
        reverse=True,
    )
    competitions = sorted({
        str(match.get("competition_name") or match.get("league_name"))
        for match in matches
        if match.get("competition_name") or match.get("league_name")
    })
    return {
        "count": len(matches),
        "seasons": seasons,
        "competitions": competitions,
        "statistics": archive_statistics(matches, team_name),
    }


def update_archive(existing: list[dict] | None, matches: list[dict] | None, provider: str, limit=500) -> list[dict]:
    """Merge newly finished matches into an archive, newest first."""
    by_id = {
        str(item.get("event_id") or f"{item.get('date_iso')}|{item.get('home_team')}|{item.get('away_team')}"): item
        for item in (existing or [])
    }
    for match in matches or []:
        if match.get("state") != "post":
            continue
        snapshot = archive_snapshot(match, provider)
        key = str(snapshot.get("event_id") or f"{snapshot.get('date_iso')}|{snapshot.get('home_team')}|{snapshot.get('away_team')}")
        if key in by_id:
            snapshot["archived_at"] = by_id[key].get("archived_at", snapshot["archived_at"])
        by_id[key] = snapshot
    return sorted(
        by_id.values(),
        key=lambda item: str(item.get("date_iso") or item.get("date") or ""),
        reverse=True,
    )[:limit]
