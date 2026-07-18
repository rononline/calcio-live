# Changelog

## v3.6.89 (2026-07-18)
- club coach: fix the current head coach being wrong (e.g. Feyenoord showing a former assistant). `/coachs?team=X` lists everyone who coached the team and each coach's whole career, so a former coach now in charge elsewhere could win. We now only weigh career spells at the queried team, prefer an open one, and break ties on the most recent start
- live odds: made opt-in. New `enable_live_odds` option (default off, shown only for providers with the new `live_odds` capability) because `/odds/live` polls often. When off, live matches keep showing the last pre-match odds via the snapshot re-attach (no extra requests). The feature pauses itself on HTTP 403 (plan doesn't include it) for 6h and after several empty responses for 1h, independent of the 429 backoff. Diagnostics now expose `live_odds_calls`, `live_odds_last_status` and `live_odds_paused_until`

## v3.6.88 (2026-07-18)
- live odds (API-Football): once a match is live, fetch the real in-play `/odds/live` 1X2 feed instead of the pre-match `/odds` (which API-Football drops at kick-off), so the odds shown during the game are actually live rather than a frozen pre-match snapshot. Tagged `live` on the odds, cached 45s (dedups sensors on the same fixture), suspended markets (stopped/blocked/individually suspended) return nothing so the last shown odds stay. Only runs while a match is live and rides the existing 429 backoff

## v3.6.87 (2026-07-18)
- top assists (API-Football): the top scorers sensor now fetches the real `/players/topassists` ranking and exposes it as a separate `assists` attribute, instead of the Scorers card re-sorting the top scorers by their assists (which missed assist leaders with few goals). Cached 6h and marked unrecorded
- club data: moved behind its own `enable_club_data` option (default on) instead of piggybacking on `enable_summary_enrichment`, and the option only appears for providers that support it via `provider_supports()`. Added a `club` provider capability
- club cache: the assembled club blob is now persisted to HA storage with a timestamp and re-used while younger than 24h, so a restart no longer spends four requests per team sensor on startup
- transfers: drop duplicate records via a composite key (player + date + from + to)

## v3.6.86 (2026-07-18)
- club data (API-Football, team sensors): attach a club attribute with the team profile (venue, founded, country), current coach, full squad (sorted by position then shirt number) and recent transfers (in/out, player, fee, date). Fetched from /teams, /coachs, /players/squads and /transfers, cached 24h (~4 requests/day), and marked unrecorded. Feeds the upcoming Club card

## v3.6.85 (2026-07-17)
- providers: add a declarative `PROVIDER_CAPABILITIES` map and a `provider_supports()` helper, and expose the selected provider's capabilities as the `provider_capabilities` sensor attribute, so cards and automations can adapt to what the provider actually supports (ESPN: news/brackets; API-Football: predictions/odds/injuries/top_assists/xg)

## v3.6.84 (2026-07-17)
- rate limiting: fix a race where an in-flight enrichment request that started before a concurrent HTTP 429 could clear a fresh backoff — the backoff is now only reset once the pause window has elapsed and a request succeeds
- pre-match data: persist the prediction/odds/injuries/standing snapshot to HA storage (debounced), so a Home Assistant restart during a match no longer loses this context

## v3.6.83 (2026-07-17)
- pre-match data: also fetch the prediction/injuries/standing for the live match itself (API-Football keeps returning them during the game), not only the next upcoming match — so the prediction shows during a match that was already live when the update landed. The pre-match snapshot cache now merges, so pre-match odds (which API-Football drops once live) are retained

## v3.6.82 (2026-07-17)
- pre-match data: cache the prediction/odds/injuries/standing snapshot per fixture id and re-attach it once the match goes live (or is rebuilt from /fixtures), so this context stays visible during the game without any new API requests. Previously these fields were only present while the match was still upcoming

## v3.6.81 (2026-07-17)
- rate limiting: on an API-Football HTTP 429, new enrichment requests are paused with an exponential backoff (60s doubling up to 30 min, reset on the next success) while the last cached data keeps being served, so sections don't disappear. The pause state (`enrichment_paused_until`) is exposed in diagnostics

## v3.6.80 (2026-07-17)
- recorder: mark the large, high-churn attributes (`matches`, `previous_matches`, `upcoming_matches`, `next_match`, `schedule_*`, `standings_groups`, `scorers`, `articles`, `rounds`, `head_to_head`, `league_info`, `last_*_event`) as unrecorded, so they no longer bloat the Home Assistant database. The sensor state and small scalar attributes are still recorded

## v3.6.79 (2026-07-17)
- diagnostics: add an `api_football` section for monitoring API usage — per-endpoint call counts and cache hits, last successful update and last HTTP status per endpoint, endpoint cache size, and a `rate_limited_at` marker set on HTTP 429. Helps diagnose why a pre-match section is temporarily missing

## v3.6.78 (2026-07-17)
- calendar: sensors now publish their match list to a shared per-entry store, and the calendar reads from it directly instead of depending on entity states/registry selection (entity-scan kept as a fallback). Makes the calendar independent of entity availability

## v3.6.77 (2026-07-16)
- sensor: expose API-Football standings as structured `home_rank`/`home_points`/`away_rank`/`away_points` fields instead of a pre-formatted string, so the cards can format and localize the label themselves

## v3.6.76 (2026-07-16)
- calendar: add a calendar platform — each config entry now exposes a calendar entity with the team/competition fixtures as events (kick-off, teams, venue, competition; score for finished matches), reusing the match data the sensors already fetch. Enables the HA calendar view and time-based (Calendar trigger) automations

## v3.6.75 (2026-07-16)
- sensor: populate `home_standing_summary`/`away_standing_summary` for API-Football matches (league position + points, e.g. "#2 · 65 pts") via the /standings endpoint for the next upcoming match; the Team card already renders these. Cached 6h, only for league matches (friendlies have no standings)

## v3.6.74 (2026-07-16)
- blueprints: add yellow card, substitution, full time (final score) and configurable kick-off reminder notification blueprints, alongside the existing goal / red card / match started ones

## v3.6.73 (2026-07-16)
- parser: normalize the API-Football `expected_goals` statistic to home/away `expectedGoals` so cards can show xG alongside possession and shots (for leagues where API-Football provides xG)

## v3.6.72 (2026-07-16)
- sensor: attach averaged 1X2 odds (home/draw/away from the Match Winner market, across bookmakers) to the next upcoming match via API-Football `/odds`; cached 1h, attached only when odds exist (API-Football carries odds ~1–14 days pre-match, generally not for friendlies)

## v3.6.71 (2026-07-16)
- parser: suppress API-Football's neutral placeholder prediction (equal percentages with no named winner, e.g. 33/33/33) so nothing is attached until a meaningful prediction exists

## v3.6.70 (2026-07-16)
- sensor: attach per-team injuries/suspensions (player + reason + `suspended` flag) to the next upcoming match via API-Football `/injuries`; fetched in parallel with predictions/odds, attached only when data exists

## v3.6.69 (2026-07-16)
- sensor: attach a pre-match `prediction` (home/draw/away win percentages + betting advice) to the next upcoming match via API-Football `/predictions`; one call, cached 6h, attached only when data exists

## v3.6.68 (2026-07-15)
- parser: ESPN match model now includes `date_iso` (raw ISO kickoff) alongside the localized display date, enabling kickoff-time weather forecasts in the cards

## v3.6.67 (2026-07-11)
- parser: flatten ESPN object scores (`{value, displayValue}`) to their display value in the live match model and head-to-head list — fixes "[object Object]" scores on live ESPN matches

## v3.6.66 (2026-07-10)
- sensor: single-match cards no longer fetch API-Football enrichment for upcoming matches more than 3h away (those endpoints are empty until close to kickoff), saving daily API quota
- diagnostics: config-entry diagnostics now include provider, api_status, last_error and the API-Football quota (the API key itself is never included, only a `has_api_football_key` boolean)

## v3.6.65 (2026-07-10)
- sensor: goal detection now attributes scored penalties for both providers (ESPN "Penalty - Scored", API-Football "Goal - Penalty"); missed penalties and VAR-disallowed goals stay excluded

## v3.6.64 (2026-07-10)
- parser: API-Football missed penalties now read "Penalty - Missed" and no longer count as a scoring play; scored penalties are written as "Goal - Penalty" so the scorer/minute reach the goal notification

## v3.6.63 (2026-07-10)
- parser: API-Football `league_name`/`competition_name` are localized to Home Assistant's language (e.g. "Friendlies Clubs" → "Oefenwedstrijd"); the raw name is kept for the friendlies filter and `league_info`

## v3.6.62 (2026-07-10)
- sensor: surface API-Football error payloads (HTTP 200 with a top-level `errors` field) to `last_error` and the log instead of caching them as valid-but-empty data; warn on HTTP 429 rate limits

## v3.6.61 (2026-07-10)
- sensor: the live match clock now includes stoppage time (e.g. 90+4)
- parser: topscorer goals/assists are summed across clubs for players transferred mid-season

## v3.6.60 (2026-07-05)
- config flow: add matching `config/error` translations (all six languages) so first-time setup shows proper messages instead of raw keys; validate the API-Football key during setup (fails open on transient network errors)

## v3.6.59 (2026-07-05)
- parser: keep stoppage time in API-Football `match_details`; normalize pre-match incidents (negative `elapsed`) to `N/A`; misc cleanups (event formatter params, O(n²) lineup tagging, module-level stat-key table)

## v3.6.58 (2026-07-05)
- provider: add optional API-Football support alongside ESPN, including provider setup, API key handling, direct team search, season selection and friendlies filtering
- sensor: API-Football supports team fixtures (`team_match`, `team_matches`, `team_matches_mixed`), competition fixtures, all matches today, standings and top scorers; news and knockout brackets remain ESPN-only
- sensor: API-Football match enrichment fetches fixture events, statistics and lineups for team sensors, including recent finished matches so card popups can show scorers/cards after full time
- sensor: add configurable `live_scan_interval` option (`30` / `45` / `60` / `90` / `120` seconds); live-mode main response cache now follows the selected interval when lower than 60 seconds
- parser: add API-Football parser and normalize event/detail strings to the existing Soccer Live match contract
- docs/tests: document provider behavior, quota-related caching and live polling; add config-flow, parser and sensor regression coverage

## v3.6.49 (2026-06-30)
- parser: `home_form` and `away_form` now default to `""` instead of `"N/A"` when ESPN does not supply form data — prevents cards from rendering spurious dots for the literal characters N, / and A

## v3.6.48 (2026-06-30)
- sensor: schedule `compact()` now includes `clock`, `league_logo`, and `season_info` — live match clock, competition logo, and round info are now available in `schedule_live_matches`, `schedule_upcoming_matches`, and `schedule_recent_matches` for use in HA templates and automations

## v3.6.47 (2026-06-30)
- sensor: `previous_matches` compact dict now includes `league_name` and `season_info` — required for competition label and phase display in the Team card
- sensor: `upcoming_matches` compact dict now includes `home_form`, `away_form`, and `league_name` — required for opponent form dots and competition label in the Team card

## v3.6.45 (2026-06-26)
- bracket: add `"round-of-64"` to slug_map so ESPN's Round of 64 events pass the single-leg filter
- bracket: add `32: "Round of 64"` to the canonical size→name dict

## v3.6.44 (2026-06-26)
- sensor: removed `commentary` sensor type — no card uses it since LiveCommentary was removed from the card repo; removes the `_enrich_with_commentary` fetch and the `if selection == "Live Commentary"` setup path
- config_flow: removed "Live Commentary" option from the integration setup menu

## v3.6.43 (2026-06-25)
- parser: `_get_details` now uses `(detail.get("type") or {})` and `(detail.get("clock") or {})` — prevents `AttributeError` when ESPN returns `null` for these fields instead of an object

## v3.6.42 (2026-06-25)
- sensor: `_extract_all_goal_scorers` now excludes `"Goal Disallowed"` strings — disallowed goals no longer appear in `goal_scorers_str` of the `match_finished` event
- sensor: `compact()` in `_compute_schedule_summary` now includes `league_name` so `schedule_upcoming_matches`, `schedule_live_matches`, and `schedule_recent_matches` carry competition info (relevant for `team_matches_mixed` sensors)

## v3.6.41 (2026-06-24)
- sensor: `sort_key` in `_compute_schedule_summary` now returns a timezone-aware `datetime.max` fallback so matches with unparseable dates no longer cause a `TypeError` when sorted alongside valid aware datetimes
- sensor: `_pick_goal_strings` now excludes `"Goal Disallowed"` strings so VAR-cancelled goals cannot be attributed as real goal scorers
- sensor: `_pick_goal_strings` now returns the *most-recent* undispatched strings (`[-count:]`) instead of the oldest — prevents a late-arriving goal string from a previous goal being picked up as the scorer for the next goal

## v3.6.40 (2026-06-24)
- sensor: `_filter_start_str` / `_filter_end_str` return `None` when no date is configured instead of calling `strftime()` on `None` and crashing
- sensor: URL building omits the ESPN `dates` parameter when neither calendar nor configured dates provide a complete range, preventing the remaining `strftime()` crash
- sensor: fetch lock pruning now preserves locks that are currently held (`v.locked()`) so an in-progress fetch is never evicted from `_fetch_locks`, eliminating the remaining race condition
- sensor: ESPN responses are cached only after successful processing, so malformed payloads cannot poison the shared cache
- parsers: match, standings, league, news, scorers and bracket parsers now re-raise internal errors instead of silently returning empty data — the sensor catches the exception and correctly sets `api_status = error`
- config_flow: competition and team responses are normalized defensively; null, non-object and incomplete entries are skipped instead of crashing with KeyError/TypeError
- tests: add regressions for empty date filters, failed-response caching, parser failures and malformed competition/team responses

## v3.6.39 (2026-06-24)
- sensor: introduce `_process_and_apply()` helper used by all three code paths (cache hit, lock double-check, network fetch) so `last_event` attributes are preserved on every update path, not just the cache path
- sensor: per-URL `_fetch_lock` (mirrors `_calendar_locks`) prevents concurrent sensors sharing the same ESPN URL from issuing duplicate network requests; a double-check inside the lock processes cached data when available
- sensor: store key now includes `config_entry_id` so two identical config entries each keep their own `match_finished` dispatched-event file and cannot overwrite each other
- config_flow: empty team list now returns `async_abort(reason="no_teams")` instead of presenting an unusable empty dropdown; translated in all 6 languages

## v3.6.38 (2026-06-24)
- sensor: goal attribution now uses `[ABBREV]` tag from ESPN detail strings to match goals to the correct team; falls back to positional order when tag is absent
- sensor: `last_event`, `last_goal_event`, `last_card_event` and related attributes now survive the next update cycle — carried forward until a new event of the same type overwrites them
- sensor: push notifications now use `minute` (not `clock`) for goal/card events, and `league_name` (not `competition_name`) for match-finished events
- config_flow: `{"sports": []}` no longer raises `IndexError` in the teams step
- config_flow: empty competition list now returns an `async_abort` instead of showing a broken empty dropdown; translated in all 6 languages

## v3.6.37 (2026-06-24)
- sensor: simultaneous goals now correctly attributed — home claims only `goals_scored` strings from the timeline, leaving the rest for away; `_extract_goal_scorers_from_details` simplified to work on the pre-filtered list
- scoreboard: prefer `competition.status` over `event.status` for match state, clock and period so a live match with status only in `competitions[0]` is no longer treated as N/A
- scoreboard: date filter interprets user-supplied `start_date`/`end_date` in the HA timezone instead of UTC, preventing midnight-local matches from being included or excluded by the wrong UTC day
- standings: handle both `seasons` (array) and `season` (singular object) fixture shapes; read `league_name`/`abbreviation` from `leagues[0]` as fallback when not present at the top level

## v3.6.36 (2026-06-24)
- scoreboard: `home_record`, `home_top_scorer`, `home_record_summary`, `home_standing_summary` and their away equivalents now use `home_comp`/`away_comp` — the remaining `competitors[0]`/`[1]` references were missed in v3.6.35
- scoreboard: `is_within_recent_window` adds 2 h to the configured window so the threshold is measured from match end (kickoff + ~2 h) rather than kickoff; a match with a 6 h window that kicked off 7 h ago and ended 5 h ago is now correctly shown
- sensor: `_extract_goal_scorers_from_details` now accepts an `exclude` set so home-goal strings are excluded when extracting the away scorer — prevents the same player from being attributed to both teams when both score in one poll cycle

## v3.6.35 (2026-06-24)
- scoreboard: use `homeAway` field from ESPN to correctly assign home and away competitors — was always taking `competitors[0]` as home, swapping teams in roughly half of matches
- scoreboard: `is_within_recent_window()` now compares naive local datetimes — the stored date string is local time (formatted by `_parse_date`), but the previous code treated it as UTC, causing 1–2 h drift depending on timezone
- sensor: goal deduplication now uses a per-match `_dispatched_goal_details` set instead of `max()` — a real goal scored after a disallowed goal (score reverts and rises again) was silently dropped
- sensor: sensor state for a post-match now reads `"Last match: X 2 - 1 Y"` instead of `"Next match: X vs Y"` — the `else` branch was also covering the `post` state

## v3.6.34 (2026-06-24)
- sensor: `match_finished` events now only fire on a known `in→post` transition; historical finished matches on first poll are silently skipped to prevent notification spam on new installs or cleared storage
- sensor: score corrections no longer trigger duplicate goal events — track the highest score seen per match so a score that dips and recovers to a known value does not re-fire
- sensor: `upcoming_matches` now starts from the first `pre`/`in` match when `next_match` is a recently finished match (was always skipping index 0, hiding the first upcoming fixture)
- sensor: invalid JSON from ESPN now sets `_last_error` and breaks the retry loop instead of propagating an unhandled exception that left `api_status` stale

## v3.6.33 (2026-06-24)
- config_flow: validate `start_date`/`end_date` format (YYYY-MM-DD) and `start ≤ end` before saving options; error messages in all 6 languages
- sensor: guard `datetime.strptime` with try/except so a bad stored date disables the filter with a warning instead of crashing sensor init
- sensor: set `_last_error` on HTTP 4xx (except expected 404 for top_scorers) so `api_status` correctly shows `error` instead of `ok`
- scoreboard: use `.astimezone(UTC)` instead of `.replace(tzinfo=UTC)` for timezone-aware dates — `17:00+02:00` now correctly becomes `15:00 UTC` instead of `17:00 UTC`
- integration: remove accidental `package-lock.json` (Python project, not Node)

## v3.6.32 (2026-06-24)
- sensor: parse errors no longer mark the update as successful — `api_status` now correctly stays `error` when `_process_data` raises an exception (was: `_last_error` set in except block then immediately overwritten to `None`)
- scoreboard: end-date filter now uses `23:59:59` instead of `00:00:00` — matches on the last day were excluded when scheduled after midnight UTC
- translations: remove unused `strings.json` (HA reads from `en.json`; duplicate file caused confusion)

## v3.6.31 (2026-06-23)
- scoreboard: replace hardcoded Dutch `team_name` fallback `"Alle wedstrijden"` with `"All matches"` — this string is a visible sensor attribute in HA

## v3.6.30 (2026-06-23)
- config_flow: catch `asyncio.TimeoutError` alongside `aiohttp.ClientError` — timeouts during setup/team-search no longer cause an unhandled exception
- config_flow: switch log calls from f-strings to `%s` lazy formatting
- sensor: translate remaining Dutch/Italian hardcoded state strings to English (`"Volgende wedstrijd"`, `"Geen wedstrijden beschikbaar"`)
- sensor/scoreboard: translate remaining Italian/Dutch docstrings and inline comments to English
- hassfest workflow: pin `actions/checkout` to `v7.0.0` consistent with other workflows

## v3.6.29 (2026-06-23)
- Prune `_calendar_cache` and `_calendar_locks` class-level dicts each update cycle — entries older than 5 minutes are removed and orphaned locks are dropped, preventing unbounded memory growth

## v3.6.28 (2026-06-22)
- Add URL-building regression tests for calendar/no-calendar sensor types
- Throttle repeated calendar fetch warnings per competition and error reason for 5 minutes

## v3.6.27 (2026-06-22)
- Reduce unnecessary ESPN calendar calls by only fetching calendar dates for date-range scoreboard sensors
- Add per-competition calendar caching and locking to prevent startup bursts across related sensors
- Improve calendar fetch logging: timeouts and HTTP/client errors now include sensor name, URL and error type instead of an empty message

## v3.6.16 (2026-06-20)
- Add Home Assistant automation blueprints for goal, red card and match started notifications

## v3.6.15 (2026-06-20)
- Docs: document health attributes, automation last-event attributes, schedule summary attributes and new match color/count fields

## v3.6.14 (2026-06-20)
- Automation attributes: expose `last_event`, `last_event_type`, `last_event_timestamp` and typed last-event attributes for goals, cards, match started and match finished
- Health attributes: expose `last_successful_update`, `last_error` and `api_status`
- Schedule summary: expose deduplicated `schedule_*` counts and compact live/upcoming/recent match lists

## v3.6.13 (2026-06-20)
- Match sensors: expose top-level home/away colors and `team_colors` for card auto-skins
- Match sensors: expose next/live match abbreviations, event IDs, event counts, H2H counts and broadcast counts for richer cards and automations

## v3.6.12 (2026-06-19)
- `standings` sensor: remove fallback ESPN logo URL construction — ESPN uses numeric IDs not competition code strings, causing 404 errors; card now shows fallback emoji instead

## v3.6.11 (2026-06-19)
- `standings` sensor: when ESPN standings API returns no logo, construct fallback URL from competition code (`espncdn.com/leaguelogos/soccer/500/{code}.png`)
- `standings` sensor: state changed from Dutch "Stand" to "Standings"
- `standings` parser: broader logo extraction (tries top-level `logos`, then `leagues[0].logos`)

## v3.6.10 (2026-06-19)
- `standings` parser: include `league_logo` from ESPN logos array
- `bracket` sensor: include `league_logo` and `league_name` from `process_league_data`
- `match_day` sensor: include `league_logo`; state changed from Dutch "Speelronde" to "Match day"
- `commentary` sensor: include `league_logo`; state no longer says "Geen live wedstrijd" — now "No live match"
- `news` sensor: include `league_name` and empty `league_logo`; state no longer says "artikelen" — now "articles"

## v3.6.9 (2026-06-19)
- Fix Dutch sensor state strings: `"tegen"` → `"vs"`, `"wedstrijden beschikbaar"` → `"matches available"`, `"Geen wedstrijden beschikbaar"` → `"No matches available"`

## v3.6.8 (2026-06-19)
- `bracket.py`: remove dead `round_name_nl`/`name_nl` Dutch fields; simplify slug/canonical tuples to plain strings; translate Italian docstrings to English
- `sensor.py`: bracket sensor state now uses English — `"Round of 16 (16 teams)"` instead of `"Round of 16 (16 ploegen)"`; fallback `"Bracket unavailable"` instead of `"Bracket niet beschikbaar"`

## v3.6.7 (2026-06-19)
- README: `league_info` attribute added to data contract table
- Config-flow: `commentary` setup step added to all 6 translation files (was missing — showed blank UI)
- Comments in `bracket.py`, `standings.py`, `sensor.py` translated to English

## v3.6.6 (2026-06-18)
- Add `icon.png` inside component directory so the HA update entity shows the integration icon

## v3.6.5 (2026-06-18)
- `league_info` objects now include a `name` field (ESPN full league name, e.g. "FIFA World Cup") — Countdown card uses this to display the competition name

## v3.6.4 (2026-06-18)
- Translate remaining NL/IT inline comments in sensor.py to English

## v3.6.3 (2026-06-18)
- All remaining Dutch/Italian log messages translated to English (goal/card/substitution/match events in sensor.py)
- URL-based shared fetch cache: sensors sharing the same ESPN endpoint now share one fetch per cache window instead of fetching separately
- Parser tests added (17 passing): scoreboard and standings parsers tested against minimal ESPN fixtures; direct module import bypasses HA's `__init__.py`

## v3.6.2 (2026-06-18)
- All log messages standardized to English (IT/NL strings in sensor.py and parsers)
- Data contract table added to README: match object attributes, enriched sensor fields, top-level `next_match_*` attributes

## v3.6.1 (2026-06-17)
- Pass `enable_summary_enrichment` and `max_matches` to all sensor constructors (were read from options but not forwarded)
- Translation labels for `enable_summary_enrichment`, `max_matches`, `notify_service` added in all 7 languages
- `next_match_has_stats`/`next_match_has_commentary` use parser flags with fallback to statistics/events presence
- Diagnostics: `sensor_type` now read reliably from state attributes (works for `team_matches_mixed`, `all_matches_today`, etc.)
- `sensor_type` added as explicit state attribute on every sensor

## v3.6.0 (2026-06-17)

### Bug fix (high priority)
- `_parse_match_datetime()` now tries both `%d-%m-%Y %H:%M` and `%d/%m/%Y %H:%M` — mismatch was causing `next_match_datetime_iso` and `next_match_minutes_until` to always return `N/A`/`None`

### New top-level attributes
- `next_match_broadcasts` — list of TV/streaming channels
- `next_match_attendance`, `next_match_neutral_site`, `next_match_has_stats`, `next_match_has_commentary`, `next_match_links`, `next_match_week`

### Diagnostics
- `diagnostics.py` added — download via HA Settings → Integrations → Soccer Live; includes competition code, sensor types, request count, match count, cache age (no large match payloads)

### Options flow
- `enable_summary_enrichment` (default: on) — disable to skip ESPN summary endpoint and reduce API calls
- `max_matches` (0/5/10/15/20/30, default: 0 = unlimited) — caps `matches` list to reduce recorder payload

## v3.5.6 (2026-06-17)
- Normalise indentation in `_fetch_match_summary` and `_get_calendar_data` HTTP session blocks

## v3.5.5 (2026-06-17)
- Fix indentation in HTTP session blocks in `sensor.py` and `config_flow.py` (normalised after aiohttp migration)

## v3.5.4 (2026-06-17)
- Use `async_get_clientsession(hass)` instead of bare `aiohttp.ClientSession()` in sensor + config_flow
- `_scorers_unavailable` now correctly set to `True` on 404 — sensor skips subsequent requests

## v3.5.3 (2026-06-17)
- Team matching on ESPN `team_id` (competitor ID) when available; falls back to name matching
- Parser: `process_match_data()` accepts `team_id` parameter

## v3.5.2 (2026-06-16)
- Fix: `scoreboard.py` skips matches with `< 2 competitors` (postponed/incomplete ESPN events no longer crash the entire sensor update)

## v3.5.1 (2026-06-16)
- Live polling: sensors with active matches refresh automatically every 60 s (in addition to base interval)
- Live polling only applies to live-capable sensor types; standings/scorers/news/bracket unaffected
- `manifest.json` version synced to `3.5.0` (was `3.4.2`)
- `hacs.json`: description added

## v3.5.0 (2026-06-15)
- Standings: `zone_color`, `zone_label`, `zone_abbrev` from `entry.note` per team
- Scoreboard: `home/away_record_summary`, `home/away_standing_summary` from competitors
- Scoreboard: `broadcasts` (full list), `neutral_site`, `tickets_available` per match
- Scoreboard: `has_stats` (boxscoreAvailable), `has_commentary` (playByPlayAvailable)
- Scoreboard: `match_links` compact dict `{summary, commentary, stats, video}`
- Scoreboard: `week_number` from `events[].week.number`
- Summary: `last_five_home`/`last_five_away` from `boxscore.players[].statistics`
- News: `byline`, `last_modified`, `image_caption`, `image_credit`, `tags`, `premium`
- Top scorers 404: clear INFO log
- `manifest.json` version synced to 3.4.2
- News: `byline`, `last_modified`, `image_caption`, `image_credit`, `tags`, `premium`
- Top scorers 404: clear INFO log (not an error, ESPN doesn't support all competitions)

## v3.3.0 (2026-06-15)
- `async_step_campionato` → `async_step_league`, `step_id="campionato"` → `"league"` (all 7 translation files)
- `nome_squadra` / `nome_squadra_normalizzato` → `display_name_input` / `display_name_normalized`
- Italian error messages and comments in `parsers/scoreboard.py` → English
- All `CalcioLive*` class names in card code → `SoccerLive*`
- Releases consolidated: removed 30+ micro-releases

## v3.2.0 (2026-06-15)

## v3.1.2 (2026-06-15)
- Event tracking now uses `event_id` as primary key (fallback to team names)
- Prevents false deduplication on rematches, friendlies or team name changes

## v3.1.1 (2026-06-15)
- `_process_data` fully pure: events collected via passed `events: list` parameter
- All `_detect_and_dispatch_*` and `_dispatch_*` methods no longer mutate `self._pending_events`
- `self._save_store_needed` derived from events on event loop instead of set in executor
- Fallback return fixed: no longer reads `self._state` / `self._attributes`

## v3.1.0 (2026-06-15)
- Rename `sensori/` → `parsers/`, `classifica.py` → `standings.py`
- Rename `classifica_data()` → `standings_data()`
- Sensor IDs: `soccerlive_classifica_*` → `soccerlive_standings_*`, `soccerlive_cannonieri_*` → `soccerlive_scorers_*`
- Image filenames renamed from Italian to English
- All Italian inline comments replaced with English

## v3.0.9 (2026-06-15)
- `_process_data` returns `{"state": ..., "attributes": {...}, "events": [...]}` instead of mutating entity state in executor thread
- `self._state` and `self._attributes` now assigned on event loop only

## v3.0.8 (2026-06-15)
- Fix: manual team entry now sets `team_name` (was: created zero sensors)
- Fix: `start_date` / `end_date` from options flow now read correctly (was: only read from `entry.data`)
- Fix: cache hit path now runs `_enrich_with_summary()` and `_enrich_with_commentary()`
- Fix: translation key in team step: `team_id` → `team_name` in all 7 language files

## v3.0.7 (2026-06-15)
- Wrap data processing in `try/except`: malformed ESPN response no longer crashes sensor

## v3.0.6 (2026-06-15)
- Remove server-side geocoding (caused HA bootstrap timeout with 35+ pending tasks)

## v3.0.5 (2026-06-15)
- Non-blocking geocoding attempt (subsequently replaced by full removal in v3.0.6)

## v3.0.4 (2026-06-15)
- Server-side stadium geocoding via Nominatim (subsequently reverted due to bootstrap issues)

## v3.0.3 (2026-06-15)
- Add `icon.png` at repo root for HACS display
- Replace placeholder blue square with soccer ball icon

## v3.0.2 (2026-06-14)
- Critical fix: include `config_entry_id` in `unique_id` generation
- Prevents duplicate sensor errors when the same team is added in multiple config entries

---

## v3.0.0 (2026-06-14)
- Initial Soccer Live integration release (fork of Calcio Live by @Bobsilvio)
- Live Commentary sensor with play-by-play commentary
- Push notifications on goal, cards, substitution, match finished
- HA events: `soccer_live_goal`, `soccer_live_yellow_card`, `soccer_live_red_card`, `soccer_live_match_started`, `soccer_live_substitution`, `soccer_live_match_finished`
- Device grouping per config entry
- All sensors use `sensor.soccer_live_*` naming
