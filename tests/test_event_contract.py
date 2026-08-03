import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "event_contract",
    Path(__file__).parents[1]
    / "custom_components"
    / "soccer_live"
    / "event_contract.py",
)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
enrich_event = module.enrich_event
event_uid = module.event_uid


def test_goal_uid_is_provider_neutral_and_uses_score_transition():
    common = {
        "date_iso": "2026-08-02T13:00:00Z",
        "home_team": "Feyenoord",
        "away_team": "Atalanta",
        "team": "Feyenoord",
        "home_score": 2,
        "away_score": 1,
    }
    api = {**common, "event_id": "154", "player": "S. van Persie", "minute": "81"}
    fotmob = {**common, "event_id": "999", "player": "Shaqueel van Persie", "minute": 81}
    assert event_uid("soccer_live_goal", api) == event_uid("soccer_live_goal", fotmob)


def test_enrich_event_adds_contract_metadata_and_correction_flag():
    result = enrich_event(
        "soccer_live_goal_cancelled",
        {"home_team": "A", "away_team": "B", "home_score": 0, "away_score": 0},
        provider="espn",
        source_entity_id="sensor.match",
        detected_at="2026-08-03T10:00:00+00:00",
    )
    assert result["provider"] == "espn"
    assert result["source_entity_id"] == "sensor.match"
    assert result["score_at_event"] == {"home": 0, "away": 0}
    assert result["is_correction"] is True
    assert result["event_uid"].startswith("sl-")
