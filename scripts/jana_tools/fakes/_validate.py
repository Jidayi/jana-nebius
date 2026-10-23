"""Contract validation for the fakes (the same generated runtime the core uses)."""

from __future__ import annotations

from typing import Any

from agent_core.contracts import ContractViolationError, errors


def check(contract: str, instance: Any, where: str) -> None:
    problems = errors(contract, instance)
    if problems:
        raise ContractViolationError(f"{contract} ({where})", problems)
