"""Local match-archive validation and service helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime

ARCHIVE_LIMIT = 500
ARCHIVE_CONTRACT = "soccer_live.archive.v1"


def _normalize_date(value) -> str:
    text = str(value or "").strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    for fmt in ("%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return text


def normalize_archive_match(item: dict) -> dict:
    """Normalize the public archive contract and common Dutch legacy exports."""
    normalized = dict(item)
    aliases = {
        "datum": "date_iso",
        "thuis": "home_team",
        "uit": "away_team",
        "competitie": "competition_name",
        "seizoen": "season",
        "stadion": "venue",
    }
    for source, target in aliases.items():
        if not normalized.get(target) and normalized.get(source) is not None:
            normalized[target] = normalized[source]
    if normalized.get("date_iso"):
        normalized["date_iso"] = _normalize_date(normalized["date_iso"])
    score = normalized.get("uitslag") or normalized.get("score")
    if score and (normalized.get("home_score") is None or normalized.get("away_score") is None):
        found = re.search(r"(\d+)\s*[-–:]\s*(\d+)", str(score))
        if found:
            normalized["home_score"] = int(found.group(1))
            normalized["away_score"] = int(found.group(2))
    normalized.setdefault("state", "post")
    return normalized


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
        value = value.get("matches") or value.get("results") or value.get("uitslagen")
    if not isinstance(value, list):
        raise ValueError("Archive must be a JSON list or an object with a matches list")
    by_id = {}
    for item in value:
        if not isinstance(item, dict):
            continue
        item = normalize_archive_match(item)
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
        {
            "schema": ARCHIVE_CONTRACT,
            "version": 1,
            "matches": validate_archive(matches or []),
        },
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
