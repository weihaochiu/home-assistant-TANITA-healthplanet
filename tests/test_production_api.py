from __future__ import annotations

import asyncio
import json

import pytest

from custom_components.tanita_healthplanet.api import WebsiteApiClient
from custom_components.tanita_healthplanet.const import (
    OFFICIAL_SCOPE,
    WEBSITE_GRAPH_URL,
    WEBSITE_HYBRID_KINDS,
    WEBSITE_KINDS,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetAuthError
from custom_components.tanita_healthplanet.models import ProviderSnapshot

SYNTHETIC_TIMESTAMP = "209901020304"


class FakeCookieJar:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True


class FakeSession:
    def __init__(self):
        self.cookie_jar = FakeCookieJar()
        self.closed = False

    async def close(self):
        self.closed = True


def graph_body(value=70.0):
    return json.dumps({"synthetic": True, "code": [0], "value1": [[value, SYNTHETIC_TIMESTAMP]]})


def test_official_scope_contains_both_documented_sources():
    assert OFFICIAL_SCOPE == "innerscan,sphygmomanometer"


@pytest.mark.asyncio
async def test_hybrid_website_client_requests_only_eight_supplemental_kinds(
    monkeypatch,
):
    client = WebsiteApiClient(
        FakeSession(),
        login_id="synthetic-user",
        password="synthetic-password-never-use",
        request_interval=0,
        kinds=WEBSITE_HYBRID_KINDS,
    )
    client._authenticated = True
    requested = []

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        requested.append(kind)
        body = (
            json.dumps({"synthetic": True, "code": [0], "value1": [None]})
            if kind == 23
            else graph_body(kind)
        )
        return 200, "application/json", body, WEBSITE_GRAPH_URL

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert tuple(requested) == WEBSITE_HYBRID_KINDS
    assert 1 not in requested
    assert 2 not in requested
    assert snapshot.measurements[23] is None


@pytest.mark.asyncio
async def test_website_login_submits_csrf_only_in_memory(monkeypatch):
    session = FakeSession()
    client = WebsiteApiClient(
        session,
        login_id="synthetic-user",
        password="synthetic-password-never-use",
        request_interval=0,
    )
    calls = []
    posted = {}

    async def fake_request(method, url, **kwargs):
        nonlocal posted
        calls.append((method, url, kwargs))
        if method == "GET":
            return (
                200,
                "text/html",
                """
                <form method="post" action="/login.do">
                  <input type="hidden"
                         name="org.apache.struts.taglib.html.TOKEN"
                         value="synthetic-csrf">
                  <input type="text" name="loginId">
                  <input type="password" name="passwd">
                </form>
                """,
                "https://www.healthplanet.jp/login.do",
            )
        posted = dict(kwargs["data"])
        return (
            200,
            "text/html",
            "<html>logout</html>",
            "https://www.healthplanet.jp/index.do",
        )

    monkeypatch.setattr(client, "_request", fake_request)
    await client.async_validate_credentials()
    assert len(calls) == 2
    assert posted["org.apache.struts.taglib.html.TOKEN"] == "synthetic-csrf"
    await client.async_close()
    assert session.cookie_jar.cleared is True
    assert session.closed is True


@pytest.mark.asyncio
async def test_website_login_failure_exception_is_redacted(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(),
        login_id="synthetic-user",
        password="synthetic-password-never-use",
        request_interval=0,
    )
    calls = 0

    async def fake_request(method, url, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return (
                200,
                "text/html",
                '<form method="post"><input name="loginId">'
                '<input type="password" name="passwd"></form>',
                "https://www.healthplanet.jp/login.do",
            )
        return (
            200,
            "text/html",
            '<form><input type="password"></form>',
            "https://www.healthplanet.jp/login.do",
        )

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(HealthPlanetAuthError) as error:
        await client.async_validate_credentials()
    rendered = repr(error.value)
    assert "synthetic-user" not in rendered
    assert "synthetic-password-never-use" not in rendered


@pytest.mark.asyncio
async def test_website_partial_kind_failure_does_not_hide_other_metrics(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        body = "malformed" if kind == 4 else graph_body(kind)
        return 200, "application/json", body, "https://www.healthplanet.jp/graph/graph.json"

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert snapshot.measurements[1] is not None
    assert snapshot.measurements[4] is None
    assert snapshot.measurements[23] is not None
    assert snapshot.errors == {4: "response_json_invalid"}
    assert snapshot.kind_statuses[4].outcome == "parser_error"
    assert snapshot.kind_statuses[4].content_category == "json"
    assert snapshot.kind_statuses[4].error_id == "response_json_invalid"


@pytest.mark.asyncio
async def test_backend_code_failure_is_isolated_to_one_kind(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        assert method == "GET"
        assert url == WEBSITE_GRAPH_URL
        assert kwargs["params"] == {"day": 31, "page": 1, "kind": kind}
        assert kwargs["accept"] == "application/json"
        body = (
            json.dumps({"synthetic": True, "code": [-1], "value1": []})
            if kind == 5
            else graph_body(kind)
        )
        return 200, "application/json", body, "https://www.healthplanet.jp/graph/graph.json"

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert snapshot.measurements[4] is not None
    assert snapshot.measurements[5] is None
    assert snapshot.measurements[6] is not None
    assert snapshot.errors == {5: "website_backend_code_minus_one"}
    assert snapshot.kind_statuses[5].outcome == "backend_error"
    assert snapshot.kind_statuses[5].backend_code == -1


@pytest.mark.asyncio
async def test_kind_23_null_does_not_fail_update(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        body = (
            json.dumps({"synthetic": True, "code": [0], "value1": [None]})
            if kind == 23
            else graph_body(kind)
        )
        return 200, "application/json", body, "https://www.healthplanet.jp/graph/graph.json"

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert snapshot.measurements[23] is None
    assert snapshot.measurements[22] is not None
    assert snapshot.errors == {}
    assert snapshot.kind_statuses[23].outcome == "null"
    assert snapshot.kind_statuses[23].row_count == 1


@pytest.mark.asyncio
async def test_first_nine_kinds_available_when_kind_23_is_null(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        body = (
            json.dumps({"synthetic": True, "code": [0], "value1": [None]})
            if kind == 23
            else graph_body(kind)
        )
        return 200, "application/json; charset=UTF-8", body, url

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert all(snapshot.measurements[kind] is not None for kind in WEBSITE_KINDS[:-1])
    assert snapshot.measurements[23] is None
    assert snapshot.errors == {}
    assert {kind: status.outcome for kind, status in snapshot.kind_statuses.items()} == {
        **dict.fromkeys(WEBSITE_KINDS[:-1], "available"),
        23: "null",
    }


@pytest.mark.asyncio
async def test_http_and_schema_failures_have_structural_diagnostics(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        kind = kwargs["params"]["kind"]
        if kind == 1:
            return 503, "text/plain", "synthetic service response", url
        if kind == 2:
            return 200, "application/json", "{", url
        if kind == 3:
            return 200, "application/json", json.dumps({"code": [0], "changed": []}), url
        if kind == 4:
            return (
                200,
                "application/json",
                json.dumps({"code": ["synthetic-private-payload"], "value1": []}),
                url,
            )
        return 200, "application/json", graph_body(kind), url

    monkeypatch.setattr(client, "_request", fake_request)
    snapshot = await client.async_fetch()
    assert snapshot.kind_statuses[1].outcome == "http_error"
    assert snapshot.kind_statuses[1].http_status == 503
    assert snapshot.kind_statuses[2].error_id == "response_json_invalid"
    assert snapshot.kind_statuses[3].error_id == "website_value_container_invalid"
    assert snapshot.kind_statuses[4].outcome == "backend_error"
    assert snapshot.kind_statuses[4].backend_code is None
    rendered = repr(snapshot.kind_statuses)
    assert "synthetic service response" not in rendered
    assert "synthetic-private-payload" not in rendered


@pytest.mark.asyncio
async def test_html_session_expiry_relogs_in_once_then_raises_auth(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True
    logins = 0

    async def fake_login():
        nonlocal logins
        logins += 1
        client._authenticated = True

    async def fake_request(method, url, **kwargs):
        return 200, "text/html", "<html><form>synthetic login</form></html>", url

    monkeypatch.setattr(client, "_login", fake_login)
    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(HealthPlanetAuthError):
        await client.async_fetch()
    assert logins == 1
    assert client.diagnostic_statuses[1].outcome == "html"


@pytest.mark.asyncio
async def test_auth_http_status_is_not_swallowed_as_per_kind_error(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True

    async def fake_request(method, url, **kwargs):
        return 401, "application/json", "{}", url

    monkeypatch.setattr(client, "_request", fake_request)
    with pytest.raises(HealthPlanetAuthError):
        await client.async_fetch()
    assert client.diagnostic_statuses[1].outcome == "auth_error"
    assert client.diagnostic_statuses[1].http_status == 401


@pytest.mark.asyncio
async def test_session_expiry_allows_only_one_controlled_relogin(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    client._authenticated = True
    logins = 0
    fetches = 0

    async def fake_login():
        nonlocal logins
        logins += 1
        client._authenticated = True

    async def fake_fetch_once():
        nonlocal fetches
        fetches += 1
        if fetches == 1:
            client._authenticated = False
            raise HealthPlanetAuthError("website_session_expired")
        return ProviderSnapshot(measurements={kind: None for kind in WEBSITE_KINDS})

    monkeypatch.setattr(client, "_login", fake_login)
    monkeypatch.setattr(client, "_fetch_once", fake_fetch_once)
    await client.async_fetch()
    assert logins == 1
    assert fetches == 2


@pytest.mark.asyncio
async def test_concurrent_updates_share_login_lock(monkeypatch):
    client = WebsiteApiClient(
        FakeSession(), login_id="synthetic", password="synthetic", request_interval=0
    )
    logins = 0

    async def fake_login():
        nonlocal logins
        logins += 1
        await asyncio.sleep(0)
        client._authenticated = True

    async def fake_fetch_once():
        await asyncio.sleep(0)
        return ProviderSnapshot(measurements={kind: None for kind in WEBSITE_KINDS})

    monkeypatch.setattr(client, "_login", fake_login)
    monkeypatch.setattr(client, "_fetch_once", fake_fetch_once)
    await asyncio.gather(client.async_fetch(), client.async_fetch())
    assert logins == 1


def test_no_production_runtime_imports_research_package():
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    for path in (root / "custom_components" / "tanita_healthplanet").glob("*.py"):
        assert "research." not in path.read_text(encoding="utf-8")
