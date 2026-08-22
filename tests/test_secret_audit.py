from __future__ import annotations

from scripts import secret_audit


def test_probe_key_audit_rejects_secret_and_value_keys():
    failures = secret_audit._probe_key_audit(
        {"safe": {"token": "synthetic", "measurement_value": 70.0}}
    )
    assert "probe_forbidden_key:safe.token" in failures
    assert "probe_forbidden_key:safe.measurement_value" in failures


def test_probe_key_audit_accepts_sanitized_schema_metadata():
    assert (
        secret_audit._probe_key_audit(
            {
                "tested_at": "synthetic-time",
                "endpoint_path": "/graph/graph.json",
                "record_count": 7,
                "metric_units": ["kg"],
                "timestamp_formats": ["YYYYMMDDHHMM"],
            }
        )
        == []
    )


def test_archive_patterns_cover_required_exclusions():
    names = (
        ".git/config",
        ".env.local",
        "_local_only/probe.json",
        "BACKUP/nested.zip",
        "cookies.json",
        "session.json",
        "capture.har",
        "raw_response.json",
        "logs/research.log",
    )
    for name in names:
        assert any(pattern.search(name) for pattern in secret_audit.FORBIDDEN_ARCHIVE_PATTERNS)
