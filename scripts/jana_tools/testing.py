"""Helpers shared by repository tests."""

from __future__ import annotations

import subprocess
from pathlib import Path


def git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", "-c", "commit.gpgsign=false", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )
