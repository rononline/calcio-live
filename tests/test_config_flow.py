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

        def async_update_reload_and_abort(self, entry, data=None, **kwargs):
            if data is not None:
                entry.data = data
            return {"type": "abort", "reason": "reauth_successful", "data": data}

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


async def _fake_competitions():
    return {"1": "Eredivisie"}


OPT_TEAM = _config_flow_mod.OPTION_SELECT_TEAM
OPT_LEAGUE = _config_flow_mod.OPTION_SELECT_LEAGUE
OPT_NEWS = _config_flow_mod.OPTION_NEWS
OPT_ALL_TODAY = _config_flow_mod.OPTION_ALL_TODAY
OPT_MANUAL = _config_flow_mod.OPTION_MANUAL_TEAM


# --- Step 1: data source only ------------------------------------------------

def test_user_step_asks_only_for_provider():
    flow = SoccerLiveConfigFlow()
    result = asyncio.run(flow.async_step_user())
    assert result["type"] == "form"
    assert result["step_id"] == "user"
    schema = result["data_schema"]
    assert "provider" in schema
    # Provider-specific fields moved out of step 1.
    assert "selection" not in schema
    assert "api_football_key" not in schema


def test_espn_skips_credentials_and_goes_to_follow():
    flow = SoccerLiveConfigFlow()
    result = asyncio.run(flow.async_step_user({"provider": "espn"}))
    assert result["type"] == "form"
    assert result["step_id"] == "follow"
    assert flow._data["provider"] == "espn"
    # ESPN keeps the friendlies default without prompting.
    assert flow._data["include_friendlies"] is True


def test_api_football_asks_credentials_first():
    flow = SoccerLiveConfigFlow()
    result = asyncio.run(flow.async_step_user({"provider": "API-Football"}))
    assert result["type"] == "form"
    assert result["step_id"] == "api_football_credentials"
    # Label value is normalised to the canonical provider id.
    assert flow._data["provider"] == "api_football"


# --- Step 1b: API-Football credentials --------------------------------------

def test_api_football_valid_key_advances_to_follow():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    flow._validate_api_football_key = _always_valid
    result = asyncio.run(flow.async_step_api_football_credentials({
        "api_football_key": "good-key",
        "api_football_season": 2025,
        "include_friendlies": False,
    }))
    assert result["type"] == "form"
    assert result["step_id"] == "follow"
    assert flow._data["api_football_key"] == "good-key"
    assert flow._data["api_football_season"] == 2025
    assert flow._data["include_friendlies"] is False


def test_api_football_invalid_key_reports_error():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    flow._validate_api_football_key = _always_invalid
    result = asyncio.run(flow.async_step_api_football_credentials({
        "api_football_key": "bad-key",
        "api_football_season": 0,
        "include_friendlies": True,
    }))
    # Rejected keys re-show the credentials form and do not advance.
    assert result["type"] == "form"
    assert result["step_id"] == "api_football_credentials"
    assert flow._errors.get("api_football_key") == "invalid_api_key"


def test_api_football_missing_key_reports_error():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    flow._validate_api_football_key = _always_valid
    result = asyncio.run(flow.async_step_api_football_credentials({
        "api_football_key": "  ",
        "api_football_season": 0,
        "include_friendlies": True,
    }))
    assert result["step_id"] == "api_football_credentials"
    assert flow._errors.get("api_football_key") == "api_key_required"


# --- Step 2: what to follow, filtered per provider --------------------------

def test_follow_offers_news_for_espn_and_defaults_to_team():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "espn"
    result = asyncio.run(flow.async_step_follow())
    assert result["step_id"] == "follow"
    selections = result["data_schema"]["selection"]
    assert OPT_NEWS in selections
    # Team is offered first so it is the default choice.
    assert selections[0] == OPT_TEAM


def test_follow_hides_news_for_api_football():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    result = asyncio.run(flow.async_step_follow())
    selections = result["data_schema"]["selection"]
    assert OPT_NEWS not in selections
    assert OPT_TEAM in selections


def test_follow_api_football_news_is_guarded_on_submit():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    result = asyncio.run(flow.async_step_follow({"selection": OPT_NEWS}))
    assert result["step_id"] == "follow"
    assert flow._errors.get("selection") == "unsupported_provider_selection"


def test_follow_api_football_team_goes_to_search():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "api_football"
    result = asyncio.run(flow.async_step_follow({"selection": OPT_TEAM}))
    assert result["step_id"] == "api_football_team_search"


def test_follow_espn_team_goes_to_competition_select():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "espn"
    flow._get_competitions = _fake_competitions
    result = asyncio.run(flow.async_step_follow({"selection": OPT_TEAM}))
    assert result["step_id"] == "select_competition_for_team"


