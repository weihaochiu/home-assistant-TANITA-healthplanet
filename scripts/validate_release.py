"""Validate stable release metadata and immutable annotated tags."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "custom_components" / "tanita_healthplanet" / "manifest.json"
CONSTANTS = ROOT / "custom_components" / "tanita_healthplanet" / "const.py"
STABLE_TAG = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+$")


class ReleaseValidationError(ValueError):
    """Raised when release metadata or Git state is unsafe."""


def _constant_strings(path: Path) -> dict[str, str]:
    """Return top-level string constants without importing integration code."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    values: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if (
            isinstance(target, ast.Name)
            and isinstance(node.value, ast.Constant)
            and isinstance(node.value.value, str)
        ):
            values[target.id] = node.value.value
    return values


def validate_release_metadata(root: Path, tag: str) -> str:
    """Validate stable tag, manifest, VERSION, and USER_AGENT consistency."""
    if STABLE_TAG.fullmatch(tag) is None:
        raise ReleaseValidationError("release_tag_not_stable_semver")
    version = tag.removeprefix("v")
    manifest_path = root / MANIFEST.relative_to(ROOT)
    constants_path = root / CONSTANTS.relative_to(ROOT)
    manifest: dict[str, Any] = json.loads(manifest_path.read_text(encoding="utf-8"))
    constants = _constant_strings(constants_path)
    if manifest.get("version") != version:
        raise ReleaseValidationError("manifest_version_mismatch")
    if constants.get("VERSION") != version:
        raise ReleaseValidationError("constant_version_mismatch")
    if constants.get("USER_AGENT") != f"home-assistant-TANITA-healthplanet/{version}":
        raise ReleaseValidationError("user_agent_version_mismatch")
    return version


def _git(*args: str) -> str:
    """Run a read-only Git query and return stripped stdout."""
    return subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def validate_annotated_tag(tag: str, *, require_main_head: bool) -> str:
    """Require an annotated tag at checked-out HEAD and optionally origin/main."""
    reference = f"refs/tags/{tag}"
    if _git("cat-file", "-t", reference) != "tag":
        raise ReleaseValidationError("release_tag_not_annotated")
    target = _git("rev-list", "-n", "1", reference)
    if target != _git("rev-parse", "HEAD"):
        raise ReleaseValidationError("release_tag_not_at_head")
    if require_main_head and target != _git("rev-parse", "refs/remotes/origin/main"):
        raise ReleaseValidationError("release_tag_not_at_origin_main")
    return target


def main() -> int:
    """Validate arguments and report only non-sensitive release metadata."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True)
    parser.add_argument("--require-annotated-tag", action="store_true")
    parser.add_argument("--require-main-head", action="store_true")
    args = parser.parse_args()
    try:
        version = validate_release_metadata(ROOT, args.tag)
        target = "not_checked"
        if args.require_annotated_tag:
            target = validate_annotated_tag(
                args.tag,
                require_main_head=args.require_main_head,
            )
    except (ReleaseValidationError, OSError, subprocess.CalledProcessError) as error:
        print(f"FAIL: {error}")
        return 1
    print(f"PASS: release_tag={args.tag} version={version} target={target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
