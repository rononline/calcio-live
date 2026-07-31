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


def test_watchlist_event_matches_players_across_provider_shapes():
    result = insights.watchlist_event(
        {"athletes": ["Other", "Calvin Stengs"], "minute": 8},
        "calvin stengs, Quinten Timber",
    )
    assert result["player"] == "Calvin Stengs"
    assert result["watchlist"] is True
    assert insights.watchlist_event({"player": "Other"}, "Calvin Stengs") is None


def _standings(points=10):
    return {
        "season": "2026/27",
        "league_name": "Eredivisie",
        "standings_groups": [{
            "name": "Eredivisie",
            "standings": [
                {"rank": 1, "team_id": 1, "team_name": "Ajax", "points": points + 2, "games_played": 4},
                {"rank": 2, "team_id": 2, "team_name": "Feyenoord", "points": points, "games_played": 4},
                {"rank": 3, "team_id": 3, "team_name": "PSV", "points": points - 1, "games_played": 4},
            ],
        }],
    }


def test_standings_history_only_appends_sporting_changes():
    history = insights.update_standings_history([], _standings(), "2026-08-01T10:00:00+00:00")
    unchanged = insights.update_standings_history(history, _standings(), "2026-08-01T11:00:00+00:00")
    changed = insights.update_standings_history(unchanged, _standings(13), "2026-08-02T10:00:00+00:00")
    assert len(history) == 1
    assert unchanged == history
    assert len(changed) == 2


def test_competition_race_exposes_gaps_and_maximum_points():
    result = insights.competition_race(_standings())
    feyenoord = result["groups"][0]["rows"][1]
    assert feyenoord["gap_to_leader"] == 2
    assert feyenoord["gap_to_above"] == 2
    assert feyenoord["remaining"] == 0
    assert feyenoord["maximum_points"] == 10


def test_competition_race_uses_actual_schedule_and_games_in_hand():
    standings = _standings()
    standings["standings_groups"][0]["standings"][1]["games_played"] = 3
    fixtures = [
        _match(home_id=2, away_id=1, home_team="Feyenoord", away_team="Ajax"),
        _match(event_id="2", home_id=2, away_id=3, home_team="Feyenoord", away_team="PSV"),
        _match(event_id="old", state="post", home_id=2, away_id=1,
               home_team="Feyenoord", away_team="Ajax", home_score=3, away_score=1),
    ]
    result = insights.competition_race(standings, fixtures)
    feyenoord = result["groups"][0]["rows"][1]
    assert result["groups"][0]["remaining_source"] == "fixtures"
    assert feyenoord["remaining"] == 2
    assert feyenoord["games_in_hand"] == 1
    assert feyenoord["projected_points"] == 16
    assert feyenoord["next_match_scenarios"] == {"win": 1, "draw": 2, "loss": 2}


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
    assert result["away"]["matches"] == 2
    assert result["common_opponents"][0]["name"] == "Sparta"
    assert result["biggest_win"]["score"] == "2-1"
