"""Sensor URL tests.

These tests import sensor.py with lightweight Home Assistant/aiohttp stubs so
URL-building regressions can be tested without a full HA test environment.
"""

import asyncio
import importlib
import logging
import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _install_module(name, **attrs):
    module = types.ModuleType(name)
    for key, value in attrs.items():
        setattr(module, key, value)
    sys.modules[name] = module
    return module


def _load_sensor_module():
    class _Entity:
        pass

    class _Store:
        def __init__(self, *args, **kwargs):
            pass

    class _ClientTimeout:
        def __init__(self, *args, **kwargs):
            pass

    class _ClientError(Exception):
        pass

    class _ClientResponseError(_ClientError):
        def __init__(self, status=500, message=""):
            super().__init__(message)
            self.status = status
            self.message = message

    _install_module("aiohttp", ClientTimeout=_ClientTimeout, ClientError=_ClientError, ClientResponseError=_ClientResponseError)
    _install_module("homeassistant")
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module("homeassistant.core", HomeAssistant=object)
    _install_module("homeassistant.helpers")
    _install_module("homeassistant.helpers.entity", Entity=_Entity)
    _install_module("homeassistant.helpers.storage", Store=_Store)
    _install_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _install_module("homeassistant.helpers.event", async_call_later=lambda *args, **kwargs: None)
    _install_module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)

    return importlib.import_module("custom_components.soccer_live.sensor")


_sensor_mod = _load_sensor_module()
SoccerLiveSensor = _sensor_mod.SoccerLiveSensor


def test_entity_object_id_removes_home_assistant_invalid_characters():
    assert _sensor_mod.safe_entity_object_id(
        "soccerlive_standings_Eredivisie #88 (Netherlands)"
    ) == "soccerlive_standings_eredivisie_88_netherlands"
    assert _sensor_mod.safe_entity_object_id("soccer_live_next_feyenoord") == "soccer_live_next_feyenoord"
    assert _sensor_mod.safe_entity_object_id("São Paulo") == "sao_paulo"


def _sensor(sensor_type, code="ned.1", team_name=None, team_id="1234", provider="espn"):
    sensor = SoccerLiveSensor.__new__(SoccerLiveSensor)
    sensor._name = f"test_{sensor_type}"
    sensor.hass = None
    sensor._code = code
    sensor._sensor_type = sensor_type
    sensor._team_name = team_name
    sensor._team_id = team_id
    sensor._provider = provider
    sensor._api_football_key = "test-key" if provider == "api_football" else ""
    sensor._api_football_season = 2026 if provider == "api_football" else None
    sensor._api_football_quota = {}
    sensor._include_friendlies = True
    sensor._recent_match_hours = 24
    sensor._live_scan_interval = 60
    sensor._attributes = {}
    sensor._last_error = None
    sensor._start_date = datetime(2026, 1, 1)
    sensor._end_date = datetime(2026, 12, 31)
    sensor._dyn_start_date = None
    sensor._dyn_end_date = None
    sensor.base_url = "https://site.web.api.espn.com/apis/v2/sports/soccer"
    sensor.base_url_2 = "https://site.api.espn.com/apis/site/v2/sports/soccer"
    sensor.base_url_3 = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
    sensor.api_football_base_url = "https://v3.football.api-sports.io"
    sensor._summary_cache = {}
    sensor._previous_scores = {}
    sensor._previous_match_details = {}
    sensor._previous_match_states = {}
    sensor._dispatched_goal_details = {}
    sensor._match_finished_dispatched = set()
    sensor._match_finished_list = []
    sensor._pending_events = []
    sensor._live_unsub = None
    sensor._enable_live_odds = False

    async def _calendar_should_not_be_called():
        raise AssertionError(f"calendar should not be called for {sensor_type}")

    sensor._get_calendar_data = _calendar_should_not_be_called
    return sensor


def test_pick_goal_strings_attributes_penalties_across_providers():
    sensor = _sensor("team_match")
    # ESPN scored-penalty string ("Penalty - Scored") and API-Football's
    # ("Goal - Penalty") must both be picked up; a miss and a disallowed goal
    # must be ignored.
    details = [
        "Penalty - Scored [ARS] - 20': Saka",       # ESPN
        "Goal - Penalty - 55': De Bruyne",           # API-Football
        "Penalty - Missed [ARS] - 70': Odegaard",    # miss -> ignore
        "Goal - Disallowed [ARS] - 80': Jesus",      # VAR -> ignore
    ]
    picked = sensor._pick_goal_strings(details, dispatched=set(), team_abbrev="", count=4)
    assert picked == [
        "Penalty - Scored [ARS] - 20': Saka",
        "Goal - Penalty - 55': De Bruyne",
    ]


