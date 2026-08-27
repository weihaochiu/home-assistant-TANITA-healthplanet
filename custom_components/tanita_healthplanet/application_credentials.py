"""Application Credentials support for HealthPlanet OAuth2."""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from typing import Any, cast, override
from urllib.parse import parse_qs, urlsplit

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

_LOGGER = logging.getLogger(__package__)
_ALLOWED_PROVIDER_ERRORS = {
    "invalid_grant": "oauth_token_invalid_grant",
    "invalid_client": "oauth_token_invalid_client",
    "invalid_request": "oauth_token_invalid_request",
    "unsupported_grant_type": "oauth_token_unsupported_grant_type",
}


def normalize_authorization_code(value: str) -> str:
    """Accept a raw code or the exact documented HealthPlanet success URL."""
    normalized = value.strip()
    if "://" not in normalized:
        return normalized
    parsed = urlsplit(normalized)
    if (
        parsed.scheme != "https"
        or parsed.netloc != "www.healthplanet.jp"
        or parsed.path != "/success.html"
        or parsed.fragment
    ):
        return ""
    codes = parse_qs(parsed.query, keep_blank_values=True).get("code", [])
    return codes[0].strip() if len(codes) == 1 else ""


def _parsed_token_body(body: str) -> tuple[dict[str, Any], str]:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError):
        if "=" not in body:
            return {}, "invalid"
        query = parse_qs(body, keep_blank_values=True)
        return ({key: values[0] for key, values in query.items() if values}, "form")
    return (cast(dict[str, Any], parsed) if isinstance(parsed, dict) else {}, "json")


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
        code = normalize_authorization_code(code)
        if not code:
            self._record_status(0, "none", "none", "oauth_token_invalid_grant", "ValueError")
            raise OAuth2TokenRequestReauthError(
                request_info=_oauth_request_info(),
                history=(),
                status=HTTPStatus.BAD_REQUEST,
                message="oauth_token_invalid_grant",
                headers=None,
                domain=DOMAIN,
            )
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
        body = ""
        try:
            response = await async_get_clientsession(self.hass).post(
                self.token_url,
                data=request_data,
                headers={
                    "Accept": "application/json, application/x-www-form-urlencoded",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
            )
            body = await response.text()
            token, response_format = _parsed_token_body(body)
            content_type = str(getattr(response, "headers", {}).get("Content-Type", ""))
            content_category = (
                "json"
                if "json" in content_type.casefold() or response_format == "json"
                else "form"
                if response_format == "form"
                else "other"
            )
            status = int(response.status)
            if status >= 400:
                provider_error = token.get("error")
                error_id = _ALLOWED_PROVIDER_ERRORS.get(
                    provider_error if isinstance(provider_error, str) else "",
                    "oauth_token_http_error",
                )
                self._record_status(status, content_category, response_format, error_id)
                if status == HTTPStatus.TOO_MANY_REQUESTS or status >= 500:
                    raise OAuth2TokenRequestTransientError(
                        request_info=_oauth_request_info(),
                        history=(),
                        status=status,
                        message=error_id,
                        headers=None,
                        domain=DOMAIN,
                    )
                raise OAuth2TokenRequestReauthError(
                    request_info=_oauth_request_info(),
                    history=(),
                    status=status,
                    message=error_id,
                    headers=None,
                    domain=DOMAIN,
                )
        except (OAuth2TokenRequestReauthError, OAuth2TokenRequestTransientError):
            raise
        except ClientResponseError as error:
            error_id = (
                "oauth_token_http_error"
                if error.status not in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}
                else "oauth_token_invalid_client"
            )
            self._record_status(error.status, "none", "none", error_id, type(error).__name__)
            if error.status == HTTPStatus.TOO_MANY_REQUESTS or error.status >= 500:
                raise OAuth2TokenRequestTransientError(
                    request_info=error.request_info,
                    history=error.history,
                    status=error.status,
                    message=error_id,
                    headers=error.headers,
                    domain=DOMAIN,
                ) from error
            raise OAuth2TokenRequestReauthError(
                request_info=error.request_info,
                history=error.history,
                status=error.status,
                message=error_id,
                headers=error.headers,
                domain=DOMAIN,
            ) from error
        except (TimeoutError, ClientError) as error:
            error_id = (
                "oauth_token_timeout"
                if isinstance(error, TimeoutError)
                else "oauth_token_network_error"
            )
            self._record_status(0, "none", "none", error_id, type(error).__name__)
            raise OAuth2TokenRequestError(
                request_info=_oauth_request_info(),
                history=(),
                status=0,
                message="healthplanet_oauth_connection_failed",
                headers=None,
                domain=DOMAIN,
            ) from error
        body = ""
        access_token = token.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            self._record_status(
                int(response.status),
                content_category,
                response_format,
                "oauth_token_missing" if token else "oauth_token_response_invalid",
            )
            raise OAuth2TokenRequestError(
                request_info=_oauth_request_info(),
                history=(),
                status=0,
                message="oauth_token_missing" if token else "oauth_token_response_invalid",
                headers=None,
                domain=DOMAIN,
            )
        try:
            expires_in = int(token.get("expires_in", _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS))
        except (TypeError, ValueError):
            expires_in = _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS
        if expires_in <= 0:
            expires_in = _UNDOCUMENTED_EXPIRY_FALLBACK_SECONDS
        self._record_status(int(response.status), content_category, response_format, None)
        return {
            "access_token": access_token,
            "token_type": token.get("token_type", "Bearer"),
            "expires_in": expires_in,
        }

    def _record_status(
        self,
        http_status: int,
        content_category: str,
        response_format: str,
        error_id: str | None,
        exception_type: str | None = None,
    ) -> None:
        """Keep and log only fixed, privacy-safe OAuth metadata."""
        domain_data = getattr(self.hass, "data", {}).setdefault(DOMAIN, {})
        domain_data["oauth_status"] = {
            "last_oauth_http_status": http_status,
            "last_oauth_error_id": error_id,
        }
        if error_id:
            _LOGGER.warning(
                "HealthPlanet OAuth failed: stage=token_exchange http_status=%s "
                "content_category=%s response_format=%s error_id=%s exception_type=%s",
                http_status,
                content_category,
                response_format,
                error_id,
                exception_type,
            )

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
