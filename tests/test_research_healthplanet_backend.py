from __future__ import annotations

import json
import subprocess
import zipfile
from http.cookiejar import Cookie
from pathlib import Path

import pytest

from scripts import create_backup
from scripts import research_healthplanet_backend as research

FIXTURES = Path(__file__).parent / "fixtures"
SYNTHETIC_LOGIN = "synthetic-user@example.invalid"
SYNTHETIC_PASSWORD = "synthetic-password-never-use"
SYNTHETIC_COOKIE = "synthetic-cookie-value"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def response(
    body: bytes,
    *,
    status: int = 200,
    content_type: str = "application/json",
    final_url: str = research.GRAPH_URL,
) -> research.ResponseData:
    return research.ResponseData(status, content_type, body, final_url)


def test_env_parser_reads_only_required_fields(tmp_path):
    path = tmp_path / ".env.local"
    path.write_text(
        "IGNORED=not-returned\n"
        f"HEALTHPLANET_LOGIN_ID={SYNTHETIC_LOGIN}\n"
        f'HEALTHPLANET_PASSWORD="{SYNTHETIC_PASSWORD}"\n',
        encoding="utf-8",
    )
    assert research.load_credentials(path) == (SYNTHETIC_LOGIN, SYNTHETIC_PASSWORD)


@pytest.mark.parametrize("content", ["", "HEALTHPLANET_LOGIN_ID=x\n"])
def test_env_parser_stops_when_fields_are_missing(tmp_path, content):
    path = tmp_path / ".env.local"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(research.ConfigurationError) as error:
        research.load_credentials(path)
    assert str(error.value) == "CREDENTIAL_FIELDS_MISSING"


def test_env_parser_stops_when_file_is_missing(tmp_path):
    with pytest.raises(research.ConfigurationError) as error:
        research.load_credentials(tmp_path / "absent")
    assert str(error.value) == "CREDENTIAL_FILE_MISSING"


def test_parse_login_form_fields_hidden_csrf_and_relative_action():
    parsed = research.parse_login_form(
        (FIXTURES / "login_relative.html").read_text(encoding="utf-8")
    )
    assert parsed.action_url == "https://www.healthplanet.jp/sessions/sign_in"
    assert parsed.action_path == "/sessions/sign_in"
    assert parsed.method == "POST"
    assert parsed.login_field == "loginId"
    assert parsed.password_field == "passwd"
    assert parsed.hidden_field_names == ["csrf_synthetic"]
    assert parsed.csrf_field_names == ["csrf_synthetic"]
    assert parsed.encoding == "UTF-8"


@pytest.mark.parametrize(
    "action",
    [
        "https://example.invalid/login",
        "http://www.healthplanet.jp/login.do",
        "https://www.healthplanet.jp.example.invalid/login",
        "https://user@www.healthplanet.jp/login",
    ],
)
def test_login_form_rejects_cross_host_and_unsafe_urls(action):
    html = f"""
    <form method="post" action="{action}">
      <input type="text" name="loginId">
      <input type="password" name="passwd">
    </form>
    """
    with pytest.raises(research.CrossHostRequestBlocked):
        research.parse_login_form(html)


@pytest.mark.parametrize(
    "marker",
    ["CAPTCHA", "reCAPTCHA", "hCaptcha", "Cloudflare challenge", "OTP", "two-factor"],
)
def test_challenge_and_mfa_require_manual_interaction(marker):
    with pytest.raises(research.ManualInteractionRequired) as error:
        research.detect_manual_interaction(f"<html>{marker}</html>")
    assert str(error.value) == "MANUAL_INTERACTION_REQUIRED"


def test_unknown_consent_control_stops():
    html = """
    <form method="post" action="/login.do">
      <input type="text" name="loginId">
      <input type="password" name="passwd">
      <input type="checkbox" name="consent">
    </form>
    """
    with pytest.raises(research.ManualInteractionRequired):
        research.parse_login_form(html)


def test_synthetic_login_success_requires_cookie_and_logout_marker():
    login_html = fixture_bytes("login_relative.html")

    class Session:
        def __init__(self):
            self.calls = 0
            self.cookie_jar = [object()]

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return response(
                    login_html,
                    content_type="text/html; charset=UTF-8",
                    final_url=research.LOGIN_URL,
                )
            return response(
                "<html>ログアウト</html>".encode(),
                content_type="text/html; charset=UTF-8",
                final_url="https://www.healthplanet.jp/index.do",
            )

    result = research.login(Session(), SYNTHETIC_LOGIN, SYNTHETIC_PASSWORD)
    assert result.status == "success"
    assert result.metadata["result_path"] == "/index.do"
    assert result.metadata["session_cookie_present"] is True


