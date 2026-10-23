"""Registry snapshot (TOL-05): a change to a tool's schema or defaults must come with a version bump.

python -m jana_tools tools-snapshot --write   # after bumping a version deliberately
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import REPO_ROOT

SNAPSHOT = REPO_ROOT / "services" / "agent-core" / "agent_core" / "tools" / "registry.snapshot.json"


def _sha(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def snapshot() -> dict[str, dict[str, Any]]:
    from agent_core.tools.specs import specs

    return {s.name: {"version": s.version, "params_sha256": _sha(s.params), "params_small_sha256": _sha(s.params_small)}
            for s in specs()}  # fmt: skip


def snapshot_errors(current: dict[str, dict[str, Any]], committed: dict[str, dict[str, Any]]) -> list[str]:
    errors = []
    for name, now in sorted(current.items()):
        before = committed.get(name)
        if before is None:
            errors.append(f"{name}: not in the registry snapshot (run tools-snapshot --write)")
            continue
        changed = now["params_sha256"] != before["params_sha256"]
        projection = now["params_small_sha256"] != before["params_small_sha256"]
        if changed and now["version"] <= before["version"]:
            errors.append(f"{name}: schema or defaults changed without a version bump (still {now['version']})")
        elif not changed and now["version"] != before["version"]:
            errors.append(f"{name}: version changed but the snapshot was not updated")
        elif changed:
            errors.append(f"{name}: version bumped; update the snapshot (tools-snapshot --write)")
        elif projection:
            # The small-profile schema is a projection of the full one: no version change, but it is reviewed.
            errors.append(f"{name}: small-profile schema changed; update the snapshot (tools-snapshot --write)")
    errors += [f"{name}: in the snapshot but not registered" for name in sorted(set(committed) - set(current))]
    return errors


def committed() -> dict[str, dict[str, Any]]:
    data: dict[str, dict[str, Any]] = json.loads(SNAPSHOT.read_text()) if SNAPSHOT.is_file() else {}
    return data


def write(path: Path = SNAPSHOT) -> None:
    path.write_text(json.dumps(snapshot(), indent=1, sort_keys=True) + "\n")
