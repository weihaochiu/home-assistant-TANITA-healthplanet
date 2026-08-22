"""Production parsers for official and experimental HealthPlanet schemas."""

from __future__ import annotations

import math
import re
from datetime import UTC, datetime
from typing import Any
from zoneinfo import ZoneInfo

from .const import JST_TIMEZONE, METRICS, OFFICIAL_TAG_BODY_FAT, OFFICIAL_TAG_WEIGHT
from .errors import HealthPlanetBackendCodeError, HealthPlanetSchemaError
from .models import Measurement

_JST = ZoneInfo(JST_TIMEZONE)
_WEBSITE_TIMESTAMP_FORMATS = (
    "%Y%m%d%H%M",
    "%Y%m%d%H%M%S",
    "%Y/%m/%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d %H:%M:%S",
)
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


def parse_jst_timestamp(value: Any) -> datetime | None:
    """Parse a website or official timestamp as JST and return UTC."""
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or candidate == "-":
        return None
    normalized = candidate[:-1] + "+00:00" if candidate.endswith("Z") else candidate
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=_JST)
        return parsed.astimezone(UTC)
    for format_string in _WEBSITE_TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(candidate, format_string).replace(tzinfo=_JST).astimezone(UTC)
        except ValueError:
            continue
    return None


def _single_code(payload: dict[str, Any]) -> Any:
    code = payload.get("code")
    if isinstance(code, list) and len(code) == 1:
        return code[0]
    return code


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


def parse_website_payload(payload: Any, kind: int) -> list[Measurement]:
    """Parse the confirmed positional website schema without guessing fields."""
    description = METRICS.get(kind)
    if description is None:
        raise HealthPlanetSchemaError("unsupported_metric_kind")
    if not isinstance(payload, dict):
        raise HealthPlanetSchemaError("website_response_not_object")
    code = _single_code(payload)
    if code == -1:
        raise HealthPlanetBackendCodeError("website_backend_code_minus_one")
    if code != 0:
        raise HealthPlanetBackendCodeError("website_backend_code_unsupported")
    rows = payload.get("value1")
    if not isinstance(rows, list):
        raise HealthPlanetSchemaError(
            "website_value_container_invalid",
            _safe_unknown_fields(payload, _WEB_KNOWN_KEYS),
        )
    measurements: list[Measurement] = []
    for row in rows:
        if row is None:
            continue
        if not isinstance(row, list) or len(row) != 2:
            raise HealthPlanetSchemaError("website_record_shape_changed")
        # Authorized research confirmed value1 rows are [numeric value, JST string].
        value = _numeric(row[0])
        measured_at = parse_jst_timestamp(row[1])
        raw_value = row[0]
        if value is None and (
            raw_value is None or (isinstance(raw_value, str) and raw_value.strip() in {"", "-"})
        ):
            continue
        if value is None or measured_at is None:
            raise HealthPlanetSchemaError("website_record_fields_invalid")
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
    return sorted(measurements, key=lambda item: item.measured_at)


_OFFICIAL_TAG_KIND = {OFFICIAL_TAG_WEIGHT: 1, OFFICIAL_TAG_BODY_FAT: 2}
_OFFICIAL_KNOWN_KEYS = {"birth_date", "data", "height", "sex"}


def parse_official_payload(payload: Any) -> dict[int, list[Measurement]]:
    """Parse only the two tags currently supported by the official API."""
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
    result: dict[int, list[Measurement]] = {1: [], 2: []}
    for record in records:
        if not isinstance(record, dict):
            raise HealthPlanetSchemaError("official_record_not_object")
        tag = record.get("tag")
        kind = _OFFICIAL_TAG_KIND.get(str(tag))
        if kind is None:
            continue
        value = _numeric(record.get("keydata"))
        measured_at = parse_jst_timestamp(record.get("date"))
        if value is None or measured_at is None:
            raise HealthPlanetSchemaError("official_record_fields_invalid")
        model = record.get("model")
        if not isinstance(model, str) or len(model) > 32:
            model = None
        description = METRICS[kind]
        result[kind].append(
            Measurement(
                metric_key=description.key,
                value=value,
                unit=description.unit,
                measured_at=measured_at,
                source="healthplanet_official_api",
                model=model,
                experimental=False,
                raw_kind=kind,
            )
        )
    for measurements in result.values():
        measurements.sort(key=lambda item: item.measured_at)
    return result
