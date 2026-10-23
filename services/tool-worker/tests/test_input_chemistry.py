"""INP-08 UI goldens must reach the authoritative chemical grammar unchanged in meaning."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
from tool_worker.functions.formula import parse_equation, parse_formula
from tool_worker.protocol import WorkerError

GOLDENS = json.loads((Path(__file__).resolve().parents[3] / "packages/ui/gallery/chem-entry-golden.json").read_text())


@pytest.mark.parametrize("case", GOLDENS, ids=lambda row: row["id"])
def inp08_chem_entry_golden(case: dict) -> None:
    if case["kind"] == "formula":
        result = parse_formula(case["serialised"])
        assert result.counts == case["counts"] and result.charge == case["charge"]
        assert result.state == case["state"]
    else:
        result = parse_equation(case["serialised"])
        assert [t.species.counts for t in result.terms] == case["counts"]
        assert [t.coefficient or Fraction(1) for t in result.terms] == case["coefficients"]
        assert [t.species.state for t in result.terms] == case["states"]
        assert result.reversible == case.get("reversible", False)
        assert getattr(result, "conditions", None) == case.get("conditions")


@pytest.mark.parametrize("source", ["co", "cl", "Xx2", "CaCO3 ->[__import__] CaO", "H2 ->[<script>] H2"])
def test_chemistry_case_and_conditions_are_never_guessed_or_executed(source: str) -> None:
    with pytest.raises(WorkerError):
        (parse_equation if "->" in source else parse_formula)(source)
