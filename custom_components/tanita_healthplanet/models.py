"""Runtime models for the integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

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


KindOutcome = Literal[
    "available",
    "null",
    "backend_error",
    "auth_error",
    "http_error",
    "html",
    "parser_error",
]
ContentCategory = Literal["json", "html", "other"]


@dataclass(frozen=True)
class KindStatus:
    """Privacy-safe structural result for one website kind."""

    kind: int
    outcome: KindOutcome
    http_status: int | None = None
    content_category: ContentCategory = "other"
    backend_code: int | None = None
    error_id: str | None = None
    row_count: int | None = None
    timestamp_parsing_success: bool | None = None


@dataclass(frozen=True)
class ProviderSnapshot:
    measurements: dict[int, Measurement | None]
    errors: dict[int, str] = field(default_factory=dict)
    kind_statuses: dict[int, KindStatus] = field(default_factory=dict)


class HealthPlanetProvider(Protocol):
    provider_type: str

    async def async_fetch(self) -> ProviderSnapshot: ...

    async def async_close(self) -> None: ...


@dataclass
class RuntimeData:
    coordinator: HealthPlanetCoordinator
    provider: HealthPlanetProvider
