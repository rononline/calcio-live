"""Provider-capability tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json

from custom_components.soccer_live.const import (
    DATA_SCHEMA_VERSION,
    ESPN_USER_AGENT,
    INTEGRATION_VERSION,
    PROVIDER_API_FOOTBALL,
    PROVIDER_CAPABILITIES,
    PROVIDER_ESPN,
    compute_sync_status,
    espn_request_headers,
    provider_supports,
    recommended_card_types,
)

# Every sensor type that gets a localised display name (via translation_key).
# The translation files are the single source of truth for the names.
REQUIRED_SENSOR_NAME_KEYS = {
    "team_match", "team_matches", "team_matches_mixed", "match_day",
    "standings", "top_scorers", "bracket", "all_matches_today", "news",
    "commentary",
}
# Languages the integration officially offers (kept in step with the cards).
SUPPORTED_LANGUAGES = ("en", "nl", "de", "fr", "es", "it", "pt")

# Leaf keys allowed to be missing from a given non-English language (none for
# now — every string is expected to be translated in every language).
ALLOWED_MISSING = {}

_COMPONENT = ROOT / "custom_components" / "soccer_live"


def _load_translation(lang):
    with open(_COMPONENT / "translations" / f"{lang}.json", encoding="utf-8") as handle:
        return json.load(handle)


def _leaf_keys(data, prefix=""):
    """Set of dotted paths to every string value (the translatable leaves)."""
    keys = set()
    if isinstance(data, dict):
        for key, value in data.items():
            keys |= _leaf_keys(value, f"{prefix}.{key}" if prefix else key)
    else:
        keys.add(prefix)
    return keys


def test_espn_capabilities():
    assert provider_supports(PROVIDER_ESPN, "news") is True
    assert provider_supports(PROVIDER_ESPN, "brackets") is True
    # ESPN has no predictions/odds/injuries.
    assert provider_supports(PROVIDER_ESPN, "predictions") is False
    assert provider_supports(PROVIDER_ESPN, "odds") is False


def test_api_football_capabilities():
    for cap in ("predictions", "odds", "live_odds", "injuries", "top_assists", "xg", "club"):
        assert provider_supports(PROVIDER_API_FOOTBALL, cap) is True
    # API-Football has no news; brackets are derived from fixture rounds.
    assert provider_supports(PROVIDER_API_FOOTBALL, "news") is False
    assert provider_supports(PROVIDER_API_FOOTBALL, "brackets") is True


def test_club_and_live_odds_are_api_football_only():
    assert provider_supports(PROVIDER_ESPN, "club") is False
    assert provider_supports(PROVIDER_ESPN, "live_odds") is False
    assert provider_supports(PROVIDER_API_FOOTBALL, "club") is True
    assert provider_supports(PROVIDER_API_FOOTBALL, "live_odds") is True


def test_both_providers_share_the_core_capabilities():
    core = {"fixtures", "scores", "standings", "top_scorers"}
    assert core <= set(PROVIDER_CAPABILITIES[PROVIDER_ESPN])
    assert core <= set(PROVIDER_CAPABILITIES[PROVIDER_API_FOOTBALL])


def test_unknown_provider_supports_nothing():
    assert provider_supports("nope", "fixtures") is False


def test_espn_request_headers_include_user_agent():
    headers = espn_request_headers()
    assert headers["Accept-Language"] == "en"
    assert headers["User-Agent"] == ESPN_USER_AGENT
    headers["User-Agent"] = "mutated"
    assert espn_request_headers()["User-Agent"] == ESPN_USER_AGENT


def test_compute_sync_status_first_load():
    # No data yet: idle vs actively fetching.
    assert compute_sync_status(auth_failed=False, rate_limited=False,
                               has_data=False, has_error=False) == "initializing"
    assert compute_sync_status(auth_failed=False, rate_limited=False,
                               has_data=False, has_error=False, fetching=True) == "fetching"
    # Never fetched and erroring -> the provider is unreachable.
    assert compute_sync_status(auth_failed=False, rate_limited=False,
                               has_data=False, has_error=True) == "provider_unavailable"


def test_compute_sync_status_ready_and_priorities():
    # Data present -> ready.
    assert compute_sync_status(auth_failed=False, rate_limited=False,
                               has_data=True, has_error=False) == "ready"
    # A transient error with existing data still reads ready (card shows cached data).
    assert compute_sync_status(auth_failed=False, rate_limited=False,
                               has_data=True, has_error=True) == "ready"
    # Auth failure and rate limiting take precedence over everything else.
    assert compute_sync_status(auth_failed=True, rate_limited=True,
                               has_data=True, has_error=False) == "authentication_failed"
    assert compute_sync_status(auth_failed=False, rate_limited=True,
                               has_data=True, has_error=False) == "rate_limited"
    # Rate limit is reported even before any data arrives.
    assert compute_sync_status(auth_failed=False, rate_limited=True,
                               has_data=False, has_error=True) == "rate_limited"


def test_recommended_card_types():
    assert recommended_card_types("team_match")[:3] == ["team", "countdown", "match-center"]
    assert recommended_card_types("standings") == ["standings", "mini-standings", "race"]
    assert recommended_card_types("news") == ["news"]
    # Unknown / calendar-like types have no recommendation.
    assert recommended_card_types("unknown") == []
    # Returns a fresh list each call (callers can mutate without side effects).
    a = recommended_card_types("team_match")
    a.append("x")
    assert "x" not in recommended_card_types("team_match")


def test_integration_version_matches_manifest():
    path = ROOT / "custom_components" / "soccer_live" / "manifest.json"
    with open(path, encoding="utf-8") as handle:
        manifest_version = json.load(handle)["version"]
    assert INTEGRATION_VERSION == manifest_version
    assert isinstance(DATA_SCHEMA_VERSION, int) and DATA_SCHEMA_VERSION >= 1


def test_entity_names_localised_in_every_supported_language():
    # The translation files are the single source of truth for entity names.
    # Each supported language must provide a non-empty name for every sensor
    # type and the calendar, so no language silently falls back to English.
    for lang in SUPPORTED_LANGUAGES:
        entity = _load_translation(lang).get("entity", {})
        sensors = entity.get("sensor", {})
        for key in REQUIRED_SENSOR_NAME_KEYS:
            assert sensors.get(key, {}).get("name"), f"{lang}: missing sensor name for {key}"
        assert entity.get("calendar", {}).get("match_calendar", {}).get("name"), \
            f"{lang}: missing calendar name"


def test_entity_name_keys_are_consistent_across_languages():
    # Every language exposes exactly the same set of sensor-name keys.
    english = set(_load_translation("en")["entity"]["sensor"])
    assert REQUIRED_SENSOR_NAME_KEYS <= english
    for lang in SUPPORTED_LANGUAGES:
        assert set(_load_translation(lang)["entity"]["sensor"]) == english, lang


def test_strings_json_matches_english_translation():
    # Home Assistant treats strings.json as the canonical English source; keep it
    # in lockstep with translations/en.json so the two can't drift.
    with open(_COMPONENT / "strings.json", encoding="utf-8") as handle:
        strings = json.load(handle)
    assert strings == _load_translation("en")


def test_all_languages_have_full_key_parity():
    # No language may silently lag behind English on any string (config-flow
    # steps, errors, aborts, options and entity names all included).
    english = _leaf_keys(_load_translation("en"))
    for lang in SUPPORTED_LANGUAGES:
        keys = _leaf_keys(_load_translation(lang))
        missing = english - keys - set(ALLOWED_MISSING.get(lang, ()))
        extra = keys - english
        assert not missing, f"{lang} missing keys: {sorted(missing)}"
        assert not extra, f"{lang} has unexpected keys: {sorted(extra)}"
