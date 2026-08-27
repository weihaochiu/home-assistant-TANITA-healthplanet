from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.tanita_healthplanet.const import METRICS, WEBSITE_KINDS
from custom_components.tanita_healthplanet.errors import (
    HealthPlanetBackendCodeError,
    HealthPlanetSchemaError,
)
from custom_components.tanita_healthplanet.parser import (
    parse_jst_timestamp,
    parse_official_payload,
    parse_website_payload,
    parse_website_payload_result,
)
from research.healthplanet_web.parser import parse_graph_payload

SYNTHETIC_TIMESTAMP_12 = "209901020304"
SYNTHETIC_TIMESTAMP_14 = "20990102030405"


def website_payload(value=70.0, timestamp=SYNTHETIC_TIMESTAMP_12):
    return {
        "synthetic": True,
        "code": [0],
        "value1": [[value, timestamp]],
        "value1_unit": ["kg"],
    }


@pytest.mark.parametrize(
    ("kind", "value"),
    [
        (1, 70.0),
        (2, 20.0),
        (3, 14.0),
        (4, 8),
        (5, 1500),
        (6, 50.0),
        (7, 2.8),
        (14, 40),
        (22, 55),
        (23, 80),
    ],
)
def test_website_parser_all_ten_confirmed_kinds(kind, value):
    measurements = parse_website_payload(website_payload(value), kind)
    assert len(measurements) == 1
    measurement = measurements[0]
    assert measurement.metric_key == METRICS[kind].key
    assert measurement.value == value
    assert measurement.raw_kind == kind
    assert measurement.experimental is True
    assert measurement.measured_at.tzinfo is UTC


def test_kind_23_null_is_unavailable_not_zero():
    payload = website_payload()
    payload["value1"] = [None]
    assert parse_website_payload(payload, 23) == []


@pytest.mark.parametrize("missing", [None, "", "-"])
def test_missing_values_are_not_coerced_to_zero(missing):
    payload = website_payload()
    payload["value1"] = [[missing, SYNTHETIC_TIMESTAMP_12]]
    assert parse_website_payload(payload, 1) == []


def test_unexpected_container_value_is_rejected_without_type_error():
    payload = website_payload()
    payload["value1"] = [[["unexpected"], SYNTHETIC_TIMESTAMP_12]]
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_website_payload(payload, 1)
    assert str(error.value) == "website_record_fields_invalid"


def test_confirmed_two_field_schema_accepts_timestamp_value_order():
    payload = website_payload()
    payload["value1"] = [[SYNTHETIC_TIMESTAMP_12, 70.0]]
    measurements = parse_website_payload(payload, 1)
    assert [item.value for item in measurements] == [70.0]


@pytest.mark.parametrize("timestamp", [1767290640, 1767290640000])
def test_production_parser_accepts_research_timestamp_variants(timestamp):
    payload = website_payload(timestamp=timestamp)
    assert len(parse_website_payload(payload, 1)) == 1


@pytest.mark.parametrize(
    "timestamp",
    [
        "20990102",
        SYNTHETIC_TIMESTAMP_12,
        SYNTHETIC_TIMESTAMP_14,
        "2099-01-02T03:04:05+09:00",
        "2099/01/02 03:04",
        "2099/01/02 03:04:05",
        "2099-01-02 03:04",
        "2099-01-02 03:04:05",
        "2099/01/02 03:04:05.125",
        "2099-01-02 03:04:05.125",
        4071035040,
        4071035040000,
        "4071035040",
        "4071035040000",
    ],
)
def test_website_timestamp_representation_matrix(timestamp):
    assert len(parse_website_payload(website_payload(value="70.25", timestamp=timestamp), 1)) == 1


@pytest.mark.parametrize("not_timestamp", ["70", "20.5", "1500"])
def test_short_numeric_measurements_are_not_timestamps(not_timestamp):
    assert parse_jst_timestamp(not_timestamp) is None


@pytest.mark.parametrize(
    "row",
    [
        ["70.25", 4071035040],
        [4071035040, "70.25"],
        ["70.25", "4071035040"],
        ["4071035040", "70.25"],
    ],
)
def test_numeric_and_numeric_string_roles_are_resolved_by_unique_assignment(row):
    payload = website_payload()
    payload["value1"] = [row]
    assert [item.value for item in parse_website_payload(payload, 1)] == [70.25]


@pytest.mark.parametrize("kind", [1, 2, 3, 4, 5, 6, 7, 14, 22])
def test_six_row_real_device_derived_synthetic_regression(kind):
    payload = website_payload()
    payload["value1"] = [[kind + index / 10, f"2099010203{index:02d}"] for index in range(6)]
    result = parse_website_payload_result(payload, kind)
    assert len(result.measurements) == 6
    assert result.row_count == 6
    assert result.timestamp_parsing_success is True


