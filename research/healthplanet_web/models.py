"""Typed models returned by the experimental parser."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


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
class ParseResult:
    measurements: tuple[Measurement, ...]
    unknown_fields: tuple[str, ...]
    skipped_records: int
