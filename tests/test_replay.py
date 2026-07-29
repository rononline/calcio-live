import importlib.util
from pathlib import Path

MODULE_PATH = (
    Path(__file__).parents[1]
    / "custom_components"
    / "soccer_live"
    / "replay.py"
)
SPEC = importlib.util.spec_from_file_location("soccer_live_replay", MODULE_PATH)
replay = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(replay)


def _snapshot(**overrides):
    return {
        "event_id": "fixture-1",
        "home_team": "Feyenoord",
        "away_team": "Sparta",
        "home_score": 0,
        "away_score": 0,
        "match_phase": "first_half",
        **overrides,
    }


def test_replay_prefers_live_and_validates_snapshots():
    selected = replay.replay_match(
        [
            _snapshot(event_id="future", state="pre", match_phase="scheduled"),
            _snapshot(event_id="live", state="in"),
        ]
    )
    assert selected["event_id"] == "live"
    assert replay.validate_replay(
        {"snapshots": [None, {}, _snapshot()]}
    )[0]["event_id"] == "fixture-1"


def test_replay_derives_lifecycle_and_goal_events():
    previous = _snapshot(clock="20", key_events=[])
    current = _snapshot(
        clock="21",
        home_score=1,
        key_events=[
            {
                "type": "goal",
                "scoring_play": True,
                "minute": 21,
                "player": "Speler",
                "team": "Feyenoord",
            }
        ],
    )
    events = replay.replay_events(previous, current)
    assert [event_type for event_type, _ in events] == ["soccer_live_goal"]
    assert events[0][1]["simulated"] is True

    finished = replay.replay_events(
        current,
        _snapshot(
            home_score=1,
            match_phase="finished",
            key_events=current["key_events"],
        ),
    )
    assert [event_type for event_type, _ in finished] == [
        "soccer_live_match_finished"
    ]


def test_demo_replay_covers_a_complete_match():
    snapshots = replay.demo_replay()
    assert snapshots[0]["match_phase"] == "scheduled"
    assert snapshots[0]["lineup_home"]
    assert snapshots[1]["match_phase"] == "first_half"
    assert snapshots[-1]["match_phase"] == "finished"
    assert len(snapshots) >= 5
    assert replay.replay_events(None, snapshots[0])[0][0] == (
        "soccer_live_lineup_available"
    )
