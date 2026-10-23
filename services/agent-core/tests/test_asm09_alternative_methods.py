"""ASM-09: a correct alternative method is never marked wrong (test: `asm09_alternative_methods`).

The real engine and sandboxed tool worker with a scripted model. Each problem's plan takes one route; the student takes
another. Every line of either route is checked by a tool (never by matching the plan's script), a wrong line is still
flagged, and the problem is solved by whichever route reaches the checked answer.
"""

from __future__ import annotations

import asyncio
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine import turn_scope
from agent_core.engine.events import new_id
from agent_core.engine.state import Plan, PlanStep, Problem
from engine_harness import close, make_engine, tutor

LINEAR = "Solve 4(x - 2) = 20."
PAIR = "Solve the simultaneous equations 2x + y = 7 and x - y = 2."
CAR = "A car starts from rest and accelerates at 2 m/s^2 for 5 s. How far does it travel?"
HALF = "Solve 4x = 2."

# The plan expands first; the student may divide first.
LINEAR_PLAN = (
    [PlanStep(1, "4x - 8 = 20", None, None, None), PlanStep(2, "4x = 28", "28", None, "chk_LINa"),
     PlanStep(3, "x = 7", "7", None, "chk_LINb")],
    "7", "chk_LINb", "x = 7", {"chk_LINa": [Fraction(28)], "chk_LINb": [Fraction(7)]},
)  # fmt: skip
# The plan eliminates y; the student may substitute.
PAIR_PLAN = (
    [PlanStep(1, "3x = 9", "9", None, "chk_PRa"), PlanStep(2, "x = 3", "3", None, "chk_PRb"),
     PlanStep(3, "y = 1", "1", None, "chk_PRc")],
    "x = 3, y = 1", "chk_PRb", "x = 3, y = 1",
    {"chk_PRa": [Fraction(9)], "chk_PRb": [Fraction(3)], "chk_PRc": [Fraction(1)]},
)  # fmt: skip
# Two plans for the car: through v (v = u + at, then s = ut + at^2/2) and direct (s = ut + at^2/2).
CAR_VIA_V = (
    [PlanStep(1, "v = u + a*t", None, None, None), PlanStep(2, "v = 10", "10", "m/s", "chk_CARa"),
     PlanStep(3, "s = u*t + 1/2*a*t^2", None, None, None), PlanStep(4, "s = 25", "25", "m", "chk_CARb")],
    "25", "chk_CARb", "s = 25 m", {"chk_CARa": [Fraction(10)], "chk_CARb": [Fraction(25)]},
)  # fmt: skip
CAR_DIRECT = (
    [PlanStep(1, "s = u*t + 1/2*a*t^2", None, None, None), PlanStep(2, "s = 25", "25", "m", "chk_CARb")],
    "25", "chk_CARb", "s = 25 m", {"chk_CARb": [Fraction(25)]},
)  # fmt: skip
# The givens on the board, as the Diagnoser reads them from the car problem.
CAR_KNOWNS = [{"symbol": "u", "value": "0", "unit": "m/s"}, {"symbol": "a", "value": "2", "unit": "m/s^2"},
              {"symbol": "t", "value": "5", "unit": "s"}]  # fmt: skip
HALF_PLAN = ([PlanStep(1, "x = 0.5", "0.5", None, "chk_HLFa")], "0.5", "chk_HLFa", "x = 0.5",
             {"chk_HLFa": [Fraction(1, 2)]})  # fmt: skip


def prepare(engine: Any, statement: str, plan: tuple[Any, ...]) -> None:
    steps, value, check_id, final_latex, values = plan
    engine.state.problem = Problem("prb_routes", statement, "prb_routes#statement")
    engine.state.plan = Plan(steps, value, None, check_id, "the plan's own route", final_latex)
    engine.state.check_values.update(values)
    engine.state.step = 1


