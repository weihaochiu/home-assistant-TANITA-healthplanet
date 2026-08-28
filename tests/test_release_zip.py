from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

from scripts.build_release import FILENAME, REQUIRED, build

ROOT = Path(__file__).resolve().parents[1]


def test_deterministic_hacs_zip_contract(tmp_path):
    asset, digest = build(tmp_path)
    assert asset.name == FILENAME
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == digest
    assert (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8") == (f"{digest}  {FILENAME}\n")
    with zipfile.ZipFile(asset) as archive:
        names = set(archive.namelist())
    assert names >= REQUIRED
    assert not any(name.startswith(("tests/", "BACKUP/")) for name in names)


def test_release_builder_uses_manifest_version_without_patch_hard_code():
    source = (ROOT / "scripts" / "build_release.py").read_text(encoding="utf-8")
    assert 'expected_version = expected_manifest.get("version")' in source
    assert 'manifest.get("version") != "0.2.3"' not in source
