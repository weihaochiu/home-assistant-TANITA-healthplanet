"""TANITA HealthPlanet integration setup."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .models import RuntimeData

    type HealthPlanetConfigEntry = ConfigEntry[RuntimeData]
else:
    HealthPlanetConfigEntry = Any

PLATFORMS = ["sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> bool:
    """Set up one independently authenticated HealthPlanet config entry."""
    import aiohttp
    from homeassistant.exceptions import ConfigEntryNotReady
    from homeassistant.helpers import aiohttp_client

    from .api import OfficialApiClient, WebsiteApiClient
    from .const import (
        CONF_ACCESS_TOKEN,
        CONF_LOGIN_ID,
        CONF_PASSWORD,
        CONF_PROVIDER,
        PROVIDER_OFFICIAL,
        PROVIDER_WEBSITE,
    )
    from .coordinator import HealthPlanetCoordinator
    from .models import HealthPlanetProvider, RuntimeData

    provider: HealthPlanetProvider
    provider_type = entry.data[CONF_PROVIDER]
    if provider_type == PROVIDER_OFFICIAL:
        session = aiohttp_client.async_get_clientsession(hass)
        provider = OfficialApiClient(session, entry.data[CONF_ACCESS_TOKEN])
    elif provider_type == PROVIDER_WEBSITE:
        session = aiohttp_client.async_create_clientsession(
            hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.CookieJar(),
        )
        provider = WebsiteApiClient(
            session,
            login_id=entry.data[CONF_LOGIN_ID],
            password=entry.data[CONF_PASSWORD],
        )
    else:
        raise ConfigEntryNotReady("unsupported_healthplanet_provider")

    coordinator = HealthPlanetCoordinator(hass, entry, provider)
    entry.runtime_data = RuntimeData(coordinator=coordinator, provider=provider)
    try:
        await coordinator.async_config_entry_first_refresh()
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await provider.async_close()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> bool:
    """Unload an entry and erase its in-memory session state."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.provider.async_close()
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> None:
    """Clear any surviving in-memory session when an entry is removed."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await runtime.provider.async_close()


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
