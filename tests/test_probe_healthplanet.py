from __future__ import annotations

import json
import zipfile
from http.cookiejar import Cookie
from pathlib import Path

import pytest

from scripts import create_backup
from scripts import probe_healthplanet as probe

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC_PASSWORD = "synthetic-password-do-not-use"
SYNTHETIC_LOGIN_ID = "synthetic-user@example.invalid"
SYNTHETIC_MEASUREMENT = "42.42"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_parse_login_form_relative_action_and_hidden_csrf():
    parsed = probe.parse_login_form(
        (FIXTURES / "login_relative.html").read_text(encoding="utf-8")
    )
    assert parsed.login_field == "loginId"
    assert parsed.password_field == "passwd"
    assert parsed.hidden_fields == {"csrf_synthetic": "fixture-csrf-value"}
    assert parsed.action_url == "https://www.healthplanet.jp/sessions/sign_in"


def test_parse_login_form_accepts_absolute_same_host_action():
    html = """
    <form method="POST" action="https://www.healthplanet.jp/session">
      <input name="loginId" type="text">
      <input name="passwd" type="password">
    </form>
    """
    parsed = probe.parse_login_form(html)
    assert parsed.action_url == "https://www.healthplanet.jp/session"


@pytest.mark.parametrize(
    "action",
    [
        "https://example.invalid/login",
        "http://www.healthplanet.jp/login.do",
        "https://www.healthplanet.jp.example.invalid/login",
        "https://user@www.healthplanet.jp/login",
    ],
)
def test_parse_login_form_rejects_unsafe_action(action):
    html = f"""
    <form method="post" action="{action}">
      <input name="loginId" type="text">
      <input name="passwd" type="password">
    </form>
    """
    with pytest.raises(probe.CrossHostRedirectError):
        probe.parse_login_form(html)


@pytest.mark.parametrize(
    "marker", ["reCAPTCHA", "hCaptcha", "Cloudflare challenge", "bot verification"]
)
def test_captcha_and_bot_challenge_detection(marker):
    with pytest.raises(probe.ManualInteractionRequired) as error:
        probe.detect_manual_interaction(f"<html>{marker}</html>")
    assert str(error.value) == "MANUAL_INTERACTION_REQUIRED"


@pytest.mark.parametrize("marker", ["OTP", "two-factor", "ワンタイムパスワード"])
def test_mfa_detection(marker):
    with pytest.raises(probe.ManualInteractionRequired):
        probe.detect_manual_interaction(f"<html>{marker}</html>")


def test_unknown_consent_control_stops_login_parser():
    html = """
    <form method="post" action="/login.do">
      <input name="loginId" type="text">
      <input name="passwd" type="password">
      <input name="consent" type="checkbox">
    </form>
    """
    with pytest.raises(probe.ManualInteractionRequired):
        probe.parse_login_form(html)


def test_cross_domain_redirect_is_rejected():
    handler = probe.SameHostRedirectHandler()
    request = probe.Request(probe.LOGIN_URL)
    with pytest.raises(probe.CrossHostRedirectError):
        handler.redirect_request(
            request, None, 302, "Found", {}, "https://example.invalid/login"
        )


def test_login_requires_logout_evidence_even_after_http_200():
    login_html = (FIXTURES / "login_relative.html").read_text(encoding="utf-8")

    class Session:
        def __init__(self):
            self.calls = 0

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return 200, "text/html", login_html.encode(), probe.LOGIN_URL
            return 200, "text/html", b"<html>Welcome</html>", "https://www.healthplanet.jp/home"

    with pytest.raises(probe.ManualInteractionRequired):
        probe.login(Session(), SYNTHETIC_LOGIN_ID, SYNTHETIC_PASSWORD)


def test_login_success_requires_non_login_path_and_logout_marker():
    login_html = (FIXTURES / "login_relative.html").read_text(encoding="utf-8")

    class Session:
        def __init__(self):
            self.calls = 0

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return 200, "text/html", login_html.encode(), probe.LOGIN_URL
            return (
                200,
                "text/html",
                "<html>ログアウト</html>".encode(),
                "https://www.healthplanet.jp/home",
            )

    assert probe.login(Session(), SYNTHETIC_LOGIN_ID, SYNTHETIC_PASSWORD) == (
        "success",
        "/home",
    )


@pytest.mark.parametrize("kind", probe.KINDS)
def test_all_known_kinds_are_allowlisted_in_output(kind):
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=fixture_bytes("graph_empty.json"),
    )
    output = probe.build_output(
        login_result="success", login_redirect_path="/home", tests={str(kind): result}
    )
    assert str(kind) in output["tests"]


def test_unknown_kind_is_dropped_from_output():
    result = probe.analyze_graph_response(
        status=200, content_type="application/json", body=b'{"data":[]}'
    )
    output = probe.build_output(
        login_result="success", login_redirect_path="/home", tests={"999": result}
    )
    assert output["tests"] == {}


def test_normal_json_schema_contains_no_measurement_values():
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json; charset=utf-8",
        body=fixture_bytes("graph_records.json"),
    )
    serialized = json.dumps(result)
    assert result["parser_status"] == "available"
    assert result["record_count"] == 2
    assert result["field_names"] == ["date", "kind", "value"]
    assert result["timestamp_formats"] == ["YYYYMMDDHHMM", "YYYYMMDDHHMMSS"]
    assert SYNTHETIC_MEASUREMENT not in serialized
    assert "20260102030405" not in serialized


def test_code_minus_one_is_recorded_but_not_interpreted_as_empty():
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=fixture_bytes("graph_code_minus_one.json"),
    )
    assert result["code_present"] is True
    assert result["code_type"] == "list[int]"
    assert result["code_value"] == -1
    assert result["parser_status"] == "code_-1"


@pytest.mark.parametrize(
    ("payload", "expected_type", "expected_value"),
    [
        ({"code": "SAFE_ERROR"}, "str", "SAFE_ERROR"),
        ({"code": {"unexpected": "shape"}}, "dict", None),
        ({"code": [1, 2]}, "list", None),
    ],
)
def test_other_code_types_are_safely_summarized(payload, expected_type, expected_value):
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )
    assert result["code_type"] == expected_type
    assert result["code_value"] == expected_value
    assert result["parser_status"] == "code_present"


def test_empty_data_is_recognized():
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=fixture_bytes("graph_empty.json"),
    )
    assert result["data_container_present"] is True
    assert result["record_count"] == 0
    assert result["parser_status"] == "empty"


@pytest.mark.parametrize("body", [b"not-json", b"", b"{"])
def test_malformed_json(body):
    result = probe.analyze_graph_response(
        status=200, content_type="application/json", body=body
    )
    assert result["is_json"] is False
    assert result["parser_status"] == "malformed_json"


def test_html_login_page_is_recognized_without_storing_html():
    body = fixture_bytes("login_page_response.html")
    result = probe.analyze_graph_response(
        status=200, content_type="text/html", body=body
    )
    assert result["parser_status"] == "login_html"
    assert "loginId" not in json.dumps(result)


def test_redirect_to_login_is_recognized_and_query_not_output():
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=b"{}",
        final_url="https://www.healthplanet.jp/login.do?account=secret",
    )
    output = probe.build_output(
        login_result="failed",
        login_redirect_path="/login.do?account=secret",
        tests={"1": result},
    )
    assert result["parser_status"] == "redirect_to_login"
    assert output["login_redirect_path"] == "/login.do"
    assert "secret" not in json.dumps(output)


def test_wrong_content_type_is_reported_without_raw_body():
    result = probe.analyze_graph_response(
        status=200, content_type="text/plain", body=b'{"data":[]}'
    )
    assert result["is_json"] is True
    assert result["parser_status"] == "content_type_mismatch"


def test_untrusted_content_type_is_not_persisted():
    result = probe.analyze_graph_response(
        status=200,
        content_type="person@example.invalid/secret",
        body=b'{"data":[]}',
    )
    assert result["content_type"] == "unknown"
    assert "example.invalid" not in json.dumps(result)


@pytest.mark.parametrize(
    ("status", "expected"),
    [(429, "http_429"), (401, "http_401"), (403, "http_403"), (500, "http_5xx")],
)
def test_http_error_statuses(status, expected):
    result = probe.analyze_graph_response(
        status=status, content_type="application/json", body=b'{"ignored":true}'
    )
    assert result["parser_status"] == expected


@pytest.mark.parametrize(
    ("payload", "expected_status"),
    [
        (None, "null"),
        ("-", "schema_unknown"),
        ("", "schema_unknown"),
        ({"newShape": {"unexpected": 123}}, "schema_unknown"),
    ],
)
def test_null_empty_dash_and_schema_drift(payload, expected_status):
    result = probe.analyze_graph_response(
        status=200,
        content_type="application/json",
        body=json.dumps(payload).encode(),
    )
    assert result["parser_status"] == expected_status


def test_sensitive_and_non_ascii_field_names_are_dropped():
    body = json.dumps(
        {
            "data": [
                {
                    "value": 999.123,
                    "name": "Synthetic Person",
                    "account_id": "synthetic-account",
                    "個人名": "人工資料",
                }
            ]
        }
    ).encode()
    result = probe.analyze_graph_response(
        status=200, content_type="application/json", body=body
    )
    serialized = json.dumps(result)
    assert result["field_names"] == ["value"]
    assert "Synthetic Person" not in serialized
    assert "synthetic-account" not in serialized
    assert "999.123" not in serialized


def test_output_has_exact_allowlist_schema_and_no_secrets():
    body = json.dumps(
        {
            "data": [
                {
                    "date": "20260102030405",
                    "value": 77.777,
                    "account_id": SYNTHETIC_LOGIN_ID,
                    "cookie": "synthetic-cookie",
                    "raw_response": "synthetic-raw-response",
                }
            ]
        }
    ).encode()
    result = probe.analyze_graph_response(
        status=200, content_type="application/json", body=body
    )
    output = probe.build_output(
        login_result="success", login_redirect_path="/home?token=synthetic", tests={"1": result}
    )
    assert set(output) == {
        "probe_version",
        "tested_at_utc",
        "base_host",
        "login_result",
        "login_redirect_path",
        "tests",
    }
    assert set(output["tests"]["1"]) == set(probe.OUTPUT_TEST_KEYS)
    serialized = json.dumps(output)
    for forbidden in (
        SYNTHETIC_PASSWORD,
        SYNTHETIC_LOGIN_ID,
        "synthetic-cookie",
        "synthetic-raw-response",
        "77.777",
        "synthetic",
    ):
        assert forbidden not in serialized


def test_unknown_redirect_path_is_redacted():
    output = probe.build_output(
        login_result="success",
        login_redirect_path="/users/synthetic-account/dashboard?token=ignored",
        tests={},
    )
    assert output["login_redirect_path"] == "/<redacted>"
    assert "synthetic-account" not in json.dumps(output)


def test_main_does_not_print_or_persist_credentials(monkeypatch, tmp_path, capsys):
    class FakeSession:
        def close(self):
            return None

    monkeypatch.setattr("builtins.input", lambda _prompt: SYNTHETIC_LOGIN_ID)
    monkeypatch.setattr(probe, "getpass", lambda _prompt: SYNTHETIC_PASSWORD)
    monkeypatch.setattr(probe, "ProbeSession", FakeSession)
    monkeypatch.setattr(probe, "login", lambda *_args: ("success", "/home"))
    monkeypatch.setattr(
        probe,
        "probe_kind",
        lambda *_args: probe.analyze_graph_response(
            status=200, content_type="application/json", body=b'{"data":[]}'
        ),
    )
    monkeypatch.setattr(probe.time, "sleep", lambda _seconds: None)
    output_path = tmp_path / "_local_only" / "healthplanet_schema_probe.json"
    monkeypatch.setattr(probe, "OUTPUT_PATH", output_path)

    assert probe.main() == 0
    captured = capsys.readouterr()
    persisted = output_path.read_text(encoding="utf-8")
    combined = captured.out + captured.err + persisted
    assert SYNTHETIC_PASSWORD not in combined
    assert SYNTHETIC_LOGIN_ID not in combined
    assert "cookie" not in persisted.casefold()


