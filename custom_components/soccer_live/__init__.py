from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, _LOGGER
from .simulator import EVENT_TYPES, simulated_event

PLATFORMS = ["sensor", "calendar"]

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if not hass.services.has_service(DOMAIN, "simulate_match_event"):
        import voluptuous as vol

        async def async_simulate_match_event(call):
            event_type, payload = simulated_event(call.data["event_type"], call.data)
            hass.bus.async_fire(event_type, payload)

        hass.services.async_register(
            DOMAIN,
            "simulate_match_event",
            async_simulate_match_event,
            schema=vol.Schema({
                vol.Required("event_type"): vol.In(EVENT_TYPES),
                vol.Optional("event_id"): str,
                vol.Optional("team_id"): vol.Any(str, int),
                vol.Optional("home_team"): str,
                vol.Optional("away_team"): str,
                vol.Optional("home_score", default=0): int,
                vol.Optional("away_score", default=0): int,
                vol.Optional("player"): str,
                vol.Optional("minute"): vol.Any(str, int),
                vol.Optional("team"): str,
                vol.Optional("home_players"): list,
                vol.Optional("away_players"): list,
            }),
        )

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed (scan_interval, recent_match_hours)."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            hass.services.async_remove(DOMAIN, "simulate_match_event")
            hass.data.pop(DOMAIN, None)
    return unload_ok