def test_single_match_enrichment_skips_far_future_pre_match():
    sensor = _sensor("team_match", provider="api_football")
    now = datetime(2026, 7, 10, 12, 0, tzinfo=timezone.utc)

    def _m(state, hours_ahead=None):
        m = {"state": state}
        if hours_ahead is not None:
            m["date_iso"] = (now + timedelta(hours=hours_ahead)).isoformat()
        return m

    # Live and finished are always enriched.
    assert sensor._should_enrich_api_football_target(_m("in"), now) is True
    assert sensor._should_enrich_api_football_target(_m("post"), now) is True
    # Upcoming match close to kickoff -> enrich; days away -> skip.
    assert sensor._should_enrich_api_football_target(_m("pre", 2), now) is True
    assert sensor._should_enrich_api_football_target(_m("pre", 26), now) is False
    # A pre match whose kickoff already passed (delayed) is still enriched.
    assert sensor._should_enrich_api_football_target(_m("pre", -1), now) is True
    # Missing date -> skip rather than fetch blindly.
    assert sensor._should_enrich_api_football_target(_m("pre"), now) is False


def test_prematch_snapshot_reattached_when_match_goes_live():
    SoccerLiveSensor._prematch_cache = {}
    sensor = _sensor("team_match", provider="api_football")

    pre = {
        "event_id": "555", "state": "pre",
        "prediction": {"percent_home": 60}, "odds": {"home": 1.5},
        "injuries_home": [{"player": "X"}], "injuries_away": [],
        "home_rank": 2, "home_points": 65,
    }
    sensor._store_prematch(pre)
    assert "555" in SoccerLiveSensor._prematch_cache

    # The same fixture is rebuilt as a live match without the pre-match fields.
    live = {"event_id": "555", "state": "in", "home_score": "1", "away_score": "0"}
    sensor._reattach_prematch([live])

    assert live["prediction"] == {"percent_home": 60}
    assert live["odds"] == {"home": 1.5}
    assert live["injuries_home"] == [{"player": "X"}]
    assert live["home_rank"] == 2


def test_prematch_target_prefers_live_match():
    sensor = _sensor("team_match", provider="api_football")
    matches = [
        {"event_id": "1", "state": "pre", "date_iso": "2026-08-01T12:00:00+00:00"},
        {"event_id": "2", "state": "in"},
    ]
    assert sensor._prematch_target_match(matches)["event_id"] == "2"
    # No live match -> nearest upcoming.
    assert sensor._prematch_target_match([matches[0]])["event_id"] == "1"


def test_store_prematch_merges_and_keeps_pre_match_odds():
    SoccerLiveSensor._prematch_cache = {}
    sensor = _sensor("team_match", provider="api_football")
    # Stored while pre (has odds).
    sensor._store_prematch({"event_id": "7", "prediction": {"p": 1}, "odds": {"home": 1.5}})
    # Live fetch: prediction present, odds gone.
    sensor._store_prematch({"event_id": "7", "prediction": {"p": 2}})
    snap = SoccerLiveSensor._prematch_cache["7"]
    assert snap["prediction"] == {"p": 2}   # updated
    assert snap["odds"] == {"home": 1.5}     # pre-match odds retained


def test_reattach_does_not_overwrite_existing_fields():
    SoccerLiveSensor._prematch_cache = {}
    sensor = _sensor("team_match", provider="api_football")
    sensor._store_prematch({"event_id": "9", "state": "pre", "odds": {"home": 2.0}})
    live = {"event_id": "9", "state": "in", "odds": {"home": 9.9}}
    sensor._reattach_prematch([live])
    assert live["odds"] == {"home": 9.9}  # current value kept


def test_large_attributes_are_excluded_from_recorder():
    # The big / high-churn attributes should be kept out of recorder history.
    unrecorded = SoccerLiveSensor._unrecorded_attributes
    for attr in ("matches", "previous_matches", "upcoming_matches", "next_match",
                 "standings_groups", "scorers", "articles", "rounds",
                 "last_event", "last_goal_event", "last_match_finished_event"):
        assert attr in unrecorded, attr
    # Small scalar attributes must stay recordable (state history stays useful).
    for attr in ("last_event_type", "provider", "request_count", "api_status"):
        assert attr not in unrecorded, attr


def test_rate_limit_backoff_pauses_and_resets():
    import datetime as _dt
    SoccerLiveSensor._af_backoff = 0
    SoccerLiveSensor._af_enrich_pause_until = None
    assert SoccerLiveSensor._af_enrichment_paused() is False

    # First 429 → paused with a backoff; a second doubles it.
    SoccerLiveSensor._af_note_rate_limited()
    first = SoccerLiveSensor._af_backoff
    assert first == 60
    assert SoccerLiveSensor._af_enrichment_paused() is True
    SoccerLiveSensor._af_note_rate_limited()
    assert SoccerLiveSensor._af_backoff == 120

    # A straggler success during the pause window must NOT clear the backoff.
    SoccerLiveSensor._af_note_success()
    assert SoccerLiveSensor._af_backoff == 120
    assert SoccerLiveSensor._af_enrichment_paused() is True

    # Backoff is capped.
    SoccerLiveSensor._af_backoff = 1800
    SoccerLiveSensor._af_note_rate_limited()
    assert SoccerLiveSensor._af_backoff == 1800

    # Once the pause window has elapsed, a success clears it.
    import datetime as _dt
    SoccerLiveSensor._af_enrich_pause_until = _dt.datetime.now() - _dt.timedelta(seconds=1)
    SoccerLiveSensor._af_note_success()
    assert SoccerLiveSensor._af_backoff == 0
    assert SoccerLiveSensor._af_enrich_pause_until is None
    assert SoccerLiveSensor._af_enrichment_paused() is False


