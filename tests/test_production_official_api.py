from __future__ import annotations

import json

import pytest

from custom_components.tanita_healthplanet.api import OfficialApiClient
from custom_components.tanita_healthplanet.errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetRateLimitError,
)

SYNTHETIC_TIMESTAMP = "209901020304"


class FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def text(self):
        return self._body


class FakeHttpSession:
    def __init__(self, status=200, body="{}", error=None):
        self.status = status
        self.body = body
        self.error = error
        self.posts = []

    def post(self, url, **kwargs):
        if self.error is not None:
            raise self.error
        self.posts.append((url, dict(kwargs), dict(kwargs["data"])))
        return FakeResponse(self.status, self.body)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"access_token": "synthetic-token-never-use"}),
        "access_token=synthetic-token-never-use",
    ],
)
async def test_official_oauth_exchange_accepts_documented_response_shapes(body):
    session = FakeHttpSession(body=body)
    token = await OfficialApiClient.async_exchange_code(
        session,
        client_id="synthetic-client",
        client_secret="synthetic-secret-never-use",
        code="synthetic-code-never-use",
    )
    assert token == "synthetic-token-never-use"
    _, kwargs, posted = session.posts[0]
    assert posted["client_secret"] == "synthetic-secret-never-use"
    assert "client_secret" not in kwargs.get("headers", {})


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, HealthPlanetAuthError),
        (429, HealthPlanetRateLimitError),
        (503, HealthPlanetConnectionError),
    ],
)
async def test_official_oauth_status_errors_are_typed_and_redacted(status, expected):
    session = FakeHttpSession(status=status, body="synthetic response")
    with pytest.raises(expected) as error:
        await OfficialApiClient.async_exchange_code(
            session,
            client_id="synthetic-client",
            client_secret="synthetic-secret-never-use",
            code="synthetic-code-never-use",
        )
    assert "synthetic-secret-never-use" not in repr(error.value)


@pytest.mark.asyncio
async def test_official_oauth_timeout_is_connection_error():
    session = FakeHttpSession(error=TimeoutError())
    with pytest.raises(HealthPlanetConnectionError) as error:
        await OfficialApiClient.async_exchange_code(
            session,
            client_id="synthetic-client",
            client_secret="synthetic-secret-never-use",
            code="synthetic-code-never-use",
        )
    assert str(error.value) == "official_oauth_timeout"


@pytest.mark.asyncio
async def test_official_fetch_returns_only_latest_weight_and_body_fat():
    session = FakeHttpSession(
        body=json.dumps(
            {
                "synthetic": True,
                "data": [
                    {"tag": "6021", "keydata": "70", "date": SYNTHETIC_TIMESTAMP},
                    {"tag": "6022", "keydata": "20", "date": SYNTHETIC_TIMESTAMP},
                ],
            }
        )
    )
    client = OfficialApiClient(session, "synthetic-token-never-use")
    snapshot = await client.async_fetch()
    assert snapshot.measurements[1].value == 70
    assert snapshot.measurements[2].value == 20
    _, kwargs, posted = session.posts[0]
    assert posted["access_token"] == "synthetic-token-never-use"
    assert "access_token" not in kwargs["headers"]
    await client.async_close()
    assert client._access_token == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (403, HealthPlanetAuthError),
        (429, HealthPlanetRateLimitError),
        (500, HealthPlanetConnectionError),
        (418, HealthPlanetConnectionError),
    ],
)
async def test_official_fetch_status_errors(status, expected):
    client = OfficialApiClient(
        FakeHttpSession(status=status, body="synthetic response"),
        "synthetic-token-never-use",
    )
    with pytest.raises(expected):
        await client.async_fetch()
