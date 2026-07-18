import logging
_LOGGER = logging.getLogger(__name__)

DOMAIN = "soccer_live"
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
        "predictions", "odds", "injuries", "xg", "club",
    ),
}


def provider_supports(provider, capability):
    """Whether the given provider supports a capability."""
    return capability in PROVIDER_CAPABILITIES.get(provider, ())
