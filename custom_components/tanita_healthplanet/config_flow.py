"""Hybrid config, reauthentication, reconfigure, and options flows."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, override

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import WebsiteApiClient
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENABLE_WEBSITE,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_LOGIN_ID,
    CONF_MODE,
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_REAUTH_SOURCE,
    CONF_STORAGE_WARNING_CONFIRMED,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
    MODES,
    OFFICIAL_SCOPE,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
    SOURCE_OFFICIAL,
    SOURCE_WEBSITE,
)
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetError,
    HealthPlanetManualInteractionRequired,
)

_LOGGER = logging.getLogger(__package__)


def _identity(login_id: str) -> str:
    """Create a stable identifier without storing plaintext in the unique ID."""
    normalized = login_id.strip().casefold()
    return f"{PROVIDER_WEBSITE}:{hashlib.sha256(normalized.encode()).hexdigest()}"


def _password_selector() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


class HealthPlanetConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Set up official-only, official-first hybrid, or website-only mode."""

    DOMAIN = DOMAIN
    VERSION = 2
    MINOR_VERSION = 0

    def __init__(self) -> None:
        super().__init__()
        self._mode = MODE_HYBRID
        self._oauth_data: dict[str, Any] | None = None
        self._reauth_source: str | None = None

    @property
    @override
    def logger(self) -> logging.Logger:
        return _LOGGER

    @property
    @override
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": OFFICIAL_SCOPE}

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            selected = user_input.get(CONF_MODE)
            # Accept the v1 input shape only to keep config-flow upgrades benign.
            if selected is None and CONF_PROVIDER in user_input:
                selected = (
                    MODE_OFFICIAL_ONLY
                    if user_input[CONF_PROVIDER] == PROVIDER_OFFICIAL
                    else MODE_WEBSITE_ONLY
                )
            self._mode = selected if isinstance(selected, str) else MODE_HYBRID
            if self._mode == MODE_WEBSITE_ONLY:
                return await self.async_step_website()
            return await self.async_step_pick_implementation()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({vol.Required(CONF_MODE, default=MODE_HYBRID): vol.In(MODES)}),
        )

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Continue after HA's standard external OAuth flow."""
        if self.context.get("source") == config_entries.SOURCE_REAUTH:
            entry = self._get_reauth_entry()
            if self._reauth_source == "both":
                self._oauth_data = data
                return await self.async_step_reauth_website()
            official_data = {
                key: value
                for key, value in entry.data.items()
                if key not in {CONF_ACCESS_TOKEN, CONF_CLIENT_ID, CONF_CLIENT_SECRET}
            }
            official_data.update(data)
            return self.async_update_reload_and_abort(entry, data=official_data)

        if self.context.get("source") == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            return self.async_update_reload_and_abort(
                entry,
                data_updates={**data, CONF_MODE: MODE_HYBRID},
            )

        self._oauth_data = data
        if self._mode == MODE_HYBRID:
            return await self.async_step_website_opt_in()
        return self.async_create_entry(
            title="HealthPlanet Official",
            data={**data, CONF_MODE: MODE_OFFICIAL_ONLY},
        )

    async def async_step_website_opt_in(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Require an explicit decision before collecting website credentials."""
        if user_input is not None:
            if user_input[CONF_ENABLE_WEBSITE]:
                return await self.async_step_website()
            return self.async_create_entry(
                title="HealthPlanet Official",
                data={**(self._oauth_data or {}), CONF_MODE: MODE_OFFICIAL_ONLY},
            )
        return self.async_show_form(
            step_id="website_opt_in",
            data_schema=vol.Schema({vol.Required(CONF_ENABLE_WEBSITE, default=True): bool}),
        )

    async def _async_validate_website(self, user_input: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        session = aiohttp_client.async_create_clientsession(
            self.hass,
            auto_cleanup=False,
            cookie_jar=aiohttp.CookieJar(),
        )
        client = WebsiteApiClient(
            session,
            login_id=user_input[CONF_LOGIN_ID],
            password=user_input[CONF_PASSWORD],
        )
        try:
            await client.async_validate_credentials()
        except HealthPlanetAuthError:
            errors["base"] = "invalid_auth"
        except HealthPlanetManualInteractionRequired:
            errors["base"] = "manual_interaction_required"
        except HealthPlanetConnectionError:
            errors["base"] = "cannot_connect"
        finally:
            await client.async_close()
        return errors

    async def async_step_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect opt-in website credentials only after both confirmations."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_EXPERIMENTAL_CONFIRMED]:
                errors["base"] = "experimental_confirmation_required"
            elif not user_input[CONF_STORAGE_WARNING_CONFIRMED]:
                errors["base"] = "storage_confirmation_required"
            else:
                errors = await self._async_validate_website(user_input)
                if not errors:
                    await self.async_set_unique_id(_identity(user_input[CONF_LOGIN_ID]))
                    self._abort_if_unique_id_configured()
                    mode = MODE_HYBRID if self._oauth_data is not None else MODE_WEBSITE_ONLY
                    return self.async_create_entry(
                        title=(
                            "HealthPlanet Hybrid" if mode == MODE_HYBRID else "HealthPlanet Website"
                        ),
                        data={
                            **(self._oauth_data or {}),
                            CONF_MODE: mode,
                            CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                            CONF_PASSWORD: user_input[CONF_PASSWORD],
                            CONF_EXPERIMENTAL_CONFIRMED: True,
                            CONF_STORAGE_WARNING_CONFIRMED: True,
                        },
                    )
        return self.async_show_form(
            step_id="website",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_ID): str,
                    vol.Required(CONF_PASSWORD): _password_selector(),
                    vol.Required(CONF_EXPERIMENTAL_CONFIRMED, default=False): bool,
                    vol.Required(CONF_STORAGE_WARNING_CONFIRMED, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Route reauth without altering the other source's credentials."""
        entry = self._get_reauth_entry()
        self._reauth_source = entry_data.get(CONF_REAUTH_SOURCE)
        if self._reauth_source is None:
            mode = entry.data[CONF_MODE]
            self._reauth_source = {
                MODE_OFFICIAL_ONLY: SOURCE_OFFICIAL,
                MODE_WEBSITE_ONLY: SOURCE_WEBSITE,
                MODE_HYBRID: "both",
            }[mode]
        if self._reauth_source == SOURCE_WEBSITE:
            return await self.async_step_reauth_website()
        return await self.async_step_pick_implementation()

    async def async_step_reauth_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace only website credentials, optionally after official OAuth."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                errors = await self._async_validate_website(user_input)
            except HealthPlanetError:
                errors["base"] = "invalid_auth"
            if not errors:
                updates = {
                    CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                if self._oauth_data is not None:
                    combined = {
                        key: value
                        for key, value in entry.data.items()
                        if key
                        not in {
                            CONF_ACCESS_TOKEN,
                            CONF_CLIENT_ID,
                            CONF_CLIENT_SECRET,
                        }
                    }
                    combined.update(self._oauth_data)
                    combined.update(updates)
                    return self.async_update_reload_and_abort(entry, data=combined)
                return self.async_update_reload_and_abort(entry, data_updates=updates)
        return self.async_show_form(
            step_id="reauth_website",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_ID): str,
                    vol.Required(CONF_PASSWORD): _password_selector(),
                }
            ),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Safely upgrade a migrated website-only entry through external OAuth."""
        entry = self._get_reconfigure_entry()
        if entry.data[CONF_MODE] != MODE_WEBSITE_ONLY:
            return self.async_abort(reason="reconfigure_not_supported")
        if user_input is not None and "upgrade_to_hybrid" in user_input:
            if not user_input["upgrade_to_hybrid"]:
                return self.async_abort(reason="reconfigure_no_changes")
            self._mode = MODE_HYBRID
            return await self.async_step_pick_implementation()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({vol.Required("upgrade_to_hybrid", default=True): bool}),
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HealthPlanetOptionsFlow:
        return HealthPlanetOptionsFlow(config_entry)


class HealthPlanetOptionsFlow(config_entries.OptionsFlow):
    """Configure separate non-sensitive polling intervals."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        mode = self._entry.data[CONF_MODE]
        schema: dict[Any, Any] = {}
        interval_validator = vol.All(
            vol.Coerce(int),
            vol.Range(
                min=MIN_UPDATE_INTERVAL_MINUTES,
                max=MAX_UPDATE_INTERVAL_MINUTES,
            ),
        )
        if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY}:
            schema[
                vol.Required(
                    CONF_OFFICIAL_UPDATE_INTERVAL,
                    default=self._entry.options.get(
                        CONF_OFFICIAL_UPDATE_INTERVAL,
                        DEFAULT_UPDATE_INTERVAL_MINUTES,
                    ),
                )
            ] = interval_validator
        if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY}:
            schema[
                vol.Required(
                    CONF_WEBSITE_UPDATE_INTERVAL,
                    default=self._entry.options.get(
                        CONF_WEBSITE_UPDATE_INTERVAL,
                        DEFAULT_UPDATE_INTERVAL_MINUTES,
                    ),
                )
            ] = interval_validator
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
