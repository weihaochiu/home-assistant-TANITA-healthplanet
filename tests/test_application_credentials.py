from __future__ import annotations

from types import SimpleNamespace

import pytest
from aiohttp import ClientError

pytest.importorskip("homeassistant")

from homeassistant.exceptions import (
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
    OAuth2TokenRequestTransientError,
)

from custom_components.tanita_healthplanet import application_credentials
from custom_components.tanita_healthplanet.application_credentials import (
    HealthPlanetOAuth2Implementation,
    normalize_authorization_code,
)
from custom_components.tanita_healthplanet.const import (
    DOMAIN,
    OFFICIAL_REDIRECT_URI,
    OFFICIAL_SCOPE,
)


class SyntheticTokenResponse:
    def __init__(self, body, status=200, content_type="application/json"):
        self._body = body
        self.status = status
        self.headers = {"Content-Type": content_type}

    async def text(self):
        return self._body

    def raise_for_status(self):
        return None


class SyntheticTokenSession:
    def __init__(self, body, status=200, content_type="application/json", error=None):
        self.body = body
        self.status = status
        self.content_type = content_type
        self.error = error
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if self.error:
            raise self.error
        return SyntheticTokenResponse(self.body, self.status, self.content_type)


def implementation(hass=None):
    return HealthPlanetOAuth2Implementation(
        hass or SimpleNamespace(data={}),
        "synthetic-application",
        "synthetic-client",
        "synthetic-secret-never-use",
        "https://www.healthplanet.jp/oauth/auth",
        "https://www.healthplanet.jp/oauth/token",
    )


def test_application_credentials_adds_both_official_scopes():
    assert implementation().extra_authorize_data == {"scope": OFFICIAL_SCOPE}
    assert implementation().redirect_uri == OFFICIAL_REDIRECT_URI


@pytest.mark.asyncio
async def test_manual_authorize_url_has_fixed_redirect_and_no_state():
    url = await implementation().async_generate_manual_authorize_url()
    assert "redirect_uri=https://www.healthplanet.jp/success.html" in url
    assert "scope=innerscan,sphygmomanometer" in url
    assert "response_type=code" in url
    assert "state=" not in url


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "body",
    [
        '{"access_token":"synthetic-token-never-use","expires_in":"7200"}',
        "access_token=synthetic-token-never-use",
    ],
)
async def test_token_response_is_normalized_without_payload_persistence(monkeypatch, body):
    session = SyntheticTokenSession(body)
    monkeypatch.setattr(
        application_credentials,
        "async_get_clientsession",
        lambda hass: session,
    )
    token = await implementation()._token_request(
        {
            "grant_type": "authorization_code",
            "code": "synthetic-code-never-use",
            "redirect_uri": "https://example.invalid/callback",
        }
    )
    assert token["access_token"] == "synthetic-token-never-use"
    assert token["token_type"] == "Bearer"
    assert int(token["expires_in"]) > 0
    assert set(token) == {"access_token", "token_type", "expires_in"}


@pytest.mark.asyncio
async def test_invalid_expiry_uses_positive_local_fallback(monkeypatch):
    session = SyntheticTokenSession(
        '{"access_token":"synthetic-token-never-use","expires_in":"invalid"}'
    )
    monkeypatch.setattr(
        application_credentials,
        "async_get_clientsession",
        lambda hass: session,
    )
    token = await implementation()._token_request({"grant_type": "authorization_code"})
    assert isinstance(token["expires_in"], int)
    assert token["expires_in"] > 0


@pytest.mark.asyncio
async def test_manual_exchange_returns_only_access_token_and_fixed_redirect(monkeypatch):
    session = SyntheticTokenSession('{"access_token":"synthetic-token-never-use"}')
    monkeypatch.setattr(application_credentials, "async_get_clientsession", lambda hass: session)
    access_token = await implementation().async_exchange_authorization_code(
        "synthetic-code-never-use"
    )
    assert access_token == "synthetic-token-never-use"
    posted = session.calls[0][1]["data"]
    assert posted["redirect_uri"] == OFFICIAL_REDIRECT_URI
    assert posted["grant_type"] == "authorization_code"
    assert session.calls[0][1]["headers"]["Content-Type"] == "application/x-www-form-urlencoded"