def test_paused_enrichment_serves_cache_and_skips_network():
    import asyncio
    SoccerLiveSensor._api_football_endpoint_cache = {}
    SoccerLiveSensor._api_football_endpoint_locks = {}
    SoccerLiveSensor._api_football_stats = {}
    sensor = _sensor("team_match", provider="api_football")

    calls = {"n": 0}

    async def _fake_uncached(path, params=None):
        calls["n"] += 1
        return {"response": [1]}

    sensor._fetch_api_football_json_uncached = _fake_uncached

    async def _run():
        # Prime the cache with one real fetch.
        await sensor._fetch_api_football_json("odds", {"fixture": 1})
        # Now simulate a rate-limit pause and force the cache to be stale.
        import datetime as _dt
        SoccerLiveSensor._af_enrich_pause_until = _dt.datetime.now() + _dt.timedelta(seconds=300)
        for entry in SoccerLiveSensor._api_football_endpoint_cache.values():
            entry["time"] = _dt.datetime.now() - _dt.timedelta(hours=1)
        return await sensor._fetch_api_football_json("odds", {"fixture": 1})

    result = asyncio.run(_run())
    SoccerLiveSensor._af_enrich_pause_until = None
    assert result == {"response": [1]}   # served from (stale) cache
    assert calls["n"] == 1               # no second network call while paused


def test_api_football_stats_track_calls_and_cache_hits():
    import asyncio
    SoccerLiveSensor._api_football_stats = {}
    SoccerLiveSensor._api_football_endpoint_cache = {}
    SoccerLiveSensor._api_football_endpoint_locks = {}
    sensor = _sensor("team_match", provider="api_football")

    async def _fake_uncached(path, params=None):
        return {"response": [1]}

    sensor._fetch_api_football_json_uncached = _fake_uncached

    async def _run():
        await sensor._fetch_api_football_json("predictions", {"fixture": 1})
        await sensor._fetch_api_football_json("predictions", {"fixture": 1})

    asyncio.run(_run())

    stat = SoccerLiveSensor._api_football_stats["predictions"]
    assert stat["calls"] == 1        # only the first request hit the network
    assert stat["cache_hits"] == 1   # the second was served from cache


def test_live_refresh_uses_configured_interval(monkeypatch):
    sensor = _sensor("team_match")
    sensor._live_scan_interval = 30
    sensor._attributes = {"matches": [{"state": "in"}]}
    calls = []

    def _fake_call_later(hass, delay, callback):
        calls.append(delay)
        return lambda: None

    monkeypatch.setattr(_sensor_mod, "async_call_later", _fake_call_later)

    sensor._schedule_live_refresh()

    assert calls == [30]


def test_live_main_cache_ttl_uses_configured_interval():
    sensor = _sensor("team_match")
    sensor._live_scan_interval = 30
    sensor._attributes = {"matches": [{"state": "in"}]}

    assert sensor._main_cache_ttl() == 30


def test_non_live_main_cache_ttl_stays_default():
    sensor = _sensor("team_match")
    sensor._live_scan_interval = 30
    sensor._attributes = {"matches": [{"state": "post"}]}

    assert sensor._main_cache_ttl() == 60


def test_standings_url_does_not_fetch_calendar():
    sensor = _sensor("standings", code="ned.1")

    url = asyncio.run(sensor._build_url())

    assert url == "https://site.web.api.espn.com/apis/v2/sports/soccer/ned.1/standings?"


def test_team_matches_mixed_url_does_not_fetch_calendar():
    sensor = _sensor("team_matches_mixed", code="ned.1", team_name="Feyenoord", team_id="1234")

    url = asyncio.run(sensor._build_url())

    assert url == "https://site.web.api.espn.com/apis/site/v2/sports/soccer/all/teams/1234/schedule?fixture=true"


def test_all_matches_today_url_does_not_fetch_calendar():
    sensor = _sensor("all_matches_today", code="99999")

    url = asyncio.run(sensor._build_url())

    assert url == "https://site.api.espn.com/apis/site/v2/sports/soccer/all/scoreboard"


def test_team_match_uses_calendar_dates_when_available():
    sensor = _sensor("team_match", code="ned.1")
    calls = {"count": 0}

    async def _calendar():
        calls["count"] += 1
        return "2026-08-01T00:00Z", "2027-06-01T00:00Z"

    sensor._get_calendar_data = _calendar

    url = asyncio.run(sensor._build_url())

    assert calls["count"] == 1
    assert url == "https://site.web.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?limit=1000&dates=20260801-20270601"
    assert sensor._dyn_start_date == datetime(2026, 8, 1)
    assert sensor._dyn_end_date == datetime(2027, 6, 1)


