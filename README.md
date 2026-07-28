# ⚽ Soccer Live — Home Assistant Integration

Real-time football data in Home Assistant via ESPN, with optional API-Football support for users who provide their own API key.

> Built on ideas from [Calcio Live](https://github.com/Bobsilvio/calcio-live) by @Bobsilvio

---

## 🚀 Quick start

New here? This gets you a live team card in a few minutes:

1. **Install the integration** via HACS (see [Installation](#-installation-via-hacs) below) and restart Home Assistant.
2. **Add the integration**: *Settings → Devices & Services → Add Integration → Soccer Live*. For the data source, pick **ESPN** — it's free and needs no API key.
3. **Choose what to follow**: pick **Team** (the default).
4. **Find your team**: select the league, then the team (for example *Eredivisie → Feyenoord*).
5. **Install the [Soccer Live Card](https://github.com/rononline/soccerlive-card)** via HACS.
6. **Add a card** to your dashboard: *Add card → Soccer Live Card*, and select your team's entity.
7. **Pick the suggested sensor**: the Team, Countdown and Match Center cards use the **`next_*`** sensor (`soccer_live_next_{competition}_{team}`). See **Which sensor do I need?** below.

> Want predictions, odds and injuries? Choose **API-Football** as the data source in step 2 instead and paste your API key when prompted — everything else works the same.

![Soccer Live first-install walkthrough](images/setup-wizard.svg)

---

## 📦 Installation via HACS

> **HACS default store**: submission pending — once approved, search for **Soccer Live** directly in HACS.

Until then, add as a **custom repository**:
1. In HACS → ⋮ → **Custom repositories** → add `https://github.com/rononline/soccerlive`, category: **Integration**
2. Install **Soccer Live** via HACS
3. Restart Home Assistant
4. Go to **Settings → Integrations → Add Integration** and search for `Soccer Live`

> Also install the companion cards: [Soccer Live Card](https://github.com/rononline/soccerlive-card)

---

## 🗃️ Sensor types

Sensors are created automatically depending on your selection:

| Sensor type | Name pattern | Description |
|---|---|---|
| `team_match` | `soccer_live_next_{competition}_{team}` | Next / current match for a team |
| `team_matches` | `soccer_live_all_{competition}_{team}` | All matches for a team (competition-specific) |
| `team_matches_mixed` | `soccer_live_all_mixed_{team}` | All matches for a team (all competitions) |
| `match_day` | `soccer_live_all_{competition}` | All matches in a competition |
| `standings` | `soccer_live_standings_{competition}` | League standings |
| `top_scorers` | `soccer_live_scorers_{competition}` | Top scorers for a competition (auto-created) |
| `bracket` | `soccer_live_bracket_{competition}` | Knockout bracket (auto-created for cup competitions) |
| `all_matches_today` | `soccer_live_all_today` | All matches worldwide today |
| `news` | `soccer_live_news_{competition}` | News feed for a competition |

> **Friendly names & devices.** Every entry is grouped as a device (e.g. *Soccer Live · Feyenoord*), and each entity has a short, readable name — **Next match**, **All matches**, **All competitions**, **Match calendar** — while the technical `entity_id` stays verbose and stable (so existing dashboards keep working).

---

## 🎯 Which sensor do I need?

A **Team** entry creates several sensors (plus a calendar). Which one you point a card at depends on the card:

| You want… | Use the sensor | Entity |
|---|---|---|
| A single team's **live / next match** — Team card, Countdown, Match Center | **`next_*`** (`team_match`) | `soccer_live_next_{competition}_{team}` |
| A team's **full schedule across all competitions** — Team Competitions, extended schedule/fixtures list | **`all_mixed_*`** (`team_matches_mixed`) | `soccer_live_all_mixed_{team}` |
| A team's matches **in one specific competition** | **`all_*`** (`team_matches`) | `soccer_live_all_{competition}_{team}` |
| A **whole competition** overview — Standings, Matches, Top scorers, Bracket | the competition sensors | `soccer_live_all_{competition}`, `soccer_live_standings_{competition}`, … |
| Fixtures in the **Home Assistant calendar** / time-based automations | the calendar | `calendar.soccer_live_{team}` |

> Rule of thumb: **Team / Countdown / Match Center → `next_*`**, **Team Competitions & extended schedules → `all_mixed_*`**, **competition-wide views → `all_*`**. The card's entity picker suggests the matching sensor.

---

## ⚙️ Integration options

Configure via **Settings → Devices & Services → Soccer Live → Configure**:

| Option | Default | Description |
|---|---|---|
| `scan_interval` | `3` minutes | Normal polling interval when no match is live. |
| `live_scan_interval` | `60` seconds | Extra refresh interval while a match is live (`30` / `45` / `60` / `90` / `120` seconds). Use `30` seconds for faster goal/card updates when your API quota allows it. |
| `enable_summary_enrichment` | `true` | Fetch extra match details. ESPN uses the summary endpoint; API-Football uses fixture events, statistics and lineups. Disable to reduce API calls. |
| `include_friendlies` | `true` | Include friendlies when using API-Football fixture data. |
| `api_football_season` | `0` (auto) | API-Football season to query. For standings/top scorers, auto mode uses the previous season before August. |
| `change_api_football_key` | — | *(API-Football only)* Paste a new key here to replace an expired/revoked one; leave blank to keep the current key. The value is validated on save. |
| `max_matches` | `0` (unlimited) | Limit the number of matches stored per sensor (5 / 10 / 15 / 20 / 30). Useful to reduce state size on large sensors. |
| `notify_goals`, `notify_cards`, `notify_match_status` | `true` | Choose which direct push-notification categories are enabled. |
| `quiet_hours_start` / `quiet_hours_end` | empty | Optional local quiet window in `HH:MM` format, including windows across midnight. |
| `player_watchlist` | empty | Comma-separated exact player names to expose in `player_watchlist` for the Club card. |

> **API key expired or revoked?** When API-Football rejects the key, the sensors report `api_status: authentication_failed` and Home Assistant automatically prompts you to re-enter it (a repair/notification appears — no need to delete the integration). You can also change it any time via the option above.

> **Sync status.** Each sensor also publishes a `sync_status` attribute — `initializing`, `fetching`, `ready`, `rate_limited`, `authentication_failed` or `provider_unavailable` — so a card can show concrete text (e.g. "fetching matches for the first time") during the first update instead of an empty card that looks like a misconfiguration.

> **Card contract.** Sensors publish `integration_version`, `data_schema_version` and `recommended_card_types` (the `card_type` slugs that suit the sensor), so the card editor can recommend the right card for a selected entity and warn when the integration is outdated.

> **Insights and local history.** Match sensors publish a provider-neutral
> `data_completeness` and `match_readiness` object per match, plus
> `data_quality`, `matchday`, `match_archive` and `match_archive_summary`.
> Finished matches are kept locally in Home Assistant (up to 500 per
> integration entry); no extra provider request is made. Large derived
> attributes are excluded from Recorder history.

### Local archive and refresh services

The integration registers services under the `soccer_live` domain:

| Service | Purpose |
|---|---|
| `soccer_live.refresh` | Immediately request a refresh from one or all config entries. |
| `soccer_live.rebuild_match_archive` | Add currently available finished matches to the local archive. |
| `soccer_live.clear_match_archive` | Permanently clear the selected local archive. |
| `soccer_live.export_match_archive` | Return a versioned JSON-compatible archive backup as response data. |
| `soccer_live.import_match_archive` | Replace an archive from a previous JSON export. |

Every service accepts an optional `config_entry_id`; without one it applies to
all Soccer Live entries. The Archive card supplies the correct ID
automatically for its rebuild and clear buttons.
The complete response from `export_match_archive` can be pasted into
`import_match_archive`; a one-entry backup also remains portable when Home
Assistant assigned the restored integration a different config-entry ID.

> **Shared coordinator.** Entities retain their provider-specific polling
> intervals, while an entry-wide coordinator publishes a real `fetching`
> transition, tracks the entry's entities and handles manual refreshes. Existing
> entity IDs, provider caches and event semantics are unchanged.

---

## 🌐 Data providers

ESPN is the default provider and does not require an API key. API-Football can be selected during setup and requires your own API-Football key.

Current API-Football support:
- Team fixtures: `team_match`, `team_matches`, `team_matches_mixed`
- Competition fixtures: `match_day`
- `all_matches_today`
- `standings`
- `top_scorers`
- Optional match enrichment for `team_match`, `team_matches` and `team_matches_mixed` via fixture events, statistics, lineups and head-to-head history

API-Football news and knockout brackets are not supported yet. News and bracket sensors remain ESPN-only.

The integration caches API-Football calls to reduce quota use:
- Main fixture/standings/scorers responses are shared by URL for up to 60 seconds. While a match is live, this cache follows `live_scan_interval` when that value is lower than 60 seconds.
- Fixture events are cached for 30 seconds.
- Fixture statistics and lineups are cached for 5 minutes.
- Head-to-head history is cached for 24 hours per unique team pairing.
- Predictions are cached for 6 hours, standings for 6 hours, injuries for 3 hours, and odds for 1 hour.
- The `api_football_quota` diagnostic attribute is refreshed through API-Football `/status` every 30 minutes.

The config-entry **diagnostics** (Settings → Devices & services → the entry → Download diagnostics) include an `api_football` section for monitoring API usage: per-endpoint call counts and cache hits, the last successful update and last HTTP status per endpoint, the endpoint cache size, and a `rate_limited_at` marker (set on an HTTP 429). This helps explain when a section is temporarily missing.

For API-Football team sensors, search teams directly by name during setup. Labels include the API-Football ID, because these IDs are different from ESPN IDs.

---

## ⚙️ Recorder / database size

The large, high-churn attributes (`matches`, `previous_matches`, `upcoming_matches`, `next_match`, the `schedule_*` lists, `standings_groups`, `scorers`, `articles`, `rounds`, `head_to_head`, `league_info` and the `last_*_event` payloads) are **automatically excluded from the recorder history** — the integration marks them as unrecorded, so the Home Assistant database stays small out of the box. The sensor *state* (the score summary) and small scalar attributes are still recorded, so state history keeps working.

If you'd rather drop the sensors from history entirely, you can still add this to `configuration.yaml`:

```yaml
recorder:
  exclude:
    entity_globs:
      - sensor.soccer_live_*
```

---

## 🔢 Finding a Team ID

Usually **not needed**: the ID is filled in automatically when you select a competition and team. Only required for manual entry.

1. **Via ESPN website**: open the team page on `espn.com` — the ID is the number in the URL:  
   `espn.com/soccer/team/_/id/`**`9723`**`/portland-timbers` → Team ID = **9723**
2. **Via ESPN API**:  
   `https://site.api.espn.com/apis/site/v2/sports/soccer/all/teams`

---

## 📲 Push Notifications

The integration can automatically send push notifications when goals, cards, or match events occur. Configure this in the integration options:

1. Go to **Settings → Devices & Services → Soccer Live**
2. Click **Options** (gear icon)
3. Set **Notify Service** to your desired notification service:
   - `notify.mobile_app_yourphone` — iOS/Android Home Assistant app
   - `notify.telegram` — Telegram (requires notify.telegram service)
   - `notify.pushbullet` — PushBullet (requires notify.pushbullet service)
4. Save

**Notifications sent for (individually configurable):**
- ⚽ Goal scored
- 🟨 Yellow card issued
- 🟥 Red card issued
- 🔄 Substitution made
- 🏁 Match finished

You can also configure a quiet-hours window. Notifications are suppressed
during that window, while events and sensor updates continue normally.

Example notification: `"⚽ GOAL! Kramer (34') — Feyenoord 1 - 0 Sparta Rotterdam"`

### Alternative: Automations with Events

If you prefer more control, use Home Assistant automations with the exposed events instead:

---

## 🔔 Automations with Events

### Notification 15 minutes before kick-off

```yaml
alias: Football - Match starting soon
trigger:
  - platform: template
    value_template: >
      {{ state_attr('sensor.soccer_live_next_ned_1_feyenoord_rotterdam', 'next_match_minutes_until') == 15 }}
condition:
  - condition: template
    value_template: >
      {{ state_attr('sensor.soccer_live_next_ned_1_feyenoord_rotterdam', 'next_match_status') == 'pre' }}
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚽ Match starts in 15 min!"
      message: >
        {{ state_attr('sensor.soccer_live_next_ned_1_feyenoord_rotterdam', 'next_match_home_team') }}
        vs {{ state_attr('sensor.soccer_live_next_ned_1_feyenoord_rotterdam', 'next_match_away_team') }}
mode: single
```

### Notification on kick-off

```yaml
alias: Football - Match started
trigger:
  - platform: event
    event_type: soccer_live_match_started
condition:
  - condition: template
    value_template: >
      {{ trigger.event.data.home_team == 'Feyenoord Rotterdam'
         or trigger.event.data.away_team == 'Feyenoord Rotterdam' }}
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "🟢 Match started!"
      message: >
        {{ trigger.event.data.home_team }} vs {{ trigger.event.data.away_team }}
        — {{ trigger.event.data.venue }}
mode: single
```

### Notification on goal

```yaml
alias: Football - Goal notification
trigger:
  - platform: event
    event_type: soccer_live_goal
    event_data:
      team: Feyenoord Rotterdam   # omit to receive for all teams
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚽ GOAL!"
      message: >
        {% set m = trigger.event.data.minute %}
        {{ trigger.event.data.player }}{{ " (" ~ m ~ "')" if m and m != 'N/A' else '' }} —
        {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
mode: queued
```

### Notification on yellow or red card

```yaml
alias: Football - Card notification
trigger:
  - platform: event
    event_type: soccer_live_yellow_card
  - platform: event
    event_type: soccer_live_red_card
action:
  - service: notify.mobile_app_my_phone
    data:
      title: >
        {{ '🟥 RED CARD!' if trigger.event_type == 'soccer_live_red_card' else '🟨 Yellow card' }}
      message: >
        {{ trigger.event.data.player }} ({{ trigger.event.data.minute }}')
        — {{ trigger.event.data.home_team }} vs {{ trigger.event.data.away_team }}
mode: queued
```

### Notification on substitution

```yaml
alias: Football - Substitution
trigger:
  - platform: event
    event_type: soccer_live_substitution
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "🔄 Substitution"
      message: >
        {{ trigger.event.data.player }} ({{ trigger.event.data.team }})
        minute {{ trigger.event.data.minute }}'
        — {{ trigger.event.data.home_team }} vs {{ trigger.event.data.away_team }}
mode: queued
```

### Notification on full time

```yaml
alias: Football - Final score
trigger:
  - platform: event
    event_type: soccer_live_match_finished
condition:
  - condition: or
    conditions:
      - condition: template
        value_template: "{{ trigger.event.data.home_team == 'Feyenoord Rotterdam' }}"
      - condition: template
        value_template: "{{ trigger.event.data.away_team == 'Feyenoord Rotterdam' }}"
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⏹️ Full time"
      message: >
        {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
        {% if trigger.event.data.goal_scorers_str != 'N/A' %}
        · Scorers: {{ trigger.event.data.goal_scorers_str }}
        {% endif %}
mode: single
```

### Filter by competition

```yaml
# Eredivisie events only
condition:
  - condition: template
    value_template: "{{ trigger.event.data.competition_code == 'ned.1' }}"

# Or by league name
condition:
  - condition: template
    value_template: "{{ trigger.event.data.league_name == 'Dutch Eredivisie' }}"
```

### Big score alert (4+ goals in match)

```yaml
alias: Football - High scoring match
trigger:
  - platform: event
    event_type: soccer_live_goal
condition:
  - condition: template
    value_template: >
      {{ (trigger.event.data.home_score | int(0)) + (trigger.event.data.away_score | int(0)) >= 4 }}
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "🔥 High-scoring match!"
      message: >
        {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
mode: queued
```

### Draw alert

```yaml
alias: Football - Match ended in draw
trigger:
  - platform: event
    event_type: soccer_live_match_finished
condition:
  - condition: template
    value_template: "{{ trigger.event.data.home_score == trigger.event.data.away_score }}"
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚽ Draw!"
      message: >
        {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
mode: single
```

### Daily upcoming fixtures

```yaml
alias: Football - Today's fixtures
trigger:
  - platform: time
    at: "10:00:00"
condition:
  - condition: template
    value_template: "{{ state_attr('sensor.soccer_live_all_today', 'upcoming_matches_count') | int(0) > 0 }}"
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚽ Today's matches"
      message: >
        {{ (state_attr('sensor.soccer_live_all_today', 'matches') or [])[0:3] | map(attribute='home_team') | list | join(', ') }}
mode: single
```

### Goal by specific player

```yaml
alias: Football - Feyenoord goal by Giménez
trigger:
  - platform: event
    event_type: soccer_live_goal
    event_data:
      team: Feyenoord Rotterdam
condition:
  - condition: template
    value_template: "{{ 'Gimenez' in trigger.event.data.player }}"
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "⚽ GIMÉNEZ SCORES!"
      message: >
        {{ trigger.event.data.player }} ({{ trigger.event.data.minute }}')
        — {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
mode: queued
```

### Red card alert (any team)

```yaml
alias: Football - Red card alert
trigger:
  - platform: event
    event_type: soccer_live_red_card
action:
  - service: notify.mobile_app_my_phone
    data:
      title: "🟥 RED CARD!"
      message: >
        {{ trigger.event.data.team }} down to 10 men
        {{ trigger.event.data.player }} sent off ({{ trigger.event.data.minute }}')
        {{ trigger.event.data.home_team }} {{ trigger.event.data.home_score }}
        - {{ trigger.event.data.away_score }} {{ trigger.event.data.away_team }}
mode: queued
```

---

## 📊 Available sensor attributes

**Next match** (`next_match_*`):
`home_team`, `away_team`, `home_score`, `away_score`, `date`, `datetime_iso`, `minutes_until`, `status` (`pre`/`in`/`post`), `clock`, `period`, `venue`, `home_logo`, `away_logo`, `home_form`, `away_form`

**Live match** (`live_match_*`): same fields as `next_match_*`

**Last match** (`last_match_*`):
`home_team`, `away_team`, `home_score`, `away_score`, `date`, `venue`

**Top-level next match extras**:
`next_match_week` — competition week/round number (e.g. `"Round 30"`)

**Counters & booleans**:
`total_matches`, `live_matches_count`, `upcoming_matches_count`, `finished_matches_count`, `has_live_match`, `has_upcoming_match`, `has_recent_match`

**Schedule summary**:
`schedule_match_count`, `schedule_live_count`, `schedule_upcoming_count`, `schedule_recent_count`, `schedule_live_matches`, `schedule_upcoming_matches`, `schedule_recent_matches`

**Automation-friendly last event attributes**:
`last_event`, `last_event_type`, `last_event_timestamp`, `last_goal_event`, `last_card_event`, `last_match_started_event`, `last_match_finished_event`

**Health/debug attributes**:
`api_status`, `last_successful_update`, `last_error`, `request_count`, `last_request_time`, `sensor_type`, `start_date`, `end_date`, `provider`, `provider_capabilities`, `api_football_season`, `api_football_quota`

**Provider capabilities**: the `provider_capabilities` attribute lists what the selected provider can supply, so cards and automations can adapt. ESPN: `fixtures`, `scores`, `standings`, `top_scorers`, `news`, `brackets`, `lineups`, `statistics`, `head_to_head`. API-Football also adds `top_assists`, `predictions`, `odds`, `injuries` and `xg` (but not `news`/`brackets`).

---

## 📅 Calendar

Each config entry also creates a **calendar entity** (`calendar.soccer_live_<team>`) with the team's/competition's fixtures as events (kick-off time, `Home - Away` title, venue as location, competition as description; finished matches include the score). It reuses the match data the sensors already fetch — no extra polling — so the fixtures show up in the Home Assistant calendar and can drive time-based automations (e.g. a **Calendar** trigger a set time before an event starts).

---

## 📡 Available events

| Event | Fired when | Key fields |
|---|---|---|
| `soccer_live_match_started` | Kick-off (pre → in) | `home_team`, `away_team`, `venue`, `date`, `league_name`, `competition_code` |
| `soccer_live_goal` | Goal scored | `team`, `player`, `minute`, `home_score`, `away_score`, `league_name`, `competition_code` |
| `soccer_live_yellow_card` | Yellow card | `player`, `minute`, `team`, `home_team`, `away_team`, `league_name` |
| `soccer_live_red_card` | Red card | `player`, `minute`, `team`, `home_team`, `away_team`, `league_name` |
| `soccer_live_substitution` | Substitution | `player`, `minute`, `team`, `home_team`, `away_team`, `league_name` |
| `soccer_live_match_finished` | Full time | `home_score`, `away_score`, `goal_scorers`, `goal_scorers_str`, `league_name` |
| `soccer_live_lineup_available` | A fixture publishes its lineup for the first time | `event_id`, `home_team`, `away_team`, `home_players`, `away_players` |
| `soccer_live_club_change` | A daily club snapshot changes | `type`, `team_id`, `player`/`name`, optional `delta` |
| `soccer_live_transfer_added` | A new transfer appears | `team_id`, `player`, `direction` |
| `soccer_live_injury_added` / `soccer_live_player_available` | A player becomes unavailable/available | `team_id`, `player` |
| `soccer_live_coach_changed` | The published head coach changes | `team_id`, `name`, `previous` |

Example automation blueprints are available in [`blueprints/automation`](blueprints/automation):
goal, yellow card, red card, substitution, match started, full time (final score)
and a configurable kick-off reminder (choose how many minutes before kick-off).

---

## 🗂️ Sensor attribute data contract

These attributes are guaranteed to be present when available. Card developers can rely on this structure.

### Full match object (inside `matches`, `next_match`)

| Attribute | Type | Description |
|---|---|---|
| `home_team` / `away_team` | string | Team names |
| `home_abbrev` / `away_abbrev` | string | Team abbreviations |
| `home_logo` / `away_logo` | string | Logo URLs |
| `home_color` / `away_color` | string | ESPN team colors when available |
| `home_score` / `away_score` | int\|str | Score or `N/A` |
| `home_form` / `away_form` | string | Recent form string, e.g. `WDWLW` |
| `state` | string | `pre` / `in` / `post` |
| `date` | string | `DD-MM-YYYY HH:MM` (localized display) |
| `date_iso` | string | Raw ISO kickoff timestamp (used for kickoff-time weather) |
| `venue` / `venue_city` | string | Stadium info |
| `league_name` / `league_logo` | string | Resolved league identity for mixed/all sensors |
| `competition_name` / `competition_logo` | string | Competition identity |
| `season_info` | string | Season phase slug, e.g. `round-of-16` |
| `broadcasts` | list | TV/streaming channels |
| `neutral_site` | bool | Neutral venue |
| `attendance` | int | Stadium attendance |
| `links` | dict | ESPN links: `stats`, `commentary`, `video`, `summary` |
| `has_stats` | bool | Boxscore available |
| `has_commentary` | bool | Play-by-play available |
| `clock` | string | Match clock (live) |
| `league_info` | list | Competition metadata: `name`, `abbreviation`, `logo_href`, `startDate`, `endDate` |
| `home_statistics` / `away_statistics` | dict | Per-team stats; includes `expectedGoals` (xG) when the provider supplies it |

#### API-Football pre-match enrichment (next upcoming match only)

These are attached to the nearest upcoming match, and **only when real data exists** (they populate close to competitive matches — generally not friendlies or far-out fixtures):

| Attribute | Type | Description |
|---|---|---|
| `prediction` | dict | `percent_home` / `percent_draw` / `percent_away` (int %), `advice`, `winner_name`, `winner_comment` |
| `injuries_home` / `injuries_away` | list | Absentees: `player`, `reason`, `type`, `suspended` (bool) |
| `odds` | dict | Averaged Match-Winner odds: `home` / `draw` / `away` (float), `bookmaker_count` |
| `home_rank` / `away_rank` | int | League position (structured, so cards can localize the label) |
| `home_points` / `away_points` | int | League points |
| `head_to_head` | list | Up to 8 completed meetings, newest first; shared for 24 hours per unique team pairing |

### Compact match objects (`previous_matches`)

The 10 most-recently finished matches for a team sensor. Subset of the full match object:

| Attribute | Type | Description |
|---|---|---|
| `home_team` / `away_team` | string | Team names |
| `home_abbrev` / `away_abbrev` | string | Abbreviations |
| `home_logo` / `away_logo` | string | Logo URLs |
| `home_color` / `away_color` | string | Team colors |
| `home_score` / `away_score` | int\|str | Final scores |
| `state` | string | Always `post` |
| `date` | string | `DD-MM-YYYY HH:MM` |
| `league_name` | string | Competition name |
| `season_info` | string | Season phase slug (e.g. `round-of-16`) |

### Compact match objects (`upcoming_matches`)

Up to 4 upcoming/live matches after the primary next match. Subset of the full match object:

| Attribute | Type | Description |
|---|---|---|
| `home_team` / `away_team` | string | Team names |
| `home_abbrev` / `away_abbrev` | string | Abbreviations |
| `home_logo` / `away_logo` | string | Logo URLs |
| `home_color` / `away_color` | string | Team colors |
| `home_score` / `away_score` | int\|str | Scores (live) |
| `state` | string | `pre` or `in` |
| `date` | string | `DD-MM-YYYY HH:MM` |
| `clock` | string | Match clock (live) |
| `event_id` | string | ESPN event ID |
| `head_to_head` | list | Last 3 H2H matches |
| `home_form` / `away_form` | string | Recent form string, e.g. `WDWLW` — empty string when ESPN does not supply form data |
| `league_name` | string | Competition name |

### League name and logo resolution

ESPN uses different data shapes per endpoint. The parser resolves per-match
league identity in this order:

1. `competition.league` or event-level `league`
2. top-level `leagues[]` matched by league ID
3. the `l:` part from competition/event `uid`
4. `altGameNote` before the comma, e.g. `FIFA World Cup, Group F`
5. curated logo overrides for common international competitions

The integration intentionally does not guess arbitrary ESPN CDN logo URLs from
league IDs, because many IDs do not match the logo file number.

### Enriched team_match sensor

Available after kick-off when `enable_summary_enrichment` is on:

| Attribute | Type | Description |
|---|---|---|
| `home_statistics` / `away_statistics` | dict | Raw ESPN stat keys → values |
| `key_events` | list | Goals, cards, subs with `clock`, `type`, `team`, `athletes` |
| `lineup_home` / `lineup_away` | list | Players with `position`, `jersey`, `headshot` |
| `head_to_head` | list | Recent H2H matches (ESPN summary or API-Football H2H endpoint) |
| `home_standing_summary` / `away_standing_summary` | string | League position |
| `home_record_summary` / `away_record_summary` | string | Season record |
| `last_five_home` / `last_five_away` | string | Form string (e.g. `WDWLW`) |

### Top-level computed attributes (next_match_* sensors)

`next_match_home_team`, `next_match_away_team`, `next_match_home_abbrev`, `next_match_away_abbrev`, `next_match_home_color`, `next_match_away_color`, `team_colors`, `next_match_date`, `next_match_datetime_iso`, `next_match_minutes_until`, `next_match_status`, `next_match_venue`, `next_match_broadcasts`, `next_match_broadcast_count`, `next_match_event_id`, `next_match_event_count`, `next_match_h2h_count`, `next_match_has_stats`, `next_match_has_commentary`, `next_match_links`, `next_match_attendance`, `next_match_neutral_site`

### Top-level live match attributes

`live_match_home_team`, `live_match_away_team`, `live_match_home_abbrev`, `live_match_away_abbrev`, `live_match_home_color`, `live_match_away_color`, `team_colors`, `live_match_date`, `live_match_status`, `live_match_venue`, `live_match_clock`, `live_match_event_id`, `live_match_event_count`, `live_match_h2h_count`

### Schedule summary attributes

`schedule_live_matches`, `schedule_upcoming_matches` and `schedule_recent_matches` contain compact match objects with: `event_id`, `date`, `state`, `clock`, team names/abbreviations/logos/colors, scores, `venue`, `league_name`, `league_logo`, `season_info`, and `broadcasts`.

### Automation attributes

`last_event` always contains the latest fired Soccer Live event payload plus `event_type` and `timestamp`. Typed convenience attributes are populated for the latest matching event category: `last_goal_event`, `last_card_event`, `last_match_started_event`, `last_match_finished_event`.

---

## 📜 License

GPL-3.0 — data via ESPN public APIs or API-Football when configured with your own key.
