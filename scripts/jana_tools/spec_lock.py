"""ARC-16 specification pin: spec.lock holds the commit of the private specification
repository this monorepo builds against; docs/ must be that commit and must verify."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HASH = re.compile(r"^[0-9a-f]{40}$")


def read_lock(root: Path) -> str:
    return (root / "spec.lock").read_text().strip()


def spec_lock_errors(root: Path, docs: Path | None = None) -> list[str]:
    docs = docs or root / "docs"
    lock_file = root / "spec.lock"
    if not lock_file.is_file():
        return ["spec.lock is missing"]
    pinned = read_lock(root)
    if not HASH.match(pinned):
        return ["spec.lock must hold exactly one 40-character commit hash"]
    head = subprocess.run(["git", "-C", str(docs), "rev-parse", "HEAD"], capture_output=True, text=True)
    if head.returncode != 0:
        return [f"{docs} is not a git checkout of the specification"]
    if head.stdout.strip() != pinned:
        return [f"docs/ is at {head.stdout.strip()} but spec.lock pins {pinned}"]
    status = subprocess.run(
        ["git", "-C", str(docs), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=True,
    )
    if status.stdout.strip():
        return ["docs/ has uncommitted changes; spec.lock must identify the complete specification being verified"]
    verify = subprocess.run(
        [sys.executable, str(docs / "tools" / "verify_spec.py")],
        capture_output=True,
        text=True,
    )
    if verify.returncode != 0:
        tail = (verify.stdout + verify.stderr).strip().splitlines()[-5:]
        return ["the pinned specification fails verify_spec.py", *tail]
    return []
