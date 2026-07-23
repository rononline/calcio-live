"""Provider-neutral match phase and active-match helpers."""


def match_phase(match):
    match = match or {}
    state = str(match.get("state") or "").lower()
    status = " ".join(str(match.get(key) or "") for key in ("status", "period")).lower()
    if any(word in status for word in ("cancel", "abandon")):
        return "cancelled"
    if "postpon" in status:
        return "postponed"
    if state == "post":
        return "finished"
    if state == "pre":
        return "scheduled"
    if state not in ("in", "live"):
        return "unknown"
    if any(word in status for word in ("penalt", "shootout")):
        return "penalties"
    if any(word in status for word in ("extra", "aet")):
        return "extra_time"
    if any(word in status for word in ("halftime", "half time", " ht")) or status.strip() == "ht":
        return "halftime"
    if any(word in status for word in ("second", "2nd")) or str(match.get("period")) == "2":
        return "second_half"
    return "first_half"


def annotate_match(match):
    return {**(match or {}), "match_phase": match_phase(match)}


def current_match(matches):
    return next((match for match in (matches or []) if match_phase(match) in {
        "first_half", "halftime", "second_half", "extra_time", "penalties"
    }), None)
