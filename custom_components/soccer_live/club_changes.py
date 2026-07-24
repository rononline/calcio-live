"""Provider-neutral club snapshot and change detection helpers."""


def _player_key(player):
    return str(player.get("id") or player.get("player_id") or player.get("name") or player.get("player") or "").strip()


def club_snapshot(club):
    club = club or {}
    squad = club.get("squad") or []
    injuries = club.get("injuries") or []
    name_to_key = {str(item.get("name") or "").strip().lower(): _player_key(item) for item in squad}
    injured = {_player_key(item) for item in squad if item.get("injured")}
    injured.update(name_to_key.get(str(item.get("player") or item.get("name") or "").strip().lower()) or _player_key(item) for item in injuries)
    transfers = {
        "|".join(str(item.get(key) or "") for key in ("player_id", "player", "date", "from", "to", "direction"))
        for item in (club.get("transfers") or [])
    }
    market_value = sum(float(item.get("market_value") or 0) for item in squad if isinstance(item.get("market_value"), (int, float)))
    return {
        "coach": str(club.get("coach") or ""),
        "squad": {_player_key(item): item.get("name") or "" for item in squad if _player_key(item)},
        "injured": {key for key in injured if key},
        "transfers": transfers,
        "market_value": market_value,
    }


def diff_club(previous_club, current_club):
    if not previous_club or not current_club:
        return []
    previous = club_snapshot(previous_club)
    current = club_snapshot(current_club)
    changes = []
    for key in sorted(current["transfers"] - previous["transfers"]):
        parts = key.split("|")
        changes.append({"type": "transfer_added", "player": parts[1] or parts[0], "direction": parts[5]})
    for key in sorted(current["injured"] - previous["injured"]):
        changes.append({"type": "injury_added", "player": current["squad"].get(key) or key})
    for key in sorted(previous["injured"] - current["injured"]):
        changes.append({"type": "player_available", "player": current["squad"].get(key) or previous["squad"].get(key) or key})
    if previous["coach"] and current["coach"] and previous["coach"] != current["coach"]:
        changes.append({"type": "coach_changed", "name": current["coach"], "previous": previous["coach"]})
    for key in sorted(current["squad"].keys() - previous["squad"].keys()):
        changes.append({"type": "squad_added", "player": current["squad"][key] or key})
    for key in sorted(previous["squad"].keys() - current["squad"].keys()):
        changes.append({"type": "squad_removed", "player": previous["squad"][key] or key})
    delta = current["market_value"] - previous["market_value"]
    threshold = max(100_000, abs(previous["market_value"]) * 0.01)
    if abs(delta) >= threshold:
        changes.append({"type": "market_value_changed", "delta": delta})
    return changes


def newly_available_lineups(previous_attrs, current_attrs):
    def matches(attrs):
        data = attrs or {}
        result = list(data.get("matches") or [])
        if data.get("next_match"):
            result.append(data["next_match"])
        return {str(item.get("event_id")): item for item in result if item.get("event_id")}

    previous = matches(previous_attrs)
    if not previous:
        return []
    available = []
    for event_id, match in matches(current_attrs).items():
        # Historical fixtures can gain lineup data when detail enrichment is
        # rebuilt after a restart. That is not a newly announced lineup.
        if match.get("state") == "post":
            continue
        has_lineup = bool(match.get("lineup_home") or match.get("lineup_away") or match.get("formation_home") or match.get("formation_away"))
        old = previous.get(event_id) or {}
        had_lineup = bool(old.get("lineup_home") or old.get("lineup_away") or old.get("formation_home") or old.get("formation_away"))
        if has_lineup and not had_lineup:
            available.append(match)
    return available
