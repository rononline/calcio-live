"""Provider-neutral fixture-change detection."""

from __future__ import annotations


def _matches(attributes: dict | None) -> dict[str, dict]:
    attributes = attributes or {}
    items = list(attributes.get("matches") or [])
    for key in ("current_match", "next_match"):
        if isinstance(attributes.get(key), dict):
            items.append(attributes[key])
    result = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        identity = str(
            item.get("event_id")
            or item.get("provider_event_id")
            or item.get("canonical_pair_id")
            or item.get("canonical_id")
            or ""
        )
        if identity:
            result[identity] = item
    return result


def _usable(value) -> str:
    text = str(value or "").strip()
    return "" if text in {"N/A", "None", "null"} else text


def fixture_changes(
    previous_attributes: dict | None,
    current_attributes: dict | None,
) -> list[tuple[str, dict]]:
    """Return meaningful changes for fixtures observed in two consecutive polls."""
    previous = _matches(previous_attributes)
    if not previous:
        return []
    changes = []
    for identity, current in _matches(current_attributes).items():
        old = previous.get(identity)
        if not old or current.get("state") == "post":
            continue
        common = {
            "event_id": current.get("event_id"),
            "canonical_id": current.get("canonical_id"),
            "home_team": current.get("home_team"),
            "away_team": current.get("away_team"),
            "league_name": current.get("league_name") or current.get("competition_name"),
        }
        old_date = _usable(old.get("date_iso") or old.get("date"))
        new_date = _usable(current.get("date_iso") or current.get("date"))
        if old_date and new_date and old_date != new_date:
            changes.append(("soccer_live_kickoff_changed", {
                **common,
                "previous_date": old_date,
                "date": new_date,
                "change_type": "kickoff",
            }))
        old_venue = _usable(old.get("venue"))
        new_venue = _usable(current.get("venue"))
        if old_venue and new_venue and old_venue != new_venue:
            changes.append(("soccer_live_venue_changed", {
                **common,
                "previous_venue": old_venue,
                "venue": new_venue,
                "change_type": "venue",
            }))
        old_pair = (_usable(old.get("home_team")), _usable(old.get("away_team")))
        new_pair = (_usable(current.get("home_team")), _usable(current.get("away_team")))
        if all(old_pair + new_pair) and old_pair != new_pair:
            changes.append(("soccer_live_opponent_changed", {
                **common,
                "previous_home_team": old_pair[0],
                "previous_away_team": old_pair[1],
                "change_type": "opponent",
            }))
    return changes
