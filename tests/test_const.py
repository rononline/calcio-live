"""Provider-capability tests."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from custom_components.soccer_live.const import (  # noqa: E402
    PROVIDER_API_FOOTBALL,
    PROVIDER_CAPABILITIES,
    PROVIDER_ESPN,
    friendly_sensor_name,
    provider_supports,
)


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
