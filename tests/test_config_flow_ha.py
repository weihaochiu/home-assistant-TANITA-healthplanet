from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_entry_oauth2_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tanita_healthplanet import (
    async_migrate_entry,
    async_unload_entry,
)
from custom_components.tanita_healthplanet.api import WebsiteApiClient
from custom_components.tanita_healthplanet.const import (
    CONF_ACCESS_TOKEN,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_LOGIN_ID,
    CONF_MODE,
    CONF_OFFICIAL_UPDATE_INTERVAL,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_REAUTH_SOURCE,
    CONF_STORAGE_WARNING_CONFIRMED,
    CONF_WEBSITE_UPDATE_INTERVAL,
    DOMAIN,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
    SOURCE_OFFICIAL,
    SOURCE_WEBSITE,
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


class SyntheticOAuthImplementation:
    domain = "synthetic-application"
    name = "Synthetic application"

    async def async_generate_authorize_url(self, flow_id):
        return "https://example.invalid/authorize"

    async def async_resolve_external_data(self, external_data):
        return {
            "access_token": "synthetic-token-never-use",
            "expires_in": 3600,
        }

    async def async_refresh_token(self, token):
        return token


def _register_oauth(hass):
    config_entry_oauth2_flow.async_register_implementation(
        hass, DOMAIN, SyntheticOAuthImplementation()
    )


async def _complete_oauth(hass, result):
    assert result["step_id"] == "pick_implementation"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"implementation": "synthetic-application"}
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            "code": "synthetic-code-never-use",
            "state": {"redirect_uri": "https://example.invalid/callback"},
        },
    )
    assert result["type"] is FlowResultType.EXTERNAL_STEP_DONE
    return await hass.config_entries.flow.async_configure(result["flow_id"])


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_only_uses_standard_oauth_config_flow(hass):
    _register_oauth(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MODE: MODE_OFFICIAL_ONLY}
    )
    result = await _complete_oauth(hass, result)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODE] == MODE_OFFICIAL_ONLY
    assert result["data"]["auth_implementation"] == "synthetic-application"
    assert result["data"]["token"]["access_token"] == "synthetic-token-never-use"
    assert CONF_LOGIN_ID not in result["data"]
    assert CONF_PASSWORD not in result["data"]


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_requires_both_explicit_confirmations(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MODE: MODE_WEBSITE_ONLY}
    )
    base = {
        CONF_LOGIN_ID: "synthetic-user",
        CONF_PASSWORD: "synthetic-password-never-use",
        CONF_EXPERIMENTAL_CONFIRMED: False,
        CONF_STORAGE_WARNING_CONFIRMED: True,
    }
    result = await hass.config_entries.flow.async_configure(result["flow_id"], base)
    assert result["errors"] == {"base": "experimental_confirmation_required"}

    base[CONF_EXPERIMENTAL_CONFIRMED] = True
    base[CONF_STORAGE_WARNING_CONFIRMED] = False
    result = await hass.config_entries.flow.async_configure(result["flow_id"], base)
    assert result["errors"] == {"base": "storage_confirmation_required"}


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_login_failure_is_redacted(hass, caplog):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MODE: MODE_WEBSITE_ONLY}
    )
    sensitive_login = "synthetic-user"
    sensitive_password = "synthetic-password-never-use"
    with patch.object(
        WebsiteApiClient,
        "async_validate_credentials",
        AsyncMock(side_effect=HealthPlanetAuthError("website_login_rejected")),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: sensitive_login,
                CONF_PASSWORD: sensitive_password,
                CONF_EXPERIMENTAL_CONFIRMED: True,
                CONF_STORAGE_WARNING_CONFIRMED: True,
            },
        )
    assert result["errors"] == {"base": "invalid_auth"}
    assert sensitive_login not in caplog.text
    assert sensitive_password not in caplog.text


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_hybrid_oauth_then_explicit_website_opt_in(hass):
    _register_oauth(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_MODE: MODE_HYBRID}
    )
    result = await _complete_oauth(hass, result)
    assert result["step_id"] == "website_opt_in"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"enable_website": True}
    )
    assert result["step_id"] == "website"
    with patch.object(WebsiteApiClient, "async_validate_credentials", AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: "synthetic-user",
                CONF_PASSWORD: "synthetic-password-never-use",
                CONF_EXPERIMENTAL_CONFIRMED: True,
                CONF_STORAGE_WARNING_CONFIRMED: True,
            },
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_MODE] == MODE_HYBRID
    assert result["data"][CONF_PASSWORD] == "synthetic-password-never-use"
    assert result["data"]["token"]["access_token"] == "synthetic-token-never-use"


