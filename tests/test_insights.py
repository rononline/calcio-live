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


def test_matchday_prefers_live_and_limits_matches_to_same_day():
    live = _match(event_id="live", state="in")
    other = _match(event_id="tomorrow", date_iso="2026-08-10T12:15:00+00:00")
    result = insights.matchday_summary([other, live])
    assert result["focus_event_id"] == "live"
    assert result["phase"] == "live"
    assert result["total"] == 1


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
