"""Parser tests — validate that ESPN data shapes produce expected attributes.

Run with:  python -m pytest tests/ -v
"""
import importlib.util
import json
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
_api_football = _load_parser("api_football")
process_match_data = _scoreboard.process_match_data
standings_data     = _standings.standings_data
process_league_data = _scoreboard.process_league_data
process_news_data = _scoreboard.process_news_data
process_scorers_data = _scoreboard.process_scorers_data
process_api_football_fixture_data = _api_football.process_fixture_data
process_api_football_bracket_data = _api_football.process_bracket_data
process_api_football_head_to_head = _api_football.process_head_to_head_data
process_api_football_standings_data = _api_football.process_standings_data
process_api_football_scorers_data = _api_football.process_scorers_data
process_api_football_fixture_enrichment = _api_football.process_fixture_enrichment
process_api_football_prediction = _api_football.process_prediction_data
process_api_football_injuries = _api_football.process_injuries_data
process_api_football_odds = _api_football.process_odds_data
process_api_football_live_odds = _api_football.process_live_odds_data
api_football_extract_team_standing = _api_football.extract_team_standing
process_api_football_team_profile = _api_football.process_team_profile
process_api_football_coach = _api_football.process_coach
process_api_football_squad = _api_football.process_squad
process_api_football_transfers = _api_football.process_transfers
api_football_extract_error = _api_football.extract_error
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

    def test_time_tbd_reflects_espn_timevalid(self):
        data = self._load()
        # No timeValid on the event -> a confirmed time, not TBD.
        assert self._parse(data)["matches"][0]["time_tbd"] is False
        # ESPN marks unconfirmed kick-off times with timeValid: false.
        data["events"][0]["timeValid"] = False
        assert self._parse(data)["matches"][0]["time_tbd"] is True

    def test_match_exposes_raw_iso_date(self):
        # date_iso carries the raw ESPN kickoff timestamp (used for kickoff-time
        # weather forecasts); date stays the localized display string.
        match = self._parse()["matches"][0]
        assert match["date_iso"] == "2026-06-20T17:00Z"
        assert match["date"] != match["date_iso"]

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

    def test_score_value_coerces_object_scores(self):
        # ESPN returns an object score for in-progress matches; it must be
        # flattened to a scalar so cards don't render "[object Object]".
        assert _scoreboard._score_value({"value": 2, "displayValue": "2"}) == "2"
        assert _scoreboard._score_value({"value": 3}) == 3
        assert _scoreboard._score_value("1") == "1"
        assert _scoreboard._score_value(0) == 0
        assert _scoreboard._score_value(None) == "N/A"
        assert _scoreboard._score_value({}) == "N/A"

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


