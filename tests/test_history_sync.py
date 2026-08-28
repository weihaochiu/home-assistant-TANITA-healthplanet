from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

pytest.importorskip("homeassistant")

from homeassistant.components.recorder.models import StatisticMeanType
from homeassistant.components.recorder.statistics import valid_statistic_id

from custom_components.tanita_healthplanet.const import SOURCE_OFFICIAL, SOURCE_WEBSITE
from custom_components.tanita_healthplanet.history import (
    HistorySyncManager,
    hourly_statistics,
    statistic_id_for,
    statistic_metadata,
)
from custom_components.tanita_healthplanet.models import Measurement, ProviderSnapshot, RuntimeData


def measurement(kind: int, value: float, minute: int, source: str) -> Measurement:
    return Measurement(
        metric_key=f"synthetic_{kind}",
        value=value,
        unit="kg" if kind == 1 else "%",
        measured_at=datetime(2026, 8, 1, 3, minute, tzinfo=UTC),
        source=source,
        model=None,
        experimental=source == SOURCE_WEBSITE,
        raw_kind=kind,
    )


def test_hourly_statistics_use_measured_at_and_measurement_semantics():
    stats = hourly_statistics(
        (
            measurement(1, 60.0, 5, SOURCE_OFFICIAL),
            measurement(1, 64.0, 45, SOURCE_OFFICIAL),
        )
    )
    assert len(stats) == 1
    assert stats[0]["start"] == datetime(2026, 8, 1, 3, 0, tzinfo=UTC)
    assert stats[0]["mean"] == 62.0
    assert stats[0]["min"] == 60.0
    assert stats[0]["max"] == 64.0
    assert "sum" not in stats[0]


def test_metadata_is_explicitly_ha_2026_11_safe():
    metadata = statistic_metadata("0123456789abcdef", 1)
    assert metadata["statistic_id"] == "tanita_healthplanet:0123456789abcdef_1"
    assert metadata["source"] == "tanita_healthplanet"
    assert metadata["mean_type"] is StatisticMeanType.ARITHMETIC
    assert metadata["has_sum"] is False
    assert metadata["unit_class"] == "mass"
    assert metadata["unit_of_measurement"] == "kg"
    assert "has_mean" not in metadata


def test_statistic_id_uppercase_entry_id():
    entry_id = "01M10K4M0P890X641ZCED5ZD07"
    old_statistic_id = f"tanita_healthplanet:{entry_id}_1"
    new_statistic_id = statistic_id_for(entry_id, 1)
    assert old_statistic_id == "tanita_healthplanet:01M10K4M0P890X641ZCED5ZD07_1"
    assert new_statistic_id == "tanita_healthplanet:01m10k4m0p890x641zced5zd07_1"
    assert valid_statistic_id(old_statistic_id) is False
    assert valid_statistic_id(new_statistic_id) is True


@pytest.mark.asyncio
async def test_repeat_import_is_incremental_and_idempotent():
    item = measurement(1, 61.5, 9, SOURCE_OFFICIAL)
    snapshot = ProviderSnapshot(measurements={1: item}, history={1: (item, item)})
    provider = SimpleNamespace(async_fetch_history=lambda days: _async_value(snapshot))
    runtime = RuntimeData(official_provider=provider)
    calls = []
    entry = SimpleNamespace(entry_id="0123456789abcdef", options={})
    manager = HistorySyncManager(
        SimpleNamespace(),
        entry,
        runtime,
        importer=lambda hass, metadata, stats: calls.append((metadata, stats)),
    )

    first = await manager.async_sync(force=True)
    second = await manager.async_sync(force=True)

    assert first.records_seen == 1
    assert first.records_imported == 1
    assert first.records_skipped == 0
    assert second.records_seen == 1
    assert second.records_imported == 0
    assert second.records_skipped == 1
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_history_failure_isolated_and_redacted(caplog):
    async def fail(days):
        raise RuntimeError("synthetic private provider detail")

    runtime = RuntimeData(official_provider=SimpleNamespace(async_fetch_history=fail))
    manager = HistorySyncManager(
        SimpleNamespace(),
        SimpleNamespace(entry_id="0123456789abcdef", options={}),
        runtime,
        importer=lambda hass, metadata, stats: None,
    )
    status = await manager.async_sync(force=True)
    assert status.result == "failed"
    assert "synthetic private provider detail" not in caplog.text
    assert "history_source_failed" in caplog.text


@pytest.mark.asyncio
async def test_five_seen_import_failure_keeps_imported_zero_and_reports_stage(caplog):
    rows = tuple(measurement(1, 60.0 + index, index, SOURCE_OFFICIAL) for index in range(5))
    snapshot = ProviderSnapshot(measurements={1: rows[-1]}, history={1: rows})

    def fail_import(hass, metadata, stats):
        raise RuntimeError("synthetic private recorder detail")

    manager = HistorySyncManager(
        SimpleNamespace(),
        SimpleNamespace(entry_id="0123456789abcdef", options={}),
        RuntimeData(
            official_provider=SimpleNamespace(
                async_fetch_history=lambda days: _async_value(snapshot)
            )
        ),
        importer=fail_import,
    )
    status = await manager.async_sync(force=True)
    assert status.records_seen == 5
    assert status.records_imported == 0
    assert status.result == "failed"
    assert status.failure_stage == "recorder_import"
    assert status.error_id == "history_recorder_import_failed"
    assert status.error_type == "RuntimeError"
    assert "synthetic private recorder detail" not in caplog.text


async def _async_value(value):
    return value
