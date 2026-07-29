import importlib.util
from pathlib import Path

MODULE_PATH = Path(__file__).parents[1] / "custom_components" / "soccer_live" / "coordinator.py"
SPEC = importlib.util.spec_from_file_location("soccer_live_coordinator", MODULE_PATH)
coordinator_module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(coordinator_module)


class _Entity:
    def __init__(self):
        self.refreshes = 0

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
    remove()
    assert asyncio.run(coordinator.async_refresh()) == 0


def test_coordinator_claims_event_only_once():
    coordinator = coordinator_module.SoccerLiveEntryCoordinator(_Hass(), "entry")
    assert coordinator.claim_event(("goal", "fixture-1", 1)) is True
    assert coordinator.claim_event(("goal", "fixture-1", 1)) is False
    assert coordinator.event_ledger_size == 1
