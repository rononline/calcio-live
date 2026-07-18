"""Config flow tests with lightweight Home Assistant stubs."""

import asyncio
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


def _load_config_flow_module():
    class _Voluptuous:
        @staticmethod
        def Schema(value):
            return value

        @staticmethod
        def Required(key, default=None):
            return key

        @staticmethod
        def Optional(key, default=None):
            return key

        @staticmethod
        def In(value):
            return value

        @staticmethod
        def Coerce(_type):
            return _type

    class _Handlers:
        def register(self, _domain):
            def decorator(cls):
                return cls
            return decorator

    class _ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            return super().__init_subclass__()

        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    class _OptionsFlow:
        def async_show_form(self, **kwargs):
            return {"type": "form", **kwargs}

        def async_create_entry(self, **kwargs):
            return {"type": "create_entry", **kwargs}

    class _ClientTimeout:
        def __init__(self, *args, **kwargs):
            pass

    class _ClientError(Exception):
        pass

    _install_module(
        "voluptuous",
        Schema=_Voluptuous.Schema,
        Required=_Voluptuous.Required,
        Optional=_Voluptuous.Optional,
        In=_Voluptuous.In,
        Coerce=_Voluptuous.Coerce,
    )
    _install_module("aiohttp", ClientTimeout=_ClientTimeout, ClientError=_ClientError)
    _install_module("homeassistant")
    _install_module(
        "homeassistant.config_entries",
        HANDLERS=_Handlers(),
        ConfigFlow=_ConfigFlow,
        OptionsFlow=_OptionsFlow,
        ConfigEntry=object,
    )
    sys.modules["homeassistant"].config_entries = sys.modules["homeassistant.config_entries"]
    _install_module("homeassistant.core", callback=lambda func: func, HomeAssistant=object)
    _install_module("homeassistant.helpers")
    _install_module("homeassistant.helpers.aiohttp_client", async_get_clientsession=lambda hass: None)
    sys.modules.pop("custom_components.soccer_live.config_flow", None)
    return importlib.import_module("custom_components.soccer_live.config_flow")


_config_flow_mod = _load_config_flow_module()
SoccerLiveConfigFlow = _config_flow_mod.SoccerLiveConfigFlow


async def _always_valid(_key):
    return True


async def _always_invalid(_key):
    return False


def test_api_football_team_starts_team_search_step():
    flow = SoccerLiveConfigFlow()
    flow._validate_api_football_key = _always_valid

    result = asyncio.run(flow.async_step_user({
        "provider": "api_football",
        "selection": "Team",
        "api_football_key": "test-key",
        "api_football_season": 0,
        "include_friendlies": True,
    }))

    assert result["type"] == "form"
    assert result["step_id"] == "api_football_team_search"
    assert flow._data["provider"] == "api_football"


def test_api_football_label_value_is_normalized():
    flow = SoccerLiveConfigFlow()
    flow._validate_api_football_key = _always_valid

    result = asyncio.run(flow.async_step_user({
        "provider": "API-Football",
        "selection": "Team",
        "api_football_key": "test-key",
        "api_football_season": 0,
        "include_friendlies": True,
    }))

    assert result["type"] == "form"
    assert result["step_id"] == "api_football_team_search"
    assert flow._data["provider"] == "api_football"


def test_api_football_invalid_key_reports_error():
    flow = SoccerLiveConfigFlow()
    flow._validate_api_football_key = _always_invalid

    result = asyncio.run(flow.async_step_user({
        "provider": "api_football",
        "selection": "Team",
        "api_football_key": "bad-key",
        "api_football_season": 0,
        "include_friendlies": True,
    }))

    # Rejected keys re-show the user form with the invalid_api_key error and
    # do not advance to the team search step.
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    assert flow._errors.get("api_football_key") == "invalid_api_key"


class _FakeEntry:
    def __init__(self, provider):
        self.data = {_config_flow_mod.CONF_PROVIDER: provider}
        self.options = {}


def _options_schema(provider):
    flow = _config_flow_mod.SoccerLiveOptionsFlow()
    flow.config_entry = _FakeEntry(provider)
    result = asyncio.run(flow.async_step_init())
    assert result["type"] == "form"
    return result["data_schema"]


def test_options_flow_shows_club_and_live_odds_for_api_football():
    schema = _options_schema(_config_flow_mod.PROVIDER_API_FOOTBALL)
    assert "enable_club_data" in schema
    assert "enable_live_odds" in schema


def test_options_flow_hides_club_and_live_odds_for_espn():
    schema = _options_schema(_config_flow_mod.PROVIDER_ESPN)
    assert "enable_club_data" not in schema
    assert "enable_live_odds" not in schema
    # The generic options stay available for every provider.
    assert "enable_summary_enrichment" in schema


def test_options_flow_exposes_shared_card_defaults():
    schema = _options_schema(_config_flow_mod.PROVIDER_API_FOOTBALL)
    for key in ("card_appearance", "card_palette", "card_compact", "card_language"):
        assert key in schema, key
    # Also present for ESPN (card defaults are provider-independent).
    espn = _options_schema(_config_flow_mod.PROVIDER_ESPN)
    assert "card_palette" in espn
