"""Independent DataUpdateCoordinators for HealthPlanet sources."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
)
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import (
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_UPDATE_INTERVAL,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    PROVIDER_WEBSITE,
    SOURCE_OFFICIAL,
    SOURCE_WEBSITE,
)
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetManualInteractionRequired,
    HealthPlanetRateLimitError,
)
from .models import EndpointStatus, HealthPlanetProvider, KindStatus, ProviderSnapshot

_LOGGER = logging.getLogger(__package__)
_FAILURE_OUTCOMES = {"backend_error", "auth_error", "http_error", "html", "parser_error"}
_ENDPOINT_FAILURE_OUTCOMES = {"auth_error", "http_error", "parser_error", "rate_limited"}


class SourceCoordinator(DataUpdateCoordinator[ProviderSnapshot]):
    """Coordinate one source without coupling its success to another source."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: HealthPlanetProvider,
        *,
        source: str,
        interval_key: str,
        primary_kinds: tuple[int, ...] = (),
        auth_failure_callback: Callable[[str], None] | None = None,
    ) -> None:
        interval = int(
            entry.options.get(
                interval_key,
                entry.options.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES),
            )
        )
        super().__init__(
            hass,
            config_entry=entry,
            logger=_LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}_{source}",
            update_interval=timedelta(minutes=interval),
            always_update=False,
        )
        self.config_entry = entry
        self.provider = provider
        self.source = source
        self.primary_kinds = primary_kinds
        self.kind_statuses: dict[int, KindStatus] = {}
        self.endpoint_statuses: dict[str, EndpointStatus] = {}
        self.auth_failed = False
        self._auth_failure_callback = auth_failure_callback
        self._logged_failures: dict[str, tuple[object, ...]] = {}
        self._logged_provider_error: str | None = None

    def _warn_once(
        self, key: str, signature: tuple[object, ...], message: str, *args: object
    ) -> None:
        if self._logged_failures.get(key) == signature:
            return
        _LOGGER.warning(message, *args)
        self._logged_failures[key] = signature

    def _record_kind_statuses(self, statuses: dict[int, KindStatus]) -> None:
        self.kind_statuses = dict(statuses)
        active: set[str] = set()
        for kind, status in statuses.items():
            if status.outcome not in _FAILURE_OUTCOMES:
                continue
            key = f"kind:{kind}"
            active.add(key)
            signature = (
                status.outcome,
                status.http_status,
                status.content_category,
                status.backend_code,
                status.error_id,
                status.row_count,
                status.timestamp_parsing_success,
                status.row_length,
                status.timestamp_candidate_count,
                status.numeric_candidate_count,
                status.valid_assignment_count,
                status.field_type_shape,
            )
            self._warn_once(
                key,
                signature,
                "HealthPlanet source update failed: source=%s kind=%s outcome=%s "
                "http_status=%s content_category=%s backend_code=%s error_id=%s "
                "row_count=%s timestamp_parsing_success=%s row_length=%s "
                "timestamp_candidate_count=%s numeric_candidate_count=%s "
                "valid_assignment_count=%s field_type_shape=%s",
                self.source,
                kind,
                status.outcome,
                status.http_status,
                status.content_category,
                status.backend_code,
                status.error_id,
                status.row_count,
                status.timestamp_parsing_success,
                status.row_length,
                status.timestamp_candidate_count,
                status.numeric_candidate_count,
                status.valid_assignment_count,
                status.field_type_shape,
            )
        for key in tuple(self._logged_failures):
            if key.startswith("kind:") and key not in active:
                del self._logged_failures[key]

    def _record_endpoint_statuses(self, statuses: dict[str, EndpointStatus]) -> None:
        self.endpoint_statuses = dict(statuses)
        active: set[str] = set()
        for endpoint, status in statuses.items():
            if status.outcome not in _ENDPOINT_FAILURE_OUTCOMES:
                continue
            key = f"endpoint:{endpoint}"
            active.add(key)
            signature = (status.outcome, status.http_status, status.error_id)
            self._warn_once(
                key,
                signature,
                "HealthPlanet official endpoint update failed: endpoint=%s outcome=%s "
                "http_status=%s error_id=%s",
                endpoint,
                status.outcome,
                status.http_status,
                status.error_id,
            )
        for key in tuple(self._logged_failures):
            if key.startswith("endpoint:") and key not in active:
                del self._logged_failures[key]

    def _record_provider_error(self, error_id: str) -> None:
        statuses = getattr(self.provider, "diagnostic_statuses", {})
        if isinstance(statuses, dict):
            if statuses and all(isinstance(key, int) for key in statuses):
                self._record_kind_statuses(statuses)
            elif statuses:
                self._record_endpoint_statuses(statuses)
        if self._logged_provider_error != error_id:
            _LOGGER.warning(
                "HealthPlanet source update failed: source=%s error_id=%s",
                self.source,
                error_id,
            )
            self._logged_provider_error = error_id

    def _snapshot_failed(self, snapshot: ProviderSnapshot) -> bool:
        if self.source == SOURCE_WEBSITE:
            if snapshot.kind_statuses:
                return bool(self.primary_kinds) and all(
                    snapshot.kind_statuses.get(kind) is not None
                    and snapshot.kind_statuses[kind].outcome in _FAILURE_OUTCOMES
                    for kind in self.primary_kinds
                )
            return bool(self.primary_kinds) and all(
                kind in snapshot.errors for kind in self.primary_kinds
            )
        if snapshot.endpoint_statuses:
            return all(
                status.outcome in _ENDPOINT_FAILURE_OUTCOMES
                for status in snapshot.endpoint_statuses.values()
            )
        return bool(snapshot.measurements) and all(
            kind in snapshot.errors for kind in snapshot.measurements
        )

    def _authentication_failed(self) -> None:
        self.auth_failed = True
        if self._auth_failure_callback is not None:
            self._auth_failure_callback(self.source)

    async def _async_update_data(self) -> ProviderSnapshot:
        try:
            snapshot = await self.provider.async_fetch()
        except (HealthPlanetAuthError, HealthPlanetManualInteractionRequired) as error:
            self._authentication_failed()
            self._record_provider_error("healthplanet_authentication_required")
            raise UpdateFailed("healthplanet_authentication_required") from error
        except OAuth2TokenRequestReauthError as error:
            self._authentication_failed()
            self._record_provider_error("healthplanet_oauth_reauthorization_required")
            raise UpdateFailed("healthplanet_oauth_reauthorization_required") from error
        except OAuth2TokenRequestError as error:
            self._record_provider_error("healthplanet_oauth_connection_failed")
            raise UpdateFailed("healthplanet_oauth_connection_failed") from error
        except HealthPlanetRateLimitError as error:
            self._record_provider_error("healthplanet_rate_limited")
            raise UpdateFailed("healthplanet_rate_limited") from error
        except HealthPlanetConnectionError as error:
            self._record_provider_error("healthplanet_connection_failed")
            raise UpdateFailed("healthplanet_connection_failed") from error
        self.auth_failed = False
        self._logged_provider_error = None
        self._record_kind_statuses(snapshot.kind_statuses)
        self._record_endpoint_statuses(snapshot.endpoint_statuses)
        if self._snapshot_failed(snapshot):
            raise UpdateFailed(f"healthplanet_{self.source}_all_primary_data_failed")
        return snapshot


