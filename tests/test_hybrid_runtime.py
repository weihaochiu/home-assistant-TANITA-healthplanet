from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import UnitOfPressure
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.tanita_healthplanet.const import (
    CONF_MODE,
    DOMAIN,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
    OFFICIAL_KINDS,
    PROVIDER_OFFICIAL,
    PROVIDER_WEBSITE,
    SOURCE_OFFICIAL,
    SOURCE_WEBSITE,
    WEBSITE_HYBRID_KINDS,
    WEBSITE_KINDS,
)
from custom_components.tanita_healthplanet.coordinator import (
    OfficialCoordinator,
    WebsiteCoordinator,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetAuthError
from custom_components.tanita_healthplanet.models import (
    EndpointStatus,
    KindStatus,
    Measurement,
    ProviderSnapshot,
)
from custom_components.tanita_healthplanet.sensor import async_setup_entry

SYNTHETIC_TIME = datetime(2099, 1, 1, tzinfo=UTC)


def entry(mode, entry_id="hybrid-entry"):
    return MockConfigEntry(
        domain=DOMAIN,
        title="Synthetic HealthPlanet",
        data={CONF_MODE: mode},
        options={},
        unique_id=f"synthetic-{entry_id}",
        entry_id=entry_id,
    )


def measurement(kind, source):
    return Measurement(
        metric_key=f"synthetic_{kind}",
        value=kind,
        unit=None,
        measured_at=SYNTHETIC_TIME,
        source=source,
        model=None,
        experimental=source == SOURCE_WEBSITE,
        raw_kind=kind,
    )


def successful_official_snapshot():
    return ProviderSnapshot(
        measurements={kind: measurement(kind, SOURCE_OFFICIAL) for kind in OFFICIAL_KINDS},
        endpoint_statuses={
            "innerscan": EndpointStatus(
                outcome="available",
                http_status=200,
                record_count=2,
                available_tags=("6021", "6022"),
            ),
            "sphygmomanometer": EndpointStatus(
                outcome="available",
                http_status=200,
                record_count=3,
                available_tags=("622E", "622F", "6230"),
                complete_pair_found=True,
            ),
        },
    )


def successful_website_snapshot():
    statuses = {
        kind: KindStatus(
            kind=kind,
            outcome="available",
            http_status=200,
            content_category="json",
            backend_code=0,
            row_count=1,
            timestamp_parsing_success=True,
        )
        for kind in WEBSITE_HYBRID_KINDS
        if kind != 23
    }
    statuses[23] = KindStatus(
        kind=23,
        outcome="null",
        http_status=200,
        content_category="json",
        backend_code=0,
        row_count=1,
    )
    return ProviderSnapshot(
        measurements={
            kind: (None if kind == 23 else measurement(kind, SOURCE_WEBSITE))
            for kind in WEBSITE_HYBRID_KINDS
        },
        kind_statuses=statuses,
    )


def failed_website_snapshot():
    primary = tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23)
    statuses = {
        kind: KindStatus(
            kind=kind,
            outcome="parser_error",
            http_status=200,
            content_category="json",
            error_id="synthetic_schema_error",
            row_count=1,
            timestamp_parsing_success=False,
        )
        for kind in primary
    }
    statuses[23] = KindStatus(
        kind=23,
        outcome="null",
        http_status=200,
        content_category="json",
        backend_code=0,
        row_count=1,
    )
    return ProviderSnapshot(
        measurements=dict.fromkeys(WEBSITE_HYBRID_KINDS),
        errors=dict.fromkeys(primary, "synthetic_schema_error"),
        kind_statuses=statuses,
    )


def failed_official_snapshot():
    return ProviderSnapshot(
        measurements=dict.fromkeys(OFFICIAL_KINDS),
        errors=dict.fromkeys(OFFICIAL_KINDS, "synthetic_endpoint_error"),
        endpoint_statuses={
            "innerscan": EndpointStatus(
                outcome="http_error",
                error_id="synthetic_endpoint_error",
                unavailable_tags=("6021", "6022"),
            ),
            "sphygmomanometer": EndpointStatus(
                outcome="http_error",
                error_id="synthetic_endpoint_error",
                unavailable_tags=("622E", "622F", "6230"),
                complete_pair_found=False,
            ),
        },
    )


