from __future__ import annotations

from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.exceptions import (
    OAuth2TokenRequestError,
    OAuth2TokenRequestReauthError,
)

from custom_components.tanita_healthplanet import application_credentials
from custom_components.tanita_healthplanet.application_credentials import (
    HealthPlanetOAuth2Implementation,
)
from custom_components.tanita_healthplanet.const import DOMAIN, OFFICIAL_SCOPE


class SyntheticTokenResponse:
    def __init__(self, body):
        self._body = body
        self.status = 200

    async def text(self):
        return self._body

    def raise_for_status(self):
        return None


class SyntheticTokenSession:
    def __init__(self, body):
        self.body = body
        self.calls = []

    async def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return SyntheticTokenResponse(self.body)


def implementation(hass=None):
    return HealthPlanetOAuth2Implementation(
        hass or SimpleNamespace(),
        "synthetic-application",
        "synthetic-client",
        "synthetic-secret-never-use",
        "https://www.healthplanet.jp/oauth/auth",
        "https://www.healthplanet.jp/oauth/token",
    )


def test_application_credentials_adds_both_official_scopes():
    assert implementation().extra_authorize_data == {"scope": OFFICIAL_SCOPE}


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
    assert error.value.message == "healthplanet_oauth_token_missing"
    assert "must-not-leak" not in repr(error.value)


@pytest.mark.asyncio
async def test_undocumented_refresh_grant_requires_standard_reauth():
    with pytest.raises(OAuth2TokenRequestReauthError) as error:
        await implementation()._async_refresh_token({"access_token": "synthetic-token-never-use"})
    assert error.value.domain == DOMAIN
    assert "synthetic-token-never-use" not in repr(error.value)
