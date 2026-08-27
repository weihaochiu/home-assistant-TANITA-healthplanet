"""Offline parser for the confirmed HealthPlanet website graph response."""

from __future__ import annotations

import math
import re
from contextlib import suppress
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .const import JAPAN_TIMEZONE, KNOWN_SCHEMA_KEYS, METRICS, SOURCE
from .errors import (
    BackendCodeError,
    ExpiredSessionError,
    MalformedResponseError,
    SchemaDriftError,
    UnsupportedKindError,
)
from .models import Measurement, ParseResult

_SAFE_UNKNOWN_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_SENSITIVE_MARKERS = (
    "account",
    "authorization",
    "birth",
    "cookie",
    "email",
    "login",
    "mail",
    "name",
    "password",
    "serial",
    "session",
    "token",
    "user",
)
_LOCAL_FORMATS = (
    (re.compile(r"\d{8}"), "%Y%m%d"),
    (re.compile(r"\d{12}"), "%Y%m%d%H%M"),
    (re.compile(r"\d{14}"), "%Y%m%d%H%M%S"),
    (re.compile(r"\d{4}/\d{2}/\d{2}"), "%Y/%m/%d"),
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "%Y-%m-%d"),
    (re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}"), "%Y/%m/%d %H:%M"),
    (
        re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}"),
        "%Y/%m/%d %H:%M:%S",
    ),
    (
        re.compile(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}"),
        "%Y/%m/%d %H:%M:%S.%f",
    ),
    (re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}"), "%Y-%m-%d %H:%M"),
    (
        re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}"),
        "%Y-%m-%d %H:%M:%S",
    ),
    (
        re.compile(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{1,6}"),
        "%Y-%m-%d %H:%M:%S.%f",
    ),
)
_NUMERIC_EPOCH_STRING = re.compile(r"(?:\d{10}|\d{13})")


def _safe_unknown_fields(payload: dict[str, Any]) -> tuple[str, ...]:
    fields: list[str] = []
    for key in payload:
        if key in KNOWN_SCHEMA_KEYS or not isinstance(key, str):
            continue
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if _SAFE_UNKNOWN_KEY.fullmatch(key) and not any(
            marker in normalized for marker in _SENSITIVE_MARKERS
        ):
            fields.append(key)
    return tuple(sorted(fields))


def _single_code(payload: dict[str, Any]) -> Any:
    code = payload.get("code")
    if isinstance(code, list) and len(code) == 1:
        return code[0]
    return code


def _numeric(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        return value
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if candidate in {"", "-"}:
        return None
    try:
        parsed = float(candidate)
    except ValueError:
        return None
    if not math.isfinite(parsed):
        return None
    return int(parsed) if parsed.is_integer() and "." not in candidate else parsed


def _unix_datetime(value: int | float, timezone: ZoneInfo) -> datetime | None:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    absolute = abs(value)
    seconds: int | float
    if 1_000_000_000_000 <= absolute < 100_000_000_000_000:
        seconds = value / 1000
    elif 1_000_000_000 <= absolute < 100_000_000_000:
        seconds = value
    else:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=UTC).astimezone(timezone)
    except (OSError, OverflowError, ValueError):
        return None


def _datetime(value: Any, timezone: ZoneInfo) -> datetime | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int | float):
        return _unix_datetime(value, timezone)
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate == "-":
        return None
    for shape, format_string in _LOCAL_FORMATS:
        if shape.fullmatch(candidate) is None:
            continue
        try:
            return datetime.strptime(candidate, format_string).replace(tzinfo=timezone)
        except ValueError:
            continue
    parsed = None
    if not candidate.isdigit():
        normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        with suppress(ValueError):
            parsed = datetime.fromisoformat(normalized)
    if parsed is not None:
        return (
            parsed.replace(tzinfo=timezone)
            if parsed.tzinfo is None
            else parsed.astimezone(timezone)
        )
    if _NUMERIC_EPOCH_STRING.fullmatch(candidate):
        return _unix_datetime(int(candidate), timezone)
    return None


