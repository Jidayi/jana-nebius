"""Validate the public policy inputs before emitting runtime data."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

STAGES = frozenset(f"S{n}" for n in range(1, 6))


def _unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError(f"duplicate policy key {name!r}")
        result[name] = value
    return result


def read_policy(folder: Path, name: str) -> tuple[bytes, dict[str, Any]]:
    path = folder / f"{name}.json"
    raw = path.read_bytes()
    data = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(data, dict) or not data:
        raise ValueError(f"{path}: policy must be a nonempty object")
    for key, value in data.items():
        valid = isinstance(key, str) and re.fullmatch(r"[a-z][a-z_]*", key) is not None
        if name == "event_registry":
            valid = valid and isinstance(value, str) and value in {"local", "consented"}
        elif name == "item_types":
            valid = (
                valid
                and isinstance(value, dict)
                and set(value) == {"stage", "marker"}
                and isinstance(value["stage"], str)
                and value["stage"] in STAGES
                and isinstance(value["marker"], str)
                and bool(value["marker"].strip())
            )
        elif name == "availability":
            valid = valid and len(key) == 3 and isinstance(value, dict) and set(value) == {"o", "a"}
            if valid:
                for rows in value.values():
                    if not isinstance(rows, list) or not rows:
                        valid = False
                        break
                    seen = set()
                    for row in rows:
                        if not (
                            isinstance(row, list)
                            and len(row) == 2
                            and isinstance(row[0], str)
                            and row[0] in STAGES
                            and row[0] not in seen
                            and (row[1] is None or (isinstance(row[1], str) and bool(row[1].strip())))
                        ):
                            valid = False
                            break
                        seen.add(row[0])
        else:
            raise ValueError(f"unknown generated policy {name!r}")
        if not valid:
            raise ValueError(f"{path}: invalid {name} entry {key!r}")
    return raw, data
