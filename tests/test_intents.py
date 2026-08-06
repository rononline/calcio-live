import importlib.util
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "intents.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_intents", PATH)
M = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M)


def _team_sensor(**over):
    base = {
        "sensor_type": "team_match",
        "team_name": "Feyenoord",
        "next_match": None,
        "matches": [],
        "home_standing_summary": {},
    }
    base.update(over)
    return base


def test_next_match_home_and_away_localised():
    home = _team_sensor(next_match={
        "state": "pre", "home_team": "Feyenoord", "away_team": "Ajax", "date": "08-08-2026 20:00",
    })
    en = M.next_match_response([home], "Feyenoord", "en")
    assert "Feyenoord play Ajax at home" in en and "Saturday 20:00" in en
    nl = M.next_match_response([home], "feyenoord", "nl")
    assert "thuis tegen Ajax" in nl and "zaterdag 20:00" in nl

    away = _team_sensor(next_match={
        "state": "pre", "home_team": "PSV", "away_team": "Feyenoord", "date": "09-08-2026 14:30",
    })
    assert "away at PSV" in M.next_match_response([away], "Feyenoord", "en")


def test_next_match_no_team_uses_only_tracked_team_but_asks_when_ambiguous():
    one = _team_sensor(next_match={"state": "pre", "home_team": "Feyenoord", "away_team": "Ajax", "date": "08-08-2026 20:00"})
    assert "Feyenoord" in M.next_match_response([one], None, "en")
    two = [one, _team_sensor(team_name="Ajax")]
    assert M.next_match_response(two, None, "en") == "Which team do you mean?"


def test_unknown_team_and_no_upcoming():
    s = _team_sensor(next_match={"state": "pre", "home_team": "Feyenoord", "away_team": "Ajax", "date": "08-08-2026 20:00"})
    assert "don't track" in M.next_match_response([s], "Barcelona", "en")
    empty = _team_sensor(next_match=None, matches=[])
    assert "no upcoming match" in M.next_match_response([empty], "Feyenoord", "en")


def test_score_live_recent_and_none():
    live = _team_sensor(matches=[{"state": "in", "home_team": "Feyenoord", "away_team": "Ajax",
                                  "home_score": "2", "away_score": "1", "clock": "67'"}])
    assert "2–1" in M.score_response([live], "Feyenoord", "en") and "67'" in M.score_response([live], "Feyenoord", "en")

    won = _team_sensor(matches=[{"state": "post", "home_team": "Feyenoord", "away_team": "Charleroi",
                                 "home_score": "3", "away_score": "1", "date_iso": "2026-08-01T18:00:00Z"}])
    r = M.score_response([won], "Feyenoord", "en")
    assert "won" in r and "3–1" in r
    assert "verloor" in M.score_response([_team_sensor(matches=[{"state": "post", "home_team": "Ajax",
        "away_team": "Feyenoord", "home_score": "2", "away_score": "0", "date_iso": "2026-08-01T18:00:00Z"}])], "Feyenoord", "nl")

    assert "no recent match" in M.score_response([_team_sensor(matches=[])], "Feyenoord", "en")


def test_standing_from_summary():
    s = _team_sensor(home_standing_summary={"rank": 2, "points": 7})
    assert M.standing_response([s], "Feyenoord", "en") == "Feyenoord are 2nd with 7 points."
    assert M.standing_response([s], "Feyenoord", "nl") == "Feyenoord staat 2e met 7 punten."
    assert "don't have a league standing" in M.standing_response([_team_sensor(home_standing_summary={})], "Feyenoord", "en")


def test_language_fallback_to_english():
    # An unsupported language (de) falls back to the English templates.
    s = _team_sensor(home_standing_summary={"rank": 1, "points": 9})
    assert M.standing_response([s], "Feyenoord", "de") == "Feyenoord are 1st with 9 points."
