"""Shared per-config-entry runtime state for Soccer Live entities.

Provider endpoints remain independently scheduled because they have different
cadences and payloads. This coordinator centralises entry-wide fetching state,
sensor registration and manual refreshes without changing those proven polling
semantics.
"""

from __future__ import annotations

from collections.abc import Callable


class SoccerLiveEntryCoordinator:
    """Coordinate entities and observable refresh state for one config entry."""

    def __init__(self, hass, entry_id: str):
        self.hass = hass
        self.entry_id = entry_id
        self.is_fetching = False
        self._active_fetches = 0
        self._entities = set()
        self._listeners: set[Callable] = set()

    def register_entity(self, entity) -> Callable:
        self._entities.add(entity)

        def remove():
            self._entities.discard(entity)

        return remove

    def add_listener(self, listener: Callable) -> Callable:
        self._listeners.add(listener)

        def remove():
            self._listeners.discard(listener)

        return remove

    def _notify(self):
        for listener in tuple(self._listeners):
            listener()

    def begin_fetch(self):
        self._active_fetches += 1
        if not self.is_fetching:
            self.is_fetching = True
            self._notify()

    def end_fetch(self):
        self._active_fetches = max(0, self._active_fetches - 1)
        fetching = self._active_fetches > 0
        if fetching != self.is_fetching:
            self.is_fetching = fetching
            self._notify()

    async def async_refresh(self):
        """Request an immediate refresh from all entities in this entry."""
        for entity in tuple(self._entities):
            entity.async_schedule_update_ha_state(force_refresh=True)
        return len(self._entities)

    async def async_replace_archive(self, matches):
        """Replace the shared archive and publish it on every entry sensor."""
        updated = 0
        for entity in tuple(self._entities):
            replace = getattr(entity, "async_replace_archive", None)
            if replace is not None:
                await replace(matches)
                updated += 1
        return updated

    async def async_rebuild_archive(self):
        """Rebuild the archive from the richest currently published match list."""
        best = []
        entry_data = self.hass.data.get("soccer_live", {}).get(self.entry_id, {})
        for matches in entry_data.get("match_sources", {}).values():
            if isinstance(matches, list) and len(matches) > len(best):
                best = matches
        from .insights import update_archive

        existing = []
        for entity in tuple(self._entities):
            existing = list(getattr(entity, "_attributes", {}).get("match_archive") or [])
            if existing:
                break
        provider = next(
            (
                getattr(entity, "_provider", "unknown")
                for entity in self._entities
            ),
            "unknown",
        )
        rebuilt = update_archive(existing, best, provider, limit=500)
        await self.async_replace_archive(rebuilt)
        return len(rebuilt)

    def archive(self):
        """Return the first published archive for this entry."""
        for entity in tuple(self._entities):
            matches = getattr(entity, "_attributes", {}).get("match_archive")
            if isinstance(matches, list):
                return matches
        return []
