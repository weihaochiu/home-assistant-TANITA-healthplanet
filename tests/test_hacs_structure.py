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
        "button.py",
        "coordinator.py",
        "sensor.py",
        "diagnostics.py",
        "history.py",
        "safe_update.py",
        "installation.py",
        "device_info.py",
        "strings.json",
        "translations/en.json",
        "translations/zh-Hant.json",
        "brand/icon.png",
        "brand/icon@2x.png",
    }
    assert all((INTEGRATION / relative).is_file() for relative in required)
    assert (ROOT / "hacs.json").is_file()
    for relative in (
        "README.md",
        "README.zh-TW.md",
        "SECURITY.md",
        "CHANGELOG.md",
        "docs/ARCHITECTURE.md",
        "docs/HEALTHPLANET_API_SETUP.md",
        "docs/HEALTHPLANET_API_SETUP.zh-TW.md",
        "docs/PRIVACY.md",
        "docs/TROUBLESHOOTING.md",
    ):
        assert (ROOT / relative).is_file()


def test_manifest_and_hacs_metadata_are_pinned_for_v022():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text(encoding="utf-8"))
    hacs = json.loads((ROOT / "hacs.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "tanita_healthplanet"
    assert manifest["version"] == "0.2.2"
    assert manifest["name"] == "HealthPlanet for Home Assistant"
    assert manifest["config_flow"] is True
    assert manifest["iot_class"] == "cloud_polling"
    assert "hacs" not in manifest.get("dependencies", [])
    assert hacs["homeassistant"] == "2026.8.0"
    assert hacs["name"] == "HealthPlanet for Home Assistant"
    assert hacs["zip_release"] is True
    assert hacs["filename"] == "healthplanet_for_home_assistant.zip"
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
    assert strings["title"] == "HealthPlanet for Home Assistant"
    assert english["title"] == strings["title"]
    assert traditional_chinese["title"] == strings["title"]


def test_safe_update_translation_structures_stay_in_sync():
    strings = json.loads((INTEGRATION / "strings.json").read_text(encoding="utf-8"))
    english = json.loads((INTEGRATION / "translations" / "en.json").read_text(encoding="utf-8"))
    traditional_chinese = json.loads(
        (INTEGRATION / "translations" / "zh-Hant.json").read_text(encoding="utf-8")
    )
    for translation in (english, traditional_chinese):
        assert set(translation["entity"]["button"]) == set(strings["entity"]["button"])
        assert set(translation["options"]["step"]["init"]["data"]) == set(
            strings["options"]["step"]["init"]["data"]
        )
        for attribute in ("last_stage", "last_result"):
            assert set(
                translation["entity"]["button"]["safe_update"]["state_attributes"][attribute][
                    "state"
                ]
            ) == set(
                strings["entity"]["button"]["safe_update"]["state_attributes"][attribute]["state"]
            )


def test_original_local_brand_assets_are_valid_png_files():
    expected = {"icon.png": (256, 256), "icon@2x.png": (512, 512)}
    for name, dimensions in expected.items():
        path = INTEGRATION / "brand" / name
        assert path.is_file()
        payload = path.read_bytes()
        assert payload.startswith(b"\x89PNG\r\n\x1a\n")
        width = int.from_bytes(payload[16:20], "big")
        height = int.from_bytes(payload[20:24], "big")
        assert (width, height) == dimensions
        assert width == height
        assert payload[24] == 8
        assert payload[25] == 6
        assert path.stat().st_size < 500_000


def test_unofficial_and_trademark_notices_are_present():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    chinese = (ROOT / "README.zh-TW.md").read_text(encoding="utf-8")
    assert "unofficial" in readme.casefold()
    assert "not affiliated" in readme.casefold()
    assert "not endorsed" in readme.casefold()
    assert "not sponsored" in readme.casefold()
    assert "## Trademark notice" in readme
    assert "非官方" in chinese
    assert "無隸屬" in chinese
    assert "無贊助" in chinese
    assert "無背書" in chinese
    assert "## 商標與非官方專案聲明" in chinese


def test_no_official_brand_artifact_is_bundled():
    bundled = {path.name.casefold() for path in INTEGRATION.rglob("*") if path.is_file()}
    assert bundled.isdisjoint(
        {"tanita.png", "tanita-logo.png", "healthplanet.png", "healthplanet-app-icon.png"}
    )


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
    assert "CONF_HACS_UPDATE_ENTITY" in options_source
    assert "CONF_RESTART_AFTER_SAFE_UPDATE" in options_source
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
