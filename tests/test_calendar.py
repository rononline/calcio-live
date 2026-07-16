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
