"""Free-response maths items in the pack build (ASM-03, ASM-05, CUR-20): algebraic and equation-solutions items are
accepted once their keys are reproduced by their build checks, and refused otherwise. Packs are copies of the S1
physics source with synthetic records added; every item, key and check here is invented test data."""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.engine.marking import mark
from agent_core.store.packs import read_pack
from pack_builder import source as tree
from pack_builder.build import BuildError, build
from pack_builder.verify import Verifier

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "content" / "curriculum" / "phy" / "o"


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "src" / "phy" / "o"
    shutil.copytree(SOURCE, target)
    shutil.copytree(tree.ref_dir(SOURCE), tree.ref_dir(target))
    return target


def _problems(source: Path, tmp_path: Path) -> str:
    with pytest.raises(BuildError) as failed:
        build(source, tmp_path / "out")
    return "\n".join(failed.value.problems)


def _item(item_id: str, answers: list[dict[str, Any]], checks: dict[str, Any], hint: str | None = None
          ) -> dict[str, Any]:  # fmt: skip
    base = dict(yaml.safe_load((SOURCE / "items" / "itm.phy.o.motion.0041.yaml").read_text()))
    hints = [{"rung": n, "name": h["name"], "text": {"en": hint if hint and n == 1 else "Work one line at a time."}}
             for n, h in enumerate(base["parts"][0]["hints"], 1)]  # fmt: skip
    parts = [{"id": "ab"[n], "prompt": "Write it.", "marks": 2, "answer": a, "hints": hints}
             for n, a in enumerate(answers)]  # fmt: skip
    record = {**base, "id": item_id, "type": answers[0]["kind"], "stem": "Write the answer in full.", "parts": parts,
              "solution": {"steps": [{"n": 1, "latex": "\\text{see the key}", "reason": "The key",
                                      "check_id": answers[0]["check_id"]}]},
              "exam_style": {**base["exam_style"], "total_marks": 2 * len(answers)}, "checks": checks}  # fmt: skip
    record.pop("template_id", None)
    return record


def expand_item(item_id: str, key: str = "x^2 + 5x + 6", form: str = "expanded", hint: str | None = None,
                assumptions: list[str] | None = None) -> dict[str, Any]:  # fmt: skip
    check = f"chk_build_test_{item_id[-4:]}"
    answer = {"kind": "algebraic", "expression": key, "variables": ["x"], "required_form": form,
              **({"assumptions": assumptions} if assumptions else {}), "check_id": check}  # fmt: skip
    spec = {
        "tool": "math_simplify",
        "args": {"expression": "(x + 2)(x + 3)", "form": "simplest" if form == "any" else form},
    }
    return _item(item_id, [answer], {check: spec}, hint)


def subject_item(item_id: str, key: str = "t = \\frac{v - u}{a}") -> dict[str, Any]:
    check = f"chk_build_test_{item_id[-4:]}"
    answer = {"kind": "algebraic", "expression": key, "variables": ["t", "u", "v", "a"], "assumptions": ["a \\neq 0"],
              "required_form": "solved_for", "check_id": check}  # fmt: skip
    spec = {"tool": "math_solve", "args": {"equations": ["v = u + a t"], "unknowns": ["t"],
                                           "assumptions": {"a": ["nonzero"]}}}  # fmt: skip
    return _item(item_id, [answer], {check: spec})


def quadratic_item(item_id: str, values: list[str] | None = None) -> dict[str, Any]:
    check = f"chk_build_test_{item_id[-4:]}"
    answer = {"kind": "equation_solutions", "variable": "x", "values": values or ["-3", "2"],
              "tolerance": {"mode": "sig_figs", "value": 3}, "check_id": check}  # fmt: skip
    return _item(item_id, [answer], {check: {"tool": "math_solve", "args": {"equations": ["x^2 + x - 6 = 0"],
                                                                            "unknowns": ["x"]}}})  # fmt: skip


def simultaneous_item(item_id: str) -> dict[str, Any]:
    check = f"chk_build_test_{item_id[-4:]}"
    tolerance = {"mode": "sig_figs", "value": 3}
    answers = [{"kind": "equation_solutions", "variable": v, "values": [k], "tolerance": tolerance, "check_id": check}
               for v, k in (("x", "2"), ("y", "1"))]  # fmt: skip
    spec = {"tool": "math_solve", "args": {"equations": ["2x + 3y = 7", "x - y = 1"], "unknowns": ["x", "y"]}}
    return _item(item_id, answers, {check: spec})


