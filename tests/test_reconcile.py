import importlib.util
import sys
from pathlib import Path

PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "reconcile.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_reconcile", PATH)
M = importlib.util.module_from_spec(SPEC)
# @dataclass looks the module up in sys.modules, so register it before exec.
sys.modules["soccer_live_reconcile"] = M
SPEC.loader.exec_module(M)


def test_first_provider_fires_single_source():
    r = M.TeamReconciler()
    d = r.observe("sl-goal-1", "soccer_live_goal", "espn", now=100.0)
    assert d.fire is True
    assert d.confidence == "single_source"
    assert d.sources == ["espn"]


def test_second_provider_corroborates_and_is_suppressed():
    r = M.TeamReconciler()
    r.observe("sl-goal-1", "soccer_live_goal", "espn", now=100.0)
    d = r.observe("sl-goal-1", "soccer_live_goal", "api_football", now=110.0)
    assert d.fire is False
    assert d.corroborated is True
    assert d.confidence == "corroborated"
    assert d.sources == ["api_football", "espn"]
    assert d.event_type == "soccer_live_goal"


def test_same_provider_repeat_is_suppressed_without_corroboration():
    r = M.TeamReconciler()
    r.observe("sl-goal-1", "soccer_live_goal", "espn", now=100.0)
    d = r.observe("sl-goal-1", "soccer_live_goal", "espn", now=105.0)
    assert d.fire is False and d.corroborated is False


def test_outside_window_is_treated_as_a_new_event():
    r = M.TeamReconciler()
    r.observe("sl-goal-1", "soccer_live_goal", "espn", now=100.0)
    # api_football reports the same uid but far outside the window -> new event.
    d = r.observe("sl-goal-1", "soccer_live_goal", "api_football", now=100.0 + M.DEFAULT_WINDOW + 1)
    assert d.fire is True and d.confidence == "single_source"


def test_missing_event_uid_always_fires():
    r = M.TeamReconciler()
    assert r.observe(None, "soccer_live_goal", "espn", now=1.0).fire is True
    assert r.observe("", "soccer_live_goal", "espn", now=1.0).fire is True


def test_tracked_set_is_bounded():
    r = M.TeamReconciler()
    for i in range(M._MAX_TRACKED + 500):
        r.observe(f"uid-{i}", "soccer_live_goal", "espn", now=float(i))
    assert len(r._seen) <= M._MAX_TRACKED


def test_get_reconciler_is_shared_per_team_key():
    hass = type("H", (), {"data": {}})()
    a1 = M.get_reconciler(hass, "feyenoord")
    a2 = M.get_reconciler(hass, "feyenoord")
    b = M.get_reconciler(hass, "ajax")
    assert a1 is a2 and a1 is not b
