"""Provider-neutral adaptive polling policy.

The entity remains a normal Home Assistant polling entity.  This module only
decides when Soccer Live should schedule an *additional* refresh around a
fixture, where a fixed multi-minute interval would feel stale.  Keeping the
policy pure makes the quota and phase behaviour independently testable.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone


def _as_utc(value) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _quota_floor(quota: dict | None) -> tuple[int, str] | None:
    """Return a conservative minimum interval when a daily quota runs low."""
    try:
        limit = int((quota or {}).get("requests_limit_day"))
        current = int((quota or {}).get("requests_current"))
    except (TypeError, ValueError):
        return None
    if limit <= 0:
        return None
    remaining = max(0, limit - current)
    ratio = remaining / limit
    if remaining == 0:
        return 3600, "quota_exhausted"
    if ratio <= 0.05:
        return 300, "quota_critical"
    if ratio <= 0.15:
        return 120, "quota_low"
    return None


def request_priority_plan(
    matches: list[dict] | None,
    *,
    quota: dict | None = None,
) -> dict:
    """Plan optional requests by match phase and remaining daily quota.

    The main fixture/score request is never disabled. Optional sections are
    ordered by usefulness and progressively deferred under quota pressure.
    """
    rows = [item for item in (matches or []) if isinstance(item, dict)]
    live = any(item.get("state") in {"in", "live"} for item in rows)
    upcoming = any(item.get("state") in {"pre", "scheduled"} for item in rows)
    finished = any(item.get("state") in {"post", "finished"} for item in rows)
    phase = "live" if live else "prematch" if upcoming else "postmatch" if finished else "idle"
    order = {
        "live": ["timeline", "lineup", "statistics", "prematch", "head_to_head", "club"],
        "prematch": ["lineup", "prematch", "head_to_head", "club", "timeline", "statistics"],
        "postmatch": ["timeline", "statistics", "lineup", "head_to_head", "club", "prematch"],
        "idle": ["club", "head_to_head", "prematch", "lineup", "timeline", "statistics"],
    }[phase]
    try:
        limit = int((quota or {}).get("requests_limit_day"))
        current = int((quota or {}).get("requests_current"))
    except (TypeError, ValueError):
        limit = current = 0
    remaining = max(0, limit - current) if limit > 0 else None
    ratio = (remaining / limit) if limit > 0 else None
    if remaining == 0 and limit > 0:
        level, allowance = "exhausted", 0
    elif ratio is not None and ratio <= 0.05:
        level, allowance = "critical", 1
    elif ratio is not None and ratio <= 0.15:
        level, allowance = "constrained", 3
    else:
        level, allowance = "normal", len(order)
    allowed = order[:allowance]
    return {
        "phase": phase,
        "quota_level": level,
        "remaining": remaining,
        "priority": order,
        "allowed": allowed,
        "deferred": [item for item in order if item not in allowed],
    }


def adaptive_poll_interval(
    matches: list[dict] | None,
    *,
    base_seconds: int,
    live_seconds: int,
    quota: dict | None = None,
    now: datetime | None = None,
) -> tuple[int, str]:
    """Return ``(seconds, reason)`` for the next useful provider refresh.

    Policy:
    - live play uses the configured live interval;
    - half-time relaxes very aggressive polling to at least 60 seconds;
    - the final 30 minutes before kick-off use at most 60 seconds;
    - recently finished fixtures receive short follow-up checks for corrections;
    - API-Football quota pressure always wins over the phase preference.
    """
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    base = max(60, int(base_seconds or 180))
    live = max(15, int(live_seconds or 60))
    interval, reason = base, "normal"

    rows = [match for match in (matches or []) if isinstance(match, dict)]
    live_rows = [m for m in rows if m.get("state") in {"in", "live"}]
    if live_rows:
        halftime = any(
            str(m.get("match_phase") or m.get("period") or m.get("status") or "")
            .casefold()
            .replace("_", " ")
            in {"halftime", "half time", "ht"}
            for m in live_rows
        )
        interval, reason = (max(60, live), "halftime") if halftime else (live, "live")
    else:
        upcoming = []
        recent_finished = False
        for match in rows:
            kickoff = _as_utc(match.get("date_iso"))
            if kickoff is None:
                continue
            state = match.get("state")
            if state in {"pre", "scheduled"} and kickoff >= current:
                upcoming.append(kickoff)
            elif state in {"post", "finished"}:
                # Kick-off + three hours safely covers ordinary and extra-time
                # matches while keeping post-match correction polling bounded.
                recent_finished |= current <= kickoff + timedelta(hours=3)
        if upcoming:
            until = min(upcoming) - current
            if timedelta(0) <= until <= timedelta(minutes=30):
                interval, reason = min(base, 60), "kickoff_soon"
            elif timedelta(0) <= until <= timedelta(hours=3):
                interval, reason = min(base, 120), "matchday"
        elif recent_finished:
            interval, reason = min(base, 60), "post_match"

    quota_limit = _quota_floor(quota)
    if quota_limit and quota_limit[0] > interval:
        interval, reason = quota_limit
    return interval, reason
