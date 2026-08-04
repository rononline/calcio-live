"""Small provider-neutral helpers for on-demand fixture details."""

from __future__ import annotations

from copy import deepcopy

DETAIL_KEYS = (
    "key_events", "match_details", "lineup_home", "lineup_away",
    "home_statistics", "away_statistics", "momentum", "shotmap",
)


def has_match_details(match: dict | None) -> bool:
    """Whether a fixture already contains useful popup/detail information."""
    if not isinstance(match, dict):
        return False
    return match.get("detail_loaded") is True or any(
        match.get(key) for key in DETAIL_KEYS
    )


def find_match(attributes: dict | None, match_id) -> dict | None:
    """Find one fixture in any normal Soccer Live published location."""
    wanted = str(match_id or "")
    if not wanted:
        return None
    attrs = attributes or {}
    for key in ("current_match", "next_match"):
        match = attrs.get(key)
        if isinstance(match, dict) and str(match.get("event_id")) == wanted:
            return match
    for key in ("matches", "previous_matches", "upcoming_matches"):
        for match in attrs.get(key) or []:
            if isinstance(match, dict) and str(match.get("event_id")) == wanted:
                return match
    return None


def public_match_details(match: dict | None) -> dict | None:
    """Return a detached response safe for a service/WebSocket caller."""
    return deepcopy(match) if isinstance(match, dict) else None
