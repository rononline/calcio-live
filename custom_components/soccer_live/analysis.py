"""Provider-neutral preview, momentum and post-match analysis helpers."""

from __future__ import annotations

import re


def _present(value) -> bool:
    return value not in (None, "", [], {}, "N/A", "Unknown", "unknown", "-")


def _minute(item) -> int | None:
    raw = item.get("minute") or item.get("clock") or item.get("time")
    match = re.search(r"\d+", str(raw or ""))
    return int(match.group()) if match else None


def _event_type(item) -> str:
    return " ".join(
        str(item.get(key) or "")
        for key in ("type", "type_text", "short_text", "detail")
    ).casefold()


def _is_goal(item) -> bool:
    kind = _event_type(item)
    invalid = any(word in kind for word in ("missed", "cancel", "disallow"))
    return not invalid and (bool(item.get("scoring_play")) or "goal" in kind)


def _side(item, match) -> str | None:
    team_id = str(item.get("team_id") or "")
    if team_id and team_id == str(match.get("home_id") or ""):
        return "home"
    if team_id and team_id == str(match.get("away_id") or ""):
        return "away"
    team = str(item.get("team") or "").casefold()
    home = str(match.get("home_team") or "").casefold()
    away = str(match.get("away_team") or "").casefold()
    if team and (team in home or home in team):
        return "home"
    if team and (team in away or away in team):
        return "away"
    return None


