"""LOC-10 over every S2 pack, plus negative controls for plain and explicit TeX quantities."""

from __future__ import annotations

from pathlib import Path

import pytest
from pack_builder.build import load_source
from pack_builder.qa import latex_strings, notation_problems

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("subject", ["phy", "chm", "acc", "mth"])
def loc10_unit_format(subject: str) -> None:
    source = load_source(ROOT / "content/curriculum" / subject / "o")
    assert len(source.tables["items"]) >= 500
    assert len(latex_strings(source.tables)) >= 2000
    assert notation_problems(source.tables) == []


@pytest.mark.parametrize("latex", [r"v=14\mathrm{m/s}", r"v=9,8\,\mathrm{m/s}", r"v=9{,}8\,\mathrm{m/s}"])
def test_explicit_unit_notation_blocks_publication(latex: str) -> None:
    tables = {
        "worked_examples": [
            {
                "id": "wex.phy.o.test.0001",
                "steps": [{"n": 1, "latex": latex}],
                "final_answer": {"latex": r"v=14\,\mathrm{m/s}"},
            }
        ]
    }
    problems = notation_problems(tables)
    assert len(problems) == 1 and "LOC-10" in problems[0]
