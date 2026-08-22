from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.tanita_healthplanet import async_unload_entry
from custom_components.tanita_healthplanet.api import OfficialApiClient, WebsiteApiClient
from custom_components.tanita_healthplanet.const import (
    CONF_ACCOUNT_LABEL,
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EXPERIMENTAL_CONFIRMED,
    CONF_LOGIN_ID,
    CONF_PASSWORD,
    CONF_PROVIDER,
    CONF_STORAGE_WARNING_CONFIRMED,
    DOMAIN,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
)
from custom_components.tanita_healthplanet.diagnostics import (
    async_get_config_entry_diagnostics,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetAuthError
from custom_components.tanita_healthplanet.models import KindStatus, ProviderSnapshot


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_official_provider_config_flow(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROVIDER: PROVIDER_OFFICIAL}
    )
    assert result["step_id"] == "official"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_CLIENT_ID: "synthetic-client",
            CONF_CLIENT_SECRET: "synthetic-secret-never-use",
            CONF_ACCOUNT_LABEL: "Synthetic Account",
        },
    )
    assert result["step_id"] == "official_authorize"
    assert "client_secret" not in result["description_placeholders"]["authorize_url"]

    snapshot = ProviderSnapshot(measurements={1: None, 2: None})
    with (
        patch.object(
            OfficialApiClient,
            "async_exchange_code",
            AsyncMock(return_value="synthetic-token-never-use"),
        ),
        patch.object(OfficialApiClient, "async_fetch", AsyncMock(return_value=snapshot)),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {"authorization_code": "synthetic-code-never-use"}
        )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_PROVIDER] == PROVIDER_OFFICIAL


@pytest.mark.usefixtures("enable_custom_integrations")
async def test_website_requires_both_explicit_confirmations(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROVIDER: PROVIDER_WEBSITE}
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
        result["flow_id"], {CONF_PROVIDER: PROVIDER_WEBSITE}
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


async def test_unload_closes_only_the_target_entry_session():
    first_provider = SimpleNamespace(async_close=AsyncMock())
    second_provider = SimpleNamespace(async_close=AsyncMock())
    first = SimpleNamespace(runtime_data=SimpleNamespace(provider=first_provider))
    hass = SimpleNamespace(
        config_entries=SimpleNamespace(async_unload_platforms=AsyncMock(return_value=True))
    )
    assert await async_unload_entry(hass, first) is True
    first_provider.async_close.assert_awaited_once()
    second_provider.async_close.assert_not_awaited()


async def test_diagnostics_exclude_credentials_values_and_timestamps():
    snapshot = ProviderSnapshot(measurements={1: None, 23: None}, errors={23: "schema"})
    coordinator = SimpleNamespace(
        data=snapshot,
        last_update_success=True,
        kind_statuses={
            1: KindStatus(
                kind=1,
                outcome="parser_error",
                http_status=200,
                content_category="json",
                error_id="synthetic_schema_mismatch",
                row_count=7,
                timestamp_parsing_success=False,
            ),
            23: KindStatus(
                kind=23,
                outcome="null",
                http_status=200,
                content_category="json",
                backend_code=0,
                row_count=1,
            ),
        },
    )
    entry = SimpleNamespace(
        data={
            CONF_PROVIDER: PROVIDER_WEBSITE,
            CONF_LOGIN_ID: "synthetic-user",
            CONF_PASSWORD: "synthetic-password-never-use",
        },
        options={},
        runtime_data=SimpleNamespace(coordinator=coordinator),
    )
    diagnostics = await async_get_config_entry_diagnostics(SimpleNamespace(), entry)
    rendered = repr(diagnostics)
    assert "synthetic-user" not in rendered
    assert "synthetic-password-never-use" not in rendered
    assert set(diagnostics) == {
        "provider",
        "update_interval_minutes",
        "last_update_success",
        "available_kinds",
        "unavailable_kinds",
        "error_kinds",
        "per_kind",
    }
    assert diagnostics["per_kind"][0] == {
        "kind": 1,
        "outcome": "parser_error",
        "http_status": 200,
        "content_category": "json",
        "backend_code": None,
        "error_id": "synthetic_schema_mismatch",
        "row_count": 7,
        "timestamp_parsing_success": False,
    }
    assert "measurement" not in rendered
    assert "timestamp" not in rendered.casefold().replace("timestamp_parsing_success", "")
