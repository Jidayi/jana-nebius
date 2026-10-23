"""Template and rehearsal markers that no evidence gate accepts.

Every fill-in template under scripts/governance/evidence/templates writes `FILL-IN` into each value the owner must
supply, and a drill rehearsal (`--dry-run`) writes `DRY-RUN` into what it produces. A record that still carries
either marker anywhere, in a key or a value, is refused by the M23 governance checks and by the M24 field-evidence
reader, so a template or a rehearsal can never stand in for a real exercise.
"""

from __future__ import annotations

from typing import Any

FILL_IN = "FILL-IN"
DRY_RUN = "DRY-RUN"
MARKERS = (FILL_IN, DRY_RUN)


def placeholder_paths(value: Any, path: str = "$") -> list[str]:
    """JSON paths of every key or string value that still carries a template or rehearsal marker."""
    found: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            where = f"{path}.{key}"
            if isinstance(key, str) and any(marker in key for marker in MARKERS):
                found.append(where)
            found += placeholder_paths(child, where)
    elif isinstance(value, list | tuple):
        for index, child in enumerate(value):
            found += placeholder_paths(child, f"{path}[{index}]")
    elif isinstance(value, str) and any(marker in value for marker in MARKERS):
        found.append(path)
    return found


def placeholder_errors(label: str, value: Any) -> list[str]:
    return [
        f"{label}: {where} is still a template placeholder or rehearsal value" for where in placeholder_paths(value)
    ]
