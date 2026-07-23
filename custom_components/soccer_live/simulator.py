"""Safe Home Assistant event simulator for testing automations."""

from datetime import datetime, timezone


EVENT_TYPES = {
    "match_started": ("soccer_live_match_started", "first_half"),
    "goal": ("soccer_live_goal", None),
    "red_card": ("soccer_live_red_card", None),
    "halftime": ("soccer_live_halftime", "halftime"),
    "second_half": ("soccer_live_second_half", "second_half"),
    "match_finished": ("soccer_live_match_finished", "finished"),
    "lineup_available": ("soccer_live_lineup_available", "scheduled"),
    "postponed": ("soccer_live_match_postponed", "postponed"),
    "cancelled": ("soccer_live_match_cancelled", "cancelled"),
}


def simulated_event(event_type, data, now=None):
    """Return (bus event name, payload), without mutating integration state."""
    bus_event, phase = EVENT_TYPES[event_type]
    payload = {
        "simulated": True,
        "provider": "simulator",
        "source": "soccer_live.simulate_match_event",
        "timestamp": (now or datetime.now(timezone.utc)).isoformat(),
        "event_id": data.get("event_id") or "simulated-match",
        "team_id": data.get("team_id"),
        "home_team": data.get("home_team") or "Feyenoord",
        "away_team": data.get("away_team") or "Tegenstander",
        "home_score": data.get("home_score", 0),
        "away_score": data.get("away_score", 0),
    }
    if phase:
        payload["match_phase"] = phase
    for key in ("player", "minute", "team", "home_players", "away_players"):
        if data.get(key) is not None:
            payload[key] = data[key]
    return bus_event, payload
