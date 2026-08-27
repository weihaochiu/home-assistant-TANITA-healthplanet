"""HTTP providers for official and experimental HealthPlanet data."""

from __future__ import annotations

import asyncio
import json
import re
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from time import monotonic
from typing import Any
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import aiohttp

from .const import (
    JST_TIMEZONE,
    OFFICIAL_INNERSCAN_KINDS,
    OFFICIAL_INNERSCAN_URL,
    OFFICIAL_SPHYGMO_KINDS,
    OFFICIAL_SPHYGMO_URL,
    OFFICIAL_TAG_BODY_FAT,
    OFFICIAL_TAG_DIASTOLIC,
    OFFICIAL_TAG_PULSE,
    OFFICIAL_TAG_SYSTOLIC,
    OFFICIAL_TAG_WEIGHT,
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
from .models import ContentCategory, EndpointStatus, KindStatus, ProviderSnapshot
from .parser import (
    OfficialParseResult,
    parse_official_innerscan_payload,
    parse_official_sphygmomanometer_payload,
    parse_website_payload_result,
)

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


def _fixed_json(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        raise HealthPlanetSchemaError("response_json_invalid") from None


def _safe_backend_code(payload: Any) -> int | None:
    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if isinstance(code, list) and len(code) == 1:
        code = code[0]
    return code if isinstance(code, int) and not isinstance(code, bool) else None


class OfficialApiClient:
    """Client for the two documented official measurement endpoints."""

    provider_type = PROVIDER_OFFICIAL

    def __init__(
        self,
        session: aiohttp.ClientSession,
        access_token: str | None = None,
        *,
        oauth_session: Any | None = None,
    ) -> None:
        self._session = session
        self._access_token = access_token or ""
        self._oauth_session = oauth_session
        self._last_endpoint_statuses: dict[str, EndpointStatus] = {}

    @property
    def diagnostic_statuses(self) -> dict[str, EndpointStatus]:
        """Return only privacy-safe endpoint metadata."""
        return dict(self._last_endpoint_statuses)

    async def _async_current_access_token(self) -> str:
        if self._oauth_session is not None:
            await self._oauth_session.async_ensure_token_valid()
            token = self._oauth_session.token.get("access_token")
            if not isinstance(token, str) or not token:
                raise HealthPlanetAuthError("official_oauth_token_missing")
            return token
        if not self._access_token:
            raise HealthPlanetAuthError("official_oauth_token_missing")
        return self._access_token

    async def _async_fetch_endpoint(
        self,
        url: str,
        tags: tuple[str, ...],
        parser: Any,
        history_days: int | None = None,
    ) -> tuple[OfficialParseResult, int]:
        access_token = await self._async_current_access_token()
        form = {
            "access_token": access_token,
            "tag": ",".join(tags),
            "date": "1",
        }
        if history_days is not None:
            now_jst = datetime.now(UTC).astimezone(ZoneInfo(JST_TIMEZONE))
            form["from"] = (now_jst - timedelta(days=history_days)).strftime("%Y%m%d%H%M%S")
            form["to"] = now_jst.strftime("%Y%m%d%H%M%S")
        try:
            async with self._session.post(
                url,
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
        return parser(payload), response.status

    async def _async_fetch(self, history_days: int | None) -> ProviderSnapshot:
        measurements: dict[int, Any] = {}
        history: dict[int, tuple[Any, ...]] = {}
        errors: dict[int, str] = {}
        statuses: dict[str, EndpointStatus] = {}
        self._last_endpoint_statuses = statuses
        endpoints = (
            (
                "innerscan",
                OFFICIAL_INNERSCAN_URL,
                (OFFICIAL_TAG_WEIGHT, OFFICIAL_TAG_BODY_FAT),
                OFFICIAL_INNERSCAN_KINDS,
                parse_official_innerscan_payload,
            ),
            (
                "sphygmomanometer",
                OFFICIAL_SPHYGMO_URL,
                (OFFICIAL_TAG_SYSTOLIC, OFFICIAL_TAG_DIASTOLIC, OFFICIAL_TAG_PULSE),
                OFFICIAL_SPHYGMO_KINDS,
                parse_official_sphygmomanometer_payload,
            ),
        )
        for name, url, tags, kinds, parser in endpoints:
            try:
                parsed, http_status = await self._async_fetch_endpoint(
                    url, tags, parser, history_days
                )
            except HealthPlanetAuthError:
                statuses[name] = EndpointStatus(
                    outcome="auth_error",
                    unavailable_tags=tags,
                    error_id="official_api_authentication_failed",
                )
                raise
            except HealthPlanetRateLimitError:
                error_id = "official_api_rate_limited"
                measurements.update(dict.fromkeys(kinds))
                errors.update(dict.fromkeys(kinds, error_id))
                statuses[name] = EndpointStatus(
                    outcome="rate_limited",
                    unavailable_tags=tags,
                    error_id=error_id,
                )
                continue
            except HealthPlanetConnectionError:
                error_id = "official_api_connection_failed"
                measurements.update(dict.fromkeys(kinds))
                errors.update(dict.fromkeys(kinds, error_id))
                statuses[name] = EndpointStatus(
                    outcome="http_error",
                    unavailable_tags=tags,
                    error_id=error_id,
                )
                continue
            except HealthPlanetSchemaError as error:
                error_id = str(error)
                measurements.update(dict.fromkeys(kinds))
                errors.update(dict.fromkeys(kinds, error_id))
                statuses[name] = EndpointStatus(
                    outcome="parser_error",
                    http_status=200,
                    unavailable_tags=tags,
                    error_id=error_id,
                )
                continue
            measurements.update(parsed.measurements)
            history.update(parsed.history)
            statuses[name] = EndpointStatus(
                outcome=(
                    "available"
                    if any(value is not None for value in parsed.measurements.values())
                    else "null"
                ),
                http_status=http_status,
                record_count=parsed.record_count,
                available_tags=parsed.available_tags,
                unavailable_tags=parsed.unavailable_tags,
                complete_pair_found=parsed.complete_pair_found,
            )
        return ProviderSnapshot(
            measurements=measurements,
            history=history,
            errors=errors,
            endpoint_statuses=dict(statuses),
        )

    async def async_fetch(self) -> ProviderSnapshot:
        """Fetch the provider's current/latest response."""
        return await self._async_fetch(None)

    async def async_fetch_history(self, days: int) -> ProviderSnapshot:
        """Fetch documented official history, bounded to 90 days by options."""
        return await self._async_fetch(days)

    async def async_close(self) -> None:
        self._access_token = ""
        self._oauth_session = None


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
        kinds: tuple[int, ...] = WEBSITE_KINDS,
    ) -> None:
        self._session = session
        self._login_id = login_id
        self._password = password
        self._request_interval = request_interval
        self._kinds = tuple(kinds)
        self._last_request_at: float | None = None
        self._authenticated = False
        self._lock = asyncio.Lock()
        self._last_kind_statuses: dict[int, KindStatus] = {}

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
        accept: str = "text/html,application/json",
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
                headers={"User-Agent": USER_AGENT, "Accept": accept},
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
        if status == 429:
            body = ""
            raise HealthPlanetRateLimitError("website_rate_limited")
        return status, content_type, body, final_url

    @staticmethod
    def _content_category(content_type: str, body: str) -> ContentCategory:
        lowered_type = content_type.casefold()
        prefix = body.lstrip()[:32].casefold()
        if "html" in lowered_type or prefix.startswith(("<!doctype html", "<html", "<form")):
            return "html"
        if "json" in lowered_type:
            return "json"
        return "other"

    @property
    def diagnostic_statuses(self) -> dict[int, KindStatus]:
        """Return only privacy-safe structural outcomes from the latest attempt."""
        return dict(self._last_kind_statuses)

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
        history: dict[int, tuple[Any, ...]] = {}
        errors: dict[int, str] = {}
        statuses: dict[int, KindStatus] = {}
        self._last_kind_statuses = statuses
        for kind in self._kinds:
            try:
                status, content_type, body, final_url = await self._request(
                    "GET",
                    WEBSITE_GRAPH_URL,
                    params={"day": 31, "page": 1, "kind": kind},
                    accept="application/json",
                )
            except HealthPlanetConnectionError as error:
                error_id = str(error)
                errors[kind] = error_id
                measurements[kind] = None
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="http_error",
                    error_id=error_id,
                )
                continue
            category = self._content_category(content_type, body)
            if status in {401, 403}:
                body = ""
                self._authenticated = False
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="auth_error",
                    http_status=status,
                    content_category=category,
                    error_id="website_authentication_failed",
                )
                raise HealthPlanetAuthError("website_authentication_failed")
            if "/login" in urlsplit(final_url).path.casefold() or category == "html":
                body = ""
                self._authenticated = False
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="html",
                    http_status=status,
                    content_category="html",
                    error_id="website_session_expired",
                )
                raise HealthPlanetAuthError("website_session_expired")
            if status != 200:
                body = ""
                error_id = "website_http_status"
                errors[kind] = error_id
                measurements[kind] = None
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="http_error",
                    http_status=status,
                    content_category=category,
                    error_id=error_id,
                )
                continue
            if category != "json":
                body = ""
                error_id = "website_content_type_invalid"
                errors[kind] = error_id
                measurements[kind] = None
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="http_error",
                    http_status=status,
                    content_category=category,
                    error_id=error_id,
                )
                continue
            payload: Any = None
            try:
                payload = _fixed_json(body)
                parsed = parse_website_payload_result(payload, kind)
            except HealthPlanetBackendCodeError as error:
                error_id = str(error)
                errors[kind] = error_id
                measurements[kind] = None
                rows = payload.get("value1") if isinstance(payload, dict) else None
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="backend_error",
                    http_status=status,
                    content_category="json",
                    backend_code=error.backend_code,
                    error_id=error_id,
                    row_count=len(rows) if isinstance(rows, list) else None,
                )
                continue
            except HealthPlanetSchemaError as error:
                error_id = str(error)
                errors[kind] = error_id
                measurements[kind] = None
                rows = payload.get("value1") if isinstance(payload, dict) else None
                statuses[kind] = KindStatus(
                    kind=kind,
                    outcome="parser_error",
                    http_status=status,
                    content_category="json",
                    backend_code=_safe_backend_code(payload),
                    error_id=error_id,
                    row_count=len(rows) if isinstance(rows, list) else None,
                    timestamp_parsing_success=False,
                    row_length=error.row_length,
                    timestamp_candidate_count=error.timestamp_candidate_count,
                    numeric_candidate_count=error.numeric_candidate_count,
                    valid_assignment_count=error.valid_assignment_count,
                    field_type_shape=error.field_type_shape,
                )
                continue
            finally:
                body = ""
            measurement = parsed.measurements[-1] if parsed.measurements else None
            measurements[kind] = measurement
            history[kind] = parsed.measurements
            statuses[kind] = KindStatus(
                kind=kind,
                outcome="available" if measurement is not None else "null",
                http_status=status,
                content_category="json",
                backend_code=0,
                row_count=parsed.row_count,
                timestamp_parsing_success=parsed.timestamp_parsing_success,
            )
        return ProviderSnapshot(
            measurements=measurements,
            history=history,
            errors=errors,
            kind_statuses=dict(statuses),
        )

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