async def _entities_for_mode(hass, mode):
    config_entry = entry(mode)
    official = OfficialCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_OFFICIAL,
            async_fetch=AsyncMock(),
        ),
    )
    website = WebsiteCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_WEBSITE,
            async_fetch=AsyncMock(),
        ),
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    official.async_set_updated_data(successful_official_snapshot())
    website.async_set_updated_data(successful_website_snapshot())
    config_entry.runtime_data = SimpleNamespace(
        official_coordinator=(official if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY} else None),
        website_coordinator=(website if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY} else None),
        coordinator=official if mode == MODE_OFFICIAL_ONLY else website,
    )
    entities = []
    await async_setup_entry(hass, config_entry, entities.extend)
    return entities


async def test_official_only_creates_five_sensors(hass):
    entities = await _entities_for_mode(hass, MODE_OFFICIAL_ONLY)
    assert len(entities) == 5
    assert {item.extra_state_attributes["data_source"] for item in entities} == {SOURCE_OFFICIAL}


async def test_hybrid_creates_thirteen_source_owned_sensors_on_one_device(hass):
    entities = await _entities_for_mode(hass, MODE_HYBRID)
    assert len(entities) == 13
    assert len({item.unique_id for item in entities}) == 13
    assert len({frozenset(item.device_info["identifiers"]) for item in entities}) == 1
    assert (
        sum(item.extra_state_attributes["data_source"] == SOURCE_OFFICIAL for item in entities) == 5
    )
    assert (
        sum(item.extra_state_attributes["data_source"] == SOURCE_WEBSITE for item in entities) == 8
    )


async def test_website_only_creates_ten_sensors_with_stable_kind_ids(hass):
    entities = await _entities_for_mode(hass, MODE_WEBSITE_ONLY)
    assert len(entities) == 10
    assert {item.unique_id for item in entities} == {
        f"hybrid-entry_{kind}" for kind in WEBSITE_KINDS
    }
    assert {item.extra_state_attributes["data_source"] for item in entities} == {SOURCE_WEBSITE}


async def test_blood_pressure_and_pulse_entity_semantics_match_ha_2026_8_2(hass):
    entities = {
        item.entity_description.kind: item
        for item in await _entities_for_mode(hass, MODE_OFFICIAL_ONLY)
    }
    for kind in (101, 102):
        assert entities[kind].device_class is SensorDeviceClass.PRESSURE
        assert entities[kind].native_unit_of_measurement is UnitOfPressure.MMHG
        assert entities[kind].state_class is SensorStateClass.MEASUREMENT
    assert entities[103].device_class is None
    assert entities[103].native_unit_of_measurement == "bpm"
    assert entities[103].state_class is SensorStateClass.MEASUREMENT


async def test_website_total_failure_does_not_change_official_success(hass):
    config_entry = entry(MODE_HYBRID, "website-fails")
    official_provider = SimpleNamespace(
        provider_type=PROVIDER_OFFICIAL,
        async_fetch=AsyncMock(return_value=successful_official_snapshot()),
    )
    website_provider = SimpleNamespace(
        provider_type=PROVIDER_WEBSITE,
        async_fetch=AsyncMock(return_value=failed_website_snapshot()),
    )
    official = OfficialCoordinator(hass, config_entry, official_provider)
    website = WebsiteCoordinator(
        hass,
        config_entry,
        website_provider,
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    await official.async_refresh()
    await website.async_refresh()
    assert official.last_update_success is True
    assert official.data.measurements[1] is not None
    assert website.last_update_success is False


async def test_official_total_failure_does_not_change_website_success(hass):
    config_entry = entry(MODE_HYBRID, "official-fails")
    official = OfficialCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_OFFICIAL,
            async_fetch=AsyncMock(return_value=failed_official_snapshot()),
        ),
    )
    website = WebsiteCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_WEBSITE,
            async_fetch=AsyncMock(return_value=successful_website_snapshot()),
        ),
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    await official.async_refresh()
    await website.async_refresh()
    assert official.last_update_success is False
    assert website.last_update_success is True
    assert website.data.measurements[3] is not None
    assert website.data.measurements[23] is None


