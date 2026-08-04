import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "details.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_details", MODULE_PATH)
details = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(details)


def test_find_and_classify_match_details():
    attrs = {
        "next_match": {"event_id": "2", "key_events": []},
        "matches": [
            {"event_id": "1"},
            {"event_id": "2", "key_events": [{"type": "goal"}]},
        ],
    }
    found = details.find_match(attrs, 2)
    assert found is attrs["next_match"]
    assert details.has_match_details(found) is False
    assert details.has_match_details(attrs["matches"][1]) is True
    detached = details.public_match_details(attrs["matches"][1])
    detached["key_events"].append({"type": "card"})
    assert len(attrs["matches"][1]["key_events"]) == 1


def test_detail_marker_counts_even_without_provider_sections():
    assert details.has_match_details({"event_id": "1", "detail_loaded": True})
    assert not details.has_match_details({
        "event_id": "1",
        "prediction": {"home": 55, "draw": 25, "away": 20},
        "head_to_head": [{"event_id": "old"}],
    })
    assert details.find_match({}, "missing") is None
