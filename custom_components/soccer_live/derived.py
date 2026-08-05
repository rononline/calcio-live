"""Provider-neutral derived state shared by entities and cards."""

from __future__ import annotations

from datetime import datetime, timezone


def _present(value) -> bool:
    return value not in (None, "", [], {}, "N/A", "Unknown", "unknown", "-")


def _as_datetime(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def entry_match_state(matches, now=None) -> dict:
    """Return automation-friendly flags for an entry's published fixtures."""
    now = now or datetime.now(timezone.utc)
    local_day = now.date()
    tomorrow_day = local_day.fromordinal(local_day.toordinal() + 1)
    items = [item for item in (matches or []) if isinstance(item, dict)]
    live = [item for item in items if item.get("state") in {"in", "live"}]
    today = []
    tomorrow = []
    for item in items:
        kickoff = _as_datetime(item.get("date_iso") or item.get("date"))
        if kickoff:
            kickoff_day = kickoff.astimezone(now.tzinfo).date()
            if kickoff_day == local_day:
                today.append(item)
            elif kickoff_day == tomorrow_day:
                tomorrow.append(item)
    upcoming = sorted(
        (
            (kickoff, item)
            for item in items
            if item.get("state") == "pre"
            if (kickoff := _as_datetime(item.get("date_iso") or item.get("date")))
            and kickoff >= now
        ),
        key=lambda pair: pair[0],
    )
    degraded = [
        item for item in (live or today)
        if (item.get("data_completeness") or {}).get("level") == "limited"
        or any(
            alert.get("severity") in {"warning", "error"}
            for alert in (item.get("data_alerts") or [])
            if isinstance(alert, dict)
        )
    ]
    focus = (
        live[0] if live
        else today[0] if today
        else upcoming[0][1] if upcoming
        else tomorrow[0] if tomorrow
        else None
    )
    lineup_available = bool(
        focus and (focus.get("lineup_home") or focus.get("lineup_away"))
    )
    return {
        "match_live": bool(live),
        "match_today": bool(today),
        "match_tomorrow": bool(tomorrow),
        "lineup_available": lineup_available,
        "data_degraded": bool(degraded),
        "focus_match": focus,
        "live_count": len(live),
        "today_count": len(today),
        "tomorrow_count": len(tomorrow),
    }


_CAPABILITY_FIELDS = {
    "fixtures": ("date_iso", "home_team", "away_team"),
    "scores": ("home_score", "away_score"),
    "lineups": ("lineup_home", "lineup_away"),
    "timeline": ("key_events", "match_details"),
    "statistics": ("home_statistics", "away_statistics", "momentum", "shotmap"),
    "head_to_head": ("head_to_head",),
    "predictions": ("prediction",),
    "odds": ("odds", "live_odds"),
    "injuries": ("injuries_home", "injuries_away", "absences"),
    "weather": ("weather", "temperature", "venue_lat"),
    "broadcasts": ("broadcasts",),
    "review": ("review", "player_of_the_match", "match_story", "match_summary"),
    "analysis": ("momentum_analysis", "preview_analysis", "post_match_analysis"),
}


def capability_matrix(matches, provider_capabilities=(), last_error=None) -> dict:
    """Explain availability instead of only reporting a list of missing fields."""
    items = [item for item in (matches or []) if isinstance(item, dict)]
    supported = set(provider_capabilities or ())
    result = {}
    for capability, fields in _CAPABILITY_FIELDS.items():
        available = any(any(_present(item.get(field)) for field in fields) for item in items)
        provider_key = {
            "timeline": "scores",
            "weather": "fixtures",
            "broadcasts": "fixtures",
            "review": "statistics",
        }.get(capability, capability)
        provider_support = provider_key in supported
        if available:
            status, reason = "available", "available"
        elif last_error:
            status, reason = "error", "provider_error"
        elif provider_support:
            status, reason = "pending", "not_yet_published"
        else:
            status, reason = "unavailable", "provider_unsupported"
        result[capability] = {
            "status": status,
            "reason": reason,
            "available": available,
            "provider_support": provider_support,
        }
    return result


def season_transition(attributes, matches, configured_season=None, now=None) -> dict:
    """Describe automatic season rollover and detect an explicitly stale season."""
    now = now or datetime.now(timezone.utc)
    items = [item for item in (matches or []) if isinstance(item, dict)]
    past = {str(item.get("season_info")) for item in items if item.get("state") == "post" and item.get("season_info") not in (None, "")}
    future = {str(item.get("season_info")) for item in items if item.get("state") == "pre" and item.get("season_info") not in (None, "")}
    end = _as_datetime((attributes or {}).get("season_end"))
    stale = False
    reason = None
    if configured_season:
        try:
            stale = any(int(float(value)) > int(configured_season) for value in future)
        except (TypeError, ValueError):
            stale = False
        if stale:
            reason = "configured_season_behind"
    if not stale and end and end < now and any(
        (_as_datetime(item.get("date_iso") or item.get("date")) or now) > end
        for item in items if item.get("state") == "pre"
    ):
        stale, reason = True, "season_window_expired"
    rollover = bool(past and future and past.isdisjoint(future))
    status = "stale" if stale else "rollover" if rollover else "current"
    return {
        "status": status,
        "reason": reason,
        "configured_season": configured_season,
        "previous_seasons": sorted(past),
        "upcoming_seasons": sorted(future),
        "season_start": (attributes or {}).get("season_start"),
        "season_end": (attributes or {}).get("season_end"),
    }


def match_summary(match, tracked_team=None) -> dict | None:
    """Build a compact structured post-match story cards can translate."""
    if not isinstance(match, dict) or match.get("state") != "post":
        return None
    try:
        home_score = int(match.get("home_score"))
        away_score = int(match.get("away_score"))
    except (TypeError, ValueError):
        return None
    events = [item for item in (match.get("key_events") or []) if isinstance(item, dict)]
    goals = [item for item in events if str(item.get("type") or "").lower() in {"goal", "score"} or item.get("scoring_play")]
    cards = [item for item in events if "card" in str(item.get("type") or "").lower()]
    tracked = str(tracked_team or "").casefold()
    home = str(match.get("home_team") or "").casefold()
    own, other = (away_score, home_score) if tracked and tracked in str(match.get("away_team") or "").casefold() else (home_score, away_score)
    outcome = "win" if own > other else "draw" if own == other else "loss"
    return {
        "outcome": outcome,
        "score": f"{home_score}-{away_score}",
        "goal_scorers": [item.get("player") for item in goals if item.get("player")],
        "goal_count": len(goals),
        "card_count": len(cards),
        "player_of_the_match": match.get("player_of_the_match"),
        "home_xg": (
            match.get("home_statistics", {}).get("expectedGoals")
            if isinstance(match.get("home_statistics"), dict) else None
        ),
        "away_xg": (
            match.get("away_statistics", {}).get("expectedGoals")
            if isinstance(match.get("away_statistics"), dict) else None
        ),
        "venue": match.get("venue"),
        "competition": match.get("competition_name") or match.get("league_name"),
    }


_RICH_FIELDS = (
    "broadcasts", "weather", "head_to_head", "prediction", "odds", "live_odds",
    "injuries_home", "injuries_away", "absences", "lineup_home", "lineup_away",
    "formation_home", "formation_away", "key_events", "match_details",
    "home_statistics", "away_statistics", "momentum", "shotmap",
    "player_of_the_match", "review", "match_story", "match_summary",
    "momentum_analysis", "preview_analysis", "post_match_analysis",
)


def merge_match_sources(primary, secondary_sources) -> tuple[list[dict], dict]:
    """Fill missing rich fields on primary fixtures without changing its schedule."""
    sources = [item for source in (secondary_sources or []) for item in (source or []) if isinstance(item, dict)]
    by_id = {}
    by_pair = {}
    for item in sources:
        if item.get("canonical_id"):
            by_id.setdefault(str(item["canonical_id"]), []).append(item)
        if item.get("canonical_pair_id"):
            by_pair.setdefault(str(item["canonical_pair_id"]), []).append(item)
    enriched = conflicts = 0
    output = []
    providers = set()
    for original in primary or []:
        item = dict(original)
        candidates = list(by_id.get(str(item.get("canonical_id")), []))
        if not candidates and item.get("canonical_pair_id"):
            kickoff = _as_datetime(item.get("date_iso") or item.get("date"))
            for candidate in by_pair.get(str(item["canonical_pair_id"]), []):
                other = _as_datetime(candidate.get("date_iso") or candidate.get("date"))
                if kickoff and other and abs((kickoff - other).total_seconds()) <= 36 * 3600:
                    candidates.append(candidate)
        seen = set()
        for candidate in candidates:
            marker = id(candidate)
            if marker in seen:
                continue
            seen.add(marker)
            provider = candidate.get("provider")
            if provider:
                providers.add(str(provider))
            for field in _RICH_FIELDS:
                incoming = candidate.get(field)
                if not _present(incoming):
                    continue
                if not _present(item.get(field)):
                    item[field] = incoming
                    enriched += 1
                elif item.get(field) != incoming:
                    conflicts += 1
        output.append(item)
    return output, {
        "enabled": True,
        "sources": sorted(providers),
        "enriched_fields": enriched,
        "conflicts": conflicts,
    }
