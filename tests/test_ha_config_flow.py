"""Real Home Assistant integration tests, using the official HA test helpers.

Unlike the other test files (which use lightweight stubs), these load the actual
integration inside a real Home Assistant instance, so they verify things the
stubs can't: that strings.json / translations load, that translated entity names
and pinned entity_ids are used, that sensors + the calendar share one device, and
that the reauth flow updates the entry and reloads it.

Heavier than the stub suite, so it lives on its own and is skipped unless the
Home Assistant test package is installed:
    pip install -r requirements-test.txt -r requirements-ha-test.txt
    pytest tests/test_ha_config_flow.py
"""
from unittest.mock import patch

import pytest

pytest.importorskip("pytest_homeassistant_custom_component")

from homeassistant.config_entries import SOURCE_REAUTH, SOURCE_USER
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr, entity_registry as er, translation
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.soccer_live.const import (
    CONF_API_FOOTBALL_KEY,
    CONF_PROVIDER,
    DOMAIN,
    PROVIDER_API_FOOTBALL,
    PROVIDER_ESPN,
)


@pytest.fixture(autouse=True)
def _auto_enable_custom_integrations(enable_custom_integrations):
    """Let HA discover the custom_components/soccer_live integration."""
    yield


async def test_translations_load_from_strings(hass: HomeAssistant):
    """strings.json / translations load and expose the localised entity names."""
    en = await translation.async_get_translations(hass, "en", "entity", [DOMAIN])
    nl = await translation.async_get_translations(hass, "nl", "entity", [DOMAIN])
    assert en[f"component.{DOMAIN}.entity.sensor.team_match.name"] == "Next match"
    assert nl[f"component.{DOMAIN}.entity.sensor.team_match.name"] == "Volgende wedstrijd"
    assert nl[f"component.{DOMAIN}.entity.calendar.match_calendar.name"] == "Wedstrijdkalender"


async def test_user_flow_espn_goes_to_follow_without_a_key(hass: HomeAssistant):
    """Step 1 (data source) -> ESPN needs no key -> straight to the follow step."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROVIDER: PROVIDER_ESPN}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "follow"


async def test_reauth_updates_key_and_reloads(hass: HomeAssistant):
    """A reauth flow accepts a new API-Football key and updates the entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PROVIDER: PROVIDER_API_FOOTBALL,
            CONF_API_FOOTBALL_KEY: "old-key",
            "team_id": "1",
            "team_name": "Feyenoord",
        },
        title="Soccer Live · Feyenoord",
    )
    entry.add_to_hass(hass)

    with patch(
        "custom_components.soccer_live.config_flow.async_validate_api_football_key",
        return_value=True,
    ), patch(
        "custom_components.soccer_live.async_setup_entry", return_value=True
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_REAUTH, "entry_id": entry.entry_id},
            data=entry.data,
        )
        assert result["type"] == FlowResultType.FORM
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_FOOTBALL_KEY: "new-key"}
        )
        await hass.async_block_till_done()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_FOOTBALL_KEY] == "new-key"


async def test_team_entry_wiring(hass: HomeAssistant):
    """A team entry creates verbose-id, translation-keyed entities plus a calendar,
    all grouped under one device — without any network fetch."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_PROVIDER: PROVIDER_ESPN,
            "team_id": "1",
            "team_name": "Feyenoord",
            "competition_code": "ned.1",
            "selection": "Team",
            "name": "Team Eredivisie Feyenoord",
        },
        title="Soccer Live · Feyenoord",
    )
    entry.add_to_hass(hass)

    # Patch the polling so setup doesn't hit the network; entities still register.
    with patch(
        "custom_components.soccer_live.sensor.SoccerLiveSensor.async_update",
        return_value=None,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()

    ent_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(ent_reg, entry.entry_id)
    entity_ids = {e.entity_id for e in entities}

    # Verbose, pinned entity_ids (not collapsed to sensor.next_match etc.).
    assert any(eid.startswith("sensor.soccerlive_next_") for eid in entity_ids), entity_ids
    assert any(eid.startswith("sensor.soccerlive_all_mixed_") for eid in entity_ids), entity_ids
    assert any(eid.startswith("calendar.soccer_live_") for eid in entity_ids), entity_ids

    # Names come from translation_key + has_entity_name.
    next_sensor = next(e for e in entities if e.entity_id.startswith("sensor.soccerlive_next_"))
    assert next_sensor.has_entity_name is True
    assert next_sensor.translation_key == "team_match"

    # Everything is grouped under a single device.
    dev_reg = dr.async_get(hass)
    devices = dr.async_entries_for_config_entry(dev_reg, entry.entry_id)
    assert len(devices) == 1
    assert all(e.device_id == devices[0].id for e in entities)
