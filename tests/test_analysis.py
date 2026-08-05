import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "analysis.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_analysis", MODULE_PATH)
analysis = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(analysis)


def _match(**values):
    return {
        "event_id": "fixture-1",
        "home_id": 1,
        "away_id": 2,
        "home_team": "Feyenoord",
        "away_team": "Sparta",
        "state": "pre",
        **values,
    }


def test_preview_analysis_only_publishes_observed_factors():
    preview = analysis.preview_analysis(_match(
        home_form="WWDLW",
        away_form="LDWLL",
        home_rank=2,
        away_rank=9,
        head_to_head=[{"home_score": 2, "away_score": 0}],
    ))
    assert [item["code"] for item in preview["factors"]] == [
        "form", "standings", "head_to_head"
    ]
    assert analysis.preview_analysis(_match()) is None


def test_event_momentum_requires_real_attacking_signals():
    momentum = analysis.match_momentum(_match(
        state="in",
        key_events=[
            {"minute": 11, "type": "Shot on target", "team_id": 1},
            {"minute": 14, "type": "Corner", "team_id": 2},
            {"minute": 16, "type": "Goal", "team_id": 1, "scoring_play": True},
        ],
    ))
    assert momentum["method"] == "event_pressure"
    assert momentum["signal_count"] == 3
    assert momentum["points"][0]["net"] == 2
    assert analysis.match_momentum(_match(state="in", key_events=[])) is None


def test_post_match_analysis_marks_equalizer_and_decisive_goal_correctly():
    review = analysis.post_match_analysis(_match(
        state="post",
        home_score=2,
        away_score=1,
        player_of_the_match={"name": "A"},
        key_events=[
            {"minute": 10, "type": "Goal", "team_id": 1, "team": "Feyenoord", "player": "A", "scoring_play": True},
            {"minute": 45, "type": "Goal", "team_id": 2, "team": "Sparta", "player": "B", "scoring_play": True},
            {"minute": 81, "type": "Goal", "team_id": 1, "team": "Feyenoord", "player": "C", "scoring_play": True},
        ],
    ))
    assert [item["code"] for item in review["milestones"]] == [
        "opening_goal", "equalizer", "goal"
    ]
    assert review["turning_point"]["code"] == "decisive_goal"
    assert review["turning_point"]["player"] == "C"


def test_installation_check_surfaces_auth_season_and_quota_actions():
    report = analysis.installation_check(
        configured_entities=3,
        entities_with_data=0,
        auth_failed=True,
        last_error=True,
        capabilities={},
        season_transition={"status": "stale"},
        quota_plan={"quota_level": "exhausted"},
    )
    assert report["status"] == "action_required"
    assert set(report["failures"]) == {
        "authentication", "provider_data", "season", "quota"
    }
