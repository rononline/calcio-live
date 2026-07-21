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
        "predictions", "odds", "live_odds", "injuries", "xg", "club",
    ),
}


def provider_supports(provider, capability):
    """Whether the given provider supports a capability."""
    return capability in PROVIDER_CAPABILITIES.get(provider, ())


# Short, human-readable entity names per sensor type. Used with
# `has_entity_name`, so the device (team or competition) supplies the context
# and these can stay concise. The verbose entity_id (e.g.
# `sensor.soccerlive_next_eredivisie_feyenoord`) is preserved separately.
SENSOR_TYPE_NAMES = {
    "team_match": "Next match",
    "team_matches": "All matches",
    "team_matches_mixed": "All competitions",
    "match_day": "All matches",
    "standings": "Standings",
    "top_scorers": "Top scorers",
    "bracket": "Knockout bracket",
    "all_matches_today": "All matches today",
    "news": "News",
    "commentary": "Live commentary",
}


def friendly_sensor_name(sensor_type):
    """Human-readable entity name for a sensor type, falling back to a
    title-cased version of the raw type for anything not in the table."""
    if sensor_type in SENSOR_TYPE_NAMES:
        return SENSOR_TYPE_NAMES[sensor_type]
    return (sensor_type or "Soccer Live").replace("_", " ").title()


# Lifecycle status published as the `sync_status` sensor attribute, so a card
# can show concrete text (e.g. "fetching matches for the first time") instead of
# an empty card that looks like a misconfiguration.
SYNC_STATUSES = (
    "initializing",          # entity created, no fetch has run yet
    "fetching",              # a fetch is in progress and there is no data yet
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
