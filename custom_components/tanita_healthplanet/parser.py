"""Production parsers for official and experimental HealthPlanet schemas."""

from __future__ import annotations

import math
import re
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .const import (
    JST_TIMEZONE,
    METRICS,
    OFFICIAL_TAG_BODY_FAT,
    OFFICIAL_TAG_DIASTOLIC,
    OFFICIAL_TAG_PULSE,
    OFFICIAL_TAG_SYSTOLIC,
    OFFICIAL_TAG_WEIGHT,
    SOURCE_OFFICIAL,
)
from .errors import HealthPlanetBackendCodeError, HealthPlanetSchemaError
from .models import Measurement

_JST = ZoneInfo(JST_TIMEZONE)
_WEBSITE_TIMESTAMP_FORMATS = (
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
_SAFE_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]{0,63}$")
_SENSITIVE_KEY_MARKERS = (
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


def _safe_unknown_fields(payload: dict[str, Any], known: set[str]) -> tuple[str, ...]:
    result: list[str] = []
    for key in payload:
        if key in known or not isinstance(key, str) or not _SAFE_KEY.fullmatch(key):
            continue
        normalized = re.sub(r"[^a-z0-9]", "", key.casefold())
        if not any(marker in normalized for marker in _SENSITIVE_KEY_MARKERS):
            result.append(key)
    return tuple(sorted(result))


def _numeric(value: Any) -> float | int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
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


def _parse_unix_timestamp(value: int | float) -> datetime | None:
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
        return datetime.fromtimestamp(seconds, tz=UTC)
    except (OSError, OverflowError, ValueError):
        return None


def parse_jst_timestamp(value: Any) -> datetime | None:
    """Parse a website or official timestamp as JST and return UTC."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return _parse_unix_timestamp(value)
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate == "-":
        return None
    # Calendar-shaped digit strings must be resolved before numeric epoch
    # strings so compact local datetimes can never be interpreted as Unix time.
    for shape, format_string in _WEBSITE_TIMESTAMP_FORMATS:
        if shape.fullmatch(candidate) is None:
            continue
        try:
            return datetime.strptime(candidate, format_string).replace(tzinfo=_JST).astimezone(UTC)
        except ValueError:
            continue
    parsed = None
    if not candidate.isdigit():
        normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
        with suppress(ValueError):
            parsed = datetime.fromisoformat(normalized)
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_JST)
        return parsed.astimezone(UTC)
    if _NUMERIC_EPOCH_STRING.fullmatch(candidate):
        return _parse_unix_timestamp(int(candidate))
    return None


def _single_code(payload: dict[str, Any]) -> Any:
    code = payload.get("code")
    if isinstance(code, list) and len(code) == 1:
        return code[0]
    return code


@dataclass(frozen=True)
class WebsiteParseResult:
    """Parsed measurements plus privacy-safe structural metadata."""

    measurements: tuple[Measurement, ...]
    row_count: int
    timestamp_parsing_success: bool | None


_WEB_KNOWN_KEYS = {
    "barMargin",
    "barWidth",
    "code",
    "formatString",
    "from_date",
    "markerSize",
    "numberTicks",
    "tickInset",
    "tickInterval",
    "to_date",
    "value1",
    "value1_formatString",
    "value1_max",
    "value1_min",
    "value1_name",
    "value1_unit",
}


def _missing(value: Any) -> bool:
    return value is None or (isinstance(value, str) and value.strip() in {"", "-"})


def _field_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list | tuple):
        return "array"
    if isinstance(value, dict):
        return "object"
    return "other"


def _row_schema_error(
    error_id: str,
    row: Any,
    *,
    timestamp_candidate_count: int | None = None,
    numeric_candidate_count: int | None = None,
    valid_assignment_count: int | None = None,
) -> HealthPlanetSchemaError:
    fields = row if isinstance(row, list | tuple) else (row,)
    return HealthPlanetSchemaError(
        error_id,
        row_length=len(row) if isinstance(row, list | tuple) else None,
        timestamp_candidate_count=timestamp_candidate_count,
        numeric_candidate_count=numeric_candidate_count,
        valid_assignment_count=valid_assignment_count,
        field_type_shape=tuple(_field_type(field) for field in fields),
    )


def _parse_website_row(row: Any) -> tuple[datetime, float | int] | None:
    """Return the only valid timestamp/value role assignment for one row."""
    if _missing(row):
        return None
    if not isinstance(row, list) or len(row) != 2:
        raise _row_schema_error("website_record_shape_changed", row)
    if all(_missing(item) for item in row):
        return None

    timestamps = [
        (index, parsed_timestamp)
        for index, item in enumerate(row)
        if (parsed_timestamp := parse_jst_timestamp(item)) is not None
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
    metadata = {
        "timestamp_candidate_count": len(timestamps),
        "numeric_candidate_count": len(numerics),
        "valid_assignment_count": len(assignments),
    }
    if len(assignments) == 1:
        return assignments[0]
    if len(assignments) > 1:
        raise _row_schema_error("website_record_timestamp_ambiguous", row, **metadata)
    if not timestamps:
        raise _row_schema_error("website_record_timestamp_missing", row, **metadata)

    timestamp_indexes = {index for index, _parsed in timestamps}
    counterpart_indexes = {1 - index for index in timestamp_indexes}
    if counterpart_indexes and all(_missing(row[index]) for index in counterpart_indexes):
        return None
    raise _row_schema_error("website_record_fields_invalid", row, **metadata)


def parse_website_payload_result(payload: Any, kind: int) -> WebsiteParseResult:
    """Parse a two-field number/timestamp row by its confirmed field types."""
    description = METRICS.get(kind)
    if description is None:
        raise HealthPlanetSchemaError("unsupported_metric_kind")
    if not isinstance(payload, dict):
        raise HealthPlanetSchemaError("website_response_not_object")
    code = _single_code(payload)
    if code == -1:
        raise HealthPlanetBackendCodeError("website_backend_code_minus_one", -1)
    if code != 0:
        safe_code = code if isinstance(code, int) and not isinstance(code, bool) else None
        raise HealthPlanetBackendCodeError("website_backend_code_unsupported", safe_code)
    rows = payload.get("value1")
    if not isinstance(rows, list):
        raise HealthPlanetSchemaError(
            "website_value_container_invalid",
            _safe_unknown_fields(payload, _WEB_KNOWN_KEYS),
        )
    measurements: list[Measurement] = []
    timestamp_attempted = False
    for row in rows:
        if not _missing(row):
            timestamp_attempted = True
        parsed_row = _parse_website_row(row)
        if parsed_row is None:
            continue
        measured_at, value = parsed_row
        measurements.append(
            Measurement(
                metric_key=description.key,
                value=value,
                unit=description.unit,
                measured_at=measured_at,
                source="healthplanet_website",
                model=None,
                experimental=True,
                raw_kind=kind,
            )
        )
    measurements.sort(key=lambda item: item.measured_at)
    return WebsiteParseResult(
        measurements=tuple(measurements),
        row_count=len(rows),
        timestamp_parsing_success=True if timestamp_attempted else None,
    )


def parse_website_payload(payload: Any, kind: int) -> list[Measurement]:
    """Return production measurements while retaining the public parser API."""
    return list(parse_website_payload_result(payload, kind).measurements)


_OFFICIAL_TAG_KIND = {OFFICIAL_TAG_WEIGHT: 1, OFFICIAL_TAG_BODY_FAT: 2}
_OFFICIAL_KNOWN_KEYS = {"birth_date", "data", "height", "sex"}


@dataclass(frozen=True)
class OfficialParseResult:
    """Official measurements plus privacy-safe structural metadata."""

    measurements: dict[int, Measurement | None]
    record_count: int
    available_tags: tuple[str, ...]
    unavailable_tags: tuple[str, ...]
    complete_pair_found: bool | None = None


def _official_records(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        raise HealthPlanetSchemaError("official_response_not_object")
    data = payload.get("data", [])
    if isinstance(data, dict):
        records = [data]
    elif isinstance(data, list):
        records = data
    else:
        raise HealthPlanetSchemaError(
            "official_data_container_invalid",
            _safe_unknown_fields(payload, _OFFICIAL_KNOWN_KEYS),
        )
    if not all(isinstance(record, dict) for record in records):
        raise HealthPlanetSchemaError("official_record_not_object")
    return records


def _official_measurement(
    record: dict[str, Any], *, kind: int, measured_at: datetime, value: float | int
) -> Measurement:
    model = record.get("model")
    if not isinstance(model, str) or len(model) > 32:
        model = None
    description = METRICS[kind]
    return Measurement(
        metric_key=description.key,
        value=value,
        unit=description.unit,
        measured_at=measured_at,
        source=SOURCE_OFFICIAL,
        model=model,
        experimental=False,
        raw_kind=kind,
    )


def parse_official_innerscan_payload(payload: Any) -> OfficialParseResult:
    """Parse documented innerscan records and select each tag's latest valid row."""
    records = _official_records(payload)
    candidates: dict[int, list[Measurement]] = {1: [], 2: []}
    for record in records:
        tag = record.get("tag")
        kind = _OFFICIAL_TAG_KIND.get(str(tag))
        if kind is None:
            continue
        raw_value = record.get("keydata")
        raw_date = record.get("date")
        if _missing(raw_value) or _missing(raw_date):
            continue
        value = _numeric(raw_value)
        measured_at = parse_jst_timestamp(raw_date)
        if value is None:
            raise HealthPlanetSchemaError("official_record_value_invalid")
        if measured_at is None:
            raise HealthPlanetSchemaError("official_record_date_invalid")
        candidates[kind].append(
            _official_measurement(record, kind=kind, measured_at=measured_at, value=value)
        )
    measurements = {
        kind: max(values, key=lambda item: item.measured_at) if values else None
        for kind, values in candidates.items()
    }
    available = tuple(
        METRICS[kind].official_tag or "" for kind in (1, 2) if measurements[kind] is not None
    )
    unavailable = tuple(
        METRICS[kind].official_tag or "" for kind in (1, 2) if measurements[kind] is None
    )
    return OfficialParseResult(
        measurements=measurements,
        record_count=len(records),
        available_tags=available,
        unavailable_tags=unavailable,
    )


_SPHYGMO_TAG_KIND = {
    OFFICIAL_TAG_SYSTOLIC: 101,
    OFFICIAL_TAG_DIASTOLIC: 102,
    OFFICIAL_TAG_PULSE: 103,
}


def parse_official_sphygmomanometer_payload(payload: Any) -> OfficialParseResult:
    """Select the latest complete blood-pressure pair and co-timed pulse."""
    records = _official_records(payload)
    grouped: dict[datetime, dict[int, Measurement]] = {}
    for record in records:
        kind = _SPHYGMO_TAG_KIND.get(str(record.get("tag")))
        if kind is None:
            continue
        raw_value = record.get("keydata")
        raw_date = record.get("date")
        if _missing(raw_value) or _missing(raw_date):
            continue
        value = _numeric(raw_value)
        measured_at = parse_jst_timestamp(raw_date)
        if value is None:
            raise HealthPlanetSchemaError("official_record_value_invalid")
        if measured_at is None:
            raise HealthPlanetSchemaError("official_record_date_invalid")
        # If duplicate tags exist at one timestamp, retaining the last row is
        # deterministic and never mixes measurements across timestamps.
        grouped.setdefault(measured_at, {})[kind] = _official_measurement(
            record, kind=kind, measured_at=measured_at, value=value
        )

    complete_times = [
        measured_at
        for measured_at, measurements in grouped.items()
        if 101 in measurements and 102 in measurements
    ]
    selected = grouped[max(complete_times)] if complete_times else {}
    measurements = {kind: selected.get(kind) for kind in (101, 102, 103)}
    available = tuple(
        METRICS[kind].official_tag or ""
        for kind in (101, 102, 103)
        if measurements[kind] is not None
    )
    unavailable = tuple(
        METRICS[kind].official_tag or "" for kind in (101, 102, 103) if measurements[kind] is None
    )
    return OfficialParseResult(
        measurements=measurements,
        record_count=len(records),
        available_tags=available,
        unavailable_tags=unavailable,
        complete_pair_found=bool(complete_times),
    )


def parse_official_payload(payload: Any) -> dict[int, list[Measurement]]:
    """Compatibility wrapper for the original innerscan parser API."""
    parsed = parse_official_innerscan_payload(payload)
    return {
        kind: [measurement] if measurement is not None else []
        for kind, measurement in parsed.measurements.items()
    }
