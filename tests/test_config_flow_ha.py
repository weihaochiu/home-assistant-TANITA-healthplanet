from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.exceptions import OAuth2TokenRequestReauthError
from homeassistant.helpers import config_entry_oauth2_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tanita_healthplanet import async_migrate_entry, async_unload_entry
from custom_components.tanita_healthplanet.api import WebsiteApiClient
from custom_components.tanita_healthplanet.application_credentials import (
    HealthPlanetOAuth2Implementation,
    _oauth_request_info,
)
from custom_components.tanita_healthplanet.config_flow import _identity
from custom_components.tanita_healthplanet.const import (
    CONF_ACCESS_TOKEN,
    CONF_ACCOUNT_LABEL,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_HACS_UPDATE_ENTITY,
    CONF_HISTORY_SYNC_ENABLED,
    CONF_LOGIN_ID,
    CONF_MODE,
    CONF_OFFICIAL_HISTORY_DAYS,
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_REAUTH_SOURCE,
    CONF_RESTART_AFTER_SAFE_UPDATE,
    CONF_STORAGE_WARNING_CONFIRMED,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DOMAIN,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
    PROVIDER_WEBSITE,
    SOURCE_OFFICIAL,
)
from custom_components.tanita_healthplanet.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetAuthError
from custom_components.tanita_healthplanet.models import (
    EndpointStatus,
    KindStatus,
    ProviderSnapshot,
)


def _register_oauth(hass, domain="synthetic-application"):
    implementation = HealthPlanetOAuth2Implementation(
        hass,
        domain,
        "synthetic-shared-client",
        "synthetic-shared-secret-never-use",
        "https://www.healthplanet.jp/oauth/auth",
        "https://www.healthplanet.jp/oauth/token",
    )
    config_entry_oauth2_flow.async_register_implementation(hass, DOMAIN, implementation)
    return implementation


async def _begin_new(hass, label="Grace"):
    implementation = _register_oauth(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert {key.schema for key in result["data_schema"].schema} == {CONF_ACCOUNT_LABEL}
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT_LABEL: label}
    )
    assert result["step_id"] == "manual_authorization"
    assert "state=" not in result["description_placeholders"]["authorize_url"]
    assert (
        "redirect_uri=https://www.healthplanet.jp/success.html"
        in result["description_placeholders"]["authorize_url"]
    )
    return implementation, result


async def _complete_manual(hass, implementation, result, token="synthetic-token-never-use"):
    with patch.object(
        implementation,
        "async_exchange_authorization_code",
        AsyncMock(return_value=token),
    ) as exchange:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"authorization_code": "synthetic-code-never-use"}
        )
    exchange.assert_awaited_once_with("synthetic-code-never-use")
    return result


