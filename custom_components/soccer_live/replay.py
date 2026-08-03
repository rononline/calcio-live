"""Provider-neutral match snapshot recording and replay helpers."""

from __future__ import annotations

from datetime import datetime, timezone

REPLAY_LIMIT = 180
_MATCH_FIELDS = (
    "event_id",
    "date",
    "date_iso",
    "provider",
    "home_id",
    "away_id",
    "home_team",
    "away_team",
    "home_score",
    "away_score",
    "state",
    "status",
    "match_phase",
    "clock",
    "league_name",
    "competition_name",
    "key_events",
    "lineup_home",
    "lineup_away",
)


def replay_match(matches: list[dict] | None) -> dict | None:
    """Select the live or nearest upcoming fixture worth recording."""
    candidates = [item for item in (matches or []) if isinstance(item, dict)]
    if not candidates:
        return None
    live = next(
        (
            item
            for item in candidates
            if item.get("state") in {"in", "live"}
            or item.get("match_phase") in {"first_half", "halftime", "second_half"}
        ),
        None,
    )
    if live:
        return live
    upcoming = [
        item
        for item in candidates
        if item.get("state") not in {"post"}
        and item.get("match_phase") not in {
            "finished",
            "cancelled",
            "postponed",
        }
    ]
    return min(
        upcoming or candidates,
        key=lambda item: str(item.get("date_iso") or item.get("date") or "9"),
    )


def compact_snapshot(match: dict, captured_at: str | None = None) -> dict:
    """Keep replay data compact and JSON-safe."""
    snapshot = {
        key: match.get(key)
        for key in _MATCH_FIELDS
        if match.get(key) not in (None, "", [], {})
    }
    snapshot["captured_at"] = captured_at or datetime.now(timezone.utc).isoformat()
    return snapshot


def snapshot_identity(snapshot: dict | None) -> tuple:
    """Return fields whose change makes a replay snapshot meaningful."""
    value = snapshot or {}
    return (
        str(value.get("event_id") or ""),
        value.get("home_score"),
        value.get("away_score"),
        value.get("state"),
        value.get("status"),
        value.get("match_phase"),
        tuple(
            (
                item.get("type"),
                item.get("minute") or item.get("clock"),
                item.get("player"),
                item.get("team"),
            )
            for item in value.get("key_events") or []
            if isinstance(item, dict)
        ),
        tuple(
            str(
                item.get("id") or item.get("name") or item
                if isinstance(item, dict)
                else item
            )
            for item in value.get("lineup_home") or []
        ),
        tuple(
            str(
                item.get("id") or item.get("name") or item
                if isinstance(item, dict)
                else item
            )
            for item in value.get("lineup_away") or []
        ),
    )


def validate_replay(value, limit: int = REPLAY_LIMIT) -> list[dict]:
    """Validate imported/stored replay snapshots."""
    if isinstance(value, dict):
        value = value.get("snapshots")
    if not isinstance(value, list):
        return []
    snapshots = []
    for item in value:
        if not isinstance(item, dict):
            continue
        if not item.get("home_team") or not item.get("away_team"):
            continue
        snapshots.append(compact_snapshot(item, item.get("captured_at")))
    return snapshots[-limit:]


def _base_payload(snapshot: dict) -> dict:
    return {
        "simulated": True,
        "replayed": True,
        "provider": "replay",
        "source": "soccer_live.play_match_replay",
        "timestamp": snapshot.get("captured_at"),
        "event_id": snapshot.get("event_id") or "replayed-match",
        "home_team": snapshot.get("home_team"),
        "away_team": snapshot.get("away_team"),
        "home_score": snapshot.get("home_score", 0),
        "away_score": snapshot.get("away_score", 0),
        "match_phase": snapshot.get("match_phase"),
        "clock": snapshot.get("clock"),
        "league_name": snapshot.get("league_name")
        or snapshot.get("competition_name"),
    }


