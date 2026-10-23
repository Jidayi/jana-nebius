"""The proposed clipboard documents retain the fixture's exact authoritative maths meaning."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tool_worker.grammar import parse

CASES = json.loads((Path(__file__).resolve().parents[3] / "packages/ui/gallery/paste-golden.json").read_text())


@pytest.mark.parametrize("case", CASES, ids=lambda row: row["id"])
def inp13_paste_normalisation(case: dict) -> None:
    math = [node["attrs"]["latex"] for node in case["document"]["content"][0]["content"] if node["type"] == "math"]
    assert len(math) == len(case["expected_math"])
    for latex, expected in zip(math, case["expected_math"], strict=True):
        assert parse(latex, variables=frozenset({"x"})).tree == parse(expected, variables=frozenset({"x"})).tree
