import importlib.util
from datetime import datetime, timezone
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "derived.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_derived", MODULE_PATH)
derived = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(derived)


def _match(**values):
    return {
        "event_id": "1",
        "canonical_id": "fixture-1",
        "canonical_pair_id": "pair-1",
        "date_iso": "2026-07-31T18:00:00+00:00",
        "home_team": "Feyenoord",
        "away_team": "Sparta",
        "state": "pre",
        **values,
    }


def test_entry_match_state_exposes_native_flags():
    now = datetime(2026, 7, 31, 12, tzinfo=timezone.utc)
    state = derived.entry_match_state([
        _match(state="in", lineup_home=[{"name": "A"}])
    ], now)
    assert state["match_live"] is True
    assert state["match_today"] is True
    assert state["lineup_available"] is True


def test_capability_matrix_explains_missing_data():
    matrix = derived.capability_matrix(
        [_match()], ["fixtures", "lineups"]
    )
    assert matrix["fixtures"]["status"] == "available"
    assert matrix["lineups"]["reason"] == "not_yet_published"
    assert matrix["odds"]["reason"] == "provider_unsupported"


def test_season_transition_detects_rollover_and_stale_manual_season():
    matches = [
        _match(state="post", season_info=2025),
        _match(event_id="2", canonical_id="fixture-2", state="pre", season_info=2026),
    ]
    assert derived.season_transition({}, matches)["status"] == "rollover"
    stale = derived.season_transition({}, matches, configured_season=2025)
    assert stale["status"] == "stale"


def test_unified_enrichment_never_appends_secondary_schedule_rows():
    primary = [_match()]
    secondary = [[
        _match(provider="api_football", odds={"home": 2.0}),
        _match(event_id="other", canonical_id="other", canonical_pair_id="other"),
    ]]
    merged, provenance = derived.merge_match_sources(primary, secondary)
    assert len(merged) == 1
    assert merged[0]["odds"] == {"home": 2.0}
    assert provenance["enriched_fields"] == 1
    assert provenance["sources"] == ["api_football"]


def test_match_summary_is_structured_and_provider_neutral():
    summary = derived.match_summary(_match(
        state="post", home_score=2, away_score=1,
        key_events=[{"type": "goal", "player": "A", "scoring_play": True}],
    ), "Feyenoord")
    assert summary["outcome"] == "win"
    assert summary["goal_scorers"] == ["A"]
