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
    DOMAIN,
    VERSION,
)
from .models import EndpointStatus, ProviderSnapshot
from .safe_update import get_safe_update_manager


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
        "safe_update": None,
    }
    if hasattr(hass, "data") and hasattr(hass, "states"):
        manager = get_safe_update_manager(hass)
        update_entity = manager.resolve_update_entity()
        update_state = hass.states.get(update_entity) if update_entity else None
        await manager.async_capture_versions(update_state, check_github=True)
        result["safe_update"] = {
            "safe_update_supported": manager.supported,
            "hacs_update_entity_resolved": update_entity is not None,
            "update_available": update_state is not None and update_state.state == "on",
            "last_safe_update_result": manager.last_result,
            "last_safe_update_stage": manager.last_stage,
            "last_completed_at": (
                manager.last_completed_at.isoformat() if manager.last_completed_at else None
            ),
            "runtime_version": VERSION,
            "disk_version": manager.disk_version,
            "hacs_installed_version": manager.hacs_installed_version,
            "hacs_latest_version": manager.hacs_latest_version,
            "github_latest_version": manager.github_latest_version,
            "version_consistent": manager.version_consistent,
            "update_metadata_status": manager.update_metadata_status,
        }
    else:
        result["safe_update"] = {
            "safe_update_supported": False,
            "hacs_update_entity_resolved": False,
            "update_available": False,
            "last_safe_update_result": None,
            "last_safe_update_stage": "idle",
            "last_completed_at": None,
            "runtime_version": VERSION,
            "disk_version": None,
            "hacs_installed_version": None,
            "hacs_latest_version": None,
            "github_latest_version": None,
            "version_consistent": False,
            "update_metadata_status": "unknown",
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
            "failure_stage": status.failure_stage,
            "error_id": status.error_id,
            "error_type": status.error_type,
            "statistic_ids": list(status.statistic_ids),
        }
    oauth_status = getattr(hass, "data", {}).get(DOMAIN, {}).get("oauth_status", {})
    result["oauth"] = {
        "last_oauth_error_id": oauth_status.get("last_oauth_error_id"),
        "last_oauth_http_status": oauth_status.get("last_oauth_http_status"),
        "stage": oauth_status.get("stage"),
        "response_format": oauth_status.get("response_format"),
        "content_category": oauth_status.get("content_category"),
        "exception_type": oauth_status.get("exception_type"),
        "last_attempt_result": oauth_status.get("last_attempt_result"),
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