def test_team_match_falls_back_to_static_dates_when_calendar_missing():
    sensor = _sensor("team_match", code="ned.1")

    async def _calendar():
        return None, None

    sensor._get_calendar_data = _calendar

    url = asyncio.run(sensor._build_url())

    assert url == "https://site.web.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?limit=1000&dates=20260101-20261231"


def test_team_match_omits_dates_when_calendar_and_filters_are_missing():
    sensor = _sensor("team_match", code="ned.1")
    sensor._start_date = None
    sensor._end_date = None

    async def _calendar():
        return None, None

    sensor._get_calendar_data = _calendar

    url = asyncio.run(sensor._build_url())

    assert url == "https://site.web.api.espn.com/apis/site/v2/sports/soccer/ned.1/scoreboard?limit=1000"


def test_api_football_team_match_url_uses_team_season_and_dates():
    sensor = _sensor("team_match", code="39", team_name="Arsenal", team_id="42", provider="api_football")

    url = asyncio.run(sensor._build_url())

    assert url == "https://v3.football.api-sports.io/fixtures?team=42&season=2026&from=2026-01-01&to=2026-12-31"


def test_api_football_standings_url_uses_league_and_season():
    sensor = _sensor("standings", code="39", provider="api_football")

    url = asyncio.run(sensor._build_url())

    assert url == "https://v3.football.api-sports.io/standings?league=39&season=2026"


def test_api_football_top_scorers_url_uses_league_and_season():
    sensor = _sensor("top_scorers", code="39", provider="api_football")

    url = asyncio.run(sensor._build_url())

    assert url == "https://v3.football.api-sports.io/players/topscorers?league=39&season=2026"


def test_api_football_all_matches_today_uses_ha_timezone(monkeypatch):
    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = cls(2026, 1, 1, 23, 30, tzinfo=timezone.utc)
            return current.astimezone(tz) if tz else current.replace(tzinfo=None)

    class _Hass:
        class config:
            time_zone = "Europe/Amsterdam"

    sensor = _sensor("all_matches_today", code="39", provider="api_football")
    sensor.hass = _Hass()
    monkeypatch.setattr(_sensor_mod, "datetime", _FakeDateTime)

    url = asyncio.run(sensor._build_url())

    assert url == "https://v3.football.api-sports.io/fixtures?date=2026-01-02"


def test_api_football_standings_auto_season_uses_previous_before_august(monkeypatch):
    class _FakeDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 7, 4)

    sensor = _sensor("standings", code="39", provider="api_football")
    sensor._api_football_season = None
    monkeypatch.setattr(_sensor_mod, "datetime", _FakeDateTime)

    url = asyncio.run(sensor._build_url())

    assert url == "https://v3.football.api-sports.io/standings?league=39&season=2025"


def test_api_football_enrichment_updates_match_from_extra_endpoints():
    sensor = _sensor("team_match", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "in",
            "home_id": 42,
            "away_id": 50,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "date": "05-07-2026 12:00",
            "home_score": "1",
            "away_score": "0",
            "match_details": [],
        }]
    }

    class _Hass:
        class config:
            time_zone = "Europe/Amsterdam"

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        if path == "fixtures/events":
            return {"response": [{
                "time": {"elapsed": 12},
                "team": {"id": 42, "name": "Arsenal"},
                "player": {"name": "Player One"},
                "type": "Goal",
                "detail": "Normal Goal",
            }]}
        if path == "fixtures/statistics":
            return {"response": [{
                "team": {"id": 42},
                "statistics": [{"type": "Shots on Goal", "value": 7}],
            }, {
                "team": {"id": 50},
                "statistics": [{"type": "Shots on Goal", "value": 3}],
            }]}
        if path == "fixtures/lineups":
            return {"response": [{
                "team": {"id": 42},
                "formation": "4-3-3",
                "startXI": [{"player": {"name": "Player One", "number": 9, "pos": "F"}}],
                "substitutes": [],
            }]}
        return None

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    match = sensor._attributes["matches"][0]
    assert len(match["key_events"]) == 1
    assert match["home_statistics"]["Shots on Goal"] == 7
    assert match["formation_home"] == "4-3-3"
    assert match["lineup_home"][0]["name"] == "Player One"


def test_api_football_team_matches_enriches_recent_finished_match():
    sensor = _sensor("team_matches", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "post",
            "date_iso": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "home_id": 42,
            "away_id": 50,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_score": "1",
            "away_score": "0",
            "match_details": [],
            "key_events": [],
        }]
    }

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        if path == "fixtures/events":
            return {"response": [{
                "time": {"elapsed": 22},
                "team": {"id": 42, "name": "Arsenal"},
                "player": {"name": "Player One"},
                "type": "Goal",
                "detail": "Normal Goal",
            }]}
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    match = sensor._attributes["matches"][0]
    assert match["key_events"][0]["player"] == "Player One"
    assert match["match_details"][0] == "Goal - 22': Player One"
    recent = sensor._attributes["schedule_recent_matches"][0]
    assert recent["event_id"] == "100"
    assert recent["match_details"][0] == "Goal - 22': Player One"
    assert recent["key_events"][0]["player"] == "Player One"


