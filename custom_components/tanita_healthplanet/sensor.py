"""HealthPlanet measurement sensors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import (
    PERCENTAGE,
    UnitOfEnergy,
    UnitOfMass,
    UnitOfPressure,
    UnitOfTime,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HealthPlanetConfigEntry, _entry_mode
from .const import (
    DOMAIN,
    METRICS,
    MODE_HYBRID,
    MODE_OFFICIAL_ONLY,
    MODE_WEBSITE_ONLY,
    OFFICIAL_KINDS,
    SOURCE_OFFICIAL,
    SOURCE_WEBSITE,
    WEBSITE_HYBRID_KINDS,
    WEBSITE_KINDS,
)
from .coordinator import SourceCoordinator
from .models import Measurement, ProviderSnapshot


@dataclass(frozen=True, kw_only=True)
class HealthPlanetSensorDescription(SensorEntityDescription):
    kind: int
    data_source: str
    medium_confidence: bool = False


def _description(kind: int, source: str) -> HealthPlanetSensorDescription:
    metric = METRICS[kind]
    device_class = None
    unit: Any = metric.unit
    if kind in {1, 3, 6, 7}:
        device_class = SensorDeviceClass.WEIGHT
        unit = UnitOfMass.KILOGRAMS
    elif kind in {2, 22}:
        unit = PERCENTAGE
    elif kind == 5:
        unit = UnitOfEnergy.KILO_CALORIE
    elif kind == 14:
        unit = UnitOfTime.YEARS
    elif kind in {101, 102}:
        # HA Core 2026.8.2 includes mmHg in UnitOfPressure and permits it
        # with the generic pressure device class.
        device_class = SensorDeviceClass.PRESSURE
        unit = UnitOfPressure.MMHG
    # HA Core 2026.8.2 has no semantically correct pulse/heart-rate
    # device class, so kind 103 intentionally keeps only bpm.
    return HealthPlanetSensorDescription(
        key=metric.key,
        translation_key=metric.translation_key,
        kind=kind,
        data_source=source,
        device_class=device_class,
        native_unit_of_measurement=unit,
        state_class=SensorStateClass.MEASUREMENT,
        medium_confidence=metric.medium_confidence,
    )


async def async_setup_entry(
    hass: HomeAssistant,
    entry: HealthPlanetConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up entities bound only to their own source coordinator."""
    mode = _entry_mode(dict(entry.data))
    runtime = entry.runtime_data
    entities: list[HealthPlanetSensor] = []

    official_coordinator = getattr(runtime, "official_coordinator", None)
    website_coordinator = getattr(runtime, "website_coordinator", None)
    # Compatibility for pre-hybrid tests and already constructed runtimes.
    legacy_coordinator = getattr(runtime, "coordinator", None)
    if mode == MODE_OFFICIAL_ONLY and official_coordinator is None:
        official_coordinator = legacy_coordinator
    if mode == MODE_WEBSITE_ONLY and website_coordinator is None:
        website_coordinator = legacy_coordinator

    if mode in {MODE_HYBRID, MODE_OFFICIAL_ONLY} and official_coordinator is not None:
        entities.extend(
            HealthPlanetSensor(
                official_coordinator,
                entry,
                _description(kind, SOURCE_OFFICIAL),
                mode,
            )
            for kind in OFFICIAL_KINDS
        )
    if mode in {MODE_HYBRID, MODE_WEBSITE_ONLY} and website_coordinator is not None:
        kinds = WEBSITE_HYBRID_KINDS if mode == MODE_HYBRID else WEBSITE_KINDS
        entities.extend(
            HealthPlanetSensor(
                website_coordinator,
                entry,
                _description(kind, SOURCE_WEBSITE),
                mode,
            )
            for kind in kinds
        )
    async_add_entities(entities)


class HealthPlanetSensor(CoordinatorEntity[SourceCoordinator], SensorEntity):
    """One source-owned metric sensor."""

    entity_description: HealthPlanetSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: SourceCoordinator,
        entry: HealthPlanetConfigEntry,
        description: HealthPlanetSensorDescription,
        mode: str,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        # Metric IDs 1/2 intentionally remain identical between official and
        # website-only modes. Hybrid never creates website kinds 1/2.
        self._attr_unique_id = f"{entry.entry_id}_{description.kind}"
        model = {
            MODE_HYBRID: "HealthPlanet Official-first Hybrid",
            MODE_OFFICIAL_ONLY: "HealthPlanet Official API",
            MODE_WEBSITE_ONLY: "HealthPlanet Experimental Website",
        }[mode]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="TANITA",
            model=model,
        )

    @property
    def _measurement(self) -> Measurement | None:
        data: ProviderSnapshot | None = self.coordinator.data
        if data is None:
            return None
        return data.measurements.get(self.entity_description.kind)

    @property
    def available(self) -> bool:
        return super().available and self._measurement is not None

    @property
    def native_value(self) -> float | int | None:
        measurement = self._measurement
        return measurement.value if measurement is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, str]:
        """Expose only the non-sensitive source label."""
        return {"data_source": self.entity_description.data_source}