def test_synthetic_login_rejects_redirect_back_to_login():
    login_html = fixture_bytes("login_relative.html")

    class Session:
        def __init__(self):
            self.calls = 0
            self.cookie_jar = [object()]

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return response(
                    login_html,
                    content_type="text/html",
                    final_url=research.LOGIN_URL,
                )
            return response(
                fixture_bytes("login_page.html"),
                content_type="text/html",
                final_url=research.LOGIN_URL,
            )

    result = research.login(Session(), SYNTHETIC_LOGIN, SYNTHETIC_PASSWORD)
    assert result.status == "invalid_credentials"


def test_synthetic_login_without_authenticated_marker_stops():
    login_html = fixture_bytes("login_relative.html")

    class Session:
        def __init__(self):
            self.calls = 0
            self.cookie_jar = [object()]

        def request(self, *_args, **_kwargs):
            self.calls += 1
            if self.calls == 1:
                return response(login_html, content_type="text/html", final_url=research.LOGIN_URL)
            return response(
                b"<html>Welcome</html>",
                content_type="text/html",
                final_url="https://www.healthplanet.jp/index.do",
            )

    with pytest.raises(research.ManualInteractionRequired):
        research.login(Session(), SYNTHETIC_LOGIN, SYNTHETIC_PASSWORD)


def test_actual_observed_graph_shape_is_available_without_values():
    finding = research.analyze_response(
        response(fixture_bytes("graph_actual_schema_synthetic.json")),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=["day", "page", "kind"],
        metric_id=1,
    )
    serialized = json.dumps(finding)
    assert finding["parser_status"] == "available"
    assert finding["code_value"] == 0
    assert finding["record_count"] == 2
    assert finding["metric_id"] == 1
    assert finding["metric_key"] == "weight"
    assert finding["metric_units"] == ["kg"]
    assert finding["timestamp_formats"] == ["UNIX_MILLISECONDS"]
    assert "70.0" not in serialized
    assert "71.0" not in serialized
    assert "1700000000000" not in serialized


def test_code_minus_one_is_recorded_without_interpretation():
    finding = research.analyze_response(
        response(fixture_bytes("graph_code_minus_one.json")),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=["day", "page", "kind"],
        metric_id=1,
    )
    assert finding["code_present"] is True
    assert finding["code_type"] == "list[int]"
    assert finding["code_value"] == -1
    assert finding["parser_status"] == "code_-1"


def test_empty_graph_dataset_is_recognized():
    finding = research.analyze_response(
        response(fixture_bytes("graph_empty_synthetic.json")),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=["day", "page", "kind"],
        metric_id=1,
    )
    assert finding["data_container_present"] is True
    assert finding["record_count"] == 0
    assert finding["parser_status"] == "empty"


@pytest.mark.parametrize("body", [b"", b"not-json", b"{"])
def test_malformed_json(body):
    finding = research.analyze_response(
        response(body), endpoint_path="/observed.json", parameter_names=[]
    )
    assert finding["parser_status"] == "malformed_json"


def test_html_login_page_is_expired_session():
    finding = research.analyze_response(
        response(
            fixture_bytes("login_page.html"),
            content_type="text/html",
            final_url=research.LOGIN_URL,
        ),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=[],
    )
    assert finding["parser_status"] == "expired_session"


def test_schema_drift_does_not_create_metric():
    finding = research.analyze_response(
        response(b'{"unexpected":{"future":123}}'),
        endpoint_path="/observed.json",
        parameter_names=[],
    )
    assert finding["parser_status"] == "schema_unknown"
    assert finding["metric_id"] is None
    assert finding["metric_key"] is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("202601020304", "YYYYMMDDHHMM"),
        ("20260102030405", "YYYYMMDDHHMMSS"),
        ("2026-01-02T03:04:05Z", "ISO8601_SECONDS"),
        (1700000000, "UNIX_SECONDS"),
        (1700000000000, "UNIX_MILLISECONDS"),
        ("-", None),
        ("", None),
        (None, None),
    ],
)
def test_timestamp_formats(value, expected):
    assert research.timestamp_format(value) == expected


def test_unknown_kind_is_not_requested():
    with pytest.raises(research.StopResearch) as error:
        research.probe_graph_kind(object(), 999)
    assert str(error.value) == "KIND_NOT_ALLOWLISTED"


def test_session_blocks_cross_host_before_network():
    session = research.ResearchSession(interval_seconds=0)
    with pytest.raises(research.CrossHostRequestBlocked):
        session.request("https://example.invalid/data")
    assert session.request_count == 0
    session.close()


@pytest.mark.parametrize("method", ["DELETE", "PUT", "PATCH"])
def test_session_blocks_mutating_methods(method):
    session = research.ResearchSession(interval_seconds=0)
    with pytest.raises(research.StopResearch) as error:
        session.request(research.GRAPH_URL, method=method)
    assert str(error.value) == "METHOD_NOT_ALLOWED"
    assert session.request_count == 0
    session.close()


def test_session_blocks_non_login_post():
    session = research.ResearchSession(interval_seconds=0)
    with pytest.raises(research.StopResearch) as error:
        session.request(research.GRAPH_URL, method="POST")
    assert str(error.value) == "POST_NOT_ALLOWED"
    session.close()


class _SyntheticResponse:
    status = 200
    headers = {"Content-Type": "application/json"}

    def __init__(self, *, status=200, body=b"{}"):
        self.status = status
        self.body = body

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def geturl(self):
        return research.GRAPH_URL

    def read(self):
        return self.body


def test_request_count_hard_limit():
    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            return _SyntheticResponse()

    session = research.ResearchSession(request_limit=2, interval_seconds=0)
    opener = Opener()
    session.opener = opener
    session.request(research.GRAPH_URL)
    session.request(research.GRAPH_URL)
    with pytest.raises(research.RequestLimitReached):
        session.request(research.GRAPH_URL)
    assert opener.calls == 2
    session.close()


def test_http_429_stops_without_retry():
    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, request, **_kwargs):
            self.calls += 1
            raise research.HTTPError(request.full_url, 429, "rate", {}, None)

    session = research.ResearchSession(interval_seconds=0)
    opener = Opener()
    session.opener = opener
    with pytest.raises(research.StopResearch) as error:
        session.request(research.GRAPH_URL)
    assert str(error.value) == "HTTP_429_STOP"
    assert opener.calls == 1
    session.close()


@pytest.mark.parametrize("status", [401, 403])
def test_auth_http_errors_stop(status):
    class Opener:
        def open(self, request, **_kwargs):
            raise research.HTTPError(request.full_url, status, "auth", {}, None)

    session = research.ResearchSession(interval_seconds=0)
    session.opener = Opener()
    with pytest.raises(research.StopResearch) as error:
        session.request(research.GRAPH_URL)
    assert str(error.value) == f"HTTP_{status}_STOP"
    session.close()


def test_5xx_retries_only_once():
    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, request, **_kwargs):
            self.calls += 1
            raise research.HTTPError(request.full_url, 500, "server", {}, None)

    session = research.ResearchSession(interval_seconds=0)
    opener = Opener()
    session.opener = opener
    result = session.request(research.GRAPH_URL)
    assert result.status == 500
    assert opener.calls == 2
    session.close()


def test_timeout_stops_without_retry():
    class Opener:
        def __init__(self):
            self.calls = 0

        def open(self, *_args, **_kwargs):
            self.calls += 1
            raise TimeoutError

    session = research.ResearchSession(interval_seconds=0)
    opener = Opener()
    session.opener = opener
    with pytest.raises(research.StopResearch) as error:
        session.request(research.GRAPH_URL)
    assert str(error.value) == "NETWORK_ERROR_STOP"
    assert opener.calls == 1
    session.close()


def test_session_enforces_spacing_between_request_starts():
    times = iter([10.0, 10.25, 11.0])
    sleeps: list[float] = []

    class Opener:
        def open(self, *_args, **_kwargs):
            return _SyntheticResponse()

    session = research.ResearchSession(
        interval_seconds=1.0,
        sleeper=sleeps.append,
        clock=lambda: next(times),
    )
    session.opener = Opener()
    session.request(research.GRAPH_URL)
    session.request(research.GRAPH_URL)
    assert sleeps == [pytest.approx(0.75)]
    session.close()


