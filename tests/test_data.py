"""Tests for normalizing ESPN config-flow responses."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).parent.parent
DATA_MODULE = ROOT / "custom_components" / "soccer_live" / "data.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_data", DATA_MODULE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)
parse_competitions = MODULE.parse_competitions
parse_teams = MODULE.parse_teams


def test_parse_competitions_skips_malformed_entries():
    result = parse_competitions({
        "leagues": [
            None,
            "invalid",
            {"slug": "ned.1"},
            {"slug": "eng.1", "name": "Premier League"},
        ],
    })

    assert result == {"eng.1": "Premier League"}


def test_parse_teams_skips_malformed_entries():
    result = parse_teams({
        "sports": [{
            "leagues": [
                None,
                {
                    "teams": [
                        None,
                        {},
                        {"team": {"id": "1"}},
                        {
                            "team": {
                                "id": "246",
                                "displayName": "Feyenoord Rotterdam",
                            },
                        },
                    ],
                },
            ],
        }],
    })

    assert result == [{"id": "246", "displayName": "Feyenoord Rotterdam"}]
