"""Native automation-friendly match-state binary sensors."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .derived import entry_match_state

KINDS = (
    "match_live",
    "match_today",
    "match_tomorrow",
    "lineup_available",
    "data_degraded",
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([
        SoccerLiveMatchBinarySensor(entry, coordinator, kind) for kind in KINDS
    ])


class SoccerLiveMatchBinarySensor(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry, coordinator, kind):
        self._entry = entry
        self._coordinator = coordinator
        self._kind = kind
        self._attr_translation_key = kind
        self._attr_unique_id = f"{entry.entry_id}_{kind}"
        self._attr_icon = {
            "match_live": "mdi:soccer",
            "match_today": "mdi:calendar-today",
            "match_tomorrow": "mdi:calendar-arrow-right",
            "lineup_available": "mdi:account-group",
            "data_degraded": "mdi:alert-circle-outline",
        }[kind]
        label = entry.data.get("team_name") or entry.data.get("competition_code") or "matches"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Soccer Live · {label}",
            "manufacturer": "API-Football" if entry.data.get("provider") == "api_football" else "ESPN",
            "entry_type": "service",
        }
        self._unsub = None

    async def async_added_to_hass(self):
        self._unsub = self._coordinator.add_listener(self._updated)

    async def async_will_remove_from_hass(self):
        if self._unsub:
            self._unsub()

    def _updated(self):
        if self.hass and self.entity_id:
            self.async_write_ha_state()

    def _state(self):
        matches = []
        degraded = False
        for entity in self._coordinator.entities:
            attrs = getattr(entity, "_attributes", {}) or {}
            matches.extend(attrs.get("matches") or [])
            degraded = degraded or bool(getattr(entity, "_last_error", None)) or any(
                item.get("severity") in {"warning", "error"}
                for item in (attrs.get("data_alerts") or [])
                if isinstance(item, dict)
            )
        state = entry_match_state(matches, dt_util.now())
        state["data_degraded"] = state["data_degraded"] or degraded
        return state

    @property
    def is_on(self):
        return bool(self._state()[self._kind])

    @property
    def extra_state_attributes(self):
        state = self._state()
        focus = state.get("focus_match") or {}
        return {
            "config_entry_id": self._entry.entry_id,
            "event_id": focus.get("event_id"),
            "home_team": focus.get("home_team"),
            "away_team": focus.get("away_team"),
            "live_count": state["live_count"],
            "today_count": state["today_count"],
            "tomorrow_count": state["tomorrow_count"],
        }
