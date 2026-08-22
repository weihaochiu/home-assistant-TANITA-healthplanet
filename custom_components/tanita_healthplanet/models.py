"""Runtime models for the integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from .coordinator import HealthPlanetCoordinator


@dataclass(frozen=True)
class Measurement:
    metric_key: str
    value: float | int
    unit: str | None
    measured_at: datetime
    source: str
    model: str | None
    experimental: bool
    raw_kind: int


@dataclass(frozen=True)
class ProviderSnapshot:
    measurements: dict[int, Measurement | None]
    errors: dict[int, str] = field(default_factory=dict)


class HealthPlanetProvider(Protocol):
    provider_type: str

    async def async_fetch(self) -> ProviderSnapshot: ...

    async def async_close(self) -> None: ...


@dataclass
class RuntimeData:
    coordinator: HealthPlanetCoordinator
    provider: HealthPlanetProvider
