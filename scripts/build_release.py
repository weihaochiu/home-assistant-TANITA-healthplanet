"""Build and validate the deterministic HACS release asset."""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
INTEGRATION = ROOT / "custom_components" / "tanita_healthplanet"
FILENAME = "healthplanet_for_home_assistant.zip"
REQUIRED = {
    "__init__.py",
    "api.py",
    "application_credentials.py",
    "button.py",
    "config_flow.py",
    "const.py",
    "coordinator.py",
    "device_info.py",
    "diagnostics.py",
    "errors.py",
    "history.py",
    "installation.py",
    "manifest.json",
    "models.py",
    "parser.py",
    "safe_update.py",
    "sensor.py",
    "strings.json",
    "translations/en.json",
    "translations/zh-Hant.json",
    "brand/icon.png",
    "brand/icon@2x.png",
}
FORBIDDEN_PARTS = {"tests", "BACKUP", "_local_only", ".env", ".storage", "logs"}


def build(output_directory: Path) -> tuple[Path, str]:
    """Create a root-layout ZIP and fail if its release contract is violated."""
    output_directory.mkdir(parents=True, exist_ok=True)
    destination = output_directory / FILENAME
    files = sorted(path for path in INTEGRATION.rglob("*") if path.is_file())
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(INTEGRATION).as_posix()
            if "__pycache__" in PurePosixPath(relative).parts or relative.endswith(".pyc"):
                continue
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = (0o100644 & 0xFFFF) << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    with zipfile.ZipFile(destination) as archive:
        if bad := archive.testzip():
            raise ValueError(f"release_zip_integrity:{bad}")
        names = set(archive.namelist())
        if missing := REQUIRED - names:
            raise ValueError(f"release_zip_missing:{','.join(sorted(missing))}")
        if any(FORBIDDEN_PARTS & set(PurePosixPath(name).parts) for name in names):
            raise ValueError("release_zip_forbidden_path")
        manifest = json.loads(archive.read("manifest.json"))
        if manifest.get("domain") != "tanita_healthplanet":
            raise ValueError("release_zip_domain_mismatch")
        if manifest.get("name") != "HealthPlanet for Home Assistant":
            raise ValueError("release_zip_name_mismatch")
        if manifest.get("version") != "0.2.2":
            raise ValueError("release_zip_version_mismatch")
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    (output_directory / "SHA256SUMS.txt").write_text(f"{digest}  {FILENAME}\n", encoding="utf-8")
    return destination, digest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "dist")
    args = parser.parse_args()
    destination, digest = build(args.output)
    print(f"asset={destination}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
