import importlib.util
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "simulator.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_simulator", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_simulated_goal_is_marked_and_does_not_need_integration_state():
    event, payload = MODULE.simulated_event("goal", {
        "team_id": 10235, "home_team": "Feyenoord", "away_team": "Ajax",
        "home_score": 2, "away_score": 1, "player": "Testspeler", "minute": 67,
    }, now=datetime(2026, 7, 23, 12, 0, tzinfo=timezone.utc))
    assert event == "soccer_live_goal"
    assert payload["simulated"] is True
    assert payload["provider"] == "simulator"
    assert payload["player"] == "Testspeler"
    assert payload["timestamp"] == "2026-07-23T12:00:00+00:00"


def test_lifecycle_simulations_publish_normalized_phase():
    expected = {
        "match_started": "first_half", "halftime": "halftime",
        "second_half": "second_half", "match_finished": "finished",
        "postponed": "postponed", "cancelled": "cancelled",
    }
    for kind, phase in expected.items():
        _event, payload = MODULE.simulated_event(kind, {})
        assert payload["match_phase"] == phase


def test_yellow_card_and_substitution_are_simulatable():
    for kind, bus in (("yellow_card", "soccer_live_yellow_card"),
                      ("substitution", "soccer_live_substitution")):
        event, payload = MODULE.simulated_event(kind, {"player": "X", "minute": 55, "team": "Home"})
        assert event == bus
        assert payload["simulated"] is True
        assert payload["player"] == "X"
        assert payload["minute"] == 55


def _load(name):
    path = Path(__file__).parents[1] / "custom_components" / "soccer_live" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"soccer_live_{name}_x", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_simulated_event_is_actually_emitted_by_the_integration():
    """Guard against the simulator advertising events the integration never
    fires (an automation would pass in simulation but never trigger live).

    Events emitted by the state/detail dispatchers in sensor.py (kept in sync
    here) plus the phase-transition events from match_contract.PHASE_EVENTS."""
    state_and_detail = {
        "soccer_live_match_started", "soccer_live_match_finished",
        "soccer_live_goal", "soccer_live_yellow_card", "soccer_live_red_card",
        "soccer_live_goal_cancelled", "soccer_live_kickoff_changed",
        "soccer_live_venue_changed", "soccer_live_opponent_changed",
        "soccer_live_substitution", "soccer_live_lineup_available",
            "soccer_live_watchlist_event",
            "soccer_live_race_milestone",
        }
    emitted = state_and_detail | set(_load("match_contract").PHASE_EVENTS.values())
    for sim_type, (bus_event, _phase) in MODULE.EVENT_TYPES.items():
        assert bus_event in emitted, (
            f"simulator '{sim_type}' fires {bus_event}, which the integration never emits"
        )