def test_api_football_team_matches_mixed_enriches_recent_finished_match():
    sensor = _sensor("team_matches_mixed", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "post",
            "date_iso": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "home_id": 42,
            "away_id": 50,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_score": "1",
            "away_score": "0",
            "match_details": [],
            "key_events": [],
        }]
    }

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        if path == "fixtures/events":
            return {"response": [{
                "time": {"elapsed": 22},
                "team": {"id": 42, "name": "Arsenal"},
                "player": {"name": "Player One"},
                "type": "Goal",
                "detail": "Normal Goal",
            }]}
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    match = sensor._attributes["matches"][0]
    assert match["key_events"][0]["player"] == "Player One"
    assert match["match_details"][0] == "Goal - 22': Player One"


def test_api_football_enrichment_attaches_cached_head_to_head_to_next_match():
    sensor = _sensor("team_match", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "pre",
            "date_iso": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
            "home_id": 50,
            "away_id": 42,
            "home_team": "Chelsea",
            "away_team": "Arsenal",
        }]
    }
    calls = []

    class _Hass:
        class config:
            language = "en"
            time_zone = "Europe/Amsterdam"

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        calls.append((path, params))
        if path == "fixtures/headtohead":
            return {"response": [{
                "fixture": {
                    "id": 90,
                    "date": "2026-01-01T15:00:00+00:00",
                    "status": {"short": "FT", "long": "Match Finished"},
                    "venue": {"name": "Emirates Stadium"},
                },
                "league": {"id": 39, "name": "Premier League", "season": 2025},
                "teams": {
                    "home": {"id": 42, "name": "Arsenal"},
                    "away": {"id": 50, "name": "Chelsea"},
                },
                "goals": {"home": 2, "away": 1},
            }]}
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    head_to_head = sensor._attributes["matches"][0]["head_to_head"]
    assert head_to_head[0]["event_id"] == "90"
    assert head_to_head[0]["home_score"] == "2"
    assert ("fixtures/headtohead", {"h2h": "42-50", "last": 8}) in calls
    assert sensor._api_football_cache_ttl("fixtures/headtohead") == 86400


def test_api_football_list_enrichment_fetches_head_to_head_before_fixture_details():
    sensor = _sensor(
        "team_matches_mixed",
        code="88",
        team_name="Feyenoord",
        team_id="209",
        provider="api_football",
    )
    sensor._attributes = {
        "matches": [
            {
                "event_id": "1552122",
                "state": "pre",
                "date_iso": (datetime.now(timezone.utc) + timedelta(days=7)).isoformat(),
                "home_id": 426,
                "away_id": 209,
                "home_team": "Sparta Rotterdam",
                "away_team": "Feyenoord",
            },
            {
                "event_id": "finished-1",
                "state": "post",
                "date_iso": (datetime.now(timezone.utc) - timedelta(days=7)).isoformat(),
                "home_id": 209,
                "away_id": 123,
                "home_team": "Feyenoord",
                "away_team": "Opponent",
            },
        ]
    }
    calls = []

    class _Hass:
        class config:
            language = "nl"
            time_zone = "Europe/Amsterdam"

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        calls.append((path, params))
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    assert calls[0] == (
        "fixtures/headtohead",
        {"h2h": "209-426", "last": 8},
    )


def test_api_football_list_enrichment_fetches_h2h_for_selectable_upcoming_matches():
    sensor = _sensor(
        "team_matches_mixed",
        code="88",
        team_name="Feyenoord",
        team_id="209",
        provider="api_football",
    )
    now = datetime.now(timezone.utc)
    sensor._attributes = {
        "matches": [
            {
                "event_id": "atalanta",
                "state": "pre",
                "date_iso": (now + timedelta(days=2)).isoformat(),
                "home_id": 209,
                "away_id": 499,
            },
            {
                "event_id": "sparta",
                "state": "pre",
                "date_iso": (now + timedelta(days=9)).isoformat(),
                "home_id": 426,
                "away_id": 209,
            },
        ]
    }
    calls = []

    class _Hass:
        class config:
            language = "nl"
            time_zone = "Europe/Amsterdam"

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        calls.append((path, params))
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    h2h_calls = [call for call in calls if call[0] == "fixtures/headtohead"]
    assert h2h_calls == [
        ("fixtures/headtohead", {"h2h": "209-499", "last": 8}),
        ("fixtures/headtohead", {"h2h": "209-426", "last": 8}),
    ]


