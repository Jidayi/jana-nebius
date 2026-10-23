"""Branching and release candidates (OPS-05).

Development is trunk-based on `main`. A release is cut on `release/<major>.<minor>`; every candidate is a tag
`v<version>-rc.<n>` (and the final `v<version>`) built by CI from that tag. Each release artefact carries a provenance
attestation naming its commit, tag and branch; the publish step refuses an artefact whose attestation does not name a
tag on a `release/` branch that points at the attested commit, or whose version does not match the tag.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any

TAG = re.compile(r"^v((0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*))(-rc\.[1-9]\d*)?$")
BRANCH = re.compile(r"^release/(0|[1-9]\d*)\.(0|[1-9]\d*)$")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()


def attestation(repo: Path, artefact: str, version: str, sha256: str, tag: str, branch: str) -> dict[str, Any]:
    return {"artefact": artefact, "version": version, "sha256": sha256, "tag": tag, "branch": branch,
            "commit": _git(repo, "rev-parse", f"{tag}^{{commit}}"), "builder": "ci"}  # fmt: skip


def provenance_errors(record: dict[str, Any], repo: Path) -> list[str]:
    """Why the publish step must refuse this artefact (empty when it was built from a release tag)."""
    tag, branch, commit = str(record.get("tag") or ""), str(record.get("branch") or ""), str(record.get("commit") or "")
    errors = []
    match = TAG.match(tag)
    if not match:
        return [f"{record.get('artefact')}: no release tag (v<version>[-rc.<n>]) in its provenance (OPS-05)"]
    if not BRANCH.match(branch):
        errors.append(f"{record.get('artefact')}: built from {branch or 'no branch'}, not a release/<major>.<minor> "
                      "branch (OPS-05)")  # fmt: skip
    elif branch != f"release/{match[2]}.{match[3]}":
        errors.append(f"{record.get('artefact')}: tag {tag} does not belong on {branch}")
    if record.get("artefact_kind", "app") == "app" and record.get("version") != tag[1:]:
        errors.append(f"{record.get('artefact')}: version {record.get('version')} does not match tag {tag}")
    try:
        tagged = _git(repo, "rev-parse", f"{tag}^{{commit}}")
    except subprocess.CalledProcessError:
        return [*errors, f"{record.get('artefact')}: tag {tag} does not exist"]
    if tagged != commit:
        errors.append(f"{record.get('artefact')}: tag {tag} points at {tagged[:12]}, not the attested {commit[:12]}")
    try:
        _git(repo, "merge-base", "--is-ancestor", commit, branch)
    except subprocess.CalledProcessError:
        errors.append(f"{record.get('artefact')}: commit {commit[:12]} is not on {branch}")
    return errors
