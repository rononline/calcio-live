"""Provider-capability tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import json  # noqa: E402

from custom_components.soccer_live.const import (  # noqa: E402
    DATA_SCHEMA_VERSION,
    INTEGRATION_VERSION,
    PROVIDER_API_FOOTBALL,
    PROVIDER_CAPABILITIES,
    PROVIDER_ESPN,
    SENSOR_TYPE_NAMES,
    compute_sync_status,
    friendly_sensor_name,
    provider_supports,
    recommended_card_types,
)


def _load_translation(lang):
    path = ROOT / "custom_components" / "soccer_live" / "translations" / f"{lang}.json"
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def test_espn_capabilities():
    assert provider_supports(PROVIDER_ESPN, "news") is True
    assert provider_supports(PROVIDER_ESPN, "brackets") is True
    # ESPN has no predictions/odds/injuries.
    assert provider_supports(PROVIDER_ESPN, "predictions") is False
    assert provider_supports(PROVIDER_ESPN, "odds") is False


def test_api_football_capabilities():
    for cap in ("predictions", "odds", "live_odds", "injuries", "top_assists", "xg", "club"):
        assert provider_supports(PROVIDER_API_FOOTBALL, cap) is True
    # API-Football has no news/brackets in Soccer Live.
    assert provider_supports(PROVIDER_API_FOOTBALL, "news") is False
    assert provider_supports(PROVIDER_API_FOOTBALL, "brackets") is False


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


def test_friendly_sensor_names():
    # The user-facing names for the three sensors a team config creates.
    assert friendly_sensor_name("team_match") == "Next match"
    assert friendly_sensor_name("team_matches") == "All matches"
    assert friendly_sensor_name("team_matches_mixed") == "All competitions"
    # Competition-scoped sensors.
    assert friendly_sensor_name("match_day") == "All matches"
    assert friendly_sensor_name("standings") == "Standings"
    assert friendly_sensor_name("all_matches_today") == "All matches today"


def test_friendly_sensor_name_falls_back_to_title_case():
    # Unknown types get a readable fallback rather than a raw slug.
    assert friendly_sensor_name("some_new_type") == "Some New Type"
    assert friendly_sensor_name(None) == "Soccer Live"


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
    assert recommended_card_types("standings") == ["standings", "mini-standings"]
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


def test_entity_name_translations_present_and_consistent():
    # Every sensor type has a localised name via translation_key; English must
    # match the canonical friendly_sensor_name, and Dutch must cover the same
    # keys so NL users see "Volgende wedstrijd" etc. (not the English fallback).
    en = _load_translation("en")["entity"]["sensor"]
    nl = _load_translation("nl")["entity"]["sensor"]
    for sensor_type, english in SENSOR_TYPE_NAMES.items():
        assert en[sensor_type]["name"] == english == friendly_sensor_name(sensor_type)
        assert nl[sensor_type]["name"], f"nl missing name for {sensor_type}"
    # The calendar entity is localised too.
    assert _load_translation("en")["entity"]["calendar"]["match_calendar"]["name"] == "Match calendar"
    assert _load_translation("nl")["entity"]["calendar"]["match_calendar"]["name"] == "Wedstrijdkalender"
