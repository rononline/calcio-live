import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "identity.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_identity", MODULE_PATH)
identity = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(identity)


def test_identity_matches_provider_name_variants():
    espn = {
        "event_id": "espn-1",
        "date_iso": "2026-08-09T12:15:00Z",
        "home_team": "Feyenoord Rotterdam",
        "away_team": "Sparta Rotterdam",
        "competition_name": "Dutch Eredivisie",
        "season_info": 2026,
    }
    other = {
        "event_id": 999,
        "date_iso": "2026-08-09T14:15:00+02:00",
        "home_team": "Feyenoord Rotterdam FC",
        "away_team": "Sparta Rotterdam",
        "league_name": "Dutch Eredivisie",
        "season_info": 2026,
    }
    assert identity.fixture_identity(espn)["canonical_id"] == identity.fixture_identity(
        other
    )["canonical_id"]


def test_pair_identity_survives_reschedule_but_fixture_identity_changes():
    original = {
        "date_iso": "2026-08-09T12:15:00Z",
        "home_team": "Feyenoord",
        "away_team": "Sparta",
        "competition_name": "Eredivisie",
        "season_info": 2026,
    }
    moved = {**original, "date_iso": "2026-08-16T12:15:00Z"}
    left = identity.fixture_identity(original)
    right = identity.fixture_identity(moved)
    assert left["canonical_pair_id"] == right["canonical_pair_id"]
    assert left["canonical_id"] != right["canonical_id"]
