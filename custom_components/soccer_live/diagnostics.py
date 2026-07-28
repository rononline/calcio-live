from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a Soccer Live config entry."""
    entity_reg = er.async_get(hass)
    entities = er.async_entries_for_config_entry(entity_reg, entry.entry_id)

    sensors = []
    for entity_entry in entities:
        state = hass.states.get(entity_entry.entity_id)
        if not state:
            sensors.append({"entity_id": entity_entry.entity_id, "state": "not_loaded"})
            continue

        attrs = state.attributes
        matches = attrs.get("matches", [])
        previous = attrs.get("previous_matches", [])

        # Collect non-sensitive diagnostic info — omit large match payloads
        sensor_info: dict[str, Any] = {
            "entity_id": entity_entry.entity_id,
            "state": state.state,
            "provider": attrs.get("provider", "N/A"),
            "competition_code": attrs.get("competition_code", "N/A"),
            "sensor_type": attrs.get("sensor_type", "N/A"),
            "request_count": attrs.get("request_count", "N/A"),
            "last_request_time": attrs.get("last_request_time", "N/A"),
            "last_successful_update": attrs.get("last_successful_update", "N/A"),
            "api_status": attrs.get("api_status", "N/A"),
            "last_error": attrs.get("last_error"),
            "api_football_quota": attrs.get("api_football_quota", {}),
            "match_count": len(matches),
            "previous_match_count": len(previous),
            "has_live_match": any(m.get("state") == "in" for m in matches),
        }

        # Cache age if available
        cache_time = None
        for entry_cache in (SoccerLiveSensor._cache or {}).values():
            if isinstance(entry_cache, dict):
                t = entry_cache.get("time")
                if t and isinstance(t, datetime):
                    now = datetime.now(t.tzinfo or timezone.utc)
                    comparable = t if t.tzinfo else t.replace(tzinfo=timezone.utc)
                    age = (now - comparable).total_seconds()
                    if cache_time is None or age < cache_time:
                        cache_time = age
        if cache_time is not None:
            sensor_info["cache_age_seconds"] = round(cache_time)

        sensors.append(sensor_info)

    api_football = {}
    if SoccerLiveSensor is not None:
        pause_until = getattr(SoccerLiveSensor, "_af_enrich_pause_until", None)
        stats = dict(getattr(SoccerLiveSensor, "_api_football_stats", {}) or {})
        live_odds_pause = getattr(SoccerLiveSensor, "_live_odds_pause_until", None)
        api_football = {
            "endpoint_stats": stats,
            "rate_limited_at": getattr(SoccerLiveSensor, "_api_football_rate_limited_at", None),
            "enrichment_paused_until": pause_until.isoformat() if pause_until else None,
            "endpoint_cache_entries": len(getattr(SoccerLiveSensor, "_api_football_endpoint_cache", {}) or {}),
            "live_odds_calls": (stats.get("odds/live") or {}).get("calls", 0),
            "live_odds_last_status": (stats.get("odds/live") or {}).get("last_status"),
            "live_odds_paused_until": live_odds_pause.isoformat() if live_odds_pause else None,
        }

    return {
        "coordinator": {
            "is_fetching": bool(
                hass.data.get("soccer_live", {})
                .get(entry.entry_id, {})
                .get("coordinator")
                and hass.data["soccer_live"][entry.entry_id]["coordinator"].is_fetching
            ),
            "registered_entities": len(
                getattr(
                    hass.data.get("soccer_live", {})
                    .get(entry.entry_id, {})
                    .get("coordinator"),
                    "_entities",
                    (),
                )
            ),
        },
        "api_football": api_football,
        "config_entry": {
            "provider": entry.data.get("provider", "N/A"),
            "has_api_football_key": bool(entry.data.get("api_football_key")),
            "competition_code": entry.data.get("competition_code", "N/A"),
            "team_name": entry.data.get("team_name", "N/A"),
            "team_id": entry.data.get("team_id", "N/A"),
            "sensor_types": entry.data.get("sensor_types", []),
            "scan_interval": entry.options.get("scan_interval", 3),
            "recent_match_hours": entry.options.get("recent_match_hours", 24),
            "notify_service": bool(entry.options.get("notify_service")),
        },
        "sensors": sensors,
    }


# Import here to avoid circular at module level
try:
    from .sensor import SoccerLiveSensor
except ImportError:
    SoccerLiveSensor = None  # type: ignore[assignment,misc]
