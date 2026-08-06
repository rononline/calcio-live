"""Cross-provider event reconciliation.

When two config entries track the same team via different providers (e.g. ESPN
and API-Football), the same real-world event is reported twice. The stable
``event_uid`` from event_contract lets us recognise that: the first provider to
report fires the event (``confidence: single_source``); a second provider that
reports the same ``event_uid`` within a short window is not fired again — instead
a ``soccer_live_event_corroborated`` signal is emitted so automations can act on
high-confidence events without receiving duplicates.

``TeamReconciler`` is pure (no Home Assistant) so it can be unit-tested; the
registry helper only reaches into ``hass.data``.
"""
from __future__ import annotations

from dataclasses import dataclass

# How far apart (seconds, monotonic) two providers may report the same event and
# still be treated as the same real-world event.
DEFAULT_WINDOW = 120.0
# Hard cap on remembered event_uids per team, so a long-running process stays
# bounded even if pruning by window lags.
_MAX_TRACKED = 2000

# Reconcilers are shared across config entries for the same team, so they live
# under their own hass.data key (not per-entry).
_STORE_KEY = "soccer_live_reconcilers"


@dataclass
class Decision:
    """Outcome of observing one event from one provider."""

    fire: bool                 # emit the original event now
    corroborated: bool         # a second provider confirmed an already-fired event
    confidence: str            # "single_source" | "corroborated"
    sources: list[str]         # providers that reported this event_uid so far
    event_type: str | None = None  # the original event type, when corroborated


class TeamReconciler:
    """Track which providers reported each event_uid for one team."""

    def __init__(self) -> None:
        # event_uid -> {"ts": float, "event_type": str, "providers": set[str]}
        self._seen: dict[str, dict] = {}

    def observe(self, event_uid, event_type, provider, now, window=DEFAULT_WINDOW) -> Decision:
        provider = provider or "unknown"
        # Without a stable identity we can't reconcile — always fire.
        if not event_uid:
            return Decision(True, False, "single_source", [provider])

        self._prune(now, window)
        record = self._seen.get(event_uid)
        if record is None:
            self._seen[event_uid] = {"ts": now, "event_type": event_type, "providers": {provider}}
            return Decision(True, False, "single_source", [provider])

        # Same provider reporting again within the window (per-entry dedup should
        # already prevent this) — suppress without a new corroboration.
        if provider in record["providers"]:
            return Decision(False, False, "single_source", sorted(record["providers"]))

        # A different provider confirms an event we already fired.
        record["providers"].add(provider)
        record["ts"] = now
        return Decision(False, True, "corroborated", sorted(record["providers"]), record["event_type"])

    def _prune(self, now, window) -> None:
        expired = [uid for uid, rec in self._seen.items() if now - rec["ts"] > window]
        for uid in expired:
            del self._seen[uid]
        if len(self._seen) > _MAX_TRACKED:
            newest = sorted(self._seen.items(), key=lambda item: item[1]["ts"], reverse=True)[:_MAX_TRACKED]
            self._seen = dict(newest)


def get_reconciler(hass, team_key: str) -> TeamReconciler:
    """Return the shared reconciler for a team, creating it on first use."""
    store = hass.data.setdefault(_STORE_KEY, {})
    reconciler = store.get(team_key)
    if reconciler is None:
        reconciler = TeamReconciler()
        store[team_key] = reconciler
    return reconciler
