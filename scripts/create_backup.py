"""Create a privacy-safe source archive before a push."""

from __future__ import annotations

import hashlib
import os
import subprocess
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

KEEP_BACKUPS = 10
EXCLUDED_DIR_NAMES = {
    ".git",
    ".storage",
    ".pytest_cache",
    ".ruff_cache",
    ".mypy_cache",
    ".venv",
    "BACKUP",
    "__pycache__",
    "_local_only",
    "browser_exports",
    "cookies",
    "healthplanet_research",
    "logs",
    "probe_output",
    "screenshots",
    "session",
    "sessions",
    "temporary_probe",
    "token",
    "tokens",
}
EXCLUDED_FILE_NAMES = {".env", "cookies.json", "secrets.yaml", "session.json"}
EXCLUDED_SUFFIXES = {
    ".cookie",
    ".cookies",
    ".db",
    ".dump",
    ".har",
    ".log",
    ".session",
    ".sqlite",
    ".token",
    ".trace",
}
EXCLUDED_SENSITIVE_STEMS = {
    "cookie",
    "cookies",
    "session",
    "sessions",
    "token",
    "tokens",
}


def repository_root() -> Path:
    return Path(__file__).resolve().parents[1]


def is_excluded(relative_path: Path) -> bool:
    parts = relative_path.parts
    if any(part in EXCLUDED_DIR_NAMES for part in parts[:-1]):
        return True
    if any(
        part.casefold().startswith(("temporary_probe", "probe_output"))
        for part in parts[:-1]
    ):
        return True
    name = relative_path.name
    folded = name.casefold()
    if name in EXCLUDED_FILE_NAMES or name.startswith(".env."):
        return True
    if relative_path.stem.casefold() in EXCLUDED_SENSITIVE_STEMS:
        return True
    if folded.startswith("raw_response"):
        return True
    if folded.startswith(("request_capture", "response_capture", "screenshot_")):
        return True
    if "_screenshot." in folded:
        return True
    return folded.endswith(tuple(EXCLUDED_SUFFIXES))


def iter_source_files(root: Path):
    for directory, directory_names, file_names in os.walk(root):
        directory_names[:] = sorted(
            name for name in directory_names if name not in EXCLUDED_DIR_NAMES
        )
        current = Path(directory)
        for file_name in sorted(file_names):
            path = current / file_name
            relative = path.relative_to(root)
            if not is_excluded(relative):
                yield path, relative


def head_short_sha(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "--short", "HEAD"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def create_backup(root: Path | None = None) -> Path:
    root = (root or repository_root()).resolve()
    backup_directory = root / "BACKUP"
    backup_directory.mkdir(exist_ok=True)
    now = datetime.now(UTC)
    timestamp = now.strftime("%Y%m%dT%H%M%S")
    microseconds = f"{now.microsecond:06d}"
    archive_name = (
        f"{root.name}_{timestamp}_{microseconds}Z_{head_short_sha(root)}.zip"
    )
    archive_path = backup_directory / archive_name

    try:
        with zipfile.ZipFile(
            archive_path, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9
        ) as archive:
            for path, relative in iter_source_files(root):
                archive.write(path, relative.as_posix())
        with zipfile.ZipFile(archive_path, "r") as archive:
            bad_member = archive.testzip()
            if bad_member is not None:
                raise OSError(f"ZIP integrity check failed for {bad_member}")
    except Exception:
        archive_path.unlink(missing_ok=True)
        raise

    backups = sorted(
        backup_directory.glob(f"{root.name}_*.zip"),
        key=lambda item: item.stat().st_mtime_ns,
        reverse=True,
    )
    for old_archive in backups[KEEP_BACKUPS:]:
        old_archive.unlink()

    digest = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    print(f"Backup created: {archive_path}")
    print(f"SHA256: {digest}")
    return archive_path


def main() -> int:
    try:
        create_backup()
    except Exception as error:
        print(f"Backup failed: {type(error).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