def test_build_accepts_free_response_items(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    records = [
        expand_item("itm.phy.o.motion.9001"),
        expand_item("itm.phy.o.motion.9002", "(x + 2)(x + 3)", "factorised"),
        subject_item("itm.phy.o.motion.9003"),
        quadratic_item("itm.phy.o.motion.9004"),
        simultaneous_item("itm.phy.o.motion.9005"),
        expand_item("itm.phy.o.motion.9006", form="any"),
    ]
    for record in records:
        tree.save_record(source, "items", record)
    built = build(source, tmp_path / "out")
    _, tables = read_pack(built.pack_path)
    types = {i["id"]: i["type"] for i in tables["items"]}
    assert [types[f"itm.phy.o.motion.900{n}"] for n in range(1, 7)] == [
        "algebraic", "algebraic", "algebraic", "equation_solutions", "equation_solutions", "algebraic"]  # fmt: skip


def test_free_response_keys_checked_by_their_tools(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    for record in (expand_item("itm.phy.o.motion.9001", "x^2 + 6x + 5"),
                   expand_item("itm.phy.o.motion.9002", "(x + 2)(x + 3)"),
                   subject_item("itm.phy.o.motion.9003", "t = \\frac{u - v}{a}"),
                   quadratic_item("itm.phy.o.motion.9004", ["2"]),
                   quadratic_item("itm.phy.o.motion.9005", ["-3", "2", "1"]),
                   expand_item("itm.phy.o.motion.9006", assumptions=["x is prime"]),
                   expand_item("itm.phy.o.motion.9007", hint="The answer is x^2 + 5x + 6."),
                   quadratic_item("itm.phy.o.motion.9008", ["-3", "2.00"])):  # fmt: skip
        tree.save_record(source, "items", record)
    found = _problems(source, tmp_path)
    assert "9001 part a: the key x^2 + 6x + 5 is not equivalent to math_simplify's x**2 + 5*x + 6" in found
    assert "9002 part a: the key (x + 2)(x + 3) is not in the expanded form the item asks for" in found
    assert "9003 part a: the key \\frac{u - v}{a} is not math_solve's t = -(u - v)/a" in found
    assert "9004 part a: math_solve's x = -3 is missing from the key (chk_build_test_9004)" in found
    assert "9005 part a: key value 1 is not a solution math_solve gives for x (chk_build_test_9005)" in found
    assert "9006 part a: an assumption of chk_build_test_9006 cannot be stated to the checker (x is prime)" in found
    assert "9007 part a: hint 1 gives away the final answer" in found
    assert "itm.phy.o.motion.9008" not in found  # a rounded decimal key within the item's tolerance


async def _checker(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    from tool_worker.functions import FUNCTIONS
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    try:
        value, _ = FUNCTIONS[name].implementation(args, CallContext("t", "chk_test_k", {}, {}, lambda: False,
                                                                    settings={}))  # fmt: skip
    except WorkerError:
        return None, None
    return value, "chk_test_k"


async def _no_units(quantity: str, to: str) -> None:
    return None


def test_mathematics_free_response_items_verified() -> None:
    """The Mathematics pack's free-response items pass tool verification on their own, and the marker finds each
    part's key correct (the generator's own checks, rerun on the committed records)."""
    _, found = tree.read_pack(REPO / "content" / "curriculum" / "mth" / "o")
    records = [r.record for r in found["items"] if r.record["type"] in ("algebraic", "equation_solutions")]
    assert len(records) >= 8 and {r["type"] for r in records} == {"algebraic", "equation_solutions"}
    conventions = [r.record for r in found["conventions"]]
    for record in records:
        verifier = Verifier(record["checks"], conventions)
        verifier.item({k: v for k, v in record.items() if k not in ("checks", "authoring")})
        assert verifier.problems == [], record["id"]
        for part in record["parts"]:
            answer = part["answer"]
            if answer["kind"] == "algebraic":
                written = answer["expression"]
            else:
                written = " or ".join(f"{answer['variable']} = {v}" for v in answer["values"])
            verdict = asyncio.run(mark(record, part["id"], written, _no_units, Settings(), _checker))  # type: ignore[arg-type]
            assert verdict.outcome == "correct", (record["id"], part["id"])