def test_safe_exception_never_contains_password():
    with pytest.raises(probe.SafeProbeError) as error:
        raise probe.SafeProbeError("NETWORK_ERROR")
    assert SYNTHETIC_PASSWORD not in repr(error.value)


def test_timeout_is_safely_classified_and_not_retried():
    class TimeoutOpener:
        def __init__(self):
            self.calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError

    session = probe.ProbeSession()
    opener = TimeoutOpener()
    session.opener = opener
    with pytest.raises(probe.SafeProbeError) as error:
        session.request(probe.LOGIN_URL)
    assert str(error.value) == "NETWORK_ERROR"
    assert opener.calls == 1


def test_request_count_hard_upper_bound_without_network():
    class Response:
        status = 200
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def geturl(self):
            return probe.GRAPH_URL

        def read(self):
            return b"{}"

    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            return Response()

    session = probe.ProbeSession()
    opener = Opener()
    session.opener = opener
    for _ in range(probe.REQUEST_LIMIT):
        session.request(probe.GRAPH_URL)
    with pytest.raises(probe.RequestLimitError):
        session.request(probe.GRAPH_URL)
    assert opener.calls == probe.REQUEST_LIMIT


def test_session_close_clears_in_memory_cookie_jar():
    session = probe.ProbeSession()
    session.cookie_jar.set_cookie(
        Cookie(
            version=0,
            name="synthetic-session",
            value="synthetic-cookie-value",
            port=None,
            port_specified=False,
            domain="www.healthplanet.jp",
            domain_specified=True,
            domain_initial_dot=False,
            path="/",
            path_specified=True,
            secure=True,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )
    )
    assert len(session.cookie_jar) == 1
    session.close()
    assert len(session.cookie_jar) == 0
    assert session.opener is None


def test_local_only_is_gitignored_and_backup_excluded():
    root = Path(__file__).resolve().parents[1]
    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert "_local_only/" in gitignore.splitlines()
    assert create_backup.is_excluded(Path("_local_only/probe.json"))


def test_backup_zip_integrity_exclusions_and_retention(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("synthetic repository", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "secret").write_text("excluded", encoding="utf-8")
    (tmp_path / "_local_only").mkdir()
    (tmp_path / "_local_only" / "probe.json").write_text("excluded", encoding="utf-8")
    (tmp_path / ".env.synthetic").write_text("excluded", encoding="utf-8")
    (tmp_path / "session.json").write_text("excluded", encoding="utf-8")
    (tmp_path / "tokens").mkdir()
    (tmp_path / "tokens" / "auth.json").write_text("excluded", encoding="utf-8")
    monkeypatch.setattr(create_backup, "head_short_sha", lambda _root: "abc1234")

    for _ in range(create_backup.KEEP_BACKUPS + 2):
        archive_path = create_backup.create_backup(tmp_path)
        assert zipfile.is_zipfile(archive_path)

    archives = list((tmp_path / "BACKUP").glob("*.zip"))
    assert len(archives) == create_backup.KEEP_BACKUPS
    with zipfile.ZipFile(archives[0]) as archive:
        names = archive.namelist()
    assert "README.md" in names
    assert not any(name.startswith(".git/") for name in names)
    assert not any(name.startswith("BACKUP/") for name in names)
    assert not any(name.startswith("_local_only/") for name in names)
    assert ".env.synthetic" not in names
    assert "session.json" not in names
    assert not any(name.startswith("tokens/") for name in names)