@pytest.mark.asyncio
async def test_missing_token_raises_fixed_oauth_error_without_body(
    monkeypatch,
):
    private_payload = '{"synthetic_private_payload":"must-not-leak"}'
    session = SyntheticTokenSession(private_payload)
    monkeypatch.setattr(
        application_credentials,
        "async_get_clientsession",
        lambda hass: session,
    )
    with pytest.raises(OAuth2TokenRequestError) as error:
        await implementation()._token_request(
            {
                "grant_type": "authorization_code",
                "code": "synthetic-code-never-use",
                "redirect_uri": "https://example.invalid/callback",
            }
        )
    assert error.value.message == "oauth_token_missing"
    assert "must-not-leak" not in repr(error.value)


@pytest.mark.asyncio
async def test_undocumented_refresh_grant_requires_standard_reauth():
    with pytest.raises(OAuth2TokenRequestReauthError) as error:
        await implementation()._async_refresh_token({"access_token": "synthetic-token-never-use"})
    assert error.value.domain == DOMAIN
    assert "synthetic-token-never-use" not in repr(error.value)


def test_authorization_code_normalization_accepts_only_exact_success_url():
    assert normalize_authorization_code(" RAW-CODE ") == "RAW-CODE"
    assert (
        normalize_authorization_code("https://www.healthplanet.jp/success.html?code=SYNTHETIC-CODE")
        == "SYNTHETIC-CODE"
    )
    assert normalize_authorization_code("https://evil.invalid/success.html?code=NO") == ""
    assert normalize_authorization_code("http://www.healthplanet.jp/success.html?code=NO") == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("status", "body", "expected_exception", "error_id"),
    [
        (
            400,
            '{"error":"invalid_grant","error_description":"private"}',
            OAuth2TokenRequestReauthError,
            "oauth_token_invalid_grant",
        ),
        (
            400,
            "error=invalid_client&error_description=private",
            OAuth2TokenRequestReauthError,
            "oauth_token_invalid_client",
        ),
        (
            401,
            '{"error":"invalid_client"}',
            OAuth2TokenRequestReauthError,
            "oauth_token_invalid_client",
        ),
        (
            403,
            '{"error":"invalid_request"}',
            OAuth2TokenRequestReauthError,
            "oauth_token_invalid_request",
        ),
        (
            429,
            '{"error":"rate_limited"}',
            OAuth2TokenRequestTransientError,
            "oauth_token_http_error",
        ),
        (500, "temporary-private-body", OAuth2TokenRequestTransientError, "oauth_token_http_error"),
    ],
)
async def test_http_errors_are_allowlisted_and_redacted(
    monkeypatch, caplog, status, body, expected_exception, error_id
):
    hass = SimpleNamespace(data={})
    session = SyntheticTokenSession(body, status=status)
    monkeypatch.setattr(application_credentials, "async_get_clientsession", lambda current: session)
    with pytest.raises(expected_exception) as error:
        await implementation(hass)._token_request({"grant_type": "authorization_code"})
    assert error.value.message == error_id
    assert hass.data[DOMAIN]["oauth_status"]["last_oauth_http_status"] == status
    assert hass.data[DOMAIN]["oauth_status"]["last_oauth_error_id"] == error_id
    assert "private" not in caplog.text


@pytest.mark.asyncio
async def test_malformed_success_and_timeout_are_fixed_errors(monkeypatch):
    session = SyntheticTokenSession("not-json-or-form")
    monkeypatch.setattr(application_credentials, "async_get_clientsession", lambda hass: session)
    with pytest.raises(OAuth2TokenRequestError) as malformed:
        await implementation()._token_request({"grant_type": "authorization_code"})
    assert malformed.value.message == "oauth_token_response_invalid"

    session = SyntheticTokenSession("", error=TimeoutError())
    monkeypatch.setattr(application_credentials, "async_get_clientsession", lambda hass: session)
    with pytest.raises(OAuth2TokenRequestError) as timeout:
        await implementation()._token_request({"grant_type": "authorization_code"})
    assert timeout.value.message == "healthplanet_oauth_connection_failed"

    session = SyntheticTokenSession("", error=ClientError("synthetic network failure"))
    monkeypatch.setattr(application_credentials, "async_get_clientsession", lambda hass: session)
    with pytest.raises(OAuth2TokenRequestError) as network:
        await implementation()._token_request({"grant_type": "authorization_code"})
    assert network.value.message == "healthplanet_oauth_connection_failed"
