"""Calendar platform tests.

Imports calendar.py with lightweight Home Assistant stubs so the pure
match -> event mapping can be tested without a full HA environment.
"""

import datetime as _dt
import importlib
import sys
import types
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


class _CalendarEvent:
    def __init__(self, start=None, end=None, summary=None, location=None, description=None):
        self.start = start
        self.end = end
        self.summary = summary
        self.location = location
        self.description = description


def _parse_datetime(value):
    try:
        return _dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def _load_calendar_module():
    _install_module("homeassistant")
    _install_module("homeassistant.config_entries", ConfigEntry=object)
    _install_module("homeassistant.core", HomeAssistant=object)
    _install_module("homeassistant.helpers")
    _install_module(
        "homeassistant.helpers.entity_registry",
        async_get=lambda hass: None,
        async_entries_for_config_entry=lambda reg, entry_id: [],
    )
    _install_module("homeassistant.helpers.entity_platform", AddEntitiesCallback=object)
    _install_module("homeassistant.components")
    _install_module("homeassistant.components.calendar", CalendarEntity=object, CalendarEvent=_CalendarEvent)
    _install_module("homeassistant.util")
    _install_module(
        "homeassistant.util.dt",
        parse_datetime=_parse_datetime,
        UTC=_dt.timezone.utc,
        utcnow=lambda: _dt.datetime.now(_dt.timezone.utc),
    )
    return importlib.import_module("custom_components.soccer_live.calendar")


_cal = _load_calendar_module()
match_to_event = _cal.match_to_event


def test_upcoming_match_maps_to_event():
    ev = match_to_event({
        "date_iso": "2026-07-17T11:30:00+00:00",
        "home_team": "Feyenoord",
        "away_team": "Charleroi",
        "state": "pre",
        "venue": "De Kuip",
        "league_name": "Oefenwedstrijd",
    })
    assert ev.summary == "Feyenoord - Charleroi"
    assert ev.location == "De Kuip"
    assert ev.description == "Oefenwedstrijd"
    assert ev.start == _dt.datetime(2026, 7, 17, 11, 30, tzinfo=_dt.timezone.utc)
    assert ev.end == ev.start + _dt.timedelta(hours=2)


def test_finished_match_includes_score_in_summary():
    ev = match_to_event({
        "date_iso": "2026-07-11T10:00:00+00:00",
        "home_team": "Feyenoord",
        "away_team": "Club Brugge",
        "state": "post",
        "home_score": "2",
        "away_score": "1",
    })
    assert ev.summary == "Feyenoord 2 - 1 Club Brugge"
    assert ev.location is None
    assert ev.description is None


def test_missing_or_bad_input_returns_none():
    assert match_to_event({"home_team": "A", "away_team": "B"}) is None  # no date
    assert match_to_event({"date_iso": "not-a-date"}) is None
    assert match_to_event(None) is None
    assert match_to_event("nope") is None


class _Hass:
    def __init__(self, data):
        self.data = data
        self.states = {}


class _Entry:
    def __init__(self, entry_id, data):
        self.entry_id = entry_id
        self.data = data


def _calendar(store):
    entry = _Entry("e1", {"team_name": "Feyenoord"})
    hass = _Hass({_cal.DOMAIN: {"e1": {"match_sources": store}}})
    return _cal.SoccerLiveCalendar(hass, entry)


def test_calendar_reads_richest_list_from_shared_store():
    small = [{"date_iso": "2027-07-17T11:30:00+00:00", "home_team": "A", "away_team": "B", "state": "pre"}]
    big = small + [{"date_iso": "2027-07-20T11:30:00+00:00", "home_team": "C", "away_team": "D", "state": "pre"}]
    cal = _calendar({"s1": small, "s2": big})
    # Picks the source exposing the most matches.
    assert cal._source_matches() is big
    events = cal._events()
    assert len(events) == 2
    # Sorted by start time.
    assert events[0].start < events[1].start


def test_calendar_get_events_filters_by_range():
    matches = [
        {"date_iso": "2027-07-17T11:30:00+00:00", "home_team": "A", "away_team": "B", "state": "pre"},
        {"date_iso": "2027-08-01T18:00:00+00:00", "home_team": "C", "away_team": "D", "state": "pre"},
    ]
    cal = _calendar({"s1": matches})
    start = _dt.datetime(2027, 7, 1, tzinfo=_dt.timezone.utc)
    end = _dt.datetime(2027, 7, 31, tzinfo=_dt.timezone.utc)
    import asyncio
    events = asyncio.run(cal.async_get_events(cal.hass, start, end))
    assert len(events) == 1
    assert events[0].summary == "A - B"


def test_calendar_empty_store_returns_no_matches():
    cal = _calendar({})
    assert cal._source_matches() == []
