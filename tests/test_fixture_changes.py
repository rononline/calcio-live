import importlib.util
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "fixture_changes.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_fixture_changes", PATH)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def _attrs(**updates):
    match = {
        "event_id": "42",
        "canonical_id": "fixture-42",
        "state": "pre",
        "date_iso": "2026-08-09T10:15:00+00:00",
        "venue": "Het Kasteel",
        "home_team": "Sparta Rotterdam",
        "away_team": "Feyenoord",
        "league_name": "Eredivisie",
    }
    match.update(updates)
    return {"matches": [match]}


def test_detects_kickoff_venue_and_opponent_changes():
    changes = module.fixture_changes(
        _attrs(),
        _attrs(
            date_iso="2026-08-09T12:30:00+00:00",
            venue="De Kuip",
            home_team="Feyenoord",
            away_team="Sparta Rotterdam",
        ),
    )
    assert [event for event, _data in changes] == [
        "soccer_live_kickoff_changed",
        "soccer_live_venue_changed",
        "soccer_live_opponent_changed",
    ]
    assert changes[0][1]["previous_date"].endswith("10:15:00+00:00")


def test_ignores_first_observation_placeholders_and_finished_matches():
    assert module.fixture_changes({}, _attrs()) == []
    assert module.fixture_changes(_attrs(venue="N/A"), _attrs(venue="De Kuip")) == []
    assert module.fixture_changes(_attrs(), _attrs(state="post", venue="De Kuip")) == []
