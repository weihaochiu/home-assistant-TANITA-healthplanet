"""HTTP providers for official and experimental HealthPlanet data."""

from __future__ import annotations

import asyncio
import json
import re
from html.parser import HTMLParser
from time import monotonic
from typing import Any
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit

import aiohttp

from .const import (
    OFFICIAL_AUTH_URL,
    OFFICIAL_DATA_URL,
    OFFICIAL_REDIRECT_URI,
    OFFICIAL_SCOPE,
    OFFICIAL_TAG_BODY_FAT,
    OFFICIAL_TAG_WEIGHT,
    OFFICIAL_TOKEN_URL,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
    REQUEST_TIMEOUT_SECONDS,
    USER_AGENT,
    WEBSITE_GRAPH_URL,
    WEBSITE_KINDS,
    WEBSITE_LOGIN_URL,
    WEBSITE_REQUEST_INTERVAL_SECONDS,
)
from .errors import (
    HealthPlanetAuthError,
    HealthPlanetBackendCodeError,
    HealthPlanetConnectionError,
    HealthPlanetManualInteractionRequired,
    HealthPlanetRateLimitError,
    HealthPlanetSchemaError,
)
from .models import ProviderSnapshot
from .parser import parse_official_payload, parse_website_payload

_CHALLENGE_MARKERS = (
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-chl",
    "cloudflare challenge",
    "one-time password",
    "one time password",
    "two-factor",
    "multi-factor",
    "ワンタイムパスワード",
    "二段階認証",
)
_AUTH_MARKERS = ("logout", "ログアウト")


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.action = ""
        self.method = ""
        self.login_field = ""
        self.password_field = ""
        self.hidden: dict[str, str] = {}
        self._in_candidate = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        if tag.casefold() == "form":
            self._in_candidate = attributes.get("method", "get").casefold() == "post"
            if self._in_candidate:
                self.action = attributes.get("action", "")
            return
        if tag.casefold() != "input" or not self._in_candidate:
            return
        name = attributes.get("name", "")
        input_type = attributes.get("type", "text").casefold()
        normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
        if input_type == "hidden" and name:
            self.hidden[name] = attributes.get("value", "")
        elif input_type in {"email", "text"} and normalized in {
            "email",
            "loginid",
            "userid",
            "username",
        }:
            self.login_field = name
        elif input_type == "password" and name:
            self.password_field = name

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form":
            self._in_candidate = False


def build_authorize_url(client_id: str) -> str:
    parameters = {
        "client_id": client_id,
        "redirect_uri": OFFICIAL_REDIRECT_URI,
        "scope": OFFICIAL_SCOPE,
        "response_type": "code",
    }
    return f"{OFFICIAL_AUTH_URL}?{urlencode(parameters)}"


def _fixed_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise HealthPlanetSchemaError("response_json_invalid") from None


