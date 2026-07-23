import importlib.util
from pathlib import Path


PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "match_contract.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_match_contract", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_match_phase_normalizes_provider_states():
    assert MODULE.match_phase({"state": "pre"}) == "scheduled"
    assert MODULE.match_phase({"state": "in", "status": "Halftime"}) == "halftime"
    assert MODULE.match_phase({"state": "in", "period": 2}) == "second_half"
    assert MODULE.match_phase({"state": "in", "status": "Penalty shootout"}) == "penalties"
    assert MODULE.match_phase({"state": "post"}) == "finished"
    assert MODULE.match_phase({"state": "pre", "status": "Postponed"}) == "postponed"


def test_current_match_is_separate_from_next_match():
    matches = [
        {"event_id": "1", "state": "in", "status": "Second half"},
        {"event_id": "2", "state": "pre"},
    ]
    assert MODULE.current_match(matches)["event_id"] == "1"
    assert MODULE.annotate_match(matches[0])["match_phase"] == "second_half"
    assert MODULE.current_match([matches[1]]) is None
