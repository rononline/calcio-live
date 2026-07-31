"""Provider-neutral derived insights for Soccer Live sensors."""

from __future__ import annotations

import re
from collections import Counter
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


def data_alerts(
    matches: list[dict] | None,
    last_error=None,
    now: datetime | None = None,
) -> list[dict]:
    """Return actionable, provider-neutral data warnings.

    Alerts describe only observable inconsistencies. Missing optional provider
    capabilities are intentionally not warnings.
    """
    now = now or datetime.now(timezone.utc)
    alerts = []
    seen = set()

    def add(code, severity="warning", match=None, **details):
        event_id = (match or {}).get("event_id")
        key = (code, str(event_id or ""), tuple(sorted(details.items())))
        if key in seen:
            return
        seen.add(key)
        alerts.append({
            "code": code,
            "severity": severity,
            "event_id": event_id,
            "canonical_id": (match or {}).get("canonical_id"),
            **details,
        })

    if last_error:
        add("provider_error", "error")

    matches = [match for match in (matches or []) if isinstance(match, dict)]
    pair_dates: dict[str, list[dict]] = {}
    for match in matches:
        phase = str(match.get("match_phase") or "")
        state = str(match.get("state") or "")
        if phase in {"postponed", "cancelled"}:
            add(f"match_{phase}", "warning", match)
        conflicts = match.get("source_conflicts") or []
        if conflicts:
            add("source_conflict", "warning", match, fields=len(conflicts))
        if state in {"in", "live"}:
            clock = str(match.get("clock") or "")
            minute_match = re.search(r"\d+", clock)
            minute = int(minute_match.group()) if minute_match else 0
            if minute >= 1 and not (
                match.get("lineup_home") or match.get("lineup_away")
            ):
                add("live_lineup_missing", "info", match)
            if minute >= 15 and not (
                match.get("key_events") or match.get("match_details")
            ):
                add("live_timeline_missing", "info", match)
            sections = match.get("source_sections") or {}
            updated_values = [
                section.get("updated_at")
                for section in sections.values()
                if isinstance(section, dict) and section.get("updated_at")
            ]
            parsed = []
            for value in updated_values:
                try:
                    stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
                    if stamp.tzinfo is None:
                        stamp = stamp.replace(tzinfo=timezone.utc)
                    parsed.append(stamp.astimezone(timezone.utc))
                except ValueError:
                    continue
            if parsed and (now - max(parsed)).total_seconds() > 5 * 60:
                add("live_data_stale", "warning", match)
        pair_id = str(match.get("canonical_pair_id") or "")
        if pair_id:
            pair_dates.setdefault(pair_id, []).append(match)

    for related in pair_dates.values():
        dates = {
            str(item.get("date_iso") or item.get("date") or "")[:10]
            for item in related
            if item.get("date_iso") or item.get("date")
        }
        phases = {str(item.get("match_phase") or "") for item in related}
        if len(dates) > 1 and phases & {"postponed", "cancelled"}:
            current = next(
                (item for item in related if item.get("state") == "pre"),
                related[0],
            )
            add("match_rescheduled", "info", current, dates=len(dates))
    return alerts


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


def watched_player_names(names: str | list[str] | None) -> set[str]:
    """Return normalized configured player names for event matching."""
    if isinstance(names, str):
        names = names.split(",")
    return {
        str(name).strip().casefold()
        for name in (names or [])
        if str(name).strip()
    }


def watchlist_event(event_data: dict | None, names: str | list[str] | None) -> dict | None:
    """Describe a match event when it concerns a configured watched player."""
    wanted = watched_player_names(names)
    if not wanted:
        return None
    event_data = event_data or {}
    candidates = [
        event_data.get("player"),
        event_data.get("athlete"),
        event_data.get("player_name"),
        *((event_data.get("athletes") or []) if isinstance(event_data.get("athletes"), list) else []),
    ]
    player = next(
        (
            str(candidate).strip()
            for candidate in candidates
            if str(candidate or "").strip().casefold() in wanted
        ),
        None,
    )
    if not player:
        return None
    return {
        **event_data,
        "player": player,
        "watchlist": True,
    }


