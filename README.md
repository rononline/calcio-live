# ⚽ Soccer Live — Home Assistant Integration

Real-time football data in Home Assistant via ESPN, with optional API-Football support for users who provide their own API key.

> Built on ideas from [Calcio Live](https://github.com/Bobsilvio/calcio-live) by @Bobsilvio

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
| `max_matches` | `0` (unlimited) | Limit the number of matches stored per sensor (5 / 10 / 15 / 20 / 30). Useful to reduce state size on large sensors. |

---

## 🌐 Data providers

ESPN is the default provider and does not require an API key. API-Football can be selected during setup and requires your own API-Football key.

Current API-Football support:
- Team fixtures: `team_match`, `team_matches`, `team_matches_mixed`
- Competition fixtures: `match_day`
- `all_matches_today`
- `standings`
- `top_scorers`
- Optional match enrichment for `team_match`, `team_matches` and `team_matches_mixed` via fixture events, statistics and lineups

API-Football news and knockout brackets are not supported yet. News and bracket sensors remain ESPN-only.

The integration caches API-Football calls to reduce quota use:
- Main fixture/standings/scorers responses are shared by URL for up to 60 seconds. While a match is live, this cache follows `live_scan_interval` when that value is lower than 60 seconds.
- Fixture events are cached for 30 seconds.
- Fixture statistics and lineups are cached for 5 minutes.
- The `api_football_quota` diagnostic attribute is refreshed through API-Football `/status` every 30 minutes.

For API-Football team sensors, search teams directly by name during setup. Labels include the API-Football ID, because these IDs are different from ESPN IDs.

---

## ⚙️ Exclude from recorder

Add this to `configuration.yaml` to avoid database warnings:

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

**Notifications sent for:**
- ⚽ Goal scored
- 🟨 Yellow card issued
- 🟥 Red card issued
- 🔄 Substitution made
- 🏁 Match finished

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
`api_status`, `last_successful_update`, `last_error`, `request_count`, `last_request_time`, `sensor_type`, `start_date`, `end_date`

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

Example automation blueprints are available in [`blueprints/automation`](blueprints/automation):
goal notification, red card notification and match started notification.

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
| `date` | string | `DD-MM-YYYY HH:MM` |
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

### Enriched team_match sensor (via summary endpoint)

Available after kick-off when `enable_summary_enrichment` is on:

| Attribute | Type | Description |
|---|---|---|
| `home_statistics` / `away_statistics` | dict | Raw ESPN stat keys → values |
| `key_events` | list | Goals, cards, subs with `clock`, `type`, `team`, `athletes` |
| `lineup_home` / `lineup_away` | list | Players with `position`, `jersey`, `headshot` |
| `head_to_head` | list | Recent H2H matches |
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
