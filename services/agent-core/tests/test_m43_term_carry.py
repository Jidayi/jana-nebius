"""M43: term carry between lines (UXS-61, D103): a term carried across the equals sign or cancelled is named on the new
line's `board.step` as `term_moves`, taken only from the step checker's comparison of the two checked lines."""

import asyncio
import random
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.contracts import errors as contract_errors
from agent_core.engine.events import new_id
from agent_core.engine.state import Plan, PlanStep, Problem
from engine_harness import close, make_engine, tutor

SEED = 20261061


def _signed(n: int) -> str:
    return f"+ {n}" if n >= 0 else f"- {-n}"


Fixture = tuple[str, str, list[tuple[int, int | None, str]], int]


def fixtures() -> list[Fixture]:
    """Seeded algebra steps with the moves each one makes by construction: (previous, next, [(from, to, kind)], x)."""
    rng = random.Random(SEED)
    out: list[Fixture] = []
    for _ in range(4):
        a, root = rng.choice([2, 3, 4, 5]), rng.randint(2, 9)
        b = rng.choice([n for n in range(-12, 13) if n != 0])
        c = a * root + b
        # Carry the constant: a x + b = c to a x = c - b (term 2 of the old line is term 3 of the new).
        out.append((f"{a}x {_signed(b)} = {c}", f"{a}x = {c} {_signed(-b)}", [(2, 3, "carry")], root))
        # Two carries: a x + b = d x + e to a x - d x = e - b.
        d = rng.choice([n for n in range(1, 6) if n != a])
        e = (a - d) * root + b
        out.append((f"{a}x {_signed(b)} = {d}x {_signed(e)}", f"{a}x - {d}x = {e} {_signed(-b)}",
                    [(2, 4, "carry"), (3, 2, "carry")], root))  # fmt: skip
        # A pair cancelling on one side: a x + b - b = c to a x = c.
        out.append((f"{a}x {_signed(b)} {_signed(-b)} = {c}", f"{a}x = {c}", [(2, None, "cancel"), (3, None, "cancel")],
                    root))  # fmt: skip
        # Combining values is not a move: a x = c - b to a x = (c - b).
        out.append((f"{a}x = {c} {_signed(-b)}", f"{a}x = {c - b}", [], root))
    return out


def _moves_of(frames: list[dict[str, Any]], step_id: str) -> list[dict[str, Any]] | None:
    found = [f["event"] for f in frames if f.get("event", {}).get("type") == "board.step"
             and f["event"]["step_id"] == step_id]  # fmt: skip
    assert found, step_id
    event = found[-1]
    assert contract_errors("api/events#/$defs/ev_board_step", event) == []
    return event.get("term_moves")


def uxs61_carry_from_verified_diff(tmp_path: Path) -> None:
    cases = fixtures()

    async def check() -> None:
        replies = [tutor("Each line follows from the one before.") for _ in cases]
        engine, _ = await make_engine(tmp_path, {"coach": replies})
        try:
            for previous, line, expected, root in cases:
                engine.state.problem = Problem(new_id("prb"), f"Solve {previous}.", "prb#statement")
                engine.state.plan = Plan([PlanStep(1, f"x = {root}", str(root), None, "chk_TCa")], str(root), None,
                                         "chk_TCa", "plan", f"x = {root}")  # fmt: skip
                engine.state.check_values.update({"chk_TCa": [Fraction(root)]})
                engine.state.board.steps.clear()
                first, second = new_id("stp"), new_id("stp")
                await engine.board_turn([(first, previous), (second, line)])
                statuses = {s.step_id: s.status for s in engine.state.board.steps}
                assert statuses[second] == "correct", (previous, line, statuses)
                moves = _moves_of(engine.events.frames, second)
                # Every move is one the checker found between these two lines, and no other term moves.
                want = [{"from": f"{first}.t{f}", "to": None if t is None else f"t{t}", "kind": k}
                        for f, t, k in expected]  # fmt: skip
                assert (moves or []) == want, (previous, line, moves)
                assert _moves_of(engine.events.frames, first) is None  # the first line follows nothing
        finally:
            await close(engine)

    asyncio.run(check())


def test_uxs61_wrong_step_has_no_moves(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor("Look at the sign.")]})
        try:
            engine.state.problem = Problem("prb_tc", "Solve 2x + 3 = 11.", "prb_tc#statement")
            steps = [PlanStep(1, "x = 4", "4", None, "chk_TCb")]
            engine.state.plan = Plan(steps, "4", None, "chk_TCb", "plan", "x = 4")
            engine.state.check_values.update({"chk_TCb": [Fraction(4)]})
            first, second = new_id("stp"), new_id("stp")
            await engine.board_turn([(first, "2x + 3 = 11"), (second, "2x = 11 + 3")])
            assert {s.step_id: s.status for s in engine.state.board.steps}[second] == "incorrect"
            assert _moves_of(engine.events.frames, second) is None  # an unchecked or wrong line never carries
        finally:
            await close(engine)

    asyncio.run(check())
