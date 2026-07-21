import json
import logging
import os

_LOGGER = logging.getLogger(__name__)

DOMAIN = "soccer_live"


def _read_manifest_version():
    """Read the integration version from manifest.json once at import, so the
    sensors can publish it as `integration_version` without hardcoding it."""
    try:
        path = os.path.join(os.path.dirname(__file__), "manifest.json")
        with open(path, encoding="utf-8") as handle:
            return json.load(handle).get("version", "unknown")
    except Exception:  # pragma: no cover - defensive, never break setup
        return "unknown"


# Published to cards so they can recommend card types, warn on an old
# integration, and detect breaking attribute-shape changes.
INTEGRATION_VERSION = _read_manifest_version()
# Bump when the published attribute shape changes in a way a card must handle.
DATA_SCHEMA_VERSION = 1
CONF_COMPETITION_CODE = "competition_code"
CONF_PROVIDER = "provider"
CONF_API_FOOTBALL_KEY = "api_football_key"
CONF_INCLUDE_FRIENDLIES = "include_friendlies"
CONF_API_FOOTBALL_SEASON = "api_football_season"
CONF_LIVE_SCAN_INTERVAL = "live_scan_interval"

PROVIDER_ESPN = "espn"
PROVIDER_API_FOOTBALL = "api_football"

# What each data provider can supply. Lets the config flow and cards show only
# options that actually work for the selected provider, and is exposed as the
# `provider_capabilities` sensor attribute for introspection.
PROVIDER_CAPABILITIES = {
    PROVIDER_ESPN: (
        "fixtures", "scores", "standings", "top_scorers",
        "news", "brackets", "lineups", "statistics", "head_to_head",
    ),
    PROVIDER_API_FOOTBALL: (
        "fixtures", "scores", "standings", "top_scorers", "top_assists",
        "lineups", "statistics", "head_to_head",
        "predictions", "odds", "live_odds", "injuries", "xg", "club",
    ),
}


def provider_supports(provider, capability):
    """Whether the given provider supports a capability."""
    return capability in PROVIDER_CAPABILITIES.get(provider, ())

# Entity display names live in the translation files (translations/<lang>.json
# under entity.sensor.<sensor_type>.name), applied via each sensor's
# translation_key. That keeps the English translation the single source of
# truth — see tests/test_const.py, which asserts every sensor type has a name in
# every supported language.


# Card types (matching the Soccer Live Card `card_type` slugs) that work best
# with each sensor type. Published as `recommended_card_types` so the card's
# editor can suggest the right card for the selected entity.
RECOMMENDED_CARD_TYPES = {
    "team_match": ["team", "countdown", "match-center", "lineup", "timeline", "team-form"],
    "team_matches": ["matches", "ticker", "team-form"],
    "team_matches_mixed": ["team-competitions", "matches", "ticker", "team-form"],
    "match_day": ["matches", "ticker"],
    "all_matches_today": ["matches", "ticker"],
    "standings": ["standings", "mini-standings"],
    "top_scorers": ["scorers"],
    "bracket": ["bracket"],
    "news": ["news"],
}


def recommended_card_types(sensor_type):
    """Card `card_type` slugs that suit the given sensor type (may be empty)."""
    return list(RECOMMENDED_CARD_TYPES.get(sensor_type, ()))


# Lifecycle status published as the `sync_status` sensor attribute, so a card
# can show concrete text (e.g. "fetching matches for the first time") instead of
# an empty card that looks like a misconfiguration.
SYNC_STATUSES = (
    "initializing",          # no successful fetch yet (covers the first-load window)
    "fetching",              # reserved: a push coordinator could report an active
                             # fetch. A polled sensor can't (HA reads attributes
                             # only after async_update returns), so it uses
                             # "initializing" for the first load instead.
    "ready",                 # data has been fetched successfully
    "rate_limited",          # provider is rate/quota limiting requests
    "authentication_failed",  # provider rejected the API key (needs reauth)
    "provider_unavailable",  # provider unreachable and no data was ever fetched
)


def compute_sync_status(*, auth_failed, rate_limited, has_data, has_error, fetching=False):
    """Derive the lifecycle status from the sensor's flags.

    Precedence: an auth failure and a rate limit are surfaced first (they need
    user attention / explain missing data); otherwise, before the first
    successful fetch we distinguish a fetch in progress ("fetching") and the
    idle pre-fetch window ("initializing") from a provider that is unreachable
    ("provider_unavailable"). Once data exists the status is "ready"."""
    if auth_failed:
        return "authentication_failed"
    if rate_limited:
        return "rate_limited"
    if not has_data:
        if has_error:
            return "provider_unavailable"
        return "fetching" if fetching else "initializing"
    return "ready"