def replay_events(previous: dict | None, current: dict) -> list[tuple[str, dict]]:
    """Derive Home Assistant events from two consecutive snapshots."""
    payload = _base_payload(current)
    events: list[tuple[str, dict]] = []
    old_phase = (previous or {}).get("match_phase")
    phase = current.get("match_phase")
    phase_events = {
        "first_half": "soccer_live_match_started",
        "halftime": "soccer_live_halftime",
        "second_half": "soccer_live_second_half",
        "finished": "soccer_live_match_finished",
        "postponed": "soccer_live_match_postponed",
        "cancelled": "soccer_live_match_cancelled",
    }
    if phase and phase != old_phase and phase in phase_events:
        events.append((phase_events[phase], payload))

    had_lineup = bool(
        (previous or {}).get("lineup_home")
        or (previous or {}).get("lineup_away")
    )
    has_lineup = bool(current.get("lineup_home") or current.get("lineup_away"))
    if has_lineup and not had_lineup and phase not in {
        "finished",
        "cancelled",
        "postponed",
    }:
        events.append(
            (
                "soccer_live_lineup_available",
                {
                    **payload,
                    "home_players": current.get("lineup_home") or [],
                    "away_players": current.get("lineup_away") or [],
                },
            )
        )

    previous_events = previous.get("key_events") or [] if previous else []
    known = {
        (
            str(item.get("type") or ""),
            str(item.get("minute") or item.get("clock") or ""),
            str(item.get("player") or ""),
            str(item.get("team") or ""),
        )
        for item in previous_events
        if isinstance(item, dict)
    }
    for item in current.get("key_events") or []:
        if not isinstance(item, dict):
            continue
        identity = (
            str(item.get("type") or ""),
            str(item.get("minute") or item.get("clock") or ""),
            str(item.get("player") or ""),
            str(item.get("team") or ""),
        )
        if identity in known:
            continue
        kind = str(item.get("type") or item.get("type_text") or "").lower()
        event_type = (
            "soccer_live_goal"
            if item.get("scoring_play") or "goal" in kind
            else "soccer_live_red_card"
            if "red" in kind
            else "soccer_live_yellow_card"
            if "yellow" in kind
            else "soccer_live_substitution"
            if "subst" in kind
            else None
        )
        if event_type:
            events.append(
                (
                    event_type,
                    {
                        **payload,
                        "player": item.get("player"),
                        "team": item.get("team"),
                        "minute": item.get("minute") or item.get("clock"),
                    },
                )
            )

    if previous:
        old_home = int(previous.get("home_score") or 0)
        old_away = int(previous.get("away_score") or 0)
        new_home = int(current.get("home_score") or 0)
        new_away = int(current.get("away_score") or 0)
        if (new_home > old_home or new_away > old_away) and not any(
            event_type == "soccer_live_goal" for event_type, _ in events
        ):
            events.append(("soccer_live_goal", payload))
        if new_home < old_home or new_away < old_away:
            side = "home" if new_home < old_home else "away"
            events.append(("soccer_live_goal_cancelled", {
                **payload,
                "team": current.get(f"{side}_team"),
                "previous_home_score": old_home,
                "previous_away_score": old_away,
                "goals_removed": (old_home - new_home) + (old_away - new_away),
                "reason": "score_correction",
            }))

    from .event_contract import enrich_event
    return [
        (
            event_type,
            enrich_event(
                event_type,
                event_payload,
                provider="replay",
                source_entity_id="soccer_live.play_match_replay",
                detected_at=current.get("captured_at"),
            ),
        )
        for event_type, event_payload in events
    ]


def demo_replay(home_team="Feyenoord", away_team="Tegenstander") -> list[dict]:
    """Return a deterministic full lifecycle when no recording exists."""
    base = {
        "event_id": "demo-replay",
        "home_team": home_team,
        "away_team": away_team,
        "league_name": "Testwedstrijd",
    }
    return [
        compact_snapshot({
            **base,
            "home_score": 0,
            "away_score": 0,
            "match_phase": "scheduled",
            "lineup_home": [{"name": "Testspeler"}],
            "lineup_away": [{"name": "Tegenspeler"}],
        }),
        compact_snapshot({**base, "home_score": 0, "away_score": 0, "match_phase": "first_half", "clock": "1"}),
        compact_snapshot({
            **base,
            "home_score": 1,
            "away_score": 0,
            "match_phase": "first_half",
            "clock": "23",
            "key_events": [{"type": "goal", "scoring_play": True, "minute": 23, "player": "Testspeler", "team": home_team}],
        }),
        compact_snapshot({**base, "home_score": 1, "away_score": 0, "match_phase": "halftime", "clock": "45"}),
        compact_snapshot({**base, "home_score": 1, "away_score": 0, "match_phase": "second_half", "clock": "46"}),
        compact_snapshot({
            **base,
            "home_score": 1,
            "away_score": 1,
            "match_phase": "second_half",
            "clock": "67",
            "key_events": [
                {"type": "goal", "scoring_play": True, "minute": 23, "player": "Testspeler", "team": home_team},
                {"type": "goal", "scoring_play": True, "minute": 67, "player": "Tegenspeler", "team": away_team},
            ],
        }),
        compact_snapshot({**base, "home_score": 1, "away_score": 1, "match_phase": "finished", "clock": "90"}),
    ]