class OfficialCoordinator(SourceCoordinator):
    """Official API failure domain."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: HealthPlanetProvider,
        *,
        auth_failure_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            hass,
            entry,
            provider,
            source=SOURCE_OFFICIAL,
            interval_key=CONF_OFFICIAL_UPDATE_INTERVAL,
            auth_failure_callback=auth_failure_callback,
        )


class WebsiteCoordinator(SourceCoordinator):
    """Experimental website failure domain."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: HealthPlanetProvider,
        *,
        primary_kinds: tuple[int, ...],
        auth_failure_callback: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(
            hass,
            entry,
            provider,
            source=SOURCE_WEBSITE,
            interval_key=CONF_WEBSITE_UPDATE_INTERVAL,
            primary_kinds=primary_kinds,
            auth_failure_callback=auth_failure_callback,
        )


class HealthPlanetCoordinator(SourceCoordinator):
    """Backward-compatible single-source coordinator used by existing tests."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        provider: HealthPlanetProvider,
    ) -> None:
        website = getattr(provider, "provider_type", entry.data.get("provider")) == PROVIDER_WEBSITE
        kinds = tuple(
            kind
            for kind in getattr(
                provider,
                "_kinds",
                entry.data.get("website_kinds", (1, 2, 3, 4, 5, 6, 7, 14, 22, 23)),
            )
            if kind != 23
        )
        super().__init__(
            hass,
            entry,
            provider,
            source=SOURCE_WEBSITE if website else SOURCE_OFFICIAL,
            interval_key=CONF_UPDATE_INTERVAL,
            primary_kinds=kinds if website else (),
        )

    async def _async_update_data(self) -> ProviderSnapshot:
        """Preserve the v1 single-source authentication exception contract."""
        try:
            return await super()._async_update_data()
        except UpdateFailed as error:
            if self.auth_failed:
                raise ConfigEntryAuthFailed("healthplanet_authentication_required") from error
            raise