async def board(tmp_path: Path, statement: str, plan: tuple[Any, ...], lines: list[str],
                knowns: list[dict[str, str]] | None = None) -> tuple[list[Any], bool]:  # fmt: skip
    """The student's working typed on the board (check my working, ASM-09): each line's status, and solved."""
    engine, _ = await make_engine(tmp_path, {"coach": [tutor("Which step would you like to talk about?")]})
    try:
        prepare(engine, statement, plan)
        engine.state.board.knowns = knowns or []
        await engine.board_turn([(new_id("stp"), line) for line in lines])
        steps = engine.state.board.steps
        assert [s.latex for s in steps] == lines
        for step in steps:  # a status other than unchecked always names the tool check that decided it (PRD-05)
            assert (step.check_id is None) == (step.status == "unchecked"), step
        return steps, engine.state.solved
    finally:
        await close(engine)


def statuses(steps: list[Any]) -> list[str]:
    return [s.status for s in steps]


ROUTES = {
    "expand first": (LINEAR, LINEAR_PLAN, ["4(x - 2) = 20", "4x - 8 = 20", "4x = 28", "x = 7"]),
    "divide first": (LINEAR, LINEAR_PLAN, ["4(x - 2) = 20", "x - 2 = 5", "x = 7"]),
    "longer route": (LINEAR, LINEAR_PLAN,
                     ["4(x - 2) = 20", "4x - 8 = 20", "4x - 8 + 8 = 20 + 8", "4x = 28", "4x/4 = 28/4", "x = 7"]),
    "elimination": (PAIR, PAIR_PLAN, ["2x + y = 7", "x - y = 2", "3x = 9", "x = 3", "3 - y = 2", "y = 1"]),
    "substitution": (PAIR, PAIR_PLAN, ["y = 7 - 2x", "x - (7 - 2x) = 2", "3x - 7 = 2", "x = 3", "y = 7 - 2*3",
                                       "y = 1"]),
    "fraction for decimal": (HALF, HALF_PLAN, ["4x = 2", "x = 1/2"]),
    "answer rearranged": (HALF, HALF_PLAN, ["4x = 2", "1/2 = x"]),
}  # fmt: skip


@pytest.mark.parametrize("route", list(ROUTES))
def asm09_alternative_methods(tmp_path: Path, route: str) -> None:
    statement, plan, lines = ROUTES[route]

    async def check() -> None:
        steps, solved = await board(tmp_path, statement, plan, lines)
        assert statuses(steps) == ["correct"] * len(lines)
        assert solved

    asyncio.run(check())


@pytest.mark.parametrize("plan", [CAR_VIA_V, CAR_DIRECT], ids=["plan via v", "plan direct"])
@pytest.mark.parametrize(
    "lines",
    [
        ["v = u + a*t", "v = 0 + 2*5", "v = 10", "s = u*t + 1/2*a*t^2", "s = 0*5 + 1/2*2*5^2", "s = 25"],
        ["v = 0 + 2*5", "v = 10", "v^2 = u^2 + 2*a*s", "10^2 = 0^2 + 2*2*s", "100 = 4*s", "s = 25"],
    ],
    ids=["v then s = ut + at^2/2", "v then v^2 = u^2 + 2as"],
)
def test_asm09_alternative_methods_kinematics(tmp_path: Path, plan: tuple[Any, ...], lines: list[str]) -> None:
    # Whichever route the plan took: no line is wrong, the substitution and answer lines are checked, the formula
    # lines (no numbers) stay unchecked as ASM-09 says, and they do not stop the problem from being solved.
    async def check() -> None:
        steps, solved = await board(tmp_path, CAR, plan, lines)
        assert "incorrect" not in statuses(steps)
        assert steps[-1].status == "correct" and steps[-2].status == "correct"
        for step in steps:
            if not any(c.isdigit() for c in step.latex):
                assert step.status == "unchecked"
        assert solved

    asyncio.run(check())


