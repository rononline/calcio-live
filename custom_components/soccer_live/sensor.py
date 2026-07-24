import asyncio
import json
import aiohttp
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.storage import Store
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
import random
import re
import unicodedata
from urllib.parse import urlencode
from .const import (
    CONF_API_FOOTBALL_KEY,
    CONF_API_FOOTBALL_SEASON,
    CONF_INCLUDE_FRIENDLIES,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_PROVIDER,
    DOMAIN,
    DATA_SCHEMA_VERSION,
    INTEGRATION_VERSION,
    PROVIDER_API_FOOTBALL,
    PROVIDER_CAPABILITIES,
    PROVIDER_ESPN,
    compute_sync_status,
    recommended_card_types,
)

_LIVE_POLL_TYPES = {"team_match", "team_matches", "team_matches_mixed", "match_day", "all_matches_today"}

_LOGGER = logging.getLogger(__name__)


def safe_entity_object_id(value):
    """Return a stable Home Assistant-safe object ID."""
    normalized = unicodedata.normalize("NFKD", str(value or ""))
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    slug = re.sub(r"[^a-z0-9_]+", "_", ascii_value)
    return re.sub(r"_+", "_", slug).strip("_") or "soccer_live"

_DATE_RANGE_SENSOR_TYPES = {"match_day", "team_match", "team_matches"}

# Competitions with a knockout bracket phase
KNOCKOUT_LEAGUES = {
    "uefa.champions",
    "uefa.europa",
    "uefa.europa.conf",
    "uefa.euro",
    "uefa.nations",
    "uefa.wchampions",
    "fifa.world",
    "fifa.wwc",
    "fifa.cwc",
    "concacaf.champions",
    "concacaf.gold",
    "concacaf.nations.league",
    "ita.coppa_italia",
    "eng.fa",
    "eng.league_cup",
    "esp.copa_del_rey",
    "ger.dfb_pokal",
    "fra.coupe_de_france",
}

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback):
    try:
        competition_name = entry.data.get("name")
        competition_code = entry.data.get("competition_code")
        team_name = entry.data.get("team_name")
        selection = entry.data.get("selection")
        team_id = entry.data.get("team_id")
        provider = entry.data.get(CONF_PROVIDER, PROVIDER_ESPN)
        api_football_key = entry.data.get(CONF_API_FOOTBALL_KEY, "")
        include_friendlies = entry.options.get(
            CONF_INCLUDE_FRIENDLIES,
            entry.data.get(CONF_INCLUDE_FRIENDLIES, True),
        )
        api_football_season = entry.options.get(
            CONF_API_FOOTBALL_SEASON,
            entry.data.get(CONF_API_FOOTBALL_SEASON),
        )

        # Season dates are resolved dynamically via _get_calendar_data each update.
        # Use a wide rolling fallback (±1 year) so process_match_data never
        # discards valid matches on first run before the calendar is available.
        _today = datetime.now()
        _default_start = (_today - timedelta(days=365)).strftime("%Y-%m-%d")
        _default_end = (_today + timedelta(days=365)).strftime("%Y-%m-%d")
        start_date = entry.options.get("start_date", entry.data.get("start_date", _default_start))
        end_date = entry.options.get("end_date", entry.data.get("end_date", _default_end))

        base_scan_interval = timedelta(minutes=entry.options.get("scan_interval", 3))
        live_scan_interval = entry.options.get(
            CONF_LIVE_SCAN_INTERVAL,
            entry.data.get(CONF_LIVE_SCAN_INTERVAL, 60),
        )
        recent_match_hours = entry.options.get("recent_match_hours", 24)
        enable_summary_enrichment = entry.options.get("enable_summary_enrichment", True)
        enable_club_data = entry.options.get("enable_club_data", True)
        enable_live_odds = entry.options.get("enable_live_odds", False)
        max_matches = entry.options.get("max_matches", 0)
        sensors = []

        if DOMAIN not in hass.data:
            hass.data[DOMAIN] = {}
    
        if selection == "News":
            comp_norm = competition_code.replace(" ", "_").replace(".", "_").lower()
            sensors += [
                SoccerLiveSensor(
                    hass, f"soccerlive_news_{comp_norm}", competition_code, "news",
                    base_scan_interval + timedelta(minutes=10) + timedelta(seconds=random.randint(0, 30)),
                    config_entry_id=entry.entry_id,
                    start_date=start_date, end_date=end_date, team_id=team_id, recent_match_hours=recent_match_hours,
                    enable_summary_enrichment=enable_summary_enrichment,
                    enable_club_data=enable_club_data,
                    enable_live_odds=enable_live_odds,
                    max_matches=max_matches, provider=provider, api_football_key=api_football_key,
                    include_friendlies=include_friendlies, api_football_season=api_football_season,
                    live_scan_interval=live_scan_interval
                )
            ]
            async_add_entities(sensors, True)
            return

        if team_name:
            team_name_normalized = team_name.replace(" ", "_").replace(".", "_").lower()
            competition_name = (competition_code or "manual").replace(" ", "_").replace(".", "_").lower()

            # ESPN needs a competition code; API-Football can fetch team fixtures by team id.
            if provider == PROVIDER_API_FOOTBALL or (competition_code and competition_code not in ("N/A", "")):
                sensors += [
                    SoccerLiveSensor(
                        hass, f"soccerlive_next_{competition_name}_{team_name_normalized}", competition_code, "team_match",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                        config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id, recent_match_hours=recent_match_hours,
                        enable_summary_enrichment=enable_summary_enrichment,
                        enable_club_data=enable_club_data,
                        enable_live_odds=enable_live_odds,
                        max_matches=max_matches, provider=provider, api_football_key=api_football_key,
                        include_friendlies=include_friendlies, api_football_season=api_football_season,
                        live_scan_interval=live_scan_interval
                    ),
                    SoccerLiveSensor(
                        hass, f"soccerlive_all_{competition_name}_{team_name_normalized}", competition_code, "team_matches",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                        config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id, recent_match_hours=recent_match_hours,
                        enable_summary_enrichment=enable_summary_enrichment,
                        enable_club_data=enable_club_data,
                        enable_live_odds=enable_live_odds,
                        max_matches=max_matches, provider=provider, api_football_key=api_football_key,
                        include_friendlies=include_friendlies, api_football_season=api_football_season,
                        live_scan_interval=live_scan_interval
                    ),
                ]
            sensors += [
                SoccerLiveSensor(
                    hass, f"soccerlive_all_mixed_{team_name_normalized}", competition_code, "team_matches_mixed",
                    base_scan_interval + timedelta(seconds=random.randint(0, 30)), team_name=team_name,
                    config_entry_id=entry.entry_id, start_date=start_date, end_date=end_date, team_id=team_id, recent_match_hours=recent_match_hours,
                    enable_summary_enrichment=enable_summary_enrichment,
                    enable_club_data=enable_club_data,
                    enable_live_odds=enable_live_odds,
                    max_matches=max_matches, provider=provider, api_football_key=api_football_key,
                    include_friendlies=include_friendlies, api_football_season=api_football_season,
                    live_scan_interval=live_scan_interval
                )
            ]
        elif competition_code:
            if competition_code == "99999":  # Dummy code for the "all matches today" sensor
                sensors += [
                    SoccerLiveSensor(
                        hass, "soccerlive_all_today", competition_code, "all_matches_today",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id, recent_match_hours=recent_match_hours,
                        enable_summary_enrichment=enable_summary_enrichment,
                        enable_club_data=enable_club_data,
                        enable_live_odds=enable_live_odds,
                        max_matches=max_matches, provider=provider, api_football_key=api_football_key,
                        include_friendlies=include_friendlies, api_football_season=api_football_season,
                        live_scan_interval=live_scan_interval
                    )
                ]
            else:
                competition_name = competition_name.replace(" ", "_").replace(".", "_").lower()

                sensors += [
                    SoccerLiveSensor(
                        hass, f"soccerlive_standings_{competition_name}", competition_code, "standings",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id, max_matches=max_matches,
                        provider=provider, api_football_key=api_football_key, include_friendlies=include_friendlies,
                        api_football_season=api_football_season, live_scan_interval=live_scan_interval
                    ),
                    SoccerLiveSensor(
                        hass, f"soccerlive_all_{competition_name}", competition_code, "match_day",
                        base_scan_interval + timedelta(seconds=random.randint(0, 30)), config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id, max_matches=max_matches,
                        provider=provider, api_football_key=api_football_key, include_friendlies=include_friendlies,
                        api_football_season=api_football_season, live_scan_interval=live_scan_interval
                    )
                ]
                # Top scorers sensor
                sensors.append(
                    SoccerLiveSensor(
                        hass, f"soccerlive_scorers_{competition_name}", competition_code, "top_scorers",
                        base_scan_interval + timedelta(minutes=5) + timedelta(seconds=random.randint(0, 30)),
                        config_entry_id=entry.entry_id,
                        start_date=start_date, end_date=end_date, team_id=team_id,
                        provider=provider, api_football_key=api_football_key, include_friendlies=include_friendlies,
                        api_football_season=api_football_season, live_scan_interval=live_scan_interval
                    )
                )
                # Auto-add bracket sensor for knockout competitions
                if competition_code in KNOCKOUT_LEAGUES:
                    sensors.append(
                        SoccerLiveSensor(
                            hass, f"soccerlive_bracket_{competition_name}", competition_code, "bracket",
                            base_scan_interval + timedelta(minutes=10) + timedelta(seconds=random.randint(0, 30)),
                            config_entry_id=entry.entry_id,
                            start_date=start_date, end_date=end_date, team_id=team_id, max_matches=max_matches,
                            provider=provider, api_football_key=api_football_key, include_friendlies=include_friendlies,
                            api_football_season=api_football_season, live_scan_interval=live_scan_interval
                        )
                    )

        async_add_entities(sensors, True)

    except Exception as e:
        _LOGGER.error(f"Error during sensor setup: {e}")
        raise


