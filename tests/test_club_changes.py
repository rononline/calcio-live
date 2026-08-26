import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "club_changes.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_club_changes", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
club_snapshot = MODULE.club_snapshot
diff_club = MODULE.diff_club
newly_available_lineups = MODULE.newly_available_lineups
lineup_difference = MODULE.lineup_difference


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
    base = {"matches": [{"event_id": "10", "state": "pre", "lineup_home": [], "lineup_away": []}]}
    current = {"matches": [{"event_id": "10", "state": "pre", "lineup_confirmed": True, "lineup_home": [{"name": "A"}], "lineup_away": []}]}
    assert [item["event_id"] for item in newly_available_lineups(base, current)] == ["10"]
    assert newly_available_lineups(current, current) == []
    assert newly_available_lineups({}, current) == []


def test_newly_available_lineups_ignores_early_prediction_but_accepts_near_kickoff():
    from datetime import datetime, timedelta, timezone

    base = {"matches": [{"event_id": "10", "state": "pre", "lineup_home": [], "lineup_away": []}]}
    # A probable XI days out, not confirmed and not near kick-off: no event.
    prediction = {"matches": [{"event_id": "10", "state": "pre", "date_iso": "2099-01-01T12:00:00Z", "lineup_home": [{"name": "A"}], "lineup_away": []}]}
    assert newly_available_lineups(base, prediction) == []
    # The official sheet drops shortly before kick-off: event fires.
    soon = (datetime.now(timezone.utc) + timedelta(minutes=45)).isoformat()
    official = {"matches": [{"event_id": "10", "state": "pre", "date_iso": soon, "lineup_home": [{"name": "A"}], "lineup_away": []}]}
    assert [item["event_id"] for item in newly_available_lineups(base, official)] == ["10"]


def test_finished_match_enrichment_never_fires_lineup_event():
    base = {"matches": [{"event_id": "10", "state": "post", "lineup_home": [], "lineup_away": []}]}
    enriched = {
        "matches": [{
            "event_id": "10",
            "state": "post",
            "lineup_home": [{"name": "A"}],
            "lineup_away": [{"name": "B"}],
        }]
    }
    assert newly_available_lineups(base, enriched) == []


def test_lineup_difference_compares_expected_with_official_starters():
    difference = lineup_difference({
        "home_id": 209,
        "home_team": "Feyenoord",
        "expected_lineup_home": [{"name": "A"}, {"name": "B"}],
        "lineup_home": [
            {"name": "A", "starter": True},
            {"name": "C", "starter": True},
            {"name": "B", "starter": False},
        ],
    }, team_id=209)
    assert difference["unexpected_starters"] == ["C"]
    assert difference["missing_expected"] == ["B"]
