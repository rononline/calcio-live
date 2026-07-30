"""Local match-archive validation and service helpers."""

from __future__ import annotations

import json

ARCHIVE_LIMIT = 500


def archive_key(item: dict) -> str:
    """Return a provider-independent archive identity."""
    return str(
        item.get("canonical_id")
        or item.get("event_id")
        or "|".join(
            str(item.get(key) or "")
            for key in ("date_iso", "home_team", "away_team")
        )
    )


def validate_archive(value, limit: int = ARCHIVE_LIMIT) -> list[dict]:
    """Validate, deduplicate and bound imported archive data."""
    if isinstance(value, str):
        value = json.loads(value)
    if isinstance(value, dict):
        value = value.get("matches")
    if not isinstance(value, list):
        raise ValueError("Archive must be a JSON list or an object with a matches list")
    by_id = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        if not item.get("home_team") or not item.get("away_team"):
            continue
        by_id[archive_key(item)] = dict(item)
    return sorted(
        by_id.values(),
        key=lambda item: str(item.get("date_iso") or item.get("date") or ""),
        reverse=True,
    )[:limit]


def export_archive(matches: list[dict] | None) -> str:
    """Return deterministic pretty JSON suitable for backup/import."""
    return json.dumps(
        {"version": 1, "matches": validate_archive(matches or [])},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
