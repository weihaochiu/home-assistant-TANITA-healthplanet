"""Manual history synchronization button."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import HealthPlanetConfigEntry
from .const import DOMAIN
from .history import HistorySyncManager


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HealthPlanetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the user-facing history control."""
    manager = entry.runtime_data.history_sync
    if isinstance(manager, HistorySyncManager):
        async_add_entities([HealthPlanetHistorySyncButton(entry, manager)])


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