@pytest.mark.parametrize("plan", [CAR_VIA_V, CAR_DIRECT], ids=["plan via v", "plan direct"])
@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["v = u + a*t", "v = 0 + 2*5", "v = 10", "s = u*t + 1/2*a*t^2", "s = 0*5 + 1/2*2*5^2", "s = 25"],
         ["unchecked", "correct", "correct", "unchecked", "correct", "correct"]),
        (["v = u + a*t", "v = 0 + 2*5", "v = 10", "v^2 = u^2 + 2*a*s", "10^2 = 0^2 + 2*2*s", "s = 25"],
         ["unchecked", "correct", "correct", "unchecked", "correct", "correct"]),
        (["v = u + a*t", "v = u + 2*5", "v = 10"], ["unchecked", "correct", "correct"]),
    ],
    ids=["v then s = ut + at^2/2", "v then v^2 = u^2 + 2as", "partly substituted"],
)  # fmt: skip
def test_asm09_substitution_lines_checked(
    tmp_path: Path, plan: tuple[Any, ...], lines: list[str], expected: list[str]
) -> None:
    # With the givens on the board, a line substituting them into the formula before it is checked by a tool, for an
    # intermediate quantity (v) as for the plan's unknown, whichever route the plan took.
    async def check() -> None:
        steps, _ = await board(tmp_path, CAR, plan, lines, CAR_KNOWNS)
        assert statuses(steps) == expected

    asyncio.run(check())


@pytest.mark.parametrize(
    ("lines", "expected"),
    [
        (["v = u + a*t", "v = 0 + 2*6", "v = 12"], ["unchecked", "incorrect", "correct"]),
        (["v = u + a*t", "v = 2 + 0*5"], ["unchecked", "incorrect"]),
        (["v = u + a*t + w", "v = 0 + 2*5"], ["unchecked", "unchecked"]),
    ],
    ids=["wrong value for t", "givens swapped", "formula names a non-given"],
)
def test_asm09_substitution_slip_flagged(tmp_path: Path, lines: list[str], expected: list[str]) -> None:
    # A wrong substitution is marked incorrect (with its check id); a line after it is checked against it (error
    # carried forward); a formula naming a quantity that is not a given leaves the substitution unchecked.
    async def check() -> None:
        steps, solved = await board(tmp_path, CAR, CAR_VIA_V, lines, CAR_KNOWNS)
        assert statuses(steps) == expected
        if "incorrect" in expected:
            assert steps[expected.index("incorrect")].error is not None
        assert not solved

    asyncio.run(check())


@pytest.mark.parametrize(
    ("statement", "plan", "lines", "wrong"),
    [
        (LINEAR, LINEAR_PLAN, ["4(x - 2) = 20", "4x - 2 = 20", "4x = 22", "x = 5.5"], 1),
        (LINEAR, LINEAR_PLAN, ["4(x - 2) = 20", "x - 2 = 4", "x = 6"], 1),
        (PAIR, PAIR_PLAN, ["y = 7 - 2x", "x - (7 + 2x) = 2", "-x = 9", "x = -9"], 1),
        (PAIR, PAIR_PLAN, ["2x + y = 7", "x - y = 2", "3x = 5"], 2),
        (CAR, CAR_DIRECT, ["v = 0 + 2*5", "v = 10", "10^2 = 0^2 + 2*s", "s = 50"], 2),
    ],
    ids=["expand slip", "divide slip", "substitution sign", "elimination add", "kinematics formula"],
)
def test_asm09_wrong_line_of_any_route_flagged(
    tmp_path: Path, statement: str, plan: tuple[Any, ...], lines: list[str], wrong: int
) -> None:
    async def check() -> None:
        steps, solved = await board(tmp_path, statement, plan, lines)
        assert statuses(steps)[:wrong] == [s for s in statuses(steps)[:wrong] if s != "incorrect"]
        assert steps[wrong].status == "incorrect" and steps[wrong].error is not None  # "Look here"
        assert not solved

    asyncio.run(check())


