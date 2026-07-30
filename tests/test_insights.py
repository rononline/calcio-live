import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "insights.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_insights", MODULE_PATH)
insights = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(insights)


def _match(**overrides):
    return {
        "event_id": "1",
        "date_iso": "2026-08-09T12:15:00+00:00",
        "home_team": "Sparta",
        "away_team": "Feyenoord",
        "competition_name": "Eredivisie",
        "state": "pre",
        **overrides,
    }


def test_match_completeness_is_honest_about_optional_sections():
    result = insights.match_completeness(_match(venue="Het Kasteel"))
    assert result["score"] == 55
    assert result["level"] == "partial"
    assert "lineup" in result["missing"]
    assert "venue" in result["available"]


def test_match_readiness_only_scores_prematch_information():
    result = insights.match_readiness(
        _match(
            venue="Het Kasteel",
            head_to_head=[{"event_id": "old"}],
            lineup_home=[{"name": "Keeper"}],
        )
    )
    assert result["score"] == 60
    assert result["level"] == "good"
    assert "lineup" in result["available"]
    assert "statistics" not in result["missing"]


def test_match_readiness_ignores_provider_placeholders():
    result = insights.match_readiness({
        "date": "N/A",
        "competition_name": "unknown",
        "venue": "-",
    })
    assert result["score"] == 0
    assert result["level"] == "early"


def test_matchday_prefers_live_and_limits_matches_to_same_day():
    live = _match(event_id="live", state="in")
    other = _match(event_id="tomorrow", date_iso="2026-08-10T12:15:00+00:00")
    result = insights.matchday_summary([other, live])
    assert result["focus_event_id"] == "live"
    assert result["phase"] == "live"
    assert result["total"] == 1


def test_data_alerts_report_only_observable_live_gaps_and_conflicts():
    result = insights.data_alerts([
        _match(
            state="in",
            match_phase="first_half",
            clock="20",
            canonical_id="fixture",
            source_conflicts=[{"field": "score"}],
        )
    ])
    assert {item["code"] for item in result} == {
        "source_conflict",
        "live_lineup_missing",
        "live_timeline_missing",
    }


def test_data_alerts_recognise_rescheduled_pair():
    result = insights.data_alerts([
        _match(
            event_id="old",
            canonical_pair_id="pair",
            match_phase="postponed",
        ),
        _match(
            event_id="new",
            canonical_pair_id="pair",
            date_iso="2026-08-16T12:15:00+00:00",
        ),
    ])
    assert "match_rescheduled" in {item["code"] for item in result}


def test_watchlist_matches_case_insensitively():
    club = {"squad": [{"id": 7, "name": "Calvin Stengs", "position": "Attacker"}]}
    assert insights.player_watchlist(club, "calvin stengs")[0]["id"] == 7
    assert insights.player_watchlist(club, "") == []


def test_archive_deduplicates_updates_and_is_newest_first():
    old = insights.archive_snapshot(
        _match(event_id="1", state="post", home_score=1, away_score=0),
        "espn",
    )
    newer = _match(
        event_id="2",
        state="post",
        date_iso="2026-08-10T12:15:00+00:00",
        home_score=2,
        away_score=1,
    )
    updated = insights.update_archive([old], [newer], "api_football")
    assert [item["event_id"] for item in updated] == ["2", "1"]
    assert updated[0]["provider"] == "api_football"


def test_archive_migrates_legacy_event_id_to_canonical_identity():
    legacy = insights.archive_snapshot(
        _match(event_id="1", state="post", home_score=1, away_score=0),
        "espn",
    )
    legacy.pop("canonical_id", None)
    legacy.pop("canonical_pair_id", None)
    refreshed = {
        **_match(event_id="1", state="post", home_score=1, away_score=0),
        "canonical_id": "canonical-fixture",
        "canonical_pair_id": "canonical-pair",
    }
    updated = insights.update_archive([legacy], [refreshed], "espn")
    assert len(updated) == 1
    assert updated[0]["canonical_id"] == "canonical-fixture"


def test_archive_summary_supports_seasons_and_team_statistics():
    matches = [
        insights.archive_snapshot(
            _match(
                event_id="1",
                state="post",
                date_iso="2026-08-10T12:15:00+00:00",
                home_score=1,
                away_score=2,
            ),
            "espn",
        ),
        insights.archive_snapshot(
            _match(
                event_id="2",
                state="post",
                date_iso="2027-02-10T12:15:00+00:00",
                home_score=0,
                away_score=0,
            ),
            "espn",
        ),
    ]
    result = insights.archive_summary(matches, "Feyenoord")
    assert result["seasons"] == ["2026/27"]
    assert result["statistics"]["matches"] == 2
    assert result["statistics"]["won"] == 1
    assert result["statistics"]["drawn"] == 1
    assert result["statistics"]["goals_for"] == 2
    assert result["statistics"]["clean_sheets"] == 1
