"""M43: "Why is this right?" (UXS-62, D103): offered only once a practice item is marked correct; the tutor asks for
the student's own explanation first, then confirms it, and the item's mark and mastery never change."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.assessment.service import Refused
from agent_core.engine.assessment.tutor import load_context
from engine_harness import close, make_engine, tutor
from test_m16_assessment import KC, answer, desk, run  # noqa: F401 (desk is the fixture)


def _mastery(d: Any) -> float:
    row = d.learner.conn.execute("SELECT n_eff FROM kc_mastery WHERE kc_id = ?", (KC,)).fetchone()
    return float(row[0]) if row else 0.0


def uxs62_why_right_on_correct_items(desk: Any, tmp_path: Path) -> None:  # noqa: F811
    d, _ = desk
    wrong = d.create_practice("mathematics", [KC], 1)
    wrong_item = wrong["current_item"]["item_id"]
    run(d.practice_answer(wrong["set_id"], "w1", wrong_item, answer("b"), 100))
    # After a wrong answer "Help me" applies, never "Why is this right?".
    with pytest.raises(Refused):
        d.practice_help(wrong["set_id"], wrong_item, "why_right")
    assert d.practice_help(wrong["set_id"], wrong_item)["reason"] == "help"
    right = d.create_practice("mathematics", [KC], 1)
    item_id = right["current_item"]["item_id"]
    assert run(d.practice_answer(right["set_id"], "r1", item_id, answer(), 100))["verdict"] == "correct"
    loaded = d.practice_help(right["set_id"], item_id, "why_right")
    assert loaded["reason"] == "why_right" and loaded["origin"]["ref"].endswith("#why_right")
    assert d.tutor_context(loaded["origin"])["reason"] == "why_right"  # the session opens on the same request

    async def first_turn() -> tuple[str, Any]:
        engine, provider = await make_engine(
            tmp_path, {"coach": [tutor("In one sentence, why does your answer work?")]}
        )
        try:
            load_context(engine.state, loaded)
            assert engine.state.practice["why_right"] == "asking"
            await engine.student_turn("Why is this right?")
            coached = [r for r in provider.requests if r.get("_role") == "coach"][-1]
            return str(coached["messages"]), engine.state.practice
        finally:
            await close(engine)

    context, practice = asyncio.run(first_turn())
    # The tutor opens with the item loaded and asks for the student's own explanation first.
    assert "say in a sentence why their answer works" in context and practice["why_right"] == "explaining"


def uxs62_mark_unchanged(desk: Any, tmp_path: Path) -> None:  # noqa: F811
    d, _ = desk
    state = d.create_practice("mathematics", [KC], 1)
    item_id = state["current_item"]["item_id"]
    run(d.practice_answer(state["set_id"], "m1", item_id, answer(), 100))
    internal = d._get(state["set_id"])["id"]
    before = (d.item_verdicts(internal, item_id), _mastery(d))
    assert before[0][1] == ["correct"]
    loaded = d.practice_help(state["set_id"], item_id, "why_right")

    async def session() -> Any:
        replies = [tutor("Why does it work?"), tutor("Yes: adding the two parts gives the total.")]
        engine, _ = await make_engine(tmp_path, {"coach": replies})
        try:
            load_context(engine.state, loaded)
            attempts = dict(engine.state.attempts)
            await engine.student_turn("Why is this right?")
            await engine.student_turn("Because I added the two numbers to get the total.")
            # Nothing was marked: no attempt counted and no board line written as an answer.
            assert engine.state.attempts == attempts
            assert all(step.owner != "student" for step in engine.state.board.steps)
            return engine.state.practice["verdicts"]
        finally:
            await close(engine)

    verdicts = asyncio.run(session())
    assert verdicts == before[0][1]
    assert (d.item_verdicts(internal, item_id), _mastery(d)) == before