async def guided(tmp_path: Path, statement: str, plan: tuple[Any, ...], replies: list[str]) -> tuple[list[str], Any]:
    """Guided solve: each reply checked by the engine's code with no model call (AGT-19)."""
    engine, provider = await make_engine(tmp_path, {})
    try:
        prepare(engine, statement, plan)
        if statement == CAR:  # the givens on the board, as the Diagnoser reads them
            engine.state.board.knowns = [{"symbol": "u", "value": "0", "unit": "m/s"},
                                         {"symbol": "a", "value": "2", "unit": "m/s^2"},
                                         {"symbol": "t", "value": "5", "unit": "s"}]  # fmt: skip
        verdicts = []
        turn = engine._begin("answer")
        for text in replies:
            with turn_scope(turn.turn_id):
                verdicts.append(await engine._check_attempt(turn, text))
        assert provider.requests == []
        for step in engine.state.board.steps:  # a line shown correct always names the check that proved it
            assert step.check_id is not None or step.status != "correct", step
            assert step.check_id is None or step.status != "unchecked", step
        return verdicts, engine.state
    finally:
        await close(engine)


@pytest.mark.parametrize(
    ("statement", "plan", "replies", "verdicts", "solved"),
    [
        (LINEAR, LINEAR_PLAN, ["x - 2 = 5", "x = 7"], ["correct", "correct"], True),
        (LINEAR, LINEAR_PLAN, ["2x - 4 = 10", "2x = 14", "x = 7"], ["correct"] * 3, True),
        (LINEAR, LINEAR_PLAN, ["4x - 8 = 20", "4x = 28", "x = 7"], ["correct"] * 3, True),
        (LINEAR, LINEAR_PLAN, ["x - 2 = 4", "4x = 30", "x = 8"], ["incorrect"] * 3, False),
        (PAIR, PAIR_PLAN, ["x - (7 - 2x) = 2", "x = 3", "y = 1"], ["correct"] * 3, True),
        (PAIR, PAIR_PLAN, ["3x = 9", "x = 3"], ["correct", "correct"], False),
        (PAIR, PAIR_PLAN, ["3x = 12", "y = 2"], ["incorrect", "incorrect"], False),
        (HALF, HALF_PLAN, ["x = 1/2"], ["correct"], True),
        (CAR, CAR_DIRECT, ["v = 0 + 2*5", "v = 10"], ["unchecked", "unchecked"], False),
        (CAR, CAR_VIA_V, ["v = 10"], ["correct"], False),
        (CAR, CAR_VIA_V, ["v = 12"], ["incorrect"], False),
        (CAR, CAR_VIA_V, ["10^2 = 0^2 + 2*2*s", "s = 25 m"], ["correct", "correct"], True),
        (CAR, CAR_VIA_V, ["10^2 = 0^2 + 2*2*s, so s = 30"], ["incorrect"], False),
        (CAR, CAR_DIRECT, ["a*t = 10", "1/2*a*t^2 = 25"], ["correct", "correct"], True),
        (CAR, CAR_DIRECT, ["a*t = 12"], ["incorrect"], False),
    ],
    ids=["divide first", "halve first", "plan's route", "wrong lines", "substitution", "one unknown only",
         "wrong pair lines", "fraction for decimal", "other route's v", "plan's v", "wrong v", "v^2 route",
         "v^2 route slip", "givens' values", "givens slip"],
)  # fmt: skip
def test_asm09_alternative_methods_guided(
    tmp_path: Path,
    statement: str,
    plan: tuple[Any, ...],
    replies: list[str],
    verdicts: list[str],
    solved: bool,
) -> None:
    async def check() -> None:
        got, state = await guided(tmp_path, statement, plan, replies)
        assert got == verdicts
        assert state.solved is solved

    asyncio.run(check())


@pytest.mark.parametrize(
    "reply,equation",
    [("oh, then s = 10 m", "s = 10 m"), ("so v = 14 - 9.8*t", "v = 14 - 9.8*t"), ("s = 10 m", "s = 10 m"),
     ("sin x = 0.5", "sin x = 0.5"), ("speed = 5", "speed = 5")],
)  # fmt: skip
def test_asm09_reply_equation_after_lead_words(reply, equation):
    """A guided reply may state its equation after a few words; the equation is what is checked (s1_wrong_then_right).
    A function name before the symbol is maths, not a lead-in."""
    from agent_core.engine.slice import equation_part

    assert equation_part(reply) == equation


