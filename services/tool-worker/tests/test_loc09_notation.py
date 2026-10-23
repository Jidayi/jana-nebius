"""The frontend's hand-authored notation goldens keep the same verified scalar meaning."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

import pytest
import sympy as sp
from tool_worker.functions.numeric import round_sf
from tool_worker.grammar import parse

ROOT = Path(__file__).resolve().parents[3]
GOLDENS = json.loads((ROOT / "packages/ui/gallery/notation-golden.json").read_text())
CASES = [row for row in GOLDENS if "expected_math" in row or row["area"] == "significant_figures"]


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["area"])
def loc09_notation_golden(case: dict) -> None:
    if case["area"] == "significant_figures":
        assert Decimal(case["shown"]) == round_sf(Decimal(str(case["value"])), case["figures"])
        return
    variables = frozenset({"x", "y"}) if case["area"] == "algebra" else frozenset()
    parsed = parse(case["latex"], variables=variables)
    actual = parsed.tree
    expected = sp.sympify(case["expected_math"], locals=parsed.symbols)
    assert sp.simplify(actual - expected) == 0
    if "alternate" in case:
        assert parse(case["alternate"], decimal_comma=True).tree == actual