def test_session_close_clears_cookie_jar():
    session = research.ResearchSession(interval_seconds=0)
    session.cookie_jar.set_cookie(
        Cookie(
            version=0,
            name="synthetic-session",
            value=SYNTHETIC_COOKIE,
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
    session.close()
    assert len(session.cookie_jar) == 0
    assert session.opener is None
    assert session.closed is True


def test_discovery_accepts_only_observed_same_origin_get_candidates():
    source = """
      fetch('/graph/observed.json?kind=1');
      ajax('https://example.invalid/data');
      const url = '/settings/update';
      const dataUrl = '/measurement/data.json';
    """
    endpoints = research._observed_get_endpoints(source, source_url=research.BASE_URL)
    paths = {research.urlsplit(item).path for item in endpoints}
    assert "/graph/observed.json" in paths
    assert "/measurement/data.json" in paths
    assert "/settings/update" not in paths
    assert all(research.urlsplit(item).hostname == research.BASE_HOST for item in endpoints)


def test_output_never_contains_measurements_or_secrets():
    finding = research.analyze_response(
        response(fixture_bytes("graph_actual_schema_synthetic.json")),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=["day", "page", "kind"],
        metric_id=1,
    )
    output = research.build_output(
        login_metadata={
            "login_page_path": "/login.do",
            "login_field": "loginId",
            "password_field": "passwd",
            "session_cookie_present": True,
        },
        findings=[finding],
        discovery={},
        request_count=3,
        result="synthetic_test",
    )
    serialized = json.dumps(output)
    for forbidden in (
        SYNTHETIC_LOGIN,
        SYNTHETIC_PASSWORD,
        SYNTHETIC_COOKIE,
        "70.0",
        "71.0",
        "1700000000000",
        "fixture-token-not-real",
    ):
        assert forbidden not in serialized


def test_main_does_not_print_or_persist_credentials(monkeypatch, tmp_path, capsys):
    class FakeSession:
        def __init__(self):
            self.request_count = 3

        def close(self):
            return None

    synthetic_finding = research.analyze_response(
        response(fixture_bytes("graph_empty_synthetic.json")),
        endpoint_path=research.GRAPH_PATH,
        parameter_names=["day", "page", "kind"],
        metric_id=1,
    )
    monkeypatch.setattr(
        research,
        "load_credentials",
        lambda: (SYNTHETIC_LOGIN, SYNTHETIC_PASSWORD),
    )
    monkeypatch.setattr(research, "ResearchSession", FakeSession)
    monkeypatch.setattr(
        research,
        "login",
        lambda *_args: research.LoginResult(
            "success",
            "https://www.healthplanet.jp/index.do",
            "<html>logout</html>",
            {"login_field": "loginId", "password_field": "passwd"},
        ),
    )
    monkeypatch.setattr(research, "probe_graph_kind", lambda *_args: synthetic_finding)
    output_path = tmp_path / "_local_only" / "healthplanet_schema_probe.json"
    monkeypatch.setattr(research, "OUTPUT_PATH", output_path)

    assert research.main() == 0
    captured = capsys.readouterr()
    persisted = output_path.read_text(encoding="utf-8")
    combined = captured.out + captured.err + persisted
    assert SYNTHETIC_LOGIN not in combined
    assert SYNTHETIC_PASSWORD not in combined
    assert SYNTHETIC_COOKIE not in combined


def test_gitignore_and_backup_exclude_sensitive_paths():
    root = Path(__file__).resolve().parents[1]
    lines = (root / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert ".env.*" in lines
    assert "!.env.example" in lines
    assert "_local_only/" in lines
    for path in (
        Path(".env.local"),
        Path("_local_only/raw.json"),
        Path("cookies.json"),
        Path("session.json"),
        Path("capture.har"),
        Path("raw_response_1.json"),
        Path("logs/research.log"),
    ):
        assert create_backup.is_excluded(path)


def test_env_local_is_not_tracked():
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        ["git", "ls-files", "--error-unmatch", ".env.local"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0


def test_backup_integrity_exclusions_and_retention(tmp_path, monkeypatch):
    (tmp_path / "README.md").write_text("synthetic", encoding="utf-8")
    for directory in (".git", "_local_only", "logs"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "excluded.txt").write_text("excluded", encoding="utf-8")
    (tmp_path / ".env.local").write_text("excluded", encoding="utf-8")
    (tmp_path / "session.json").write_text("excluded", encoding="utf-8")
    (tmp_path / "capture.har").write_text("excluded", encoding="utf-8")
    (tmp_path / "raw_response_1.json").write_text("excluded", encoding="utf-8")
    monkeypatch.setattr(create_backup, "head_short_sha", lambda _root: "abc1234")
    for _ in range(create_backup.KEEP_BACKUPS + 2):
        archive = create_backup.create_backup(tmp_path)
        assert zipfile.is_zipfile(archive)
    archives = list((tmp_path / "BACKUP").glob("*.zip"))
    assert len(archives) == create_backup.KEEP_BACKUPS
    with zipfile.ZipFile(archives[0]) as opened:
        names = opened.namelist()
    assert "README.md" in names
    assert not any(name.startswith((".git/", "_local_only/", "BACKUP/", "logs/")) for name in names)
    assert ".env.local" not in names
    assert "session.json" not in names
    assert "capture.har" not in names
    assert "raw_response_1.json" not in names
