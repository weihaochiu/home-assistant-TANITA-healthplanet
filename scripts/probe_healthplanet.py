"""Privacy-safe, user-operated probe for HealthPlanet's internal graph endpoint.

This is a research tool, not a Home Assistant integration. It intentionally stores
only a small allowlisted schema summary and never stores credentials, cookies,
raw responses, or measurement values.
"""

from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from getpass import getpass
from html.parser import HTMLParser
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit
from urllib.request import (
    HTTPCookieProcessor,
    HTTPRedirectHandler,
    Request,
    build_opener,
)

PROBE_VERSION = "1.0.0"
BASE_HOST = "www.healthplanet.jp"
LOGIN_URL = f"https://{BASE_HOST}/login.do"
GRAPH_URL = f"https://{BASE_HOST}/graph/graph.json"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "_local_only" / (
    "healthplanet_schema_probe.json"
)
KINDS = (1, 2, 3, 4, 5, 6, 7, 14, 22, 23)
REQUEST_LIMIT = 2 + len(KINDS)
TIMEOUT_SECONDS = 15
REQUEST_INTERVAL_SECONDS = 0.75
USER_AGENT = (
    "HealthPlanet-Web-Schema-Probe/1.0 "
    "(local user-operated endpoint research; no data collection)"
)

OUTPUT_TEST_KEYS = (
    "http_status",
    "content_type",
    "is_json",
    "top_level_keys",
    "code_present",
    "code_type",
    "code_value",
    "data_container_present",
    "record_count",
    "field_names",
    "timestamp_formats",
    "parser_status",
)
SAFE_FIELD_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
SAFE_MEDIA_TYPE_PATTERN = re.compile(r"^[a-z0-9!#$&^_.+-]+/[a-z0-9!#$&^_.+-]+$")
SENSITIVE_FIELD_NAMES = {
    "account",
    "accountid",
    "age",
    "authorization",
    "birthdate",
    "birthday",
    "cookie",
    "email",
    "gender",
    "height",
    "loginid",
    "mail",
    "name",
    "passwd",
    "password",
    "refreshtoken",
    "serial",
    "sex",
    "token",
    "userid",
    "username",
}
DATA_CONTAINER_NAMES = {
    "data",
    "dataset",
    "graph",
    "items",
    "list",
    "plots",
    "records",
    "result",
    "results",
    "status",
}
SAFE_REDIRECT_PATHS = {
    "/",
    "/dashboard",
    "/home",
    "/index.do",
    "/login.do",
    "/mypage",
}
LOGIN_PATH_MARKERS = ("/login", "login.do")
CHALLENGE_MARKERS = {
    "captcha": "captcha",
    "recaptcha": "recaptcha",
    "hcaptcha": "hcaptcha",
    "cf-chl": "cloudflare",
    "cloudflare challenge": "cloudflare",
    "bot verification": "bot_verification",
    "verify you are human": "bot_verification",
    "one-time password": "mfa",
    "one time password": "mfa",
    "otp": "mfa",
    "two-factor": "mfa",
    "multi-factor": "mfa",
    "ワンタイムパスワード": "mfa",
    "二段階認証": "mfa",
    "security warning": "security_warning",
    "セキュリティ警告": "security_warning",
}


class SafeProbeError(Exception):
    """An error whose fixed message is safe to show to the user."""


class ManualInteractionRequired(SafeProbeError):
    """The normal login flow cannot safely continue automatically."""


class CrossHostRedirectError(SafeProbeError):
    """A request attempted to leave the allowlisted host."""


class RequestLimitError(SafeProbeError):
    """The hard request limit was reached."""


@dataclass(frozen=True)
class ParsedLoginForm:
    action_url: str
    login_field: str
    password_field: str
    hidden_fields: dict[str, str]


@dataclass
class _FormCandidate:
    action: str
    method: str
    hidden_fields: dict[str, str] = field(default_factory=dict)
    login_field: str | None = None
    password_field: str | None = None
    consent_control: bool = False


class _LoginFormParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[_FormCandidate] = []
        self._current: _FormCandidate | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {name.lower(): value or "" for name, value in attrs}
        if tag.lower() == "form":
            self._current = _FormCandidate(
                action=attributes.get("action", ""),
                method=attributes.get("method", "get").lower(),
            )
            return
        if tag.lower() != "input" or self._current is None:
            return
        input_type = attributes.get("type", "text").lower()
        name = attributes.get("name", "")
        normalized_name = re.sub(r"[^a-z0-9]", "", name.lower())
        if input_type == "hidden" and name:
            self._current.hidden_fields[name] = attributes.get("value", "")
        elif input_type in {"text", "email"} and normalized_name in {
            "loginid",
            "userid",
            "username",
        }:
            self._current.login_field = name
        elif input_type == "password" and name:
            self._current.password_field = name
        if "consent" in normalized_name or "agree" in normalized_name:
            self._current.consent_control = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "form" and self._current is not None:
            self.forms.append(self._current)
            self._current = None


