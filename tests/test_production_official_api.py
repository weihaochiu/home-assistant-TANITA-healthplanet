from __future__ import annotations

import json

import pytest

from custom_components.tanita_healthplanet.api import OfficialApiClient
from custom_components.tanita_healthplanet.const import (
    OFFICIAL_INNERSCAN_URL,
    OFFICIAL_SPHYGMO_URL,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetAuthError

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


class RoutedHttpSession:
    def __init__(self, responses):
        self.responses = responses
        self.posts = []

    def post(self, url, **kwargs):
        self.posts.append((url, dict(kwargs), dict(kwargs["data"])))
        status, body = self.responses[url]
        return FakeResponse(status, body)


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
    assert [request[0] for request in session.posts] == [
        OFFICIAL_INNERSCAN_URL,
        OFFICIAL_SPHYGMO_URL,
    ]
    _, kwargs, posted = session.posts[0]
    assert posted["access_token"] == "synthetic-token-never-use"
    assert "access_token" not in kwargs["headers"]
    await client.async_close()
    assert client._access_token == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "outcome"),
    [
        (429, "rate_limited"),
        (500, "http_error"),
        (418, "http_error"),
    ],
)
async def test_official_fetch_endpoint_errors_are_structural(status, outcome):
    client = OfficialApiClient(
        FakeHttpSession(status=status, body="synthetic response"),
        "synthetic-token-never-use",
    )
    snapshot = await client.async_fetch()
    assert all(value is None for value in snapshot.measurements.values())
    assert set(snapshot.errors) == {1, 2, 101, 102, 103}
    assert {status.outcome for status in snapshot.endpoint_statuses.values()} == {outcome}


@pytest.mark.asyncio
async def test_official_fetch_auth_error_is_not_no_data():
    client = OfficialApiClient(
        FakeHttpSession(status=403, body="synthetic response"),
        "synthetic-token-never-use",
    )
    with pytest.raises(HealthPlanetAuthError):
        await client.async_fetch()


@pytest.mark.asyncio
async def test_malformed_innerscan_json_does_not_hide_valid_blood_pressure():
    session = RoutedHttpSession(
        {
            OFFICIAL_INNERSCAN_URL: (200, "{"),
            OFFICIAL_SPHYGMO_URL: (
                200,
                json.dumps(
                    {
                        "synthetic": True,
                        "data": [
                            {
                                "tag": "622E",
                                "keydata": "501",
                                "date": SYNTHETIC_TIMESTAMP,
                            },
                            {
                                "tag": "622F",
                                "keydata": "502",
                                "date": SYNTHETIC_TIMESTAMP,
                            },
                            {
                                "tag": "6230",
                                "keydata": "503",
                                "date": SYNTHETIC_TIMESTAMP,
                            },
                        ],
                    }
                ),
            ),
        }
    )
    snapshot = await OfficialApiClient(session, "synthetic-token-never-use").async_fetch()
    assert snapshot.endpoint_statuses["innerscan"].outcome == "parser_error"
    assert snapshot.endpoint_statuses["sphygmomanometer"].outcome == "available"
    assert snapshot.measurements[1] is None
    assert snapshot.measurements[101].value == 501
    assert snapshot.measurements[102].value == 502
    assert snapshot.measurements[103].value == 503


@pytest.mark.asyncio
async def test_official_update_uses_one_call_per_endpoint_not_per_tag():
    empty = json.dumps({"synthetic": True, "data": []})
    session = RoutedHttpSession(
        {
            OFFICIAL_INNERSCAN_URL: (200, empty),
            OFFICIAL_SPHYGMO_URL: (200, empty),
        }
    )
    await OfficialApiClient(session, "synthetic-token-never-use").async_fetch()
    assert len(session.posts) == 2
    assert session.posts[0][2]["tag"] == "6021,6022"
    assert session.posts[1][2]["tag"] == "622E,622F,6230"
    assert all(posted["date"] == "1" for _, _, posted in session.posts)


@pytest.mark.asyncio
async def test_official_history_uses_documented_bounded_range_and_keeps_rows():
    body = json.dumps(
        {
            "data": [
                {"tag": "6021", "keydata": "60", "date": "202608010100"},
                {"tag": "6021", "keydata": "61", "date": "202608020100"},
            ]
        }
    )
    session = FakeHttpSession(body=body)
    snapshot = await OfficialApiClient(session, "synthetic-token-never-use").async_fetch_history(90)
    assert [item.value for item in snapshot.history[1]] == [60, 61]
    assert snapshot.measurements[1].value == 61
    assert all(posted["date"] == "1" for _, _, posted in session.posts)
    assert all("from" in posted and "to" in posted for _, _, posted in session.posts)
    assert all(len(posted["from"]) == 14 for _, _, posted in session.posts)
