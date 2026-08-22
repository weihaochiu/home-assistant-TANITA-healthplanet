"""Privacy-minimized diagnostics for HealthPlanet."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import HealthPlanetConfigEntry
from .const import CONF_PROVIDER, CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
from .models import ProviderSnapshot


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HealthPlanetConfigEntry
) -> dict[str, Any]:
    """Return availability/schema state without credentials or health data."""
    snapshot: ProviderSnapshot | None = entry.runtime_data.coordinator.data
    return {
        "provider": entry.data[CONF_PROVIDER],
        "update_interval_minutes": entry.options.get(
            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
        ),
        "last_update_success": entry.runtime_data.coordinator.last_update_success,
        "available_kinds": (
            sorted(kind for kind, value in snapshot.measurements.items() if value is not None)
            if snapshot
            else []
        ),
        "unavailable_kinds": (
            sorted(kind for kind, value in snapshot.measurements.items() if value is None)
            if snapshot
            else []
        ),
        "error_kinds": sorted(snapshot.errors) if snapshot else [],
    }
