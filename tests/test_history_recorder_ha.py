from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from homeassistant.components.recorder import get_instance, statistics
from pytest_homeassistant_custom_component.components.recorder.common import (
    async_recorder_block_till_done,
)

from custom_components.tanita_healthplanet.const import SOURCE_WEBSITE
from custom_components.tanita_healthplanet.history import HistorySyncManager
from custom_components.tanita_healthplanet.models import Measurement, ProviderSnapshot, RuntimeData


async def test_v021_five_row_signature_against_real_recorder(recorder_mock, hass):
    start = datetime(2026, 8, 1, 3, tzinfo=UTC)
    rows = tuple(
        Measurement(
            metric_key="weight",
            value=60.0 + index,
            unit="kg",
            measured_at=start + timedelta(hours=index),
            source=SOURCE_WEBSITE,
            model=None,
            experimental=True,
            raw_kind=1,
        )
        for index in range(5)
    )
    snapshot = ProviderSnapshot(measurements={1: rows[-1]}, history={1: rows})

    async def fetch():
        return snapshot

    manager = HistorySyncManager(
        hass,
        SimpleNamespace(entry_id="0123456789abcdef", options={}),
        RuntimeData(website_provider=SimpleNamespace(async_fetch=fetch)),
    )

    status = await manager.async_sync(force=True)
    await async_recorder_block_till_done(hass)
    statistic_id = "tanita_healthplanet:0123456789abcdef_1"
    result = await get_instance(hass).async_add_executor_job(
        statistics.statistics_during_period,
        hass,
        start,
        start + timedelta(hours=6),
        {statistic_id},
        "hour",
        None,
        {"mean", "min", "max"},
    )

    assert status.records_seen == 5
    assert status.records_imported == 5
    assert status.result == "success"
    assert len(result[statistic_id]) == 5

    second = await manager.async_sync(force=True)
    assert second.records_imported == 0
    assert second.records_skipped == 5

    restarted_manager = HistorySyncManager(
        hass,
        SimpleNamespace(entry_id="0123456789abcdef", options={}),
        RuntimeData(website_provider=SimpleNamespace(async_fetch=fetch)),
    )
    restarted = await restarted_manager.async_sync(force=True)
    await async_recorder_block_till_done(hass)
    repeated = await get_instance(hass).async_add_executor_job(
        statistics.statistics_during_period,
        hass,
        start,
        start + timedelta(hours=6),
        {statistic_id},
        "hour",
        None,
        {"mean", "min", "max"},
    )
    assert restarted.records_imported == 5
    assert len(repeated[statistic_id]) == 5
    assert [row["mean"] for row in repeated[statistic_id]] == [60, 61, 62, 63, 64]