def _validated_same_host_url(url: str, *, base_url: str = LOGIN_URL) -> str:
    absolute = urljoin(base_url, url)
    parsed = urlsplit(absolute)
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname != BASE_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in {None, 443}
    ):
        raise CrossHostRedirectError("CROSS_HOST_REQUEST_BLOCKED")
    return absolute


def parse_login_form(html: str, *, page_url: str = LOGIN_URL) -> ParsedLoginForm:
    detect_manual_interaction(html)
    parser = _LoginFormParser()
    try:
        parser.feed(html)
    except Exception as error:
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED") from None
    matches = [
        form
        for form in parser.forms
        if form.method == "post" and form.login_field and form.password_field
    ]
    if len(matches) != 1 or matches[0].consent_control:
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    selected = matches[0]
    action_url = _validated_same_host_url(selected.action or page_url, base_url=page_url)
    return ParsedLoginForm(
        action_url=action_url,
        login_field=selected.login_field or "",
        password_field=selected.password_field or "",
        hidden_fields=dict(selected.hidden_fields),
    )


def detect_manual_interaction(html: str) -> None:
    lowered = html.casefold()
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")


def _looks_like_login_path(url: str) -> bool:
    path = urlsplit(url).path.casefold()
    return any(marker in path for marker in LOGIN_PATH_MARKERS)


def _contains_login_form(html: str) -> bool:
    parser = _LoginFormParser()
    try:
        parser.feed(html)
    except Exception:
        return True
    return any(form.password_field for form in parser.forms)


def _confirmed_authenticated_page(html: str) -> bool:
    lowered = html.casefold()
    return any(marker in lowered for marker in ("logout", "ログアウト"))


class SameHostRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, request, file_pointer, code, message, headers, new_url):
        _validated_same_host_url(new_url, base_url=request.full_url)
        return super().redirect_request(
            request, file_pointer, code, message, headers, new_url
        )


class ProbeSession:
    def __init__(self) -> None:
        self.cookie_jar = CookieJar()
        self.opener = build_opener(
            SameHostRedirectHandler(), HTTPCookieProcessor(self.cookie_jar)
        )
        self.request_count = 0

    def request(
        self,
        url: str,
        *,
        data: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, str, bytes, str]:
        _validated_same_host_url(url)
        if self.request_count >= REQUEST_LIMIT:
            raise RequestLimitError("REQUEST_LIMIT_REACHED")
        self.request_count += 1
        request_headers = {"User-Agent": USER_AGENT, "Accept": "text/html,application/json"}
        request_headers.update(headers or {})
        request = Request(url, data=data, headers=request_headers)
        try:
            with self.opener.open(request, timeout=TIMEOUT_SECONDS) as response:
                final_url = response.geturl()
                _validated_same_host_url(final_url)
                content_type = response.headers.get("Content-Type", "")
                return response.status, content_type, response.read(), final_url
        except HTTPError as error:
            final_url = error.geturl()
            _validated_same_host_url(final_url)
            content_type = error.headers.get("Content-Type", "") if error.headers else ""
            body = error.read() if error.fp else b""
            return error.code, content_type, body, final_url
        except (URLError, TimeoutError, OSError):
            raise SafeProbeError("NETWORK_ERROR") from None
        finally:
            request = None

    def close(self) -> None:
        self.cookie_jar.clear()
        self.opener = None


