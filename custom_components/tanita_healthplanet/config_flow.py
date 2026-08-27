"""Hybrid-first config, manual authorization, reauth, and options flows."""

from __future__ import annotations

import hashlib
import logging
from typing import Any, override

import aiohttp
import voluptuous as vol
from homeassistant import config_entries
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.core import callback
from homeassistant.exceptions import (
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
)
from homeassistant.helpers import aiohttp_client, config_entry_oauth2_flow
from homeassistant.helpers.config_entry_oauth2_flow import (
    ImplementationUnavailableError,
    async_get_implementations,
)
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig, TextSelectorType

from .api import WebsiteApiClient
from .application_credentials import HealthPlanetOAuth2Implementation
from .const import (
    API_SETUP_DOCS_URL,
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_LABEL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_HISTORY_SYNC_ENABLED,
    CONF_LOGIN_ID,
    CONF_MODE,
    CONF_OFFICIAL_HISTORY_DAYS,
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_PASSWORD,
    CONF_REAUTH_SOURCE,
    CONF_STORAGE_WARNING_CONFIRMED,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DEFAULT_HISTORY_SYNC_ENABLED,
    DEFAULT_OFFICIAL_HISTORY_DAYS,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    MAX_OFFICIAL_HISTORY_DAYS,
    MAX_UPDATE_INTERVAL_MINUTES,
    MIN_UPDATE_INTERVAL_MINUTES,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
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
_AUTH_IMPLEMENTATION = "auth_implementation"
_AUTHORIZATION_CODE = "authorization_code"
_UPGRADE_TO_HYBRID = "upgrade_to_hybrid"


def _identity(login_id: str) -> str:
    normalized = login_id.strip().casefold()
    return f"{PROVIDER_WEBSITE}:{hashlib.sha256(normalized.encode()).hexdigest()}"


def _password_selector() -> TextSelector:
    return TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _label(value: Any) -> str:
    return str(value).strip()


class HealthPlanetConfigFlow(
    config_entry_oauth2_flow.AbstractOAuth2FlowHandler,
    domain=DOMAIN,
):
    """Set up Hybrid entries while retaining legacy recovery paths."""

    DOMAIN = DOMAIN
    VERSION = 3
    MINOR_VERSION = 0

    def __init__(self) -> None:
        super().__init__()
        self._oauth_data: dict[str, Any] | None = None
        self._reauth_source: str | None = None
        self._account_label = ""

    @property
    @override
    def logger(self) -> logging.Logger:
        return _LOGGER

    @override
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Start new users directly in the Hybrid-only setup."""
        if user_input is not None:
            self._account_label = _label(user_input[CONF_ACCOUNT_LABEL])
            return await self.async_step_pick_implementation()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {vol.Required(CONF_ACCOUNT_LABEL): vol.All(str, vol.Length(min=1))}
            ),
        )

    @override
    async def async_step_pick_implementation(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Select shared Application Credentials without starting callback OAuth."""
        try:
            implementations = await async_get_implementations(self.hass, self.DOMAIN)
        except ImplementationUnavailableError:
            implementations = {}
        if not implementations:
            return self.async_abort(
                reason="missing_credentials",
                description_placeholders={
                    "docs_url": API_SETUP_DOCS_URL,
                    "repository_url": (
                        "https://github.com/weihaochiu/home-assistant-TANITA-healthplanet"
                    ),
                },
            )
        if user_input is not None:
            self.flow_impl = implementations[user_input["implementation"]]
            return await self.async_step_manual_authorization()
        if len(implementations) == 1:
            self.flow_impl = next(iter(implementations.values()))
            return await self.async_step_manual_authorization()
        return self.async_show_form(
            step_id="pick_implementation",
            data_schema=vol.Schema(
                {
                    vol.Required("implementation", default=next(iter(implementations))): vol.In(
                        {
                            key: implementation.name
                            for key, implementation in implementations.items()
                        }
                    )
                }
            ),
        )

    async def async_step_manual_authorization(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Exchange a copied one-time code without a callback or persistence."""
        implementation = self.flow_impl
        if not isinstance(implementation, HealthPlanetOAuth2Implementation):
            return self.async_abort(reason="oauth_implementation_unavailable")
        errors: dict[str, str] = {}
        if user_input is not None:
            code = str(user_input.pop(_AUTHORIZATION_CODE, "")).strip()
            try:
                access_token = await implementation.async_exchange_authorization_code(code)
            except OAuth2TokenRequestReauthError:
                errors["base"] = "authorization_code_invalid"
            except OAuth2TokenRequestTransientError:
                errors["base"] = "cannot_connect"
            except OAuth2TokenRequestError:
                errors["base"] = "token_exchange_failed"
            else:
                self._oauth_data = {
                    _AUTH_IMPLEMENTATION: implementation.domain,
                    CONF_ACCESS_TOKEN: access_token,
                }
                access_token = ""
                code = ""
                return await self._async_official_authorized()
            finally:
                code = ""

        return self.async_show_form(
            step_id="manual_authorization",
            data_schema=vol.Schema({vol.Required(_AUTHORIZATION_CODE): _password_selector()}),
            errors=errors,
            description_placeholders={
                "authorize_url": await implementation.async_generate_manual_authorize_url(),
                "redirect_uri": implementation.redirect_uri,
                "docs_url": API_SETUP_DOCS_URL,
            },
        )

    async def _async_official_authorized(self) -> ConfigFlowResult:
        source = self.context.get("source")
        if source == config_entries.SOURCE_REAUTH:
            if self._reauth_source == "both":
                return await self.async_step_reauth_website()
            entry = self._get_reauth_entry()
            data = self._official_reauth_data(entry.data)
            self._oauth_data = None
            return self.async_update_reload_and_abort(entry, data=data)
        if source == config_entries.SOURCE_RECONFIGURE:
            entry = self._get_reconfigure_entry()
            return self.async_update_reload_and_abort(
                entry,
                data_updates={
                    **(self._oauth_data or {}),
                    CONF_ACCOUNT_LABEL: self._account_label,
                    CONF_MODE: MODE_HYBRID,
                },
                title=f"HealthPlanet - {self._account_label}",
            )
        return await self.async_step_website()

    def _official_reauth_data(self, entry_data: Any) -> dict[str, Any]:
        data = {
            key: value
            for key, value in dict(entry_data).items()
            if key not in {"token", CONF_CLIENT_ID, CONF_CLIENT_SECRET}
        }
        data.update(self._oauth_data or {})
        return data

    async def _async_validate_website(self, user_input: dict[str, Any]) -> dict[str, str]:
        errors: dict[str, str] = {}
        session = aiohttp_client.async_create_clientsession(
            self.hass, auto_cleanup=False, cookie_jar=aiohttp.CookieJar()
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

    def _duplicate_website_identity(self, identity: str, current_entry_id: str) -> bool:
        return any(
            entry.entry_id != current_entry_id and entry.unique_id == identity
            for entry in self.hass.config_entries.async_entries(DOMAIN)
        )

    async def async_step_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect required per-member Website credentials."""
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input[CONF_EXPERIMENTAL_CONFIRMED]:
                errors["base"] = "experimental_confirmation_required"
            elif not user_input[CONF_STORAGE_WARNING_CONFIRMED]:
                errors["base"] = "storage_confirmation_required"
            else:
                errors = await self._async_validate_website(user_input)
                if not errors:
                    identity = _identity(user_input[CONF_LOGIN_ID])
                    if self.context.get("source") != config_entries.SOURCE_RECONFIGURE:
                        await self.async_set_unique_id(identity)
                        self._abort_if_unique_id_configured()
                    website_data = {
                        CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                        CONF_PASSWORD: user_input[CONF_PASSWORD],
                        CONF_EXPERIMENTAL_CONFIRMED: True,
                        CONF_STORAGE_WARNING_CONFIRMED: True,
                    }
                    if self.context.get("source") == config_entries.SOURCE_RECONFIGURE:
                        entry = self._get_reconfigure_entry()
                        if self._duplicate_website_identity(identity, entry.entry_id):
                            return self.async_abort(reason="already_configured")
                        return self.async_update_reload_and_abort(
                            entry,
                            data_updates={
                                **website_data,
                                CONF_ACCOUNT_LABEL: self._account_label,
                                CONF_MODE: MODE_HYBRID,
                            },
                            unique_id=identity,
                            title=f"HealthPlanet - {self._account_label}",
                        )
                    oauth_data = self._oauth_data or {}
                    self._oauth_data = None
                    return self.async_create_entry(
                        title=f"HealthPlanet - {self._account_label}",
                        data={
                            **oauth_data,
                            **website_data,
                            CONF_ACCOUNT_LABEL: self._account_label,
                            CONF_MODE: MODE_HYBRID,
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
        self._account_label = _label(entry.data.get(CONF_ACCOUNT_LABEL, entry.title))
        self._reauth_source = entry_data.get(CONF_REAUTH_SOURCE)
        if self._reauth_source is None:
            self._reauth_source = {
                MODE_OFFICIAL_ONLY: SOURCE_OFFICIAL,
                MODE_WEBSITE_ONLY: SOURCE_WEBSITE,
                MODE_HYBRID: "both",
            }[entry.data[CONF_MODE]]
        if self._reauth_source == SOURCE_WEBSITE:
            return await self.async_step_reauth_website()
        return await self.async_step_pick_implementation()

    async def async_step_reauth_website(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Replace only Website credentials, optionally after official authorization."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()
        if user_input is not None:
            try:
                errors = await self._async_validate_website(user_input)
            except HealthPlanetError:
                errors["base"] = "invalid_auth"
            if not errors:
                identity = _identity(user_input[CONF_LOGIN_ID])
                if self._duplicate_website_identity(identity, entry.entry_id):
                    return self.async_abort(reason="already_configured")
                updates = {
                    CONF_LOGIN_ID: user_input[CONF_LOGIN_ID],
                    CONF_PASSWORD: user_input[CONF_PASSWORD],
                }
                if self._oauth_data is not None:
                    data = self._official_reauth_data({**entry.data, **updates})
                    self._oauth_data = None
                    return self.async_update_reload_and_abort(entry, data=data, unique_id=identity)
                return self.async_update_reload_and_abort(
                    entry, data_updates=updates, unique_id=identity
                )
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
        """Upgrade either legacy single-source entry to Hybrid in place."""
        entry = self._get_reconfigure_entry()
        mode = entry.data[CONF_MODE]
        if mode not in {MODE_WEBSITE_ONLY, MODE_OFFICIAL_ONLY}:
            return self.async_abort(reason="reconfigure_not_supported")
        if user_input is not None and _UPGRADE_TO_HYBRID in user_input:
            if not user_input[_UPGRADE_TO_HYBRID]:
                return self.async_abort(reason="reconfigure_no_changes")
            self._account_label = _label(user_input[CONF_ACCOUNT_LABEL])
            if mode == MODE_WEBSITE_ONLY:
                return await self.async_step_pick_implementation()
            return await self.async_step_website()
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Required(_UPGRADE_TO_HYBRID, default=True): bool,
                    vol.Required(
                        CONF_ACCOUNT_LABEL,
                        default=_label(entry.data.get(CONF_ACCOUNT_LABEL, "")),
                    ): vol.All(str, vol.Length(min=1)),
                }
            ),
        )

    @override
    async def async_oauth_create_entry(self, data: dict[str, Any]) -> ConfigFlowResult:
        """Reject the incompatible callback-based OAuth path."""
        return self.async_abort(reason="callback_oauth_not_supported")

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> HealthPlanetOptionsFlow:
        return HealthPlanetOptionsFlow(config_entry)


class HealthPlanetOptionsFlow(config_entries.OptionsFlow):
    """Configure source polling and bounded history synchronization."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self._entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)
        mode = self._entry.data[CONF_MODE]
        schema: dict[Any, Any] = {}
        interval_validator = vol.All(
            vol.Coerce(int),
            vol.Range(min=MIN_UPDATE_INTERVAL_MINUTES, max=MAX_UPDATE_INTERVAL_MINUTES),
        )
        if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY}:
            schema[
                vol.Required(
                    CONF_OFFICIAL_UPDATE_INTERVAL,
                    default=self._entry.options.get(
                        CONF_OFFICIAL_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
                    ),
                )
            ] = interval_validator
        if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY}:
            schema[
                vol.Required(
                    CONF_WEBSITE_UPDATE_INTERVAL,
                    default=self._entry.options.get(
                        CONF_WEBSITE_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL_MINUTES
                    ),
                )
            ] = interval_validator
        schema[
            vol.Required(
                CONF_HISTORY_SYNC_ENABLED,
                default=self._entry.options.get(
                    CONF_HISTORY_SYNC_ENABLED, DEFAULT_HISTORY_SYNC_ENABLED
                ),
            )
        ] = bool
        if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY}:
            schema[
                vol.Required(
                    CONF_OFFICIAL_HISTORY_DAYS,
                    default=self._entry.options.get(
                        CONF_OFFICIAL_HISTORY_DAYS, DEFAULT_OFFICIAL_HISTORY_DAYS
                    ),
                )
            ] = vol.All(vol.Coerce(int), vol.Range(min=1, max=MAX_OFFICIAL_HISTORY_DAYS))
        return self.async_show_form(step_id="init", data_schema=vol.Schema(schema))
