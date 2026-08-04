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
