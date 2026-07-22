import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "club_changes.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_club_changes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
club_snapshot = MODULE.club_snapshot
diff_club = MODULE.diff_club
newly_available_lineups = MODULE.newly_available_lineups


def test_club_snapshot_and_diff_detect_meaningful_changes():
    previous = {
        "coach": "Old Coach",
        "squad": [{"id": 1, "name": "A", "injured": True, "market_value": 10_000_000}],
        "injuries": [{"player": "A"}],
        "transfers": [],
    }
    current = {
        "coach": "New Coach",
        "squad": [{"id": 1, "name": "A", "market_value": 10_200_000}, {"id": 2, "name": "B"}],
        "injuries": [],
        "transfers": [{"player_id": 2, "player": "B", "date": "2026-07-22", "from": "X", "to": "Y", "direction": "in"}],
    }
    assert club_snapshot(previous)["injured"] == {"1"}
    changes = diff_club(previous, current)
    assert {item["type"] for item in changes} == {
        "transfer_added", "player_available", "coach_changed", "squad_added", "market_value_changed"
    }
    assert diff_club(None, current) == []


def test_market_value_change_ignores_small_provider_fluctuations():
    previous = {"squad": [{"id": 1, "name": "A", "market_value": 10_000_000}]}
    current = {"squad": [{"id": 1, "name": "A", "market_value": 10_050_000}]}
    assert diff_club(previous, current) == []


def test_newly_available_lineups_only_fires_on_transition():
    base = {"matches": [{"event_id": "10", "lineup_home": [], "lineup_away": []}]}
    current = {"matches": [{"event_id": "10", "lineup_home": [{"name": "A"}], "lineup_away": []}]}
    assert [item["event_id"] for item in newly_available_lineups(base, current)] == ["10"]
    assert newly_available_lineups(current, current) == []
    assert newly_available_lineups({}, current) == []
