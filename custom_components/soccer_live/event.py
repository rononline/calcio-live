"""Native Home Assistant event entity for Soccer Live match events."""

from typing import ClassVar

from homeassistant.components.event import EventEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .simulator import EVENT_TYPES

_BUS_TO_EVENT = {
    bus_event: event_type
    for event_type, (bus_event, _phase) in EVENT_TYPES.items()
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    async_add_entities([SoccerLiveMatchEvent(entry)])


class SoccerLiveMatchEvent(EventEntity):
    """Expose bus events as one automation-editor-friendly event entity."""

    _attr_has_entity_name = True
    _attr_translation_key = "match_event"
    _attr_event_types: ClassVar[list[str]] = list(EVENT_TYPES)

    def __init__(self, entry: ConfigEntry):
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_match_event"
        self._unsubs = []
        label = (
            entry.data.get("team_name")
            or entry.data.get("competition_code")
            or "matches"
        )
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": f"Soccer Live · {label}",
            "entry_type": "service",
        }

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        for bus_event in _BUS_TO_EVENT:
            self._unsubs.append(
                self.hass.bus.async_listen(bus_event, self._handle_bus_event)
            )

    async def async_will_remove_from_hass(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs = []
        await super().async_will_remove_from_hass()

    def _belongs_to_entry(self, data: dict) -> bool:
        config_entry_id = data.get("config_entry_id")
        if config_entry_id:
            return str(config_entry_id) == self._entry.entry_id
        team_id = self._entry.data.get("team_id")
        if team_id and data.get("team_id") not in (None, ""):
            return str(data.get("team_id")) == str(team_id)
        team = str(self._entry.data.get("team_name") or "").casefold()
        if team:
            return team in str(data.get("home_team") or "").casefold() or team in str(
                data.get("away_team") or ""
            ).casefold()
        return True

    def _handle_bus_event(self, event: Event) -> None:
        if not self._belongs_to_entry(event.data):
            return
        event_type = _BUS_TO_EVENT.get(event.event_type)
        if event_type:
            self._trigger_event(event_type, dict(event.data))
