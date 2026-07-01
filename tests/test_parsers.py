"""Parser tests — validate that ESPN data shapes produce expected attributes.

Run with:  python -m pytest tests/ -v
"""
import json
import importlib.util
from pathlib import Path
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
ROOT     = Path(__file__).parent.parent

def _load_parser(name):
    """Import a parser module directly, bypassing HA's __init__.py."""
    path = ROOT / "custom_components" / "soccer_live" / "parsers" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    mod  = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

_scoreboard = _load_parser("scoreboard")
_standings  = _load_parser("standings")
process_match_data = _scoreboard.process_match_data
standings_data     = _standings.standings_data
process_league_data = _scoreboard.process_league_data
process_news_data = _scoreboard.process_news_data
process_scorers_data = _scoreboard.process_scorers_data
process_bracket_data = _load_parser("bracket").process_bracket_data

class _MockHass:
    class config:
        time_zone = "Europe/Amsterdam"


# ---------------------------------------------------------------------------
# Scoreboard parser
# process_match_data(data, hass) → dict with key "matches" (list)
# ---------------------------------------------------------------------------

class TestScoreboardParser:
    def _load(self, name="scoreboard_minimal.json"):
        return json.loads((FIXTURES / name).read_text())

    def _parse(self, data=None, **kwargs):
        return process_match_data(data or self._load(), _MockHass(), **kwargs)

    def test_returns_dict_with_matches(self):
        result = self._parse()
        assert isinstance(result, dict)
        assert "matches" in result
        assert isinstance(result["matches"], list)

    def test_matches_not_empty(self):
        result = self._parse()
        assert len(result["matches"]) == 1

    def test_match_has_required_keys(self):
        match = self._parse()["matches"][0]
        required = {"home_team", "away_team", "home_score", "away_score", "state", "date"}
        missing = required - match.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_match_teams(self):
        match = self._parse()["matches"][0]
        assert match["home_team"] == "Ajax"
        assert match["away_team"] == "PSV"

    def test_match_state_scheduled(self):
        match = self._parse()["matches"][0]
        assert match["state"] == "pre"

    def test_broadcasts_extracted(self):
        match = self._parse()["matches"][0]
        assert isinstance(match.get("broadcasts", []), list)

    def test_has_stats_and_commentary_flags(self):
        match = self._parse()["matches"][0]
        assert match.get("has_stats") is False
        assert match.get("has_commentary") is False

    def test_graceful_on_empty_data(self):
        result = process_match_data({}, _MockHass())
        assert isinstance(result, dict)
        assert result.get("matches") == []

    def test_graceful_on_no_events(self):
        result = process_match_data({"leagues": [], "events": []}, _MockHass())
        assert result["matches"] == []

    def test_graceful_on_malformed_match_entries(self):
        result = process_match_data({"leagues": [None], "events": [None, "bad", 42]}, _MockHass())
        assert isinstance(result, dict)
        assert result.get("matches") == []

    def test_malformed_league_entry_skipped_in_match_data(self):
        result = process_match_data({"leagues": [None, {"name": "Test", "id": "1"}], "events": []}, _MockHass())
        assert isinstance(result, dict)
        assert result.get("matches") == []

    @pytest.mark.parametrize(
        ("parser_func", "data", "expected_key"),
        [
            (process_league_data, {"leagues": [None]}, None),
            (process_news_data, {"articles": [None]}, None),
            (process_scorers_data, {"leaders": [None]}, None),
            (process_bracket_data, {"events": [None]}, "rounds"),
        ],
    )
    def test_malformed_payloads_skip_gracefully(self, parser_func, data, expected_key):
        result = parser_func(data)
        if expected_key:
            assert isinstance(result, dict)
            assert result[expected_key] == []
        else:
            assert isinstance(result, list)
            assert result == []

    def _minimal_event(self, **competition_overrides):
        competition = {
            "id": "700001",
            "date": "2026-06-20T17:00Z",
            "uid": "s:600~l:ned.1~e:700001",
            "competitors": [
                {
                    "homeAway": "home",
                    "score": "0",
                    "team": {
                        "id": "84",
                        "displayName": "Ajax",
                        "abbreviation": "AJX",
                        "logos": [{"href": "https://example.com/ajax.png"}],
                    },
                },
                {
                    "homeAway": "away",
                    "score": "0",
                    "team": {
                        "id": "85",
                        "displayName": "PSV",
                        "abbreviation": "PSV",
                        "logos": [{"href": "https://example.com/psv.png"}],
                    },
                },
            ],
        }
        competition.update(competition_overrides)
        return {
            "id": "700001",
            "date": "2026-06-20T17:00Z",
            "name": "Ajax vs PSV",
            "status": {"type": {"state": "pre", "description": "Scheduled"}},
            "competitions": [competition],
        }

    def test_league_name_and_logo_from_uid_top_league_lookup(self):
        data = {
            "leagues": [{
                "id": "ned.1",
                "name": "Dutch Eredivisie",
                "logos": [{"href": "https://example.com/eredivisie.png"}],
            }],
            "events": [self._minimal_event()],
        }

        match = self._parse(data)["matches"][0]

        assert match["league_name"] == "Dutch Eredivisie"
        assert match["league_logo"] == "https://example.com/eredivisie.png"

    def test_league_name_from_alt_game_note_and_curated_logo_override(self):
        data = {
            "leagues": [],
            "events": [self._minimal_event(
                uid="s:600~l:606~e:700002",
                altGameNote="FIFA World Cup, Group F",
            )],
        }

        match = self._parse(data)["matches"][0]

        assert match["league_name"] == "FIFA World Cup"
        assert match["league_logo"] == "https://a.espncdn.com/i/leaguelogos/soccer/500/4.png"

    def test_league_name_from_event_level_league(self):
        event = self._minimal_event(uid="")
        event["league"] = {
            "id": "uefa.champions",
            "displayName": "UEFA Champions League",
            "logos": [{"href": "https://example.com/ucl.png"}],
        }
        data = {"leagues": [], "events": [event]}

        match = self._parse(data)["matches"][0]

        assert match["league_name"] == "UEFA Champions League"
        assert match["league_logo"] == "https://example.com/ucl.png"


