import asyncio
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
import aiohttp
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from homeassistant.helpers.selector import SelectSelector, SelectSelectorConfig
from .const import (
    CONF_API_FOOTBALL_KEY,
    CONF_API_FOOTBALL_SEASON,
    CONF_INCLUDE_FRIENDLIES,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_PROVIDER,
    DOMAIN,
    PROVIDER_API_FOOTBALL,
    PROVIDER_ESPN,
    provider_supports,
)
from .data import parse_competitions, parse_teams

_LOGGER = logging.getLogger(__name__)

FOLLOW_TEAM = "team"
FOLLOW_LEAGUE = "league"
FOLLOW_MANUAL = "manual"
FOLLOW_ALL_TODAY = "all_today"
FOLLOW_NEWS = "news"
TEAM_METHOD_SEARCH = "search"
TEAM_METHOD_LEAGUE = "league"

LEGACY_FOLLOW_SELECTIONS = {
    "team": FOLLOW_TEAM,
    "league": FOLLOW_LEAGUE,
    "manual entry": FOLLOW_MANUAL,
    "all matches today": FOLLOW_ALL_TODAY,
    "news": FOLLOW_NEWS,
}


def _normalize_follow_selection(value):
    return LEGACY_FOLLOW_SELECTIONS.get(str(value or "").strip().lower(), str(value or "").strip().lower())


def _normalize_provider(provider):
    value = str(provider or PROVIDER_ESPN).strip().lower()
    if value in {PROVIDER_API_FOOTBALL, "api-football", "api football"}:
        return PROVIDER_API_FOOTBALL
    return PROVIDER_ESPN


async def async_validate_api_football_key(hass, api_key):
    """Return True if API-Football accepts the key.

    Rejects only on a clear invalid-credentials signal (HTTP 401/403 or an
    ``errors.token`` in the body). On transient problems (timeout, 5xx, network
    error) it returns True so a temporary outage cannot block setup or a key
    change. Shared by initial setup, reauth and the options "change key" field.
    """
    try:
        session = async_get_clientsession(hass)
        async with session.get(
            "https://v3.football.api-sports.io/status",
            headers={"x-apisports-key": api_key},
            timeout=aiohttp.ClientTimeout(total=10),
        ) as response:
            if response.status in (401, 403):
                return False
            if response.status != 200:
                return True
            data = await response.json()
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        _LOGGER.warning("Could not validate API-Football key (network issue): %s", repr(e))
        return True
    errors = data.get("errors") if isinstance(data, dict) else None
    if isinstance(errors, dict) and errors.get("token"):
        return False
    return True