def test_follow_all_today_creates_entry():
    flow = SoccerLiveConfigFlow()
    flow._data["provider"] = "espn"
    result = asyncio.run(flow.async_step_follow({"selection": OPT_ALL_TODAY}))
    assert result["type"] == "create_entry"
    assert flow._data["competition_code"] == "99999"


# --- Item 7: NL/EN labels for the new steps exist ---------------------------

def _load_translation(lang):
    import json
    path = ROOT / "custom_components" / "soccer_live" / "translations" / f"{lang}.json"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_new_steps_have_english_and_dutch_labels():
    for lang in ("en", "nl"):
        steps = _load_translation(lang)["config"]["step"]
        for step in ("user", "api_football_credentials", "follow"):
            assert step in steps, f"{lang}: missing {step}"
            assert steps[step].get("title"), f"{lang}: {step} has no title"
        # Step 1 is now provider-only in the labels too.
        assert set(steps["user"]["data"]) == {"provider"}
        # Credentials step exposes exactly the API-Football fields.
        assert set(steps["api_football_credentials"]["data"]) == {
            "api_football_key", "api_football_season", "include_friendlies"
        }


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


# --- Item 4: reauth + change API key ----------------------------------------

async def _mod_valid(_hass, _key):
    return True


async def _mod_invalid(_hass, _key):
    return False


class _MutableEntry:
    def __init__(self, data):
        self.data = dict(data)
        self.options = {}
        self.title = "Soccer Live · Test"


class _FakeConfigEntries:
    def async_update_entry(self, entry, data=None, **kwargs):
        if data is not None:
            entry.data = data


class _FakeHass:
    def __init__(self):
        self.config_entries = _FakeConfigEntries()


def _patch_validator(func):
    """Swap the module-level validator (used by reauth/options), returning the
    original so the caller can restore it."""
    original = _config_flow_mod.async_validate_api_football_key
    _config_flow_mod.async_validate_api_football_key = func
    return original


def test_reauth_valid_key_updates_entry_and_aborts():
    flow = SoccerLiveConfigFlow()
    flow.hass = _FakeHass()
    entry = _MutableEntry({"provider": "api_football", "api_football_key": "old"})
    flow._reauth_entry = entry
    original = _patch_validator(_mod_valid)
    try:
        result = asyncio.run(flow.async_step_reauth_confirm({"api_football_key": "new-key"}))
    finally:
        _patch_validator(original)
    assert result["type"] == "abort"
    assert result["reason"] == "reauth_successful"
    assert entry.data["api_football_key"] == "new-key"
    # The rest of the config (provider, selection) is preserved.
    assert entry.data["provider"] == "api_football"


def test_reauth_invalid_key_stays_on_form():
    flow = SoccerLiveConfigFlow()
    flow.hass = _FakeHass()
    entry = _MutableEntry({"provider": "api_football", "api_football_key": "old"})
    flow._reauth_entry = entry
    original = _patch_validator(_mod_invalid)
    try:
        result = asyncio.run(flow.async_step_reauth_confirm({"api_football_key": "still-bad"}))
    finally:
        _patch_validator(original)
    assert result["type"] == "form"
    assert result["step_id"] == "reauth_confirm"
    assert flow._errors.get("api_football_key") == "invalid_api_key"
    # Unchanged until a valid key is entered.
    assert entry.data["api_football_key"] == "old"


def test_options_change_api_key_updates_entry_data():
    flow = _config_flow_mod.SoccerLiveOptionsFlow()
    flow.config_entry = _MutableEntry({"provider": "api_football", "api_football_key": "old"})
    flow.hass = _FakeHass()
    original = _patch_validator(_mod_valid)
    try:
        result = asyncio.run(flow.async_step_init({
            "change_api_football_key": "fresh-key", "start_date": "", "end_date": "",
        }))
    finally:
        _patch_validator(original)
    assert result["type"] == "create_entry"
    assert flow.config_entry.data["api_football_key"] == "fresh-key"
    # The key is not leaked into the options blob.
    assert "change_api_football_key" not in result["data"]


def test_options_change_api_key_rejects_invalid():
    flow = _config_flow_mod.SoccerLiveOptionsFlow()
    flow.config_entry = _MutableEntry({"provider": "api_football", "api_football_key": "old"})
    flow.hass = _FakeHass()
    original = _patch_validator(_mod_invalid)
    try:
        result = asyncio.run(flow.async_step_init({
            "change_api_football_key": "bad", "start_date": "", "end_date": "",
        }))
    finally:
        _patch_validator(original)
    # Stays on the form with an error; the stored key is untouched.
    assert result["type"] == "form"
    assert flow.config_entry.data["api_football_key"] == "old"


def test_options_change_api_key_field_hidden_for_espn():
    assert "change_api_football_key" not in _options_schema(_config_flow_mod.PROVIDER_ESPN)
    assert "change_api_football_key" in _options_schema(_config_flow_mod.PROVIDER_API_FOOTBALL)
