import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "polling.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_polling", MODULE_PATH)
polling = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(polling)
adaptive_poll_interval = polling.adaptive_poll_interval
request_priority_plan = polling.request_priority_plan


NOW = datetime(2026, 8, 4, 18, 0, tzinfo=timezone.utc)


def match(state, offset=0, **extra):
    return {
        "state": state,
        "date_iso": (NOW + timedelta(minutes=offset)).isoformat(),
        **extra,
    }


def test_adaptive_polling_follows_match_phase():
    assert adaptive_poll_interval([], base_seconds=180, live_seconds=30, now=NOW) == (180, "normal")
    assert adaptive_poll_interval([match("pre", 20)], base_seconds=180, live_seconds=30, now=NOW) == (60, "kickoff_soon")
    assert adaptive_poll_interval([match("pre", 120)], base_seconds=180, live_seconds=30, now=NOW) == (120, "matchday")
    assert adaptive_poll_interval([match("in", -60)], base_seconds=180, live_seconds=30, now=NOW) == (30, "live")
    assert adaptive_poll_interval([match("in", -60, period="HT")], base_seconds=180, live_seconds=30, now=NOW) == (60, "halftime")
    assert adaptive_poll_interval([match("post", -120)], base_seconds=180, live_seconds=30, now=NOW) == (60, "post_match")


def test_quota_pressure_overrides_aggressive_live_polling():
    quota = {"requests_limit_day": 100, "requests_current": 96}
    assert adaptive_poll_interval([match("in")], base_seconds=180, live_seconds=15, quota=quota, now=NOW) == (300, "quota_critical")
    exhausted = {"requests_limit_day": 100, "requests_current": 100}
    assert adaptive_poll_interval([match("in")], base_seconds=180, live_seconds=15, quota=exhausted, now=NOW) == (3600, "quota_exhausted")


def test_bad_dates_and_unknown_quota_are_safe():
    rows = [{"state": "pre", "date_iso": "not-a-date"}]
    assert adaptive_poll_interval(rows, base_seconds=300, live_seconds=60, quota={"requests_current": "?"}, now=NOW) == (300, "normal")


def test_request_plan_prioritizes_live_data_and_defers_optional_calls():
    normal = request_priority_plan([match("in")])
    assert normal["phase"] == "live"
    assert normal["allowed"][:3] == ["timeline", "lineup", "statistics"]
    constrained = request_priority_plan(
        [match("in")],
        quota={"requests_limit_day": 100, "requests_current": 90},
    )
    assert constrained["quota_level"] == "constrained"
    assert constrained["allowed"] == ["timeline", "lineup", "statistics"]
    exhausted = request_priority_plan(
        [match("pre")],
        quota={"requests_limit_day": 100, "requests_current": 100},
    )
    assert exhausted["allowed"] == []
    assert "prematch" in exhausted["deferred"]
