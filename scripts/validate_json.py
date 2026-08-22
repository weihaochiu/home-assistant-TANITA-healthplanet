"""Validate every tracked JSON document without printing its content."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.json"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    paths = [ROOT / line for line in output.splitlines()]
    for path in paths:
        json.loads(path.read_text(encoding="utf-8"))
    print(f"PASS: valid JSON files={len(paths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