def _standing_groups(attributes: dict | None) -> list[dict]:
    return [
        group for group in (attributes or {}).get("standings_groups", [])
        if isinstance(group, dict) and isinstance(group.get("standings"), list)
    ]


def standings_snapshot(
    attributes: dict | None,
    captured_at: str | None = None,
) -> dict | None:
    """Return a compact provider-neutral league-table snapshot."""
    attributes = attributes or {}
    groups = []
    for group in _standing_groups(attributes):
        rows = []
        for row in group["standings"]:
            if not isinstance(row, dict) or not row.get("team_name"):
                continue
            rows.append({
                key: row.get(key)
                for key in (
                    "rank", "team_id", "team_name", "team_logo", "points",
                    "games_played", "wins", "draws", "losses",
                    "goals_for", "goals_against", "goal_difference",
                    "zone_label", "zone_abbrev",
                )
                if row.get(key) not in (None, "")
            })
        if rows:
            groups.append({"name": group.get("name") or "Standings", "standings": rows})
    if not groups:
        return None
    return {
        "captured_at": captured_at or datetime.now(timezone.utc).isoformat(),
        "season": attributes.get("season"),
        "league_name": attributes.get("league_name"),
        "groups": groups,
    }


def update_standings_history(
    history: list[dict] | None,
    attributes: dict | None,
    captured_at: str | None = None,
    limit: int = 200,
) -> list[dict]:
    """Append a table snapshot only when its sporting content changed."""
    snapshot = standings_snapshot(attributes, captured_at)
    current = [item for item in (history or []) if isinstance(item, dict)]
    if not snapshot:
        return current[-limit:]

    def fingerprint(item):
        return [
            [
                (
                    row.get("team_id") or row.get("team_name"),
                    row.get("rank"),
                    row.get("points"),
                    row.get("games_played"),
                    row.get("goal_difference"),
                )
                for row in group.get("standings", [])
            ]
            for group in item.get("groups", [])
        ]

    if current and fingerprint(current[-1]) == fingerprint(snapshot):
        return current[-limit:]
    return (current + [snapshot])[-limit:]


def competition_race(attributes: dict | None) -> dict | None:
    """Summarize gaps and attainable ranges for every table row."""
    groups = _standing_groups(attributes)
    if not groups:
        return None
    result_groups = []
    for group in groups:
        rows = group.get("standings") or []
        numeric = []
        for index, row in enumerate(rows):
            try:
                points = int(row.get("points"))
                played = int(row.get("games_played"))
            except (TypeError, ValueError):
                continue
            numeric.append((index, row, points, played))
        if not numeric:
            continue
        leader_points = max(item[2] for item in numeric)
        max_played = max(item[3] for item in numeric)
        total_matches = max(2 * (len(rows) - 1), max_played)
        race_rows = []
        for position, row, points, played in numeric:
            remaining = max(0, total_matches - played)
            above_points = numeric[position - 1][2] if position > 0 and position - 1 < len(numeric) else points
            race_rows.append({
                "rank": row.get("rank", position + 1),
                "team_id": row.get("team_id"),
                "team_name": row.get("team_name"),
                "team_logo": row.get("team_logo"),
                "points": points,
                "games_played": played,
                "remaining": remaining,
                "maximum_points": points + remaining * 3,
                "gap_to_leader": max(0, leader_points - points),
                "gap_to_above": max(0, above_points - points),
                "zone_label": row.get("zone_label") or row.get("zone_abbrev"),
            })
        result_groups.append({
            "name": group.get("name") or "Standings",
            "total_matches": total_matches,
            "rows": race_rows,
        })
    if not result_groups:
        return None
    return {
        "season": (attributes or {}).get("season"),
        "league_name": (attributes or {}).get("league_name"),
        "groups": result_groups,
    }