async def test_unload_closes_all_target_entry_sessions_only():
    official_provider = SimpleNamespace(async_close=AsyncMock())
    website_provider = SimpleNamespace(async_close=AsyncMock())
    unrelated_provider = SimpleNamespace(async_close=AsyncMock())
    entry = SimpleNamespace(
        runtime_data=SimpleNamespace(providers=(official_provider, website_provider))
    )
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
    )
    assert await async_unload_entry(hass, entry) is True
    official_provider.async_close.assert_awaited_once()
    website_provider.async_close.assert_awaited_once()
    unrelated_provider.async_close.assert_not_awaited()


async def test_website_entry_migration_is_idempotent_and_preserves_credentials(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic legacy",
        data={
            CONF_PROVIDER: PROVIDER_WEBSITE,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
        },
        version=1,
    )
    entry.add_to_hass(hass)
    original_password = entry.data[CONF_PASSWORD]
    assert await async_migrate_entry(hass, entry) is True
    assert entry.version == 2
    assert entry.minor_version == 0
    assert entry.data[CONF_MODE] == MODE_WEBSITE_ONLY
    assert entry.data[CONF_PASSWORD] == original_password
    migrated_data = dict(entry.data)
    assert await async_migrate_entry(hass, entry) is True
    assert entry.data == migrated_data