async def _complete_website(hass, result, login="synthetic-user"):
    with patch.object(WebsiteApiClient, "async_validate_credentials", AsyncMock(return_value=None)):
        return await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: login,
                CONF_PASSWORD: "synthetic-password-never-use",
                CONF_EXPERIMENTAL_CONFIRMED: True,
                CONF_STORAGE_WARNING_CONFIRMED: True,
            },
        )


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_new_user_sees_hybrid_only_manual_code_flow(hass):
    implementation, result = await _begin_new(hass, "Grace")
    result = await _complete_manual(hass, implementation, result)
    assert result["step_id"] == "website"
    result = await _complete_website(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "HealthPlanet - Grace"
    assert result["data"][CONF_MODE] == MODE_HYBRID
    assert result["data"][CONF_ACCOUNT_LABEL] == "Grace"
    assert result["data"][CONF_ACCESS_TOKEN] == "synthetic-token-never-use"
    assert result["data"]["auth_implementation"] == "synthetic-application"
    assert "authorization_code" not in result["data"]
    assert "client_id" not in result["data"]
    assert "client_secret" not in result["data"]
    assert "token" not in result["data"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_missing_application_credentials_has_setup_guidance(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_ACCOUNT_LABEL: "Grace"}
    )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "missing_credentials"
    assert result["description_placeholders"]["docs_url"].endswith("docs/HEALTHPLANET_API_SETUP.md")


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_two_family_members_share_application_but_store_distinct_tokens(hass):
    created = []
    for label, login, token in (
        ("Grace", "synthetic-grace", "synthetic-grace-token-never-use"),
        ("Wei-Hao", "synthetic-weihao", "synthetic-weihao-token-never-use"),
    ):
        implementation, result = await _begin_new(hass, label)
        result = await _complete_manual(hass, implementation, result, token)
        created.append(await _complete_website(hass, result, login))
    assert {item["data"]["auth_implementation"] for item in created} == {"synthetic-application"}
    assert {item["data"][CONF_ACCESS_TOKEN] for item in created} == {
        "synthetic-grace-token-never-use",
        "synthetic-weihao-token-never-use",
    }
    assert {entry.unique_id for entry in hass.config_entries.async_entries(DOMAIN)} == {
        _identity("synthetic-grace"),
        _identity("synthetic-weihao"),
    }


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_oauth_status_survives_failed_config_flow_and_preserves_existing_family(hass):
    existing = MockConfigEntry(
        domain=DOMAIN,
        title="HealthPlanet - Existing",
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_ACCESS_TOKEN: "synthetic-existing-token-never-use",
            CONF_LOGIN_ID: "synthetic-existing-user",
            CONF_PASSWORD: "synthetic-existing-password-never-use",
        },
    )
    existing.add_to_hass(hass)
    original = dict(existing.data)
    implementation, result = await _begin_new(hass, "Second family")

    async def fail_exchange(code: str) -> str:
        implementation._record_status(
            400,
            "json",
            "json",
            "authorization_code_invalid",
            "OAuth2TokenRequestReauthError",
        )
        raise OAuth2TokenRequestReauthError(
            request_info=_oauth_request_info(),
            history=(),
            status=400,
            message="authorization_code_invalid",
            headers=None,
            domain=DOMAIN,
        )

    with patch.object(
        implementation,
        "async_exchange_authorization_code",
        side_effect=fail_exchange,
    ):
        failed = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"authorization_code": "synthetic-code-never-use"}
        )
    assert failed["type"] is FlowResultType.FORM
    assert failed["errors"] == {"base": "authorization_code_invalid"}
    assert existing.data == original
    status = hass.data[DOMAIN]["oauth_status"]
    assert status == {
        "stage": "token_exchange",
        "response_format": "json",
        "content_category": "json",
        "exception_type": "OAuth2TokenRequestReauthError",
        "last_attempt_result": "failed",
        "last_oauth_http_status": 400,
        "last_oauth_error_id": "authorization_code_invalid",
    }
    rendered = repr(status)
    for forbidden in original.values():
        assert str(forbidden) not in rendered


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_duplicate_website_account_is_rejected(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HealthPlanet - Existing",
        unique_id=_identity("synthetic-user"),
        data={CONF_MODE: MODE_HYBRID},
    )
    entry.add_to_hass(hass)
    implementation, result = await _begin_new(hass)
    result = await _complete_manual(hass, implementation, result)
    result = await _complete_website(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_login_failure_is_redacted(hass, caplog):
    implementation, result = await _begin_new(hass)
    result = await _complete_manual(hass, implementation, result)
    with patch.object(
        WebsiteApiClient,
        "async_validate_credentials",
        AsyncMock(side_effect=HealthPlanetAuthError("website_login_rejected")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: "synthetic-private-login",
                CONF_PASSWORD: "synthetic-private-password-never-use",
                CONF_EXPERIMENTAL_CONFIRMED: True,
                CONF_STORAGE_WARNING_CONFIRMED: True,
            },
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert "synthetic-private-login" not in caplog.text
    assert "synthetic-private-password-never-use" not in caplog.text


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_reauth_manual_code_preserves_website(hass):
    implementation = _register_oauth(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HealthPlanet - Grace",
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_ACCOUNT_LABEL: "Grace",
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
            CONF_ACCESS_TOKEN: "synthetic-old-token-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_REAUTH, "entry_id": entry.entry_id},
        data={**entry.data, CONF_REAUTH_SOURCE: SOURCE_OFFICIAL},
    )
    assert result["step_id"] == "manual_authorization"
    result = await _complete_manual(hass, implementation, result, "synthetic-new-token-never-use")
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_ACCESS_TOKEN] == "synthetic-new-token-never-use"
    assert entry.data[CONF_PASSWORD] == "synthetic-password-never-use"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_only_reconfigure_upgrades_in_place_without_password_echo(hass):
    implementation = _register_oauth(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy Website",
        unique_id=_identity("synthetic-user"),
        data={
            CONF_MODE: MODE_WEBSITE_ONLY,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data=entry.data,
    )
    assert "synthetic-password-never-use" not in repr(result)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"upgrade_to_hybrid": True, CONF_ACCOUNT_LABEL: "Grace"},
    )
    result = await _complete_manual(hass, implementation, result)
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_MODE] == MODE_HYBRID
    assert entry.data[CONF_PASSWORD] == "synthetic-password-never-use"
    assert entry.data[CONF_ACCESS_TOKEN] == "synthetic-token-never-use"
    assert entry.unique_id == _identity("synthetic-user")


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_only_reconfigure_adds_website_and_preserves_token(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Legacy Official",
        data={
            CONF_MODE: MODE_OFFICIAL_ONLY,
            CONF_ACCESS_TOKEN: "synthetic-official-token-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": config_entries.SOURCE_RECONFIGURE, "entry_id": entry.entry_id},
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"upgrade_to_hybrid": True, CONF_ACCOUNT_LABEL: "Grace"},
    )
    assert result["step_id"] == "website"
    result = await _complete_website(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_MODE] == MODE_HYBRID
    assert entry.data[CONF_ACCESS_TOKEN] == "synthetic-official-token-never-use"
    assert entry.data[CONF_PASSWORD] == "synthetic-password-never-use"


