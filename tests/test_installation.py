from __future__ import annotations

import json
from types import SimpleNamespace

from custom_components.tanita_healthplanet.installation import (
    ERROR_MANIFEST_INVALID,
    ERROR_MANIFEST_MISSING,
    STATUS_HACS_METADATA_STALE,
    STATUS_INSTALLATION_DRIFT,
    STATUS_INSTALLATION_INVALID,
    STATUS_NORMAL,
    STATUS_UPDATE_AVAILABLE,
    ActualInstalledVersionVerifier,
    InstallationVersions,
)
from custom_components.tanita_healthplanet.versioning import normalize_version, versions_equal


class FakeHass:
    def __init__(self, root):
        self.config = SimpleNamespace(path=lambda *parts: str(root.joinpath(*parts)))

    async def async_add_executor_job(self, target, *args):
        return target(*args)


async def test_disk_manifest_reading_is_narrow_and_validated(tmp_path):
    verifier = ActualInstalledVersionVerifier(FakeHass(tmp_path))
    assert (await verifier.async_read()).error_id == ERROR_MANIFEST_MISSING
    path = tmp_path / "custom_components" / "tanita_healthplanet" / "manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text("not-json", encoding="utf-8")
    assert (await verifier.async_read()).error_id == ERROR_MANIFEST_INVALID
    path.write_text(json.dumps({"domain": "wrong", "version": "0.2.2"}), encoding="utf-8")
    assert (await verifier.async_read()).error_id == ERROR_MANIFEST_INVALID
    path.write_text(
        json.dumps(
            {
                "domain": "tanita_healthplanet",
                "name": "HealthPlanet for Home Assistant",
                "version": "0.2.2",
                "ignored": "not-read-for-verification",
            }
        ),
        encoding="utf-8",
    )
    result = await verifier.async_read()
    assert result.version == "0.2.2"
    assert result.error_id is None

    path.write_text(
        json.dumps({"domain": "tanita_healthplanet", "version": "not-a-version"}),
        encoding="utf-8",
    )
    invalid = await verifier.async_read()
    assert invalid.version == "not-a-version"
    assert invalid.error_id == ERROR_MANIFEST_INVALID


def test_version_v_prefix_equal():
    assert normalize_version("0.2.2") == "0.2.2"
    assert normalize_version("v0.2.2") == "0.2.2"
    assert normalize_version("V0.2.2") == "0.2.2"
    assert versions_equal("0.2.2", "v0.2.2") is True
    assert versions_equal("0.2.1", "v0.2.2") is False
    assert normalize_version("invalid") is None


def test_version_state_model_distinguishes_drift_stale_and_update():
    base = dict(
        runtime="0.2.3",
        disk="0.2.2",
        hacs_installed="v0.2.2",
        hacs_latest="v0.2.2",
        github_check_complete=True,
    )
    normal = InstallationVersions(**base, github_latest="v0.2.2")
    assert normal.consistent is True
    assert normal.update_metadata_status == STATUS_NORMAL
    stale = InstallationVersions(**base, github_latest="v0.2.3")
    assert stale.update_metadata_status == STATUS_HACS_METADATA_STALE
    available = InstallationVersions(**{**base, "hacs_latest": "v0.2.3"}, github_latest="v0.2.3")
    assert available.update_metadata_status == STATUS_UPDATE_AVAILABLE
    drift = InstallationVersions(**{**base, "disk": "0.2.1"}, github_latest="v0.2.2")
    assert drift.update_metadata_status == STATUS_INSTALLATION_DRIFT
    invalid = InstallationVersions(
        **{**base, "disk": "invalid", "disk_error_id": ERROR_MANIFEST_INVALID},
        github_latest="v0.2.2",
    )
    assert invalid.update_metadata_status == STATUS_INSTALLATION_INVALID
