"""Native Home Assistant controls for Soccer Live entries."""

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities(
        [
            SoccerLiveButton(entry, coordinator, "refresh"),
            SoccerLiveButton(entry, coordinator, "rebuild_archive"),
            SoccerLiveButton(entry, coordinator, "play_replay"),
        ]
    )


class SoccerLiveButton(ButtonEntity):
    """One entry-level Soccer Live action."""

    _attr_has_entity_name = True

    def __init__(self, entry, coordinator, action):
        self._entry = entry
        self._coordinator = coordinator
        self._action = action
        self._attr_translation_key = action
        self._attr_unique_id = f"{entry.entry_id}_{action}"
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

    async def async_press(self) -> None:
        if self._action == "refresh":
            await self._coordinator.async_refresh()
        elif self._action == "rebuild_archive":
            await self._coordinator.async_rebuild_archive()
        else:
            await self._coordinator.async_play_replay()
