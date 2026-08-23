from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "tanita_healthplanet"


def test_required_hacs_integration_files_exist():
    required = {
        "__init__.py",
        "manifest.json",
        "const.py",
        "config_flow.py",
        "application_credentials.py",
        "coordinator.py",
        "sensor.py",
        "diagnostics.py",
        "strings.json",
        "translations/en.json",
        "translations/zh-Hant.json",
    }
    assert all((INTEGRATION / relative).is_file() for relative in required)
    assert (ROOT / "hacs.json").is_file()
    for relative in (
        "README.md",
        "README.zh-TW.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "docs/ARCHITECTURE.md",
        "docs/PRIVACY.md",
        "docs/TROUBLESHOOTING.md",
    ):
        assert (ROOT / relative).is_file()


def test_manifest_and_hacs_metadata_are_pinned_for_v010():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "tanita_healthplanet"
    assert manifest["version"] == "0.1.0"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert hacs["homeassistant"] == "2026.8.0"
    keys = list(manifest)
    assert keys[:2] == ["domain", "name"]
    assert keys[2:] == sorted(keys[2:])


def test_translations_have_same_sensor_keys():
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    traditional_chinese = json.loads(
        (INTEGRATION / "translations" / "zh-Hant.json").read_text(encoding="utf-8")
    )
    expected = set(strings["entity"]["sensor"])
    assert len(expected) == 13
    assert set(english["entity"]["sensor"]) == expected
    assert set(traditional_chinese["entity"]["sensor"]) == expected


def test_website_warning_mentions_unofficial_endpoint_and_storage_risk():
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    website = strings["config"]["step"]["website"]
    rendered = json.dumps(website).casefold()
    assert "unofficial" in rendered
    assert ".storage" in rendered
    assert "encrypted password vault" in rendered


def test_options_flow_schema_contains_no_sensitive_fields():
    source = (INTEGRATION / "config_flow.py").read_text(encoding="utf-8")
    options_source = source.split("class HealthPlanetOptionsFlow", 1)[1]
    assert "CONF_OFFICIAL_UPDATE_INTERVAL" in options_source
    assert "CONF_WEBSITE_UPDATE_INTERVAL" in options_source
    assert "CONF_PASSWORD" not in options_source
    assert "CONF_CLIENT_SECRET" not in options_source


def test_workflows_pin_every_third_party_action_to_a_commit():
    workflows = (ROOT / ".github" / "workflows").glob("*.yml")
    for workflow in workflows:
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" not in line:
                continue
            reference = line.split("@", 1)[1].split()[0]
            assert len(reference) == 40
            assert all(character in "0123456789abcdef" for character in reference)
