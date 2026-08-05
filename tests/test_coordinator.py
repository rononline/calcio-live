import importlib.util
import sys
from pathlib import Path
from types import ModuleType

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "coordinator.py"
PACKAGE_NAME = "soccer_live_coordinator_test_package"
PACKAGE = ModuleType(PACKAGE_NAME)
PACKAGE.__path__ = [str(MODULE_PATH.parent)]
sys.modules[PACKAGE_NAME] = PACKAGE
SPEC = importlib.util.spec_from_file_location(
    f"{PACKAGE_NAME}.coordinator", MODULE_PATH
)
coordinator_module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = coordinator_module
SPEC.loader.exec_module(coordinator_module)


class _Entity:
    def __init__(self):
        self.refreshes = 0
        self.hass = True

    def async_schedule_update_ha_state(self, force_refresh=False):
        self.refreshes += int(force_refresh)


class _Hass:
    def __init__(self):
        self.data = {}


def test_coordinator_publishes_fetch_transitions_once():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    states = []
    coordinator.add_listener(lambda: states.append(coordinator.is_fetching))
    coordinator.begin_fetch()
    coordinator.begin_fetch()
    coordinator.end_fetch()
    coordinator.end_fetch()
    assert states == [True, False]


def test_coordinator_registers_refreshes_and_unregisters_entities():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    entity = _Entity()
    remove = coordinator.register_entity(entity)
    import asyncio

    assert asyncio.run(coordinator.async_refresh()) == 1
    assert entity.refreshes == 1
    assert coordinator.entities == (entity,)
    remove()
    assert asyncio.run(coordinator.async_refresh()) == 0


def test_coordinator_fans_out_due_adaptive_refreshes_as_one_cycle():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    first, second = _Entity(), _Entity()
    coordinator.register_entity(first)
    coordinator.register_entity(second)
    coordinator._refresh_requests = {
        first: {"deadline": 0, "interval": 30, "reason": "live"},
        second: {"deadline": 0, "interval": 60, "reason": "kickoff_soon"},
    }
    coordinator._handle_refresh_cycle(None)
    assert first.refreshes == second.refreshes == 1
    assert coordinator.refresh_cycle_count == 1
    assert coordinator.last_refresh_reasons == ["kickoff_soon", "live"]
    assert coordinator.scheduled_refresh_count == 0


def test_archive_sync_rejects_non_http_urls_before_network_access():
    import asyncio

    import pytest

    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    with pytest.raises(ValueError, match="http or https"):
        asyncio.run(coordinator.async_sync_archive_url("file:///tmp/archive.json"))


def test_coordinator_claims_event_only_once():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    assert coordinator.claim_event(("goal", "fixture-1", 1)) is True
    assert coordinator.claim_event(("goal", "fixture-1", 1)) is False
    assert coordinator.event_ledger_size == 1


def test_coordinator_keeps_entry_scoped_snapshot_and_request_state():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    coordinator.publish_snapshot(
        "sensor-key",
        "Feyenoord 1–0 Sparta",
        {
            "matches": [{"event_id": str(index)} for index in range(200)],
            "match_archive": [{"event_id": "old"}],
        },
    )
    snapshot = coordinator.snapshot("sensor-key")
    assert snapshot["state"] == "Feyenoord 1–0 Sparta"
    assert len(snapshot["attributes"]["matches"]) == 150
    assert "match_archive" not in snapshot["attributes"]
    assert coordinator.snapshot_count == 1
    assert coordinator.main_cache == {}
    assert coordinator.api_endpoint_cache == {}


def test_coordinator_keeps_bounded_changed_standings_history():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    attrs = {
        "standings_groups": [{
            "name": "League",
            "standings": [
                {"rank": 1, "team_name": "A", "points": 3, "games_played": 1},
                {"rank": 2, "team_name": "B", "points": 0, "games_played": 1},
            ],
        }],
    }
    assert len(coordinator.update_standings("league-a", attrs)) == 1
    assert len(coordinator.update_standings("league-a", attrs)) == 1
    attrs["standings_groups"][0]["standings"][0]["points"] = 6
    assert len(coordinator.update_standings("league-a", attrs)) == 2
    assert len(coordinator.update_standings("league-b", attrs)) == 1
    assert len(coordinator.update_standings("league-a", attrs)) == 2
    assert len(coordinator._standings_histories) == 2
    assert coordinator.standings_history_count == 3


def test_on_demand_details_use_one_focused_entity():
    class DetailEntity:
        def __init__(self, sensor_type):
            self._sensor_type = sensor_type
            self._attributes = {"matches": [{"event_id": "fixture-1"}]}
            self.calls = 0

        async def async_get_match_details(self, match_id):
            self.calls += 1
            return {"event_id": match_id, "detail_loaded": True}

    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    schedule = DetailEntity("team_matches_mixed")
    focused = DetailEntity("team_match")
    coordinator.register_entity(schedule)
    coordinator.register_entity(focused)
    import asyncio

    result = asyncio.run(coordinator.async_get_match_details("fixture-1"))
    assert result["detail_loaded"] is True
    assert focused.calls == 1
    assert schedule.calls == 0
