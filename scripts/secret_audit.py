"""Deep privacy audit for the working tree, Git objects, and source backups.

The scanner never prints a matched value. Findings contain only a location, risk
category, optional object identifier, and a first-two/last-two masked summary.
It intentionally does not require or read `.env.local`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import zipfile
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, cast

ROOT = Path(__file__).resolve().parents[1]
PROBE_RELATIVE_PATH = PurePosixPath("_local_only/healthplanet_schema_probe.json")
BACKUP_LIMIT = 10
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
SENSITIVE_ASSIGNMENT = re.compile(
    rb"(?i)[\"']?(?:healthplanet_password|password|passwd|client_secret|access_token|"
    rb"refresh_token|session_id|cookie|authorization)[\"']?\s*[=:]\s*"
    rb"[\"']?([^\s\"',}\]]{6,})"
)
EMAIL_PATTERN = re.compile(
    r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}",
    re.IGNORECASE | re.ASCII,
)
SAFE_EMAIL_LIKE_LITERALS = {"icon@2x.png"}
HEADER_SECRET_PATTERN = re.compile(rb"(?im)^\s*(?:cookie|authorization)\s*:\s*([^\r\n]{6,})")
STRUTS_TOKEN_VALUE_PATTERN = re.compile(
    rb"(?i)org\.apache\.struts\.taglib\.html\.TOKEN\s*[=:]\s*"
    rb"[\"']?([^\s\"',}\]]{6,})"
)
GITHUB_TOKEN_VALUE_PATTERN = re.compile(rb"(?i)\b(?:ghp_[a-z0-9]{20,}|github_pat_[a-z0-9_]{20,})\b")
WINDOWS_USER_PATH = re.compile(rb"(?i)[A-Z]:\\Users\\([^\\\r\n]{2,})")
MEASUREMENT_TIMESTAMP = re.compile(rb"[\"'](\d{12}(?:\d{2})?)[\"']")
SAFE_LITERAL_MARKERS = (
    b"synthetic",
    b"placeholder",
    b"example.invalid",
    b"fixture",
    b"do-not-use",
    b"never-use",
)
CONFIG_LIKE_SUFFIXES = {
    ".cfg",
    ".conf",
    ".dump",
    ".env",
    ".har",
    ".ini",
    ".json",
    ".log",
    ".text",
    ".trace",
    ".txt",
    ".yaml",
    ".yml",
}
SKIPPED_WORKING_DIRECTORIES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "BACKUP",
    "__pycache__",
    "htmlcov",
}


@dataclass(frozen=True, order=True)
class Finding:
    location: str
    risk: str
    object_id: str = ""
    masked: str = ""


def _run_git(*args: str, text: bool = False) -> bytes | str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=text,
    )
    return result.stdout


def _mask(value: bytes) -> str:
    cleaned = value.strip().decode("utf-8", errors="replace")
    if not cleaned:
        return ""
    if len(cleaned) <= 4:
        return "**"
    return f"{cleaned[:2]}…{cleaned[-2:]}"


def _is_synthetic_path(path: PurePosixPath) -> bool:
    folded = path.as_posix().casefold()
    return folded.startswith("tests/") or "synthetic" in folded or "fixture" in folded


def _path_risks(path: PurePosixPath, *, allow_probe: bool) -> list[str]:
    folded_parts = tuple(part.casefold() for part in path.parts)
    name = path.name.casefold()
    suffix = path.suffix.casefold()
    risks: list[str] = []
    if name == ".env.example":
        return risks
    if name == ".env" or name.startswith(".env."):
        risks.append("environment_file")
    if "_local_only" in folded_parts and not (allow_probe and path == PROBE_RELATIVE_PATH):
        risks.append("local_only_artifact")
    if any(
        part in {"browser_exports", "screenshots"}
        or part.startswith(("temporary_probe", "probe_output"))
        for part in folded_parts
    ):
        risks.append("capture_directory")
    if suffix in {
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
    }:
        risks.append("sensitive_artifact_extension")
    if name in {"cookies.json", "session.json"}:
        risks.append("session_artifact")
    if name.startswith(("raw_response", "request_capture", "response_capture")):
        risks.append("raw_capture")
    if name.startswith("screenshot_") or "_screenshot." in name:
        risks.append("screenshot")
    return risks


def _safe_literal(value: bytes) -> bool:
    lowered = value.lower()
    return any(marker in lowered for marker in SAFE_LITERAL_MARKERS)


def _is_translation_metadata(path: PurePosixPath) -> bool:
    return path.name == "strings.json" or "translations" in {part.casefold() for part in path.parts}


def _content_findings(
    path: PurePosixPath,
    data: bytes,
    *,
    location: str,
    object_id: str = "",
) -> list[Finding]:
    if b"\x00" in data:
        return []
    findings: list[Finding] = []
    synthetic = _is_synthetic_path(path) or b'"synthetic": true' in data.lower()

    text = data.decode("utf-8", errors="ignore")
    for token_match in GITHUB_TOKEN_VALUE_PATTERN.finditer(data):
        findings.append(
            Finding(
                location,
                "hardcoded_github_token",
                object_id,
                _mask(token_match.group(0)),
            )
        )
    for email_match in EMAIL_PATTERN.finditer(text):
        value = email_match.group(0)
        if value.casefold() in SAFE_EMAIL_LIKE_LITERALS:
            continue
        context = text[max(0, email_match.start() - 64) : email_match.end() + 64].casefold()
        if not any(marker.decode() in context for marker in SAFE_LITERAL_MARKERS):
            findings.append(
                Finding(
                    location,
                    "email_like_identifier",
                    object_id,
                    _mask(value.encode()),
                )
            )

    if (
        path.suffix.casefold() in CONFIG_LIKE_SUFFIXES or path.name.startswith(".env")
    ) and not _is_translation_metadata(path):
        for pattern, risk in (
            (SENSITIVE_ASSIGNMENT, "secret_assignment"),
            (HEADER_SECRET_PATTERN, "secret_header"),
            (STRUTS_TOKEN_VALUE_PATTERN, "csrf_token_value"),
        ):
            for secret_match in pattern.finditer(data):
                secret_value = secret_match.group(1)
                if not _safe_literal(secret_value):
                    findings.append(Finding(location, risk, object_id, _mask(secret_value)))

    if not synthetic:
        for path_match in WINDOWS_USER_PATH.finditer(data):
            findings.append(
                Finding(location, "windows_user_path", object_id, _mask(path_match.group(1)))
            )
        if (
            path != PROBE_RELATIVE_PATH
            and path.suffix.casefold() == ".json"
            and re.search(rb'"value1"\s*:', data)
        ):
            findings.append(Finding(location, "unsanitized_graph_json", object_id))
        if path.suffix.casefold() == ".html" and b"healthplanet" in data.lower():
            findings.append(Finding(location, "possible_raw_healthplanet_html", object_id))
        if _path_risks(path, allow_probe=True):
            for timestamp_match in MEASUREMENT_TIMESTAMP.finditer(data):
                findings.append(
                    Finding(
                        location,
                        "measurement_timestamp",
                        object_id,
                        _mask(timestamp_match.group(1)),
                    )
                )
    return findings


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


def _working_tree_files() -> Iterable[tuple[PurePosixPath, Path]]:
    for directory, child_directories, filenames in os.walk(ROOT):
        child_directories[:] = [
            name for name in child_directories if name not in SKIPPED_WORKING_DIRECTORIES
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            relative = PurePosixPath(path.relative_to(ROOT).as_posix())
            yield relative, path


def _git_blob_entries() -> Iterable[tuple[str, PurePosixPath]]:
    commits = str(_run_git("rev-list", "--all", text=True)).splitlines()
    seen: set[tuple[str, str]] = set()
    for commit in commits:
        output = cast(bytes, _run_git("ls-tree", "-r", "-z", "--full-tree", commit))
        for entry in output.split(b"\x00"):
            if not entry or b"\t" not in entry:
                continue
            metadata, raw_path = entry.split(b"\t", 1)
            fields = metadata.split()
            if len(fields) != 3 or fields[1] != b"blob":
                continue
            object_id = fields[2].decode("ascii")
            path_text = raw_path.decode("utf-8", errors="surrogateescape")
            key = (object_id, path_text)
            if key in seen:
                continue
            seen.add(key)
            yield object_id, PurePosixPath(path_text)


def _scan_working_tree() -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    for relative, path in _working_tree_files():
        count += 1
        for risk in _path_risks(relative, allow_probe=True):
            findings.append(Finding(relative.as_posix(), risk))
        findings.extend(
            _content_findings(relative, path.read_bytes(), location=relative.as_posix())
        )
    return findings, count


def _scan_git_objects() -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    count = 0
    for object_id, path in _git_blob_entries():
        count += 1
        location = f"git:{path.as_posix()}"
        for risk in _path_risks(path, allow_probe=False):
            findings.append(Finding(location, risk, object_id))
        data = cast(bytes, _run_git("cat-file", "blob", object_id))
        findings.extend(_content_findings(path, data, location=location, object_id=object_id))
    return findings, count


def _scan_backups() -> tuple[list[Finding], int]:
    findings: list[Finding] = []
    archives = sorted((ROOT / "BACKUP").glob("*.zip"))
    if len(archives) > BACKUP_LIMIT:
        findings.append(Finding("BACKUP", "retention_exceeded"))
    for archive_path in archives:
        try:
            with zipfile.ZipFile(archive_path) as archive:
                bad_member = archive.testzip()
                if bad_member:
                    findings.append(
                        Finding(
                            archive_path.name, "backup_integrity", masked=_mask(bad_member.encode())
                        )
                    )
                for member in archive.infolist():
                    path = PurePosixPath(member.filename)
                    location = f"{archive_path.name}:{member.filename}"
                    for risk in _path_risks(path, allow_probe=False):
                        findings.append(Finding(location, risk))
                    if not member.is_dir():
                        findings.extend(
                            _content_findings(path, archive.read(member), location=location)
                        )
        except (OSError, zipfile.BadZipFile):
            findings.append(Finding(archive_path.name, "backup_unreadable"))
    return findings, len(archives)


def _validate_probe() -> list[Finding]:
    path = ROOT / PROBE_RELATIVE_PATH
    if not path.is_file():
        return []
    try:
        probe = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return [Finding(PROBE_RELATIVE_PATH.as_posix(), "probe_invalid_json")]
    return [Finding(PROBE_RELATIVE_PATH.as_posix(), risk) for risk in _probe_key_audit(probe)]


def run_audit() -> tuple[list[Finding], dict[str, int]]:
    working_findings, working_count = _scan_working_tree()
    git_findings, git_blob_count = _scan_git_objects()
    backup_findings, backup_count = _scan_backups()
    findings = working_findings + git_findings + backup_findings + _validate_probe()
    return sorted(set(findings)), {
        "working_files": working_count,
        "git_blobs": git_blob_count,
        "backups": backup_count,
    }


def main() -> int:
    try:
        findings, counts = run_audit()
    except (OSError, subprocess.CalledProcessError, UnicodeError):
        print("FAIL: audit_execution_error", file=sys.stderr)
        return 1
    if findings:
        for finding in findings:
            fields = [f"FAIL: {finding.risk}", f"location={finding.location}"]
            if finding.object_id:
                fields.append(f"object={finding.object_id}")
            if finding.masked:
                fields.append(f"masked={finding.masked}")
            print(" ".join(fields), file=sys.stderr)
        return 1
    print(
        "PASS: deep privacy audit "
        f"working_files={counts['working_files']} "
        f"git_blobs={counts['git_blobs']} backups={counts['backups']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
