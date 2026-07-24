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


def test_phase_event_mapping():
    assert MODULE.phase_event("halftime") == "soccer_live_halftime"
    assert MODULE.phase_event("second_half") == "soccer_live_second_half"
    assert MODULE.phase_event("postponed") == "soccer_live_match_postponed"
    assert MODULE.phase_event("cancelled") == "soccer_live_match_cancelled"
    # pre->in (match_started) and ->post (match_finished) are handled by state,
    # so those phases — and phases without their own event — return None.
    for phase in ("first_half", "finished", "scheduled", "extra_time", "penalties", "unknown"):
        assert MODULE.phase_event(phase) is None


def test_phase_transition_fires_once_and_not_on_first_observation():
    # Reproduces the sensor dispatcher's logic against the pure helpers.
    previous = {}

    def dispatch(match):
        mid = match["event_id"]
        phase = MODULE.match_phase(match)
        prev = previous.get(mid)
        event = MODULE.phase_event(phase)
        previous[mid] = phase
        return event if (event and prev is not None and prev != phase) else None

    # First time we see it already at halftime -> no event (no restart spam).
    assert dispatch({"event_id": "1", "state": "in", "status": "Halftime"}) is None
    # Still halftime -> nothing.
    assert dispatch({"event_id": "1", "state": "in", "status": "Halftime"}) is None
    # Transition into the second half -> fires exactly once.
    assert dispatch({"event_id": "1", "state": "in", "period": 2}) == "soccer_live_second_half"
    assert dispatch({"event_id": "1", "state": "in", "period": 2}) is None
    # A scheduled match that gets postponed -> fires.
    assert dispatch({"event_id": "2", "state": "pre"}) is None
    assert dispatch({"event_id": "2", "state": "pre", "status": "Postponed"}) == "soccer_live_match_postponed"
