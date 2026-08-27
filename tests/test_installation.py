from __future__ import annotations

import json
from types import SimpleNamespace

from custom_components.tanita_healthplanet.installation import (
    ERROR_MANIFEST_INVALID,
    ERROR_MANIFEST_MISSING,
    ActualInstalledVersionVerifier,
)


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
