"""Native Home Assistant device triggers for Soccer Live match events."""

from __future__ import annotations

from collections.abc import Callable

import voluptuous as vol
from homeassistant.components.device_automation import DEVICE_TRIGGER_BASE_SCHEMA
from homeassistant.components.homeassistant.triggers import event as event_trigger
from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_PLATFORM, CONF_TYPE
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.typing import ConfigType

from .const import DOMAIN

TRIGGER_EVENTS = {
    "goal": "soccer_live_goal",
    "goal_cancelled": "soccer_live_goal_cancelled",
    "lineup_available": "soccer_live_lineup_available",
    "match_started": "soccer_live_match_started",
    "halftime": "soccer_live_halftime",
    "second_half": "soccer_live_second_half",
    "red_card": "soccer_live_red_card",
    "match_finished": "soccer_live_match_finished",
    "match_postponed": "soccer_live_match_postponed",
    "match_cancelled": "soccer_live_match_cancelled",
}

TRIGGER_SCHEMA = DEVICE_TRIGGER_BASE_SCHEMA.extend(
    {vol.Required(CONF_TYPE): vol.In(TRIGGER_EVENTS)}
)


def _entry_id_for_device(hass: HomeAssistant, device_id: str) -> str | None:
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return None
    runtime = hass.data.get(DOMAIN, {})
    return next(
        (entry_id for entry_id in device.config_entries if entry_id in runtime),
        None,
    )


async def async_get_triggers(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """Return match lifecycle triggers for a Soccer Live device."""
    if _entry_id_for_device(hass, device_id) is None:
        return []
    return [
        {
            CONF_PLATFORM: "device",
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: trigger_type,
        }
        for trigger_type in TRIGGER_EVENTS
    ]


async def async_attach_trigger(
    hass: HomeAssistant,
    config: ConfigType,
    action: Callable,
    trigger_info: dict,
):
    """Attach a device trigger to the provider-neutral event bus contract."""
    entry_id = _entry_id_for_device(hass, config[CONF_DEVICE_ID])
    event_config = event_trigger.TRIGGER_SCHEMA(
        {
            event_trigger.CONF_PLATFORM: "event",
            event_trigger.CONF_EVENT_TYPE: TRIGGER_EVENTS[config[CONF_TYPE]],
            event_trigger.CONF_EVENT_DATA: {"config_entry_id": entry_id},
        }
    )
    return await event_trigger.async_attach_trigger(
        hass,
        event_config,
        action,
        trigger_info,
        platform_type="device",
    )