class OfficialApiClient:
    """Client for the documented OAuth API (weight and body-fat percentage)."""

    provider_type = PROVIDER_OFFICIAL

    def __init__(self, session: aiohttp.ClientSession, access_token: str) -> None:
        self._session = session
        self._access_token = access_token

    @staticmethod
    async def async_exchange_code(
        session: aiohttp.ClientSession,
        *,
        client_id: str,
        client_secret: str,
        code: str,
    ) -> str:
        form = {
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": OFFICIAL_REDIRECT_URI,
            "code": code,
            "grant_type": "authorization_code",
        }
        try:
            async with session.post(
                OFFICIAL_TOKEN_URL,
                data=form,
                headers={"User-Agent": USER_AGENT},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                body = await response.text()
                if response.status in {400, 401, 403}:
                    raise HealthPlanetAuthError("official_oauth_exchange_failed")
                if response.status == 429:
                    raise HealthPlanetRateLimitError("official_oauth_rate_limited")
                if response.status >= 500:
                    raise HealthPlanetConnectionError("official_oauth_service_unavailable")
        except TimeoutError:
            raise HealthPlanetConnectionError("official_oauth_timeout") from None
        except aiohttp.ClientError:
            raise HealthPlanetConnectionError("official_oauth_connection_failed") from None
        finally:
            form = {}
        token: Any = None
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            parsed_query = parse_qs(body, keep_blank_values=True)
            if parsed_query.get("access_token"):
                token = parsed_query["access_token"][0]
        else:
            if isinstance(parsed, dict):
                token = parsed.get("access_token")
        body = ""
        if not isinstance(token, str) or not token:
            raise HealthPlanetAuthError("official_oauth_token_missing")
        return token

    async def async_fetch(self) -> ProviderSnapshot:
        form = {
            "access_token": self._access_token,
            "tag": f"{OFFICIAL_TAG_WEIGHT},{OFFICIAL_TAG_BODY_FAT}",
            "date": "1",
        }
        try:
            async with self._session.post(
                OFFICIAL_DATA_URL,
                data=form,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                body = await response.text()
                if response.status in {400, 401, 403}:
                    raise HealthPlanetAuthError("official_api_authentication_failed")
                if response.status == 429:
                    raise HealthPlanetRateLimitError("official_api_rate_limited")
                if response.status >= 500:
                    raise HealthPlanetConnectionError("official_api_service_unavailable")
                if response.status != 200:
                    raise HealthPlanetConnectionError("official_api_request_failed")
        except TimeoutError:
            raise HealthPlanetConnectionError("official_api_timeout") from None
        except aiohttp.ClientError:
            raise HealthPlanetConnectionError("official_api_connection_failed") from None
        finally:
            form = {}
        payload = _fixed_json(body)
        body = ""
        parsed = parse_official_payload(payload)
        measurements = {kind: values[-1] if values else None for kind, values in parsed.items()}
        return ProviderSnapshot(measurements=measurements)

    async def async_close(self) -> None:
        self._access_token = ""


class WebsiteApiClient:
    """Opt-in client for the unofficial authenticated website endpoint."""

    provider_type = PROVIDER_WEBSITE

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        login_id: str,
        password: str,
        request_interval: float = WEBSITE_REQUEST_INTERVAL_SECONDS,
    ) -> None:
        self._session = session
        self._login_id = login_id
        self._password = password
        self._request_interval = request_interval
        self._last_request_at: float | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()

    async def _throttle(self) -> None:
        if self._last_request_at is not None:
            remaining = self._request_interval - (monotonic() - self._last_request_at)
            if remaining > 0:
                await asyncio.sleep(remaining)
        self._last_request_at = monotonic()

    async def _request(
        self,
        method: str,
        url: str,
        *,
        data: dict[str, str] | None = None,
        params: dict[str, int] | None = None,
    ) -> tuple[int, str, str, str]:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or parsed.hostname != "www.healthplanet.jp":
            raise HealthPlanetConnectionError("website_cross_host_blocked")
        await self._throttle()
        try:
            async with self._session.request(
                method,
                url,
                data=data,
                params=params,
                allow_redirects=True,
                headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/json"},
                timeout=aiohttp.ClientTimeout(total=REQUEST_TIMEOUT_SECONDS),
            ) as response:
                body = await response.text(errors="replace")
                final_url = str(response.url.with_query(None))
                content_type = response.headers.get("Content-Type", "")
                status = response.status
        except TimeoutError:
            raise HealthPlanetConnectionError("website_request_timeout") from None
        except aiohttp.ClientError:
            raise HealthPlanetConnectionError("website_connection_failed") from None
        final = urlsplit(final_url)
        if final.scheme != "https" or final.hostname != "www.healthplanet.jp":
            body = ""
            raise HealthPlanetConnectionError("website_cross_host_redirect_blocked")
        if status in {401, 403}:
            body = ""
            raise HealthPlanetAuthError("website_authentication_failed")
        if status == 429:
            body = ""
            raise HealthPlanetRateLimitError("website_rate_limited")
        if status >= 500:
            body = ""
            raise HealthPlanetConnectionError("website_service_unavailable")
        return status, content_type, body, final_url

    @staticmethod
    def _detect_challenge(html: str) -> None:
        lowered = html.casefold()
        if any(marker in lowered for marker in _CHALLENGE_MARKERS):
            raise HealthPlanetManualInteractionRequired("website_manual_interaction_required")

    async def _login(self) -> None:
        status, content_type, html, page_url = await self._request("GET", WEBSITE_LOGIN_URL)
        if status != 200 or "html" not in content_type.casefold():
            html = ""
            raise HealthPlanetAuthError("website_login_page_unavailable")
        self._detect_challenge(html)
        parser = _LoginFormParser()
        parser.feed(html)
        html = ""
        if not parser.login_field or not parser.password_field:
            raise HealthPlanetSchemaError("website_login_form_changed")
        action_url = urljoin(page_url, parser.action or page_url)
        action = urlsplit(action_url)
        if action.scheme != "https" or action.hostname != "www.healthplanet.jp":
            raise HealthPlanetConnectionError("website_login_action_blocked")
        form: dict[str, str] = dict(parser.hidden)
        form[parser.login_field] = self._login_id
        form[parser.password_field] = self._password
        try:
            status, content_type, response_html, final_url = await self._request(
                "POST", action_url, data=form
            )
        finally:
            form.clear()
            parser.hidden.clear()
        self._detect_challenge(response_html)
        lowered = response_html.casefold()
        still_login = (
            "/login" in urlsplit(final_url).path.casefold() or 'type="password"' in lowered
        )
        authenticated_marker = any(marker in lowered for marker in _AUTH_MARKERS)
        response_html = ""
        if status != 200 or "html" not in content_type.casefold() or still_login:
            raise HealthPlanetAuthError("website_invalid_credentials")
        if not authenticated_marker:
            raise HealthPlanetManualInteractionRequired("website_authentication_unconfirmed")
        self._authenticated = True

    async def async_validate_credentials(self) -> None:
        async with self._lock:
            await self._login()

    async def _fetch_once(self) -> ProviderSnapshot:
        measurements: dict[int, Any] = {}
        errors: dict[int, str] = {}
        for kind in WEBSITE_KINDS:
            status, content_type, body, final_url = await self._request(
                "GET",
                WEBSITE_GRAPH_URL,
                params={"day": 31, "page": 1, "kind": kind},
            )
            if "/login" in urlsplit(final_url).path.casefold() or "html" in content_type.casefold():
                body = ""
                self._authenticated = False
                raise HealthPlanetAuthError("website_session_expired")
            if status != 200 or "json" not in content_type.casefold():
                body = ""
                errors[kind] = "website_response_invalid"
                measurements[kind] = None
                continue
            try:
                payload = _fixed_json(body)
                values = parse_website_payload(payload, kind)
            except (HealthPlanetBackendCodeError, HealthPlanetSchemaError) as error:
                errors[kind] = str(error)
                values = []
            finally:
                body = ""
            measurements[kind] = values[-1] if values else None
        return ProviderSnapshot(measurements=measurements, errors=errors)

    async def async_fetch(self) -> ProviderSnapshot:
        async with self._lock:
            if not self._authenticated:
                await self._login()
            try:
                return await self._fetch_once()
            except HealthPlanetAuthError as error:
                if str(error) != "website_session_expired":
                    raise
                # One controlled re-login only; no loop or background retry storm.
                await self._login()
                return await self._fetch_once()

    async def async_close(self) -> None:
        async with self._lock:
            self._authenticated = False
            self._login_id = ""
            self._password = ""
            self._session.cookie_jar.clear()
            if not self._session.closed:
                # HA-created sessions share its connector and must be detached,
                # not closed. Test doubles without detach still close normally.
                detach = getattr(self._session, "detach", None)
                if callable(detach):
                    detach()
                else:
                    await self._session.close()
