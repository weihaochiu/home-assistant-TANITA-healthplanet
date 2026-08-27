"""Privacy-safe, hourly Recorder statistics synchronization."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from statistics import fmean

from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_HISTORY_SYNC_ENABLED,
    CONF_OFFICIAL_HISTORY_DAYS,
    DEFAULT_HISTORY_SYNC_ENABLED,
    DEFAULT_OFFICIAL_HISTORY_DAYS,
    DOMAIN,
    HISTORY_SYNC_INTERVAL,
    METRICS,
)
from .models import Measurement, ProviderSnapshot, RuntimeData

_LOGGER = logging.getLogger(__package__)

_UNIT_CLASS_BY_KIND: dict[int, str | None] = {
    1: "mass",
    2: None,
    3: "mass",
    4: None,
    5: "energy",
    6: "mass",
    7: "mass",
    14: "duration",
    22: None,
    23: None,
    101: "pressure",
    102: "pressure",
    103: None,
}


@dataclass(frozen=True)
class HistorySyncStatus:
    """Non-sensitive status safe for diagnostics and entity attributes."""

    last_history_sync: datetime | None = None
    result: str = "never"
    records_seen: int = 0
    records_imported: int = 0
    records_skipped: int = 0


def _identity(measurement: Measurement) -> tuple[int, datetime, str]:
    return (measurement.raw_kind, measurement.measured_at, measurement.source)


def _hour(measured_at: datetime) -> datetime:
    return measured_at.astimezone(UTC).replace(minute=0, second=0, microsecond=0)


def _deduplicated(history: Iterable[Measurement]) -> tuple[Measurement, ...]:
    unique = {_identity(item): item for item in history}
    return tuple(sorted(unique.values(), key=lambda item: item.measured_at))


def hourly_statistics(history: Iterable[Measurement]) -> list[StatisticData]:
    """Aggregate exact provider timestamps into HA-supported hourly statistics."""
    buckets: dict[datetime, list[float]] = defaultdict(list)
    for measurement in _deduplicated(history):
        buckets[_hour(measurement.measured_at)].append(float(measurement.value))
    return [
        StatisticData(
            start=start,
            mean=fmean(values),
            min=min(values),
            max=max(values),
        )
        for start, values in sorted(buckets.items())
    ]


def statistic_metadata(entry_id: str, kind: int) -> StatisticMetaData:
    """Build the explicit HA 2026.8+/2026.11-safe metadata shape."""
    metric = METRICS[kind]
    return StatisticMetaData(
        has_sum=False,
        mean_type=StatisticMeanType.ARITHMETIC,
        name=f"HealthPlanet {metric.key}",
        source=DOMAIN,
        statistic_id=f"{DOMAIN}:{entry_id}_{kind}",
        unit_class=_UNIT_CLASS_BY_KIND[kind],
        unit_of_measurement=metric.unit,
    )


class HistorySyncManager:
    """Synchronize provider history independently from live coordinators."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        runtime: RuntimeData,
        *,
        importer: Callable[
            [HomeAssistant, StatisticMetaData, list[StatisticData]], None
        ] = async_add_external_statistics,
    ) -> None:
        self.hass = hass
        self.entry = entry
        self.runtime = runtime
        self.status = HistorySyncStatus()
        self._importer = importer
        self._lock = asyncio.Lock()
        self._known: dict[tuple[int, datetime, str], Measurement] = {}

    def _enabled(self) -> bool:
        return bool(self.entry.options.get(CONF_HISTORY_SYNC_ENABLED, DEFAULT_HISTORY_SYNC_ENABLED))

    def _due(self) -> bool:
        last = self.status.last_history_sync
        return last is None or datetime.now(UTC) - last >= HISTORY_SYNC_INTERVAL

    async def _async_snapshots(self, *, refetch: bool) -> tuple[list[ProviderSnapshot], int]:
        snapshots: list[ProviderSnapshot] = []
        failures = 0
        official = self.runtime.official_provider
        if official is not None:
            try:
                fetch_history = getattr(official, "async_fetch_history", None)
                if callable(fetch_history):
                    days = int(
                        self.entry.options.get(
                            CONF_OFFICIAL_HISTORY_DAYS, DEFAULT_OFFICIAL_HISTORY_DAYS
                        )
                    )
                    snapshots.append(await fetch_history(days))
                elif self.runtime.official_coordinator is not None:
                    snapshot = self.runtime.official_coordinator.data
                    if snapshot is not None:
                        snapshots.append(snapshot)
            except Exception:
                failures += 1
                _LOGGER.warning(
                    "HealthPlanet history source failed: source=official_api "
                    "error_id=history_source_failed"
                )
        website = self.runtime.website_provider
        website_coordinator = self.runtime.website_coordinator
        try:
            if website is not None and refetch:
                snapshots.append(await website.async_fetch())
            elif website_coordinator is not None and website_coordinator.data is not None:
                snapshots.append(website_coordinator.data)
        except Exception:
            failures += 1
            _LOGGER.warning(
                "HealthPlanet history source failed: source=experimental_website "
                "error_id=history_source_failed"
            )
        return snapshots, failures

    async def async_sync(self, *, force: bool = False) -> HistorySyncStatus:
        """Fetch and queue missing hourly statistics without affecting live sensors."""
        if not force and (not self._enabled() or not self._due()):
            return self.status
        async with self._lock:
            if not force and (not self._enabled() or not self._due()):
                return self.status
            started = datetime.now(UTC)
            seen = imported = skipped = 0
            try:
                snapshots, failures = await self._async_snapshots(refetch=force)
                combined: dict[int, list[Measurement]] = defaultdict(list)
                for snapshot in snapshots:
                    for kind, snapshot_measurements in snapshot.history.items():
                        combined[kind].extend(snapshot_measurements)
                for kind, combined_measurements in combined.items():
                    deduplicated = _deduplicated(combined_measurements)
                    seen += len(deduplicated)
                    new = [item for item in deduplicated if _identity(item) not in self._known]
                    skipped += len(deduplicated) - len(new)
                    if not new:
                        continue
                    affected_hours = {_hour(item.measured_at) for item in new}
                    candidate_known = dict(self._known)
                    candidate_known.update({_identity(item): item for item in new})
                    affected = [
                        item
                        for item in candidate_known.values()
                        if item.raw_kind == kind and _hour(item.measured_at) in affected_hours
                    ]
                    self._importer(
                        self.hass,
                        statistic_metadata(self.entry.entry_id, kind),
                        hourly_statistics(affected),
                    )
                    self._known.update({_identity(item): item for item in new})
                    imported += len(new)
            except Exception:
                _LOGGER.warning("HealthPlanet history sync failed: error_id=history_sync_failed")
                result = "failed"
            else:
                result = (
                    "partial" if failures and snapshots else "failed" if failures else "success"
                )
                if result == "failed":
                    _LOGGER.warning(
                        "HealthPlanet history sync failed: error_id=history_sync_failed"
                    )
            self.status = HistorySyncStatus(
                last_history_sync=started,
                result=result,
                records_seen=seen,
                records_imported=imported,
                records_skipped=skipped,
            )
            return self.status

    async def async_maybe_sync(self) -> None:
        """Run a due incremental sync as a separate failure domain."""
        await self.async_sync(force=False)
