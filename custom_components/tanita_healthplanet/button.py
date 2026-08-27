"""Manual history synchronization and native Safe Update buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HealthPlanetConfigEntry
from .const import DOMAIN
from .history import HistorySyncManager
from .safe_update import (
    SafeUpdateManager,
    configured_restart_after_update,
    get_safe_update_manager,
    is_management_entry,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HealthPlanetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the user-facing history control."""
    manager = entry.runtime_data.history_sync
    entities: list[ButtonEntity] = []
    if isinstance(manager, HistorySyncManager):
        entities.append(HealthPlanetHistorySyncButton(entry, manager))
    if is_management_entry(hass, entry):
        entities.append(HealthPlanetSafeUpdateButton(hass, get_safe_update_manager(hass)))
    async_add_entities(entities)


class HealthPlanetHistorySyncButton(ButtonEntity):
    """Re-fetch and import bounded provider history."""

    _attr_has_entity_name = True
    _attr_translation_key = "sync_history"

    def __init__(self, entry: HealthPlanetConfigEntry, manager: HistorySyncManager) -> None:
        self._manager = manager
        self._attr_unique_id = f"{entry.entry_id}_history_sync"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="TANITA",
            model="HealthPlanet cloud data",
        )

    async def async_press(self) -> None:
        await self._manager.async_sync(force=True)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, str | int | None]:
        status = self._manager.status
        return {
            "last_history_sync": (
                status.last_history_sync.isoformat() if status.last_history_sync else None
            ),
            "history_sync_result": status.result,
            "records_seen": status.records_seen,
            "records_imported": status.records_imported,
            "records_skipped": status.records_skipped,
        }


class HealthPlanetSafeUpdateButton(ButtonEntity):
    """Expose one repository-level, explicitly initiated Safe Update button."""

    _attr_has_entity_name = True
    _attr_translation_key = "safe_update"
    _attr_unique_id = f"{DOMAIN}_safe_update"
    _attr_icon = "mdi:shield-refresh"
    _attr_device_info = DeviceInfo(
        identifiers={(DOMAIN, "integration_management")},
        name="HealthPlanet for Home Assistant",
        manufacturer="Independent open-source project",
        model="Integration management",
    )

    def __init__(self, hass: HomeAssistant, manager: SafeUpdateManager) -> None:
        self._hass_ref = hass
        self._manager = manager

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(self._manager.async_add_listener(self.async_write_ha_state))

        def _update_entity_changed(event: object) -> None:
            data = getattr(event, "data", {})
            if str(data.get("entity_id", "")).startswith("update."):
                self.async_write_ha_state()

        self.async_on_remove(self.hass.bus.async_listen("state_changed", _update_entity_changed))

    @property
    def available(self) -> bool:
        return not self._manager.running and self._manager.ready

    async def async_press(self) -> None:
        await self._manager.async_run(
            restart_after_update=configured_restart_after_update(self._hass_ref),
            context=self._context,
        )

    @property
    def extra_state_attributes(self) -> dict[str, str | bool | None]:
        return {
            "safe_update_supported": self._manager.supported,
            "last_result": self._manager.last_result,
            "last_stage": self._manager.last_stage,
            "last_completed_at": (
                self._manager.last_completed_at.isoformat()
                if self._manager.last_completed_at
                else None
            ),
        }
