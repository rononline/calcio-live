import asyncio
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import logging
import aiohttp
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
from .const import (
    CONF_API_FOOTBALL_KEY,
    CONF_API_FOOTBALL_SEASON,
    CONF_INCLUDE_FRIENDLIES,
    CONF_LIVE_SCAN_INTERVAL,
    CONF_PROVIDER,
    DOMAIN,
    PROVIDER_API_FOOTBALL,
    PROVIDER_ESPN,
)
from .data import parse_competitions, parse_teams

_LOGGER = logging.getLogger(__name__)

OPTION_SELECT_LEAGUE = "League"
OPTION_SELECT_TEAM = "Team"
OPTION_MANUAL_TEAM = "Manual entry"
OPTION_ALL_TODAY = "All matches today"
OPTION_NEWS = "News"
OPTION_API_FOOTBALL_TEAM_SEARCH = "Search team by name"
OPTION_API_FOOTBALL_TEAM_BY_LEAGUE = "Select team from league"


def _normalize_provider(provider):
    value = str(provider or PROVIDER_ESPN).strip().lower()
    if value in {PROVIDER_API_FOOTBALL, "api-football", "api football"}:
        return PROVIDER_API_FOOTBALL
    return PROVIDER_ESPN


@config_entries.HANDLERS.register(DOMAIN)
class SoccerLiveConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    VERSION = 1

    def __init__(self):
        self._errors = {}
        self._data = {}
        self._teams = []

    async def async_step_user(self, user_input=None):
        self._errors = {}

        if user_input is not None:
            selection = user_input.get("selection")
            provider = _normalize_provider(user_input.get(CONF_PROVIDER, PROVIDER_ESPN))
            user_input[CONF_PROVIDER] = provider
            api_football_key = (user_input.get(CONF_API_FOOTBALL_KEY) or "").strip()
            if provider == PROVIDER_API_FOOTBALL and not api_football_key:
                self._errors[CONF_API_FOOTBALL_KEY] = "api_key_required"
            elif provider == PROVIDER_API_FOOTBALL and selection == OPTION_NEWS:
                self._errors["selection"] = "unsupported_provider_selection"
            elif provider == PROVIDER_API_FOOTBALL and not await self._validate_api_football_key(api_football_key):
                self._errors[CONF_API_FOOTBALL_KEY] = "invalid_api_key"
            else:
                user_input[CONF_API_FOOTBALL_KEY] = api_football_key
                user_input[CONF_INCLUDE_FRIENDLIES] = user_input.get(CONF_INCLUDE_FRIENDLIES, True)
                if provider == PROVIDER_API_FOOTBALL:
                    user_input[CONF_API_FOOTBALL_SEASON] = user_input.get(CONF_API_FOOTBALL_SEASON) or 0

            if self._errors:
                pass
            elif selection == OPTION_SELECT_LEAGUE:
                self._data.update(user_input)
                return await self.async_step_league()

            elif selection == OPTION_SELECT_TEAM:
                self._data.update(user_input)
                if provider == PROVIDER_API_FOOTBALL:
                    return await self.async_step_api_football_team_search()
                return await self.async_step_select_competition_for_team()
            
            elif selection == OPTION_ALL_TODAY:
                self._data.update(user_input)
                self._data["competition_code"] = "99999"  # Dummy code for the "all matches today" sensor
                return self.async_create_entry(
                    title="All matches today",
                    data=self._data,
                )

            elif selection == OPTION_NEWS:
                self._data.update(user_input)
                return await self.async_step_news_competition()

            elif selection == OPTION_MANUAL_TEAM:
                self._data.update(user_input)
                return await self.async_step_manual_team()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required(CONF_PROVIDER, default=PROVIDER_ESPN): vol.In({
                    PROVIDER_ESPN: "ESPN",
                    PROVIDER_API_FOOTBALL: "API-Football",
                }),
                vol.Required("selection", default=OPTION_SELECT_LEAGUE): vol.In([OPTION_SELECT_LEAGUE, OPTION_SELECT_TEAM, OPTION_ALL_TODAY, OPTION_NEWS, OPTION_MANUAL_TEAM]),
                vol.Optional(CONF_API_FOOTBALL_KEY, default=""): str,
                vol.Optional(CONF_API_FOOTBALL_SEASON, default=0): vol.Coerce(int),
                vol.Optional(CONF_INCLUDE_FRIENDLIES, default=True): bool,
            }),
            errors=self._errors,
        )

    async def async_step_api_football_team_method(self, user_input=None):
        if user_input is not None:
            method = user_input.get("team_method")
            if method == OPTION_API_FOOTBALL_TEAM_SEARCH:
                return await self.async_step_api_football_team_search()
            return await self.async_step_select_competition_for_team()

        return self.async_show_form(
            step_id="api_football_team_method",
            data_schema=vol.Schema({
                vol.Required("team_method", default=OPTION_API_FOOTBALL_TEAM_SEARCH): vol.In([
                    OPTION_API_FOOTBALL_TEAM_SEARCH,
                    OPTION_API_FOOTBALL_TEAM_BY_LEAGUE,
                ]),
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
        """Return True if API-Football accepts the key.

        Rejects only on a clear invalid-credentials signal (HTTP 401/403 or an
        ``errors.token`` in the body). On transient problems (timeout, 5xx,
        network error) it returns True so a temporary outage cannot block setup.
        """
        try:
            session = async_get_clientsession(self.hass)
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
        if user_input is not None:
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
        max_matches = self.config_entry.options.get("max_matches", 0)
        include_friendlies = self.config_entry.options.get(
            CONF_INCLUDE_FRIENDLIES,
            self.config_entry.data.get(CONF_INCLUDE_FRIENDLIES, True),
        )
        api_football_season = self.config_entry.options.get(
            CONF_API_FOOTBALL_SEASON,
            self.config_entry.data.get(CONF_API_FOOTBALL_SEASON, 0),
        )

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema({
                vol.Optional("scan_interval", default=scan_interval): vol.In([1, 2, 3, 5, 10]),
                vol.Optional(CONF_LIVE_SCAN_INTERVAL, default=live_scan_interval): vol.In([30, 45, 60, 90, 120]),
                vol.Optional("recent_match_hours", default=recent_match_hours): vol.In([6, 12, 24, 48]),
                vol.Optional("start_date", default=start_date): str,
                vol.Optional("end_date", default=end_date): str,
                vol.Optional("notify_service", default=notify_service): str,
                vol.Optional("enable_summary_enrichment", default=enable_summary_enrichment): bool,
                vol.Optional(CONF_INCLUDE_FRIENDLIES, default=include_friendlies): bool,
                vol.Optional(CONF_API_FOOTBALL_SEASON, default=api_football_season): vol.Coerce(int),
                vol.Optional("max_matches", default=max_matches): vol.In([0, 5, 10, 15, 20, 30]),
            }),
            errors=errors,
        )
        
        
