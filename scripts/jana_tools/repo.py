"""Helpers for reading the repository as git sees it."""

from __future__ import annotations

import subprocess
from pathlib import Path


def _git_paths(root: Path, *args: str) -> set[str]:
    out = subprocess.run(["git", "ls-files", "-z", *args], cwd=root, check=True, capture_output=True).stdout.decode()
    return {p for p in out.split("\0") if p}


def repo_paths(root: Path) -> list[str]:
    """Tracked files plus untracked files that are not gitignored, relative to root.

    An untracked symlink to a directory stands for that directory: the spec checkout linked at docs/ in a worktree,
    or installed node_modules linked from the main checkout. git lists such a link as a single path, so the
    directory-only ignore rules (`docs/`, `node_modules/`) never match it; it is left out, as the directory is."""
    tracked = _git_paths(root, "--cached")
    untracked = _git_paths(root, "--others", "--exclude-standard") - tracked
    linked_dirs = {p for p in untracked if (root / p).is_symlink() and (root / p).is_dir()}
    return sorted(p for p in tracked | (untracked - linked_dirs) if (root / p).exists())