async def test_v1_and_v2_migrations_are_idempotent_and_preserve_secrets(hass):
    for version, data in (
        (
            1,
            {
                CONF_PROVIDER: PROVIDER_WEBSITE,
                CONF_LOGIN_ID: "synthetic-user",
                CONF_PASSWORD: "synthetic-password-never-use",
            },
        ),
        (
            2,
            {
                CONF_MODE: MODE_OFFICIAL_ONLY,
                CONF_ACCESS_TOKEN: "synthetic-token-never-use",
            },
        ),
    ):
        entry = MockConfigEntry(domain=DOMAIN, title="Legacy", data=data, version=version)
        entry.add_to_hass(hass)
        original = dict(entry.data)
        assert await async_migrate_entry(hass, entry) is True
        assert entry.version == 3
        if version == 1:
            assert entry.data[CONF_MODE] == MODE_WEBSITE_ONLY
            assert entry.data[CONF_PASSWORD] == original[CONF_PASSWORD]
        else:
            assert entry.data == original
        migrated = dict(entry.data)
        assert await async_migrate_entry(hass, entry) is True
        assert entry.data == migrated


async def test_unload_closes_all_target_entry_sessions_only():
    official_provider = SimpleNamespace(async_close=AsyncMock())
    website_provider = SimpleNamespace(async_close=AsyncMock())
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(providers=(official_provider, website_provider))
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
    )
    assert await async_unload_entry(hass, entry) is True
    official_provider.async_close.assert_awaited_once()
    website_provider.async_close.assert_awaited_once()


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_hybrid_options_include_history_controls(hass):
    entry = MockConfigEntry(domain=DOMAIN, title="Hybrid", data={CONF_MODE: MODE_HYBRID})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert set(result["data_schema"].schema) == {
        CONF_OFFICIAL_UPDATE_INTERVAL,
        CONF_WEBSITE_UPDATE_INTERVAL,
        CONF_HISTORY_SYNC_ENABLED,
        CONF_OFFICIAL_HISTORY_DAYS,
        CONF_HACS_UPDATE_ENTITY,
        CONF_RESTART_AFTER_SAFE_UPDATE,
    }


async def test_split_diagnostics_exclude_credentials_values_and_measurement_timestamps():
    official = SimpleNamespace(
        last_update_success=True,
        endpoint_statuses={
            "innerscan": EndpointStatus(outcome="available", http_status=200, record_count=2),
            "sphygmomanometer": EndpointStatus(
                outcome="null", http_status=200, complete_pair_found=False
            ),
        },
    )
    website = SimpleNamespace(
        data=ProviderSnapshot(measurements={23: None}),
        last_update_success=True,
        kind_statuses={23: KindStatus(kind=23, outcome="null", row_count=1)},
    )
    entry = SimpleNamespace(
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_ACCOUNT_LABEL: "Private Family Name",
            CONF_LOGIN_ID: "synthetic-private-user",
            CONF_PASSWORD: "synthetic-private-password-never-use",
            CONF_ACCESS_TOKEN: "synthetic-private-token-never-use",
            "authorization_code": "synthetic-private-authorization-code-never-use",
            "backup_encryption_key": "synthetic-private-backup-key-never-use",
            "github_token": "synthetic-private-github-token-never-use",
        },
        options={},
        runtime_data=SimpleNamespace(
            official_coordinator=official,
            website_coordinator=website,
            history_sync=None,
        ),
    )
    diagnostics = await async_get_config_entry_diagnostics(SimpleNamespace(), entry)
    rendered = repr(diagnostics)
    assert set(diagnostics) == {
        "mode",
        "official",
        "website",
        "history",
        "safe_update",
        "oauth",
    }
    for forbidden in (
        "Private Family Name",
        "synthetic-private-user",
        "synthetic-private-password-never-use",
        "synthetic-private-token-never-use",
        "synthetic-private-authorization-code-never-use",
        "synthetic-private-backup-key-never-use",
        "synthetic-private-github-token-never-use",
        "measurement_time",
    ):
        assert forbidden not in rendered
