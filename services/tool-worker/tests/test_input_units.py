"""INP-09: formatted aliases retain the exact typed magnitude and authoritative unit."""

from __future__ import annotations

import json
from fractions import Fraction
from pathlib import Path

import pytest
from tool_worker.functions.units import parse_quantity, parse_unit

GOLDENS = json.loads((Path(__file__).resolve().parents[3] / "packages/ui/gallery/unit-entry-golden.json").read_text())


@pytest.mark.parametrize("case", GOLDENS, ids=lambda row: row["id"])
def inp09_units_golden(case: dict) -> None:
    quantity = parse_quantity(case["serialised"])
    assert quantity.magnitude == Fraction(case["magnitude"])
    assert quantity.units == parse_unit(case["unit"])
    assert quantity.to(case["unit"]).magnitude == Fraction(case["magnitude"])