# --- T3: the tutor names the student's own method (ASM-09) -----------------------------------------------------------


@pytest.mark.parametrize(
    ("statement", "plan", "line", "pair", "givens", "method"),
    [
        (LINEAR, LINEAR_PLAN, "x - 2 = 5", False, set(), "divide_first"),
        (LINEAR, LINEAR_PLAN, "2x - 4 = 10", False, set(), "divide_first"),
        (LINEAR, LINEAR_PLAN, "4x - 8 = 20", False, set(), None),
        (LINEAR, LINEAR_PLAN, "x = 7", False, set(), None),
        (PAIR, PAIR_PLAN, "x - (7 - 2x) = 2", True, set(), "substitution"),
        (PAIR, PAIR_PLAN, "3x = 9", True, set(), None),
        (PAIR, PAIR_PLAN, "3y = 3", True, set(), "elimination"),
        (PAIR, PAIR_PLAN, "y = 1", True, set(), None),
        (CAR, CAR_DIRECT, "a*t = 10", False, {"u", "a", "t"}, "givens_formula"),
        (CAR, CAR_VIA_V, "10^2 = 0^2 + 2*2*s", False, {"u", "a", "t"}, "other_formula"),
        (CAR, CAR_VIA_V, "s = 25 m", False, {"u", "a", "t"}, None),
    ],
    ids=["divide first", "halve first", "plan's route", "stated value", "substitution", "plan's elimination",
         "other elimination", "stated y", "givens' values", "v^2 route", "stated answer"],
)  # fmt: skip
def test_t3_method_of(statement, plan, line, pair, givens, method) -> None:
    from agent_core.engine.slice import method_of

    steps, value, check_id, final_latex, _ = plan
    assert method_of(statement, Plan(steps, value, None, check_id, "r", final_latex), line, pair=pair,
                     givens=givens) == method  # fmt: skip


def test_t3_every_method_has_plain_words() -> None:
    from agent_core.engine.receipts import default_receipts
    from agent_core.engine.slice import METHODS

    words = default_receipts().methods
    assert set(words) == set(METHODS)
    assert all(text and "{" not in text and "_" not in text for text in words.values())


@pytest.mark.parametrize(
    ("statement", "plan", "reply", "method"),
    [(LINEAR, LINEAR_PLAN, "x - 2 = 5", "divide_first"), (PAIR, PAIR_PLAN, "x - (7 - 2x) = 2", "substitution"),
     (LINEAR, LINEAR_PLAN, "4x - 8 = 20", None), (LINEAR, LINEAR_PLAN, "x - 2 = 4", None)],
    ids=["divide first", "substitution", "plan's route", "wrong line"],
)  # fmt: skip
def test_t3_guided_check_names_the_method(tmp_path: Path, statement, plan, reply, method) -> None:
    """The guided check records the method of a line it accepted on its own maths; never for a wrong line or a step of
    the plan's own route."""

    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {})
        try:
            prepare(engine, statement, plan)
            turn = engine._begin("answer")
            with turn_scope(turn.turn_id):
                await engine._check_attempt(turn, reply)
            assert turn.method == method
        finally:
            await close(engine)

    asyncio.run(check())


def test_t3_tutor_is_told_the_method_in_plain_words(tmp_path: Path) -> None:
    """A whole guided turn: the Coach's per-turn block names the student's method in the words of engine.en.yaml."""
    from agent_core.engine.receipts import default_receipts

    async def check() -> list[Any]:
        engine, provider = await make_engine(tmp_path, {"coach": [tutor("Nice, dividing first works.")]})
        try:
            prepare(engine, LINEAR, LINEAR_PLAN)
            await engine.student_turn("x - 2 = 5")
            return provider.requests
        finally:
            await close(engine)

    requests = asyncio.run(check())
    words = default_receipts().methods["divide_first"]
    sent = [str(m["content"]) for r in requests for m in r["messages"] if "<tutor-context>" in str(m["content"])]
    assert sent and any(words in text and "attempt was correct" in text for text in sent), [
        t[t.find("this turn") :][:300] for t in sent
    ]
