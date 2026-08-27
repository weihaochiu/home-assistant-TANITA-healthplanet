from __future__ import annotations

import hashlib
import zipfile

from scripts.build_release import FILENAME, REQUIRED, build


def test_deterministic_hacs_zip_contract(tmp_path):
    asset, digest = build(tmp_path)
    assert asset.name == FILENAME
    assert hashlib.sha256(asset.read_bytes()).hexdigest() == digest
    assert (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8") == (f"{digest}  {FILENAME}\n")
    with zipfile.ZipFile(asset) as archive:
        names = set(archive.namelist())
    assert names >= REQUIRED
    assert not any(name.startswith(("tests/", "BACKUP/")) for name in names)
