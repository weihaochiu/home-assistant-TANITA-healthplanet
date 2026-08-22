"""Audit tracked/staged files and backups without printing secret values."""

from __future__ import annotations

import json
import re
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

try:
    from .research_healthplanet_backend import ConfigurationError, load_credentials
except ImportError:  # Direct script execution places scripts/ on sys.path.
    from research_healthplanet_backend import ConfigurationError, load_credentials

ROOT = Path(__file__).resolve().parents[1]
PROBE_PATH = ROOT / "_local_only" / "healthplanet_schema_probe.json"
FORBIDDEN_ARCHIVE_PATTERNS = (
    re.compile(r"(?:^|/)\.git(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)\.env(?:\.|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)_local_only(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:^|/)BACKUP(?:/|$)", re.IGNORECASE),
    re.compile(r"(?:cookie|session|token|\.har$|raw_response|\.log$)", re.IGNORECASE),
)
FORBIDDEN_PROBE_KEYS = {
    "account_id",
    "authorization",
    "cookie",
    "headers",
    "login_id",
    "measurement_value",
    "password",
    "raw_response",
    "session_id",
    "token",
    "value",
}
SUSPICIOUS_TRACKED_PATTERNS = (
    re.compile(r"(?im)^\s*(?:cookie|authorization)\s*:\s*\S+"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]{12,}"),
    re.compile(r"(?i)(?:session|token)[_-]?(?:id|value)?\s*[=:]\s*['\"][^'\"]{12,}"),
)


def _git_paths(*args: str) -> list[Path]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return [ROOT / line for line in result.stdout.splitlines() if line]


def _contains_secret(data: bytes, secrets: tuple[bytes, ...]) -> bool:
    return any(secret and secret in data for secret in secrets)


def _probe_key_audit(value: Any, *, path: tuple[str, ...] = ()) -> list[str]:
    failures: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            normalized = re.sub(r"[^a-z0-9]", "_", str(key).casefold()).strip("_")
            if normalized in FORBIDDEN_PROBE_KEYS:
                failures.append("probe_forbidden_key:" + ".".join((*path, str(key))))
            failures.extend(_probe_key_audit(child, path=(*path, str(key))))
    elif isinstance(value, list):
        for child in value:
            failures.extend(_probe_key_audit(child, path=path))
    return failures


def run_audit() -> list[str]:
    failures: list[str] = []
    try:
        login_id, password = load_credentials()
    except ConfigurationError:
        return ["credential_source_unavailable"]
    secrets = (login_id.encode(), password.encode())
    login_id = ""
    password = ""

    tracked = set(_git_paths("ls-files"))
    staged = set(_git_paths("diff", "--cached", "--name-only", "--diff-filter=ACMR"))
    for path in sorted(tracked | staged):
        if not path.is_file():
            continue
        data = path.read_bytes()
        if _contains_secret(data, secrets):
            failures.append(f"credential_in_repository:{path.relative_to(ROOT)}")
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            text = ""
        if any(pattern.search(text) for pattern in SUSPICIOUS_TRACKED_PATTERNS):
            failures.append(f"suspicious_secret_pattern:{path.relative_to(ROOT)}")

    for archive_path in sorted((ROOT / "BACKUP").glob("*.zip")):
        try:
            with zipfile.ZipFile(archive_path) as archive:
                if archive.testzip() is not None:
                    failures.append(f"backup_integrity:{archive_path.name}")
                for member in archive.infolist():
                    name = member.filename
                    if any(pattern.search(name) for pattern in FORBIDDEN_ARCHIVE_PATTERNS):
                        failures.append(f"backup_forbidden_path:{archive_path.name}:{name}")
                        continue
                    if not member.is_dir() and _contains_secret(archive.read(member), secrets):
                        failures.append(f"credential_in_backup:{archive_path.name}:{name}")
        except (OSError, zipfile.BadZipFile):
            failures.append(f"backup_unreadable:{archive_path.name}")

    if PROBE_PATH.is_file():
        try:
            probe = json.loads(PROBE_PATH.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            failures.append("probe_invalid_json")
        else:
            failures.extend(_probe_key_audit(probe))
            serialized = json.dumps(probe, ensure_ascii=False).encode()
            if _contains_secret(serialized, secrets):
                failures.append("credential_in_probe")
    secrets = ()
    return sorted(set(failures))


def main() -> int:
    failures = run_audit()
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}", file=sys.stderr)
        return 1
    print("PASS: repository, backups, and sanitized probe contain no detected secrets")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
