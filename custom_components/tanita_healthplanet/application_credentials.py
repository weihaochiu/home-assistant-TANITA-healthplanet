"""Application Credentials support for HealthPlanet OAuth2."""

from __future__ import annotations

import json
from http import HTTPStatus
from typing import Any, cast, override
from urllib.parse import parse_qs

from aiohttp import ClientError, ClientResponseError, RequestInfo
from homeassistant.components.application_credentials import ClientCredential
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
)
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.config_entry_oauth2_flow import LocalOAuth2Implementation
from multidict import CIMultiDict, CIMultiDictProxy
from yarl import URL

from .const import (
    DOMAIN,
    OFFICIAL_AUTH_URL,
    OFFICIAL_REDIRECT_URI,
    OFFICIAL_SCOPE,
    OFFICIAL_TOKEN_URL,
)

# HealthPlanet documents authorization_code as its only grant and does not
# document refresh_token or expiry. A long HA-side validity window avoids
# fabricating refresh calls; an API authentication failure starts reauth.
_UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS = 10 * 365 * 24 * 60 * 60


def _oauth_request_info() -> RequestInfo:
    """Create a non-sensitive request descriptor for HA OAuth exceptions."""
    url = URL(OFFICIAL_TOKEN_URL)
    return RequestInfo(
        url,
        "POST",
        CIMultiDictProxy(CIMultiDict()),
        url,
    )


class HealthPlanetOAuth2Implementation(LocalOAuth2Implementation):
    """OAuth implementation that normalizes HealthPlanet's token response."""

    @property
    @override
    def extra_authorize_data(self) -> dict[str, str]:
        return {"scope": OFFICIAL_SCOPE}

    @property
    @override
    def redirect_uri(self) -> str:
        """Use HealthPlanet's documented manual-code redirect."""
        return OFFICIAL_REDIRECT_URI

    async def async_generate_manual_authorize_url(self) -> str:
        """Build a provider-compatible URL without a state callback."""
        from yarl import URL

        return str(
            URL(self.authorize_url).with_query(
                {
                    "client_id": self.client_id,
                    "redirect_uri": OFFICIAL_REDIRECT_URI,
                    "scope": OFFICIAL_SCOPE,
                    "response_type": "code",
                }
            )
        )

    async def async_exchange_authorization_code(self, code: str) -> str:
        """Exchange one in-memory authorization code and return only the access token."""
        request_data = {
            "redirect_uri": OFFICIAL_REDIRECT_URI,
            "code": code,
            "grant_type": "authorization_code",
        }
        try:
            token = await self._token_request(request_data)
        finally:
            request_data.clear()
            code = ""
        return str(token["access_token"])

    async def _token_request(self, data: dict[str, Any]) -> dict[str, Any]:
        """Request a token without ever logging the response payload."""
        request_data = {
            **data,
            "client_id": self.client_id,
            "client_secret": self.client_secret,
        }
        try:
            response = await async_get_clientsession(self.hass).post(
                self.token_url, data=request_data
            )
            body = await response.text()
            response.raise_for_status()
        except ClientResponseError as error:
            if error.status == HTTPStatus.TOO_MANY_REQUESTS or error.status >= 500:
                raise OAuth2TokenRequestTransientError(
                    request_info=error.request_info,
                    history=error.history,
                    status=error.status,
                    message="healthplanet_oauth_transient_error",
                    headers=error.headers,
                    domain=DOMAIN,
                ) from error
            raise OAuth2TokenRequestReauthError(
                request_info=error.request_info,
                history=error.history,
                status=error.status,
                message="healthplanet_oauth_reauthorization_required",
                headers=error.headers,
                domain=DOMAIN,
            ) from error
        except ClientError as error:
            raise OAuth2TokenRequestError(
                request_info=_oauth_request_info(),
                history=(),
                status=0,
                message="healthplanet_oauth_connection_failed",
                headers=None,
                domain=DOMAIN,
            ) from error
        token: dict[str, Any]
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, TypeError):
            query = parse_qs(body, keep_blank_values=True)
            token = {key: values[0] for key, values in query.items() if values}
        else:
            token = cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}
        body = ""
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise OAuth2TokenRequestError(
                request_info=_oauth_request_info(),
                history=(),
                status=0,
                message="healthplanet_oauth_token_missing",
                headers=None,
                domain=DOMAIN,
            )
        try:
            expires_in = int(token.get("expires_in", _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS))
        except (TypeError, ValueError):
            expires_in = _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS
        if expires_in <= 0:
            expires_in = _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS
        return {
            "access_token": access_token,
            "token_type": token.get("token_type", "Bearer"),
            "expires_in": expires_in,
        }

    @override
    async def _async_refresh_token(self, token: dict[str, Any]) -> dict[str, Any]:
        """Require reauthorization because the provider documents no refresh grant."""
        raise OAuth2TokenRequestReauthError(
            request_info=_oauth_request_info(),
            history=(),
            status=HTTPStatus.UNAUTHORIZED,
            message="healthplanet_oauth_reauthorization_required",
            headers=None,
            domain=DOMAIN,
        )


async def async_get_auth_implementation(
    hass: HomeAssistant, auth_domain: str, credential: ClientCredential
) -> HealthPlanetOAuth2Implementation:
    """Create the OAuth implementation from HA Application Credentials."""
    return HealthPlanetOAuth2Implementation(
        hass,
        auth_domain,
        credential.client_id,
        credential.client_secret,
        OFFICIAL_AUTH_URL,
        OFFICIAL_TOKEN_URL,
    )


async def async_get_description_placeholders(hass: HomeAssistant) -> dict[str, str]:
    """Describe the required HealthPlanet application registration."""
    return {
        "oauth_scope": OFFICIAL_SCOPE,
        "redirect_uri": OFFICIAL_REDIRECT_URI,
    }
