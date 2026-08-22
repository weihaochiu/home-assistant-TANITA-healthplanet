"""Authorized, privacy-safe HealthPlanet authenticated backend research probe.

This is a bounded research tool, not a production client. It reads credentials
inside the process, sends only allowlisted same-origin requests, and persists
schema metadata without response values, secrets, cookies, or identifiers.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
    build_opener,
)

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env.local"
OUTPUT_PATH = ROOT / "_local_only" / "healthplanet_schema_probe.json"
BASE_HOST = "www.healthplanet.jp"
BASE_URL = f"https://{BASE_HOST}"
LOGIN_URL = f"{BASE_URL}/login.do"
GRAPH_PATH = "/graph/graph.json"
GRAPH_URL = f"{BASE_URL}{GRAPH_PATH}"
USER_AGENT = (
    "home-assistant-TANITA-healthplanet-research/0.1 "
    "(+local authorized account research)"
)
KINDS = (1, 2, 3, 4, 5, 6, 7, 14, 22, 23)
KIND_NAMES = {
    1: "weight",
    2: "body_fat_percentage",
    3: "body_fat_mass",
    4: "visceral_fat_level",
    5: "basal_metabolic_rate",
    6: "muscle_mass",
    7: "estimated_bone_mass",
    14: "metabolic_age",
    22: "body_water_percentage",
    23: "muscle_quality_score",
}
REQUEST_LIMIT = 50
LOGIN_LIMIT = 2
REQUEST_INTERVAL_SECONDS = 1.0
TIMEOUT_SECONDS = 20
MAX_DISCOVERY_PAGES = 4
MAX_FIRST_PARTY_SCRIPTS = 8
MAX_OBSERVED_ENDPOINTS = 8
SAFE_UNITS = {
    "%",
    "kg",
    "kcal",
    "kcal/day",
    "level",
    "point",
    "points",
    "才",
    "歳",
    "点",
}
SAFE_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
VALUE_KEY_PATTERN = re.compile(r"^value\d+$", re.IGNORECASE)
TIMESTAMP_KEY_PATTERN = re.compile(r"(?:date|time|timestamp)", re.IGNORECASE)
DATA_MARKERS = ("graph", "measurement", "innerscan", "data")
MUTATION_MARKERS = (
    "delete",
    "edit",
    "insert",
    "logout",
    "password",
    "profile",
    "register",
    "remove",
    "setting",
    "update",
)
CHALLENGE_MARKERS = {
    "captcha",
    "recaptcha",
    "hcaptcha",
    "cf-chl",
    "cloudflare challenge",
    "bot verification",
    "verify you are human",
    "one-time password",
    "one time password",
    "otp",
    "two-factor",
    "multi-factor",
    "ワンタイムパスワード",
    "二段階認証",
    "同意が必要",
    "consent required",
}
AUTH_MARKERS = ("logout", "ログアウト")
LOGIN_PATH_MARKERS = ("/login", "login.do")
CSRF_NAME_MARKERS = ("csrf", "token", "authenticity")
SENSITIVE_KEY_MARKERS = (
    "account",
    "authorization",
    "birth",
    "cookie",
    "email",
    "gender",
    "height",
    "login",
    "mail",
    "name",
    "passwd",
    "password",
    "serial",
    "session",
    "sex",
    "token",
    "user",
)


class ResearchError(Exception):
    """Fixed-message error safe for terminal output."""


class ConfigurationError(ResearchError):
    pass


class ManualInteractionRequired(ResearchError):
    pass


class CrossHostRequestBlocked(ResearchError):
    pass


class RequestLimitReached(ResearchError):
    pass


class StopResearch(ResearchError):
    pass


@dataclass(frozen=True)
class ParsedLoginForm:
    action_url: str
    action_path: str
    method: str
    login_field: str
    password_field: str
    hidden_fields: dict[str, str]
    hidden_field_names: list[str]
    csrf_field_names: list[str]
    encoding: str


@dataclass
class _FormCandidate:
    action: str
    method: str
    encoding: str
    hidden_fields: dict[str, str] = field(default_factory=dict)
    login_field: str | None = None
    password_field: str | None = None
    consent_control: bool = False


@dataclass(frozen=True)
class ResponseData:
    status: int
    content_type: str
    body: bytes
    final_url: str


@dataclass(frozen=True)
class LoginResult:
    status: str
    page_url: str
    page_html: str
    metadata: dict[str, Any]


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_FormCandidate] = []
        self._current: _FormCandidate | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        lowered_tag = tag.casefold()
        if lowered_tag == "form":
            self._current = _FormCandidate(
                action=attributes.get("action", ""),
                method=attributes.get("method", "get").casefold(),
                encoding=attributes.get("accept-charset", "utf-8") or "utf-8",
            )
            return
        if lowered_tag != "input" or self._current is None:
            return
        input_type = attributes.get("type", "text").casefold()
        name = attributes.get("name", "")
        normalized = re.sub(r"[^a-z0-9]", "", name.casefold())
        if input_type == "hidden" and name:
            self._current.hidden_fields[name] = attributes.get("value", "")
        elif input_type in {"email", "text"} and normalized in {
            "email",
            "login",
            "loginid",
            "mail",
            "userid",
            "username",
        }:
            self._current.login_field = name
        elif input_type == "password" and name:
            self._current.password_field = name
        if "consent" in normalized or "agree" in normalized:
            self._current.consent_control = True

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.scripts: list[str] = []
        self.links: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.casefold(): value or "" for name, value in attrs}
        if tag.casefold() == "script" and attributes.get("src"):
            self.scripts.append(attributes["src"])
        elif tag.casefold() == "a" and attributes.get("href"):
            self.links.append(attributes["href"])


class SameHostRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        validate_same_host_url(new_url, base_url=request.full_url)
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


def validate_same_host_url(url: str, *, base_url: str = BASE_URL) -> str:
    absolute = urljoin(base_url, url)
    parsed = urlsplit(absolute)
    if (
        parsed.scheme.casefold() != "https"
        or parsed.hostname != BASE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise CrossHostRequestBlocked("CROSS_HOST_REQUEST_BLOCKED")
    return absolute


def detect_manual_interaction(html: str) -> None:
    lowered = html.casefold()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")


def parse_login_form(html: str, *, page_url: str = LOGIN_URL) -> ParsedLoginForm:
    detect_manual_interaction(html)
    parser = _LoginFormParser()
    try:
        parser.feed(html)
    except Exception:
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED") from None
    matches = [
        item
        for item in parser.forms
        if item.method == "post" and item.login_field and item.password_field
    ]
    if len(matches) != 1 or matches[0].consent_control:
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    selected = matches[0]
    action_url = validate_same_host_url(selected.action or page_url, base_url=page_url)
    hidden_names = sorted(selected.hidden_fields)
    csrf_names = sorted(
        name
        for name in hidden_names
        if any(marker in name.casefold() for marker in CSRF_NAME_MARKERS)
    )
    return ParsedLoginForm(
        action_url=action_url,
        action_path=urlsplit(action_url).path or "/",
        method="POST",
        login_field=selected.login_field or "",
        password_field=selected.password_field or "",
        hidden_fields=dict(selected.hidden_fields),
        hidden_field_names=hidden_names,
        csrf_field_names=csrf_names,
        encoding=selected.encoding,
    )


def _parse_env_value(raw: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        value = value[1:-1]
    return value


def load_credentials(path: Path = ENV_PATH) -> tuple[str, str]:
    if not path.is_file():
        raise ConfigurationError("CREDENTIAL_FILE_MISSING")
    values: dict[str, str] = {}
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, raw_value = line.split("=", 1)
                key = key.strip()
                if key in {"HEALTHPLANET_LOGIN_ID", "HEALTHPLANET_PASSWORD"}:
                    values[key] = _parse_env_value(raw_value)
    except (OSError, UnicodeError):
        raise ConfigurationError("CREDENTIAL_FILE_UNREADABLE") from None
    login_id = values.get("HEALTHPLANET_LOGIN_ID", "")
    password = values.get("HEALTHPLANET_PASSWORD", "")
    if not login_id or not password:
        login_id = ""
        password = ""
        raise ConfigurationError("CREDENTIAL_FIELDS_MISSING")
    return login_id, password


def _looks_like_login_url(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(marker in path for marker in LOGIN_PATH_MARKERS)


def _contains_login_form(html: str) -> bool:
    parser = _LoginFormParser()
    try:
        parser.feed(html)
    except Exception:
        return True
    return any(item.password_field for item in parser.forms)


def _is_authenticated_html(html: str) -> bool:
    lowered = html.casefold()
    return any(marker in lowered for marker in AUTH_MARKERS)


def _media_type(content_type: str) -> str:
    candidate = content_type.split(";", 1)[0].strip().casefold()
    if re.fullmatch(r"[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+", candidate):
        return candidate
    return "unknown"


class ResearchSession:
    def __init__(
        self,
        *,
        request_limit: int = REQUEST_LIMIT,
        interval_seconds: float = REQUEST_INTERVAL_SECONDS,
        sleeper=time.sleep,
        clock=time.monotonic,
    ) -> None:
        self.cookie_jar = CookieJar()
        self.opener = build_opener(
            SameHostRedirectHandler(), HTTPCookieProcessor(self.cookie_jar)
        )
        self.request_limit = request_limit
        self.interval_seconds = interval_seconds
        self.sleeper = sleeper
        self.clock = clock
        self.request_count = 0
        self.login_count = 0
        self._last_request_at: float | None = None
        self.closed = False

    def request(
        self,
        url: str,
        *,
        method: str = "GET",
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
        is_login: bool = False,
        retry_5xx: bool = True,
    ) -> ResponseData:
        absolute = validate_same_host_url(url)
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise StopResearch("METHOD_NOT_ALLOWED")
        if normalized_method == "POST" and not is_login:
            raise StopResearch("POST_NOT_ALLOWED")
        if is_login:
            if self.login_count >= LOGIN_LIMIT:
                raise StopResearch("LOGIN_LIMIT_REACHED")
            self.login_count += 1
        if self.request_count >= self.request_limit:
            raise RequestLimitReached("REQUEST_LIMIT_REACHED")
        if self._last_request_at is not None:
            remaining = self.interval_seconds - (self.clock() - self._last_request_at)
            if remaining > 0:
                self.sleeper(remaining)
        request_headers = {
            "Accept": "text/html,application/json,application/javascript",
            "User-Agent": USER_AGENT,
        }
        request_headers.update(headers or {})
        request = Request(
            absolute,
            data=data,
            headers=request_headers,
            method=normalized_method,
        )
        self.request_count += 1
        self._last_request_at = self.clock()
        try:
            try:
                with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                    result = ResponseData(
                        status=response.status,
                        content_type=response.headers.get("Content-Type", ""),
                        body=response.read(),
                        final_url=response.geturl(),
                    )
            except HTTPError as error:
                result = ResponseData(
                    status=error.code,
                    content_type=(
                        error.headers.get("Content-Type", "") if error.headers else ""
                    ),
                    body=error.read() if error.fp else b"",
                    final_url=error.geturl(),
                )
            validate_same_host_url(result.final_url)
            if result.status == 429:
                raise StopResearch("HTTP_429_STOP")
            if result.status in {401, 403}:
                raise StopResearch(f"HTTP_{result.status}_STOP")
            if result.status >= 500 and retry_5xx:
                self.sleeper(self.interval_seconds)
                return self.request(
                    absolute,
                    method=normalized_method,
                    data=data,
                    headers=headers,
                    is_login=is_login,
                    retry_5xx=False,
                )
            return result
        except (URLError, TimeoutError, OSError):
            raise StopResearch("NETWORK_ERROR_STOP") from None
        finally:
            request = None

    def close(self) -> None:
        if self.closed:
            return
        self.cookie_jar.clear()
        self.opener = None
        self.closed = True


def _decode_html(response: ResponseData) -> str:
    content_type = response.content_type.casefold()
    charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    try:
        return response.body.decode(charset, errors="replace")
    except LookupError:
        return response.body.decode("utf-8", errors="replace")


def login(session: ResearchSession, login_id: str, password: str) -> LoginResult:
    page = session.request(LOGIN_URL)
    if page.status != 200 or "html" not in page.content_type.casefold():
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    html = _decode_html(page)
    form = parse_login_form(html, page_url=page.final_url)
    html = ""
    fields: dict[str, str] | None = dict(form.hidden_fields)
    fields[form.login_field] = login_id
    fields[form.password_field] = password
    encoded: bytes | None = urlencode(fields).encode("utf-8")
    metadata = {
        "login_page_path": urlsplit(page.final_url).path or "/",
        "form_action_path": form.action_path,
        "method": form.method,
        "login_field": form.login_field,
        "password_field": form.password_field,
        "hidden_field_names": form.hidden_field_names,
        "csrf_field_names": form.csrf_field_names,
        "encoding": form.encoding,
    }
    try:
        authenticated = session.request(
            form.action_url,
            method="POST",
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            is_login=True,
        )
    finally:
        fields = None
        encoded = None
        form = None
    response_html = _decode_html(authenticated)
    detect_manual_interaction(response_html)
    final_path = urlsplit(authenticated.final_url).path or "/"
    has_cookie = len(session.cookie_jar) > 0
    still_login = _looks_like_login_url(authenticated.final_url) or _contains_login_form(
        response_html
    )
    marker = _is_authenticated_html(response_html)
    metadata.update(
        {
            "result_path": final_path,
            "session_cookie_present": has_cookie,
            "session_cookie_count": len(session.cookie_jar),
            "authenticated_marker_present": marker,
            "captcha_present": False,
            "mfa_present": False,
        }
    )
    if authenticated.status != 200 or still_login:
        return LoginResult("invalid_credentials", authenticated.final_url, "", metadata)
    if not marker or not has_cookie:
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    return LoginResult("success", authenticated.final_url, response_html, metadata)


def timestamp_format(value: Any) -> str | None:
    if isinstance(value, str):
        if re.fullmatch(r"\d{12}", value):
            return "YYYYMMDDHHMM"
        if re.fullmatch(r"\d{14}", value):
            return "YYYYMMDDHHMMSS"
        if re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?",
            value,
        ):
            return "ISO8601_SECONDS"
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", value):
            return "YYYY-MM-DD_HH:MM"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        absolute = abs(value)
        if 1_000_000_000_000 <= absolute < 100_000_000_000_000:
            return "UNIX_MILLISECONDS"
        if 1_000_000_000 <= absolute < 100_000_000_000:
            return "UNIX_SECONDS"
    return None


def _safe_key(key: Any) -> str | None:
    if not isinstance(key, str) or not SAFE_FIELD_PATTERN.fullmatch(key):
        return None
    normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
    if any(marker in normalized for marker in SENSITIVE_KEY_MARKERS):
        return None
    return key


def _code_metadata(payload: Any) -> tuple[bool, str | None, Any]:
    if not isinstance(payload, dict) or "code" not in payload:
        return False, None, None
    raw = payload["code"]
    code_type = type(raw).__name__
    candidate = raw
    if isinstance(raw, list) and len(raw) == 1:
        candidate = raw[0]
        code_type = f"list[{type(candidate).__name__}]"
    safe_value = candidate if isinstance(candidate, (bool, int, float)) else None
    if isinstance(candidate, str) and re.fullmatch(r"[A-Z0-9_-]{1,32}", candidate):
        safe_value = candidate
    return True, code_type, safe_value


def _value_shape(value: Any, *, depth: int = 0) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        detected = timestamp_format(value)
        return f"timestamp:{detected}" if detected else "string"
    if isinstance(value, list):
        if depth >= 2:
            return "list"
        shapes = sorted({_value_shape(item, depth=depth + 1) for item in value})
        return f"list[{','.join(shapes)}]" if shapes else "list[empty]"
    if isinstance(value, dict):
        return "object"
    return "unknown"


def _safe_format_template(value: Any) -> str | None:
    if not isinstance(value, str) or not 1 <= len(value) <= 64:
        return None
    if not re.fullmatch(r"[A-Za-z%0-9/:., _+\-]+", value):
        return None
    return value


def _collect_schema(
    payload: Any,
) -> tuple[
    list[str],
    list[str],
    int,
    list[str],
    list[str],
    dict[str, list[str]],
    dict[str, str],
    dict[str, list[str]],
]:
    nested_keys: set[str] = set()
    timestamp_formats: set[str] = set()
    units: set[str] = set()
    value_keys: set[str] = set()
    value_item_shapes: dict[str, set[str]] = {}
    date_field_shapes: dict[str, str] = {}
    format_templates: dict[str, set[str]] = {}
    record_count = 0

    def visit(value: Any, *, parent_key: str = "", depth: int = 0) -> None:
        nonlocal record_count
        if depth > 8:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                safe = _safe_key(key)
                if depth > 0 and safe:
                    nested_keys.add(safe)
                if isinstance(key, str) and key.casefold().endswith("_unit"):
                    candidates = child if isinstance(child, list) else [child]
                    for candidate in candidates:
                        if isinstance(candidate, str) and candidate.strip() in SAFE_UNITS:
                            units.add(candidate.strip())
                if isinstance(key, str) and "formatstring" in key.casefold():
                    candidates = child if isinstance(child, list) else [child]
                    safe_templates = {
                        template
                        for template in (_safe_format_template(item) for item in candidates)
                        if template is not None
                    }
                    if safe_templates:
                        format_templates[key] = safe_templates
                if isinstance(key, str) and TIMESTAMP_KEY_PATTERN.search(key):
                    date_field_shapes[key] = _value_shape(child)
                visit(child, parent_key=key if isinstance(key, str) else "", depth=depth + 1)
        elif isinstance(value, list):
            if VALUE_KEY_PATTERN.fullmatch(parent_key):
                value_keys.add(parent_key)
                record_count += len(value)
                value_item_shapes.setdefault(parent_key, set()).update(
                    _value_shape(item) for item in value
                )
                for row in value:
                    candidates = row if isinstance(row, (list, tuple)) else [row]
                    for candidate in candidates:
                        detected = timestamp_format(candidate)
                        if detected:
                            timestamp_formats.add(detected)
                return
            elif value and all(isinstance(item, dict) for item in value):
                record_count += len(value)
            for child in value:
                visit(child, parent_key=parent_key, depth=depth + 1)
        elif TIMESTAMP_KEY_PATTERN.search(parent_key):
            detected = timestamp_format(value)
            if detected:
                timestamp_formats.add(detected)

    visit(payload)
    return (
        sorted(nested_keys),
        sorted(timestamp_formats),
        record_count,
        sorted(units),
        sorted(value_keys),
        {key: sorted(value) for key, value in sorted(value_item_shapes.items())},
        dict(sorted(date_field_shapes.items())),
        {key: sorted(value) for key, value in sorted(format_templates.items())},
    )


def analyze_response(
    response: ResponseData,
    *,
    endpoint_path: str,
    parameter_names: list[str],
    metric_id: int | None = None,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "endpoint_path": endpoint_path,
        "method": "GET",
        "parameter_names": sorted(parameter_names),
        "http_status": response.status,
        "content_type": _media_type(response.content_type),
        "redirect_path": urlsplit(response.final_url).path or "/",
        "is_json": False,
        "top_level_keys": [],
        "nested_keys": [],
        "code_present": False,
        "code_type": None,
        "code_value": None,
        "data_container_present": False,
        "record_count": 0,
        "timestamp_formats": [],
        "value_item_shapes": {},
        "date_field_shapes": {},
        "format_templates": {},
        "metric_id": metric_id,
        "metric_key": KIND_NAMES.get(metric_id) if metric_id is not None else None,
        "metric_units": [],
        "parser_status": "schema_unknown",
        "authenticated_session_required": True,
    }
    if _looks_like_login_url(response.final_url):
        result["parser_status"] = "expired_session"
        return result
    if response.status in {401, 403, 429}:
        result["parser_status"] = f"http_{response.status}"
        return result
    if response.status >= 500:
        result["parser_status"] = "http_5xx"
        return result
    stripped = response.body.lstrip()
    if stripped.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")):
        html = _decode_html(response)
        detect_manual_interaction(html)
        result["parser_status"] = "login_html" if _contains_login_form(html) else "html"
        return result
    try:
        payload = json.loads(response.body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        result["parser_status"] = "malformed_json"
        return result
    result["is_json"] = True
    if isinstance(payload, dict):
        result["top_level_keys"] = sorted(
            safe for safe in (_safe_key(key) for key in payload) if safe
        )
    present, code_type, code_value = _code_metadata(payload)
    result["code_present"] = present
    result["code_type"] = code_type
    result["code_value"] = code_value
    (
        nested,
        timestamps,
        count,
        units,
        value_keys,
        value_item_shapes,
        date_field_shapes,
        format_templates,
    ) = _collect_schema(payload)
    result["nested_keys"] = nested
    result["timestamp_formats"] = timestamps
    result["record_count"] = count
    result["metric_units"] = units
    result["value_item_shapes"] = value_item_shapes
    result["date_field_shapes"] = date_field_shapes
    result["format_templates"] = format_templates
    result["data_container_present"] = bool(value_keys) or count > 0
    media_type = _media_type(response.content_type)
    if "json" not in media_type:
        result["parser_status"] = "content_type_mismatch"
    elif present and code_value == -1:
        result["parser_status"] = "code_-1"
    elif value_keys and count > 0:
        result["parser_status"] = "available"
    elif value_keys:
        result["parser_status"] = "empty"
    elif isinstance(payload, dict) and any(
        key.casefold() in {"data", "items", "records", "result", "results"}
        for key in payload
        if isinstance(key, str)
    ):
        result["parser_status"] = "available" if count else "empty"
        result["data_container_present"] = True
    elif present:
        result["parser_status"] = "code_present"
    return result


def probe_graph_kind(session: ResearchSession, kind: int) -> dict[str, Any]:
    if kind not in KINDS:
        raise StopResearch("KIND_NOT_ALLOWLISTED")
    parameters = {"day": 31, "page": 1, "kind": kind}
    response = session.request(
        f"{GRAPH_URL}?{urlencode(parameters)}",
        headers={"Accept": "application/json"},
    )
    try:
        return analyze_response(
            response,
            endpoint_path=GRAPH_PATH,
            parameter_names=list(parameters),
            metric_id=kind,
        )
    finally:
        response = None


def _safe_discovery_url(candidate: str, *, base_url: str) -> str | None:
    if not candidate or candidate.startswith(("#", "javascript:", "mailto:")):
        return None
    try:
        absolute = validate_same_host_url(candidate, base_url=base_url)
    except CrossHostRequestBlocked:
        return None
    parsed = urlsplit(absolute)
    lowered = parsed.path.casefold()
    if any(marker in lowered for marker in MUTATION_MARKERS):
        return None
    return absolute


def _page_and_script_urls(html: str, *, page_url: str) -> tuple[list[str], list[str]]:
    parser = _LinkParser()
    parser.feed(html)
    scripts: list[str] = []
    pages: list[str] = []
    for source in parser.scripts:
        safe = _safe_discovery_url(source, base_url=page_url)
        if safe and safe not in scripts:
            scripts.append(safe)
    for href in parser.links:
        safe = _safe_discovery_url(href, base_url=page_url)
        if safe and any(marker in urlsplit(safe).path.casefold() for marker in DATA_MARKERS):
            if safe not in pages:
                pages.append(safe)
    return scripts[:MAX_FIRST_PARTY_SCRIPTS], pages[:MAX_DISCOVERY_PAGES]


def _observed_get_endpoints(source: str, *, source_url: str) -> list[str]:
    candidates: list[str] = []
    patterns = (
        r"(?:fetch|ajax|getJSON)\s*\(\s*['\"]([^'\"]+)['\"]",
        r"(?:url|href)\s*[:=]\s*['\"]([^'\"]+)['\"]",
        r"['\"]((?:https://www\.healthplanet\.jp)?/[^'\"]*(?:graph|measurement|innerscan|data)[^'\"]*)['\"]",
    )
    for pattern in patterns:
        for raw in re.findall(pattern, source, flags=re.IGNORECASE):
            if "{" in raw or "}" in raw or "<" in raw or ">" in raw:
                continue
            safe = _safe_discovery_url(raw, base_url=source_url)
            if safe and safe not in candidates:
                candidates.append(safe)
    return candidates[:MAX_OBSERVED_ENDPOINTS]


def discover_first_party_endpoints(
    session: ResearchSession, *, homepage_html: str, homepage_url: str
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    scripts, pages = _page_and_script_urls(homepage_html, page_url=homepage_url)
    observed: list[str] = []
    inspected_paths: list[str] = []
    for page_url in pages:
        response = session.request(page_url)
        inspected_paths.append(urlsplit(page_url).path or "/")
        if response.status == 200 and "html" in response.content_type.casefold():
            page_html = _decode_html(response)
            page_scripts, _ = _page_and_script_urls(page_html, page_url=page_url)
            for item in page_scripts:
                if item not in scripts:
                    scripts.append(item)
            for item in _observed_get_endpoints(page_html, source_url=page_url):
                if item not in observed:
                    observed.append(item)
            page_html = ""
        response = None
    for script_url in scripts[:MAX_FIRST_PARTY_SCRIPTS]:
        response = session.request(script_url)
        inspected_paths.append(urlsplit(script_url).path or "/")
        if response.status == 200:
            source = response.body.decode("utf-8", errors="replace")
            for item in _observed_get_endpoints(source, source_url=script_url):
                if item not in observed:
                    observed.append(item)
            source = ""
        response = None
    findings: list[dict[str, Any]] = []
    for endpoint in observed[:MAX_OBSERVED_ENDPOINTS]:
        parsed = urlsplit(endpoint)
        if parsed.path == GRAPH_PATH:
            continue
        response = session.request(endpoint, headers={"Accept": "application/json"})
        findings.append(
            analyze_response(
                response,
                endpoint_path=parsed.path or "/",
                parameter_names=sorted(name for name, _ in parse_qsl(parsed.query)),
            )
        )
        response = None
    discovery = {
        "inspected_first_party_paths": sorted(set(inspected_paths)),
        "observed_get_endpoint_paths": sorted(
            {urlsplit(item).path or "/" for item in observed}
        ),
        "tested_observed_endpoint_count": len(findings),
    }
    return findings, discovery


def build_output(
    *,
    login_metadata: dict[str, Any],
    findings: list[dict[str, Any]],
    discovery: dict[str, Any],
    request_count: int,
    result: str,
) -> dict[str, Any]:
    return {
        "probe_version": "2.0.0",
        "tested_at": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "base_host": BASE_HOST,
        "result": result,
        "request_count": request_count,
        "login": login_metadata,
        "endpoints": findings,
        "discovery": discovery,
    }


def write_output(output: dict[str, Any], path: Path | None = None) -> None:
    path = path or OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(output, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    login_id: str | None = None
    password: str | None = None
    session: ResearchSession | None = None
    login_metadata: dict[str, Any] = {}
    findings: list[dict[str, Any]] = []
    discovery: dict[str, Any] = {
        "inspected_first_party_paths": [],
        "observed_get_endpoint_paths": [],
        "tested_observed_endpoint_count": 0,
    }
    result = "failed"
    exit_code = 1
    try:
        login_id, password = load_credentials()
        session = ResearchSession()
        login_result = login(session, login_id, password)
        login_id = None
        password = None
        login_metadata = login_result.metadata
        if login_result.status != "success":
            print("LOGIN: FAILED")
            result = "invalid_credentials"
            return 1
        print("LOGIN: SUCCESS")
        first = probe_graph_kind(session, KINDS[0])
        findings.append(first)
        print(f"KIND 1: {first['parser_status'].upper()}")
        if first["parser_status"] in {"available", "empty"}:
            for kind in KINDS[1:]:
                finding = probe_graph_kind(session, kind)
                findings.append(finding)
                print(f"KIND {kind}: {finding['parser_status'].upper()}")
            result = "graph_kinds_tested"
        elif first["parser_status"] == "code_-1":
            observed, discovery = discover_first_party_endpoints(
                session,
                homepage_html=login_result.page_html,
                homepage_url=login_result.page_url,
            )
            findings.extend(observed)
            result = "first_party_discovery_completed"
        else:
            result = "kind_1_schema_unknown"
        exit_code = 0
    except ManualInteractionRequired:
        result = "manual_interaction_required"
        print("MANUAL_INTERACTION_REQUIRED")
        exit_code = 2
    except ConfigurationError as error:
        result = str(error)
        print(f"CONFIGURATION: {error}")
        exit_code = 1
    except ResearchError as error:
        result = str(error)
        print(f"RESEARCH_STOPPED: {error}")
        exit_code = 1
    finally:
        login_id = None
        password = None
        request_count = session.request_count if session is not None else 0
        if session is not None:
            session.close()
        session = None
        output = build_output(
            login_metadata=login_metadata,
            findings=findings,
            discovery=discovery,
            request_count=request_count,
            result=result,
        )
        write_output(output)
        print(f"SANITIZED OUTPUT: {OUTPUT_PATH}")
        output = None
        findings = []
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
