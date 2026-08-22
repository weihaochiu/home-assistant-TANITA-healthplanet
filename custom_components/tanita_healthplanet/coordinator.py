"""DataUpdateCoordinator for HealthPlanet providers."""

from __future__ import annotations

from datetime import timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DEFAULT_UPDATE_INTERVAL_MINUTES, DOMAIN
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetManualInteractionRequired,
    HealthPlanetRateLimitError,
)
from .models import HealthPlanetProvider, ProviderSnapshot


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

    async def _async_update_data(self) -> ProviderSnapshot:
        try:
            return await self.provider.async_fetch()
        except (HealthPlanetAuthError, HealthPlanetManualInteractionRequired) as error:
            raise ConfigEntryAuthFailed("healthplanet_authentication_required") from error
        except HealthPlanetRateLimitError as error:
            raise UpdateFailed("healthplanet_rate_limited") from error
        except HealthPlanetConnectionError as error:
            raise UpdateFailed("healthplanet_connection_failed") from error
