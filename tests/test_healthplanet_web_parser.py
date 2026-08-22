from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from research.healthplanet_web.client import HealthPlanetWebClient
from research.healthplanet_web.const import METRICS
from research.healthplanet_web.errors import (
    BackendCodeError,
    ExpiredSessionError,
    MalformedResponseError,
    SchemaDriftError,
    UnsupportedKindError,
)
from research.healthplanet_web.parser import parse_graph_payload, select_newest
from scripts import research_healthplanet_backend as probe

FIXTURES = Path(__file__).parent / "fixtures"


def synthetic_payload(
    value=70.0,
    timestamp="202601020304",
    *,
    unit="kg",
):
    return {
        "synthetic": True,
        "code": [0],
        "value1": [[value, timestamp]],
        "value1_unit": [unit],
        "value1_formatString": ["%.1f"],
    }


@pytest.mark.parametrize(
    ("kind", "value", "unit"),
    [
        (1, 70.0, "kg"),
        (2, 20.0, "%"),
        (3, 14.0, "kg"),
        (4, 8, None),
        (5, 1500, "kcal"),
        (6, 50.0, "kg"),
        (7, 2.8, "kg"),
        (14, 40, "才"),
        (22, 55, "%"),
        (23, 80, None),
    ],
)
def test_every_confirmed_kind_parses_synthetic_actual_shape(kind, value, unit):
    payload = synthetic_payload(value, unit=unit or "")
    result = parse_graph_payload(payload, kind)
    measurement = select_newest(result)
    assert measurement is not None
    assert measurement.metric_key == METRICS[kind].key
    assert measurement.value == value
    assert measurement.unit == unit
    assert measurement.raw_kind == kind
    assert measurement.source == "healthplanet_web_graph"
    assert measurement.experimental is True
    assert measurement.model is None


def test_actual_observed_schema_fixture_is_marked_synthetic_and_parsed():
    payload = json.loads(
        (FIXTURES / "graph_actual_schema_synthetic.json").read_text(encoding="utf-8")
    )
    assert payload["synthetic"] is True
    result = parse_graph_payload(payload, 1)
    assert [item.value for item in result.measurements] == [70.0, 71.0]
    assert result.skipped_records == 0


@pytest.mark.parametrize(
    ("timestamp", "year", "minute"),
    [
        ("202601020304", 2026, 4),
        ("20260102030405", 2026, 4),
        ("2026/01/02 03:04", 2026, 4),
        ("2026-01-02T03:04:05+09:00", 2026, 4),
        (1767290640, 2026, 4),
        (1767290640000, 2026, 4),
    ],
)
def test_timestamp_variants_and_timezone(timestamp, year, minute):
    result = parse_graph_payload(synthetic_payload(timestamp=timestamp), 1)
    measurement = select_newest(result)
    assert measurement is not None
    assert measurement.measured_at.year == year
    assert measurement.measured_at.minute == minute
    assert measurement.measured_at.utcoffset() == timedelta(hours=9)


@pytest.mark.parametrize(
    ("value", "expected"),
    [("70.0", 70.0), (70, 70), (70.5, 70.5), ("1500", 1500)],
)
def test_numeric_string_integer_and_float(value, expected):
    measurement = select_newest(parse_graph_payload(synthetic_payload(value), 1))
    assert measurement is not None
    assert measurement.value == expected


@pytest.mark.parametrize("missing", [None, "-", ""])
def test_missing_rows_are_skipped(missing):
    payload = synthetic_payload()
    payload["value1"] = [missing]
    result = parse_graph_payload(payload, 1)
    assert result.measurements == ()
    assert result.skipped_records == 1


def test_missing_value_inside_row_is_skipped():
    payload = synthetic_payload()
    payload["value1"] = [["-", "202601020304"]]
    result = parse_graph_payload(payload, 1)
    assert result.measurements == ()
    assert result.skipped_records == 1


def test_empty_dataset_is_valid():
    payload = synthetic_payload()
    payload["value1"] = []
    result = parse_graph_payload(payload, 1)
    assert result.measurements == ()
    assert result.skipped_records == 0
    assert select_newest(result) is None


def test_newest_record_selection_is_time_based():
    payload = synthetic_payload()
    payload["value1"] = [
        [71.0, "202601020405"],
        [70.0, "202601020304"],
    ]
    result = parse_graph_payload(payload, 1)
    newest = select_newest(result)
    assert newest is not None
    assert newest.value == 71.0