def test_api_football_empty_post_match_enrichment_is_not_cached():
    sensor = _sensor("team_matches_mixed", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "post",
            "date_iso": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "home_id": 42,
            "away_id": 50,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_score": "1",
            "away_score": "0",
            "match_details": [],
            "key_events": [],
        }]
    }

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    assert "100" not in sensor._summary_cache
    assert sensor._attributes["matches"][0]["match_details"] == []


def test_api_football_team_matches_mixed_enriches_latest_finished_outside_recent_window():
    sensor = _sensor("team_matches_mixed", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    sensor._recent_match_hours = 1
    sensor._attributes = {
        "matches": [{
            "event_id": "100",
            "state": "post",
            "date": "04-07-2026 12:00",
            "date_iso": (datetime.now(timezone.utc) - timedelta(hours=30)).isoformat(),
            "home_id": 42,
            "away_id": 50,
            "home_team": "Arsenal",
            "away_team": "Chelsea",
            "home_score": "1",
            "away_score": "0",
            "match_details": [],
            "key_events": [],
        }]
    }

    class _Hass:
        class config:
            time_zone = "Europe/Amsterdam"

        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        if path == "fixtures/events":
            return {"response": [{
                "time": {"elapsed": 22},
                "team": {"id": 42, "name": "Arsenal"},
                "player": {"name": "Player One"},
                "type": "Goal",
                "detail": "Normal Goal",
            }]}
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_with_api_football_fixture())

    match = sensor._attributes["matches"][0]
    assert match["match_details"][0] == "Goal - 22': Player One"


def test_api_football_endpoint_cache_reuses_response(monkeypatch):
    sensor = _sensor("team_match", code="39", team_name="Arsenal", team_id="42", provider="api_football")
    calls = {"count": 0}

    class _Response:
        status = 200

        async def read(self):
            return b'{"response": [{"ok": true}]}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class _Session:
        def get(self, *args, **kwargs):
            calls["count"] += 1
            return _Response()

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    sensor.hass = _Hass()
    SoccerLiveSensor._api_football_endpoint_cache = {}
    SoccerLiveSensor._api_football_endpoint_locks = {}
    monkeypatch.setattr(_sensor_mod, "async_get_clientsession", lambda hass: _Session())

    first = asyncio.run(sensor._fetch_api_football_json("fixtures/events", {"fixture": "100"}))
    second = asyncio.run(sensor._fetch_api_football_json("fixtures/events", {"fixture": "100"}))

    assert first == second
    assert calls["count"] == 1


def test_failed_processing_does_not_cache_response(monkeypatch):
    sensor = _sensor("team_match", code="ned.1")
    sensor._last_error = None
    sensor._last_successful_update = None
    sensor._request_count = 0
    sensor._last_request_time = None
    sensor._scorers_unavailable = False
    sensor._schedule_live_refresh = lambda: None

    async def _build_url():
        return "https://example.test/scoreboard"

    async def _process_and_apply(data):
        raise ValueError("broken payload")

    class _Response:
        status = 200

        async def read(self):
            return b'{"events": []}'

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class _Session:
        def get(self, *args, **kwargs):
            return _Response()

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    sensor.hass = _Hass()
    sensor._build_url = _build_url
    sensor._process_and_apply = _process_and_apply
    SoccerLiveSensor._cache = {}
    SoccerLiveSensor._fetch_locks = {}
    monkeypatch.setattr(_sensor_mod, "async_get_clientsession", lambda hass: _Session())

    asyncio.run(sensor.async_update())

    assert "https://example.test/scoreboard" not in SoccerLiveSensor._cache
    assert sensor._last_error == "broken payload"


def test_calendar_issue_logging_is_throttled(caplog):
    caplog.set_level(logging.DEBUG, logger="custom_components.soccer_live.sensor")
    sensor = _sensor("team_match", code="ned.1")
    _sensor_mod.SoccerLiveSensor._calendar_error_logs = {}

    sensor._log_calendar_fetch_issue("timeout", "Calendar fetch timed out for %s", sensor._name)
    sensor._log_calendar_fetch_issue("timeout", "Calendar fetch timed out for %s", sensor._name)

    warning_records = [record for record in caplog.records if record.levelname == "WARNING"]
    debug_records = [record for record in caplog.records if record.levelname == "DEBUG"]

    assert len(warning_records) == 1
    assert len(debug_records) == 1


def test_api_football_assists_fetches_topassists_and_sets_attribute():
    sensor = _sensor("top_scorers", code="88", provider="api_football")
    sensor._api_football_season = 2025
    captured = {}

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        captured["path"] = path
        captured["params"] = params
        return {"response": [{
            "player": {"name": "J. Veerman"},
            "statistics": [{"team": {"id": 1, "name": "PSV"}, "goals": {"total": 8, "assists": 14}}],
        }]}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch

    asyncio.run(sensor._enrich_api_football_assists())

    assert captured["path"] == "players/topassists"
    assert captured["params"] == {"league": "88", "season": 2025}
    assert sensor._attributes["assists"][0]["player"] == "J. Veerman"
    assert sensor._attributes["assists"][0]["assists"] == 14


