"""Provider-neutral fixture identity helpers."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from datetime import datetime, timezone

_CLUB_WORDS = {
    "afc",
    "cf",
    "fc",
    "football",
    "club",
    "sc",
    "sv",
}


def _slug(value) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    words = re.findall(r"[a-z0-9]+", text.casefold())
    trimmed = [word for word in words if word not in _CLUB_WORDS]
    return "-".join(trimmed or words) or "unknown"


def _team_key(match: dict, side: str) -> str:
    provider_id = match.get(f"{side}_id")
    name = _slug(match.get(f"{side}_team") or match.get(side))
    # Provider IDs differ between sources, so names are authoritative whenever
    # available. The ID is only a fallback for nameless malformed records.
    if name != "unknown":
        return name
    return f"id-{provider_id}" if provider_id not in (None, "", "N/A") else name


def _kickoff_day(match: dict) -> str:
    raw = str(match.get("date_iso") or match.get("date") or "")
    if not raw:
        return "unknown"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).date().isoformat()
    except ValueError:
        found = re.search(r"((?:19|20)\d{2})[-/](\d{2})[-/](\d{2})", raw)
        if found:
            return "-".join(found.groups())
        return raw[:10]


def _digest(*parts: str) -> str:
    raw = "|".join(parts).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def fixture_identity(match: dict | None) -> dict:
    """Return stable fixture and matchup identities for a normalised match.

    ``canonical_id`` includes the UTC match day and therefore identifies one
    scheduled fixture. ``canonical_pair_id`` deliberately omits the date so a
    postponed/rescheduled meeting can still be recognised across providers.
    """
    match = match or {}
    home = _team_key(match, "home")
    away = _team_key(match, "away")
    competition = _slug(
        match.get("competition_name")
        or match.get("league_name")
        or match.get("league_id")
    )
    season = _slug(match.get("season") or match.get("season_info"))
    pair_id = _digest(home, away, competition, season)
    return {
        "canonical_id": _digest(pair_id, _kickoff_day(match)),
        "canonical_pair_id": pair_id,
        "provider_event_id": str(match.get("event_id") or "") or None,
    }


def annotate_identity(match: dict | None) -> dict:
    """Copy a match and attach canonical identity fields."""
    return {**(match or {}), **fixture_identity(match)}
