"""PRV-07, PRV-21, EVL-22, TRN-01: checked evidence formats, separate from approvals.

The formats are the `ops/governance-records` contract (D92), selected by `$defs` name. A kind the contract does not
define yet is read from the proposed additions at the repository root (`contract-additions-gates.json`, the local
copy until the specification adopts them); once the contract has the definition, the contract's is used."""

from __future__ import annotations

import json
from functools import cache
from typing import Any

from agent_core.contracts import document
from agent_core.contracts import errors as contract_errors

from .. import REPO_ROOT

CONTRACT = "ops/governance-records"
ADDITIONS = REPO_ROOT / "contract-additions-gates.json"


def schema() -> dict[str, Any]:
    return document(CONTRACT)


@cache
def _proposed() -> dict[str, Any]:
    """The governance-records definitions the additions propose, by `$defs` name, plus any new contract they add."""
    if not ADDITIONS.is_file():
        return {}
    found: dict[str, Any] = {}
    for entry in json.loads(ADDITIONS.read_text())["additions"]:
        if entry["target"] == "ops/governance-records.schema.json" and entry["pointer"].startswith("/$defs/"):
            found[entry["pointer"].removeprefix("/$defs/")] = entry["value"]
        elif entry["pointer"] == "":
            found[entry["target"].removesuffix(".schema.json")] = entry["value"]
    return found


def known(kind: str) -> bool:
    return kind in schema()["$defs"] or kind in _proposed()


def _local_errors(kind: str, record: Any) -> list[str]:
    from jsonschema import Draft202012Validator

    base = schema()
    proposed = _proposed()
    if "/" in kind:  # a whole proposed contract, such as ops/dpia-list
        root: dict[str, Any] = proposed[kind]
    else:
        merged = {**base, "$defs": {**proposed, **base["$defs"]}}
        merged.pop("$id", None)
        root = {**merged, "$ref": f"#/$defs/{kind}"}
    validator = Draft202012Validator(root, format_checker=Draft202012Validator.FORMAT_CHECKER)
    return sorted(f"{e.json_path}: {e.message}" for e in validator.iter_errors(record))


def errors(kind: str, record: Any) -> list[str]:
    """Contract problems, then any value still holding a fill-in template or rehearsal marker: a template's free-text
    placeholders would otherwise satisfy a non-empty string field."""
    from jana_tools.evidence.placeholders import placeholder_errors

    if kind in schema()["$defs"]:
        problems = contract_errors(f"{CONTRACT}#/$defs/{kind}", record)
    elif kind in _proposed():
        problems = _local_errors(kind, record)
    else:
        raise KeyError(f"unknown governance record {kind!r}")
    return [f"{kind}: {problem}" for problem in problems] + placeholder_errors(kind, record)