def login(
    session: ProbeSession, login_id: str, password: str
) -> tuple[str, str]:
    status, content_type, body, page_url = session.request(LOGIN_URL)
    if status != 200 or "html" not in content_type.casefold():
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    html = body.decode("utf-8", errors="replace")
    detect_manual_interaction(html)
    form = parse_login_form(html, page_url=page_url)
    body = b""
    html = ""

    form_fields: dict[str, str] | None = dict(form.hidden_fields)
    form_fields[form.login_field] = login_id
    form_fields[form.password_field] = password
    encoded: bytes | None = urlencode(form_fields).encode("utf-8")
    try:
        status, content_type, response_body, final_url = session.request(
            form.action_url,
            data=encoded,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
    finally:
        form_fields = None
        encoded = None
        form = None

    response_html = response_body.decode("utf-8", errors="replace")
    response_body = b""
    detect_manual_interaction(response_html)
    redirect_path = urlsplit(final_url).path or "/"
    if status in {401, 403} or _looks_like_login_path(final_url) or _contains_login_form(
        response_html
    ):
        return "failed", redirect_path
    if status != 200 or "html" not in content_type.casefold():
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    if not _confirmed_authenticated_page(response_html):
        raise ManualInteractionRequired("MANUAL_INTERACTION_REQUIRED")
    return "success", redirect_path


def _safe_field_name(value: Any) -> str | None:
    if not isinstance(value, str) or not SAFE_FIELD_PATTERN.fullmatch(value):
        return None
    normalized = re.sub(r"[^a-z0-9]", "", value.casefold())
    if normalized in SENSITIVE_FIELD_NAMES:
        return None
    return value


def _safe_key_list(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    return sorted(
        key for key in (_safe_field_name(item) for item in value) if key is not None
    )


def _code_summary(payload: Any) -> tuple[bool, str | None, Any]:
    if not isinstance(payload, dict) or "code" not in payload:
        return False, None, None
    code = payload["code"]
    code_type = type(code).__name__
    candidate = code
    if isinstance(code, list) and len(code) == 1:
        candidate = code[0]
        code_type = f"list[{type(candidate).__name__}]"
    if candidate is None or isinstance(candidate, (bool, int, float)):
        return True, code_type, candidate
    if isinstance(candidate, str) and re.fullmatch(r"[A-Z0-9_-]{1,32}", candidate):
        return True, code_type, candidate
    return True, code_type, None


def _timestamp_format(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    if re.fullmatch(r"\d{12}", value):
        return "YYYYMMDDHHMM"
    if re.fullmatch(r"\d{14}", value):
        return "YYYYMMDDHHMMSS"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:?\d{2})?", value):
        return "ISO8601_SECONDS"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", value):
        return "YYYY-MM-DD_HH:MM"
    return None


def _schema_details(payload: Any) -> tuple[bool, int, list[str], list[str]]:
    container_present = False
    record_count = 0
    field_names: set[str] = set()
    timestamp_formats: set[str] = set()

    def visit(value: Any, *, parent_key: str = "", depth: int = 0) -> None:
        nonlocal container_present, record_count
        if depth > 8:
            return
        if isinstance(value, dict):
            for key, child in value.items():
                safe_key = _safe_field_name(key)
                if safe_key is not None and depth > 0:
                    field_names.add(safe_key)
                if isinstance(key, str) and any(
                    marker in key.casefold() for marker in ("date", "time", "timestamp")
                ):
                    detected = _timestamp_format(child)
                    if detected:
                        timestamp_formats.add(detected)
                visit(child, parent_key=key if isinstance(key, str) else "", depth=depth + 1)
        elif isinstance(value, list):
            normalized_parent = parent_key.casefold()
            record_like = [item for item in value if isinstance(item, dict)]
            if normalized_parent in DATA_CONTAINER_NAMES or record_like:
                container_present = True
                record_count += len(record_like) if record_like else len(value)
            for child in value:
                visit(child, parent_key=parent_key, depth=depth + 1)
        else:
            detected = _timestamp_format(value)
            if detected and any(
                marker in parent_key.casefold()
                for marker in ("date", "time", "timestamp")
            ):
                timestamp_formats.add(detected)

    visit(payload)
    return (
        container_present,
        record_count,
        sorted(field_names),
        sorted(timestamp_formats),
    )


def _empty_test_result(status: int, content_type: str) -> dict[str, Any]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if not SAFE_MEDIA_TYPE_PATTERN.fullmatch(media_type):
        media_type = "unknown"
    return {
        "http_status": status,
        "content_type": media_type,
        "is_json": False,
        "top_level_keys": [],
        "code_present": False,
        "code_type": None,
        "code_value": None,
        "data_container_present": False,
        "record_count": 0,
        "field_names": [],
        "timestamp_formats": [],
        "parser_status": "schema_unknown",
    }


def analyze_graph_response(
    *,
    status: int,
    content_type: str,
    body: bytes,
    final_url: str = GRAPH_URL,
) -> dict[str, Any]:
    result = _empty_test_result(status, content_type)
    if _looks_like_login_path(final_url):
        result["parser_status"] = "redirect_to_login"
        return result
    if status == 429:
        result["parser_status"] = "http_429"
        return result
    if status in {401, 403}:
        result["parser_status"] = f"http_{status}"
        return result
    if status >= 500:
        result["parser_status"] = "http_5xx"
        return result

    stripped = body.lstrip()
    if stripped.startswith((b"<!DOCTYPE", b"<!doctype", b"<html", b"<HTML")):
        html = body.decode("utf-8", errors="replace")
        try:
            detect_manual_interaction(html)
        finally:
            html = ""
        result["parser_status"] = "login_html" if _contains_login_form(
            body.decode("utf-8", errors="replace")
        ) else "schema_unknown"
        return result

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        result["parser_status"] = "malformed_json"
        return result
    result["is_json"] = True
    result["top_level_keys"] = _safe_key_list(payload)
    code_present, code_type, code_value = _code_summary(payload)
    result["code_present"] = code_present
    result["code_type"] = code_type
    result["code_value"] = code_value
    present, count, fields, timestamps = _schema_details(payload)
    result["data_container_present"] = present
    result["record_count"] = count
    result["field_names"] = fields
    result["timestamp_formats"] = timestamps

    media_type = content_type.split(";", 1)[0].strip().casefold()
    if "json" not in media_type:
        result["parser_status"] = "content_type_mismatch"
    elif payload is None:
        result["parser_status"] = "null"
    elif code_present and code_value == -1:
        result["parser_status"] = "code_-1"
    elif code_present:
        result["parser_status"] = "code_present"
    elif present and count > 0:
        result["parser_status"] = "available"
    elif present and count == 0:
        result["parser_status"] = "empty"
    else:
        result["parser_status"] = "schema_unknown"
    return {key: result[key] for key in OUTPUT_TEST_KEYS}


def _normal_kind_one_result(result: dict[str, Any]) -> bool:
    return result["is_json"] and result["parser_status"] in {"available", "empty"}


def probe_kind(session: ProbeSession, kind: int) -> dict[str, Any]:
    query = urlencode({"day": 31, "page": 1, "kind": kind})
    url = f"{GRAPH_URL}?{query}"
    status, content_type, body, final_url = session.request(
        url, headers={"Accept": "application/json"}
    )
    try:
        return analyze_graph_response(
            status=status,
            content_type=content_type,
            body=body,
            final_url=final_url,
        )
    finally:
        body = b""


def build_output(
    *, login_result: str, login_redirect_path: str, tests: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    parsed_path = urlsplit(login_redirect_path).path or "/"
    safe_path = parsed_path if parsed_path in SAFE_REDIRECT_PATHS else "/<redacted>"
    safe_tests = {
        str(kind): {key: result.get(key) for key in OUTPUT_TEST_KEYS}
        for kind, result in tests.items()
        if str(kind) in {str(item) for item in KINDS}
    }
    return {
        "probe_version": PROBE_VERSION,
        "tested_at_utc": datetime.now(UTC).isoformat(timespec="seconds").replace(
            "+00:00", "Z"
        ),
        "base_host": BASE_HOST,
        "login_result": login_result,
        "login_redirect_path": safe_path,
        "tests": safe_tests,
    }


def write_output(output: dict[str, Any], path: Path | None = None) -> None:
    path = path or OUTPUT_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(output, indent=2, ensure_ascii=True, sort_keys=True)
    path.write_text(serialized + "\n", encoding="utf-8")


def _terminal_status(result: dict[str, Any]) -> str:
    status = result["parser_status"]
    if status == "available":
        return "AVAILABLE"
    if status == "empty":
        return "EMPTY"
    if status == "code_-1":
        return "CODE_-1"
    return "SCHEMA_UNKNOWN"


def main() -> int:
    login_id: str | None = None
    password: str | None = None
    session: ProbeSession | None = None
    tests: dict[str, dict[str, Any]] = {}
    login_result = "failed"
    redirect_path = "/login.do"
    exit_code = 1
    try:
        login_id = input("HealthPlanet login ID: ")
        password = getpass("HealthPlanet password: ")
        session = ProbeSession()
        login_result, redirect_path = login(session, login_id, password)
        password = None
        login_id = None
        if login_result != "success":
            print("LOGIN: FAILED")
            return 1
        print("LOGIN: SUCCESS")

        first_result = probe_kind(session, KINDS[0])
        tests[str(KINDS[0])] = first_result
        print(f"KIND {KINDS[0]}: {_terminal_status(first_result)}")
        if _normal_kind_one_result(first_result):
            for kind in KINDS[1:]:
                time.sleep(REQUEST_INTERVAL_SECONDS)
                result = probe_kind(session, kind)
                tests[str(kind)] = result
                print(f"KIND {kind}: {_terminal_status(result)}")
        exit_code = 0
    except ManualInteractionRequired:
        login_result = "manual_interaction_required"
        print("LOGIN: MANUAL_INTERACTION_REQUIRED")
        exit_code = 2
    except (CrossHostRedirectError, RequestLimitError, SafeProbeError):
        login_result = "failed"
        print("LOGIN: FAILED")
        exit_code = 1
    finally:
        password = None
        login_id = None
        if session is not None:
            session.close()
        session = None
        output = build_output(
            login_result=login_result,
            login_redirect_path=redirect_path,
            tests=tests,
        )
        write_output(output)
        print(f"SANITIZED OUTPUT: {OUTPUT_PATH}")
        output = None
        tests = {}
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
