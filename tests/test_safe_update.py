from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

from custom_components.tanita_healthplanet.safe_update import (
    RESULT_BACKUP_FAILED,
    RESULT_BACKUP_TIMEOUT,
    RESULT_BUSY,
    RESULT_NO_UPDATE,
    RESULT_SUCCESS,
    RESULT_UNSUPPORTED,
    RESULT_UPDATE_FAILED,
    RESULT_UPDATE_TIMEOUT,
    SafeUpdateManager,
    management_entry_id,
    management_replacement_entry_id,
)


@dataclass
class FakeState:
    state: str
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class FakeEvent:
    data: dict[str, Any]


class FakeBus:
    def __init__(self) -> None:
        self.listeners: list[Any] = []

    def async_listen(self, event_type: str, listener: Any) -> Any:
        assert event_type == "state_changed"
        self.listeners.append(listener)
        return lambda: self.listeners.remove(listener)

    def fire(self, entity_id: str, state: FakeState) -> None:
        event = FakeEvent({"entity_id": entity_id, "new_state": state})
        for listener in tuple(self.listeners):
            listener(event)


class FakeStates:
    def __init__(self, bus: FakeBus) -> None:
        self._states: dict[str, FakeState] = {}
        self._bus = bus

    def get(self, entity_id: str | None) -> FakeState | None:
        return self._states.get(entity_id) if entity_id else None

    def set(self, entity_id: str, state: FakeState) -> None:
        self._states[entity_id] = state
        self._bus.fire(entity_id, state)


class FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any, Any]] = []
        self.contexts: list[Any] = []
        self.hooks: dict[tuple[str, str], Any] = {}

    async def async_call(
        self,
        domain: str,
        service: str,
        data: Any = None,
        *,
        blocking: bool,
        target: Any = None,
        context: Any = None,
    ) -> None:
        self.calls.append((domain, service, data, target))
        self.contexts.append(context)
        if hook := self.hooks.get((domain, service)):
            await hook()


class FakeHass:
    def __init__(self) -> None:
        self.bus = FakeBus()
        self.states = FakeStates(self.bus)
        self.services = FakeServices()
        self.config = SimpleNamespace(language="en")

    def async_create_task(self, coroutine: Any, name: str) -> asyncio.Task[Any]:
        return asyncio.create_task(coroutine, name=name)


UPDATE_ENTITY = "update.renamed_healthplanet"
BACKUP_ENTITY = "event.renamed_automatic_backup"


def _manager(hass: FakeHass) -> SafeUpdateManager:
    return SafeUpdateManager(
        hass,  # type: ignore[arg-type]
        backup_start_timeout=0.02,
        backup_completion_timeout=0.02,
        install_timeout=0.02,
        restart_delay=0,
        update_entity_resolver=lambda: UPDATE_ENTITY,
        backup_entity_resolver=lambda: BACKUP_ENTITY,
    )


def _available_update() -> FakeState:
    return FakeState("on", {"installed_version": "0.2.1", "latest_version": "0.2.2"})


def _initial_states(hass: FakeHass) -> None:
    hass.states.set(UPDATE_ENTITY, _available_update())
    hass.states.set(BACKUP_ENTITY, FakeState("old", {"event_type": "completed"}))


def _schedule_backup(hass: FakeHass, terminal: str = "completed") -> None:
    async def emit() -> None:
        await asyncio.sleep(0)
        hass.states.set(
            BACKUP_ENTITY,
            FakeState("new-start", {"event_type": "in_progress", "backup_stage": "folders"}),
        )
        await asyncio.sleep(0)
        hass.states.set(
            BACKUP_ENTITY,
            FakeState("new-end", {"event_type": terminal, "failed_reason": None}),
        )

    asyncio.create_task(emit())


