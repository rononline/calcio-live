import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
FIXTURES = Path(__file__).parent / "fixtures"


def load_parser(name):
    path = ROOT / "custom_components" / "soccer_live" / "parsers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"contract_{name}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Hass:
    class config:
        time_zone = "Europe/Amsterdam"
        language = "nl"


def payload(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def assert_public_match_contract(match):
    required = {
        "event_id", "date", "date_iso", "home_team", "away_team",
        "home_score", "away_score", "state", "league_name", "venue",
    }
    assert not required.difference(match)
    assert isinstance(match["event_id"], str)
    assert match["state"] in {"pre", "in", "post"}
    assert isinstance(match.get("key_events", []), list)


def test_espn_fixture_keeps_public_match_contract():
    parser = load_parser("scoreboard")
    result = parser.process_match_data(payload("scoreboard_minimal.json"), Hass())
    assert len(result["matches"]) == 1
    assert_public_match_contract(result["matches"][0])


def test_api_football_live_fixture_keeps_public_match_contract():
    parser = load_parser("api_football")
    result = parser.process_fixture_data(
        payload("api_football_live_minimal.json"), Hass(), team_id="209"
    )
    match = result["matches"][0]
    assert_public_match_contract(match)
    assert match["state"] == "in"
    assert match["clock"] == "67"
    assert match["league_name"] == "Oefenwedstrijd"
