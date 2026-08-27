"""Privacy-minimized diagnostics for independent HealthPlanet sources."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import HealthPlanetConfigEntry, _entry_mode
from .const import (
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_PROVIDER,
    CONF_UPDATE_INTERVAL,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
)
from .models import EndpointStatus, ProviderSnapshot


def _endpoint(status: EndpointStatus | None, *, blood_pressure: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "outcome": status.outcome if status else "null",
        "http_status": status.http_status if status else None,
        "record_count": status.record_count if status else 0,
        "available_tags": list(status.available_tags) if status else [],
        "unavailable_tags": list(status.unavailable_tags) if status else [],
        "error_id": status.error_id if status else None,
    }
    if blood_pressure:
        result["complete_pair_found"] = status.complete_pair_found if status else False
    return result


def _website_statuses(coordinator: Any) -> list[dict[str, Any]]:
    statuses = getattr(coordinator, "kind_statuses", {})
    return [
        {
            "kind": status.kind,
            "outcome": status.outcome,
            "http_status": status.http_status,
            "content_category": status.content_category,
            "backend_code": status.backend_code,
            "error_id": status.error_id,
            "row_count": status.row_count,
            "timestamp_parsing_success": status.timestamp_parsing_success,
            "row_length": status.row_length,
            "timestamp_candidate_count": status.timestamp_candidate_count,
            "numeric_candidate_count": status.numeric_candidate_count,
            "valid_assignment_count": status.valid_assignment_count,
            "field_type_shape": list(status.field_type_shape),
        }
        for status in (statuses[kind] for kind in sorted(statuses))
    ]


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: HealthPlanetConfigEntry
) -> dict[str, Any]:
    """Return source health and schema metadata without personal data."""
    runtime = entry.runtime_data
    official = getattr(runtime, "official_coordinator", None)
    website = getattr(runtime, "website_coordinator", None)

    # Keep the v1 diagnostic contract for legacy unit-test runtimes. Real
    # entries are migrated before setup and always use the split structure.
    if official is None and website is None and hasattr(runtime, "coordinator"):
        coordinator = runtime.coordinator
        snapshot: ProviderSnapshot | None = coordinator.data
        return {
            "provider": entry.data[CONF_PROVIDER],
            "update_interval_minutes": entry.options.get(
                CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
            ),
            "last_update_success": coordinator.last_update_success,
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
            "per_kind": _website_statuses(coordinator),
        }

    result: dict[str, Any] = {
        "mode": _entry_mode(dict(entry.data)),
        "official": None,
        "website": None,
        "history": None,
    }
    history_sync = getattr(runtime, "history_sync", None)
    status = getattr(history_sync, "status", None)
    if status is not None:
        result["history"] = {
            "last_history_sync": (
                status.last_history_sync.isoformat() if status.last_history_sync else None
            ),
            "history_sync_result": status.result,
            "records_seen": status.records_seen,
            "records_imported": status.records_imported,
            "records_skipped": status.records_skipped,
        }
    if official is not None:
        statuses = getattr(official, "endpoint_statuses", {})
        result["official"] = {
            "update_interval_minutes": entry.options.get(
                CONF_OFFICIAL_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
            ),
            "last_update_success": official.last_update_success,
            "innerscan": _endpoint(statuses.get("innerscan"), blood_pressure=False),
            "sphygmomanometer": _endpoint(statuses.get("sphygmomanometer"), blood_pressure=True),
        }
    if website is not None:
        result["website"] = {
            "update_interval_minutes": entry.options.get(
                CONF_WEBSITE_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
            ),
            "last_update_success": website.last_update_success,
            "per_kind": _website_statuses(website),
        }
    return result
