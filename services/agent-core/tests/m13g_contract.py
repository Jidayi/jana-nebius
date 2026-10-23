"""The subject map and lesson player's contract (D78): replies are validated against the bundled command contract,
and the endpoints are the generated endpoint table's entries for these paths."""

from __future__ import annotations

from typing import Any

from agent_core.contracts import errors as contract_errors
from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

PATHS = (
    "/v1/curriculum/{subject_id}/map",
    "/v1/lessons/{lesson_id}",
    "/v1/lessons/{lesson_id}/position",
    "/v1/lessons/{lesson_id}/checks",
)


def m13g_errors(definition: str, instance: Any) -> list[str]:
    """Every violation of one definition of the command contract."""
    return contract_errors(f"api/commands#/$defs/{definition}", instance)


def endpoints() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = [e for e in ENDPOINTS_BY_KEY.values() if e["path"] in PATHS]
    return entries
