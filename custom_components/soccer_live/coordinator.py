"""Shared per-config-entry runtime state for Soccer Live entities.

Provider endpoints remain independently scheduled because they have different
cadences and payloads. This coordinator centralises entry-wide fetching state,
sensor registration and manual refreshes without changing those proven polling
semantics.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Callable
from datetime import datetime, timezone

_SNAPSHOT_MAX_AGE = 7 * 86400
_SNAPSHOT_EXCLUDED = {
    "club_changes",
    "last_card_event",
    "last_event",
    "last_goal_event",
    "last_match_finished_event",
    "last_match_started_event",
    "match_archive",
    "match_archive_summary",
}


class SoccerLiveEntryCoordinator:
    """Coordinate entities and observable refresh state for one config entry."""

    def __init__(self, hass, entry_id: str):
        self.hass = hass
        self.entry_id = entry_id
        self.is_fetching = False
        self._active_fetches = 0
        self._entities = set()
        self._listeners: set[Callable] = set()
        self._event_ledger: dict[str, float] = {}
        self._replay_snapshots: list[dict] = []
        self._ledger_store = None
        self._replay_store = None
        self._snapshot_store = None
        self._standings_store = None
        self._save_ledger_task = None
        self._save_replay_task = None
        self._save_snapshot_task = None
        self._save_standings_task = None
        self._ledger_dirty = False
        self._replay_dirty = False
        self._snapshot_dirty = False
        self._standings_dirty = False
        self._snapshots: dict[str, dict] = {}
        self._standings_histories: dict[str, list[dict]] = {}
        # Entry-scoped request state. Sensors keep their independent cadence,
        # while identical endpoint work is deduplicated here per config entry.
        self.main_cache: dict = {}
        self.fetch_locks: dict = {}
        self.api_endpoint_cache: dict = {}
        self.api_endpoint_locks: dict = {}
        self.calendar_cache: dict = {}
        self.calendar_locks: dict = {}
        self.archive_sync_status = "disabled"
        self.archive_sync_last_update = None
        self.archive_sync_last_error = None

    async def async_initialize(self):
        """Load persistent event claims and recorded replay snapshots."""
        from homeassistant.helpers.storage import Store

        from .replay import validate_replay

        self._ledger_store = Store(
            self.hass, 1, f"soccer_live_{self.entry_id}_event_ledger"
        )
        self._replay_store = Store(
            self.hass, 1, f"soccer_live_{self.entry_id}_match_replay"
        )
        self._snapshot_store = Store(
            self.hass, 1, f"soccer_live_{self.entry_id}_last_snapshot"
        )
        self._standings_store = Store(
            self.hass, 1, f"soccer_live_{self.entry_id}_standings_history"
        )
        ledger = await self._ledger_store.async_load()
        now = time.time()
        self._event_ledger = {}
        events = (ledger or {}).get("events", {})
        if isinstance(events, dict):
            for key, timestamp in events.items():
                try:
                    parsed = float(timestamp)
                except (TypeError, ValueError):
                    continue
                if now - parsed < 7 * 86400:
                    self._event_ledger[str(key)] = parsed
        replay = await self._replay_store.async_load()
        self._replay_snapshots = validate_replay(replay or {})
        stored_snapshots = await self._snapshot_store.async_load()
        self._snapshots = {}
        for key, snapshot in (stored_snapshots or {}).get("entities", {}).items():
            if not isinstance(snapshot, dict):
                continue
            captured_at = snapshot.get("captured_at")
            try:
                captured = datetime.fromisoformat(
                    str(captured_at).replace("Z", "+00:00")
                )
                if captured.tzinfo is None:
                    captured = captured.replace(tzinfo=timezone.utc)
                age = datetime.now(timezone.utc) - captured.astimezone(timezone.utc)
            except (TypeError, ValueError):
                continue
            if age.total_seconds() <= _SNAPSHOT_MAX_AGE:
                self._snapshots[str(key)] = snapshot
        stored_standings = await self._standings_store.async_load()
        histories = (stored_standings or {}).get("histories", {})
        self._standings_histories = {
            str(key): [
                item for item in history[-200:] if isinstance(item, dict)
            ]
            for key, history in histories.items()
            if isinstance(history, list)
        }

    @staticmethod
    def _snapshot_attributes(attributes) -> dict:
        """Return a JSON-safe, bounded copy of useful entity attributes."""
        source = {
            key: value
            for key, value in (attributes or {}).items()
            if key not in _SNAPSHOT_EXCLUDED
        }
        # A provider can occasionally return thousands of fixtures. Last-known
        # state is for immediate recovery, not a second archive.
        for key in ("matches", "previous_matches", "upcoming_matches"):
            if isinstance(source.get(key), list):
                source[key] = source[key][:150]
        try:
            return json.loads(json.dumps(source, default=str))
        except (TypeError, ValueError):
            return {}

    def publish_snapshot(self, key: str, state, attributes) -> None:
        """Persist the latest normalised entity snapshot for restart recovery."""
        if not key or not attributes:
            return
        self._snapshots[str(key)] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "state": state,
            "attributes": self._snapshot_attributes(attributes),
        }
        if len(self._snapshots) > 30:
            newest = sorted(
                self._snapshots.items(),
                key=lambda item: str(item[1].get("captured_at") or ""),
                reverse=True,
            )[:30]
            self._snapshots = dict(newest)
        self._snapshot_dirty = True
        if self._snapshot_store is None:
            return
        if self._save_snapshot_task and not self._save_snapshot_task.done():
            return
        self._save_snapshot_task = self.hass.async_create_task(
            self._async_save_snapshots()
        )

    async def _async_save_snapshots(self):
        while self._snapshot_dirty:
            self._snapshot_dirty = False
            await self._snapshot_store.async_save(
                {"version": 1, "entities": dict(self._snapshots)}
            )

    def snapshot(self, key: str) -> dict | None:
        snapshot = self._snapshots.get(str(key))
        return dict(snapshot) if isinstance(snapshot, dict) else None

    @property
    def snapshot_count(self) -> int:
        return len(self._snapshots)

    async def async_shutdown(self):
        """Flush coalesced storage tasks before an entry unload."""
        for task in (
            self._save_ledger_task,
            self._save_replay_task,
            self._save_snapshot_task,
            self._save_standings_task,
        ):
            if task and not task.done():
                await task

    def update_standings(self, key: str, attributes: dict) -> list[dict]:
        """Persist a bounded table trajectory for one standings entity."""
        try:
            from .insights import update_standings_history
        except ImportError:  # focused tests load this file without its package
            import importlib.util
            from pathlib import Path

            path = Path(__file__).with_name("insights.py")
            spec = importlib.util.spec_from_file_location(
                "soccer_live_insights", path
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            update_standings_history = module.update_standings_history

        key = str(key)
        current = self._standings_histories.get(key, [])
        updated = update_standings_history(current, attributes)
        if updated == current:
            return list(updated)
        self._standings_histories[key] = updated
        self._standings_dirty = True
        if self._standings_store is not None and (
            self._save_standings_task is None or self._save_standings_task.done()
        ):
            self._save_standings_task = self.hass.async_create_task(
                self._async_save_standings()
            )
        return list(updated)

    async def _async_save_standings(self):
        while self._standings_dirty:
            self._standings_dirty = False
            await self._standings_store.async_save({
                "version": 2,
                "histories": {
                    key: list(history)
                    for key, history in self._standings_histories.items()
                },
            })

    @property
    def standings_history_count(self) -> int:
        return sum(len(history) for history in self._standings_histories.values())

    def register_entity(self, entity) -> Callable:
        self._entities.add(entity)

        def remove():
            self._entities.discard(entity)

        return remove

    @property
    def entities(self):
        """Registered source entities, exposed read-only to derived platforms."""
        return tuple(self._entities)

    def add_listener(self, listener: Callable) -> Callable:
        self._listeners.add(listener)

        def remove():
            self._listeners.discard(listener)

        return remove

    def _notify(self):
        for listener in tuple(self._listeners):
            listener()

    @staticmethod
    def _ledger_key(fingerprint) -> str:
        raw = json.dumps(
            fingerprint, sort_keys=True, default=str, separators=(",", ":")
        ).encode()
        return hashlib.sha256(raw).hexdigest()

    def claim_event(self, fingerprint, ttl=7 * 86400) -> bool:
        """Persistently claim an event so restarts cannot replay notifications."""
        now = time.time()
        key = self._ledger_key(fingerprint)
        previous = self._event_ledger.get(key)
        if previous is not None and now - previous < ttl:
            return False
        self._event_ledger[key] = now
        self._event_ledger = {
            item: timestamp
            for item, timestamp in self._event_ledger.items()
            if now - timestamp < 7 * 86400
        }
        if len(self._event_ledger) > 1000:
            newest = sorted(
                self._event_ledger.items(), key=lambda item: item[1], reverse=True
            )[:1000]
            self._event_ledger = dict(newest)
        self._schedule_ledger_save()
        return True

    def _schedule_ledger_save(self):
        if self._ledger_store is None:
            return
        self._ledger_dirty = True
        if self._save_ledger_task and not self._save_ledger_task.done():
            return
        self._save_ledger_task = self.hass.async_create_task(
            self._async_save_ledger()
        )

    async def _async_save_ledger(self):
        """Coalesce rapid claims without losing the final ledger state."""
        while self._ledger_dirty:
            self._ledger_dirty = False
            await self._ledger_store.async_save({"events": dict(self._event_ledger)})

    def capture_matches(self, matches):
        """Record meaningful snapshots of the current/live fixture."""
        from .replay import compact_snapshot, replay_match, snapshot_identity

        match = replay_match(matches)
        if not match:
            return
        snapshot = compact_snapshot(match)
        if (
            self._replay_snapshots
            and snapshot_identity(self._replay_snapshots[-1])
            == snapshot_identity(snapshot)
        ):
            return
        event_id = str(snapshot.get("event_id") or "")
        current_id = (
            str(self._replay_snapshots[-1].get("event_id") or "")
            if self._replay_snapshots
            else event_id
        )
        if event_id and current_id and event_id != current_id:
            self._replay_snapshots = []
        self._replay_snapshots.append(snapshot)
        self._replay_snapshots = self._replay_snapshots[-180:]
        self._schedule_replay_save()

    def _schedule_replay_save(self):
        if self._replay_store is None:
            return
        self._replay_dirty = True
        if self._save_replay_task and not self._save_replay_task.done():
            return
        self._save_replay_task = self.hass.async_create_task(
            self._async_save_replay()
        )

    async def _async_save_replay(self):
        """Coalesce live snapshots while preserving the newest one."""
        while self._replay_dirty:
            self._replay_dirty = False
            await self._replay_store.async_save(
                {"version": 1, "snapshots": list(self._replay_snapshots)}
            )

    async def async_clear_replay(self):
        if self._save_replay_task and not self._save_replay_task.done():
            await self._save_replay_task
        self._replay_snapshots = []
        self._replay_dirty = False
        if self._replay_store:
            await self._replay_store.async_save(
                {"version": 1, "snapshots": []}
            )

    def replay(self):
        return list(self._replay_snapshots)

    @property
    def event_ledger_size(self):
        return len(self._event_ledger)

    async def async_play_replay(self, speed=20, demo=False):
        """Replay recorded snapshots as safe simulated Home Assistant events."""
        from .replay import demo_replay, replay_events

        snapshots = (
            demo_replay()
            if demo or len(self._replay_snapshots) < 2
            else list(self._replay_snapshots)
        )
        fired = 0
        previous = None
        delay = max(0.05, min(5.0, 1.0 / max(0.2, float(speed))))
        for index, snapshot in enumerate(snapshots):
            for event_type, payload in replay_events(previous, snapshot):
                self.hass.bus.async_fire(
                    event_type,
                    {**payload, "config_entry_id": self.entry_id},
                )
                fired += 1
            previous = snapshot
            if index < len(snapshots) - 1:
                await asyncio.sleep(delay)
        return fired

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

    async def async_get_match_details(self, match_id: str) -> dict | None:
        """Load one fixture on demand without duplicating provider requests."""
        from .details import find_match, has_match_details, public_match_details

        candidates = []
        for entity in tuple(self._entities):
            match = find_match(getattr(entity, "_attributes", {}), match_id)
            if match is None:
                continue
            if has_match_details(match):
                return public_match_details(match)
            candidates.append(entity)
        if not candidates:
            return None
        # The focused next-match entity is cheapest and most likely to have the
        # right competition code for an ESPN summary endpoint.
        candidates.sort(
            key=lambda entity: getattr(entity, "_sensor_type", "") != "team_match"
        )
        loader = getattr(candidates[0], "async_get_match_details", None)
        return await loader(str(match_id)) if loader else None

    async def async_replace_archive(self, matches):
        """Replace the shared archive and publish it on every entry sensor."""
        updated = 0
        for entity in tuple(self._entities):
            replace = getattr(entity, "async_replace_archive", None)
            if replace is not None:
                await replace(matches)
                updated += 1
        return updated

    async def async_sync_archive_url(self, url: str):
        """Merge a remote soccer_live.archive.v1/legacy JSON document."""
        from urllib.parse import urlparse

        parsed = urlparse(str(url or "").strip())
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Archive sync URL must use http or https")
        self.archive_sync_status = "fetching"
        self.archive_sync_last_error = None
        self._notify()
        try:
            import aiohttp
            from homeassistant.helpers.aiohttp_client import async_get_clientsession

            session = async_get_clientsession(self.hass)
            async with session.get(
                parsed.geturl(), timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                response.raise_for_status()
                if response.content_length and response.content_length > 5_000_000:
                    raise ValueError("Archive response exceeds 5 MB")
                payload = await response.json(content_type=None)
            from .archive import validate_archive

            remote = validate_archive(payload)
            merged = validate_archive([*self.archive(), *remote])
            await self.async_replace_archive(merged)
            self.archive_sync_status = "ready"
            self.archive_sync_last_update = datetime.now(timezone.utc).isoformat()
            self._notify()
            return len(remote)
        except Exception as err:
            self.archive_sync_status = "error"
            self.archive_sync_last_error = str(err)
            self._notify()
            raise

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
