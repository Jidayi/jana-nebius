"""The form as written is never evaluated, so parsing it asks SymPy nothing about its non-canonical nodes.

SymPy's answers about a node that evaluation would have removed (the -1*0 the form of `7 - (0)` keeps) depend on the
order the facts are asked in, and SymPy caches the node and what it learnt for every later call in the worker. A
contradiction learnt there failed an unrelated later check with InconsistentAssumptions
(`itm.mth.o.coordinate_geometry.0061`, 2026-10-19)."""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from typing import Any

import pytest
import sympy as sp
from tool_worker.grammar import parse

assumptions = importlib.import_module("sympy.core.assumptions")

WRITTEN = [
    "sqrt((2 - (-2))^2 + (7 - (0))^2)",
    "\\sqrt{(7-(0))^2}",
    "\\sqrt[3]{7-(0)}",
    "\\left|7-(0)\\right|",
    "sin(7 - (0))",
    "3*0 + sqrt(2*0)",
]


@pytest.fixture
def asked(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[sp.Basic]]:
    seen: list[sp.Basic] = []
    ask = assumptions._ask

    def recording(fact: str, obj: sp.Basic) -> Any:
        seen.append(obj)
        return ask(fact, obj)

    monkeypatch.setattr(assumptions, "_ask", recording)
    yield seen


@pytest.mark.parametrize("text", WRITTEN)
def test_form_as_written_asks_no_facts(text: str, asked: list[sp.Basic]) -> None:
    written = parse(text).as_written
    # Numbers and symbols are canonical in any form; SymPy answers for them in any order.
    assert not [obj for obj in asked if obj.args and obj in set(sp.preorder_traversal(written))]