# ---------------------------------------------------------------------------
# Standings parser
# standings_data(data) → dict with key "standings_groups" (list of groups)
# Each group: {"name": str, "entries": [{"team_name", "rank", "points", ...}]}
# ---------------------------------------------------------------------------

class TestStandingsParser:
    def _load(self, name="standings_minimal.json"):
        return json.loads((FIXTURES / name).read_text())

    def _parse(self, data=None):
        return standings_data(data or self._load())

    def test_returns_dict_with_groups(self):
        result = self._parse()
        assert isinstance(result, dict)
        assert "standings_groups" in result
        assert isinstance(result["standings_groups"], list)

    def test_has_one_group(self):
        groups = self._parse()["standings_groups"]
        assert len(groups) == 1

    def test_group_has_standings(self):
        group = self._parse()["standings_groups"][0]
        assert "standings" in group
        assert len(group["standings"]) >= 1

    def test_entry_has_required_keys(self):
        entry = self._parse()["standings_groups"][0]["standings"][0]
        required = {"team_name", "rank", "wins", "losses", "points", "games_played"}
        missing = required - entry.keys()
        assert not missing, f"Missing keys: {missing}"

    def test_entry_team_name(self):
        entry = self._parse()["standings_groups"][0]["standings"][0]
        assert entry["team_name"] == "Ajax"

    def test_entry_rank_and_points(self):
        entry = self._parse()["standings_groups"][0]["standings"][0]
        assert entry["rank"] == 1
        assert entry["points"] == "65"

    def test_zone_info_extracted(self):
        entry = self._parse()["standings_groups"][0]["standings"][0]
        assert entry.get("zone_color") == "#007AC0"
        assert "Champions" in entry.get("zone_label", "")

    def test_graceful_on_empty_data(self):
        result = standings_data({})
        assert isinstance(result, dict)
        assert result.get("standings_groups") == []

    def test_graceful_on_none_child(self):
        result = standings_data({"children": [None]})
        assert isinstance(result, dict)
        assert result["standings_groups"] == []

    def test_graceful_on_none_entry(self):
        result = standings_data({"children": [{"name": "Group A", "standings": {"entries": [None]}}]})
        assert isinstance(result, dict)
        groups = result["standings_groups"]
        assert len(groups) == 1
        assert groups[0]["standings"] == []

    def test_graceful_on_none_logo_in_entry(self):
        result = standings_data({"children": [{"name": "Group A", "standings": {"entries": [
            {"team": {"id": "1", "displayName": "Ajax", "logos": [None]}, "stats": [], "note": {}}
        ]}}]})
        groups = result["standings_groups"]
        assert groups[0]["standings"][0]["team_logo"] == "N/A"

    def test_graceful_on_none_stat_entry(self):
        result = standings_data({"children": [{"name": "Group A", "standings": {"entries": [
            {"team": {"id": "1", "displayName": "Ajax"}, "stats": [None, {"name": "points", "displayValue": "42"}], "note": {}}
        ]}}]})
        groups = result["standings_groups"]
        assert groups[0]["standings"][0]["points"] == "42"


