"""Runtime models for the integration."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from .coordinator import OfficialCoordinator, WebsiteCoordinator


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
EndpointOutcome = Literal[
    "available", "null", "auth_error", "http_error", "parser_error", "rate_limited"
]


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
    row_length: int | None = None
    timestamp_candidate_count: int | None = None
    numeric_candidate_count: int | None = None
    valid_assignment_count: int | None = None
    field_type_shape: tuple[str, ...] = ()


@dataclass(frozen=True)
class EndpointStatus:
    """Privacy-safe structural result for one official endpoint."""

    outcome: EndpointOutcome
    http_status: int | None = None
    record_count: int = 0
    available_tags: tuple[str, ...] = ()
    unavailable_tags: tuple[str, ...] = ()
    error_id: str | None = None
    complete_pair_found: bool | None = None


@dataclass(frozen=True)
class ProviderSnapshot:
    measurements: dict[int, Measurement | None]
    errors: dict[int, str] = field(default_factory=dict)
    kind_statuses: dict[int, KindStatus] = field(default_factory=dict)
    endpoint_statuses: dict[str, EndpointStatus] = field(default_factory=dict)


class HealthPlanetProvider(Protocol):
    provider_type: str

    async def async_fetch(self) -> ProviderSnapshot: ...

    async def async_close(self) -> None: ...


@dataclass
class RuntimeData:
    official_coordinator: OfficialCoordinator | None = None
    website_coordinator: WebsiteCoordinator | None = None
    official_provider: HealthPlanetProvider | None = None
    website_provider: HealthPlanetProvider | None = None

    @property
    def coordinator(self) -> OfficialCoordinator | WebsiteCoordinator:
        """Compatibility accessor for single-source entries."""
        coordinator = self.official_coordinator or self.website_coordinator
        if coordinator is None:
            raise RuntimeError("healthplanet_runtime_has_no_coordinator")
        return coordinator

    @property
    def provider(self) -> HealthPlanetProvider:
        """Compatibility accessor for single-source entries."""
        provider = self.official_provider or self.website_provider
        if provider is None:
            raise RuntimeError("healthplanet_runtime_has_no_provider")
        return provider

    @property
    def coordinators(self) -> tuple[OfficialCoordinator | WebsiteCoordinator, ...]:
        return tuple(
            coordinator
            for coordinator in (self.official_coordinator, self.website_coordinator)
            if coordinator is not None
        )

    @property
    def providers(self) -> tuple[HealthPlanetProvider, ...]:
        return tuple(
            provider
            for provider in (self.official_provider, self.website_provider)
            if provider is not None
        )
