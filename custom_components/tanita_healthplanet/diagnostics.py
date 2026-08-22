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
    statuses = getattr(entry.runtime_data.coordinator, "kind_statuses", {})
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
        "per_kind": [
            {
                "kind": status.kind,
                "outcome": status.outcome,
                "http_status": status.http_status,
                "content_category": status.content_category,
                "backend_code": status.backend_code,
                "error_id": status.error_id,
                "row_count": status.row_count,
                "timestamp_parsing_success": status.timestamp_parsing_success,
            }
            for status in (statuses[kind] for kind in sorted(statuses))
        ],
    }
