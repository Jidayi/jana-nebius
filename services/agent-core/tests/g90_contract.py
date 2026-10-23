"""The knows page's commands under the proposed G90 contract additions (D72).

Until the command contract carries them, replies are validated against the local copy of the proposal in
fixtures/g90/commands-additions.json; once the contract has a definition, against the contract itself, so these tests
follow the contract as soon as it is regenerated."""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

from agent_core.contracts import document
from agent_core.contracts import errors as contract_errors
from jsonschema import Draft202012Validator, FormatChecker

ADDITIONS = Path(__file__).parent / "fixtures" / "g90" / "commands-additions.json"


@cache
def additions() -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(ADDITIONS.read_text())
    return loaded


def g90_errors(definition: str, instance: Any) -> list[str]:
    """Every violation of one definition: the contract's when it has it, else the proposal's."""
    if definition in document("api/commands")["$defs"]:
        return contract_errors(f"api/commands#/$defs/{definition}", instance)
    schema = {"$defs": additions()["$defs"], "$ref": f"#/$defs/{definition}"}
    found = Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(instance)
    return sorted(f"{e.json_path}: {e.message}" for e in found)


def endpoints() -> list[dict[str, Any]]:
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    entries: list[dict[str, Any]] = additions()["x-endpoints"]
    return [ENDPOINTS_BY_KEY.get(f"{e['method']} {e['path']}", e) for e in entries]