def test_zero_timestamp_candidate_is_missing_not_ambiguous():
    payload = website_payload()
    payload["value1"] = [["70.25", "synthetic-not-a-timestamp"]]
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_website_payload(payload, 1)
    assert str(error.value) == "website_record_timestamp_missing"
    assert error.value.timestamp_candidate_count == 0
    assert error.value.numeric_candidate_count == 1
    assert error.value.valid_assignment_count == 0
    assert error.value.field_type_shape == ("string", "string")


def test_two_valid_role_assignments_remain_strictly_ambiguous():
    payload = website_payload()
    payload["value1"] = [[4071035040, 4071035100]]
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_website_payload(payload, 1)
    assert str(error.value) == "website_record_timestamp_ambiguous"
    assert error.value.timestamp_candidate_count == 2
    assert error.value.numeric_candidate_count == 2
    assert error.value.valid_assignment_count == 2
    assert error.value.field_type_shape == ("number", "number")


def test_known_timestamp_with_invalid_counterpart_is_fields_invalid():
    payload = website_payload()
    payload["value1"] = [[SYNTHETIC_TIMESTAMP_12, {"synthetic": True}]]
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_website_payload(payload, 1)
    assert str(error.value) == "website_record_fields_invalid"
    assert error.value.timestamp_candidate_count == 1
    assert error.value.numeric_candidate_count == 1
    assert error.value.valid_assignment_count == 0
    assert error.value.field_type_shape == ("string", "object")


@pytest.mark.parametrize(
    "row",
    [
        [70.0, SYNTHETIC_TIMESTAMP_12],
        [SYNTHETIC_TIMESTAMP_12, 70.0],
        [70.0, 4071035040],
    ],
)
def test_research_and_production_parsers_agree_on_confirmed_synthetic_schema(row):
    payload = website_payload()
    payload["value1"] = [row]
    production = parse_website_payload(payload, 1)
    research = parse_graph_payload(payload, 1).measurements
    assert len(production) == len(research) == 1
    assert production[0].value == research[0].value
    assert production[0].measured_at == research[0].measured_at


@pytest.mark.parametrize(
    "row",
    [
        [70.0],
        [70.0, SYNTHETIC_TIMESTAMP_12, "extra"],
        {"value": 70.0},
        [True, SYNTHETIC_TIMESTAMP_12],
        [float("nan"), SYNTHETIC_TIMESTAMP_12],
        [float("inf"), SYNTHETIC_TIMESTAMP_12],
        [["nested"], SYNTHETIC_TIMESTAMP_12],
    ],
)
def test_unknown_website_record_shape_is_rejected(row):
    payload = website_payload()
    payload["value1"] = [row]
    with pytest.raises(HealthPlanetSchemaError):
        parse_website_payload(payload, 1)


def test_backend_code_minus_one_is_not_empty_data():
    with pytest.raises(HealthPlanetBackendCodeError) as error:
        parse_website_payload({"code": [-1], "value1": []}, 1)
    assert str(error.value) == "website_backend_code_minus_one"


@pytest.mark.parametrize("payload", [None, [], "<html>login</html>", {"code": [0]}])
def test_malformed_or_html_website_response_is_rejected(payload):
    with pytest.raises(HealthPlanetSchemaError):
        parse_website_payload(payload, 1)


def test_jst_is_explicitly_converted_to_utc():
    parsed = parse_jst_timestamp(SYNTHETIC_TIMESTAMP_14)
    assert parsed == datetime(2099, 1, 1, 18, 4, 5, tzinfo=UTC)


def test_official_parser_supports_only_documented_weight_and_body_fat_tags():
    payload = {
        "synthetic": True,
        "data": [
            {
                "date": SYNTHETIC_TIMESTAMP_12,
                "keydata": "70.0",
                "model": "synthetic-model",
                "tag": "6021",
            },
            {
                "date": SYNTHETIC_TIMESTAMP_12,
                "keydata": "20.0",
                "model": "synthetic-model",
                "tag": "6022",
            },
            {
                "date": SYNTHETIC_TIMESTAMP_12,
                "keydata": "999",
                "model": "synthetic-model",
                "tag": "unknown",
            },
        ],
    }
    parsed = parse_official_payload(payload)
    assert [item.value for item in parsed[1]] == [70.0]
    assert [item.value for item in parsed[2]] == [20.0]
    assert all(not item.experimental for values in parsed.values() for item in values)


def test_official_parser_empty_data_keeps_both_sensors_unavailable():
    assert parse_official_payload({"data": []}) == {1: [], 2: []}


def test_schema_error_contains_keys_only_never_values():
    payload = {
        "code": [0],
        "future_field": "plausible-private-value",
        "value1": "changed",
    }
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_website_payload(payload, 1)
    assert error.value.unknown_fields == ("future_field",)
    assert "plausible-private-value" not in str(error.value)
    assert "plausible-private-value" not in repr(error.value)


def test_confirmed_website_kind_count_is_ten():
    assert len(WEBSITE_KINDS) == 10
    assert set(WEBSITE_KINDS).issubset(METRICS)