class TestApiFootballParser:
    def test_fixture_rounds_are_derived_into_bracket(self):
        data = {"response": [{
            "fixture": {"id": 1, "date": "2026-05-20T19:00:00+00:00", "status": {"short": "FT"}},
            "league": {"name": "Champions League", "logo": "ucl.png", "round": "Final"},
            "teams": {"home": {"name": "Feyenoord", "logo": "f.png"}, "away": {"name": "Inter", "logo": "i.png"}},
            "goals": {"home": 2, "away": 1},
        }]}
        result = process_api_football_bracket_data(data)
        assert result["rounds"][0]["name"] == "Final"
        assert result["rounds"][0]["ties"][0]["winner_team"] == "Feyenoord"
        assert result["league_logo"] == "ucl.png"

    def test_two_legged_fixture_round_is_combined_with_aggregate(self):
        def leg(fixture_id, date, home, away, home_score, away_score):
            return {
                "fixture": {"id": fixture_id, "date": date, "status": {"short": "FT"}},
                "league": {"name": "Champions League", "round": "Semi-finals"},
                "teams": {"home": home, "away": away},
                "goals": {"home": home_score, "away": away_score},
            }
        feyenoord = {"id": 1, "name": "Feyenoord", "logo": "f.png"}
        inter = {"id": 2, "name": "Inter", "logo": "i.png"}
        result = process_api_football_bracket_data({"response": [
            leg(1, "2026-05-01T19:00:00+00:00", feyenoord, inter, 2, 0),
            leg(2, "2026-05-08T19:00:00+00:00", inter, feyenoord, 1, 1),
        ]})
        tie = result["rounds"][0]["ties"][0]
        assert "single" not in tie
        assert tie["aggregate"] == "3-1"
        assert tie["winner_team"] == "Feyenoord"

    def test_fixture_response_maps_to_match_model(self):
        data = {
            "response": [{
                "fixture": {
                    "id": 123,
                    "date": "2026-07-20T18:00:00+00:00",
                    "status": {"short": "NS", "long": "Not Started", "elapsed": None},
                    "venue": {"name": "De Kuip"},
                },
                "league": {"id": 667, "name": "Friendlies Clubs", "country": "World", "season": 2026, "logo": "league.png"},
                "teams": {
                    "home": {"id": 1, "name": "Feyenoord", "logo": "home.png"},
                    "away": {"id": 2, "name": "PSV", "logo": "away.png"},
                },
                "goals": {"home": None, "away": None},
            }]
        }

        result = process_api_football_fixture_data(data, _MockHass(), team_id="1", team_name="Feyenoord")

        assert result["provider"] == "api_football"
        assert result["team_logo"] == "home.png"
        assert result["league_info"][0]["name"] == "Friendlies Clubs"
        assert result["league_info"][0]["abbreviation"] == "Friendlies Clubs"
        match = result["matches"][0]
        assert match["event_id"] == "123"
        assert match["home_id"] == 1
        assert match["away_id"] == 2
        assert match["home_team"] == "Feyenoord"
        assert match["away_team"] == "PSV"
        assert match["state"] == "pre"
        # league_name is localized (default language "en" -> canonical English)
        assert match["league_name"] == "Club Friendlies"
        # league_info keeps the raw provider name
        assert result["league_info"][0]["name"] == "Friendlies Clubs"

    def test_league_name_is_localized_to_hass_language(self):
        class _DutchHass:
            class config:
                time_zone = "Europe/Amsterdam"
                language = "nl"

        data = {
            "response": [{
                "fixture": {"id": 1, "date": "2026-07-20T18:00:00+00:00", "status": {"short": "NS"}},
                "league": {"id": 667, "name": "Friendlies Clubs"},
                "teams": {
                    "home": {"id": 1, "name": "Feyenoord"},
                    "away": {"id": 2, "name": "Club Brugge"},
                },
                "goals": {"home": None, "away": None},
            }]
        }

        result = process_api_football_fixture_data(data, _DutchHass())

        match = result["matches"][0]
        assert match["league_name"] == "Oefenwedstrijd"
        assert match["competition_name"] == "Oefenwedstrijd"
        # Stable flag from the raw English name, so cards don't have to guess
        # from the localised display name.
        assert match["is_friendly"] is True

    def test_is_friendly_false_for_a_real_competition(self):
        data = {
            "response": [{
                "fixture": {"id": 9, "date": "2026-08-02T18:00:00+00:00", "status": {"short": "NS"}},
                "league": {"id": 88, "name": "Eredivisie"},
                "teams": {
                    "home": {"id": 1, "name": "Feyenoord"},
                    "away": {"id": 2, "name": "Ajax"},
                },
                "goals": {"home": None, "away": None},
            }]
        }
        result = process_api_football_fixture_data(data, _MockHass())
        assert result["matches"][0]["is_friendly"] is False

    def test_normalize_competition_name_passes_through_unknown(self):
        assert _api_football.normalize_competition_name("UEFA Champions League", "nl") == "UEFA Champions League"
        assert _api_football.normalize_competition_name("Friendlies", "nl") == "Oefenwedstrijden"
        assert _api_football.normalize_competition_name("", "nl") == ""

    def test_friendlies_can_be_filtered_out(self):
        data = {
            "response": [{
                "fixture": {"id": 123, "date": "2026-07-20T18:00:00+00:00", "status": {"short": "NS"}},
                "league": {"id": 667, "name": "Friendlies Clubs"},
                "teams": {
                    "home": {"id": 1, "name": "Feyenoord"},
                    "away": {"id": 2, "name": "PSV"},
                },
                "goals": {"home": None, "away": None},
            }]
        }

        result = process_api_football_fixture_data(data, _MockHass(), team_id="1", include_friendlies=False)

        assert result["matches"] == []

    def test_head_to_head_keeps_finished_matches_newest_first_and_compact(self):
        def fixture(fixture_id, date, status, home_score, away_score):
            return {
                "fixture": {
                    "id": fixture_id,
                    "date": date,
                    "status": {"short": status, "long": "Match Finished" if status == "FT" else "Not Started"},
                    "venue": {"name": "Test Ground"},
                },
                "league": {"id": 39, "name": "Premier League", "season": 2025},
                "teams": {
                    "home": {"id": 42, "name": "Arsenal", "logo": "arsenal.png"},
                    "away": {"id": 50, "name": "Chelsea", "logo": "chelsea.png"},
                },
                "goals": {"home": home_score, "away": away_score},
            }

        data = {"response": [
            fixture(1, "2025-01-01T15:00:00+00:00", "FT", 1, 0),
            fixture(3, "2027-01-01T15:00:00+00:00", "NS", None, None),
            fixture(2, "2026-01-01T15:00:00+00:00", "FT", 2, 1),
        ]}

        result = process_api_football_head_to_head(data, _MockHass(), limit=8)

        assert [match["event_id"] for match in result] == ["2", "1"]
        assert result[0]["home_score"] == "2"
        assert result[0]["away_score"] == "1"
        assert result[0]["provider"] == "api_football"
        assert "key_events" not in result[0]

    def test_standings_response_maps_to_standings_model(self):
        data = {"response": [{"league": {
            "id": 39,
            "name": "Premier League",
            "country": "England",
            "logo": "league.png",
            "season": 2026,
            "standings": [[{
                "rank": 1,
                "team": {"id": 42, "name": "Arsenal", "logo": "arsenal.png"},
                "points": 80,
                "goalsDiff": 42,
                "group": "Premier League",
                "description": "Champions League",
                "all": {"played": 38, "win": 25, "draw": 5, "lose": 8, "goals": {"for": 81, "against": 39}},
            }]],
        }}]}

        result = process_api_football_standings_data(data)

        assert result["league_name"] == "Premier League"
        assert result["standings_groups"][0]["standings"][0]["team_name"] == "Arsenal"
        assert result["standings_groups"][0]["standings"][0]["points"] == 80

    def test_scorers_response_maps_to_scorers_model(self):
        data = {"response": [{
            "player": {"id": 1, "name": "Player One", "photo": "player.png"},
            "statistics": [{
                "team": {"id": 42, "name": "Arsenal", "logo": "arsenal.png"},
                "league": {"id": 39, "name": "Premier League", "logo": "league.png"},
                "goals": {"total": 21, "assists": 6},
            }],
        }]}

        result = process_api_football_scorers_data(data)

        assert result["league_name"] == "Premier League"
        assert result["scorers"][0]["player"] == "Player One"
        assert result["scorers"][0]["goals"] == 21

    def test_scorers_sum_goals_across_transferred_clubs(self):
        data = {"response": [{
            "player": {"id": 1, "name": "Player One", "photo": "player.png"},
            "statistics": [
                {
                    "team": {"id": 42, "name": "Arsenal", "logo": "arsenal.png"},
                    "league": {"id": 39, "name": "Premier League", "logo": "league.png"},
                    "goals": {"total": 8, "assists": 2},
                },
                {
                    "team": {"id": 50, "name": "Chelsea", "logo": "chelsea.png"},
                    "league": {"id": 39, "name": "Premier League", "logo": "league.png"},
                    "goals": {"total": 13, "assists": None},
                },
            ],
        }]}

        result = process_api_football_scorers_data(data)

        scorer = result["scorers"][0]
        assert scorer["goals"] == 21
        assert scorer["assists"] == 2
        # Team/league come from the club where he scored the most.
        assert scorer["team_name"] == "Chelsea"

    def test_prediction_maps_percentages_and_advice(self):
        data = {"response": [{
            "predictions": {
                "winner": {"id": 209, "name": "Feyenoord", "comment": "Win or draw"},
                "advice": "Double chance : Feyenoord or draw",
                "percent": {"home": "55%", "draw": "25%", "away": "20%"},
            },
        }]}

        pred = process_api_football_prediction(data)

        assert pred["percent_home"] == 55
        assert pred["percent_draw"] == 25
        assert pred["percent_away"] == 20
        assert pred["advice"] == "Double chance : Feyenoord or draw"
        assert pred["winner_name"] == "Feyenoord"
        # No comparison/goals in this payload -> those keys are omitted.
        assert "comparison" not in pred
        assert "goals_home" not in pred

    def test_prediction_extracts_comparison_and_goal_lines(self):
        data = {"response": [{
            "predictions": {
                "winner": {"name": "Away FC"},
                "advice": "Away FC",
                "percent": {"home": "30%", "draw": "20%", "away": "50%"},
                "goals": {"home": "-2.5", "away": "-2.5"},
                "under_over": "-3.5",
            },
            "comparison": {
                "form": {"home": "28.6%", "away": "71.4%"},
                "att": {"home": "46%", "away": "54%"},
                "def": {"home": "20%", "away": "80%"},
                "poisson_distribution": {"home": "38%", "away": "62%"},
                "total": {"home": "28.6%", "away": "71.4%"},
            },
        }]}
        pred = process_api_football_prediction(data)
        # Only form/att/def are surfaced (poisson and total dropped).
        assert set(pred["comparison"].keys()) == {"form", "att", "def"}
        # Percentages are rounded, not truncated: 28.6 -> 29, 71.4 -> 71.
        assert pred["comparison"]["form"] == {"home": 29, "away": 71}
        assert pred["comparison"]["def"] == {"home": 20, "away": 80}
        # Raw goal-line thresholds are kept as-is (formatted in the card).
        assert pred["goals_home"] == "-2.5"
        assert pred["goals_away"] == "-2.5"
        assert pred["under_over"] == "-3.5"

    def test_prediction_drops_empty_zero_comparison_metrics(self):
        # API-Football returns 0/0 pairs (no "%") for comparison metrics it can't
        # compute — these must not surface as empty "0% / 0%" bars.
        data = {"response": [{
            "predictions": {
                "winner": {"name": "Away FC"},
                "advice": "Double chance",
                "percent": {"home": "0%", "draw": "50%", "away": "50%"},
            },
            "comparison": {
                "form": {"home": "0%", "away": "0%"},
                "att": {"home": "60%", "away": "40%"},
                "def": {"home": "0%", "away": "0%"},
            },
        }]}
        pred = process_api_football_prediction(data)
        # Only the metric with real data survives; the 0/0 pairs are dropped.
        assert pred["comparison"] == {"att": {"home": 60, "away": 40}}

    def test_injuries_split_by_team_with_suspension_flag(self):
        data = {"response": [
            {"player": {"name": "G. Trauner", "type": "Missing Fixture", "reason": "Achilles tendon problems"},
             "team": {"id": 209, "name": "Feyenoord"}},
            {"player": {"name": "Q. Timber", "type": "Missing Fixture", "reason": "Suspended"},
             "team": {"id": 209, "name": "Feyenoord"}},
            {"player": {"name": "H. Vanaken", "type": "Questionable", "reason": "Knock"},
             "team": {"id": 569, "name": "Club Brugge"}},
            {"player": {"name": "", "reason": "Injury"}, "team": {"id": 209}},  # no name -> skipped
        ]}

        out = process_api_football_injuries(data, home_team_id=209, away_team_id=569)

        assert len(out["injuries_home"]) == 2
        assert len(out["injuries_away"]) == 1
        assert out["injuries_home"][0]["player"] == "G. Trauner"
        assert out["injuries_home"][0]["suspended"] is False
        assert out["injuries_home"][1]["suspended"] is True  # "Suspended"
        assert out["injuries_away"][0]["player"] == "H. Vanaken"

    def test_injuries_deduplicate_repeated_rows(self):
        # API-Football repeats each absentee (once per fixture in the round);
        # the same player must not be listed twice.
        row = {"player": {"name": "T. Beelen", "type": "Missing Fixture", "reason": "Broken Leg"},
               "team": {"id": 209, "name": "Feyenoord"}}
        data = {"response": [row, dict(row), row]}  # same entry three times
        out = process_api_football_injuries(data, home_team_id=209, away_team_id=569)
        assert len(out["injuries_home"]) == 1
        assert out["injuries_home"][0]["player"] == "T. Beelen"

    def test_odds_average_match_winner_across_bookmakers(self):
        data = {"response": [{
            "bookmakers": [
                {"name": "A", "bets": [{"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "1.50"}, {"value": "Draw", "odd": "4.00"}, {"value": "Away", "odd": "6.00"}]}]},
                {"name": "B", "bets": [
                    {"name": "Over/Under", "values": [{"value": "Over 2.5", "odd": "1.80"}]},
                    {"name": "Match Winner", "values": [
                        {"value": "Home", "odd": "1.60"}, {"value": "Draw", "odd": "4.20"}, {"value": "Away", "odd": "5.80"}]}]},
            ],
        }]}

        odds = process_api_football_odds(data)

        assert odds["home"] == 1.55   # (1.50 + 1.60) / 2
        assert odds["draw"] == 4.10   # (4.00 + 4.20) / 2
        assert odds["away"] == 5.90   # (6.00 + 5.80) / 2
        assert odds["bookmaker_count"] == 2

    def test_live_odds_reads_in_play_match_winner(self):
        data = {"response": [{
            "status": {"stopped": False, "blocked": False, "finished": False},
            "odds": [
                {"id": 33, "name": "Over/Under", "values": [{"value": "Over", "odd": "1.80"}]},
                {"id": 59, "name": "Match Winner", "values": [
                    {"value": "Home", "odd": "2.50", "suspended": False},
                    {"value": "Draw", "odd": "3.10", "suspended": False},
                    {"value": "Away", "odd": "2.70", "suspended": False}]},
            ],
        }]}
        odds = process_api_football_live_odds(data)
        assert odds == {"home": 2.50, "draw": 3.10, "away": 2.70, "live": True}

    def test_live_odds_none_when_suspended(self):
        # Whole market stopped (e.g. right after a goal) -> keep last shown odds.
        blocked = {"response": [{"status": {"stopped": True, "blocked": False},
                                 "odds": [{"name": "Match Winner", "values": [{"value": "Home", "odd": "2.0"}]}]}]}
        assert process_api_football_live_odds(blocked) is None
        # Individual suspended values are skipped.
        partial = {"response": [{"status": {"stopped": False, "blocked": False}, "odds": [
            {"name": "Match Winner", "values": [
                {"value": "Home", "odd": "2.0", "suspended": True},
                {"value": "Draw", "odd": "3.3", "suspended": False},
                {"value": "Away", "odd": "3.0", "suspended": True}]}]}]}
        assert process_api_football_live_odds(partial) == {"home": None, "draw": 3.3, "away": None, "live": True}
        assert process_api_football_live_odds({"response": []}) is None

    def test_extract_team_standing_returns_rank_and_points(self):
        data = {"response": [{"league": {"standings": [[
            {"rank": 1, "team": {"id": 42}, "points": 80},
            {"rank": 3, "team": {"id": 209}, "points": 45},
        ]]}}]}
        assert api_football_extract_team_standing(data, 209) == {"rank": 3, "points": 45}
        assert api_football_extract_team_standing(data, 42) == {"rank": 1, "points": 80}

    def test_team_profile_maps_venue_and_founded(self):
        data = {"response": [{
            "team": {"id": 209, "name": "Feyenoord", "logo": "l.png", "founded": 1908, "country": "Netherlands"},
            "venue": {"name": "Stadion Feijenoord", "city": "Rotterdam", "capacity": 47500},
        }]}
        p = process_api_football_team_profile(data)
        assert p["name"] == "Feyenoord"
        assert p["founded"] == 1908
        assert p["venue"] == "Stadion Feijenoord"
        assert p["venue_city"] == "Rotterdam"
        assert process_api_football_team_profile({"response": []}) is None

    def test_coach_prefers_current_spell(self):
        data = {"response": [
            {"name": "Old Coach", "career": [{"team": {"id": 209}, "start": "2020", "end": "2023"}]},
            {"name": "Brian Priske", "career": [{"team": {"id": 209}, "start": "2024", "end": None}]},
        ]}
        assert process_api_football_coach(data) == "Brian Priske"
        # No current spell -> first entry.
        assert process_api_football_coach({"response": [{"name": "X", "career": []}]}) == "X"
        assert process_api_football_coach({"response": []}) == ""

    def test_coach_ignores_former_coach_now_elsewhere(self):
        # An ex-coach whose current (open) job is at another club must not win;
        # only the open spell at the queried team counts.
        data = {"response": [
            {"name": "Pascal Bosschaart", "career": [  # interim, ended at 209; now open elsewhere
                {"team": {"id": 209}, "start": "2025-01", "end": "2025-05"},
                {"team": {"id": 999}, "start": "2025-06", "end": None},
            ]},
            {"name": "Giovanni van Bronckhorst", "career": [
                {"team": {"id": 209}, "start": "2025-06", "end": None},
            ]},
        ]}
        assert process_api_football_coach(data, 209) == "Giovanni van Bronckhorst"

    def test_coach_breaks_ties_on_most_recent_start_at_team(self):
        data = {"response": [
            {"name": "Assistant", "career": [{"team": {"id": 209}, "start": "2023-06", "end": None}]},
            {"name": "Head Coach", "career": [{"team": {"id": 209}, "start": "2025-06", "end": None}]},
        ]}
        assert process_api_football_coach(data, 209) == "Head Coach"

    def test_squad_sorted_by_position_then_number(self):
        data = {"response": [{"players": [
            {"name": "Striker", "number": 9, "position": "Attacker", "age": 25},
            {"name": "Keeper", "number": 1, "position": "Goalkeeper", "age": 30},
            {"name": "Defender", "number": 4, "position": "Defender", "age": 27},
            {"name": "", "number": 99, "position": "Attacker"},  # no name -> skipped
        ]}]}
        squad = process_api_football_squad(data)
        assert [p["name"] for p in squad] == ["Keeper", "Defender", "Striker"]

    def test_transfers_flattened_and_tagged_by_direction(self):
        data = {"response": [{
            "player": {"name": "Player A"},
            "transfers": [
                {"date": "2025-07-01", "type": "€ 10M", "teams": {"in": {"id": 209, "name": "Feyenoord"}, "out": {"id": 5, "name": "Ajax"}}},
                {"date": "2024-01-01", "type": "Loan", "teams": {"in": {"id": 5, "name": "Ajax"}, "out": {"id": 209, "name": "Feyenoord"}}},
                {"date": "2020-01-01", "type": "Free", "teams": {"in": {"id": 8, "name": "X"}, "out": {"id": 9, "name": "Y"}}},  # unrelated -> skipped
            ],
        }]}
        transfers = process_api_football_transfers(data, 209)
        assert len(transfers) == 2
        assert transfers[0]["direction"] == "in"      # most recent first
        assert transfers[0]["to"] == "Feyenoord"
        assert transfers[1]["direction"] == "out"

    def test_transfers_deduplicates_repeated_records(self):
        # API-Football can list the same move more than once; a composite key on
        # player + date + from + to must collapse those into one.
        move = {"date": "2025-07-01", "type": "€ 10M",
                "teams": {"in": {"id": 209, "name": "Feyenoord"}, "out": {"id": 5, "name": "Ajax"}}}
        data = {"response": [{"player": {"name": "Player A"}, "transfers": [move, dict(move)]}]}
        transfers = process_api_football_transfers(data, 209)
        assert len(transfers) == 1
        assert transfers[0]["player"] == "Player A"

    def test_extract_team_standing_returns_none_when_absent(self):
        data = {"response": [{"league": {"standings": [[{"rank": 1, "team": {"id": 42}, "points": 80}]]}}]}
        assert api_football_extract_team_standing(data, 999) is None
        assert api_football_extract_team_standing({"response": []}, 209) is None
        assert api_football_extract_team_standing({}, 209) is None
        assert api_football_extract_team_standing(data, None) is None

    def test_odds_returns_none_without_match_winner(self):
        assert process_api_football_odds({"response": []}) is None
        assert process_api_football_odds({}) is None
        assert process_api_football_odds({"response": [{"bookmakers": [
            {"name": "A", "bets": [{"name": "Over/Under", "values": [{"value": "Over 2.5", "odd": "1.8"}]}]}
        ]}]}) is None

    def test_injuries_returns_none_when_empty_or_unmatched(self):
        assert process_api_football_injuries({"response": []}, 1, 2) is None
        assert process_api_football_injuries({}, 1, 2) is None
        # team ids that don't match either side -> nothing attributed -> None
        assert process_api_football_injuries(
            {"response": [{"player": {"name": "X", "reason": "Injury"}, "team": {"id": 999}}]},
            home_team_id=1, away_team_id=2,
        ) is None

    def test_prediction_suppresses_neutral_placeholder(self):
        # 33/33/33 with no winner is API-Football's "no real prediction" filler.
        assert process_api_football_prediction({"response": [{
            "predictions": {
                "winner": {"name": None},
                "advice": "No predictions available",
                "percent": {"home": "33%", "draw": "33%", "away": "33%"},
            },
        }]}) is None
        # But an equal split WITH a named winner is kept.
        kept = process_api_football_prediction({"response": [{
            "predictions": {
                "winner": {"name": "Feyenoord"},
                "percent": {"home": "33%", "draw": "33%", "away": "33%"},
            },
        }]})
        assert kept is not None and kept["winner_name"] == "Feyenoord"

    def test_prediction_returns_none_without_usable_data(self):
        assert process_api_football_prediction({"response": []}) is None
        assert process_api_football_prediction({"response": [{"predictions": {}}]}) is None
        assert process_api_football_prediction({}) is None
        # percentages absent and no advice/winner -> None
        assert process_api_football_prediction(
            {"response": [{"predictions": {"percent": {"home": None, "draw": None, "away": None}}}]}
        ) is None

    def test_extract_error_returns_none_on_success(self):
        assert api_football_extract_error({"errors": [], "response": [1]}) is None
        assert api_football_extract_error({"errors": {}, "response": []}) is None
        assert api_football_extract_error({"response": []}) is None
        assert api_football_extract_error(None) is None

    def test_extract_error_reports_token_and_quota_messages(self):
        token = api_football_extract_error({
            "errors": {"token": "Error/Missing application key."},
            "response": [],
        })
        assert token == "Error/Missing application key."

        quota = api_football_extract_error({
            "errors": {"requests": "You have reached the request limit for the day"},
            "response": [],
        })
        assert quota == "You have reached the request limit for the day"

        listed = api_football_extract_error({"errors": ["Bad request"], "response": []})
        assert listed == "Bad request"

    def test_is_auth_error_detects_token_errors_only(self):
        is_auth_error = _api_football.is_auth_error
        # A token error means the key is missing/invalid -> reauth.
        assert is_auth_error({"errors": {"token": "Invalid application key."}}) is True
        # Quota / parameter errors are not auth failures.
        assert is_auth_error({"errors": {"requests": "limit reached"}}) is False
        assert is_auth_error({"errors": {}}) is False
        assert is_auth_error({"errors": ["Bad request"]}) is False
        assert is_auth_error({"response": []}) is False
        assert is_auth_error(None) is False

    def test_scored_penalty_keeps_goal_token_and_missed_does_not(self):
        events = {"response": [
            {
                "time": {"elapsed": 20},
                "team": {"id": 1, "name": "A"},
                "player": {"name": "Scorer"},
                "type": "Goal",
                "detail": "Penalty",
            },
            {
                "time": {"elapsed": 40},
                "team": {"id": 1, "name": "A"},
                "player": {"name": "Misser"},
                "type": "Goal",
                "detail": "Missed Penalty",
            },
        ]}

        out = process_api_football_fixture_enrichment(events_data=events)

        # Scored penalty keeps the "Goal" token so goal detection can attribute it.
        assert out["match_details"][0] == "Goal - Penalty - 20': Scorer"
        # A missed penalty must not read as scored, and carries no "Goal" token.
        assert out["match_details"][1] == "Penalty - Missed - 40': Misser"
        assert "Goal" not in out["match_details"][1]
        # scoring_play must be True for the conversion and False for the miss.
        assert out["key_events"][0]["scoring_play"] is True
        assert out["key_events"][1]["scoring_play"] is False

    def test_live_clock_includes_stoppage_time(self):
        data = {
            "response": [{
                "fixture": {
                    "id": 9,
                    "date": "2026-07-20T18:00:00+00:00",
                    "status": {"short": "2H", "long": "Second Half", "elapsed": 90, "extra": 4},
                },
                "league": {"id": 39, "name": "Premier League"},
                "teams": {
                    "home": {"id": 1, "name": "Arsenal"},
                    "away": {"id": 2, "name": "Chelsea"},
                },
                "goals": {"home": 1, "away": 1},
            }]
        }

        result = process_api_football_fixture_data(data, _MockHass())

        match = result["matches"][0]
        assert match["state"] == "in"
        assert match["clock"] == "90+4"

    def test_fixture_enrichment_maps_events_stats_and_lineups(self):
        events = {"response": [{
            "time": {"elapsed": 12},
            "team": {"id": 42, "name": "Arsenal"},
            "player": {"name": "Player One"},
            "type": "Goal",
            "detail": "Normal Goal",
        }, {
            "time": {"elapsed": 36},
            "team": {"id": 42, "name": "Arsenal"},
            "player": {"name": "Player Two"},
            "type": "Goal",
            "detail": "Penalty",
        }, {
            "time": {"elapsed": 73},
            "team": {"id": 50, "name": "Chelsea"},
            "player": {"name": "Player Three"},
            "type": "Card",
            "detail": "Yellow Card",
        }]}
        statistics = {"response": [{
            "team": {"id": 50, "name": "Chelsea"},
            "statistics": [
                {"type": "Ball Possession", "value": "45%"},
                {"type": "Total Shots", "value": 8},
                {"type": "Shots on Goal", "value": 3},
                {"type": "Fouls", "value": 11},
            ],
        }, {
            "team": {"id": 42, "name": "Arsenal"},
            "statistics": [
                {"type": "Ball Possession", "value": "55%"},
                {"type": "Total Shots", "value": 14},
                {"type": "Shots on Goal", "value": 7},
                {"type": "Fouls", "value": 9},
                {"type": "expected_goals", "value": "1.20"},
            ],
        }]}
        lineups = {"response": [{
            "team": {"id": 50, "name": "Chelsea"},
            "formation": "4-2-3-1",
            "startXI": [{"player": {"name": "Player Two", "number": 1, "pos": "G"}}],
            "substitutes": [],
        }, {
            "team": {"id": 42, "name": "Arsenal"},
            "formation": "4-3-3",
            "startXI": [{"player": {"name": "Player One", "number": 9, "pos": "F"}}],
            "substitutes": [],
        }]}

        result = process_api_football_fixture_enrichment(events, statistics, lineups, home_team_id=42, away_team_id=50)

        assert result["has_commentary"] is True
        assert result["match_details"][0] == "Goal - 12': Player One"
        assert result["match_details"][1] == "Goal - Penalty - 36': Player Two"
        assert result["match_details"][2] == "Yellow Card - 73': Player Three"
        assert result["key_events"][0]["type"] == "Goal"
        assert result["key_events"][0]["clock"] == "12"
        assert result["home_statistics"]["Shots on Goal"] == 7
        assert result["home_statistics"]["possessionPct"] == "55"
        assert result["home_statistics"]["totalShots"] == 14
        assert result["home_statistics"]["shotsOnTarget"] == 7
        assert result["home_statistics"]["foulsCommitted"] == 9
        assert result["home_statistics"]["expectedGoals"] == "1.20"
        assert result["formation_home"] == "4-3-3"
        assert result["lineup_home"][0]["starter"] is True

    def test_stoppage_time_kept_in_event_detail_and_key_event(self):
        # elapsed=90, extra=7 must render as "90+7" in both the human-readable
        # match_details string and the key_event minute/clock fields.
        events = {"response": [{
            "time": {"elapsed": 90, "extra": 7},
            "team": {"id": 42, "name": "Arsenal"},
            "player": {"name": "J. Alvarez"},
            "type": "Card",
            "detail": "Yellow Card",
        }]}
        result = process_api_football_fixture_enrichment(events, None, None, home_team_id=42, away_team_id=50)
        assert result["match_details"][0] == "Yellow Card - 90+7': J. Alvarez"
        assert result["key_events"][0]["clock"] == "90+7"
        assert result["key_events"][0]["minute"] == "90+7"

    def test_event_detail_without_extra_and_missing_minute(self):
        events = {"response": [
            {"time": {"elapsed": 45}, "player": {"name": "A"}, "type": "Goal", "detail": "Normal Goal"},
            {"time": {}, "player": {"name": "B"}, "type": "Card", "detail": "Yellow Card"},
        ]}
        result = process_api_football_fixture_enrichment(events, None, None, home_team_id=1, away_team_id=2)
        assert result["match_details"][0] == "Goal - 45': A"
        assert result["match_details"][1] == "Yellow Card - N/A: B"

    def test_pre_match_negative_minute_normalized(self):
        # API-Football uses elapsed=-5 for a tunnel/warmup card; it must not
        # render as "-5'" and the key_event minute must be blank, not "-5".
        events = {"response": [
            {"time": {"elapsed": -5, "extra": None}, "player": {"name": "S. McTominay"},
             "type": "Card", "detail": "Yellow Card"},
        ]}
        result = process_api_football_fixture_enrichment(events, None, None, home_team_id=1, away_team_id=2)
        assert result["match_details"][0] == "Yellow Card - N/A: S. McTominay"
        assert result["key_events"][0]["minute"] == ""

    def test_substitutes_not_marked_as_starters(self):
        lineups = {"response": [{
            "team": {"id": 1, "name": "Home"},
            "formation": "4-3-3",
            "startXI": [{"player": {"name": "Starter", "number": 9, "pos": "F"}}],
            "substitutes": [{"player": {"name": "Sub", "number": 20, "pos": "M"}}],
        }]}
        result = process_api_football_fixture_enrichment(None, None, lineups, home_team_id=1, away_team_id=2)
        by_name = {p["name"]: p for p in result["lineup_home"]}
        assert by_name["Starter"]["starter"] is True
        assert by_name["Sub"]["starter"] is False


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


class TestSummaryParser:
    process_summary_data = staticmethod(_scoreboard.process_summary_data)

    def test_graceful_on_empty(self):
        out = self.process_summary_data({})
        assert out["lineup_home"] == [] and out["head_to_head"] == []

    def test_malformed_roster_does_not_wipe_key_events(self):
        # A null roster entry must not drop the valid keyEvents section.
        data = {
            "rosters": [None, "bad"],
            "keyEvents": [{"type": {"type": "Goal", "text": "Goal"}, "shortText": "1-0"}],
        }
        out = self.process_summary_data(data)
        assert out["lineup_home"] == []
        assert len(out["key_events"]) == 1
        assert out["key_events"][0]["type"] == "Goal"

    def test_malformed_h2h_does_not_wipe_lineups(self):
        data = {
            "rosters": [{"homeAway": "home", "formation": "4-3-3", "roster": [
                {"athlete": {"displayName": "Player"}, "jersey": "10"}]}],
            "headToHeadGames": [None, {"events": [None, "bad"]}],
        }
        out = self.process_summary_data(data)
        assert out["formation_home"] == "4-3-3"
        assert out["lineup_home"][0]["name"] == "Player"
        assert out["head_to_head"] == []

    def test_null_athlete_and_position_in_roster(self):
        data = {"rosters": [{"homeAway": "away", "roster": [
            {"athlete": None, "position": None, "jersey": "7"}]}]}
        out = self.process_summary_data(data)
        assert out["lineup_away"][0] == {
            "name": "", "short_name": "", "jersey": "7",
            "position": "", "starter": False, "headshot": "",
        }