class SoccerLiveSensor(Entity):
    # Keep large / high-churn attributes out of the recorder history so the HA
    # database doesn't balloon. The state itself (the score summary) and the
    # small scalar attributes are still recorded.
    _unrecorded_attributes = frozenset({
        "matches", "previous_matches", "upcoming_matches", "next_match", "current_match",
        "schedule_live_matches", "schedule_upcoming_matches", "schedule_recent_matches",
        "standings_groups", "scorers", "assists", "articles", "rounds",
        "head_to_head", "league_info", "club", "club_changes", "card_defaults",
        "last_event", "last_goal_event", "last_card_event",
        "last_match_started_event", "last_match_finished_event",
    })

    _cache = {}
    _fetch_locks = {}
    _calendar_cache = {}
    _calendar_locks = {}
    _calendar_error_logs = {}
    _api_football_endpoint_cache = {}
    _api_football_endpoint_locks = {}
    # API-usage diagnostics (shared across sensors): per-endpoint calls,
    # cache hits, last success and last HTTP status, plus a rate-limit marker.
    _api_football_stats = {}
    _api_football_rate_limited_at = None
    # Rate-limit backoff: after an HTTP 429, pause new enrichment requests until
    # this time, doubling the wait on each consecutive 429 (reset on success).
    _af_enrich_pause_until = None
    _af_backoff = 0
    # Config entries for which an API-Football reauth flow has been started, so
    # a persistent bad key doesn't spawn a new flow on every poll.
    _af_reauth_entries = set()

    def __init__(self, hass, name, code, sensor_type=None, scan_interval=timedelta(minutes=5),
                 team_name=None, config_entry_id=None, start_date=None, end_date=None, team_id=None,
                 recent_match_hours=24, enable_summary_enrichment=True, max_matches=0,
                 provider=PROVIDER_ESPN, api_football_key="", include_friendlies=True,
                 api_football_season=None, live_scan_interval=60, enable_club_data=True,
                 enable_live_odds=False):
        self.hass = hass
        self._name = name
        # Localised display name via the sensor type's translation_key (so Dutch
        # users see "Volgende wedstrijd" etc.); the device supplies the team/
        # competition context. Pin the verbose entity_id to the slug so it stays
        # stable (and doesn't collapse to e.g. sensor.next_match) now that the
        # display name is human-readable.
        self._attr_has_entity_name = True
        self._attr_translation_key = sensor_type
        self.entity_id = f"sensor.{safe_entity_object_id(name)}"
        self._code = code
        self._team_id = team_id
        self._sensor_type = sensor_type
        self._scan_interval = scan_interval
        self._state = None
        self._attributes = {}
        self._config_entry_id = config_entry_id
        self._team_name = team_name
        self._recent_match_hours = recent_match_hours
        self._enable_summary_enrichment = enable_summary_enrichment
        self._enable_club_data = enable_club_data
        self._enable_live_odds = enable_live_odds
        self._max_matches = max_matches  # 0 = unlimited
        try:
            self._live_scan_interval = max(15, int(live_scan_interval or 60))
        except (TypeError, ValueError):
            self._live_scan_interval = 60
        self._provider = provider or PROVIDER_ESPN
        self._api_football_key = api_football_key or ""
        self._include_friendlies = include_friendlies
        try:
            self._api_football_season = int(api_football_season) if api_football_season else None
        except (TypeError, ValueError):
            self._api_football_season = None
        self._api_football_quota = {}

        # Parse date strings into datetime objects; empty/missing = no filter
        try:
            self._start_date = datetime.strptime(start_date, "%Y-%m-%d") if start_date else None
        except ValueError:
            _LOGGER.warning("Invalid start_date %r for %s — date filter disabled", start_date, name)
            self._start_date = None
        try:
            self._end_date = datetime.strptime(end_date, "%Y-%m-%d") if end_date else None
        except ValueError:
            _LOGGER.warning("Invalid end_date %r for %s — date filter disabled", end_date, name)
            self._end_date = None

        # Dynamic season dates fetched from ESPN each update.
        # When available, these override the static fallbacks in URL building
        # and match filtering so the integration follows the current season automatically.
        self._dyn_start_date = None
        self._dyn_end_date = None
        
        self._request_count = 0
        self._last_request_time = None
        self._last_successful_update = None
        self._last_error = None
        
        self._previous_scores = {}
        self._previous_match_details = {}
        self._previous_match_states = {}
        self._previous_match_phases = {}
        self._dispatched_goal_details = {}
        self._match_finished_dispatched = set()
        self._match_finished_list = []
        self._store = None
        self._summary_cache = {}
        self._scorers_unavailable = False
        # Set when API-Football rejects the key (HTTP 401/403 or an errors.token
        # body); surfaces a clear status and triggers a reauth flow.
        self._auth_failed = False

        # Events collected during executor-thread processing, fired on event loop
        self._pending_events: list = []
        self._save_store_needed: bool = False

        # Handle for the extra live-mode refresh timer (cancelled on removal)
        self._live_unsub = None

        self.base_url = "https://site.web.api.espn.com/apis/v2/sports/soccer"
        self.base_url_2 = "https://site.api.espn.com/apis/site/v2/sports/soccer"
        self.base_url_3 = "https://site.web.api.espn.com/apis/site/v2/sports/soccer"
        self.api_football_base_url = "https://v3.football.api-sports.io"

    async def async_will_remove_from_hass(self):
        if self._live_unsub:
            self._live_unsub()
            self._live_unsub = None

    def _is_live(self):
        """Return True if any tracked match is currently in progress."""
        if self._sensor_type not in _LIVE_POLL_TYPES:
            return False
        matches = self._attributes.get("matches", []) or []
        return any(m.get("state") in ("in", "live") for m in matches)

    def _main_cache_ttl(self):
        """Return cache TTL for the main provider request."""
        if self._is_live():
            return min(60, self._live_scan_interval)
        return 60

    def _schedule_live_refresh(self):
        """Schedule an extra refresh while a match is live, replacing any pending timer."""
        if self._live_unsub:
            self._live_unsub()
            self._live_unsub = None
        if self._is_live():
            self._live_unsub = async_call_later(
                self.hass, self._live_scan_interval,
                lambda _: self.async_schedule_update_ha_state(force_refresh=True),
            )
            _LOGGER.debug(
                "Live match active for %s — refresh scheduled in %s s",
                self._name,
                self._live_scan_interval,
            )

    async def async_added_to_hass(self):
        """Load previously dispatched match_finished keys from disk so HA restarts
        do not re-fire events for matches that already ended."""
        await self._load_prematch_cache()
        await self._load_club_cache()
        store_key = f"soccer_live_{self._config_entry_id or 'default'}_{self._name}_finished"
        self._store = Store(self.hass, 1, store_key)
        stored = await self._store.async_load()
        if stored and "dispatched" in stored:
            dispatched = stored["dispatched"]
            # Keep the most recent 500 entries
            if len(dispatched) > 500:
                dispatched = dispatched[-500:]
            self._match_finished_list = dispatched
            self._match_finished_dispatched = set(dispatched)
            _LOGGER.debug(
                f"Loaded {len(self._match_finished_dispatched)} match_finished entries from storage for {self._name}"
            )

    async def _save_match_finished_store(self):
        """Persist the match_finished set to HA .storage."""
        if self._store:
            await self._store.async_save({"dispatched": self._match_finished_list[-500:]})

    @property
    def state(self):
        return self._state

    def _card_defaults(self):
        """Shared card presentation preferences (appearance/palette/compact/
        language) so multiple cards on one sensor can inherit a single setting
        instead of being configured individually. Empty keys are omitted."""
        if not self._config_entry_id:
            return {}
        entry = self.hass.config_entries.async_get_entry(self._config_entry_id)
        if not entry:
            return {}
        opts = entry.options
        out = {}
        if opts.get("card_appearance"):
            out["appearance"] = opts["card_appearance"]
        if opts.get("card_palette"):
            out["palette"] = opts["card_palette"]
        if opts.get("card_compact"):
            out["compact"] = True
        if opts.get("card_language"):
            out["language"] = opts["card_language"]
        return out

    @property
    def extra_state_attributes(self):
        card_defaults = self._card_defaults()
        return {
            **self._attributes,
            **({"card_defaults": card_defaults} if card_defaults else {}),
            "request_count": self._request_count,
            "last_request_time": self._last_request_time,
            "last_successful_update": self._last_successful_update,
            "last_error": self._last_error,
            "api_status": "authentication_failed" if self._auth_failed else ("error" if self._last_error else "ok"),
            "sync_status": self._sync_status(),
            "provider": self._provider,
            "provider_capabilities": list(PROVIDER_CAPABILITIES.get(self._provider, ())),
            "integration_version": INTEGRATION_VERSION,
            "data_schema_version": DATA_SCHEMA_VERSION,
            "recommended_card_types": recommended_card_types(self._sensor_type),
            "api_football_season": self._api_football_season,
            "api_football_quota": self._api_football_quota,
            "live_scan_interval": self._live_scan_interval,
            "start_date": self._filter_start_str(),
            "end_date": self._filter_end_str(),
            "sensor_type": self._sensor_type,
        }

    @property
    def scan_interval(self):
        return self._scan_interval

    @property
    def should_poll(self):
        return True

    @property
    def _provider_label(self):
        return "API-Football" if self._provider == PROVIDER_API_FOOTBALL else "ESPN"

    def _request_headers(self):
        if self._provider == PROVIDER_API_FOOTBALL:
            return {"x-apisports-key": self._api_football_key}
        return {"Accept-Language": "en"}

    @property
    def unique_id(self):
        return f"{self._config_entry_id}_{self._name}_{self._sensor_type}"

    @property
    def device_info(self):
        # Prefer the team name so a team's device reads "Soccer Live · Feyenoord"
        # rather than a raw competition code; fall back to the code, then the slug.
        display = self._team_name or (self._code if self._code and self._code not in ("N/A", "") else self._name)
        return {
            "identifiers": {(DOMAIN, self._config_entry_id)},
            "name": f"Soccer Live · {display}",
            "manufacturer": "API-Football" if self._provider == PROVIDER_API_FOOTBALL else "ESPN",
            "entry_type": "service",
        }

    @property
    def config_entry_id(self):
        return self._config_entry_id

    async def async_update(self):
        _LOGGER.info(f"Starting update for {self._name}")

        self._pending_events = []
        self._save_store_needed = False

        # Prune cache entries older than 5 minutes to prevent unbounded growth
        _now = datetime.now()
        SoccerLiveSensor._cache = {
            k: v for k, v in SoccerLiveSensor._cache.items()
            if (_now - v["time"]).total_seconds() < 300
        }
        _active_calendar_keys = {
            k for k, v in SoccerLiveSensor._calendar_cache.items()
            if (_now - v["time"]).total_seconds() < 300
        }
        SoccerLiveSensor._calendar_cache = {
            k: v for k, v in SoccerLiveSensor._calendar_cache.items()
            if k in _active_calendar_keys
        }
        SoccerLiveSensor._calendar_locks = {
            k: v for k, v in SoccerLiveSensor._calendar_locks.items()
            if k in _active_calendar_keys
        }
        SoccerLiveSensor._fetch_locks = {
            k: v for k, v in SoccerLiveSensor._fetch_locks.items()
            if k in SoccerLiveSensor._cache or v.locked()
        }
        self._prune_api_football_endpoint_cache(_now)

        # Use the request URL as cache key so sensors sharing the same provider endpoint share one fetch
        url = await self._build_url()
        if url is None:
            return
        cache_key = url
        main_cache_ttl = self._main_cache_ttl()
        if cache_key in SoccerLiveSensor._cache and (datetime.now() - SoccerLiveSensor._cache[cache_key]["time"]).total_seconds() < main_cache_ttl:
            try:
                await self._process_and_apply(SoccerLiveSensor._cache[cache_key]["data"])
                self._last_successful_update = datetime.now().isoformat()
                self._last_error = None
            except Exception as proc_err:
                self._last_error = str(proc_err)
                _LOGGER.error(f"Error processing cached data for {self._name}: {proc_err}")
            _LOGGER.info(f"Using cached data for {self._name}")
            self._schedule_live_refresh()
            return

        if self._scorers_unavailable:
            return

        _fetch_lock = SoccerLiveSensor._fetch_locks.setdefault(cache_key, asyncio.Lock())
        async with _fetch_lock:
            # Double-check cache: another sensor may have fetched while we waited for the lock
            if cache_key in SoccerLiveSensor._cache and (datetime.now() - SoccerLiveSensor._cache[cache_key]["time"]).total_seconds() < main_cache_ttl:
                try:
                    await self._process_and_apply(SoccerLiveSensor._cache[cache_key]["data"])
                    self._last_successful_update = datetime.now().isoformat()
                    self._last_error = None
                except Exception as proc_err:
                    self._last_error = str(proc_err)
                    _LOGGER.error(f"Error processing cached data for {self._name} (lock hit): {proc_err}")
                self._schedule_live_refresh()
                return

            headers = self._request_headers()
            _timeout = aiohttp.ClientTimeout(total=10)
            session = async_get_clientsession(self.hass)
            retries = 0
            while retries < 3:
                try:
                    async with session.get(url, headers=headers, timeout=_timeout) as response:
                        if response.status == 200:
                            raw = await response.read()
                            try:
                                data = await self.hass.async_add_executor_job(json.loads, raw)
                            except (ValueError, UnicodeDecodeError) as json_err:
                                self._last_error = f"Invalid JSON from {self._provider_label}: {json_err}"
                                _LOGGER.error(f"Invalid JSON for {self._name}: {json_err}")
                                break
                            _LOGGER.debug(f"Data received for {self._name}")
                            if self._api_football_body_is_auth_error(data):
                                self._handle_auth_failure()
                                break
                            af_error = self._api_football_error(data)
                            if af_error:
                                self._last_error = f"API-Football: {af_error}"
                                _LOGGER.warning("API-Football returned an error for %s: %s", self._name, af_error)
                                break
                            try:
                                await self._process_and_apply(data)
                            except Exception as proc_err:
                                self._last_error = str(proc_err)
                                _LOGGER.error(f"Error processing data for {self._name}: {proc_err}")
                            else:
                                SoccerLiveSensor._cache[cache_key] = {
                                    "data": data,
                                    "time": datetime.now(),
                                }
                                await self._refresh_api_football_status()
                                self._last_successful_update = datetime.now().isoformat()
                                self._last_error = None
                                self._clear_auth_failure()
                            self._schedule_live_refresh()
                            self._request_count += 1
                            self._last_request_time = datetime.now().isoformat()
                            _LOGGER.info(f"Finished update for {self._name}")
                            break
                        elif response.status < 500:
                            # 4xx: endpoint does not exist or access denied — do not retry
                            _LOGGER.debug(f"HTTP {response.status} for {self._name} — no retry")
                            if self._provider == PROVIDER_API_FOOTBALL and response.status in (401, 403):
                                # Rejected credentials — surface a clear status and reauth.
                                self._handle_auth_failure()
                            elif self._sensor_type == "top_scorers" and response.status == 404:
                                self._state = "Not available"
                                self._scorers_unavailable = True
                                _LOGGER.info(f"Top scorers not available for {self._code} ({self._provider_label} endpoint returned 404 — not supported for all competitions)")
                            else:
                                self._last_error = f"HTTP {response.status}"
                            break
                        else:
                            # 5xx: temporary server error — wait briefly and retry
                            await asyncio.sleep(2)
                            retries += 1
                except aiohttp.ClientError as error:
                    self._last_error = str(error)
                    await asyncio.sleep(2)
                    retries += 1
                except asyncio.TimeoutError:
                    self._last_error = f"Timeout while fetching {self._provider_label} data"
                    await asyncio.sleep(2)
                    retries += 1
            else:
                self._last_error = f"All attempts failed; no data received from {self._provider_label}"
                _LOGGER.warning(f"All attempts failed for {self._name} — no data received from {self._provider_label}")

    async def _process_and_apply(self, data):
        """Process raw ESPN data and apply state/attributes to this sensor.
        Carries forward last-event attributes so they survive between update cycles."""
        previous_attrs = self._attributes
        result = await self.hass.async_add_executor_job(self._process_data, data)
        self._state = result["state"]
        attrs = result["attributes"]
        from .match_contract import annotate_match, current_match
        for key in ("matches", "previous_matches", "upcoming_matches"):
            if isinstance(attrs.get(key), list):
                attrs[key] = [annotate_match(match) for match in attrs[key]]
        if attrs.get("next_match"):
            attrs["next_match"] = annotate_match(attrs["next_match"])
        attrs["current_match"] = current_match(attrs.get("matches") or [])
        attrs["match_phase"] = (
            attrs["current_match"].get("match_phase")
            if attrs["current_match"] else
            (attrs.get("next_match") or {}).get("match_phase", "unknown")
        )
        if self._max_matches and "matches" in attrs:
            _all = attrs["matches"]
            _live = [m for m in _all if m.get("state") == "in"]
            _upcoming = [m for m in _all if m.get("state") == "pre"]
            _past = list(reversed([m for m in _all if m.get("state") == "post"]))
            attrs["matches"] = (_live + _upcoming + _past)[:self._max_matches]
        for _k in ("last_event", "last_event_type", "last_event_timestamp",
                   "last_goal_event", "last_card_event",
                   "last_match_started_event", "last_match_finished_event"):
            if _k in self._attributes and _k not in attrs:
                attrs[_k] = self._attributes[_k]
        self._attributes = attrs
        self._pending_events = result.get("events", [])
        self._detect_and_dispatch_halftime(attrs.get("matches") or [], self._pending_events)
        self._save_store_needed = any(e[0] == "soccer_live_match_finished" for e in self._pending_events)
        await self._enrich_with_summary()
        await self._enrich_club_data()
        await self._enrich_api_football_assists()
        self._fire_new_lineup_events(previous_attrs, self._attributes)
        await self._flush_pending_events()
        self._publish_matches(self._attributes.get("matches") or [])

    def _fire_new_lineup_events(self, previous_attrs, current_attrs):
        from .club_changes import newly_available_lineups
        for match in newly_available_lineups(previous_attrs, current_attrs):
            self.hass.bus.async_fire("soccer_live_lineup_available", {
                "entity_id": self.entity_id,
                "team_id": self._team_id,
                "event_id": match.get("event_id"),
                "home_team": match.get("home_team"),
                "away_team": match.get("away_team"),
                "home_players": [item.get("name") or item.get("player") for item in (match.get("lineup_home") or [])],
                "away_players": [item.get("name") or item.get("player") for item in (match.get("lineup_away") or [])],
            })

    def _publish_matches(self, matches):
        """Publish this sensor's match list to a shared per-entry store so other
        platforms (e.g. the calendar) can read it directly instead of scanning
        entity states."""
        if not self._config_entry_id:
            return
        store = (
            self.hass.data.setdefault(DOMAIN, {})
            .setdefault(self._config_entry_id, {})
            .setdefault("match_sources", {})
        )
        store[self.unique_id] = matches

    def _filter_start_str(self):
        d = self._dyn_start_date or self._start_date
        return d.strftime("%Y-%m-%d") if d else None

    def _filter_end_str(self):
        d = self._dyn_end_date or self._end_date
        return d.strftime("%Y-%m-%d") if d else None

    async def _flush_pending_events(self):
        """Fire events collected during executor processing on the event loop (thread-safe).

        team_match always pairs with a team_matches sensor that fires the actual HA events
        and notifications. To avoid duplicates, team_match only updates its own last_event
        attributes without touching the bus.
        """
        fire_bus = self._sensor_type != "team_match"
        now_iso = datetime.now().isoformat()
        for event_type, event_data in self._pending_events:
            self._store_last_event_attributes(event_type, event_data, now_iso)
            if fire_bus:
                self.hass.bus.fire(event_type, event_data)
                await self._send_notification(event_type, event_data)
        self._pending_events = []
        if self._save_store_needed:
            self._save_store_needed = False
            await self._save_match_finished_store()

    def _store_last_event_attributes(self, event_type, event_data, timestamp):
        """Expose the latest detected event as sensor attributes for simple automations."""
        payload = {
            **event_data,
            "event_type": event_type,
            "timestamp": timestamp,
        }
        self._attributes["last_event_type"] = event_type
        self._attributes["last_event_timestamp"] = timestamp
        self._attributes["last_event"] = payload

        if event_type == "soccer_live_goal":
            self._attributes["last_goal_event"] = payload
        elif event_type in ("soccer_live_yellow_card", "soccer_live_red_card"):
            self._attributes["last_card_event"] = payload
        elif event_type == "soccer_live_match_started":
            self._attributes["last_match_started_event"] = payload
        elif event_type == "soccer_live_match_finished":
            self._attributes["last_match_finished_event"] = payload

    async def _send_notification(self, event_type, event_data):
        """Send HA notification when a goal or card event fires, if notify_service is configured."""
        try:
            config_entry = self.hass.config_entries.async_get_entry(self._config_entry_id)
            notify_service = (config_entry.options if config_entry else {}).get("notify_service", "")
            if not notify_service:
                return
            if event_type == "soccer_live_goal":
                title = f"⚽ Goal! {event_data.get('home_team','')} {event_data.get('home_score','')} - {event_data.get('away_score','')} {event_data.get('away_team','')}"
                message = f"{event_data.get('player','Unknown')} · {event_data.get('minute','')}"
            elif event_type == "soccer_live_yellow_card":
                title = f"🟨 Yellow card · {event_data.get('home_team','')} vs {event_data.get('away_team','')}"
                message = f"{event_data.get('player','Unknown')} · {event_data.get('minute','')}"
            elif event_type == "soccer_live_red_card":
                title = f"🟥 Red card · {event_data.get('home_team','')} vs {event_data.get('away_team','')}"
                message = f"{event_data.get('player','Unknown')} · {event_data.get('minute','')}"
            elif event_type == "soccer_live_match_finished":
                title = f"🏁 Full time · {event_data.get('home_team','')} {event_data.get('home_score','')} - {event_data.get('away_score','')} {event_data.get('away_team','')}"
                message = event_data.get('league_name','')
            else:
                return
            domain, service = notify_service.split(".", 1) if "." in notify_service else ("notify", notify_service)
            await self.hass.services.async_call(domain, service, {"title": title, "message": message}, blocking=False)
        except Exception as e:
            _LOGGER.debug(f"Notification error: {e}")

    async def _enrich_with_summary(self):
        """For team_match sensors, add lineup, formation, key events, and h2h
        from the summary?event=ID endpoint for the current match."""
        if self._provider == PROVIDER_API_FOOTBALL:
            if self._sensor_type not in {"team_match", "team_matches", "team_matches_mixed"} or not self._enable_summary_enrichment:
                return
            await self._enrich_with_api_football_fixture()
            return
        if self._sensor_type != "team_match" or not self._enable_summary_enrichment:
            return
        matches = self._attributes.get("matches") or []
        if not matches:
            return
        first = matches[0]
        event_id = first.get("event_id")
        if not event_id:
            return

        # Post-match summaries won't change: serve from cache to avoid repeated fetches
        if event_id in self._summary_cache:
            first.update(self._summary_cache[event_id])
            return

        summary = await self._fetch_match_summary(event_id)
        if not summary:
            return
        from .parsers.scoreboard import process_summary_data
        # Sync processing offloaded to executor to keep event loop free
        summary_data = await self.hass.async_add_executor_job(process_summary_data, summary)
        # Inject only into matches[0]: cards (Lineup/Timeline/Team) read
        # lineup/key_events/h2h from matches[0]. No top-level copy to avoid
        # doubling the payload and exceeding the 16384-byte recorder limit.
        first.update(summary_data)

        # Cache only finished matches — live matches must keep refreshing
        if first.get("state") == "post":
            if len(self._summary_cache) >= 20:
                self._summary_cache.pop(next(iter(self._summary_cache)))
            self._summary_cache[event_id] = summary_data

    async def _build_url(self):
        if self._provider == PROVIDER_API_FOOTBALL:
            return self._build_api_football_url()

        season_start = ""
        season_end = ""

        # Sensors below do not need the competition calendar. Return early to
        # avoid a burst of unnecessary calendar calls during Home Assistant
        # startup or reloads.
        if self._sensor_type == "news":
            return f"{self.base_url_2}/{self._code}/news?limit=15"

        if self._sensor_type == "top_scorers":
            return f"{self.base_url_2}/{self._code}/leaders"

        if self._sensor_type == "bracket":
            # Bracket covers the full KO phase (Feb-Jul).
            # If we are in the second half of the season (Feb-Jul) use current year,
            # otherwise use next year (the KO phase always falls in the second half).
            from datetime import datetime as _dt
            now = _dt.now()
            if now.month >= 8:
                ko_year = now.year + 1
            else:
                ko_year = now.year
            return f"{self.base_url_3}/{self._code}/scoreboard?limit=300&dates={ko_year}0201-{ko_year}0731"

        if self._sensor_type == "standings":
            return f"{self.base_url}/{self._code}/standings?"

        if self._sensor_type == "team_matches_mixed" and self._team_name:
            return f"{self.base_url_3}/all/teams/{self._team_id}/schedule?fixture=true"

        if self._sensor_type == "all_matches_today":
            return f"{self.base_url_2}/all/scoreboard"

        if self._code and self._sensor_type in _DATE_RANGE_SENSOR_TYPES:
            season_start, season_end = await self._get_calendar_data()

        # Store dynamic dates for use in _process_data so match filtering
        # follows the current season automatically without manual yearly updates.
        if season_start and season_end:
            try:
                self._dyn_start_date = datetime.strptime(season_start[:10], "%Y-%m-%d")
                self._dyn_end_date = datetime.strptime(season_end[:10], "%Y-%m-%d")
            except (ValueError, TypeError):
                pass

        # Fall back to static dates if ESPN did not return calendar dates.
        # Empty filters are valid, so omit the date range when neither source
        # provides a complete range.
        if not season_start or not season_end:
            if self._start_date and self._end_date:
                season_start = self._start_date.strftime("%Y-%m-%d")
                season_end = self._end_date.strftime("%Y-%m-%d")
            else:
                season_start = ""
                season_end = ""

        if season_start and season_end:
            season_start = season_start[:10].replace("-", "")
            season_end = season_end[:10].replace("-", "")

        if self._sensor_type in _DATE_RANGE_SENSOR_TYPES:
            url = f"{self.base_url_3}/{self._code}/scoreboard?limit=1000"
            if season_start and season_end:
                url += f"&dates={season_start}-{season_end}"
            return url

        return None

    def _build_api_football_url(self):
        if not self._api_football_key:
            self._last_error = "API-Football key is missing"
            return None

        season = self._api_football_effective_season()
        start, end = self._api_football_date_range()
        params = {}

        if self._sensor_type in {"team_match", "team_matches", "team_matches_mixed"}:
            if not self._team_id:
                self._last_error = "API-Football team_id is missing"
                return None
            params = {"team": self._team_id, "season": season}
            if start and end:
                params.update({"from": start, "to": end})
            return f"{self.api_football_base_url}/fixtures?{urlencode(params)}"

        if self._sensor_type == "all_matches_today":
            return f"{self.api_football_base_url}/fixtures?{urlencode({'date': self._local_today_str()})}"

        if self._sensor_type == "match_day" and self._code:
            params = {"league": self._code, "season": season}
            if start and end:
                params.update({"from": start, "to": end})
            return f"{self.api_football_base_url}/fixtures?{urlencode(params)}"

        if self._sensor_type == "standings" and self._code:
            return f"{self.api_football_base_url}/standings?{urlencode({'league': self._code, 'season': season})}"

        if self._sensor_type == "top_scorers" and self._code:
            return f"{self.api_football_base_url}/players/topscorers?{urlencode({'league': self._code, 'season': season})}"

        self._last_error = f"{self._sensor_type} is not supported by API-Football provider yet"
        return None

    def _local_today_str(self):
        user_timezone = getattr(getattr(self.hass, "config", None), "time_zone", None) or "UTC"
        try:
            local_tz = ZoneInfo(user_timezone)
        except Exception:
            local_tz = timezone.utc
        return datetime.now(local_tz).strftime("%Y-%m-%d")

    def _api_football_effective_season(self):
        if self._api_football_season:
            return self._api_football_season
        start = self._dyn_start_date or self._start_date
        end = self._dyn_end_date or self._end_date
        now = datetime.now()
        if self._sensor_type in {"standings", "top_scorers"} and now.month < 8:
            return now.year - 1
        if start and end:
            if start.year == end.year:
                return start.year
            if start <= now <= end:
                return now.year
            return start.year
        if start:
            return start.year
        return now.year

    def _api_football_date_range(self):
        start = self._dyn_start_date or self._start_date
        end = self._dyn_end_date or self._end_date
        if start and end:
            return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        return "", ""

    async def _fetch_match_summary(self, event_id):
        """Fetch full match summary (lineup, formation, key events) for the current match."""
        if not event_id or not self._code:
            return None
        url = f"{self.base_url_2}/{self._code}/summary?event={event_id}"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(url, headers={"Accept-Language": "en"}, timeout=aiohttp.ClientTimeout(total=10)) as response:
                if response.status == 200:
                    raw = await response.read()
                    return await self.hass.async_add_executor_job(json.loads, raw)
        except Exception as e:
            _LOGGER.debug(f"Error fetching summary for {event_id}: {e}")
        return None

    async def _enrich_with_api_football_fixture(self):
        matches = self._attributes.get("matches") or []
        if not matches:
            return

        # H2H is the most useful enrichment for an upcoming fixture and costs a
        # single, 24-hour cached request. Fetch it before enriching historical
        # fixtures: a list sensor can otherwise spend up to fifteen requests on
        # events/statistics/lineups and enter provider backoff before H2H runs.
        await self._enrich_api_football_head_to_head(matches)

        if self._sensor_type in {"team_matches", "team_matches_mixed"}:
            targets = self._api_football_team_list_enrichment_targets(matches)
        else:
            # Single-match card: don't burn quota enriching a match that is still
            # far off — events/statistics/lineups only exist close to kickoff.
            now = datetime.now(timezone.utc)
            targets = [m for m in matches if self._should_enrich_api_football_target(m, now)]

        from .parsers.api_football import process_fixture_enrichment
        for match in targets:
            event_id = match.get("event_id")
            if not event_id:
                continue

            if event_id in self._summary_cache:
                match.update(self._summary_cache[event_id])
                continue

            events_data, statistics_data, lineups_data = await asyncio.gather(
                self._fetch_api_football_json("fixtures/events", {"fixture": event_id}),
                self._fetch_api_football_json("fixtures/statistics", {"fixture": event_id}),
                self._fetch_api_football_json("fixtures/lineups", {"fixture": event_id}),
            )
            if not any(self._api_football_response_has_items(d) for d in (events_data, statistics_data, lineups_data)):
                continue

            enrichment = await self.hass.async_add_executor_job(
                process_fixture_enrichment,
                events_data,
                statistics_data,
                lineups_data,
                match.get("home_id"),
                match.get("away_id"),
            )
            match.update(enrichment)
            if match.get("state") == "post":
                if len(self._summary_cache) >= 20:
                    self._summary_cache.pop(next(iter(self._summary_cache)))
                self._summary_cache[event_id] = enrichment

        await self._enrich_api_football_prematch(matches)

        self._detect_and_dispatch_goals(matches, self._pending_events)
        self._detect_and_dispatch_cards(matches, self._pending_events)
        self._detect_and_dispatch_match_finished(matches, self._pending_events)
        self._detect_and_dispatch_match_started(matches, self._pending_events)
        self._refresh_api_football_enriched_schedule_attributes(matches)

    async def _enrich_api_football_head_to_head(self, matches):
        """Attach recent completed meetings to the live/next fixture.

        Team IDs are sorted in the request so every sensor following the same
        matchup shares one 24-hour endpoint-cache entry.
        """
        target = self._prematch_target_match(matches)
        if not target or target.get("head_to_head"):
            return
        try:
            team_ids = sorted(
                (int(target.get("home_id")), int(target.get("away_id")))
            )
        except (TypeError, ValueError):
            return
        if team_ids[0] <= 0 or team_ids[0] == team_ids[1]:
            return

        data = await self._fetch_api_football_json(
            "fixtures/headtohead",
            {"h2h": f"{team_ids[0]}-{team_ids[1]}", "last": 8},
        )
        if not self._api_football_response_has_items(data):
            return

        from .parsers.api_football import process_head_to_head_data
        head_to_head = await self.hass.async_add_executor_job(
            process_head_to_head_data, data, self.hass, 8
        )
        if head_to_head:
            target["head_to_head"] = head_to_head

    def _next_upcoming_api_football_match(self, matches):
        """The nearest not-yet-started match with an event id, or None."""
        upcoming = [m for m in matches if m.get("state") == "pre" and m.get("event_id")]
        if not upcoming:
            return None
        upcoming.sort(key=lambda m: m.get("date_iso") or "")
        return upcoming[0]

    async def _enrich_api_football_prematch(self, matches):
        """Attach pre-match prediction/odds/injuries/standing to the next match,
        cache the snapshot by fixture id, and re-attach it to a match that is now
        live/finished so the pre-match context stays visible without new requests."""
        match = self._prematch_target_match(matches)
        if match:
            await self._fetch_and_store_prematch(match)
        self._reattach_prematch(matches)

    async def _enrich_api_football_assists(self):
        """Attach a real top-assists ranking (API-Football /players/topassists) to
        a top_scorers sensor, so the Scorers card's assists mode is the actual
        competition-wide assist leaders, not just assists among the top scorers."""
        if self._provider != PROVIDER_API_FOOTBALL or self._sensor_type != "top_scorers" or not self._code:
            return
        season = self._api_football_effective_season()
        data = await self._fetch_api_football_json(
            "players/topassists", {"league": self._code, "season": season}
        )
        if data is None:
            return
        from .parsers.api_football import process_scorers_data
        parsed = await self.hass.async_add_executor_job(process_scorers_data, data)
        assists = (parsed or {}).get("scorers") or []
        if assists:
            self._attributes["assists"] = assists

    async def _enrich_club_data(self):
        """Attach the club profile, coach, squad and recent transfers for the
        tracked team (API-Football, team sensors). The assembled blob is cached
        24h and persisted to disk, so an HA restart re-uses it instead of
        spending four requests per team sensor on every startup."""
        if self._provider != PROVIDER_API_FOOTBALL or not self._enable_club_data:
            return
        if self._sensor_type not in {"team_match", "team_matches", "team_matches_mixed"}:
            return
        team_id = self._team_id
        if not team_id:
            return

        # Re-use the persisted club blob while it is still fresh (< 24h),
        # avoiding four API requests after every restart.
        cached = self._get_cached_club(team_id)
        if cached is not None:
            self._attributes["club"] = cached
            return

        from .parsers.api_football import (
            process_team_profile,
            process_coach,
            process_squad,
            process_transfers,
        )

        profile_data, coach_data, squad_data, transfers_data = await asyncio.gather(
            self._fetch_api_football_json("teams", {"id": team_id}),
            self._fetch_api_football_json("coachs", {"team": team_id}),
            self._fetch_api_football_json("players/squads", {"team": team_id}),
            self._fetch_api_football_json("transfers", {"team": team_id}),
        )

        old_entry = SoccerLiveSensor._club_cache.get(str(team_id)) or {}
        previous_club = old_entry.get("club") if isinstance(old_entry, dict) else None
        club = {}
        if profile_data is not None:
            profile = await self.hass.async_add_executor_job(process_team_profile, profile_data)
            if profile:
                club["profile"] = profile
        if coach_data is not None:
            coach = await self.hass.async_add_executor_job(process_coach, coach_data, team_id)
            if coach:
                club["coach"] = coach
        if squad_data is not None:
            squad = await self.hass.async_add_executor_job(process_squad, squad_data)
            if squad:
                club["squad"] = squad
        if transfers_data is not None:
            transfers = await self.hass.async_add_executor_job(process_transfers, transfers_data, team_id)
            if transfers:
                club["transfers"] = transfers
        if club:
            from .club_changes import diff_club
            changes = diff_club(previous_club, club)
            self._attributes["club"] = club
            self._attributes["club_changes"] = changes
            for change in changes:
                fingerprint = f"{team_id}:{json.dumps(change, sort_keys=True, default=str)}"
                now = datetime.now().timestamp()
                last = SoccerLiveSensor._club_event_fingerprints.get(fingerprint, 0)
                if now - last < 300:
                    continue
                SoccerLiveSensor._club_event_fingerprints[fingerprint] = now
                event_data = {"entity_id": self.entity_id, "team_id": team_id, **change}
                self.hass.bus.async_fire("soccer_live_club_change", event_data)
                self.hass.bus.async_fire(f"soccer_live_{change['type']}", event_data)
            self._store_club(team_id, club)

    _club_cache = {}
    _club_store = None
    _club_loaded = False
    _club_event_fingerprints = {}
    _CLUB_TTL = 86400  # seconds; matches the per-endpoint club cache TTL
    # Bump when the club blob's shape or parsing changes, so an upgrade doesn't
    # keep serving a stale blob (e.g. an old, wrongly-picked coach) for 24h.
    _CLUB_CACHE_VERSION = 2

    async def _load_club_cache(self):
        """Load the persisted club blobs once so a restart re-uses fresh club
        data (profile/coach/squad/transfers) instead of re-fetching it."""
        if SoccerLiveSensor._club_loaded:
            return
        SoccerLiveSensor._club_loaded = True
        try:
            SoccerLiveSensor._club_store = Store(self.hass, 1, "soccer_live_club")
            stored = await SoccerLiveSensor._club_store.async_load()
            if isinstance(stored, dict):
                SoccerLiveSensor._club_cache.update(stored)
        except Exception as err:  # pragma: no cover - storage best-effort
            _LOGGER.debug("Could not load club cache: %s", err)

    def _get_cached_club(self, team_id):
        """Return the cached club blob for team_id if present and younger than
        the TTL, else None."""
        entry = SoccerLiveSensor._club_cache.get(str(team_id))
        if not isinstance(entry, dict):
            return None
        if entry.get("v") != self._CLUB_CACHE_VERSION:
            return None  # blob from an older code version -> refetch
        club = entry.get("club")
        ts = entry.get("ts")
        if not club or not ts:
            return None
        try:
            age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
        except (ValueError, TypeError):
            return None
        if age < 0 or age > self._CLUB_TTL:
            return None
        return club

    def _store_club(self, team_id, club):
        cache = SoccerLiveSensor._club_cache
        cache[str(team_id)] = {
            "club": club,
            "ts": datetime.now().isoformat(),
            "v": self._CLUB_CACHE_VERSION,
        }
        if len(cache) > 60:
            cache.pop(next(iter(cache)))
        if SoccerLiveSensor._club_store is not None:
            SoccerLiveSensor._club_store.async_delay_save(
                lambda: dict(SoccerLiveSensor._club_cache), 60
            )

    def _prematch_target_match(self, matches):
        """Which match to fetch pre-match data for: the live match when there is
        one (API-Football keeps returning the prediction during the game),
        otherwise the nearest upcoming match."""
        live = [m for m in matches if m.get("state") == "in" and m.get("event_id")]
        if live:
            return live[0]
        return self._next_upcoming_api_football_match(matches)

    async def _fetch_and_store_prematch(self, match):
        """Fetch and attach pre-match prediction/odds/injuries/standing for the
        given (upcoming) match, then cache the snapshot by fixture id."""
        fixture_id = match["event_id"]
        from .parsers.api_football import (
            process_prediction_data,
            process_injuries_data,
            process_odds_data,
            process_live_odds_data,
            extract_team_standing,
        )

        league_id = match.get("league_id")
        season = match.get("season_info")
        fetch_standings = bool(league_id) and season not in (None, "")
        # Once the match is live, API-Football drops the pre-match /odds. The
        # /odds/live in-play feed carries the real live 1X2, but it wants frequent
        # polling, so it is opt-in (enable_live_odds) and paused on 403/empty.
        # While live without live odds, the last pre-match odds stay via the
        # snapshot re-attach, so we simply skip the odds request.
        is_live = match.get("state") == "in"
        attempt_live_odds = is_live and self._enable_live_odds and self._live_odds_available()

        tasks = [
            self._fetch_api_football_json("predictions", {"fixture": fixture_id}),
            self._fetch_api_football_json("injuries", {"fixture": fixture_id}),
        ]
        odds_idx = None
        if attempt_live_odds:
            odds_idx = len(tasks)
            tasks.append(self._fetch_api_football_json("odds/live", {"fixture": fixture_id}))
        elif not is_live:
            odds_idx = len(tasks)
            tasks.append(self._fetch_api_football_json("odds", {"fixture": fixture_id}))
        standings_idx = None
        if fetch_standings:
            standings_idx = len(tasks)
            tasks.append(self._fetch_api_football_json("standings", {"league": league_id, "season": season}))

        results = await asyncio.gather(*tasks)
        pred_data, inj_data = results[0], results[1]
        odds_data = results[odds_idx] if odds_idx is not None else None
        standings_data = results[standings_idx] if standings_idx is not None else None

        if pred_data is not None:
            prediction = await self.hass.async_add_executor_job(process_prediction_data, pred_data)
            if prediction:
                match["prediction"] = prediction

        if inj_data is not None:
            injuries = await self.hass.async_add_executor_job(
                process_injuries_data, inj_data, match.get("home_id"), match.get("away_id")
            )
            if injuries:
                match["injuries_home"] = injuries["injuries_home"]
                match["injuries_away"] = injuries["injuries_away"]

        if attempt_live_odds:
            # Track availability: 403 (plan) or repeated empty responses pause the
            # feature; a present response (even all-suspended) means it works.
            status = SoccerLiveSensor._af_stat("odds/live").get("last_status")
            has_response = isinstance(odds_data, dict) and bool(odds_data.get("response"))
            self._note_live_odds_result(status, has_response)

        if odds_data is not None:
            odds_parser = process_live_odds_data if attempt_live_odds else process_odds_data
            odds = await self.hass.async_add_executor_job(odds_parser, odds_data)
            if odds:
                match["odds"] = odds

        if standings_data is not None:
            home_standing = await self.hass.async_add_executor_job(
                extract_team_standing, standings_data, match.get("home_id")
            )
            away_standing = await self.hass.async_add_executor_job(
                extract_team_standing, standings_data, match.get("away_id")
            )
            if home_standing:
                match["home_rank"] = home_standing["rank"]
                match["home_points"] = home_standing["points"]
            if away_standing:
                match["away_rank"] = away_standing["rank"]
                match["away_points"] = away_standing["points"]

        self._store_prematch(match)

    # Pre-match snapshot fields to preserve across the pre -> live transition.
    _PREMATCH_FIELDS = (
        "prediction", "odds", "injuries_home", "injuries_away",
        "home_rank", "home_points", "away_rank", "away_points",
    )
    _prematch_cache = {}
    _prematch_store = None
    _prematch_loaded = False

    async def _load_prematch_cache(self):
        """Load the persisted pre-match snapshots once, so a restart during a
        match doesn't lose the prediction/odds/injuries context."""
        if SoccerLiveSensor._prematch_loaded:
            return
        SoccerLiveSensor._prematch_loaded = True
        try:
            SoccerLiveSensor._prematch_store = Store(self.hass, 1, "soccer_live_prematch")
            stored = await SoccerLiveSensor._prematch_store.async_load()
            if isinstance(stored, dict):
                SoccerLiveSensor._prematch_cache.update(stored)
        except Exception as err:  # pragma: no cover - storage best-effort
            _LOGGER.debug("Could not load pre-match cache: %s", err)

    def _store_prematch(self, match):
        fixture_id = str(match.get("event_id") or "")
        if not fixture_id:
            return
        snapshot = {k: match[k] for k in self._PREMATCH_FIELDS if k in match}
        if not snapshot:
            return
        cache = SoccerLiveSensor._prematch_cache
        # Merge, so pre-match odds (which API-Football drops once the match is
        # live) aren't wiped by a later live fetch that no longer returns them.
        existing = cache.pop(fixture_id, None) or {}
        existing.update(snapshot)
        cache[fixture_id] = existing
        # Bound the cache so it can't grow without limit.
        if len(cache) > 60:
            cache.pop(next(iter(cache)))
        # Persist (debounced) so the snapshot survives an HA restart.
        if SoccerLiveSensor._prematch_store is not None:
            SoccerLiveSensor._prematch_store.async_delay_save(
                lambda: dict(SoccerLiveSensor._prematch_cache), 60
            )

    def _reattach_prematch(self, matches):
        """Re-attach cached pre-match data to any match (e.g. now live) that had it
        but lost it when the fixture was rebuilt from /fixtures. Never overwrites
        fields the current match already carries."""
        cache = SoccerLiveSensor._prematch_cache
        if not cache:
            return
        for match in matches:
            snapshot = cache.get(str(match.get("event_id") or ""))
            if not snapshot:
                continue
            for key, value in snapshot.items():
                if key not in match:
                    match[key] = value

    def _api_football_response_has_items(self, data):
        if not isinstance(data, dict):
            return False
        response = data.get("response")
        return isinstance(response, list) and bool(response)

    def _api_football_team_list_enrichment_targets(self, matches):
        now = datetime.now(timezone.utc)
        live = [m for m in matches if m.get("state") == "in"]
        recent_finished = [
            m for m in matches
            if self._should_enrich_recent_finished_api_football_match(m, now)
        ]
        latest_finished = [m for m in matches if m.get("state") == "post"][-5:]
        targets = []
        seen = set()
        for match in live + recent_finished + latest_finished:
            event_id = match.get("event_id")
            key = event_id or f"{match.get('date_iso')}|{match.get('home_team')}|{match.get('away_team')}"
            if key in seen:
                continue
            seen.add(key)
            targets.append(match)
        return targets

    def _refresh_api_football_enriched_schedule_attributes(self, matches):
        if self._sensor_type not in {"team_matches", "team_matches_mixed", "all_matches_today", "match_day"}:
            return
        self._attributes.update(self._compute_all_matches_attributes(matches, [], detect_events=False))
        current_next = self._attributes.get("next_match")
        if isinstance(current_next, dict):
            current_id = current_next.get("event_id")
            refreshed_next = next((m for m in matches if m.get("event_id") == current_id), None)
            if refreshed_next:
                self._attributes["next_match"] = refreshed_next

    def _should_enrich_api_football_target(self, match, now):
        """Whether a single-match card should fetch enrichment for this match.

        Live and finished matches are always enriched. An upcoming match is only
        enriched once kickoff is within reach (lineups appear ~1h before, stats
        and events only during play), so a match days away doesn't repeatedly
        fetch three empty endpoints and waste the API quota."""
        if match.get("state") != "pre":
            return True
        raw_date = match.get("date_iso")
        if not raw_date:
            return False
        try:
            kickoff = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=timezone.utc)
            kickoff = kickoff.astimezone(timezone.utc)
        except ValueError:
            return False
        return (kickoff - now) <= timedelta(hours=3)

    def _should_enrich_recent_finished_api_football_match(self, match, now):
        if match.get("state") != "post":
            return False
        if match.get("match_details") or match.get("key_events"):
            return False
        raw_date = match.get("date_iso")
        if not raw_date:
            return False
        try:
            match_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            if match_date.tzinfo is None:
                match_date = match_date.replace(tzinfo=timezone.utc)
            match_date = match_date.astimezone(timezone.utc)
        except ValueError:
            return False
        recent_hours = max(int(self._recent_match_hours or 0), 1)
        return match_date <= now and now - match_date <= timedelta(hours=recent_hours)

    @staticmethod
    def _af_stat(path):
        return SoccerLiveSensor._api_football_stats.setdefault(
            path, {"calls": 0, "cache_hits": 0, "last_success": None, "last_status": None}
        )

    @staticmethod
    def _af_enrichment_paused():
        pause = SoccerLiveSensor._af_enrich_pause_until
        return pause is not None and datetime.now() < pause

    @staticmethod
    def _af_is_rate_limit_message(msg):
        """Whether an API-Football 200-body error message is a rate/quota limit
        (per-minute or per-day), so it can be handled like an HTTP 429."""
        m = (msg or "").lower()
        return (
            "too many requests" in m
            or "requests per minute" in m
            or "requests per day" in m
            or "request limit" in m
            or "rate limit" in m
            or "ratelimit" in m
        )

    @staticmethod
    def _af_is_daily_limit_message(msg):
        """A per-day quota exhaustion (vs a transient per-minute burst). Retrying
        every 30 min all day is pointless, so these pause until the next reset."""
        m = (msg or "").lower()
        return "per day" in m or "for the day" in m or "daily" in m

    def _af_handle_rate_limit(self, path, reason):
        """Pause enrichment on a rate/quota limit. Only the first hit (while not
        already paused) starts the pause and logs — at INFO, since it's an
        expected, self-healing condition (e.g. the burst after a restart) and the
        last cached data keeps being served. Concurrent stragglers from the same
        burst are dropped to DEBUG so they don't spam the log or balloon the
        backoff. A per-day quota pauses until the next reset; a per-minute limit
        uses the doubling backoff. Diagnostics expose the pause (rate_limited_at)."""
        if self._af_enrichment_paused():
            _LOGGER.debug("API-Football still rate-limited while fetching %s (%s)", path, reason)
            return
        if self._af_is_daily_limit_message(reason):
            self._af_note_daily_limit()
            _LOGGER.info(
                "API-Football daily quota reached while fetching %s (%s) — pausing enrichment "
                "until the next quota reset (~%s); serving cached data meanwhile",
                path, reason, SoccerLiveSensor._af_enrich_pause_until,
            )
        else:
            self._af_note_rate_limited()
            _LOGGER.info(
                "API-Football rate limit hit while fetching %s (%s) — pausing enrichment for %s s; "
                "serving cached data meanwhile",
                path, reason, SoccerLiveSensor._af_backoff,
            )

    @staticmethod
    def _af_note_rate_limited():
        SoccerLiveSensor._af_backoff = min(max(60, SoccerLiveSensor._af_backoff * 2), 1800)
        SoccerLiveSensor._af_enrich_pause_until = datetime.now() + timedelta(seconds=SoccerLiveSensor._af_backoff)
        SoccerLiveSensor._api_football_rate_limited_at = datetime.now().isoformat()

    @staticmethod
    def _af_note_daily_limit():
        # Pause until the next UTC midnight (API-Football's daily counter reset),
        # at least 30 min out. Uses a naive-local pause to match _af_enrichment_paused.
        now_utc = datetime.now(timezone.utc)
        next_reset = (now_utc + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        secs = max(1800, (next_reset - now_utc).total_seconds())
        # Clear the per-minute backoff so an old minute-limit doesn't carry into
        # the next day once this daily pause elapses.
        SoccerLiveSensor._af_backoff = 0
        SoccerLiveSensor._af_enrich_pause_until = datetime.now() + timedelta(seconds=secs)
        SoccerLiveSensor._api_football_rate_limited_at = datetime.now().isoformat()

    # Live odds (/odds/live) can be forbidden by plan or structurally empty; pause
    # the feature on its own (longer than the 429 backoff) so it doesn't keep
    # burning the daily quota on requests that never return usable odds.
    _live_odds_pause_until = None
    _live_odds_misses = 0

    @staticmethod
    def _live_odds_available():
        p = SoccerLiveSensor._live_odds_pause_until
        return p is None or datetime.now() >= p

    @staticmethod
    def _note_live_odds_result(status, has_response):
        # HTTP 403 => the plan doesn't include in-play odds: back off for hours.
        if status == 403:
            SoccerLiveSensor._live_odds_pause_until = datetime.now() + timedelta(hours=6)
            SoccerLiveSensor._live_odds_misses = 0
            return
        # A present response (even an all-suspended market) means the feed works.
        if has_response:
            SoccerLiveSensor._live_odds_misses = 0
            return
        # Structurally empty for several live cycles => pause for an hour.
        SoccerLiveSensor._live_odds_misses += 1
        if SoccerLiveSensor._live_odds_misses >= 5:
            SoccerLiveSensor._live_odds_pause_until = datetime.now() + timedelta(hours=1)
            SoccerLiveSensor._live_odds_misses = 0

    @staticmethod
    def _af_note_success():
        pause = SoccerLiveSensor._af_enrich_pause_until
        # An in-flight request that started before a concurrent 429 must not
        # clear a fresh backoff — only reset once the pause window has elapsed.
        if pause is not None and datetime.now() < pause:
            return
        if SoccerLiveSensor._af_backoff or pause is not None:
            SoccerLiveSensor._af_backoff = 0
            SoccerLiveSensor._af_enrich_pause_until = None

    async def _fetch_api_football_json(self, path, params=None):
        if not self._api_football_key:
            return None
        cache_key = self._api_football_cache_key(path, params or {})
        ttl = self._api_football_cache_ttl(path)
        cached = SoccerLiveSensor._api_football_endpoint_cache.get(cache_key)
        if cached and (datetime.now() - cached["time"]).total_seconds() < ttl:
            SoccerLiveSensor._af_stat(path)["cache_hits"] += 1
            return cached["data"]

        if self._af_enrichment_paused():
            # Rate-limited: don't make a new request; serve the last cached value
            # (even if stale) so sections don't disappear.
            return cached["data"] if cached else None

        lock = SoccerLiveSensor._api_football_endpoint_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = SoccerLiveSensor._api_football_endpoint_cache.get(cache_key)
            if cached and (datetime.now() - cached["time"]).total_seconds() < ttl:
                SoccerLiveSensor._af_stat(path)["cache_hits"] += 1
                return cached["data"]
            if self._af_enrichment_paused():
                return cached["data"] if cached else None

            SoccerLiveSensor._af_stat(path)["calls"] += 1
            data = await self._fetch_api_football_json_uncached(path, params or {})
            if data is not None:
                SoccerLiveSensor._api_football_endpoint_cache[cache_key] = {
                    "data": data,
                    "time": datetime.now(),
                    "ttl": ttl,
                }
            return data

    async def _fetch_api_football_json_uncached(self, path, params=None):
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"{self.api_football_base_url}/{path}",
                headers=self._request_headers(),
                params=params or {},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                SoccerLiveSensor._af_stat(path)["last_status"] = response.status
                if response.status == 200:
                    raw = await response.read()
                    data = await self.hass.async_add_executor_job(json.loads, raw)
                    af_error = self._api_football_error(data)
                    if af_error:
                        # API-Football signals rate/quota limits as an HTTP 200 body
                        # error (not a 429). Treat those like a 429 so the shared
                        # enrichment backoff kicks in and stops the burst (e.g. all
                        # sensors enriching at once right after a restart).
                        if self._af_is_rate_limit_message(af_error):
                            self._af_handle_rate_limit(path, af_error)
                        else:
                            _LOGGER.warning("API-Football %s returned an error: %s", path, af_error)
                        return None
                    SoccerLiveSensor._af_stat(path)["last_success"] = datetime.now().isoformat()
                    self._af_note_success()
                    return data
                if response.status == 429:
                    self._af_handle_rate_limit(path, "HTTP 429")
                else:
                    _LOGGER.debug("API-Football enrichment %s returned HTTP %s", path, response.status)
        except Exception as e:
            _LOGGER.debug("Error fetching API-Football enrichment %s: %s", path, e)
        return None

    def _api_football_error(self, data):
        """Human-readable API-Football error from a 200 body, or None (also None
        for the ESPN provider, so callers can invoke it unconditionally)."""
        if self._provider != PROVIDER_API_FOOTBALL:
            return None
        from .parsers.api_football import extract_error
        return extract_error(data)

    def _api_football_body_is_auth_error(self, data):
        if self._provider != PROVIDER_API_FOOTBALL:
            return False
        from .parsers.api_football import is_auth_error
        return is_auth_error(data)

    def _handle_auth_failure(self):
        """Flag an API-Football authentication failure: set a clear status and
        start a reauth flow (once per entry) so the user can supply a new key
        without deleting the config."""
        self._auth_failed = True
        self._last_error = "API-Football API key is invalid"
        self._state = "Authentication failed"
        entry_id = self._config_entry_id
        if not entry_id or entry_id in SoccerLiveSensor._af_reauth_entries:
            return
        entry = self.hass.config_entries.async_get_entry(entry_id)
        if not entry:
            return
        SoccerLiveSensor._af_reauth_entries.add(entry_id)
        _LOGGER.warning(
            "API-Football rejected the API key for %s — starting reauth", self._name
        )
        entry.async_start_reauth(self.hass)

    def _clear_auth_failure(self):
        """Reset the auth-failure marker after a successful request, so a later
        key change is picked up cleanly."""
        if self._auth_failed:
            self._auth_failed = False
        SoccerLiveSensor._af_reauth_entries.discard(self._config_entry_id)

    def _is_rate_limited(self):
        """Whether the provider is currently rate/quota limiting us — an active
        API-Football backoff pause, or a rate-limit message in the last error."""
        if self._provider != PROVIDER_API_FOOTBALL:
            return False
        if self._af_enrichment_paused():
            return True
        return self._af_is_rate_limit_message(self._last_error or "")

    def _sync_status(self):
        """Lifecycle status for the card (see const.compute_sync_status).

        A polled sensor can't observably publish "fetching": HA only reads the
        attributes after async_update() returns, so the first load is reported as
        "initializing" (the card shows the same "fetching…" text for it). The
        "fetching" value is reserved for a future push-based coordinator."""
        return compute_sync_status(
            auth_failed=self._auth_failed,
            rate_limited=self._is_rate_limited(),
            has_data=self._last_successful_update is not None,
            has_error=bool(self._last_error),
        )

    async def _refresh_api_football_status(self):
        if self._provider != PROVIDER_API_FOOTBALL or not self._api_football_key:
            return
        status = await self._fetch_api_football_json("status")
        response = status.get("response", {}) if isinstance(status, dict) else {}
        requests = response.get("requests", {}) if isinstance(response, dict) else {}
        subscription = response.get("subscription", {}) if isinstance(response, dict) else {}
        if requests or subscription:
            self._api_football_quota = {
                "plan": subscription.get("plan"),
                "active": subscription.get("active"),
                "requests_current": requests.get("current"),
                "requests_limit_day": requests.get("limit_day"),
            }

    def _api_football_cache_key(self, path, params):
        return path, tuple(sorted((params or {}).items()))

    def _api_football_cache_ttl(self, path):
        if path == "status":
            return 1800
        if path == "fixtures/events":
            return 30
        if path in {"fixtures/statistics", "fixtures/lineups"}:
            return 300
        if path == "predictions":
            return 21600  # predictions change rarely; cache for 6 hours
        if path == "injuries":
            return 10800  # team news updates occasionally; cache for 3 hours
        if path == "odds":
            return 3600  # bookmaker odds update a few times a day; cache 1 hour
        if path == "odds/live":
            return 45  # in-play odds move fast; short cache dedups sensors on the same fixture
        if path == "standings":
            return 21600  # league table changes at most daily; cache for 6 hours
        if path == "fixtures/headtohead":
            return 86400  # historical meetings are immutable; one call per matchup/day
        if path in {"teams", "coachs", "players/squads", "transfers"}:
            return 86400  # club profile / squad / transfers change rarely; cache 24h
        if path == "players/topassists":
            return 21600  # top assists change at most daily; cache 6h
        return 300

    def _prune_api_football_endpoint_cache(self, now):
        SoccerLiveSensor._api_football_endpoint_cache = {
            k: v for k, v in SoccerLiveSensor._api_football_endpoint_cache.items()
            if (now - v["time"]).total_seconds() < v.get("ttl", 300)
        }
        SoccerLiveSensor._api_football_endpoint_locks = {
            k: v for k, v in SoccerLiveSensor._api_football_endpoint_locks.items()
            if k in SoccerLiveSensor._api_football_endpoint_cache or v.locked()
        }
    
    
    async def _get_calendar_data(self):
        """Fetch the competition calendar to determine season start and end dates."""
    
        if self._code == "99999":
           # _LOGGER.warning("Competition code 99999 excluded from calendar fetch.")
            return None, None

        calendar_url = f"{self.base_url_2}/{self._code}/scoreboard"
        cache_key = self._code or calendar_url
        cached = SoccerLiveSensor._calendar_cache.get(cache_key)
        if cached and (datetime.now() - cached["time"]).total_seconds() < 300:
            return cached["start"], cached["end"]

        lock = SoccerLiveSensor._calendar_locks.setdefault(cache_key, asyncio.Lock())
        async with lock:
            cached = SoccerLiveSensor._calendar_cache.get(cache_key)
            if cached and (datetime.now() - cached["time"]).total_seconds() < 300:
                return cached["start"], cached["end"]

            start, end = await self._fetch_calendar_data(calendar_url)
            SoccerLiveSensor._calendar_cache[cache_key] = {
                "start": start,
                "end": end,
                "time": datetime.now(),
            }
            return start, end

    async def _fetch_calendar_data(self, calendar_url):
        """Fetch calendar data from ESPN. Caller handles per-code caching."""
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(calendar_url, headers={"Accept-Language": "en"}, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                raw = await response.read()
                data = await self.hass.async_add_executor_job(json.loads, raw)
                # Extract season start/end from the calendar response.
                # ESPN no longer exposes calendarStartDate/EndDate at top level;
                # season dates live in leagues[0]. Read from there first,
                # then fall back to the top-level for backwards compatibility.
                leagues = data.get("leagues") or []
                league0 = leagues[0] if leagues else {}
                calendar_start_date = (
                    data.get("calendarStartDate")
                    or league0.get("calendarStartDate")
                )
                calendar_end_date = (
                    data.get("calendarEndDate")
                    or league0.get("calendarEndDate")
                )
                # Rolling fallback (±240 days) when ESPN provides no dates:
                # avoids hard-coded windows that would cut off future matches
                # (e.g. MLS running through November).
                if not calendar_start_date or not calendar_end_date:
                    now = datetime.now()
                    calendar_start_date = (now - timedelta(days=240)).strftime("%Y-%m-%dT00:00Z")
                    calendar_end_date = (now + timedelta(days=240)).strftime("%Y-%m-%dT00:00Z")
                return calendar_start_date, calendar_end_date
        except asyncio.TimeoutError:
            self._log_calendar_fetch_issue(
                "timeout",
                "Calendar fetch timed out for %s (%s)",
                self._name,
                calendar_url,
            )
            return None, None
        except aiohttp.ClientResponseError as e:
            self._log_calendar_fetch_issue(
                f"http-{e.status}",
                "Calendar fetch failed for %s (%s): HTTP %s %s",
                self._name,
                calendar_url,
                e.status,
                e.message,
            )
            return None, None
        except aiohttp.ClientError as e:
            self._log_calendar_fetch_issue(
                type(e).__name__,
                "Calendar fetch failed for %s (%s): %s: %r",
                self._name,
                calendar_url,
                type(e).__name__,
                e,
            )
            return None, None
        except Exception:
            self._log_calendar_fetch_issue(
                "unexpected",
                "Unexpected error fetching calendar for %s (%s)",
                self._name,
                calendar_url,
                exc_info=True,
            )
            return None, None

    def _log_calendar_fetch_issue(self, reason, message, *args, exc_info=False):
        """Throttle repeated calendar warnings per competition/reason."""
        key = (self._code or self._name, reason)
        now = datetime.now()
        last = SoccerLiveSensor._calendar_error_logs.get(key)
        if last and (now - last).total_seconds() < 300:
            _LOGGER.debug(message, *args, exc_info=exc_info)
            return
        SoccerLiveSensor._calendar_error_logs[key] = now
        _LOGGER.warning(message, *args, exc_info=exc_info)


    def _parse_match_datetime(self, date_str):
        """Parse a match date string to a timezone-aware datetime."""
        if not isinstance(date_str, str):
            return None
        user_timezone = self.hass.config.time_zone
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo(user_timezone)
        for fmt in ("%d-%m-%Y %H:%M", "%d/%m/%Y %H:%M"):
            try:
                return datetime.strptime(date_str, fmt).replace(tzinfo=local_tz)
            except ValueError:
                continue
        return None

    def _detect_and_dispatch_goals(self, matches, events: list):
        live_matches = [m for m in matches if m.get("state") == "in"]
        for match in live_matches:
            match_id = match.get("event_id") or f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            home_score = match.get("home_score", 0)
            away_score = match.get("away_score", 0)
            try:
                home_score = int(home_score) if home_score != "N/A" else 0
                away_score = int(away_score) if away_score != "N/A" else 0
            except (ValueError, TypeError):
                home_score = 0
                away_score = 0
            if match_id not in self._previous_scores:
                self._previous_scores[match_id] = {
                    "home": home_score,
                    "away": away_score,
                    "match_details": match.get("match_details", []).copy()
                }
                continue
            prev_home = self._previous_scores[match_id]["home"]
            prev_away = self._previous_scores[match_id]["away"]
            prev_details = self._previous_scores[match_id].get("match_details", [])
            curr_details = match.get("match_details", [])
            if match_id not in self._dispatched_goal_details:
                self._dispatched_goal_details[match_id] = set()
            dispatched = self._dispatched_goal_details[match_id]

            home_abbrev = match.get("home_abbrev", "")
            away_abbrev = match.get("away_abbrev", "")

            if home_score > prev_home:
                goals_scored = home_score - prev_home
                home_strings = self._pick_goal_strings(curr_details, dispatched, home_abbrev, goals_scored)
                goal_scorers = self._extract_goal_scorers_from_details(home_strings, goals_scored)
                synthetic_key = f"h_{home_score}"
                if home_strings or synthetic_key not in dispatched:
                    self._dispatch_goal_event(match.get("home_team", "N/A"), match.get("away_team", "N/A"), goals_scored, home_score, away_score, match, goal_scorers, events)
                    dispatched.update(home_strings)
                    dispatched.add(synthetic_key)
            if away_score > prev_away:
                goals_scored = away_score - prev_away
                away_strings = self._pick_goal_strings(curr_details, dispatched, away_abbrev, goals_scored)
                goal_scorers = self._extract_goal_scorers_from_details(away_strings, goals_scored)
                synthetic_key = f"a_{away_score}"
                if away_strings or synthetic_key not in dispatched:
                    self._dispatch_goal_event(match.get("away_team", "N/A"), match.get("home_team", "N/A"), goals_scored, home_score, away_score, match, goal_scorers, events)
                    dispatched.update(away_strings)
                    dispatched.add(synthetic_key)
            self._previous_scores[match_id]["home"] = home_score
            self._previous_scores[match_id]["away"] = away_score
            self._previous_scores[match_id]["match_details"] = curr_details.copy()

    @staticmethod
    def _is_scored_goal_detail(d):
        """Whether a match-detail string represents a goal that changed the score.

        ESPN writes scored penalties as "Penalty - Scored", API-Football as
        "Goal - Penalty"; both must be attributable. Disallowed goals and missed
        penalties never changed the score and are excluded."""
        if "Disallowed" in d or "Missed" in d:
            return False
        return "Goal" in d or "Penalty - Scored" in d

    def _pick_goal_strings(self, curr_details, dispatched, team_abbrev, count):
        """Return up to `count` new goal strings for a team.
        Filters by [ABBREV] tag when available; falls back to positional order.
        Uses the most-recent strings ([-count:]) so a late-arriving string from a
        previous goal is not attributed to the next goal. Disallowed goals and
        missed penalties are excluded so they cannot pollute future attribution."""
        all_new = [d for d in curr_details if self._is_scored_goal_detail(d) and d not in dispatched]
        if team_abbrev:
            tagged = [d for d in all_new if f"[{team_abbrev}]" in d]
            if tagged:
                return tagged[-count:]
        return all_new[-count:]

    def _extract_goal_scorers_from_details(self, goal_strings, goals_count):
        """Parse player name and minute from pre-filtered goal detail strings.
        Return a list of dicts with {player, minute}."""
        new_goals = []
        for detail in goal_strings:
            # Format: "Goal - 38': Bryan Mbeumo"
            try:
                parts = detail.split("': ")
                if len(parts) == 2:
                    player_name = parts[1].strip()
                    minute = parts[0].split(" - ")[-1].strip() if " - " in parts[0] else "N/A"
                    new_goals.append({"player": player_name, "minute": minute})
            except Exception as e:
                _LOGGER.debug(f"Error extracting player name: {e}")
        return new_goals[:goals_count]

    def _dispatch_goal_event(self, scoring_team, opponent_team, goals_count, home_score, away_score, match, goal_scorers=None, events: list = None):
        """Build and collect a goal event."""
        try:
            # goal_scorers is a list of {player, minute} dicts.
            # Also accepts plain strings for backwards compatibility.
            first = goal_scorers[0] if goal_scorers and len(goal_scorers) > 0 else None
            if isinstance(first, dict):
                player_name = first.get("player", "N/A")
                minute = first.get("minute", "N/A")
            elif isinstance(first, str):
                player_name = first
                minute = "N/A"
            else:
                player_name = "N/A"
                minute = "N/A"

            players = [g.get("player") if isinstance(g, dict) else g for g in (goal_scorers or [])]

            event_data = {
                "team": scoring_team,
                "opponent": opponent_team,
                "goals_scored": goals_count,
                "player": player_name,
                "minute": minute,
                "players": players,
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": home_score,
                "away_score": away_score,
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "competition_code": self._code,
                "sensor_name": self._name,
            }
            if events is not None:
                events.append(("soccer_live_goal", event_data))
            _LOGGER.info(f"Goal detected: {scoring_team} scores (total: {goals_count}). Player: {player_name} ({minute}). Score: {home_score}-{away_score}")
        except Exception as e:
            _LOGGER.error(f"Error dispatching goal event: {e}")

    def _detect_and_dispatch_cards(self, matches, events: list):
        live_matches = [m for m in matches if m.get("state") == "in"]
        for match in live_matches:
            match_id = match.get("event_id") or f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            match_details = match.get("match_details", [])
            if match_id not in self._previous_match_details:
                self._previous_match_details[match_id] = match_details.copy()
                continue
            prev_details = self._previous_match_details[match_id]
            for detail in match_details:
                if detail not in prev_details:
                    if "Yellow Card" in detail:
                        self._dispatch_card_event("yellow", detail, match, events)
                    elif "Red Card" in detail:
                        self._dispatch_card_event("red", detail, match, events)
                    elif "Substitution" in detail:
                        self._dispatch_substitution_event(detail, match, events)
            self._previous_match_details[match_id] = match_details.copy()

    def _dispatch_card_event(self, card_type, detail_str, match, events: list = None):
        """Build and collect a card event."""
        try:
            # Parse: "Yellow Card [TOT] - 27': Destiny Udogie" or "Red Card - 29': Cristian Romero"
            parts = detail_str.split("': ")
            minute = parts[0].split(" - ")[1] if " - " in parts[0] else "N/A"
            player = parts[1] if len(parts) > 1 else "N/A"

            team_match = re.search(r'\[([^\]]+)\]', detail_str)
            team = team_match.group(1) if team_match else "N/A"

            event_type = f"soccer_live_{card_type}_card"
            event_data = {
                "card_type": card_type.upper(),
                "player": player,
                "minute": minute,
                "team": team,
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": match.get("home_score", "N/A"),
                "away_score": match.get("away_score", "N/A"),
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "competition_code": self._code,
                "sensor_name": self._name,
            }
            if events is not None:
                events.append((event_type, event_data))
            _LOGGER.info(f"Card detected: {card_type.upper()} at {minute} | {player}")
        except Exception as e:
            _LOGGER.error(f"Error dispatching card event: {e}")

    def _dispatch_substitution_event(self, detail_str, match, events: list = None):
        """Dispatch a substitution event."""
        try:
            parts = detail_str.split("': ")
            minute = parts[0].split(" - ")[1] if " - " in parts[0] else "N/A"
            player = parts[1] if len(parts) > 1 else "N/A"
            team_match = re.search(r'\[([^\]]+)\]', detail_str)
            team = team_match.group(1) if team_match else "N/A"
            event_data = {
                "player": player,
                "minute": minute,
                "team": team,
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": match.get("home_score", "N/A"),
                "away_score": match.get("away_score", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "competition_code": self._code,
                "sensor_name": self._name,
            }
            if events is not None:
                events.append(("soccer_live_substitution", event_data))
            _LOGGER.info(f"Substitution: {player} ({team}) at {minute}")
        except Exception as e:
            _LOGGER.error(f"Error dispatching substitution event: {e}")

    def _detect_and_dispatch_match_started(self, matches, events: list):
        """Dispatch an event when a match transitions from pre to in."""
        for match in matches:
            match_id = match.get("event_id") or f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            current_state = match.get("state")
            prev_state = self._previous_match_states.get(match_id)
            if current_state == "in" and prev_state == "pre":
                event_data = {
                    "event_id": match.get("event_id"),
                    "match_phase": "first_half",
                    "home_team": match.get("home_team", "N/A"),
                    "away_team": match.get("away_team", "N/A"),
                    "home_logo": match.get("home_logo", "N/A"),
                    "away_logo": match.get("away_logo", "N/A"),
                    "venue": match.get("venue", "N/A"),
                    "date": match.get("date", "N/A"),
                    "league_name": match.get("league_name", "N/A"),
                    "competition_code": self._code,
                    "sensor_name": self._name,
                }
                events.append(("soccer_live_match_started", event_data))
                _LOGGER.info(f"Match started: {match.get('home_team', 'N/A')} vs {match.get('away_team', 'N/A')}")
            if current_state:
                self._previous_match_states[match_id] = current_state

    def _detect_and_dispatch_halftime(self, matches, events: list):
        from .match_contract import match_phase
        for match in matches:
            match_id = str(match.get("event_id") or f"{match.get('home_team')}_{match.get('away_team')}")
            phase = match_phase(match)
            previous = self._previous_match_phases.get(match_id)
            if phase == "halftime" and previous is not None and previous != "halftime":
                events.append(("soccer_live_halftime", {
                    "event_id": match.get("event_id"),
                    "match_phase": phase,
                    "home_team": match.get("home_team"),
                    "away_team": match.get("away_team"),
                    "home_score": match.get("home_score"),
                    "away_score": match.get("away_score"),
                    "league_name": match.get("league_name"),
                    "competition_code": self._code,
                    "sensor_name": self._name,
                }))
            self._previous_match_phases[match_id] = phase

    def _detect_and_dispatch_match_finished(self, matches, events: list):
        finished_matches = [m for m in matches if m.get("state") == "post"]
        for match in finished_matches:
            match_id = match.get("event_id") or f"{match.get('home_team', 'N/A')}_{match.get('away_team', 'N/A')}"
            if match_id not in self._match_finished_dispatched:
                prev_state = self._previous_match_states.get(match_id)
                if prev_state is not None and prev_state != "post":
                    # Known in→post transition — fire the event
                    self._dispatch_match_finished_event(match, events)
                    _LOGGER.info(f"Match-finished event collected for: {match_id}")
                else:
                    # First poll already shows post: historical match, skip notification
                    _LOGGER.debug(f"Skipping match_finished for {match_id} (first seen already finished)")
                # Always mark dispatched to prevent firing again in future polls
                self._match_finished_dispatched.add(match_id)
                self._match_finished_list.append(match_id)
            self._previous_match_states[match_id] = "post"

    def _dispatch_match_finished_event(self, match, events: list = None):
        """Build and collect a match finished event."""
        try:
            # Extract goal scorers from match details
            goal_scorers = self._extract_all_goal_scorers(match.get("match_details", []))
            
            event_data = {
                "event_id": match.get("event_id"),
                "match_phase": "finished",
                "home_team": match.get("home_team", "N/A"),
                "away_team": match.get("away_team", "N/A"),
                "home_score": match.get("home_score", "N/A"),
                "away_score": match.get("away_score", "N/A"),
                "final_status": match.get("status", "N/A"),
                "venue": match.get("venue", "N/A"),
                "match_status": match.get("status", "N/A"),
                "date": match.get("date", "N/A"),
                "competition_code": self._code,
                "season_info": match.get("season_info", "N/A"),
                "league_name": match.get("league_name", "N/A"),
                "goal_scorers": goal_scorers,
                "goal_scorers_str": ", ".join(goal_scorers) if goal_scorers else "N/A",
                "sensor_name": self._name,
            }
            if events is not None:
                events.append(("soccer_live_match_finished", event_data))
            _LOGGER.info(f"Match finished: {match.get('home_team', 'N/A')} {match.get('home_score', '?')} - {match.get('away_score', '?')} {match.get('away_team', 'N/A')}. Scorers: {', '.join(goal_scorers)}")
        except Exception as e:
            _LOGGER.error(f"Error dispatching match finished event: {e}")

    def _extract_all_goal_scorers(self, match_details):
        """Extract all goal scorer names from match_details."""
        goal_scorers = []
        
        for detail in match_details:
            if "Goal" in detail and "Disallowed" not in detail:
                # Format: "Goal - 38': Bryan Mbeumo"
                try:
                    parts = detail.split("': ")
                    if len(parts) == 2:
                        player_name = parts[1].strip()
                        goal_scorers.append(player_name)
                except Exception as e:
                    _LOGGER.debug(f"Error extracting player name: {e}")
        
        return goal_scorers

    def _get_minutes_until(self, match_datetime):
        """Calculate minutes remaining until the match."""
        try:
            if not match_datetime:
                return None
            user_timezone = self.hass.config.time_zone
            from zoneinfo import ZoneInfo
            local_tz = ZoneInfo(user_timezone)
            now = datetime.now(local_tz)
            delta = match_datetime - now
            minutes = int(delta.total_seconds() / 60)
            return minutes
        except Exception as e:
            _LOGGER.debug(f"Error calculating minutes: {e}")
            return None

    def _compute_next_match_attributes(self, match):
        """Compute attributes for the next/current match."""
        if not match:
            return {}
        
        match_datetime = self._parse_match_datetime(match.get("date"))
        
        broadcasts = match.get("broadcasts") or []
        if not isinstance(broadcasts, list):
            broadcasts = [broadcasts] if broadcasts and broadcasts != "N/A" else []
        return {
            "next_match_home_team": match.get("home_team", "N/A"),
            "next_match_away_team": match.get("away_team", "N/A"),
            "next_match_home_abbrev": match.get("home_abbrev", "N/A"),
            "next_match_away_abbrev": match.get("away_abbrev", "N/A"),
            "next_match_home_logo": match.get("home_logo", "N/A"),
            "next_match_away_logo": match.get("away_logo", "N/A"),
            "next_match_home_color": match.get("home_color", "N/A"),
            "next_match_away_color": match.get("away_color", "N/A"),
            "home_color": match.get("home_color", "N/A"),
            "away_color": match.get("away_color", "N/A"),
            "team_colors": [
                color for color in (match.get("home_color"), match.get("away_color"))
                if color and color != "N/A"
            ],
            "next_match_home_score": match.get("home_score", "N/A"),
            "next_match_away_score": match.get("away_score", "N/A"),
            "next_match_date": match.get("date", "N/A"),
            "next_match_datetime_iso": match_datetime.isoformat() if match_datetime else "N/A",
            "next_match_minutes_until": self._get_minutes_until(match_datetime),
            "next_match_status": match.get("state", "N/A"),
            "next_match_description": match.get("status", "N/A"),
            "next_match_venue": match.get("venue", "N/A"),
            "next_match_period": match.get("period", "N/A"),
            "next_match_clock": match.get("clock", "N/A"),
            "next_match_home_form": match.get("home_form", "N/A"),
            "next_match_away_form": match.get("away_form", "N/A"),
            "next_match_season_info": match.get("season_info", "N/A"),
            "next_match_broadcasts": broadcasts,
            "next_match_attendance": match.get("attendance", "N/A"),
            "next_match_neutral_site": match.get("neutral_site", False),
            "next_match_has_stats": bool(match.get("has_stats") or match.get("home_statistics")),
            "next_match_has_commentary": bool(match.get("has_commentary") or match.get("key_events")),
            "next_match_event_id": match.get("event_id", "N/A"),
            "next_match_broadcast_count": len(broadcasts),
            "next_match_event_count": len(match.get("match_details") or []),
            "next_match_h2h_count": len(match.get("head_to_head") or []),
            "next_match_links": match.get("links") or [],
            "next_match_week": match.get("week_number", "N/A"),
        }

    def _compute_live_match_attributes(self, matches):
        """Compute attributes for the live match, if one exists."""
        live_matches = [m for m in matches if m.get("state") == "in"]
        if not live_matches:
            return {}
        
        match = live_matches[0]
        return {
            "live_match_home_team": match.get("home_team", "N/A"),
            "live_match_away_team": match.get("away_team", "N/A"),
            "live_match_home_abbrev": match.get("home_abbrev", "N/A"),
            "live_match_away_abbrev": match.get("away_abbrev", "N/A"),
            "live_match_home_logo": match.get("home_logo", "N/A"),
            "live_match_away_logo": match.get("away_logo", "N/A"),
            "live_match_home_color": match.get("home_color", "N/A"),
            "live_match_away_color": match.get("away_color", "N/A"),
            "home_color": match.get("home_color", "N/A"),
            "away_color": match.get("away_color", "N/A"),
            "team_colors": [
                color for color in (match.get("home_color"), match.get("away_color"))
                if color and color != "N/A"
            ],
            "live_match_home_score": match.get("home_score", "N/A"),
            "live_match_away_score": match.get("away_score", "N/A"),
            "live_match_date": match.get("date", "N/A"),
            "live_match_status": "in",
            "live_match_description": match.get("status", "N/A"),
            "live_match_venue": match.get("venue", "N/A"),
            "live_match_period": match.get("period", "N/A"),
            "live_match_clock": match.get("clock", "N/A"),
            "live_match_home_form": match.get("home_form", "N/A"),
            "live_match_away_form": match.get("away_form", "N/A"),
            "live_match_event_id": match.get("event_id", "N/A"),
            "live_match_event_count": len(match.get("match_details") or []),
            "live_match_h2h_count": len(match.get("head_to_head") or []),
        }

    def _compute_all_matches_attributes(self, matches, events: list = None, detect_events=True):
        if events is None:
            events = []
        if detect_events and self._sensor_type != "team_matches_mixed":
            self._detect_and_dispatch_goals(matches, events)
            self._detect_and_dispatch_cards(matches, events)
            self._detect_and_dispatch_match_finished(matches, events)
            self._detect_and_dispatch_match_started(matches, events)
        
        computed = {}
        
        # Info match in corso se esiste
        live_matches = [m for m in matches if m.get("state") == "in"]
        if live_matches:
            computed.update(self._compute_live_match_attributes(matches))
            computed["has_live_match"] = True
        else:
            computed["has_live_match"] = False
        
        # Upcoming match info
        upcoming_matches = [m for m in matches if m.get("state") == "pre"]
        if upcoming_matches:
            computed.update(self._compute_next_match_attributes(upcoming_matches[0]))
            computed["has_upcoming_match"] = True
        else:
            computed["has_upcoming_match"] = False
        
        # Most recent finished match (within recent_match_hours window)
        from .parsers.scoreboard import is_within_recent_window
        recent_finished_matches = [m for m in matches
            if m.get("state") == "post" and is_within_recent_window(m.get("date"), self._recent_match_hours)
        ]
        if recent_finished_matches:
            last_match = recent_finished_matches[-1]  # ESPN chronological: [-1] is most recent
            computed.update({
                "last_match_home_team": last_match.get("home_team", "N/A"),
                "last_match_away_team": last_match.get("away_team", "N/A"),
                "last_match_home_logo": last_match.get("home_logo", "N/A"),
                "last_match_away_logo": last_match.get("away_logo", "N/A"),
                "last_match_home_score": last_match.get("home_score", "N/A"),
                "last_match_away_score": last_match.get("away_score", "N/A"),
                "last_match_date": last_match.get("date", "N/A"),
                "last_match_venue": last_match.get("venue", "N/A"),
                "has_recent_match": True,
            })
        else:
            computed["has_recent_match"] = False
        
        # Conteggi
        computed["total_matches"] = len(matches)
        computed["live_matches_count"] = len(live_matches)
        computed["upcoming_matches_count"] = len(upcoming_matches)
        computed["finished_matches_count"] = len([m for m in matches if m.get("state") == "post"])
        computed.update(self._compute_schedule_summary(matches))
        
        return computed

    def _compute_schedule_summary(self, matches):
        """Return compact, deduplicated schedule slices for cards and automations."""
        unique_matches = []
        seen = set()
        for match in matches or []:
            key = match.get("event_id") or f"{match.get('date')}|{match.get('home_team')}|{match.get('away_team')}"
            if key in seen:
                continue
            seen.add(key)
            unique_matches.append(match)

        def sort_key(match):
            parsed = self._parse_match_datetime(match.get("date"))
            return parsed or datetime.max.replace(tzinfo=timezone.utc)

        unique_matches = sorted(unique_matches, key=sort_key)
        live = [m for m in unique_matches if m.get("state") == "in"]
        upcoming = [m for m in unique_matches if m.get("state") == "pre"]
        recent = [m for m in unique_matches if m.get("state") == "post"][-5:]

        def compact(match):
            item = {
                "event_id": match.get("event_id"),
                "date": match.get("date"),
                "state": match.get("state"),
                "clock": match.get("clock"),
                "home_team": match.get("home_team"),
                "home_abbrev": match.get("home_abbrev"),
                "home_logo": match.get("home_logo"),
                "home_color": match.get("home_color"),
                "home_score": match.get("home_score"),
                "away_team": match.get("away_team"),
                "away_abbrev": match.get("away_abbrev"),
                "away_logo": match.get("away_logo"),
                "away_color": match.get("away_color"),
                "away_score": match.get("away_score"),
                "venue": match.get("venue"),
                "league_name": match.get("league_name"),
                "league_logo": match.get("league_logo"),
                "season_info": match.get("season_info"),
                "broadcasts": match.get("broadcasts") or [],
            }
            for key in (
                "match_details",
                "key_events",
                "home_statistics",
                "away_statistics",
                "lineup_home",
                "lineup_away",
                "formation_home",
                "formation_away",
            ):
                value = match.get(key)
                if value:
                    item[key] = value
            return item

        return {
            "schedule_match_count": len(unique_matches),
            "schedule_live_count": len(live),
            "schedule_upcoming_count": len(upcoming),
            "schedule_recent_count": len(recent),
            "schedule_live_matches": [compact(m) for m in live[:5]],
            "schedule_upcoming_matches": [compact(m) for m in upcoming[:10]],
            "schedule_recent_matches": [compact(m) for m in list(reversed(recent))],
        }

    def _process_data(self, data) -> dict:
        """Parse provider data and return {"state": ..., "attributes": {...}, "events": [...]}.
        No mutations to self._state, self._attributes, or self._pending_events.
        The caller applies all returned values on the event loop.
        """
        events: list = []
        from .parsers.scoreboard import process_match_data, process_news_data
        if self._provider == PROVIDER_API_FOOTBALL:
            from .parsers.api_football import process_fixture_data

            if self._sensor_type == "standings":
                from .parsers.api_football import process_standings_data
                standings = process_standings_data(data)
                return {
                    "state": "Standings",
                    "attributes": {
                        **standings,
                        "competition_code": self._code,
                        "provider": PROVIDER_API_FOOTBALL,
                    },
                    "events": events,
                }

            if self._sensor_type == "top_scorers":
                from .parsers.api_football import process_scorers_data as process_api_football_scorers_data
                scorer_data = process_api_football_scorers_data(data)
                scorers = scorer_data.get("scorers", [])
                return {
                    "state": str(len(scorers)),
                    "attributes": {
                        **scorer_data,
                        "competition_code": self._code,
                        "provider": PROVIDER_API_FOOTBALL,
                    },
                    "events": events,
                }

            def get_team_match_data(next_match_only=False):
                return process_fixture_data(
                    data,
                    self.hass,
                    team_name=self._team_name,
                    team_id=self._team_id,
                    include_friendlies=self._include_friendlies,
                )

            if self._sensor_type in ["team_matches", "team_matches_mixed", "all_matches_today", "match_day"]:
                from .parsers.scoreboard import is_within_recent_window
                match_data = get_team_match_data()
                matches = match_data.get("matches", []) or []
                _live = [m for m in matches if m.get("state") == "in"]
                _recent_post = [m for m in matches
                    if m.get("state") == "post" and is_within_recent_window(m.get("date"), self._recent_match_hours)]
                _upcoming = [m for m in matches if m.get("state") == "pre"]
                if _live:
                    next_match = _live[0]
                elif _recent_post:
                    next_match = _recent_post[-1]
                elif _upcoming:
                    next_match = _upcoming[0]
                else:
                    next_match = matches[-1] if matches else None

                live_matches = [m for m in matches if m.get("state") == "in"]
                if live_matches:
                    lm = live_matches[0]
                    state = f"🔴 {lm.get('home_team','?')} {lm.get('home_score','?')} - {lm.get('away_score','?')} {lm.get('away_team','?')} ({lm.get('clock','')})"
                elif matches:
                    finished_matches = [m for m in matches if m.get("state") == "post"]
                    if finished_matches:
                        fm = finished_matches[-1]
                        state = f"✅ {fm.get('home_team','?')} {fm.get('home_score','?')} - {fm.get('away_score','?')} {fm.get('away_team','?')}"
                    else:
                        um = _upcoming[0] if _upcoming else matches[0]
                        state = f"⏳ {um.get('home_team','?')} vs {um.get('away_team','?')} ({um.get('date','?')})"
                else:
                    state = "No matches available"

                detect_now = not (self._sensor_type == "team_matches" and self._enable_summary_enrichment)
                computed_attrs = self._compute_all_matches_attributes(matches, events, detect_events=detect_now)
                return {
                    "state": state,
                    "attributes": {
                        "league_info": match_data.get("league_info", []),
                        "team_name": match_data.get("team_name", "N/A"),
                        "team_logo": match_data.get("team_logo", "N/A"),
                        "matches": matches,
                        "next_match": next_match,
                        "provider": PROVIDER_API_FOOTBALL,
                        "friendlies_included": self._include_friendlies,
                        **computed_attrs,
                    },
                    "events": events,
                }

            if self._sensor_type == "team_match":
                all_data = get_team_match_data()
                all_matches = all_data.get("matches", []) or []
                if not self._enable_summary_enrichment:
                    self._detect_and_dispatch_goals(all_matches, events)
                    self._detect_and_dispatch_cards(all_matches, events)
                    self._detect_and_dispatch_match_finished(all_matches, events)
                    self._detect_and_dispatch_match_started(all_matches, events)

                from .parsers.scoreboard import is_within_recent_window
                _live = [m for m in all_matches if m.get("state") == "in"]
                _recent_post = [m for m in all_matches
                    if m.get("state") == "post" and is_within_recent_window(m.get("date"), self._recent_match_hours)]
                _upcoming = [m for m in all_matches if m.get("state") == "pre"]
                if _live:
                    next_match = _live[0]
                elif _recent_post:
                    next_match = _recent_post[-1]
                elif _upcoming:
                    next_match = _upcoming[0]
                else:
                    next_match = None

                if next_match:
                    if next_match.get("state") == "in":
                        state = f"{next_match.get('home_score','?')} - {next_match.get('away_score','?')} ({next_match.get('clock','')})"
                    elif next_match.get("state") == "post":
                        state = f"Last match: {next_match.get('home_team','N/A')} {next_match.get('home_score','?')} - {next_match.get('away_score','?')} {next_match.get('away_team','N/A')}"
                    else:
                        state = f"Next match: {next_match.get('home_team','N/A')} vs {next_match.get('away_team','N/A')}"
                else:
                    state = "No matches available"

                finished_matches = [m for m in all_matches if m.get("state") == "post"]
                previous_matches = [
                    {
                        "date": m.get("date"),
                        "home_team": m.get("home_team"),
                        "home_abbrev": m.get("home_abbrev"),
                        "home_logo": m.get("home_logo"),
                        "home_color": m.get("home_color"),
                        "home_score": m.get("home_score"),
                        "away_team": m.get("away_team"),
                        "away_abbrev": m.get("away_abbrev"),
                        "away_logo": m.get("away_logo"),
                        "away_color": m.get("away_color"),
                        "away_score": m.get("away_score"),
                        "state": m.get("state"),
                        "league_name": m.get("league_name", ""),
                        "season_info": m.get("season_info", ""),
                    }
                    for m in list(reversed(finished_matches))[:10]
                ]
                pre_in_matches = [m for m in all_matches if m.get("state") in ("pre", "in")]
                skip = 1 if next_match and next_match.get("state") in ("pre", "in") else 0
                upcoming_matches = [
                    {
                        "date": m.get("date"),
                        "state": m.get("state"),
                        "home_team": m.get("home_team"),
                        "home_abbrev": m.get("home_abbrev"),
                        "home_logo": m.get("home_logo"),
                        "home_color": m.get("home_color"),
                        "home_score": m.get("home_score"),
                        "away_team": m.get("away_team"),
                        "away_abbrev": m.get("away_abbrev"),
                        "away_logo": m.get("away_logo"),
                        "away_color": m.get("away_color"),
                        "away_score": m.get("away_score"),
                        "clock": m.get("clock"),
                        "head_to_head": (m.get("head_to_head") or [])[:3],
                        "event_id": m.get("event_id"),
                        "home_form": m.get("home_form", ""),
                        "away_form": m.get("away_form", ""),
                        "league_name": m.get("league_name", ""),
                    }
                    for m in pre_in_matches[skip:skip + 4]
                ]
                computed_attrs = self._compute_next_match_attributes(next_match) if next_match else {}
                return {
                    "state": state,
                    "attributes": {
                        **all_data,
                        "matches": [next_match] if next_match else [],
                        "next_match": next_match,
                        "upcoming_matches": upcoming_matches,
                        "previous_matches": previous_matches,
                        "provider": PROVIDER_API_FOOTBALL,
                        "friendlies_included": self._include_friendlies,
                        **computed_attrs,
                    },
                    "events": events,
                }

            return {
                "state": "Unsupported by API-Football provider",
                "attributes": {"provider": PROVIDER_API_FOOTBALL, "matches": []},
                "events": events,
            }

        if self._sensor_type == "news":
            articles = process_news_data(data)
            count = len(articles)
            return {
                "state": f"{count} articles" if count else "No articles",
                "attributes": {
                    "articles": articles,
                    "competition_code": self._code,
                    "league_name": self._name or self._code or "",
                    "league_logo": "",
                },
            }

        if self._sensor_type == "top_scorers":
            from .parsers.scoreboard import process_scorers_data
            scorers = process_scorers_data(data)
            top_leagues = data.get("sports", [{}])[0].get("leagues", [{}]) if data.get("sports") else []
            league_name = top_leagues[0].get("name", "") if top_leagues else ""
            league_logo = (top_leagues[0].get("logos", [{}])[0].get("href", "") if top_leagues and top_leagues[0].get("logos") else "")
            return {
                "state": str(len(scorers)),
                "attributes": {
                    "scorers": scorers,
                    "league_name": league_name,
                    "league_logo": league_logo,
                    "competition_code": self._code,
                },
            }

        if self._sensor_type == "bracket":
            from .parsers.bracket import process_bracket_data
            from .parsers.scoreboard import process_league_data
            bracket = process_bracket_data(data)
            rounds = bracket.get("rounds", [])
            if rounds:
                last = rounds[-1]
                state = f"{last.get('name')} ({last.get('size')} teams)"
            else:
                state = "Bracket unavailable"
            league_info = process_league_data(data, self.hass)
            league_logo = (league_info[0].get("logo_href", "") if league_info else "")
            league_name = (league_info[0].get("name", "") if league_info else "")
            return {
                "state": state,
                "attributes": {
                    "rounds": rounds,
                    "ties_count": bracket.get("ties_count", 0),
                    "competition_code": self._code,
                    "league_logo": league_logo,
                    "league_name": league_name,
                },
            }

        if self._sensor_type == "standings":
            from .parsers.standings import standings_data
            return {"state": "Standings", "attributes": standings_data(data)}

        if self._sensor_type == "match_day":
            match_data = process_match_data(data, self.hass, start_date=self._filter_start_str(), end_date=self._filter_end_str())
            league_info = match_data.get("league_info") or []
            league_logo = (league_info[0].get("logo_href", "") if league_info else "")
            return {
                "state": "Match day",
                "attributes": {
                    "league_info": league_info,
                    "league_logo": league_logo,
                    "matches": match_data.get("matches", []),
                },
            }

        if self._sensor_type in ["team_matches", "team_match", "team_matches_mixed", "all_matches_today"]:
            def get_team_match_data(next_match_only=False):
                return process_match_data(
                    data,
                    self.hass,
                    team_name=self._team_name,
                    team_id=self._team_id,
                    next_match_only=next_match_only,
                    start_date=self._filter_start_str(),
                    end_date=self._filter_end_str(),
                    recent_match_hours=self._recent_match_hours,
                )

            if self._sensor_type in ["team_matches", "team_matches_mixed", "all_matches_today"]:
                from .parsers.scoreboard import is_within_recent_window
                match_data = get_team_match_data()
                matches = match_data.get("matches", []) or []
                _live = [m for m in matches if m.get("state") == "in"]
                _recent_post = [m for m in matches
                    if m.get("state") == "post" and is_within_recent_window(m.get("date"), self._recent_match_hours)]
                _upcoming = [m for m in matches if m.get("state") == "pre"]
                if _live:
                    next_match = _live[0]
                elif _recent_post:
                    next_match = _recent_post[-1]
                elif _upcoming:
                    next_match = _upcoming[0]
                else:
                    next_match = matches[-1] if matches else None

                live_matches = [m for m in matches if m.get("state") == "in"]
                if live_matches:
                    lm = live_matches[0]
                    state = f"🔴 {lm.get('home_team','?')} {lm.get('home_score','?')} - {lm.get('away_score','?')} {lm.get('away_team','?')} ({lm.get('clock','')})"
                elif matches:
                    finished_matches = [m for m in matches if m.get("state") == "post"]
                    if finished_matches:
                        fm = finished_matches[-1]
                        state = f"✅ {fm.get('home_team','?')} {fm.get('home_score','?')} - {fm.get('away_score','?')} {fm.get('away_team','?')}"
                    else:
                        upcoming_matches = [m for m in matches if m.get("state") == "pre"]
                        if upcoming_matches:
                            um = upcoming_matches[0]
                            state = f"⏳ {um.get('home_team','?')} vs {um.get('away_team','?')} ({um.get('date','?')})"
                        else:
                            state = f"📊 {len(matches)} matches available"
                else:
                    state = "No matches available"

                computed_attrs = self._compute_all_matches_attributes(matches, events)
                return {
                    "state": state,
                    "attributes": {
                        "league_info": match_data.get("league_info", "N/A"),
                        "team_name": match_data.get("team_name", "N/A"),
                        "team_logo": match_data.get("team_logo", "N/A"),
                        "matches": matches,
                        "next_match": next_match,
                        **computed_attrs,
                    },
                    "events": events,
                }

            # team_match — detects events to keep its own last_event attributes current,
            # but _flush_pending_events skips bus.fire/notifications for team_match so
            # the paired team_matches sensor remains the sole source of HA events.
            all_data = get_team_match_data()
            all_matches = all_data.get("matches", []) or []
            self._detect_and_dispatch_goals(all_matches, events)
            self._detect_and_dispatch_cards(all_matches, events)
            self._detect_and_dispatch_match_finished(all_matches, events)
            self._detect_and_dispatch_match_started(all_matches, events)

            from .parsers.scoreboard import is_within_recent_window
            _live = [m for m in all_matches if m.get("state") == "in"]
            _recent_post = [m for m in all_matches
                if m.get("state") == "post" and is_within_recent_window(m.get("date"), self._recent_match_hours)]
            _upcoming = [m for m in all_matches if m.get("state") == "pre"]

            if _live:
                next_match = _live[0]
            elif _recent_post:
                next_match = _recent_post[-1]
            elif _upcoming:
                next_match = _upcoming[0]
            else:
                next_match = None

            if next_match:
                if next_match.get("state") == "in":
                    state = f"{next_match.get('home_score','?')} - {next_match.get('away_score','?')} ({next_match.get('clock','')})"
                elif next_match.get("state") == "post":
                    state = f"Last match: {next_match.get('home_team','N/A')} {next_match.get('home_score','?')} - {next_match.get('away_score','?')} {next_match.get('away_team','N/A')}"
                else:
                    state = f"Next match: {next_match.get('home_team','N/A')} vs {next_match.get('away_team','N/A')}"
            else:
                state = "No matches available"

            finished_matches = [m for m in all_matches if m.get("state") == "post"]
            previous_matches = [
                {
                    "date": m.get("date"),
                    "home_team": m.get("home_team"),
                    "home_abbrev": m.get("home_abbrev"),
                    "home_logo": m.get("home_logo"),
                    "home_color": m.get("home_color"),
                    "home_score": m.get("home_score"),
                    "away_team": m.get("away_team"),
                    "away_abbrev": m.get("away_abbrev"),
                    "away_logo": m.get("away_logo"),
                    "away_color": m.get("away_color"),
                    "away_score": m.get("away_score"),
                    "state": m.get("state"),
                    "league_name": m.get("league_name", ""),
                    "season_info": m.get("season_info", ""),
                }
                for m in list(reversed(finished_matches))[:10]
            ]
            pre_in_matches = [m for m in all_matches if m.get("state") in ("pre", "in")]
            # Skip the first entry only when next_match itself is pre/in (it is shown separately).
            # When next_match is a recently finished match, the first pre/in is genuinely upcoming.
            skip = 1 if next_match and next_match.get("state") in ("pre", "in") else 0
            upcoming_candidates = pre_in_matches[skip:skip + 4]
            upcoming_matches = [
                {
                    "date": m.get("date"),
                    "state": m.get("state"),
                    "home_team": m.get("home_team"),
                    "home_abbrev": m.get("home_abbrev"),
                    "home_logo": m.get("home_logo"),
                    "home_color": m.get("home_color"),
                    "home_score": m.get("home_score"),
                    "away_team": m.get("away_team"),
                    "away_abbrev": m.get("away_abbrev"),
                    "away_logo": m.get("away_logo"),
                    "away_color": m.get("away_color"),
                    "away_score": m.get("away_score"),
                    "clock": m.get("clock"),
                    "head_to_head": (m.get("head_to_head") or [])[:3],
                    "event_id": m.get("event_id"),
                    "home_form": m.get("home_form", ""),
                    "away_form": m.get("away_form", ""),
                    "league_name": m.get("league_name", ""),
                }
                for m in upcoming_candidates
            ]
            computed_attrs = self._compute_next_match_attributes(next_match) if next_match else {}
            return {
                "state": state,
                "attributes": {
                    **all_data,
                    "matches": [next_match] if next_match else [],
                    "next_match": next_match,
                    "upcoming_matches": upcoming_matches,
                    "previous_matches": previous_matches,
                    **computed_attrs,
                },
                "events": events,
            }

        return {"state": "", "attributes": {}, "events": events}