@pytest.mark.parametrize(
    ("failed_endpoint", "available_kind"),
    [("innerscan", 101), ("sphygmomanometer", 1)],
)
async def test_official_endpoint_partial_failure_keeps_other_endpoint(
    hass, failed_endpoint, available_kind
):
    snapshot = successful_official_snapshot()
    statuses = dict(snapshot.endpoint_statuses)
    failed_kinds = (1, 2) if failed_endpoint == "innerscan" else (101, 102, 103)
    measurements = dict(snapshot.measurements)
    for kind in failed_kinds:
        measurements[kind] = None
    statuses[failed_endpoint] = EndpointStatus(
        outcome="http_error",
        error_id="synthetic_endpoint_error",
    )
    snapshot = ProviderSnapshot(
        measurements=measurements,
        errors=dict.fromkeys(failed_kinds, "synthetic_endpoint_error"),
        endpoint_statuses=statuses,
    )
    coordinator = OfficialCoordinator(
        hass,
        entry(MODE_HYBRID, failed_endpoint),
        SimpleNamespace(
            provider_type=PROVIDER_OFFICIAL,
            async_fetch=AsyncMock(return_value=snapshot),
        ),
    )
    await coordinator.async_refresh()
    assert coordinator.last_update_success is True
    assert coordinator.data.measurements[available_kind] is not None


async def test_source_auth_failure_does_not_clear_other_coordinator_data(hass):
    config_entry = entry(MODE_HYBRID, "auth-isolation")
    official = OfficialCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_OFFICIAL,
            async_fetch=AsyncMock(side_effect=HealthPlanetAuthError("synthetic_auth")),
        ),
    )
    website = WebsiteCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_WEBSITE,
            async_fetch=AsyncMock(return_value=successful_website_snapshot()),
        ),
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    await website.async_refresh()
    preserved = website.data
    await official.async_refresh()
    assert official.auth_failed is True
    assert official.last_update_success is False
    assert website.last_update_success is True
    assert website.data is preserved


async def test_website_auth_failure_does_not_clear_official_data(hass):
    config_entry = entry(MODE_HYBRID, "website-auth-isolation")
    official = OfficialCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_OFFICIAL,
            async_fetch=AsyncMock(return_value=successful_official_snapshot()),
        ),
    )
    website = WebsiteCoordinator(
        hass,
        config_entry,
        SimpleNamespace(
            provider_type=PROVIDER_WEBSITE,
            async_fetch=AsyncMock(side_effect=HealthPlanetAuthError("synthetic_auth")),
        ),
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    await official.async_refresh()
    preserved = official.data
    await website.async_refresh()
    assert website.auth_failed is True
    assert website.last_update_success is False
    assert official.last_update_success is True
    assert official.data is preserved


async def test_source_warning_reappears_only_after_recovery(hass, caplog):
    failure = failed_official_snapshot()
    provider = SimpleNamespace(
        provider_type=PROVIDER_OFFICIAL,
        async_fetch=AsyncMock(
            side_effect=[failure, failure, successful_official_snapshot(), failure]
        ),
    )
    coordinator = OfficialCoordinator(hass, entry(MODE_HYBRID, "warning-recovery"), provider)
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    await coordinator.async_refresh()
    messages = [
        record.getMessage()
        for record in caplog.records
        if "endpoint=innerscan" in record.getMessage()
    ]
    assert len(messages) == 2
    rendered = caplog.text
    for forbidden in (
        "synthetic-password-never-use",
        "synthetic-token-never-use",
        "209901020304",
        "98765.4321",
    ):
        assert forbidden not in rendered


async def test_coordinators_refresh_independently(hass):
    config_entry = entry(MODE_HYBRID, "independent-refresh")
    official_fetch = AsyncMock(return_value=successful_official_snapshot())
    website_fetch = AsyncMock(return_value=successful_website_snapshot())
    official = OfficialCoordinator(
        hass,
        config_entry,
        SimpleNamespace(provider_type=PROVIDER_OFFICIAL, async_fetch=official_fetch),
    )
    website = WebsiteCoordinator(
        hass,
        config_entry,
        SimpleNamespace(provider_type=PROVIDER_WEBSITE, async_fetch=website_fetch),
        primary_kinds=tuple(kind for kind in WEBSITE_HYBRID_KINDS if kind != 23),
    )
    await official.async_refresh()
    official_fetch.assert_awaited_once()
    website_fetch.assert_not_awaited()
    await website.async_refresh()
    website_fetch.assert_awaited_once()
    official_fetch.assert_awaited_once()
