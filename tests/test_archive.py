import importlib.util
import json
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "archive.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_archive", MODULE_PATH)
archive = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(archive)


def test_validate_archive_parses_deduplicates_and_orders():
    raw = json.dumps({
        "matches": [
            {
                "event_id": "1",
                "date_iso": "2026-01-01T12:00:00+00:00",
                "home_team": "A",
                "away_team": "B",
            },
            {
                "event_id": "2",
                "date_iso": "2026-02-01T12:00:00+00:00",
                "home_team": "A",
                "away_team": "C",
            },
            {"event_id": "bad"},
        ]
    })
    assert [item["event_id"] for item in archive.validate_archive(raw)] == ["2", "1"]


def test_export_archive_round_trips():
    matches = [{"home_team": "Feyenoord", "away_team": "Sparta", "event_id": "1"}]
    exported = archive.export_archive(matches)
    assert json.loads(exported)["version"] == 1
    assert json.loads(exported)["schema"] == archive.ARCHIVE_CONTRACT
    assert archive.validate_archive(exported)[0]["event_id"] == "1"


def test_dutch_legacy_archive_is_normalized():
    result = archive.validate_archive({"uitslagen": [{
        "datum": "10-05-2026",
        "thuis": "Feyenoord",
        "uit": "AZ",
        "uitslag": "3-1",
        "competitie": "Eredivisie",
    }]})[0]
    assert result["date_iso"] == "2026-05-10"
    assert (result["home_score"], result["away_score"]) == (3, 1)
    assert result["competition_name"] == "Eredivisie"
