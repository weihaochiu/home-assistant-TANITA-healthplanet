"""HealthPlanet for Home Assistant integration setup."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any, TypeAlias

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

    from .models import RuntimeData

    HealthPlanetConfigEntry: TypeAlias = ConfigEntry[RuntimeData]  # noqa: UP040
else:
    HealthPlanetConfigEntry = Any

PLATFORMS = ["sensor", "button"]
CONFIG_ENTRY_VERSION = 3
CONFIG_ENTRY_MINOR_VERSION = 0


def _runtime_providers(runtime: Any) -> tuple[Any, ...]:
    """Return providers from either a v2 or legacy test runtime."""
    providers = getattr(runtime, "providers", None)
    if providers is not None:
        return tuple(providers)
    provider = getattr(runtime, "provider", None)
    return (provider,) if provider is not None else ()


def _entry_mode(data: dict[str, Any]) -> str:
    from .const import (
        CONF_MODE,
        CONF_PROVIDER,
        MODE_OFFICIAL_ONLY,
        MODE_WEBSITE_ONLY,
        PROVIDER_OFFICIAL,
    )

    mode = data.get(CONF_MODE)
    if isinstance(mode, str):
        return mode
    return MODE_OFFICIAL_ONLY if data.get(CONF_PROVIDER) == PROVIDER_OFFICIAL else MODE_WEBSITE_ONLY


async def async_migrate_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> bool:
    """Migrate provider entries to explicit source modes without touching secrets."""
    from .const import (
        CONF_MODE,
        CONF_PROVIDER,
        MODE_OFFICIAL_ONLY,
        MODE_WEBSITE_ONLY,
        PROVIDER_OFFICIAL,
    )

    if entry.version > CONFIG_ENTRY_VERSION:
        return False
    if entry.version == CONFIG_ENTRY_VERSION:
        return True
    if entry.version not in {1, 2}:
        return False

    data = dict(entry.data)
    if entry.version == 1:
        provider = data.get(CONF_PROVIDER)
        data[CONF_MODE] = MODE_OFFICIAL_ONLY if provider == PROVIDER_OFFICIAL else MODE_WEBSITE_ONLY
        data.pop(CONF_PROVIDER, None)
    hass.config_entries.async_update_entry(
        entry,
        data=data,
        version=CONFIG_ENTRY_VERSION,
        minor_version=CONFIG_ENTRY_MINOR_VERSION,
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> bool:
    """Set up independently authenticated source coordinators."""
    import aiohttp
    from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
    from homeassistant.helpers import aiohttp_client

    from .api import OfficialApiClient, WebsiteApiClient
    from .const import (
        CONF_ACCESS_TOKEN,
        CONF_LOGIN_ID,
        CONF_PASSWORD,
        CONF_REAUTH_SOURCE,
        MODE_HYBRID,
        MODE_OFFICIAL_ONLY,
        MODE_WEBSITE_ONLY,
        SOURCE_OFFICIAL,
        SOURCE_WEBSITE,
        WEBSITE_HYBRID_KINDS,
        WEBSITE_KINDS,
    )
    from .coordinator import OfficialCoordinator, WebsiteCoordinator
    from .history import HistorySyncManager
    from .models import RuntimeData

    mode = _entry_mode(dict(entry.data))
    runtime = RuntimeData()
    auth_failures: set[str] = set()
    initializing = True
    reauth_scheduled = False

    def _start_reauth() -> None:
        nonlocal reauth_scheduled
        reauth_scheduled = False
        if not auth_failures:
            return
        source = "both" if len(auth_failures) > 1 else next(iter(auth_failures))
        auth_failures.clear()
        entry.async_start_reauth_if_available(hass, data={CONF_REAUTH_SOURCE: source})

    def _auth_failed(source: str) -> None:
        nonlocal reauth_scheduled
        auth_failures.add(source)
        if initializing or reauth_scheduled:
            return
        reauth_scheduled = True
        hass.loop.call_soon(_start_reauth)

    try:
        if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY}:
            access_token = entry.data.get(CONF_ACCESS_TOKEN)
            legacy_token = entry.data.get("token")
            if not isinstance(access_token, str) and isinstance(legacy_token, dict):
                access_token = legacy_token.get("access_token")
            if not isinstance(access_token, str) or not access_token:
                auth_failures.add(SOURCE_OFFICIAL)
            else:
                official_provider = OfficialApiClient(
                    aiohttp_client.async_get_clientsession(hass),
                    access_token=access_token,
                )
                runtime.official_provider = official_provider
                runtime.official_coordinator = OfficialCoordinator(
                    hass,
                    entry,
                    official_provider,
                    auth_failure_callback=_auth_failed,
                )

        if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY}:
            if CONF_LOGIN_ID not in entry.data or CONF_PASSWORD not in entry.data:
                auth_failures.add(SOURCE_WEBSITE)
            else:
                website_session = aiohttp_client.async_create_clientsession(
                    hass,
                    auto_cleanup=False,
                    cookie_jar=aiohttp.CookieJar(),
                )
                website_kinds = WEBSITE_HYBRID_KINDS if mode == MODE_HYBRID else WEBSITE_KINDS
                website_provider = WebsiteApiClient(
                    website_session,
                    login_id=entry.data[CONF_LOGIN_ID],
                    password=entry.data[CONF_PASSWORD],
                    kinds=website_kinds,
                )
                runtime.website_provider = website_provider
                runtime.website_coordinator = WebsiteCoordinator(
                    hass,
                    entry,
                    website_provider,
                    primary_kinds=tuple(kind for kind in website_kinds if kind != 23),
                    auth_failure_callback=_auth_failed,
                )

        entry.runtime_data = runtime
        if runtime.coordinators:
            await asyncio.gather(
                *(coordinator.async_refresh() for coordinator in runtime.coordinators)
            )
        initializing = False

        successful = [
            coordinator for coordinator in runtime.coordinators if coordinator.last_update_success
        ]
        failed_auth_sources = {
            coordinator.source for coordinator in runtime.coordinators if coordinator.auth_failed
        } | auth_failures
        configured_sources = {
            SOURCE_OFFICIAL if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY} else "",
            SOURCE_WEBSITE if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY} else "",
        } - {""}
        if not successful:
            if failed_auth_sources == configured_sources:
                # Raising is the HA-standard setup path; ConfigEntry starts
                # reauth once and the flow infers the configured source(s).
                raise ConfigEntryAuthFailed("healthplanet_reauthorization_required")
            raise ConfigEntryNotReady("healthplanet_all_configured_sources_unavailable")
        if auth_failures:
            _start_reauth()

        history_sync = HistorySyncManager(hass, entry, runtime)
        runtime.history_sync = history_sync
        await history_sync.async_sync(force=False)

        def _schedule_history_sync() -> None:
            hass.async_create_task(
                history_sync.async_maybe_sync(),
                "HealthPlanet incremental history sync",
            )

        for coordinator in runtime.coordinators:
            entry.async_on_unload(coordinator.async_add_listener(_schedule_history_sync))

        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await asyncio.gather(
            *(provider.async_close() for provider in _runtime_providers(runtime)),
            return_exceptions=True,
        )
        raise

    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> bool:
    """Unload an entry and erase all in-memory source sessions."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await asyncio.gather(
            *(provider.async_close() for provider in _runtime_providers(entry.runtime_data)),
            return_exceptions=True,
        )
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: HealthPlanetConfigEntry) -> None:
    """Clear any surviving in-memory sessions when an entry is removed."""
    runtime = getattr(entry, "runtime_data", None)
    if runtime is not None:
        await asyncio.gather(
            *(provider.async_close() for provider in _runtime_providers(runtime)),
            return_exceptions=True,
        )
    from .safe_update import management_replacement_entry_id

    if replacement := management_replacement_entry_id(hass, entry):
        await hass.config_entries.async_reload(replacement)


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