def _unit_from_payload(payload: dict[str, Any], confirmed: str | None) -> str | None:
    raw = payload.get("value1_unit")
    if isinstance(raw, list) and len(raw) == 1:
        raw = raw[0]
    if raw in {None, "", "-"}:
        return confirmed
    if not isinstance(raw, str) or len(raw) > 16:
        return confirmed
    return raw if raw == confirmed else confirmed


def _parse_row(row: Any, timezone: ZoneInfo) -> tuple[datetime, float | int] | None:
    if row is None or (isinstance(row, str) and row in {"", "-"}):
        return None
    if not isinstance(row, list | tuple) or len(row) != 2:
        raise SchemaDriftError("RECORD_SHAPE_CHANGED")
    if all(item is None or (isinstance(item, str) and item.strip() in {"", "-"}) for item in row):
        return None
    timestamps = [
        (index, parsed_timestamp)
        for index, item in enumerate(row)
        if (parsed_timestamp := _datetime(item, timezone)) is not None
    ]
    numerics = [
        (index, parsed_numeric)
        for index, item in enumerate(row)
        if (parsed_numeric := _numeric(item)) is not None
    ]
    assignments = [
        (measured_at, value)
        for timestamp_index, measured_at in timestamps
        for value_index, value in numerics
        if timestamp_index != value_index
    ]
    if len(assignments) == 1:
        return assignments[0]
    if len(assignments) > 1:
        raise SchemaDriftError("RECORD_TIMESTAMP_AMBIGUOUS")
    if not timestamps:
        raise SchemaDriftError("RECORD_TIMESTAMP_MISSING")
    timestamp_indexes = {index for index, _parsed in timestamps}
    counterpart_indexes = {1 - index for index in timestamp_indexes}
    if counterpart_indexes and all(
        row[index] is None or (isinstance(row[index], str) and row[index].strip() in {"", "-"})
        for index in counterpart_indexes
    ):
        return None
    raise SchemaDriftError("RECORD_FIELDS_INVALID")


def parse_graph_payload(
    payload: Any,
    kind: int,
    *,
    timezone_name: str = JAPAN_TIMEZONE,
    model: str | None = None,
) -> ParseResult:
    """Parse one confirmed graph kind without depending on a real account."""
    definition = METRICS.get(kind)
    if definition is None:
        raise UnsupportedKindError("UNSUPPORTED_KIND")
    if isinstance(payload, str) and "<html" in payload.casefold():
        raise ExpiredSessionError("HTML_LOGIN_OR_EXPIRED_SESSION")
    if not isinstance(payload, dict):
        raise MalformedResponseError("MALFORMED_RESPONSE")
    code = _single_code(payload)
    if code == -1:
        raise BackendCodeError("BACKEND_CODE_MINUS_ONE")
    if code not in {0, None}:
        raise BackendCodeError("BACKEND_CODE_UNSUPPORTED")
    rows = payload.get("value1")
    if rows is None:
        raise SchemaDriftError("VALUE_CONTAINER_MISSING")
    if not isinstance(rows, list):
        raise SchemaDriftError("VALUE_CONTAINER_INVALID")
    timezone = ZoneInfo(timezone_name)
    unit = _unit_from_payload(payload, definition.unit)
    measurements: list[Measurement] = []
    skipped = 0
    for row in rows:
        parsed = _parse_row(row, timezone)
        if parsed is None:
            skipped += 1
            continue
        measured_at, value = parsed
        measurements.append(
            Measurement(
                metric_key=definition.key,
                value=value,
                unit=unit,
                measured_at=measured_at,
                source=SOURCE,
                model=model,
                experimental=True,
                raw_kind=kind,
            )
        )
    measurements.sort(key=lambda item: item.measured_at)
    return ParseResult(
        measurements=tuple(measurements),
        unknown_fields=_safe_unknown_fields(payload),
        skipped_records=skipped,
    )


def select_newest(result: ParseResult) -> Measurement | None:
    return result.measurements[-1] if result.measurements else None