def _schedule_update(hass: FakeHass, *, installed: str = "0.2.2") -> None:
    async def emit() -> None:
        await asyncio.sleep(0)
        hass.states.set(
            UPDATE_ENTITY,
            FakeState(
                "on",
                {
                    "installed_version": "0.2.1",
                    "latest_version": "0.2.2",
                    "in_progress": True,
                },
            ),
        )
        await asyncio.sleep(0)
        hass.states.set(
            UPDATE_ENTITY,
            FakeState(
                "off",
                {
                    "installed_version": installed,
                    "latest_version": "0.2.2",
                    "in_progress": False,
                },
            ),
        )

    asyncio.create_task(emit())


def _actions(hass: FakeHass) -> list[tuple[str, str]]:
    return [(domain, service) for domain, service, _data, _target in hass.services.calls]


async def test_no_update_does_not_backup_install_or_restart():
    hass = FakeHass()
    _initial_states(hass)
    hass.states.set(UPDATE_ENTITY, FakeState("off", {"installed_version": "0.2.1"}))
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_NO_UPDATE
    assert ("backup", "create_automatic") not in _actions(hass)
    assert ("update", "install") not in _actions(hass)
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_notification_failure_cannot_start_an_update():
    hass = FakeHass()
    _initial_states(hass)
    hass.states.set(UPDATE_ENTITY, FakeState("off", {"installed_version": "0.2.1"}))

    async def notification_hook() -> None:
        raise RuntimeError("synthetic notification failure")

    hass.services.hooks[("persistent_notification", "create")] = notification_hook
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_NO_UPDATE
    assert ("backup", "create_automatic") not in _actions(hass)
    assert ("update", "install") not in _actions(hass)
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_external_hacs_install_in_progress_cannot_start_safe_update():
    hass = FakeHass()
    _initial_states(hass)
    hass.states.set(
        UPDATE_ENTITY,
        FakeState(
            "on",
            {
                "installed_version": "0.2.1",
                "latest_version": "0.2.2",
                "in_progress": True,
            },
        ),
    )
    manager = _manager(hass)
    assert manager.ready is False
    assert await manager.async_run(restart_after_update=True) == RESULT_UPDATE_FAILED
    assert ("backup", "create_automatic") not in _actions(hass)


async def test_happy_path_verifies_backup_and_update_before_restart():
    hass = FakeHass()
    _initial_states(hass)
    context = object()

    async def backup_hook() -> None:
        _schedule_backup(hass)

    async def update_hook() -> None:
        _schedule_update(hass)

    hass.services.hooks[("backup", "create_automatic")] = backup_hook
    hass.services.hooks[("update", "install")] = update_hook
    assert (
        await _manager(hass).async_run(restart_after_update=True, context=context) == RESULT_SUCCESS
    )
    actions = _actions(hass)
    assert actions.index(("backup", "create_automatic")) < actions.index(("update", "install"))
    assert actions.index(("update", "install")) < actions.index(("homeassistant", "restart"))
    update_call = next(call for call in hass.services.calls if call[:2] == ("update", "install"))
    assert update_call[2] == {"version": "0.2.2"}
    assert "backup" not in update_call[2]
    assert update_call[3] == {"entity_id": UPDATE_ENTITY}
    assert hass.services.contexts == [context, context, context]


async def test_stale_completed_event_and_backup_timeout_never_install():
    hass = FakeHass()
    _initial_states(hass)
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_BACKUP_TIMEOUT
    assert ("update", "install") not in _actions(hass)
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_backup_failure_never_installs_or_restarts():
    hass = FakeHass()
    _initial_states(hass)

    async def backup_hook() -> None:
        _schedule_backup(hass, terminal="failed")

    hass.services.hooks[("backup", "create_automatic")] = backup_hook
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_BACKUP_FAILED
    assert ("update", "install") not in _actions(hass)
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_backup_service_error_never_installs_or_restarts():
    hass = FakeHass()
    _initial_states(hass)

    async def backup_hook() -> None:
        raise RuntimeError("synthetic backup failure")

    hass.services.hooks[("backup", "create_automatic")] = backup_hook
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_BACKUP_FAILED
    assert ("update", "install") not in _actions(hass)
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_update_timeout_and_wrong_version_never_restart():
    for schedule_wrong_version, expected_result in (
        (False, RESULT_UPDATE_TIMEOUT),
        (True, RESULT_UPDATE_FAILED),
    ):
        hass = FakeHass()
        _initial_states(hass)

        async def backup_hook(current_hass: FakeHass = hass) -> None:
            _schedule_backup(current_hass)

        async def update_hook(current_hass: FakeHass = hass) -> None:
            _schedule_update(current_hass, installed="0.2.1")

        hass.services.hooks[("backup", "create_automatic")] = backup_hook
        if schedule_wrong_version:
            hass.services.hooks[("update", "install")] = update_hook
        assert await _manager(hass).async_run(restart_after_update=True) == expected_result
        assert ("homeassistant", "restart") not in _actions(hass)