def _run_prematch_and_collect_paths(match, enable_live_odds):
    SoccerLiveSensor._live_odds_pause_until = None
    SoccerLiveSensor._live_odds_misses = 0
    SoccerLiveSensor._api_football_stats = {}
    SoccerLiveSensor._prematch_cache = {}
    SoccerLiveSensor._prematch_store = None
    sensor = _sensor("team_match", code="88", team_id="209", provider="api_football")
    sensor._enable_live_odds = enable_live_odds
    paths = []

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    async def _fetch(path, params=None):
        paths.append(path)
        if path == "odds/live":
            return {"response": [{"status": {"stopped": False, "blocked": False}, "odds": [
                {"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "2.0"},
                    {"value": "Draw", "odd": "3.0"},
                    {"value": "Away", "odd": "3.5"}]}]}]}
        if path == "odds":
            return {"response": [{"bookmakers": [{"name": "A", "bets": [
                {"name": "Match Winner", "values": [
                    {"value": "Home", "odd": "1.8"},
                    {"value": "Draw", "odd": "3.4"},
                    {"value": "Away", "odd": "4.2"}]}]}]}]}
        return {"response": []}

    sensor.hass = _Hass()
    sensor._fetch_api_football_json = _fetch
    asyncio.run(sensor._fetch_and_store_prematch(match))
    return sensor, paths


def test_prematch_uses_live_odds_when_live_and_enabled():
    live = {"event_id": "500", "state": "in", "home_id": 1, "away_id": 2}
    sensor, paths = _run_prematch_and_collect_paths(live, enable_live_odds=True)
    assert "odds/live" in paths
    assert "odds" not in paths
    assert sensor._attributes.get("matches") is None  # only the match dict is updated
    assert live["odds"]["live"] is True


def test_prematch_uses_pre_match_odds_when_upcoming():
    pre = {"event_id": "501", "state": "pre", "home_id": 1, "away_id": 2}
    _sensor_obj, paths = _run_prematch_and_collect_paths(pre, enable_live_odds=True)
    assert "odds" in paths
    assert "odds/live" not in paths
    assert pre["odds"].get("live") is None


def test_prematch_skips_odds_when_live_but_live_odds_disabled():
    live = {"event_id": "502", "state": "in", "home_id": 1, "away_id": 2}
    _sensor_obj, paths = _run_prematch_and_collect_paths(live, enable_live_odds=False)
    assert "odds" not in paths
    assert "odds/live" not in paths


def test_live_odds_pause_on_403_and_empty_streak():
    SoccerLiveSensor._live_odds_pause_until = None
    SoccerLiveSensor._live_odds_misses = 0
    # 403 -> paused immediately.
    SoccerLiveSensor._note_live_odds_result(403, has_response=False)
    assert SoccerLiveSensor._live_odds_available() is False
    # Reset, then a present response keeps it available and clears misses.
    SoccerLiveSensor._live_odds_pause_until = None
    SoccerLiveSensor._note_live_odds_result(200, has_response=True)
    assert SoccerLiveSensor._live_odds_available() is True
    # Five empty responses in a row -> paused.
    for _ in range(5):
        SoccerLiveSensor._note_live_odds_result(200, has_response=False)
    assert SoccerLiveSensor._live_odds_available() is False
    SoccerLiveSensor._live_odds_pause_until = None


def test_club_cache_rejects_old_version_and_expired():
    import datetime as _dt
    SoccerLiveSensor._club_cache = {}
    sensor = _sensor("team_match", provider="api_football")
    v = SoccerLiveSensor._CLUB_CACHE_VERSION
    now = _dt.datetime.now().isoformat()
    # Fresh blob at the current version is served.
    SoccerLiveSensor._club_cache["209"] = {"club": {"coach": "R. van Persie"}, "ts": now, "v": v}
    assert sensor._get_cached_club("209") == {"coach": "R. van Persie"}
    # A blob from an older code version (e.g. no version tag) is rejected so the
    # fix lands on the next refetch instead of being masked for 24h.
    SoccerLiveSensor._club_cache["209"] = {"club": {"coach": "P. Bosschaart"}, "ts": now}
    assert sensor._get_cached_club("209") is None
    # An expired blob is rejected too.
    old = (_dt.datetime.now() - _dt.timedelta(hours=25)).isoformat()
    SoccerLiveSensor._club_cache["209"] = {"club": {"coach": "X"}, "ts": old, "v": v}
    assert sensor._get_cached_club("209") is None
    SoccerLiveSensor._club_cache = {}


def test_af_rate_limit_message_detection():
    yes = SoccerLiveSensor._af_is_rate_limit_message
    assert yes("Too many requests. You have exceeded the limit of requests per minute of your subscription.")
    assert yes("You have reached the request limit for the day")
    assert yes("rateLimit exceeded")
    assert not yes("Invalid API key")
    assert not yes("")
    assert not yes(None)