async def test_official_entry_migration_requires_explicit_oauth_reauthorization(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic legacy official",
        data={
            CONF_PROVIDER: PROVIDER_OFFICIAL,
            CONF_ACCESS_TOKEN: "synthetic-legacy-token-never-use",
        },
        version=1,
    )
    entry.add_to_hass(hass)
    assert await async_migrate_entry(hass, entry) is True
    assert entry.data[CONF_MODE] == MODE_OFFICIAL_ONLY
    assert "token" not in entry.data
    assert entry.data[CONF_ACCESS_TOKEN] == "synthetic-legacy-token-never-use"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_reauth_changes_only_website_credentials(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic hybrid",
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_LOGIN_ID: "synthetic-old-user",
            CONF_PASSWORD: "synthetic-old-password-never-use",
            "auth_implementation": "synthetic-application",
            "token": {
                "access_token": "synthetic-official-token-never-use",
                "expires_in": 3600,
                "expires_at": 4102444800,
            },
        },
    )
    entry.add_to_hass(hass)
    original_token = dict(entry.data["token"])
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data={**entry.data, CONF_REAUTH_SOURCE: SOURCE_WEBSITE},
    )
    assert result["step_id"] == "reauth_website"
    assert result["data_schema"](
        {
            CONF_LOGIN_ID: "synthetic-new-user",
            CONF_PASSWORD: "synthetic-new-password-never-use",
        }
    )
    with patch.object(WebsiteApiClient, "async_validate_credentials", AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: "synthetic-new-user",
                CONF_PASSWORD: "synthetic-new-password-never-use",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"] == original_token
    assert entry.data[CONF_LOGIN_ID] == "synthetic-new-user"
    assert entry.data[CONF_PASSWORD] == "synthetic-new-password-never-use"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_reauth_preserves_website_and_removes_legacy_oauth_fields(
    hass,
):
    _register_oauth(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic hybrid",
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
            CONF_CLIENT_ID: "synthetic-legacy-client",
            CONF_CLIENT_SECRET: "synthetic-legacy-secret-never-use",
            CONF_ACCESS_TOKEN: "synthetic-legacy-token-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data={**entry.data, CONF_REAUTH_SOURCE: SOURCE_OFFICIAL},
    )
    result = await _complete_oauth(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert entry.data[CONF_LOGIN_ID] == "synthetic-user"
    assert entry.data[CONF_PASSWORD] == "synthetic-password-never-use"
    assert entry.data["token"]["access_token"] == "synthetic-token-never-use"
    assert CONF_CLIENT_ID not in entry.data
    assert CONF_CLIENT_SECRET not in entry.data
    assert CONF_ACCESS_TOKEN not in entry.data


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_both_source_reauth_runs_oauth_then_website_without_cross_clearing(hass):
    _register_oauth(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic hybrid",
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_LOGIN_ID: "synthetic-old-user",
            CONF_PASSWORD: "synthetic-old-password-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data={**entry.data, CONF_REAUTH_SOURCE: "both"},
    )
    result = await _complete_oauth(hass, result)
    assert result["step_id"] == "reauth_website"
    with (
        patch.object(
            WebsiteApiClient,
            "async_validate_credentials",
            AsyncMock(return_value=None),
        ),
        patch.object(hass.config_entries, "async_reload", AsyncMock()),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_LOGIN_ID: "synthetic-new-user",
                CONF_PASSWORD: "synthetic-new-password-never-use",
            },
        )
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert entry.data["token"]["access_token"] == "synthetic-token-never-use"
    assert entry.data[CONF_LOGIN_ID] == "synthetic-new-user"
    assert entry.data[CONF_PASSWORD] == "synthetic-new-password-never-use"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_only_reconfigure_upgrades_to_hybrid_without_password_echo(
    hass,
):
    _register_oauth(hass)
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic website",
        data={
            CONF_MODE: MODE_WEBSITE_ONLY,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
        },
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_RECONFIGURE,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    rendered = repr(result)
    assert "synthetic-password-never-use" not in rendered
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"upgrade_to_hybrid": True}
    )
    with patch.object(hass.config_entries, "async_reload", AsyncMock()):
        result = await _complete_oauth(hass, result)
    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_MODE] == MODE_HYBRID
    assert entry.data[CONF_PASSWORD] == "synthetic-password-never-use"
    assert entry.data["token"]["access_token"] == "synthetic-token-never-use"


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_hybrid_options_store_independent_source_intervals(hass):
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic hybrid",
        data={CONF_MODE: MODE_HYBRID},
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    assert set(result["data_schema"].schema) == {
        CONF_OFFICIAL_UPDATE_INTERVAL,
        CONF_WEBSITE_UPDATE_INTERVAL,
    }
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_OFFICIAL_UPDATE_INTERVAL: 30,
            CONF_WEBSITE_UPDATE_INTERVAL: 120,
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_OFFICIAL_UPDATE_INTERVAL: 30,
        CONF_WEBSITE_UPDATE_INTERVAL: 120,
    }


async def test_split_diagnostics_exclude_credentials_values_and_timestamps():
    official = SimpleNamespace(
        last_update_success=True,
        endpoint_statuses={
            "innerscan": EndpointStatus(
                outcome="available",
                http_status=200,
                record_count=2,
                available_tags=("6021", "6022"),
            ),
            "sphygmomanometer": EndpointStatus(
                outcome="null",
                http_status=200,
                record_count=0,
                unavailable_tags=("622E", "622F", "6230"),
                complete_pair_found=False,
            ),
        },
    )
    website = SimpleNamespace(
        data=ProviderSnapshot(measurements={23: None}),
        last_update_success=True,
        kind_statuses={
            23: KindStatus(
                kind=23,
                outcome="null",
                http_status=200,
                content_category="json",
                backend_code=0,
                row_count=1,
            )
        },
    )
    entry = SimpleNamespace(
        data={
            CONF_MODE: MODE_HYBRID,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
            "token": {"access_token": "synthetic-token-never-use"},
        },
        options={},
        runtime_data=SimpleNamespace(
            official_coordinator=official,
            website_coordinator=website,
        ),
    )
    diagnostics = await async_get_config_entry_diagnostics(SimpleNamespace(), entry)
    rendered = repr(diagnostics)
    assert set(diagnostics) == {"mode", "official", "website"}
    assert diagnostics["official"]["sphygmomanometer"]["complete_pair_found"] is False
    assert diagnostics["website"]["per_kind"][0]["outcome"] == "null"
    for forbidden in (
        "synthetic-user",
        "synthetic-password-never-use",
        "synthetic-token-never-use",
        "measurement",
    ):
        assert forbidden not in rendered
