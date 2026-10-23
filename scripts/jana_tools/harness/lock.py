"""Frozen, hash-locked suites with held-out splits (EVL-18).

`evals/lock.json` records, per suite, the version and the sha256 of every file the suite locks. A gate run refuses
a suite whose files changed while its version in `evals/suites.toml` did not; a bumped version with a stale lock
asks for `eval lock --write`. Held-out items are stored encrypted (AES-256-GCM) beside their suite; only a release
run holding the key decrypts them, and a release run reports their results as aggregates only. A development run
cannot read them at all.
"""

from __future__ import annotations

import base64
import glob
import hashlib
import json
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pack_builder import heldout

from .. import REPO_ROOT

REGISTRY = REPO_ROOT / "evals" / "suites.toml"
LOCK = REPO_ROOT / "evals" / "lock.json"
HELD_OUT = REPO_ROOT / "evals" / "held-out"
KEY_ENV = "JANA_HELD_OUT_KEY"  # base64 of a 256-bit key; set only in the release pipeline
SPLITS = ("development", "held_out", "regression")


@dataclass(frozen=True)
class Suite:
    name: str
    owner: str
    cadence: str
    stage: str
    version: str
    files: tuple[str, ...]
    needs_model: bool = False
    device_lab: bool = False


def suites(registry: Path = REGISTRY) -> dict[str, Suite]:
    data = tomllib.loads(registry.read_text())["suites"]
    return {
        name: Suite(
            name,
            s["owner"],
            s["cadence"],
            s["stage"],
            s["version"],
            tuple(s["files"]),
            s.get("needs_model", False),
            s.get("device_lab", False),
        )
        for name, s in data.items()
    }


def file_hashes(suite: Suite, root: Path = REPO_ROOT) -> dict[str, str]:
    out = {}
    for pattern in suite.files:
        for path in sorted(glob.glob(str(root / pattern))):
            out[str(Path(path).relative_to(root))] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    held = root / "evals" / "held-out" / f"{suite.name}.enc"
    if held.is_file():
        out[str(held.relative_to(root))] = hashlib.sha256(held.read_bytes()).hexdigest()
    return out


def _split_policy() -> dict[str, Any]:
    from agent_core.config import Settings

    settings = Settings()
    return {"held_out_share": settings.eval_held_out_share, "splits": list(SPLITS),
            "held_out_runs_per_candidate": settings.eval_held_out_runs_per_candidate}  # fmt: skip


def build_lock(registry: Path = REGISTRY, root: Path = REPO_ROOT) -> dict[str, Any]:
    return {
        "version": 1,
        "split_policy": _split_policy(),
        "suites": {
            name: {"version": s.version, "files": file_hashes(s, root)} for name, s in sorted(suites(registry).items())
        },
    }


def write_lock(registry: Path = REGISTRY, lock: Path = LOCK, root: Path = REPO_ROOT) -> None:
    lock.write_text(json.dumps(build_lock(registry, root), indent=1, sort_keys=True) + "\n")


def lock_errors(registry: Path = REGISTRY, lock: Path = LOCK, root: Path = REPO_ROOT) -> list[str]:
    """Why a gate run must not report from these suites (empty when every suite matches its lock)."""
    if not lock.is_file():
        return ["evals/lock.json is missing; run: python -m jana_tools eval lock --write"]
    locked = json.loads(lock.read_text())["suites"]
    errors = []
    for name, suite in sorted(suites(registry).items()):
        entry = locked.get(name)
        current = file_hashes(suite, root)
        if entry is None:
            errors.append(f"{name}: not in the lock; run: python -m jana_tools eval lock --write")
        elif entry["files"] != current:
            changed = sorted(set(entry["files"].items()) ^ set(current.items()))
            paths = sorted({p for p, _ in changed})
            if entry["version"] == suite.version:
                errors.append(f"{name}: {', '.join(paths)} changed without a version bump (locked {suite.version})")
            else:
                errors.append(f"{name}: version {suite.version} is not locked yet; run: python -m jana_tools eval lock "
                              "--write")  # fmt: skip
        elif entry["version"] != suite.version:
            errors.append(f"{name}: version changed to {suite.version} but the lock says {entry['version']}")
    return errors


# --- held-out items ---------------------------------------------------------------------------------------------------


class HeldOutInaccessibleError(PermissionError):
    """A development run asked for held-out items, or the release key is absent."""


def new_key() -> str:
    return base64.b64encode(AESGCM.generate_key(bit_length=256)).decode()


def seal(items: list[dict[str, Any]], suite: str, key: str, out_dir: Path = HELD_OUT) -> Path:
    """Encrypt a suite's held-out items; their id and text hashes go beside them for the leakage check (EVL-24) and
    the pack build's exclusion (CUR-22)."""
    return heldout.seal(items, suite, key, out_dir)


def held_out_items(suite: str, mode: str, out_dir: Path = HELD_OUT) -> list[dict[str, Any]]:
    """The held-out items, for a release run only (never a development run)."""
    if mode != "release":
        raise HeldOutInaccessibleError(f"{suite}: held-out items are read only by a release run")
    key = os.environ.get(KEY_ENV)
    if not key:
        raise HeldOutInaccessibleError(f"{suite}: the release key ({KEY_ENV}) is not set")
    return heldout.open_sealed(suite, key, out_dir)


def held_out_hashes(out_dir: Path = HELD_OUT) -> set[str]:
    found: set[str] = set()
    for path in out_dir.glob("*.hashes.json"):
        found.update(json.loads(path.read_text()))
    return found
