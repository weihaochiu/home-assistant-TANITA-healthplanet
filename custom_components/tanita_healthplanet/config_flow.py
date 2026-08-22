"""Config, reauthentication, and options flows for HealthPlanet."""

from __future__ import annotations

import hashlib
from typing import Any

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.helpers import aiohttp_client

from .api import OfficialApiClient, WebsiteApiClient, build_authorize_url
from .const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_LABEL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_LOGIN_ID,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_STORAGE_WARNING_CONFIRMED,
    CONF_UPDATE_INTERVAL,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
)
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetError,
    HealthPlanetManualInteractionRequired,
)

CONF_AUTHORIZATION_CODE = "authorization_code"


def _identity(provider: str, *parts: str) -> str:
    normalized = "\x00".join(item.strip().casefold() for item in parts)
    digest = hashlib.sha256(normalized.encode()).hexdigest()
    return f"{provider}:{digest}"


class HealthPlanetConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up exactly one provider per config entry."""

    VERSION = 1

    def __init__(self) -> None:
        self._official: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            if user_input[CONF_PROVIDER] == PROVIDER_OFFICIAL:
                return await self.async_step_official()
            return await self.async_step_website()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_PROVIDER, default=PROVIDER_OFFICIAL): vol.In(
                        [PROVIDER_OFFICIAL, PROVIDER_WEBSITE]
                    )
                }
            ),
        )

    async def async_step_official(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._official = {
                CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET],
                CONF_ACCOUNT_LABEL: user_input[CONF_ACCOUNT_LABEL].strip(),
            }
            return await self.async_step_official_authorize()
        return self.async_show_form(
            step_id="official",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ID): str,
                    vol.Required(CONF_CLIENT_SECRET): str,
                    vol.Required(CONF_ACCOUNT_LABEL): str,
                }
            ),
        )

    async def async_step_official_authorize(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            session = aiohttp_client.async_get_clientsession(self.hass)
            try:
                token = await OfficialApiClient.async_exchange_code(
                    session,
                    client_id=self._official[CONF_CLIENT_ID],
                    client_secret=self._official[CONF_CLIENT_SECRET],
                    code=user_input[CONF_AUTHORIZATION_CODE],
                )
                client = OfficialApiClient(session, token)
                await client.async_fetch()
            except HealthPlanetAuthError:
                errors["base"] = "invalid_auth"
            except HealthPlanetConnectionError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(
                    _identity(
                        PROVIDER_OFFICIAL,
                        self._official[CONF_CLIENT_ID],
                        self._official[CONF_ACCOUNT_LABEL],
                    )
                )
                self._abort_if_unique_id_configured()
                data = {
                    CONF_PROVIDER: PROVIDER_OFFICIAL,
                    **self._official,
                    CONF_ACCESS_TOKEN: token,
                }
                title = self._official[CONF_ACCOUNT_LABEL]
                self._official = {}
                token = ""
                return self.async_create_entry(title=title, data=data)
        authorize_url = (
            build_authorize_url(self._official[CONF_CLIENT_ID]) if self._official else ""
        )
        return self.async_show_form(
            step_id="official_authorize",
            data_schema=vol.Schema({vol.Required(CONF_AUTHORIZATION_CODE): str}),
            errors=errors,
            description_placeholders={"authorize_url": authorize_url},
        )

    async def async_step_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_EXPERIMENTAL_CONFIRMED]:
                errors["base"] = "experimental_confirmation_required"
            elif not user_input[CONF_STORAGE_WARNING_CONFIRMED]:
                errors["base"] = "storage_confirmation_required"
            else:
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
                if not errors:
                    await self.async_set_unique_id(
                        _identity(PROVIDER_WEBSITE, user_input[CONF_LOGIN_ID])
                    )
                    self._abort_if_unique_id_configured()
                    return self.async_create_entry(
                        title="HealthPlanet Website",
                        data={
                            CONF_PROVIDER: PROVIDER_WEBSITE,
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
                    vol.Required(CONF_PASSWORD): str,
                    vol.Required(CONF_EXPERIMENTAL_CONFIRMED, default=False): bool,
                    vol.Required(CONF_STORAGE_WARNING_CONFIRMED, default=False): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        if entry.data[CONF_PROVIDER] == PROVIDER_WEBSITE:
            return await self.async_step_reauth_website()
        return await self.async_step_reauth_official()

    async def async_step_reauth_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
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
            except HealthPlanetError:
                errors["base"] = "invalid_auth"
            finally:
                await client.async_close()
            if not errors:
                await self.async_set_unique_id(
                    _identity(PROVIDER_WEBSITE, user_input[CONF_LOGIN_ID])
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                    },
                )
        return self.async_show_form(
            step_id="reauth_website",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_LOGIN_ID): str,
                    vol.Required(CONF_PASSWORD): str,
                }
            ),
            errors=errors,
        )

    async def async_step_reauth_official(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            session = aiohttp_client.async_get_clientsession(self.hass)
            try:
                token = await OfficialApiClient.async_exchange_code(
                    session,
                    client_id=entry.data[CONF_CLIENT_ID],
                    client_secret=entry.data[CONF_CLIENT_SECRET],
                    code=user_input[CONF_AUTHORIZATION_CODE],
                )
            except HealthPlanetError:
                errors["base"] = "invalid_auth"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_ACCESS_TOKEN: token}
                )
        return self.async_show_form(
            step_id="reauth_official",
            data_schema=vol.Schema({vol.Required(CONF_AUTHORIZATION_CODE): str}),
            errors=errors,
            description_placeholders={
                "authorize_url": build_authorize_url(entry.data[CONF_CLIENT_ID])
            },
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HealthPlanetOptionsFlow:
        return HealthPlanetOptionsFlow(config_entry)


class HealthPlanetOptionsFlow(config_entries.OptionsFlow):
    """Configure non-sensitive polling options only."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        CONF_UPDATE_INTERVAL,
                        default=self._entry.options.get(
                            CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
                        ),
                    ): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_UPDATE_INTERVAL_MINUTES,
                            max=MAX_UPDATE_INTERVAL_MINUTES,
                        ),
                    )
                }
            ),
        )
