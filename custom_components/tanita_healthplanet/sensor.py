"""HealthPlanet measurement sensors."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, UnitOfMass, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import HealthPlanetConfigEntry
from .const import DOMAIN, METRICS, OFFICIAL_KINDS, PROVIDER_OFFICIAL
from .coordinator import HealthPlanetCoordinator
from .models import Measurement, ProviderSnapshot


@dataclass(frozen=True, kw_only=True)
class HealthPlanetSensorDescription(SensorEntityDescription):
    kind: int
    medium_confidence: bool = False


def _description(kind: int) -> HealthPlanetSensorDescription:
    metric = METRICS[kind]
    device_class = None
    unit = metric.unit
    if kind in {1, 3, 6, 7}:
        device_class = SensorDeviceClass.WEIGHT
        unit = UnitOfMass.KILOGRAMS
    elif kind in {2, 22}:
        unit = PERCENTAGE
    elif kind == 14:
        unit = UnitOfTime.YEARS
    return HealthPlanetSensorDescription(
        key=metric.key,
        translation_key=metric.translation_key,
        kind=kind,
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
    """Set up sensors for exactly one provider on this entry."""
    coordinator: HealthPlanetCoordinator = entry.runtime_data.coordinator
    kinds = OFFICIAL_KINDS if entry.data["provider"] == PROVIDER_OFFICIAL else tuple(METRICS)
    async_add_entities(HealthPlanetSensor(coordinator, entry, _description(kind)) for kind in kinds)


class HealthPlanetSensor(CoordinatorEntity[HealthPlanetCoordinator], SensorEntity):
    """One isolated metric sensor."""

    entity_description: HealthPlanetSensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: HealthPlanetCoordinator,
        entry: HealthPlanetConfigEntry,
        description: HealthPlanetSensorDescription,
    ) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.kind}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="TANITA",
            model=(
                "HealthPlanet Official API"
                if entry.data["provider"] == PROVIDER_OFFICIAL
                else "HealthPlanet Experimental Website"
            ),
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
