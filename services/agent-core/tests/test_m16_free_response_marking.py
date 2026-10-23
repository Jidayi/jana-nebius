"""Markers for free-response maths (ASM-03, ASM-05, CUR-14, CUR-15): algebraic answers by `math_check_equivalence`
and `math_check_answer` (value, then form), and equation solutions by `math_check_answer` as sets. The worker's
checkers run in-process; every item, key and student answer here is synthetic test data."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import validate
from agent_core.engine.marking import (
    MARKERS,
    Converted,
    RunTool,
    Verdict,
    mark,
    settle,
    solution_values,
    worker_assumptions,
)
from agent_core.engine.slice import plan_from_item

SETTINGS = Settings()
CALLS: list[str] = []


async def run_tool(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The worker's checker, in-process: the result value and a check id, or nothing when it refuses."""
    from tool_worker.functions import FUNCTIONS
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    check_id = f"chk_test_{name}_{len(CALLS)}"
    CALLS.append(name)
    try:
        value, _ = FUNCTIONS[name].implementation(args, CallContext("t", check_id, {}, {}, lambda: False, settings={}))
    except WorkerError:
        return None, None
    return value, check_id


async def undecided(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """A checker that runs but cannot decide (VER-27): `unknown`, never a guess."""
    if name == "math_check_equivalence":
        return {"verdict": "unknown", "reason": "timeout"}, "chk_test_unknown_eq"
    return {"verdict": "unknown", "components": {"value": "unknown", "form": "not_required"}}, "chk_test_unknown_ans"


async def no_convert(quantity: str, to: str) -> Converted | None:
    raise AssertionError("free-response maths converts no units")


def marked(item: dict[str, Any], response: Any, run: RunTool | None = run_tool, part: str = "a") -> Verdict:
    verdict = asyncio.run(mark(item, part, response, no_convert, SETTINGS, run))
    if verdict.outcome != "unverifiable":  # every verdict names the checker it came from (ASM-02)
        assert verdict.provenance and verdict.check_ids
        assert verdict.check_ids[0] == item["parts"][0]["answer"]["check_id"]
    payload = verdict.payload(verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                              closes_opportunity=True)  # fmt: skip
    validate("learning/learning-event#/$defs/payload_verdict", payload)
    return verdict


def item(kind: str, answer: dict[str, Any], marks: int = 2) -> dict[str, Any]:
    return {"id": "itm.mth.o.algebra_and_graphs.9001", "type": kind,
            "parts": [{"id": "a", "prompt": "Answer.", "marks": marks,
                       "answer": {"kind": kind, **answer, "check_id": "chk_build_test_key"}, "hints": []}]}  # fmt: skip


def algebraic(expression: str, form: str, variables: list[str] | None = None, marks: int = 2,
              **extra: Any) -> dict[str, Any]:  # fmt: skip
    return item("algebraic", {"expression": expression, "variables": variables or ["x"], "required_form": form,
                              **extra}, marks)  # fmt: skip


def solutions(values: list[str], variable: str = "x", tolerance: dict[str, Any] | None = None) -> dict[str, Any]:
    return item("equation_solutions", {"variable": variable, "values": values,
                                       "tolerance": tolerance or {"mode": "sig_figs", "value": 3}})  # fmt: skip


def outcome(verdict: Verdict) -> tuple[str, float, str | None]:
    return verdict.outcome, verdict.marks_awarded, verdict.error_category


def test_free_response_types_have_markers() -> None:
    assert {"algebraic", "equation_solutions"} <= set(MARKERS)


# --- ASM-05 ---------------------------------------------------------------------------------------------------------


def asm05_equivalence_and_form() -> None:
    # Equivalent forms are accepted when the item asks for no form, and when they are in the form asked.
    any_form = algebraic("x^2 + 5x + 6", "any")
    for written in ("(x+2)(x+3)", "x^2 + 5x + 6", "(x + 3)(x + 2)", "x(x+5) + 6", "(x+2)(x+3) = x^2+5x+6"):
        assert outcome(marked(any_form, written)) == ("correct", 2.0, None), written
    expanded = algebraic("x^2 + 5x + 6", "expanded")
    assert outcome(marked(expanded, "6 + 5x + x^2")) == ("correct", 2.0, None)
    factorised = algebraic("(x + 2)(x + 3)", "factorised")
    assert outcome(marked(factorised, "(x+3)(x+2)")) == ("correct", 2.0, None)
    # Equivalent but not in the form asked: partial, error category `form`, value passed and form failed.
    wrong_form = marked(expanded, "(x+2)(x+3)")
    assert outcome(wrong_form) == ("partial", 1.0, "form")
    assert [(c["criterion_id"], c["result"]) for c in wrong_form.criteria] == [("value", "pass"), ("form", "fail")]
    assert outcome(marked(factorised, "x^2 + 5x + 6")) == ("partial", 1.0, "form")
    # A value that is wrong is wrong whatever its form.
    assert outcome(marked(factorised, "(x+1)(x+6)")) == ("incorrect", 0.0, "value")


# --- focused cases --------------------------------------------------------------------------------------------------


def test_algebraic_form_only_when_required() -> None:
    # Not fully factorised is a form fault only when the item asks for the factorised form.
    common = algebraic("2x(x + 3)", "factorised")
    assert outcome(marked(common, "2x(x+3)")) == ("correct", 2.0, None)
    assert outcome(marked(common, "x(2x + 6)")) == ("partial", 1.0, "form")
    assert outcome(marked(algebraic("2x(x + 3)", "any"), "x(2x + 6)")) == ("correct", 2.0, None)
    # Simplest form of an algebraic fraction: equal except where the original is undefined counts as the same value.
    fraction = algebraic("\\frac{x + 1}{2}", "simplest")
    assert outcome(marked(fraction, "(x+1)/2")) == ("correct", 2.0, None)
    assert outcome(marked(fraction, "\\frac{2x + 2}{4}")) == ("partial", 1.0, "form")  # a common factor of 2 left
    assert outcome(marked(algebraic("x + 1", "simplest"), "\\frac{x^2 - 1}{x - 1}")) == ("partial", 1.0, "form")
    # A common factor left on the top and the bottom is not the simplest form, even though the value is the key's.
    uncancelled = algebraic("\\frac{6}{x - 2}", "simplest")
    assert outcome(marked(uncancelled, "\\frac{6(x + 2)}{(x - 2)(x + 2)}")) == ("partial", 1.0, "form")
    assert outcome(marked(uncancelled, "6/(x - 2)")) == ("correct", 2.0, None)
    # The item may make a wrong form wrong; a one-mark part has no mark to keep.
    strict = algebraic("x^2 + 5x + 6", "expanded", form_unmet="wrong")
    assert outcome(marked(strict, "(x+2)(x+3)")) == ("incorrect", 0.0, "form")
    assert outcome(marked(algebraic("x^2 + 5x + 6", "expanded", marks=1), "(x+2)(x+3)")) == ("incorrect", 0.0, "form")


def test_algebraic_solved_for_subject() -> None:
    subject = algebraic("t = \\frac{v - u}{a}", "solved_for", ["t", "u", "v", "a"], assumptions=["a \\neq 0"])
    for written in ("t = (v - u)/a", "t = v/a - u/a", "\\frac{v-u}{a} = t", "(v-u)/a"):
        assert outcome(marked(subject, written)) == ("correct", 2.0, None), written
    # The right relation with the subject not alone on one side is the right value in the wrong form.
    not_isolated = marked(subject, "a t = v - u")
    assert outcome(not_isolated) == ("partial", 1.0, "form")
    assert [c["result"] for c in not_isolated.criteria] == ["pass", "fail"]
    assert outcome(marked(subject, "t = (u - v)/a")) == ("incorrect", 0.0, "value")
    assert outcome(marked(subject, "t = v - u - a")) == ("incorrect", 0.0, "value")
    # An assumption the checker cannot state cannot be marked under.
    assert marked(algebraic("x", "any", assumptions=["x is prime"]), "x").outcome == "unverifiable"
    assert worker_assumptions(["x > 0", "a \\neq 0", "n \\geq 0", "k integer"]) == {
        "x": ["positive"], "a": ["nonzero"], "n": ["nonnegative"], "k": ["integer"]}  # fmt: skip


def test_algebraic_unreadable_and_unverifiable() -> None:
    key = algebraic("x^2 + 5x + 6", "expanded")
    assert outcome(marked(key, "x^2 +* 5x")) == ("incorrect", 0.0, "unreadable")  # the checker reads the key only
    assert outcome(marked(key, "")) == ("incorrect", 0.0, "unreadable")
    # No checker, or a checker that cannot decide: no verdict, never a guess.
    assert marked(key, "x^2 + 5x + 6", run=None).outcome == "unverifiable"
    assert marked(key, "x^2 + 5x + 6", run=undecided).outcome == "unverifiable"
    # A model's differing outcome is discarded (ASM-02).
    assert settle("correct", marked(key, "x^2 + 6x + 5")).outcome == "incorrect"


def test_solution_values_read() -> None:
    assert solution_values("x = 2 or x = -3", "x") == ["2", "-3"]
    assert solution_values("x = \\pm 3", "x") == ["3", "-3"]
    assert solution_values("x = 2 \\pm \\sqrt{3}", "x") == ["2 + \\sqrt{3}", "2 - \\sqrt{3}"]
    assert solution_values("\\{-3, 2\\}", "x") == ["-3", "2"]
    assert solution_values(["x=1", "x = \\frac{1}{2}"], "x") == ["1", "\\frac{1}{2}"]
    assert solution_values("x = 2, y = -1", "x") == ["2"]  # a value for another unknown answers another part
    assert solution_values("no real solutions", "x") == []
    assert solution_values("", "x") is None


def test_equation_solutions_as_sets() -> None:
    quadratic = solutions(["-3", "2"])
    for written in ("x = 2 or x = -3", "x = -3, x = 2", ["2", "-3"], "{2, -3}", "x = 2, x = -3, x = 2.0"):
        verdict = marked(quadratic, written)
        assert outcome(verdict) == ("correct", 2.0, None), written
        assert [c["result"] for c in verdict.criteria] == ["pass", "pass"]
    # A missing value and an extra value are each incorrect; the extra values are counted.
    missing = marked(quadratic, "x = 2")
    assert outcome(missing) == ("incorrect", 0.0, "value")
    assert [(c["criterion_id"], c["result"]) for c in missing.criteria] == [("value_1", "fail"), ("value_2", "pass")]
    extra = marked(quadratic, "x = 2, x = -3, x = 0, x = 5")
    assert outcome(extra) == ("incorrect", 0.0, "value")
    assert [c["criterion_id"] for c in extra.criteria if c["result"] == "fail"] == ["extra_1", "extra_2"]
    assert outcome(marked(quadratic, "no solution")) == ("incorrect", 0.0, "value")
    # ± gives both values; exact values in any written form, and decimals of exact values to the item's figures.
    assert marked(solutions(["-3", "3"]), "x = \\pm 3").outcome == "correct"
    assert marked(solutions(["\\frac{1}{2}"]), "x = 0.5").outcome == "correct"
    assert marked(solutions(["\\frac{1}{3}", "-2"]), "x = 0.333 or x = -2").outcome == "correct"
    assert marked(solutions(["\\frac{1}{3}", "-2"]), "x = 0.33 or x = -2").outcome == "incorrect"  # 2 figures of 3
    surds = solutions(["1 - \\sqrt{2}", "1 + \\sqrt{2}"])
    assert marked(surds, "x = 1 \\pm \\sqrt{2}").outcome == "correct"
    assert marked(surds, "x = 2.41 or x = -0.414").outcome == "correct"
    # A key given as rounded decimals is met within the item's tolerance.
    rounded = solutions(["-3.56", "0.56"], tolerance={"mode": "absolute", "value": 0.005})
    assert marked(rounded, "x = 0.562 or x = -3.561").outcome == "correct"
    assert marked(rounded, "x = 0.6 or x = -3.56").outcome == "incorrect"


def test_equation_solutions_unreadable_and_unverifiable() -> None:
    key = solutions(["-3", "2"])
    assert outcome(marked(key, "x = 2 or x = (")) == ("incorrect", 0.0, "unreadable")
    assert outcome(marked(key, ", ,")) == ("incorrect", 0.0, "unreadable")
    assert outcome(marked(key, ", ".join(str(n) for n in range(SETTINGS.marking_solutions_max_values + 1)))) == (
        "incorrect", 0.0, "unreadable")  # fmt: skip
    assert marked(key, "x = 2 or x = -3", run=None).outcome == "unverifiable"
    assert marked(key, "x = 2 or x = -3", run=undecided).outcome == "unverifiable"


def test_form_unmet_contract_addition() -> None:
    from agent_core.contracts import errors

    answer = algebraic("x^2 + 5x + 6", "expanded", form_unmet="wrong")["parts"][0]["answer"]
    assert errors("content/content-pack#/$defs/Answer", answer) == []
    assert errors("content/content-pack#/$defs/Answer", {**answer, "form_unmet": "ignore"}) != []


def test_practice_plan_from_free_response_items() -> None:
    plan, values = plan_from_item({**algebraic("x^2 + 5x + 6", "expanded"), "solution": {"steps": []}}, "a")
    assert plan.final_value == "x^2 + 5x + 6" and values == {}
    plan, _ = plan_from_item({**solutions(["-3", "2"]), "solution": {"steps": []}}, "a")
    assert plan.final_value == "-3, 2"