def test_af_rate_limit_body_triggers_backoff(monkeypatch):
    import asyncio
    SoccerLiveSensor._af_backoff = 0
    SoccerLiveSensor._af_enrich_pause_until = None
    SoccerLiveSensor._api_football_stats = {}
    sensor = _sensor("team_match", provider="api_football")

    class _Response:
        status = 200
        async def read(self):
            return b'{"errors": {"requests": "Too many requests. You have exceeded the limit of requests per minute of your subscription."}}'
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return None

    class _Session:
        def get(self, *args, **kwargs):
            return _Response()

    class _Hass:
        async def async_add_executor_job(self, func, *args):
            return func(*args)

    sensor.hass = _Hass()
    monkeypatch.setattr(_sensor_mod, "async_get_clientsession", lambda hass: _Session())

    # A 200-body "too many requests" must trigger the shared enrichment backoff.
    result = asyncio.run(sensor._fetch_api_football_json_uncached("predictions", {"fixture": 1}))
    assert result is None
    assert SoccerLiveSensor._af_enrichment_paused() is True
    assert SoccerLiveSensor._af_backoff == 60

    SoccerLiveSensor._af_enrich_pause_until = None
    SoccerLiveSensor._af_backoff = 0


def test_af_rate_limit_stragglers_do_not_double_backoff():
    SoccerLiveSensor._af_backoff = 0
    SoccerLiveSensor._af_enrich_pause_until = None
    sensor = _sensor("team_match", provider="api_football")
    # First hit pauses and sets the backoff.
    sensor._af_handle_rate_limit("predictions", "too many requests")
    assert SoccerLiveSensor._af_backoff == 60
    assert SoccerLiveSensor._af_enrichment_paused() is True
    # A concurrent straggler from the same burst must not double the backoff.
    sensor._af_handle_rate_limit("odds", "too many requests")
    assert SoccerLiveSensor._af_backoff == 60
    SoccerLiveSensor._af_enrich_pause_until = None
    SoccerLiveSensor._af_backoff = 0


def test_af_daily_limit_pauses_until_reset():
    import datetime as _dt
    SoccerLiveSensor._af_backoff = 0
    SoccerLiveSensor._af_enrich_pause_until = None
    sensor = _sensor("team_match", provider="api_football")
    sensor._af_handle_rate_limit("predictions", "You have reached the request limit for the day")
    assert SoccerLiveSensor._af_enrichment_paused() is True
    # A daily limit pauses long (>= ~30 min) and does NOT use the per-minute backoff.
    remaining = (SoccerLiveSensor._af_enrich_pause_until - _dt.datetime.now()).total_seconds()
    assert remaining >= 1800 - 5
    assert SoccerLiveSensor._af_backoff == 0
    assert SoccerLiveSensor._af_is_daily_limit_message("exceeded the limit of requests per day") is True
    assert SoccerLiveSensor._af_is_daily_limit_message("requests per minute") is False
    SoccerLiveSensor._af_enrich_pause_until = None


def test_af_daily_limit_ends_at_utc_midnight(monkeypatch):
    import datetime as _dt

    class _Fake(_dt.datetime):
        _now = _dt.datetime(2026, 7, 20, 22, 0, tzinfo=_dt.timezone.utc)
        @classmethod
        def now(cls, tz=None):
            return cls._now.astimezone(tz) if tz else cls._now.replace(tzinfo=None)

    monkeypatch.setattr(_sensor_mod, "datetime", _Fake)
    SoccerLiveSensor._af_backoff = 120                 # a stale minute backoff
    SoccerLiveSensor._af_enrich_pause_until = None
    sensor = _sensor("team_match", provider="api_football")
    sensor._af_note_daily_limit()
    # Pause ends exactly at the next UTC midnight, and the minute backoff is cleared.
    assert SoccerLiveSensor._af_enrich_pause_until == _dt.datetime(2026, 7, 21, 0, 0)
    assert SoccerLiveSensor._af_backoff == 0
    SoccerLiveSensor._af_enrich_pause_until = None


def test_af_daily_limit_clamped_to_min_30_min(monkeypatch):
    import datetime as _dt

    class _Fake(_dt.datetime):
        _now = _dt.datetime(2026, 7, 20, 23, 50, tzinfo=_dt.timezone.utc)  # 10 min to midnight
        @classmethod
        def now(cls, tz=None):
            return cls._now.astimezone(tz) if tz else cls._now.replace(tzinfo=None)

    monkeypatch.setattr(_sensor_mod, "datetime", _Fake)
    SoccerLiveSensor._af_enrich_pause_until = None
    sensor = _sensor("team_match", provider="api_football")
    sensor._af_note_daily_limit()
    # Only 10 min to midnight -> clamped to a 30 min pause (00:20).
    assert SoccerLiveSensor._af_enrich_pause_until == _dt.datetime(2026, 7, 21, 0, 20)
    SoccerLiveSensor._af_enrich_pause_until = None
