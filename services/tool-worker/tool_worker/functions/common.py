"""Helpers shared by the compute functions: parsing with the call's options, and errors."""

from __future__ import annotations

from typing import Any

from tool_worker.grammar import Parsed, ParseRejected, TooLarge, parse
from tool_worker.protocol import Code, WorkerError
from tool_worker.registry import CallContext

ASSUMPTION_FLAGS = {"positive": "positive", "nonzero": "nonzero", "integer": "integer", "nonnegative": "nonnegative"}


def parse_arg(text: str, args: dict[str, Any], field: str = "text", *, imaginary_unit: bool = False) -> Parsed:
    """Parse one argument; grammar errors become PARSE_REJECTED with the position, size breaches LIMIT_EXCEEDED.
    With `imaginary_unit` the letter `i` is parsed as a non-real symbol (never simplified as a real variable), for the
    caller to replace with the imaginary unit (VER-30)."""
    assumptions = {
        name: {ASSUMPTION_FLAGS[flag]: True for flag in flags} for name, flags in args.get("assumptions", {}).items()
    }
    if imaginary_unit:
        assumptions["i"] = {"real": False, "imaginary": True}
    try:
        return parse(
            text,
            variables=frozenset(args.get("variables", [])),
            assumptions=assumptions,
            log_base=int(args.get("log_base", 10)),  # base 10 unless the pack says otherwise (VER-03)
            decimal_comma=bool(args.get("decimal_comma", False)),
        )
    except ParseRejected as error:
        raise WorkerError(Code.PARSE_REJECTED, f"{field}: {error}", position=error.position) from None
    except TooLarge as error:
        raise WorkerError(Code.LIMIT_EXCEEDED, f"{field}: {error}", limit=error.limit) from None


def convention(context: CallContext, key: str) -> tuple[Any, str] | None:
    """A convention sent with the call, in the worker protocol's shape (`{value, source}`, unit optional), as
    (value, source); None when the call states none. The host sends each pack setting under one flat key such as
    `numeric.sf` (G103, G104)."""
    held = context.conventions.get(key) if isinstance(context.conventions, dict) else None
    if isinstance(held, dict) and "value" in held:
        return held["value"], str(held.get("source", "pack"))
    return None
