import json
from enum import Enum

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

try:
    from homeassistant.core import SupportsResponse
except ImportError:  # pragma: no cover - lightweight standalone test stubs
    class SupportsResponse(Enum):
        OPTIONAL = "optional"
        ONLY = "only"

from .const import DOMAIN
from .coordinator import SoccerLiveEntryCoordinator
from .simulator import EVENT_TYPES, simulated_event

PLATFORMS = ["sensor", "binary_sensor", "calendar", "button", "event"]


def _coordinators(hass, requested=None):
    """Return selected entry coordinators, or all when no ID was supplied."""
    runtime = hass.data.get(DOMAIN, {})
    if requested:
        coordinator = runtime.get(str(requested), {}).get("coordinator")
        return [coordinator] if coordinator else []
    return [
        value.get("coordinator")
        for value in runtime.values()
        if isinstance(value, dict) and value.get("coordinator")
    ]


def _register_services(hass: HomeAssistant) -> None:
    """Register entry-wide utility services once."""
    if hass.services.has_service(DOMAIN, "simulate_match_event"):
        return
    import voluptuous as vol

    async def async_simulate_match_event(call):
        event_type, payload = simulated_event(call.data["event_type"], call.data)
        hass.bus.async_fire(event_type, payload)

    async def async_refresh(call):
        count = 0
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            count += await coordinator.async_refresh()
        return {"entities": count}

    async def async_clear_archive(call):
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            await coordinator.async_replace_archive([])

    async def async_rebuild_archive(call):
        total = 0
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            total += await coordinator.async_rebuild_archive()
        return {"matches": total}

    async def async_import_archive(call):
        from .archive import validate_archive

        raw = call.data["archive"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else raw
        except (ValueError, TypeError, json.JSONDecodeError) as err:
            raise vol.Invalid(str(err)) from err
        selected = _coordinators(hass, call.data.get("config_entry_id"))
        archives = payload.get("archives") if isinstance(payload, dict) else None
        total = 0
        for coordinator in selected:
            candidate = payload
            if isinstance(archives, dict):
                candidate = archives.get(coordinator.entry_id)
                if candidate is None and len(archives) == 1:
                    # A restored config entry receives a new ID. A backup with
                    # one archive is therefore unambiguous and remains portable.
                    candidate = next(iter(archives.values()))
                if candidate is None:
                    raise vol.Invalid(
                        f"Archive backup has no data for config entry {coordinator.entry_id}"
                    )
            try:
                matches = validate_archive(candidate)
            except (ValueError, TypeError, json.JSONDecodeError) as err:
                raise vol.Invalid(str(err)) from err
            await coordinator.async_replace_archive(matches)
            total += len(matches)
        return {"matches": total}

    async def async_export_archive(call):
        from .archive import export_archive

        selected = _coordinators(hass, call.data.get("config_entry_id"))
        return {
            "archives": {
                coordinator.entry_id: json.loads(export_archive(coordinator.archive()))
                for coordinator in selected
            }
        }

    async def async_sync_archive(call):
        total = 0
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            url = call.data.get("url")
            if not url:
                entry = hass.config_entries.async_get_entry(coordinator.entry_id)
                url = (entry.options if entry else {}).get("archive_sync_url")
            if not url:
                raise vol.Invalid("No archive sync URL configured")
            total += await coordinator.async_sync_archive_url(url)
        return {"matches": total}

    async def async_play_match_replay(call):
        total = 0
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            total += await coordinator.async_play_replay(
                speed=call.data.get("speed", 20),
                demo=call.data.get("demo", False),
            )
        return {"events": total}

    async def async_clear_match_replay(call):
        for coordinator in _coordinators(hass, call.data.get("config_entry_id")):
            await coordinator.async_clear_replay()

    async def async_export_match_replay(call):
        selected = _coordinators(hass, call.data.get("config_entry_id"))
        return {
            "replays": {
                coordinator.entry_id: {
                    "version": 1,
                    "snapshots": coordinator.replay(),
                }
                for coordinator in selected
            }
        }

    entry_schema = {vol.Optional("config_entry_id"): str}
    hass.services.async_register(
        DOMAIN,
        "simulate_match_event",
        async_simulate_match_event,
        schema=vol.Schema({
            vol.Required("event_type"): vol.In(EVENT_TYPES),
            vol.Optional("event_id"): str,
            vol.Optional("team_id"): vol.Any(str, int),
            vol.Optional("home_team"): str,
            vol.Optional("away_team"): str,
            vol.Optional("home_score", default=0): int,
            vol.Optional("away_score", default=0): int,
            vol.Optional("player"): str,
            vol.Optional("minute"): vol.Any(str, int),
            vol.Optional("team"): str,
            vol.Optional("home_players"): list,
            vol.Optional("away_players"): list,
        }),
    )
    hass.services.async_register(
        DOMAIN,
        "refresh",
        async_refresh,
        schema=vol.Schema(entry_schema),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "clear_match_archive",
        async_clear_archive,
        schema=vol.Schema(entry_schema),
    )
    hass.services.async_register(
        DOMAIN,
        "rebuild_match_archive",
        async_rebuild_archive,
        schema=vol.Schema(entry_schema),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "import_match_archive",
        async_import_archive,
        schema=vol.Schema({
            **entry_schema,
            vol.Required("archive"): str,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "export_match_archive",
        async_export_archive,
        schema=vol.Schema(entry_schema),
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        "sync_match_archive",
        async_sync_archive,
        schema=vol.Schema({
            **entry_schema,
            vol.Optional("url"): str,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "play_match_replay",
        async_play_match_replay,
        schema=vol.Schema({
            **entry_schema,
            vol.Optional("speed", default=20): vol.Coerce(float),
            vol.Optional("demo", default=False): bool,
        }),
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(
        DOMAIN,
        "clear_match_replay",
        async_clear_match_replay,
        schema=vol.Schema(entry_schema),
    )
    hass.services.async_register(
        DOMAIN,
        "export_match_replay",
        async_export_match_replay,
        schema=vol.Schema(entry_schema),
        supports_response=SupportsResponse.ONLY,
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    coordinator = SoccerLiveEntryCoordinator(hass, entry.entry_id)
    await coordinator.async_initialize()
    hass.data[DOMAIN].setdefault(entry.entry_id, {})["coordinator"] = coordinator
    _register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    archive_url = str(entry.options.get("archive_sync_url") or "").strip()
    if archive_url:
        from datetime import timedelta
        from homeassistant.helpers.event import async_track_time_interval

        interval = max(1, int(entry.options.get("archive_sync_interval", 24)))

        async def _sync_archive(_now=None):
            try:
                await coordinator.async_sync_archive_url(archive_url)
            except Exception:
                # Status/error are already published by the coordinator; a
                # temporary remote outage must never unload Soccer Live.
                pass

        entry.async_on_unload(
            async_track_time_interval(hass, _sync_archive, timedelta(hours=interval))
        )
        hass.async_create_task(_sync_archive())
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    return True

async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the integration when options are changed (scan_interval, recent_match_hours)."""
    await hass.config_entries.async_reload(entry.entry_id)

async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    coordinator = (
        hass.data.get(DOMAIN, {})
        .get(entry.entry_id, {})
        .get("coordinator")
    )
    if coordinator:
        await coordinator.async_shutdown()
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        if not hass.data.get(DOMAIN):
            for service in (
                "simulate_match_event",
                "refresh",
                "clear_match_archive",
                "rebuild_match_archive",
                "import_match_archive",
                "export_match_archive",
                "sync_match_archive",
                "play_match_replay",
                "clear_match_replay",
                "export_match_replay",
            ):
                hass.services.async_remove(DOMAIN, service)
            hass.data.pop(DOMAIN, None)
    return unload_ok