async def test_update_service_error_never_restarts():
    hass = FakeHass()
    _initial_states(hass)

    async def backup_hook() -> None:
        _schedule_backup(hass)

    async def update_hook() -> None:
        raise RuntimeError("synthetic install failure")

    hass.services.hooks[("backup", "create_automatic")] = backup_hook
    hass.services.hooks[("update", "install")] = update_hook
    assert await _manager(hass).async_run(restart_after_update=True) == RESULT_UPDATE_FAILED
    assert ("homeassistant", "restart") not in _actions(hass)


async def test_restart_disabled_notifies_without_restart():
    hass = FakeHass()
    _initial_states(hass)

    async def backup_hook() -> None:
        _schedule_backup(hass)

    async def update_hook() -> None:
        _schedule_update(hass)

    hass.services.hooks[("backup", "create_automatic")] = backup_hook
    hass.services.hooks[("update", "install")] = update_hook
    assert await _manager(hass).async_run(restart_after_update=False) == RESULT_SUCCESS
    assert ("homeassistant", "restart") not in _actions(hass)
    assert ("persistent_notification", "create") in _actions(hass)


async def test_hacs_unavailable_is_isolated_and_clean():
    hass = FakeHass()
    manager = SafeUpdateManager(
        hass,  # type: ignore[arg-type]
        update_entity_resolver=lambda: None,
        backup_entity_resolver=lambda: BACKUP_ENTITY,
    )
    assert await manager.async_run(restart_after_update=True) == RESULT_UNSUPPORTED
    assert ("backup", "create_automatic") not in _actions(hass)


async def test_global_lock_allows_only_one_operation():
    hass = FakeHass()
    _initial_states(hass)
    manager = _manager(hass)

    async def update_hook() -> None:
        _schedule_update(hass)

    hass.services.hooks[("update", "install")] = update_hook
    first = asyncio.create_task(manager.async_run(restart_after_update=True))
    await asyncio.sleep(0)
    assert await manager.async_run(restart_after_update=True) == RESULT_BUSY
    _schedule_backup(hass)
    assert await first == RESULT_SUCCESS
    assert _actions(hass).count(("backup", "create_automatic")) == 1
    assert _actions(hass).count(("update", "install")) == 1
    assert _actions(hass).count(("homeassistant", "restart")) == 1


def test_three_family_entries_have_one_deterministic_management_owner():
    entries = [
        SimpleNamespace(entry_id="third", created_at="2026-03-01"),
        SimpleNamespace(entry_id="first", created_at="2026-01-01"),
        SimpleNamespace(entry_id="second", created_at="2026-02-01"),
    ]
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda domain: entries))
    assert management_entry_id(hass) == "first"
    assert management_replacement_entry_id(hass, entries[1]) == "second"
    assert management_replacement_entry_id(hass, entries[2]) is None


def test_repository_discovery_matches_only_the_exact_public_release_url():
    match = SafeUpdateManager._release_url_matches_repository
    assert match("https://github.com/weihaochiu/home-assistant-TANITA-healthplanet/releases/v0.2.2")
    assert match("https://github.com/weihaochiu/home-assistant-TANITA-healthplanet")
    assert not match("https://github.com/other/home-assistant-TANITA-healthplanet/releases/v0.2.2")
    assert not match(
        "https://github.com/weihaochiu/home-assistant-TANITA-healthplanet-malicious/releases/v0.2.2"
    )
