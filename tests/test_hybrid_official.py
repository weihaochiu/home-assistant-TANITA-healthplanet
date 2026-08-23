from __future__ import annotations

from datetime import UTC, datetime

import pytest

from custom_components.tanita_healthplanet.const import (
    OFFICIAL_TAG_BODY_FAT,
    OFFICIAL_TAG_DIASTOLIC,
    OFFICIAL_TAG_PULSE,
    OFFICIAL_TAG_SYSTOLIC,
    OFFICIAL_TAG_WEIGHT,
)
from custom_components.tanita_healthplanet.errors import HealthPlanetSchemaError
from custom_components.tanita_healthplanet.parser import (
    parse_official_innerscan_payload,
    parse_official_sphygmomanometer_payload,
)

OLDER = "209901010101"
NEWER = "209901020304"
NEWEST = "209901030405"


def record(tag, value, date=NEWER):
    return {
        "tag": tag,
        "keydata": value,
        "date": date,
        "model": "synthetic-model",
    }


def test_innerscan_selects_each_tags_latest_valid_measurement():
    parsed = parse_official_innerscan_payload(
        {
            "synthetic": True,
            "data": [
                record(OFFICIAL_TAG_WEIGHT, "101.25", OLDER),
                record(OFFICIAL_TAG_BODY_FAT, "202.5", OLDER),
                record(OFFICIAL_TAG_WEIGHT, "303.75", NEWER),
                record(OFFICIAL_TAG_BODY_FAT, "404", NEWER),
                record("synthetic-unknown-tag", "999", NEWEST),
            ],
        }
    )
    assert parsed.measurements[1].value == 303.75
    assert parsed.measurements[2].value == 404
    assert parsed.record_count == 5
    assert parsed.available_tags == ("6021", "6022")
    assert parsed.unavailable_tags == ()
    assert parsed.measurements[1].measured_at == datetime(2099, 1, 1, 18, 4, tzinfo=UTC)


@pytest.mark.parametrize("missing", [None, "", "-"])
def test_innerscan_null_is_unavailable_not_zero(missing):
    parsed = parse_official_innerscan_payload({"data": [record(OFFICIAL_TAG_WEIGHT, missing)]})
    assert parsed.measurements == {1: None, 2: None}
    assert parsed.available_tags == ()
    assert parsed.unavailable_tags == ("6021", "6022")


def test_innerscan_empty_data_is_valid_no_data():
    parsed = parse_official_innerscan_payload({"data": []})
    assert parsed.measurements == {1: None, 2: None}
    assert parsed.record_count == 0


@pytest.mark.parametrize(
    ("payload", "error_id"),
    [
        ({"data": "synthetic-invalid"}, "official_data_container_invalid"),
        ({"data": ["synthetic-invalid"]}, "official_record_not_object"),
        (
            {"data": [record(OFFICIAL_TAG_WEIGHT, "not-numeric")]},
            "official_record_value_invalid",
        ),
        (
            {"data": [record(OFFICIAL_TAG_WEIGHT, "101", "not-a-date")]},
            "official_record_date_invalid",
        ),
    ],
)
def test_innerscan_malformed_schema_is_typed(payload, error_id):
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_official_innerscan_payload(payload)
    assert str(error.value) == error_id


def test_blood_pressure_uses_complete_pair_and_cotimed_pulse():
    parsed = parse_official_sphygmomanometer_payload(
        {
            "data": [
                record(OFFICIAL_TAG_SYSTOLIC, "501", NEWER),
                record(OFFICIAL_TAG_DIASTOLIC, "502", NEWER),
                record(OFFICIAL_TAG_PULSE, "503", NEWER),
            ]
        }
    )
    assert {kind: value.value for kind, value in parsed.measurements.items()} == {
        101: 501,
        102: 502,
        103: 503,
    }
    assert parsed.complete_pair_found is True
    assert parsed.available_tags == ("622E", "622F", "6230")


def test_blood_pressure_pair_can_be_complete_without_pulse():
    parsed = parse_official_sphygmomanometer_payload(
        {
            "data": [
                record(OFFICIAL_TAG_SYSTOLIC, "601"),
                record(OFFICIAL_TAG_DIASTOLIC, "602"),
            ]
        }
    )
    assert parsed.measurements[101].value == 601
    assert parsed.measurements[102].value == 602
    assert parsed.measurements[103] is None
    assert parsed.complete_pair_found is True
    assert parsed.unavailable_tags == ("6230",)


def test_blood_pressure_never_pairs_different_timestamps():
    parsed = parse_official_sphygmomanometer_payload(
        {
            "data": [
                record(OFFICIAL_TAG_SYSTOLIC, "701", NEWER),
                record(OFFICIAL_TAG_DIASTOLIC, "702", OLDER),
                record(OFFICIAL_TAG_PULSE, "703", NEWER),
            ]
        }
    )
    assert parsed.measurements == {101: None, 102: None, 103: None}
    assert parsed.complete_pair_found is False


def test_newest_incomplete_pressure_data_does_not_replace_recent_complete_pair():
    parsed = parse_official_sphygmomanometer_payload(
        {
            "data": [
                record(OFFICIAL_TAG_SYSTOLIC, "801", OLDER),
                record(OFFICIAL_TAG_DIASTOLIC, "802", OLDER),
                record(OFFICIAL_TAG_PULSE, "803", OLDER),
                record(OFFICIAL_TAG_SYSTOLIC, "901", NEWEST),
                record(OFFICIAL_TAG_PULSE, "903", NEWEST),
            ]
        }
    )
    assert parsed.measurements[101].value == 801
    assert parsed.measurements[102].value == 802
    assert parsed.measurements[103].value == 803


@pytest.mark.parametrize(
    "payload",
    [
        {"data": []},
        {
            "data": [
                record(OFFICIAL_TAG_SYSTOLIC, None),
                record(OFFICIAL_TAG_DIASTOLIC, None),
            ]
        },
    ],
)
def test_blood_pressure_empty_or_null_data_is_unavailable(payload):
    parsed = parse_official_sphygmomanometer_payload(payload)
    assert parsed.measurements == {101: None, 102: None, 103: None}
    assert parsed.complete_pair_found is False


def test_blood_pressure_malformed_date_is_rejected_without_payload_in_error():
    payload = {"data": [record(OFFICIAL_TAG_SYSTOLIC, "1001", "private-date")]}
    with pytest.raises(HealthPlanetSchemaError) as error:
        parse_official_sphygmomanometer_payload(payload)
    rendered = repr(error.value)
    assert str(error.value) == "official_record_date_invalid"
    assert "1001" not in rendered
    assert "private-date" not in rendered