@config_entries.HANDLERS.register(DOMAIN)
class SoccerLiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._errors = {}
        self._data = {}
        self._teams = []
        self._reauth_entry = None

    async def async_step_user(self, user_input=None):
        """Step 1 — choose the data source only.

        Provider-specific fields (API-Football key/season/friendlies) are asked
        in a dedicated follow-up step, so ESPN users never see options that
        don't apply to them.
        """
        self._errors = {}

        if user_input is not None:
            provider = _normalize_provider(user_input.get(CONF_PROVIDER, PROVIDER_ESPN))
            self._data[CONF_PROVIDER] = provider
            if provider == PROVIDER_API_FOOTBALL:
                return await self.async_step_api_football_credentials()
            # ESPN is key-less; keep the friendlies default without prompting.
            self._data.setdefault(CONF_INCLUDE_FRIENDLIES, True)
            return await self.async_step_follow()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PROVIDER, default=PROVIDER_ESPN): SelectSelector(
                    SelectSelectorConfig(
                        options=[PROVIDER_ESPN, PROVIDER_API_FOOTBALL],
                        translation_key="provider_source",
                    )
                ),
            }),
            errors=self._errors,
        )

    async def async_step_reauth(self, entry_data):
        """Start reauth (triggered when API-Football rejects the stored key)."""
        self._reauth_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input=None):
        """Ask for a replacement API-Football key and update the entry in place,
        so a expired/revoked key can be fixed without deleting the config."""
        self._errors = {}
        entry = self._reauth_entry

        if user_input is not None:
            api_key = (user_input.get(CONF_API_FOOTBALL_KEY) or "").strip()
            if not api_key:
                self._errors[CONF_API_FOOTBALL_KEY] = "api_key_required"
            elif not await async_validate_api_football_key(self.hass, api_key):
                self._errors[CONF_API_FOOTBALL_KEY] = "invalid_api_key"
            if not self._errors:
                return self.async_update_reload_and_abort(
                    entry,
                    data={**entry.data, CONF_API_FOOTBALL_KEY: api_key},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({
                vol.Required(CONF_API_FOOTBALL_KEY): str,
            }),
            description_placeholders={"name": entry.title if entry else "Soccer Live"},
            errors=self._errors,
        )

    async def async_step_api_football_credentials(self, user_input=None):
        """Step 1b (API-Football only) — API key, season and friendlies.

        Asked before the selection/search steps because searching teams and
        competitions on API-Football needs the key.
        """
        self._errors = {}

        if user_input is not None:
            api_key = (user_input.get(CONF_API_FOOTBALL_KEY) or "").strip()
            if not api_key:
                self._errors[CONF_API_FOOTBALL_KEY] = "api_key_required"
            elif not await self._validate_api_football_key(api_key):
                self._errors[CONF_API_FOOTBALL_KEY] = "invalid_api_key"
            if not self._errors:
                self._data[CONF_API_FOOTBALL_KEY] = api_key
                self._data[CONF_API_FOOTBALL_SEASON] = user_input.get(CONF_API_FOOTBALL_SEASON) or 0
                self._data[CONF_INCLUDE_FRIENDLIES] = user_input.get(CONF_INCLUDE_FRIENDLIES, True)
                return await self.async_step_follow()

        return self.async_show_form(
            step_id="api_football_credentials",
            data_schema=vol.Schema({
                vol.Required(CONF_API_FOOTBALL_KEY, default=self._data.get(CONF_API_FOOTBALL_KEY, "")): str,
                vol.Optional(CONF_API_FOOTBALL_SEASON, default=self._data.get(CONF_API_FOOTBALL_SEASON, 0)): vol.Coerce(int),
                vol.Optional(CONF_INCLUDE_FRIENDLIES, default=self._data.get(CONF_INCLUDE_FRIENDLIES, True)): bool,
            }),
            errors=self._errors,
        )

    async def async_step_follow(self, user_input=None):
        """Step 2 — choose what to follow, with only the options the selected
        provider supports (e.g. News is ESPN-only, so it isn't offered for
        API-Football instead of failing after submit). Team is the default."""
        self._errors = {}
        provider = _normalize_provider(self._data.get(CONF_PROVIDER))

        if user_input is not None:
            selection = _normalize_follow_selection(user_input.get("selection"))
            # Defensive guard in case a client submits a filtered-out combo.
            if provider == PROVIDER_API_FOOTBALL and selection == FOLLOW_NEWS:
                self._errors["selection"] = "unsupported_provider_selection"
            else:
                self._data["selection"] = selection
                if selection == FOLLOW_LEAGUE:
                    return await self.async_step_league()
                if selection == FOLLOW_TEAM:
                    if provider == PROVIDER_API_FOOTBALL:
                        return await self.async_step_api_football_team_search()
                    return await self.async_step_select_competition_for_team()
                if selection == FOLLOW_ALL_TODAY:
                    self._data["competition_code"] = "99999"  # Dummy code for the "all matches today" sensor
                    return self.async_create_entry(
                        title="All matches today",
                        data=self._data,
                    )
                if selection == FOLLOW_NEWS:
                    return await self.async_step_news_competition()
                if selection == FOLLOW_MANUAL:
                    return await self.async_step_manual_team()

        # Team first so it is the default; News only for providers that supply it.
        selections = [FOLLOW_TEAM, FOLLOW_LEAGUE, FOLLOW_ALL_TODAY]
        if provider_supports(provider, "news"):
            selections.append(FOLLOW_NEWS)
        selections.append(FOLLOW_MANUAL)

        return self.async_show_form(
            step_id="follow",
            data_schema=vol.Schema({
                vol.Required("selection", default=FOLLOW_TEAM): SelectSelector(
                    SelectSelectorConfig(
                        options=selections,
                        translation_key="follow_selection",
                    )
                ),
            }),
            errors=self._errors,
        )

    async def async_step_api_football_team_method(self, user_input=None):
        if user_input is not None:
            method = user_input.get("team_method")
            if method == TEAM_METHOD_SEARCH:
                return await self.async_step_api_football_team_search()
            return await self.async_step_select_competition_for_team()

        return self.async_show_form(
            step_id="api_football_team_method",
            data_schema=vol.Schema({
                vol.Required("team_method", default=TEAM_METHOD_SEARCH): SelectSelector(
                    SelectSelectorConfig(
                        options=[TEAM_METHOD_SEARCH, TEAM_METHOD_LEAGUE],
                        translation_key="api_football_team_method",
                    )
                ),
            }),
            errors=self._errors,
        )

    async def async_step_api_football_team_search(self, user_input=None):
        self._errors = {}
        if user_input is not None:
            search = (user_input.get("team_search") or "").strip()
            if len(search) < 3:
                self._errors["team_search"] = "search_too_short"
            else:
                self._teams = await self._search_api_football_teams(search)
                if not self._teams:
                    self._errors["team_search"] = "no_search_results"
                else:
                    return await self.async_step_team()

        return self.async_show_form(
            step_id="api_football_team_search",
            data_schema=vol.Schema({
                vol.Required("team_search"): str,
            }),
            errors=self._errors,
        )

    async def async_step_news_competition(self, user_input=None):
        if user_input is not None:
            competition_code = user_input.get("competition_code")
            competition_name = await self._get_competition_name(competition_code)
            self._data.update({
                "competition_code": competition_code,
                "name": f"News {competition_name}",
                "selection": "News",
            })
            return self.async_create_entry(
                title=f"News {competition_name}",
                data=self._data,
            )

        competitions = await self._get_competitions()
        sorted_competitions = {k: v for k, v in sorted(competitions.items(), key=lambda item: item[1])}
        if not sorted_competitions:
            return self.async_abort(reason="no_competitions")
        return self.async_show_form(
            step_id="news_competition",
            data_schema=vol.Schema({
                vol.Required("competition_code"): vol.In(sorted_competitions),
            }),
            errors=self._errors,
        )

    async def async_step_league(self, user_input=None):
        if user_input is not None:
            competition_code = user_input.get("competition_code")
            competition_name = await self._get_competition_name(competition_code)
            self._data.update({"competition_code": competition_code, "name": competition_name})

            # Calendar dates are now resolved dynamically by the sensor on each
            # update via _get_calendar_data, so the user is no longer prompted.
            return self.async_create_entry(
                title=self._data.get("name", "Soccer Live"),
                data=self._data,
            )

        competitions = await self._get_competitions()
        sorted_competitions = {k: v for k, v in sorted(competitions.items(), key=lambda item: item[1])}
        if not sorted_competitions:
            return self.async_abort(reason="no_competitions")
        return self.async_show_form(
            step_id="league",
            data_schema=vol.Schema({
                vol.Required("competition_code"): vol.In(sorted_competitions),
            }),
            errors=self._errors,
        )

    async def async_step_select_competition_for_team(self, user_input=None):
        if user_input is not None:
            competition_code = user_input.get("competition_code")
            self._data.update({"competition_code": competition_code})

            await self._get_teams(competition_code)
            return await self.async_step_team()

        competitions = await self._get_competitions()
        sorted_competitions = {k: v for k, v in sorted(competitions.items(), key=lambda item: item[1])}
        if not sorted_competitions:
            return self.async_abort(reason="no_competitions")
        return self.async_show_form(
            step_id="select_competition_for_team",
            data_schema=vol.Schema({
                vol.Required("competition_code"): vol.In(sorted_competitions),
            }),
            errors=self._errors,
        )

    async def async_step_team(self, user_input=None):
        if user_input is not None:
            team_name = user_input["team_name"]
            competition_code = self._data.get("competition_code", "N/A")
            competition_name = await self._get_competition_name(competition_code)

            # Find the team ID for the selected team name
            selected_team = next((team for team in self._teams if team.get("label") == team_name or team.get("displayName") == team_name), None)
            team_id = selected_team["id"] if selected_team else None
            display_name = selected_team.get("displayName", team_name) if selected_team else team_name

            # Store team_id and team_name
            self._data.update({"team_name": display_name, "team_id": team_id, "name": f"Team {competition_name} {display_name}"})

            # Season dates are resolved dynamically by the sensor — no prompt needed.
            return self.async_create_entry(
                title=self._data.get("name", "Soccer Live"),
                data=self._data,
            )

        team_options = {
            team.get("label", team["displayName"]): team.get("label", team["displayName"])
            for team in sorted(self._teams, key=lambda t: t["displayName"])
        }
        if not team_options:
            return self.async_abort(reason="no_teams")

        return self.async_show_form(
            step_id="team",
            data_schema=vol.Schema({
                vol.Required("team_name"): vol.In(team_options),
            }),
            errors=self._errors,
        )

    async def async_step_manual_team(self, user_input=None):
        if user_input is not None:
            team_id = user_input["manual_team_id"]
            competition_code = self._data.get("competition_code", "N/A")
            if competition_code and competition_code != "N/A":
                competition_name = await self._get_competition_name(competition_code)
            else:
                competition_name = "Vrije invoer"
            display_name_input = user_input.get("name", "")
            display_name_normalized = display_name_input.replace(" ", "_").lower()

            display_name = display_name_input if display_name_input else team_id
            self._data.update({
                "team_id": team_id,
                "team_name": display_name,
                "name": f"Team {competition_name} {team_id} {display_name_normalized}",
            })

            # Season dates are resolved dynamically by the sensor — no prompt needed.
            return self.async_create_entry(
                title=self._data.get("name", "Soccer Live"),
                data=self._data,
            )

        return self.async_show_form(
            step_id="manual_team",
            data_schema=vol.Schema({
                vol.Required("manual_team_id"): str,
                vol.Optional("name", default=""): str,
            }),
            errors=self._errors,
        )



    async def _get_competitions(self):
        if _normalize_provider(self._data.get(CONF_PROVIDER)) == PROVIDER_API_FOOTBALL:
            return await self._get_api_football_competitions()

        url = "https://site.api.espn.com/apis/site/v2/leagues/dropdown?lang=en&region=us&calendartype=whitelist&limit=200&sport=soccer"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                competitions_data = await response.json()
                return parse_competitions(competitions_data)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Error loading competitions: %s", repr(e))
            return {}

    async def _get_competition_name(self, competition_code):
        """Return the competition display name for the given competition code."""
        competitions = await self._get_competitions()
        return competitions.get(str(competition_code), "Unknown competition")

    async def _get_teams(self, competition_code):
        if _normalize_provider(self._data.get(CONF_PROVIDER)) == PROVIDER_API_FOOTBALL:
            self._teams = await self._get_api_football_teams(competition_code)
            return

        url = f"https://site.api.espn.com/apis/site/v2/sports/soccer/{competition_code}/teams"
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                response.raise_for_status()
                teams_data = await response.json()
                self._teams = parse_teams(teams_data)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Error loading teams for %s: %s", competition_code, repr(e))
            self._teams = []

    async def _validate_api_football_key(self, api_key):
        """Return True if API-Football accepts the key (see the module helper)."""
        return await async_validate_api_football_key(self.hass, api_key)

    async def _get_api_football_json(self, path, params=None):
        api_key = self._data.get(CONF_API_FOOTBALL_KEY, "")
        if not api_key:
            return {}
        try:
            session = async_get_clientsession(self.hass)
            async with session.get(
                f"https://v3.football.api-sports.io/{path}",
                headers={"x-apisports-key": api_key},
                params=params or {},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as response:
                response.raise_for_status()
                return await response.json()
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            _LOGGER.error("Error loading API-Football %s: %s", path, repr(e))
            return {}

    async def _get_api_football_competitions(self):
        season = self._api_football_config_season()
        data = await self._get_api_football_json("leagues", {"season": season})
        competitions = {}
        for item in data.get("response", []) or []:
            league = item.get("league") if isinstance(item, dict) else {}
            country = item.get("country") if isinstance(item, dict) else {}
            if not isinstance(league, dict):
                continue
            league_id = league.get("id")
            if not league_id:
                continue
            country_name = country.get("name") if isinstance(country, dict) else ""
            label = f"{league.get('name', str(league_id))} #{league_id}"
            if country_name:
                label = f"{label} ({country_name})"
            competitions[str(league_id)] = label
        return competitions

    async def _get_api_football_teams(self, competition_code):
        season = self._api_football_config_season()
        data = await self._get_api_football_json(
            "teams",
            {"league": competition_code, "season": season},
        )
        teams = []
        for item in data.get("response", []) or []:
            team = item.get("team") if isinstance(item, dict) else {}
            if not isinstance(team, dict):
                continue
            team_id = team.get("id")
            name = team.get("name")
            if team_id and name:
                country = team.get("country", "")
                label = f"{name} #{team_id}"
                if country:
                    label = f"{label} ({country})"
                teams.append({"id": str(team_id), "displayName": name, "label": label})
        return teams

    async def _search_api_football_teams(self, search):
        data = await self._get_api_football_json("teams", {"search": search})
        teams = []
        for item in data.get("response", []) or []:
            team = item.get("team") if isinstance(item, dict) else {}
            venue = item.get("venue") if isinstance(item, dict) else {}
            if not isinstance(team, dict):
                continue
            team_id = team.get("id")
            name = team.get("name")
            if not team_id or not name:
                continue
            country = team.get("country", "")
            venue_name = venue.get("name") if isinstance(venue, dict) else ""
            label = f"{name} #{team_id}"
            if country:
                label = f"{label} ({country})"
            if venue_name:
                label = f"{label} - {venue_name}"
            teams.append({"id": str(team_id), "displayName": name, "label": label})
        return teams

    def _api_football_config_season(self):
        try:
            season = int(self._data.get(CONF_API_FOOTBALL_SEASON) or 0)
            return season or datetime.now().year
        except (TypeError, ValueError):
            return datetime.now().year

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return SoccerLiveOptionsFlow()


class SoccerLiveOptionsFlow(config_entries.OptionsFlow):

    async def async_step_init(self, user_input=None):
        errors = {}
        is_api_football = _normalize_provider(
            self.config_entry.data.get(CONF_PROVIDER, PROVIDER_ESPN)
        ) == PROVIDER_API_FOOTBALL
        if user_input is not None:
            # "Change API key": validate here but only commit it once *every*
            # field is valid, so a later error (e.g. a bad date) can't leave the
            # key already changed while the form reports failure. Stored in the
            # entry data — same place reauth writes — not in the options.
            new_key = (user_input.pop("change_api_football_key", "") or "").strip()
            key_to_commit = None
            if is_api_football and new_key:
                if not await async_validate_api_football_key(self.hass, new_key):
                    errors["change_api_football_key"] = "invalid_api_key"
                elif new_key != self.config_entry.data.get(CONF_API_FOOTBALL_KEY):
                    key_to_commit = new_key
            start = (user_input.get("start_date") or "").strip()
            end = (user_input.get("end_date") or "").strip()
            start_dt = end_dt = None
            if start:
                try:
                    start_dt = datetime.strptime(start, "%Y-%m-%d")
                except ValueError:
                    errors["start_date"] = "invalid_date"
            if end:
                try:
                    end_dt = datetime.strptime(end, "%Y-%m-%d")
                except ValueError:
                    errors["end_date"] = "invalid_date"
            if start_dt and end_dt and start_dt > end_dt:
                errors["end_date"] = "end_before_start"
            if not errors:
                if key_to_commit is not None:
                    self.hass.config_entries.async_update_entry(
                        self.config_entry,
                        data={**self.config_entry.data, CONF_API_FOOTBALL_KEY: key_to_commit},
                    )
                user_input.pop("info", None)
                return self.async_create_entry(title="", data=user_input)

        today = datetime.now()

        start_date = self.config_entry.options.get(
            "start_date", self.config_entry.data.get("start_date", (today - relativedelta(months=3)).strftime("%Y-%m-%d"))
        )
        end_date = self.config_entry.options.get(
            "end_date", self.config_entry.data.get("end_date", (today + relativedelta(months=4)).strftime("%Y-%m-%d"))
        )
        recent_match_hours = self.config_entry.options.get("recent_match_hours", 24)
        scan_interval = self.config_entry.options.get("scan_interval", 3)
        live_scan_interval = self.config_entry.options.get(
            CONF_LIVE_SCAN_INTERVAL,
            self.config_entry.data.get(CONF_LIVE_SCAN_INTERVAL, 60),
        )
        notify_service = self.config_entry.options.get("notify_service", "")
        enable_summary_enrichment = self.config_entry.options.get("enable_summary_enrichment", True)
        enable_club_data = self.config_entry.options.get("enable_club_data", True)
        enable_live_odds = self.config_entry.options.get("enable_live_odds", False)
        provider = _normalize_provider(self.config_entry.data.get(CONF_PROVIDER, PROVIDER_ESPN))
        supports_club = provider_supports(provider, "club")
        supports_live_odds = provider_supports(provider, "live_odds")
        max_matches = self.config_entry.options.get("max_matches", 0)
        include_friendlies = self.config_entry.options.get(
            CONF_INCLUDE_FRIENDLIES,
            self.config_entry.data.get(CONF_INCLUDE_FRIENDLIES, True),
        )
        api_football_season = self.config_entry.options.get(
            CONF_API_FOOTBALL_SEASON,
            self.config_entry.data.get(CONF_API_FOOTBALL_SEASON, 0),
        )

        schema = {
            vol.Optional("scan_interval", default=scan_interval): vol.In([1, 2, 3, 5, 10]),
            vol.Optional(CONF_LIVE_SCAN_INTERVAL, default=live_scan_interval): vol.In([30, 45, 60, 90, 120]),
            vol.Optional("recent_match_hours", default=recent_match_hours): vol.In([6, 12, 24, 48]),
            vol.Optional("start_date", default=start_date): str,
            vol.Optional("end_date", default=end_date): str,
            vol.Optional("notify_service", default=notify_service): str,
            vol.Optional("enable_summary_enrichment", default=enable_summary_enrichment): bool,
        }
        # Club enrichment (profile/coach/squad/transfers) is API-Football only.
        if supports_club:
            schema[vol.Optional("enable_club_data", default=enable_club_data)] = bool
        # Live in-play odds (API-Football) — off by default because it polls often.
        if supports_live_odds:
            schema[vol.Optional("enable_live_odds", default=enable_live_odds)] = bool
        schema.update({
            vol.Optional(CONF_INCLUDE_FRIENDLIES, default=include_friendlies): bool,
            vol.Optional(CONF_API_FOOTBALL_SEASON, default=api_football_season): vol.Coerce(int),
            vol.Optional("max_matches", default=max_matches): vol.In([0, 5, 10, 15, 20, 30]),
        })
        # Replace an expired/revoked API-Football key without deleting the entry.
        # Blank = keep the current key; the entered value is validated on save.
        if is_api_football:
            schema[vol.Optional("change_api_football_key", default="")] = str

        # Shared card presentation defaults, published to the sensor so multiple
        # cards on this sensor can inherit one look instead of being set per card.
        opts = self.config_entry.options
        schema.update({
            vol.Optional("card_appearance", default=opts.get("card_appearance", "")):
                vol.In(["", "dark", "light", "ha"]),
            vol.Optional("card_palette", default=opts.get("card_palette", "")):
                vol.In(["", "purple", "red-white", "red-gold", "blue-red", "white-gold",
                        "blue", "orange", "black-white", "classic", "neon", "gold", "team"]),
            vol.Optional("card_compact", default=opts.get("card_compact", False)): bool,
            vol.Optional("card_language", default=opts.get("card_language", "")):
                vol.In(["", "en", "nl", "de", "fr", "es", "it", "pt"]),
        })

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(schema),
            errors=errors,
        )
        
        
