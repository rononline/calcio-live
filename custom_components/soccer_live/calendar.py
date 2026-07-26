"""Calendar platform: exposes a team/competition's fixtures as a calendar.

The entity reads the match list already fetched by this config entry's sensors
(no extra polling) and turns each match into a calendar event, so fixtures show
up in the Home Assistant calendar and can drive time-based automations.
"""
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN

# Assume a match lasts about this long for the event end time.
MATCH_DURATION = timedelta(hours=2)


def _parse_start(raw):
    """Parse an ISO kickoff string. Uses the fast stdlib ``fromisoformat`` path
    (handling a trailing ``Z``) and only falls back to the slower
    ``dt_util.parse_datetime`` for unusual formats — parsing hundreds of matches
    on every calendar refresh was blocking the event loop."""
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw[:-1] + "+00:00" if raw.endswith("Z") else raw)
    except (ValueError, TypeError):
        return dt_util.parse_datetime(raw)


def match_to_event(match):
    """Build a CalendarEvent from a Soccer Live match dict, or None if it has no
    parseable kickoff time."""
    if not isinstance(match, dict):
        return None
    start = _parse_start(match.get("date_iso"))
    if start is None:
        return None
    if start.tzinfo is None:
        start = start.replace(tzinfo=dt_util.UTC)
    home = match.get("home_team") or "?"
    away = match.get("away_team") or "?"
    state = match.get("state")
    summary = f"{home} - {away}"
    if state in ("in", "post"):
        hs, as_ = match.get("home_score"), match.get("away_score")
        if hs not in (None, "N/A") and as_ not in (None, "N/A"):
            summary = f"{home} {hs} - {as_} {away}"
    league = match.get("league_name")
    description = league if league and league != "N/A" else None
    venue = match.get("venue")
    location = venue if venue and venue != "N/A" else None
    return CalendarEvent(
        start=start,
        end=start + MATCH_DURATION,
        summary=summary,
        location=location,
        description=description,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([SoccerLiveCalendar(hass, entry)])


class SoccerLiveCalendar(CalendarEntity):
    """A calendar of the fixtures already known to this config entry's sensors."""

    _attr_has_entity_name = True

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self._entry = entry
        label = entry.data.get("team_name") or entry.data.get("competition_code") or "matches"
        # Localised entity name ("Match calendar" / "Wedstrijdkalender") via
        # translation_key; the device (team/competition) supplies the context.
        self._attr_has_entity_name = True
        self._attr_translation_key = "match_calendar"
        self._attr_unique_id = f"{entry.entry_id}_calendar"
        # Group under the same device as this entry's sensors.
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Soccer Live · {label}",
            "entry_type": "service",
        }
        # Cache the parsed/sorted events between refreshes; the calendar is
        # polled and both `event` and `async_get_events` read them, so without
        # this the whole match list is re-parsed on every access.
        self._events_cache = None
        self._events_sig = None

    def _source_matches(self):
        """Return the richest match list published by this entry's sensors.

        Sensors publish their matches to a shared per-entry store, so the
        calendar reads that directly rather than depending on entity states.
        Falls back to scanning the entry's sensor entities (e.g. before the
        first sensor update has populated the store)."""
        best = []
        store = (
            self.hass.data.get(DOMAIN, {})
            .get(self._entry.entry_id, {})
            .get("match_sources", {})
        )
        for matches in store.values():
            if isinstance(matches, list) and len(matches) > len(best):
                best = matches
        if best:
            return best

        registry = er.async_get(self.hass)
        for entity in er.async_entries_for_config_entry(registry, self._entry.entry_id):
            state = self.hass.states.get(entity.entity_id)
            if not state:
                continue
            matches = state.attributes.get("matches")
            if isinstance(matches, list) and len(matches) > len(best):
                best = matches
        return best

    @staticmethod
    def _signature(matches):
        """Fingerprint of the source list so events are only re-parsed when the
        matches actually change. Covers the fields that affect a calendar entry —
        kickoff, live state and score — so a match going pre -> in -> post or a
        score update invalidates the cache (a length/time-only fingerprint would
        keep showing a stale "Team - Team" without the score). Building this tuple
        is still far cheaper than re-parsing every date and rebuilding events."""
        if not matches:
            return ()
        return tuple(
            (
                m.get("event_id"),
                m.get("date_iso"),
                m.get("state"),
                m.get("home_score"),
                m.get("away_score"),
                m.get("home_team"),
                m.get("away_team"),
                m.get("venue"),
                m.get("league_name"),
            ) if isinstance(m, dict) else (m,)
            for m in matches
        )

    def _events(self):
        matches = self._source_matches()
        sig = self._signature(matches)
        if sig == self._events_sig and self._events_cache is not None:
            return self._events_cache
        events = [e for e in (match_to_event(m) for m in matches) if e is not None]
        events.sort(key=lambda e: e.start)
        self._events_cache = events
        self._events_sig = sig
        return events

    @property
    def event(self):
        """The next upcoming (or currently ongoing) match."""
        now = dt_util.utcnow()
        for e in self._events():
            if e.end >= now:
                return e
        return None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ):
        return [
            e for e in self._events()
            if e.end >= start_date and e.start <= end_date
        ]