# ---------------------------------------------------------------------------
# Scoreboard helper robustness (malformed nested arrays / null season / tz)
# ---------------------------------------------------------------------------

class TestScoreboardHelpers:
    def test_season_slug_on_null_season(self):
        assert _scoreboard.get_season_slug_or_displayname({"season": None}) is None

    def test_season_slug_on_scalar_season(self):
        assert _scoreboard.get_season_slug_or_displayname({"season": "2026"}) is None

    def test_season_slug_reads_slug(self):
        assert _scoreboard.get_season_slug_or_displayname({"season": {"slug": "2025-26"}}) == "2025-26"

    def test_statistics_skips_non_dict(self):
        stats = _scoreboard._get_statistics({"statistics": [None, "x", {"name": "shots", "displayValue": "5"}]})
        assert stats == {"shots": "5"}

    def test_record_skips_non_dict(self):
        assert _scoreboard._get_record({"records": [None, {"summary": "14-6-14"}]}) == "14-6-14"

    def test_top_scorer_on_null_athlete(self):
        comp = {"leaders": [None, {"name": "goals", "leaders": [None, {"athlete": None, "displayValue": "10"}]}]}
        assert _scoreboard._get_top_scorer(comp) == {"name": "", "short_name": "", "value": "10"}

    def test_broadcast_skips_non_dict(self):
        comp = {"geoBroadcasts": [None, {"media": {"shortName": "ESPN"}}]}
        assert _scoreboard._get_broadcast(comp) == "ESPN"

    def test_broadcasts_skips_non_dict(self):
        comp = {"geoBroadcasts": [None, "x", {"media": {"shortName": "ESPN"}}, {"media": None}]}
        assert _scoreboard._get_broadcasts(comp) == ["ESPN"]

    def test_links_skips_non_dict(self):
        comp = {"links": [None, {"rel": ["summary"], "href": "http://x/s"}]}
        assert _scoreboard._get_links(comp) == {"summary": "http://x/s"}

    def test_parse_date_falls_back_to_utc_without_hass(self):
        # hass=None must not raise; UTC fallback yields a formatted date.
        out = _scoreboard._parse_date(None, "2026-06-20T17:00Z", show_time=False)
        assert out == "20-06-2026"

    def test_parse_date_bad_timezone_falls_back_to_utc(self):
        class _BadTz:
            class config:
                time_zone = "Not/AZone"
        out = _scoreboard._parse_date(_BadTz(), "2026-06-20T17:00Z", show_time=False)
        assert out == "20-06-2026"