def archive_snapshot(match: dict, provider: str) -> dict:
    """Create a bounded, recorder-friendly historical match record."""
    snapshot = {
        key: match.get(key)
        for key in (
            "event_id", "canonical_id", "canonical_pair_id", "provider_event_id",
            "date", "date_iso", "competition_name", "league_name",
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
    results = [
        (match, _tracked_result(match, team_name))
        for match in matches
    ]
    results = [(match, result) for match, result in results if result is not None]
    monthly: dict[str, list[dict]] = {}
    opponents = Counter()
    home = []
    away = []
    biggest_win = None
    biggest_loss = None
    tracked = str(team_name or "").casefold()
    for match, (own, other) in results:
        raw_date = str(match.get("date_iso") or match.get("date") or "")
        month_match = re.search(r"((?:19|20)\d{2}-\d{2})", raw_date)
        if month_match:
            monthly.setdefault(month_match.group(1), []).append(match)
        home_name = str(match.get("home_team") or "")
        away_name = str(match.get("away_team") or "")
        is_away = bool(tracked and tracked in away_name.casefold())
        opponent = home_name if is_away else away_name
        if opponent:
            opponents[opponent] += 1
        (away if is_away else home).append(match)
        margin = own - other
        candidate = {
            "date": match.get("date_iso") or match.get("date"),
            "opponent": opponent,
            "score": f"{own}-{other}",
            "margin": abs(margin),
        }
        if margin > 0 and (biggest_win is None or margin > biggest_win["margin"]):
            biggest_win = candidate
        if margin < 0 and (biggest_loss is None or -margin > biggest_loss["margin"]):
            biggest_loss = candidate
    seasons_report = [
        {"season": season, **archive_statistics(matches, team_name, season=season)}
        for season in seasons[:10]
    ]
    return {
        "count": len(matches),
        "seasons": seasons,
        "competitions": competitions,
        "statistics": archive_statistics(matches, team_name),
        "home": archive_statistics(home, team_name),
        "away": archive_statistics(away, team_name),
        "monthly": [
            {"month": month, **archive_statistics(items, team_name)}
            for month, items in sorted(monthly.items())[-18:]
        ],
        "season_reports": seasons_report,
        "common_opponents": [
            {"name": name, "matches": count}
            for name, count in opponents.most_common(10)
        ],
        "biggest_win": biggest_win,
        "biggest_loss": biggest_loss,
    }


def update_archive(existing: list[dict] | None, matches: list[dict] | None, provider: str, limit=500) -> list[dict]:
    """Merge newly finished matches into an archive, newest first."""
    by_id = {
        str(
            item.get("canonical_id")
            or item.get("event_id")
            or f"{item.get('date_iso')}|{item.get('home_team')}|{item.get('away_team')}"
        ): item
        for item in (existing or [])
    }
    for match in matches or []:
        if match.get("state") != "post":
            continue
        snapshot = archive_snapshot(match, provider)
        key = str(
            snapshot.get("canonical_id")
            or snapshot.get("event_id")
            or f"{snapshot.get('date_iso')}|{snapshot.get('home_team')}|{snapshot.get('away_team')}"
        )
        # Migrate archives written before canonical IDs without duplicating the
        # same provider fixture on its first schema-v5 update.
        legacy_key = str(snapshot.get("event_id") or "")
        previous = by_id.get(key)
        if previous is None and legacy_key and legacy_key != key:
            previous = by_id.pop(legacy_key, None)
        if previous is not None:
            snapshot["archived_at"] = previous.get(
                "archived_at", snapshot["archived_at"]
            )
        by_id[key] = snapshot
    return sorted(
        by_id.values(),
        key=lambda item: str(item.get("date_iso") or item.get("date") or ""),
        reverse=True,
    )[:limit]
