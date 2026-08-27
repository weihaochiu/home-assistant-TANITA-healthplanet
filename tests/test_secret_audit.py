from __future__ import annotations

from pathlib import Path, PurePosixPath

from scripts import create_backup, secret_audit


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


def test_path_audit_covers_required_sensitive_artifacts():
    names = {
        ".env.local": "environment_file",
        "_local_only/probe.json": "local_only_artifact",
        "browser_exports/network.json": "capture_directory",
        "screenshots/page.png": "capture_directory",
        "cookies.json": "session_artifact",
        "session.json": "session_artifact",
        "capture.har": "sensitive_artifact_extension",
        "capture.trace": "sensitive_artifact_extension",
        "capture.dump": "sensitive_artifact_extension",
        "capture.sqlite": "sensitive_artifact_extension",
        "raw_response.json": "raw_capture",
        "request_capture.json": "raw_capture",
        "screenshot_login.png": "screenshot",
    }
    for name, expected in names.items():
        assert expected in secret_audit._path_risks(PurePosixPath(name), allow_probe=False)


def test_allowlisted_probe_is_not_a_path_risk():
    assert secret_audit._path_risks(secret_audit.PROBE_RELATIVE_PATH, allow_probe=True) == []


def test_mask_never_returns_full_sensitive_value():
    assert secret_audit._mask(b"abcdefgh") == "ab…gh"
    assert "abcdefgh" not in secret_audit._mask(b"abcdefgh")


def test_realistic_secret_patterns_are_masked_and_synthetic_is_allowed():
    real = secret_audit._content_findings(
        PurePosixPath("capture.json"),
        b'{"password":"plausible-real-secret"}',
        location="capture.json",
    )
    assert len(real) == 1
    assert real[0].risk == "secret_assignment"
    assert real[0].masked == "pl…et"
    assert "plausible-real-secret" not in repr(real)
    synthetic = secret_audit._content_findings(
        PurePosixPath("tests/fixture.json"),
        b'{"password":"synthetic-password-never-use"}',
        location="tests/fixture.json",
    )
    assert synthetic == []


def test_realistic_email_is_reported_but_synthetic_invalid_domain_is_allowed():
    realistic_email = b"person" + b"@" + b"real-domain" + b"." + b"test"
    real = secret_audit._content_findings(
        PurePosixPath("capture.json"),
        b'{"login":"' + realistic_email + b'"}',
        location="capture.json",
    )
    assert len(real) == 1
    assert real[0].risk == "email_like_identifier"
    assert realistic_email.decode() not in repr(real)


def test_required_hass_brand_retina_filename_is_not_an_email_identifier():
    findings = secret_audit._content_findings(
        PurePosixPath("tests/brand_reference.py"),
        b'asset = "brand/icon@2x.png"',
        location="tests/brand_reference.py",
    )
    assert findings == []
    synthetic = secret_audit._content_findings(
        PurePosixPath("tests/fixture.json"),
        b'{"login":"synthetic-user@example.invalid"}',
        location="tests/fixture.json",
    )
    assert synthetic == []


def test_backup_rules_cover_browser_and_probe_artifacts():
    for path in (
        Path("browser_exports/network.json"),
        Path("screenshots/login.png"),
        Path("temporary_probe_1/output.json"),
        Path("probe_output_1/result.json"),
        Path("capture.trace"),
        Path("capture.dump"),
        Path("capture.sqlite"),
        Path("capture.db"),
        Path("request_capture.json"),
        Path("response_capture.json"),
        Path("screenshot_login.png"),
    ):
        assert create_backup.is_excluded(path)


def test_cookie_and_csrf_values_are_reported_only_masked():
    cookie_value = b"plausible" + b"-cookie-value"
    csrf_value = b"plausible" + b"-csrf-value"
    findings = secret_audit._content_findings(
        PurePosixPath("capture.har"),
        b"Cookie: " + cookie_value + b"\norg.apache.struts.taglib.html.TOKEN=" + csrf_value,
        location="capture.har",
    )
    assert {item.risk for item in findings} >= {"secret_header", "csrf_token_value"}
    rendered = repr(findings)
    assert cookie_value.decode() not in rendered
    assert csrf_value.decode() not in rendered


def test_all_tracked_fixtures_are_synthetic_and_secret_free():
    fixture_root = Path(__file__).parent / "fixtures"
    for path in fixture_root.iterdir():
        if not path.is_file():
            continue
        relative = PurePosixPath("tests/fixtures") / path.name
        assert (
            secret_audit._content_findings(
                relative, path.read_bytes(), location=relative.as_posix()
            )
            == []
        )


def test_run_audit_has_no_credential_file_dependency(monkeypatch):
    monkeypatch.setattr(secret_audit, "_scan_working_tree", lambda: ([], 1))
    monkeypatch.setattr(secret_audit, "_scan_git_objects", lambda: ([], 2))
    monkeypatch.setattr(secret_audit, "_scan_backups", lambda: ([], 3))
    monkeypatch.setattr(secret_audit, "_validate_probe", lambda: [])
    findings, counts = secret_audit.run_audit()
    assert findings == []
    assert counts == {"working_files": 1, "git_blobs": 2, "backups": 3}
