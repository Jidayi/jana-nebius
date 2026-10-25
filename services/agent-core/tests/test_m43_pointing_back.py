"""M43: pointing back at a term or a part (UXS-58, D103): "Why this?" on a term range or a part reaches the Coach as
that target's id and content, and a spoken "this" refers to what is selected."""

import asyncio
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.engine.pointing_back import resolve_ref
from agent_core.engine.state import Plan, PlanStep, Problem
from agent_core.engine.ui import update_board
from engine_harness import close, make_engine, tutor

VISUAL = "vis_01JZ0000000000000000000V01"


def _prepare(engine: Any) -> None:
    engine.state.problem = Problem("prb_point", "Solve 2x - 3 = 7.", "prb_point#statement")
    steps = [PlanStep(1, "2x = 10", "10", None, "chk_PTa"), PlanStep(2, "x = 5", "5", None, "chk_PTb")]
    engine.state.plan = Plan(steps, "5", None, "chk_PTb", "the plan", "x = 5")
    engine.state.check_values.update({"chk_PTa": [Fraction(10)], "chk_PTb": [Fraction(5)]})
    engine.state.step = 1
    op = {"op": "add_step", "step": None, "latex": "2x - 3 = 7", "reason": None, "owner": "tutor", "status": "final",
          "terms": [], "prompt": None, "check_id": None}  # fmt: skip
    update_board([op], engine.state, {Fraction(3), Fraction(7), Fraction(2)})
    engine.state.shown_visuals = [{"visual_id": VISUAL, "parts": ["force.weight", "force.normal"],
                                   "kind": "free_body"}]  # fmt: skip


def _coach_context(requests: list[dict[str, Any]]) -> str:
    coached = [r for r in requests if r.get("_role") == "coach"]
    return json.dumps(coached[-1]["messages"]) if coached else ""


def uxs58_term_why_sends_target(tmp_path: Path) -> None:
    async def check() -> str:
        engine, provider = await make_engine(tmp_path, {"coach": [tutor("That term is the constant moved over.")]})
        try:
            _prepare(engine)
            step_id = engine.state.board.steps[0].step_id
            ref = f"{step_id}.t2"
            target = resolve_ref(engine.state, ref)
            assert target is not None and target.terms == "t2" and target.content == "- 3"
            # Ranges resolve to exactly their terms; a term the line does not have resolves to nothing.
            assert resolve_ref(engine.state, f"{step_id}.t1-t2").content == "2x - 3"  # type: ignore[union-attr]
            assert resolve_ref(engine.state, f"{step_id}.t9") is None
            await engine.why_line(ref, "Why this?")
            return _coach_context(provider.requests)
        finally:
            await close(engine)

    context = asyncio.run(check())
    # The Coach is told exactly that range, by id and content, never coordinates.
    assert ".t2" in context and "- 3" in context and "the terms" in context


def uxs58_voice_this_resolves_selection(tmp_path: Path) -> None:
    async def check() -> str:
        engine, provider = await make_engine(tmp_path, {"coach": [tutor("The normal force balances the weight.")]})
        try:
            _prepare(engine)
            engine.state.selection = f"{VISUAL}:force.weight"
            await engine.student_turn("why is this one bigger?")
            return _coach_context(provider.requests)
        finally:
            await close(engine)

    context = asyncio.run(check())
    assert "force.weight" in context and VISUAL in context
