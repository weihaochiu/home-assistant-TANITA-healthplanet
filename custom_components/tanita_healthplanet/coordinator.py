"""DataUpdateCoordinator for HealthPlanet providers."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    PROVIDER_WEBSITE,
    WEBSITE_PRIMARY_KINDS,
)
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetManualInteractionRequired,
    HealthPlanetRateLimitError,
)
from .models import HealthPlanetProvider, KindStatus, ProviderSnapshot

_LOGGER = logging.getLogger(__package__)
_FAILURE_OUTCOMES = {"backend_error", "auth_error", "http_error", "html", "parser_error"}


class HealthPlanetCoordinator(DataUpdateCoordinator[ProviderSnapshot]):
    """Coordinate conservative polling for one isolated config entry."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: HealthPlanetProvider,
    ) -> None:
        interval = int(entry.options.get("update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES))
        super().__init__(
            hass,
            config_entry=entry,
            logger=__import__("logging").getLogger(__package__),
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(minutes=interval),
            always_update=False,
        )
        self.config_entry = entry
        self.provider = provider
        self._provider_type = entry.data.get("provider")
        self.kind_statuses: dict[int, KindStatus] = {}
        self._logged_kind_failures: dict[int, tuple[object, ...]] = {}
        self._logged_provider_error: str | None = None

    def _record_kind_statuses(self, statuses: dict[int, KindStatus]) -> None:
        self.kind_statuses = dict(statuses)
        current_failures: dict[int, tuple[object, ...]] = {}
        for kind, status in statuses.items():
            if status.outcome not in _FAILURE_OUTCOMES:
                continue
            signature = (
                status.outcome,
                status.http_status,
                status.content_category,
                status.backend_code,
                status.error_id,
                status.row_count,
                status.timestamp_parsing_success,
            )
            current_failures[kind] = signature
            if self._logged_kind_failures.get(kind) == signature:
                continue
            _LOGGER.warning(
                "HealthPlanet kind update failed: kind=%s outcome=%s http_status=%s "
                "content_category=%s backend_code=%s error_id=%s row_count=%s "
                "timestamp_parsing_success=%s",
                kind,
                status.outcome,
                status.http_status,
                status.content_category,
                status.backend_code,
                status.error_id,
                status.row_count,
                status.timestamp_parsing_success,
            )
        self._logged_kind_failures = current_failures

    def _record_provider_error(self, error_id: str) -> None:
        statuses = getattr(self.provider, "diagnostic_statuses", {})
        if isinstance(statuses, dict):
            self._record_kind_statuses(statuses)
        if self._logged_provider_error != error_id:
            _LOGGER.warning("HealthPlanet provider update failed: error_id=%s", error_id)
            self._logged_provider_error = error_id

    @staticmethod
    def _all_primary_kinds_failed(snapshot: ProviderSnapshot) -> bool:
        if snapshot.kind_statuses:
            return all(
                snapshot.kind_statuses.get(kind) is not None
                and snapshot.kind_statuses[kind].outcome in _FAILURE_OUTCOMES
                for kind in WEBSITE_PRIMARY_KINDS
            )
        return all(kind in snapshot.errors for kind in WEBSITE_PRIMARY_KINDS)

    async def _async_update_data(self) -> ProviderSnapshot:
        try:
            snapshot = await self.provider.async_fetch()
        except (HealthPlanetAuthError, HealthPlanetManualInteractionRequired) as error:
            self._record_provider_error("healthplanet_authentication_required")
            raise ConfigEntryAuthFailed("healthplanet_authentication_required") from error
        except HealthPlanetRateLimitError as error:
            self._record_provider_error("healthplanet_rate_limited")
            raise UpdateFailed("healthplanet_rate_limited") from error
        except HealthPlanetConnectionError as error:
            self._record_provider_error("healthplanet_connection_failed")
            raise UpdateFailed("healthplanet_connection_failed") from error
        self._logged_provider_error = None
        self._record_kind_statuses(snapshot.kind_statuses)
        if getattr(
            self.provider, "provider_type", self._provider_type
        ) == PROVIDER_WEBSITE and self._all_primary_kinds_failed(snapshot):
            raise UpdateFailed("healthplanet_all_primary_kinds_failed")
        return snapshot
