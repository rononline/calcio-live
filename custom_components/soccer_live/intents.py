"""Assist / conversation intents for Soccer Live.

Provider-neutral and localised: the response builders are pure (they take a list
of sensor attribute dicts, not Home Assistant), so they can be unit-tested
without a running HA. The IntentHandler wrappers only adapt hass.states to that.
"""
from __future__ import annotations

import re
import unicodedata
from typing import ClassVar

INTENT_NEXT_MATCH = "SoccerLiveNextMatch"
INTENT_SCORE = "SoccerLiveScore"
INTENT_STANDING = "SoccerLiveStanding"

# Weekday names for the "when" phrase, indexed by datetime.weekday() (Mon=0).
_WEEKDAYS = {
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
    "nl": ["maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"],
}

_RESPONSES = {
    "en": {
        "which_team": "Which team do you mean?",
        "unknown_team": "I don't track a team called {team}.",
        "no_next": "{team} have no upcoming match scheduled.",
        "next_home": "{team} play {opponent} at home, {when}.",
        "next_away": "{team} play away at {opponent}, {when}.",
        "score_live": "{team} are playing {opponent}: {home}–{away}, {clock}.",
        "score_recent": "{team} {result} {home}–{away} against {opponent}.",
        "score_none": "I have no recent match for {team}.",
        "result_won": "won", "result_lost": "lost", "result_draw": "drew",
        "standing": "{team} are {rank} with {points} points.",
        "standing_none": "I don't have a league standing for {team}.",
    },
    "nl": {
        "which_team": "Welk team bedoel je?",
        "unknown_team": "Ik volg geen team dat {team} heet.",
        "no_next": "{team} heeft geen geplande wedstrijd.",
        "next_home": "{team} speelt thuis tegen {opponent}, {when}.",
        "next_away": "{team} speelt uit bij {opponent}, {when}.",
        "score_live": "{team} speelt tegen {opponent}: {home}–{away}, {clock}.",
        "score_recent": "{team} {result} met {home}–{away} van {opponent}.",
        "score_none": "Ik heb geen recente wedstrijd voor {team}.",
        "result_won": "won", "result_lost": "verloor", "result_draw": "speelde gelijk",
        "standing": "{team} staat {rank} met {points} punten.",
        "standing_none": "Ik heb geen competitiestand voor {team}.",
    },
}


def _lang(language: str | None) -> str:
    code = str(language or "en").split("-")[0].lower()
    return code if code in _RESPONSES else "en"


def _normalize(name) -> str:
    text = unicodedata.normalize("NFKD", str(name or ""))
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _team_sensors(sensors, sensor_type):
    return [s for s in sensors if isinstance(s, dict) and s.get("sensor_type") == sensor_type]


def _match_team(sensors, team, sensor_type):
    """Pick the sensor attributes for the requested team.

    Returns (attributes, resolved_team_name) or (None, reason) where reason is
    "which_team" (ambiguous, no team given) or "unknown_team" (no match)."""
    candidates = _team_sensors(sensors, sensor_type)
    if not team:
        names = {s.get("team_name") for s in candidates if s.get("team_name")}
        if len(names) == 1:
            only = candidates[0]
            return only, only.get("team_name")
        return None, "which_team"
    wanted = _normalize(team)
    for s in candidates:
        name = _normalize(s.get("team_name"))
        if name and (name == wanted or wanted in name or name in wanted):
            return s, s.get("team_name")
    return None, "unknown_team"


def _when(match, lang) -> str:
    # The `date` attribute is already in HA-local display form "dd-mm-yyyy hh:mm".
    raw = str(match.get("date") or "")
    found = re.match(r"(\d{2})-(\d{2})-(\d{4})\s+(\d{2}):(\d{2})", raw)
    if not found:
        return raw
    day, month, year, hour, minute = (int(x) for x in found.groups())
    try:
        import datetime
        weekday = datetime.date(year, month, day).weekday()
        return f"{_WEEKDAYS.get(lang, _WEEKDAYS['en'])[weekday]} {hour:02d}:{minute:02d}"
    except (ValueError, IndexError):
        return raw