def test_unknown_kind_never_creates_measurement():
    with pytest.raises(UnsupportedKindError) as error:
        parse_graph_payload(synthetic_payload(), 999)
    assert str(error.value) == "UNSUPPORTED_KIND"


def test_unknown_fields_are_only_sanitized_names():
    payload = synthetic_payload()
    payload.update(
        {
            "future_metric": 999.99,
            "account_id": "synthetic-account",
            "token": "synthetic-token",
            "個人": "synthetic-person",
        }
    )
    result = parse_graph_payload(payload, 1)
    assert result.unknown_fields == ("future_metric",)
    assert "999.99" not in repr(result.unknown_fields)
    assert "synthetic" not in repr(result.unknown_fields)


def test_code_minus_one_is_an_error_not_an_empty_dataset():
    with pytest.raises(BackendCodeError) as error:
        parse_graph_payload({"synthetic": True, "code": [-1]}, 1)
    assert str(error.value) == "BACKEND_CODE_MINUS_ONE"


def test_other_backend_code_is_safely_rejected():
    with pytest.raises(BackendCodeError) as error:
        parse_graph_payload({"synthetic": True, "code": [7], "value1": []}, 1)
    assert str(error.value) == "BACKEND_CODE_UNSUPPORTED"


@pytest.mark.parametrize("payload", [None, [], 42, "not-json"])
def test_malformed_payload_is_rejected(payload):
    with pytest.raises(MalformedResponseError):
        parse_graph_payload(payload, 1)


def test_html_login_page_is_expired_session():
    with pytest.raises(ExpiredSessionError) as error:
        parse_graph_payload("<html><form>login</form></html>", 1)
    assert str(error.value) == "HTML_LOGIN_OR_EXPIRED_SESSION"


def test_schema_drift_missing_or_invalid_value_container():
    with pytest.raises(SchemaDriftError):
        parse_graph_payload({"synthetic": True, "code": [0]}, 1)
    with pytest.raises(SchemaDriftError):
        parse_graph_payload({"synthetic": True, "code": [0], "value1": {}}, 1)


def test_untrusted_response_unit_does_not_override_confirmed_mapping():
    result = parse_graph_payload(synthetic_payload(unit="synthetic-secret-unit"), 1)
    measurement = select_newest(result)
    assert measurement is not None
    assert measurement.unit == "kg"


def test_model_is_explicitly_propagated_without_inference():
    result = parse_graph_payload(synthetic_payload(), 1, model="synthetic-model")
    measurement = select_newest(result)
    assert measurement is not None
    assert measurement.model == "synthetic-model"


def test_client_requires_authenticated_session():
    class Session:
        def close(self):
            pass

    client = HealthPlanetWebClient(Session())
    with pytest.raises(MalformedResponseError) as error:
        client.fetch_kind(1)
    assert str(error.value) == "SESSION_NOT_AUTHENTICATED"
    client.close()


def test_client_rejects_unknown_kind_before_request():
    class Session:
        def close(self):
            pass

    client = HealthPlanetWebClient(Session())
    client._authenticated = True
    with pytest.raises(UnsupportedKindError):
        client.fetch_kind(999)
    client.close()


def test_client_fetches_allowlisted_get_and_parses(monkeypatch):
    payload = json.dumps(synthetic_payload()).encode()

    class Session:
        def __init__(self):
            self.calls = []

        def request(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return probe.ResponseData(
                200, "application/json", payload, "https://www.healthplanet.jp/graph/graph.json"
            )

        def close(self):
            pass

    session = Session()
    client = HealthPlanetWebClient(session)
    client._authenticated = True
    result = client.fetch_kind(1)
    assert select_newest(result) is not None
    assert len(session.calls) == 1
    assert session.calls[0][1]["headers"] == {"Accept": "application/json"}
    assert "kind=1" in session.calls[0][0]
    client.close()


def test_client_malformed_json_is_safe():
    class Session:
        def request(self, *_args, **_kwargs):
            return probe.ResponseData(
                200, "text/html", b"not-json", "https://www.healthplanet.jp/index.do"
            )

        def close(self):
            pass

    client = HealthPlanetWebClient(Session())
    client._authenticated = True
    with pytest.raises(MalformedResponseError) as error:
        client.fetch_kind(1)
    assert str(error.value) == "MALFORMED_RESPONSE"
    client.close()
