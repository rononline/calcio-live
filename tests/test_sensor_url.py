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

    async def _calendar_should_not_be_called():
        raise AssertionError(f"calendar should not be called for {sensor_type}")

    sensor._get_calendar_data = _calendar_should_not_be_called
    return sensor


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
