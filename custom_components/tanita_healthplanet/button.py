"""Manual history synchronization and native Safe Update buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HealthPlanetConfigEntry
from .const import DOMAIN
from .device_info import healthplanet_device_info
from .history import HistorySyncManager
from .safe_update import (
    SafeUpdateManager,
    configured_restart_after_update,
    get_safe_update_manager,
    is_management_entry,
)


def remove_legacy_management_device(hass: HomeAssistant, entity_id: str) -> None:
    """Detach Safe Update and remove only the v0.2.1 management device."""
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    entities = er.async_get(hass)
    registry_entry = entities.async_get(entity_id)
    if registry_entry is None or registry_entry.device_id is None:
        return
    devices = dr.async_get(hass)
    device = devices.async_get(registry_entry.device_id)
    legacy_identifier = (DOMAIN, "integration_management")
    if device is None or legacy_identifier not in device.identifiers:
        return
    legacy_device_id = registry_entry.device_id
    entities.async_update_entity(entity_id, device_id=None)
    devices.async_remove_device(legacy_device_id)


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
        self._attr_device_info = healthplanet_device_info(
            entry.entry_id, entry.title, "HealthPlanet cloud data"
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
            "failure_stage": status.failure_stage,
            "error_id": status.error_id,
            "error_type": status.error_type,
            "statistics_ui": "statistics_graph",
            "statistic_ids": ",".join(status.statistic_ids),
        }


class HealthPlanetSafeUpdateButton(ButtonEntity):
    """Expose one repository-level, explicitly initiated Safe Update button."""

    _attr_has_entity_name = True
    _attr_translation_key = "safe_update"
    _attr_unique_id = f"{DOMAIN}_safe_update"
    _attr_icon = "mdi:shield-refresh"

    def __init__(self, hass: HomeAssistant, manager: SafeUpdateManager) -> None:
        self._hass_ref = hass
        self._manager = manager

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        remove_legacy_management_device(self.hass, self.entity_id)
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
