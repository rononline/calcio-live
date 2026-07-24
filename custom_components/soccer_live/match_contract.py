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


# Phases that warrant their own bus event, fired on the transition into the
# phase. `match_started` (pre->in) and `match_finished` (->post) are detected
# separately by state, so they're deliberately excluded here to avoid firing an
# event twice for the same transition.
PHASE_EVENTS = {
    "halftime": "soccer_live_halftime",
    "second_half": "soccer_live_second_half",
    "postponed": "soccer_live_match_postponed",
    "cancelled": "soccer_live_match_cancelled",
}


def phase_event(phase):
    """Bus event name for a phase, or None when the phase has no own event."""
    return PHASE_EVENTS.get(phase)
