"""Stable, provider-neutral Home Assistant event contract."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone

EVENT_CONTRACT_VERSION = 1

# Some providers spell the same club differently — e.g. ESPN "Feyenoord
# Rotterdam" vs API-Football "Feyenoord" — which would break cross-provider
# event identity. Map the normalized slug of each known variant to a canonical
# slug. Extend this as needed; deliberately avoid heuristics such as stripping a
# trailing city, which would wrongly merge distinct clubs (e.g. "Sparta
# Rotterdam" → "Sparta").
_TEAM_NAME_ALIASES = {
    "feyenoord-rotterdam": "feyenoord",
}


def _text(value) -> str:
    value = unicodedata.normalize("NFKD", str(value or ""))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")
    return _TEAM_NAME_ALIASES.get(value, value)


def _score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def event_uid(event_type: str, payload: dict | None) -> str:
    """Identify one real-world event independently of provider fixture IDs."""
    data = payload or {}
    home_score = _score(data.get("home_score"))
    away_score = _score(data.get("away_score"))
    home = _text(data.get("home_team"))
    away = _text(data.get("away_team"))
    team = _text(data.get("team"))
    side = "home" if team and team == home else "away" if team and team == away else team
    date = str(data.get("date_iso") or data.get("date") or "")[:10]
    kind = event_type.removeprefix("soccer_live_")
    identity = {"date": date, "home": home, "away": away, "kind": kind}
    if kind == "goal" and home_score is not None and away_score is not None:
        identity.update({"side": side, "score": [home_score, away_score]})
    elif kind == "goal_cancelled":
        identity.update({
            "side": side,
            "from": [_score(data.get("previous_home_score")), _score(data.get("previous_away_score"))],
            "to": [home_score, away_score],
        })
    elif kind in {"match_started", "halftime", "second_half", "match_finished", "match_postponed", "match_cancelled", "lineup_available"}:
        pass
    else:
        identity.update({
            "minute": _text(data.get("minute") or data.get("clock")),
            "player": _text(data.get("player")),
            "team": side,
        })
    raw = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    return f"sl-{hashlib.sha256(raw).hexdigest()[:24]}"


def enrich_event(
    event_type: str,
    payload: dict | None,
    *,
    provider: str | None = None,
    source_entity_id: str | None = None,
    detected_at: str | None = None,
) -> dict:
    """Return a complete event payload while preserving provider fields."""
    result = dict(payload or {})
    result.setdefault("provider", provider or "unknown")
    result.setdefault("source_entity_id", source_entity_id)
    result.setdefault("detected_at", detected_at or datetime.now(timezone.utc).isoformat())
    result.setdefault("event_contract_version", EVENT_CONTRACT_VERSION)
    result.setdefault("is_correction", event_type == "soccer_live_goal_cancelled")
    result.setdefault("score_at_event", {
        "home": _score(result.get("home_score")),
        "away": _score(result.get("away_score")),
    })
    result.setdefault("event_uid", event_uid(event_type, result))
    return result