def match_momentum(match: dict | None) -> dict | None:
    """Build five-minute pressure buckets from observable attacking events."""
    if not isinstance(match, dict):
        return None
    weights = {
        "goal": 5,
        "penalty": 3,
        "on_target": 3,
        "shot": 2,
        "corner": 1,
    }
    buckets = {}
    signals = 0
    for event in match.get("key_events") or []:
        if not isinstance(event, dict):
            continue
        minute = _minute(event)
        side = _side(event, match)
        if minute is None or side is None:
            continue
        kind = _event_type(event)
        if _is_goal(event):
            weight, signal = weights["goal"], "goal"
        elif "penalty" in kind:
            weight, signal = weights["penalty"], "penalty"
        elif "on target" in kind or "on_target" in kind:
            weight, signal = weights["on_target"], "shot_on_target"
        elif "shot" in kind or "attempt" in kind:
            weight, signal = weights["shot"], "shot"
        elif "corner" in kind:
            weight, signal = weights["corner"], "corner"
        else:
            continue
        bucket = min(120, (minute // 5) * 5)
        row = buckets.setdefault(bucket, {"minute": bucket, "home": 0, "away": 0, "signals": []})
        row[side] += weight
        row["signals"].append(signal)
        signals += 1
    if signals < 2:
        return None
    points = []
    for row in sorted(buckets.values(), key=lambda item: item["minute"]):
        points.append({**row, "net": row["home"] - row["away"]})
    return {
        "method": "event_pressure",
        "bucket_minutes": 5,
        "signal_count": signals,
        "points": points,
    }


def _form(value):
    if isinstance(value, str):
        values = [char.upper() for char in value if char.upper() in {"W", "D", "L"}]
    elif isinstance(value, list):
        values = [str(item).upper()[:1] for item in value if str(item).upper()[:1] in {"W", "D", "L"}]
    else:
        values = []
    return values[-5:]


def preview_analysis(match: dict | None) -> dict | None:
    """Return a compact preview made only from fields present in the fixture."""
    if not isinstance(match, dict) or match.get("state") not in {"pre", "scheduled"}:
        return None
    factors = []
    home_form = _form(match.get("home_form") or match.get("form_home"))
    away_form = _form(match.get("away_form") or match.get("form_away"))
    if home_form or away_form:
        factors.append({"code": "form", "home": home_form, "away": away_form})
    home_position = match.get("home_position") or match.get("home_rank") or match.get("standing_home")
    away_position = match.get("away_position") or match.get("away_rank") or match.get("standing_away")
    if _present(home_position) or _present(away_position):
        factors.append({"code": "standings", "home": home_position, "away": away_position})
    h2h = [row for row in (match.get("head_to_head") or []) if isinstance(row, dict)]
    if h2h:
        factors.append({"code": "head_to_head", "meetings": len(h2h)})
    home_absences = match.get("injuries_home") or []
    away_absences = match.get("injuries_away") or []
    if home_absences or away_absences:
        factors.append({"code": "absences", "home": len(home_absences), "away": len(away_absences)})
    prediction = match.get("prediction")
    if _present(prediction):
        factors.append({"code": "prediction", "value": prediction})
    player = match.get("player_to_watch") or match.get("featured_player")
    if _present(player):
        factors.append({"code": "player_to_watch", "value": player})
    if not factors:
        return None
    return {
        "factor_count": len(factors),
        "factors": factors,
        "readiness": match.get("match_readiness"),
    }


def post_match_analysis(match: dict | None) -> dict | None:
    """Derive factual post-match milestones and observed standout data."""
    if not isinstance(match, dict) or match.get("state") not in {"post", "finished"}:
        return None
    goals = sorted(
        [event for event in (match.get("key_events") or []) if isinstance(event, dict) and _is_goal(event)],
        key=lambda event: (_minute(event) is None, _minute(event) or 999),
    )
    running = {"home": 0, "away": 0}
    milestones = []
    previous_leader = None
    for index, goal in enumerate(goals):
        side = _side(goal, match)
        if side is None:
            continue
        running[side] += 1
        leader = "home" if running["home"] > running["away"] else "away" if running["away"] > running["home"] else None
        if index == 0:
            code = "opening_goal"
        elif leader is None:
            code = "equalizer"
        elif previous_leader and leader != previous_leader:
            code = "lead_change"
        else:
            code = "goal"
        milestones.append({
            "code": code,
            "minute": _minute(goal),
            "team": goal.get("team"),
            "player": goal.get("player"),
            "score": f'{running["home"]}-{running["away"]}',
        })
        if leader:
            previous_leader = leader
    try:
        home_score = int(match.get("home_score"))
        away_score = int(match.get("away_score"))
    except (TypeError, ValueError):
        home_score = away_score = None
    winner = "home" if home_score is not None and home_score > away_score else "away" if home_score is not None and away_score > home_score else None
    decisive = None
    if winner:
        for index, milestone in enumerate(milestones):
            score = milestone["score"].split("-")
            leader = "home" if int(score[0]) > int(score[1]) else "away" if int(score[1]) > int(score[0]) else None
            later_equalizer = any(item["code"] == "equalizer" for item in milestones[index + 1:])
            if leader == winner and not later_equalizer:
                decisive = {**milestone, "code": "decisive_goal"}
                break
    standout = match.get("player_of_the_match")
    if not _present(standout):
        standout = None
    if not milestones and not standout and home_score is None:
        return None
    return {
        "score": f"{home_score}-{away_score}" if home_score is not None else None,
        "winner": winner or "draw",
        "milestones": milestones,
        "turning_point": decisive or (milestones[-1] if milestones else None),
        "player_of_the_match": standout,
        "home_xg": _stat(match.get("home_statistics"), ("expectedGoals", "expected_goals", "xg")),
        "away_xg": _stat(match.get("away_statistics"), ("expectedGoals", "expected_goals", "xg")),
    }


def _stat(statistics, keys):
    if not isinstance(statistics, dict):
        return None
    lowered = {str(key).casefold().replace(" ", "_"): value for key, value in statistics.items()}
    for key in keys:
        value = lowered.get(str(key).casefold().replace(" ", "_"))
        if _present(value):
            return value
    return None


def annotate_match_analysis(matches) -> list[dict]:
    """Attach only the analyses supported by each match payload."""
    output = []
    for original in matches or []:
        if not isinstance(original, dict):
            continue
        match = dict(original)
        momentum = match_momentum(match)
        preview = preview_analysis(match)
        review = post_match_analysis(match)
        if momentum:
            match["momentum_analysis"] = momentum
        if preview:
            match["preview_analysis"] = preview
        if review:
            match["post_match_analysis"] = review
        output.append(match)
    return output


def installation_check(
    *,
    configured_entities: int,
    entities_with_data: int,
    auth_failed: bool,
    last_error: bool,
    capabilities: dict | None,
    season_transition: dict | None,
    quota_plan: dict | None,
) -> dict:
    """Build an actionable first-install checklist for the Setup sensor."""
    capabilities = capabilities or {}
    checks = [
        {"code": "configuration", "status": "pass" if configured_entities else "pending"},
        {"code": "authentication", "status": "fail" if auth_failed else "pass"},
        {"code": "provider_data", "status": "pass" if entities_with_data else "fail" if last_error else "pending"},
        {"code": "fixtures", "status": "pass" if (capabilities.get("fixtures") or {}).get("available") else "pending"},
        {"code": "season", "status": "fail" if (season_transition or {}).get("status") == "stale" else "pass"},
        {"code": "quota", "status": "fail" if (quota_plan or {}).get("quota_level") == "exhausted" else "warning" if (quota_plan or {}).get("quota_level") in {"critical", "constrained"} else "pass"},
    ]
    passed = sum(item["status"] == "pass" for item in checks)
    failures = [item["code"] for item in checks if item["status"] == "fail"]
    warnings = [item["code"] for item in checks if item["status"] == "warning"]
    return {
        "status": "action_required" if failures else "warning" if warnings else "ready" if passed == len(checks) else "initializing",
        "score": round(100 * passed / len(checks)),
        "checks": checks,
        "failures": failures,
        "warnings": warnings,
    }
