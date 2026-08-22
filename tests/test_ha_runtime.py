from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant import config_entries
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tanita_healthplanet import async_setup_entry as async_setup_integration
from custom_components.tanita_healthplanet.api import OfficialApiClient
from custom_components.tanita_healthplanet.const import (
    DOMAIN,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
)
from custom_components.tanita_healthplanet.coordinator import HealthPlanetCoordinator
from custom_components.tanita_healthplanet.errors import (
    HealthPlanetAuthError,
    HealthPlanetConnectionError,
    HealthPlanetManualInteractionRequired,
    HealthPlanetRateLimitError,
)
from custom_components.tanita_healthplanet.models import Measurement, ProviderSnapshot
from custom_components.tanita_healthplanet.sensor import async_setup_entry


def _entry(provider: str, entry_id: str) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title=f"Synthetic {entry_id}",
        data={"provider": provider, "access_token": "synthetic-token-never-use"},
        options={"update_interval": 60},
        unique_id=f"synthetic-{entry_id}",
        entry_id=entry_id,
    )


async def test_coordinator_keeps_partial_snapshot_and_entry_interval(hass):
    snapshot = ProviderSnapshot(measurements={1: None, 2: None}, errors={2: "schema"})
    provider = SimpleNamespace(async_fetch=AsyncMock(return_value=snapshot))
    coordinator = HealthPlanetCoordinator(hass, _entry(PROVIDER_OFFICIAL, "first"), provider)
    assert coordinator.update_interval.total_seconds() == 3600
    assert await coordinator._async_update_data() is snapshot


async def test_setup_failure_closes_provider_state(hass, monkeypatch):
    entry = _entry(PROVIDER_OFFICIAL, "setup-failure")
    entry.mock_state(hass, config_entries.ConfigEntryState.SETUP_IN_PROGRESS)
    failed_fetch = AsyncMock(side_effect=HealthPlanetAuthError("redacted"))
    closed = AsyncMock()
    monkeypatch.setattr(OfficialApiClient, "async_fetch", failed_fetch)
    monkeypatch.setattr(OfficialApiClient, "async_close", closed)
    with pytest.raises(ConfigEntryAuthFailed):
        await async_setup_integration(hass, entry)
    closed.assert_awaited_once()


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (HealthPlanetAuthError("redacted"), ConfigEntryAuthFailed),
        (HealthPlanetManualInteractionRequired("redacted"), ConfigEntryAuthFailed),
        (HealthPlanetRateLimitError("redacted"), UpdateFailed),
        (HealthPlanetConnectionError("redacted"), UpdateFailed),
    ],
)
async def test_coordinator_maps_provider_failures(hass, error, expected):
    provider = SimpleNamespace(async_fetch=AsyncMock(side_effect=error))
    coordinator = HealthPlanetCoordinator(hass, _entry(PROVIDER_OFFICIAL, "error"), provider)
    with pytest.raises(expected):
        await coordinator._async_update_data()


async def test_sensor_platform_official_ids_and_unavailable_state(hass):
    entry = _entry(PROVIDER_OFFICIAL, "official-entry")
    provider = SimpleNamespace(async_fetch=AsyncMock())
    coordinator = HealthPlanetCoordinator(hass, entry, provider)
    coordinator.async_set_updated_data(ProviderSnapshot(measurements={1: None, 2: None}))
    entry.runtime_data = SimpleNamespace(coordinator=coordinator)
    entities = []
    await async_setup_entry(hass, entry, entities.extend)
    assert len(entities) == 2
    assert {entity.unique_id for entity in entities} == {
        "official-entry_1",
        "official-entry_2",
    }
    assert all(entity.available is False for entity in entities)
    assert all(entity.native_value is None for entity in entities)
    assert all(
        entity.device_info["identifiers"] == {(DOMAIN, "official-entry")} for entity in entities
    )


async def test_website_entries_are_isolated_and_expose_ten_metrics(hass):
    first = _entry(PROVIDER_WEBSITE, "website-first")
    second = _entry(PROVIDER_WEBSITE, "website-second")
    first_provider = SimpleNamespace(async_fetch=AsyncMock())
    second_provider = SimpleNamespace(async_fetch=AsyncMock())
    first_coordinator = HealthPlanetCoordinator(hass, first, first_provider)
    second_coordinator = HealthPlanetCoordinator(hass, second, second_provider)
    measurement = Measurement(
        metric_key="weight",
        value=70.0,
        unit="kg",
        measured_at=__import__("datetime").datetime(2099, 1, 1, tzinfo=__import__("datetime").UTC),
        source="synthetic",
        model=None,
        experimental=True,
        raw_kind=1,
    )
    first_coordinator.async_set_updated_data(ProviderSnapshot(measurements={1: measurement}))
    second_coordinator.async_set_updated_data(ProviderSnapshot(measurements={1: None}))
    first.runtime_data = SimpleNamespace(coordinator=first_coordinator)
    second.runtime_data = SimpleNamespace(coordinator=second_coordinator)
    first_entities = []
    second_entities = []
    await async_setup_entry(hass, first, first_entities.extend)
    await async_setup_entry(hass, second, second_entities.extend)
    assert len(first_entities) == len(second_entities) == 10
    assert first_entities[0].native_value == 70.0
    assert second_entities[0].native_value is None
    assert {entity.unique_id for entity in first_entities}.isdisjoint(
        entity.unique_id for entity in second_entities
    )
