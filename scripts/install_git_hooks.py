"""Install this repository's version-controlled Git hooks."""

from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    subprocess.run(
        ["git", "config", "core.hooksPath", ".githooks"], cwd=root, check=True
    )
    hook = root / ".githooks" / "pre-push"
    try:
        hook.chmod(hook.stat().st_mode | 0o111)
    except OSError:
        # Git for Windows executes the hook through its shebang without POSIX mode bits.
        pass
    configured = subprocess.run(
        ["git", "config", "--get", "core.hooksPath"],
        cwd=root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if configured != ".githooks":
        raise RuntimeError("Git hook path verification failed")
    print("Git hooks installed from .githooks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

