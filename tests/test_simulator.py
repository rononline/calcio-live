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