def _score(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def next_match_response(sensors, team, language=None) -> str:
    lang = _lang(language)
    r = _RESPONSES[lang]
    attrs, resolved = _match_team(sensors, team, "team_match")
    if attrs is None:
        return r[resolved].format(team=team or "")
    match = attrs.get("next_match") or (attrs.get("matches") or [None])[0]
    if not match or match.get("state") not in ("pre", None):
        # No upcoming match (already live/finished counts as "no upcoming").
        upcoming = next((m for m in (attrs.get("matches") or []) if m.get("state") == "pre"), None)
        if not upcoming:
            return r["no_next"].format(team=resolved)
        match = upcoming
    home = match.get("home_team") or ""
    away = match.get("away_team") or ""
    is_home = _normalize(home) == _normalize(resolved)
    opponent = away if is_home else home
    key = "next_home" if is_home else "next_away"
    return r[key].format(team=resolved, opponent=opponent, when=_when(match, lang))


def score_response(sensors, team, language=None) -> str:
    lang = _lang(language)
    r = _RESPONSES[lang]
    attrs, resolved = _match_team(sensors, team, "team_match")
    if attrs is None:
        return r[resolved].format(team=team or "")
    matches = attrs.get("matches") or []
    live = next((m for m in matches if m.get("state") == "in"), None)
    if live:
        home = _normalize(live.get("home_team")) == _normalize(resolved)
        opponent = live.get("away_team") if home else live.get("home_team")
        clock = live.get("clock") if live.get("clock") not in (None, "", "N/A") else ""
        return r["score_live"].format(
            team=resolved, opponent=opponent,
            home=live.get("home_score", "?"), away=live.get("away_score", "?"), clock=clock,
        )
    finished = [m for m in matches if m.get("state") == "post"]
    finished.sort(key=lambda m: str(m.get("date_iso") or m.get("date") or ""))
    if not finished:
        return r["score_none"].format(team=resolved)
    last = finished[-1]
    home = _normalize(last.get("home_team")) == _normalize(resolved)
    ours, theirs = (_score(last.get("home_score")), _score(last.get("away_score"))) if home \
        else (_score(last.get("away_score")), _score(last.get("home_score")))
    if ours is None or theirs is None:
        return r["score_none"].format(team=resolved)
    result = r["result_won"] if ours > theirs else r["result_lost"] if ours < theirs else r["result_draw"]
    opponent = last.get("away_team") if home else last.get("home_team")
    return r["score_recent"].format(
        team=resolved, result=result,
        home=last.get("home_score"), away=last.get("away_score"), opponent=opponent,
    )


_ORDINALS = {
    "en": lambda n: f"{n}th" if 11 <= n % 100 <= 13 else {1: f"{n}st", 2: f"{n}nd", 3: f"{n}rd"}.get(n % 10, f"{n}th"),
    "nl": lambda n: f"{n}e",
}


def standing_response(sensors, team, language=None) -> str:
    lang = _lang(language)
    r = _RESPONSES[lang]
    # Standing lives on the team_match sensor (home_standing_summary) or a
    # standings sensor. Prefer the compact per-team summary when present.
    attrs, resolved = _match_team(sensors, team, "team_match")
    if attrs is None:
        return r[resolved].format(team=team or "")
    summary = attrs.get("home_standing_summary") or {}
    rank = summary.get("rank")
    points = summary.get("points")
    if rank is None or points is None:
        return r["standing_none"].format(team=resolved)
    rank_text = _ORDINALS.get(lang, _ORDINALS["en"])(int(rank))
    return r["standing"].format(team=resolved, rank=rank_text, points=points)


# --- Home Assistant IntentHandler wrappers ---------------------------------

def _collect(hass) -> list[dict]:
    return [
        dict(state.attributes)
        for state in hass.states.async_all("sensor")
        if state.attributes.get("sensor_type") and "soccer" in state.entity_id
    ]


async def async_setup_intents(hass) -> None:
    """Register the Soccer Live conversation intents (once)."""
    import voluptuous as vol
    from homeassistant.helpers import intent

    class _Handler(intent.IntentHandler):
        # slot_schema is a read-only property on the base, so it must be a class
        # attribute (it's the same for every handler). intent_type is a plain
        # attribute and is set per instance.
        slot_schema: ClassVar = {vol.Optional("team"): str}

        def __init__(self, intent_name, builder):
            self.intent_type = intent_name
            self._builder = builder

        async def async_handle(self, intent_obj):
            slots = self.async_validate_slots(intent_obj.slots)
            team = slots.get("team", {}).get("value")
            text = self._builder(_collect(intent_obj.hass), team, intent_obj.language)
            response = intent_obj.create_response()
            response.async_set_speech(text)
            return response

    for name, builder in (
        (INTENT_NEXT_MATCH, next_match_response),
        (INTENT_SCORE, score_response),
        (INTENT_STANDING, standing_response),
    ):
        intent.async_register(hass, _Handler(name, builder))
