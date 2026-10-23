"""M9.b: the S1 slice flows beyond guided solve: check my working (AGT-21, ASM-09, S1 subset) and practice help
(AGT-23, S1 subset), and the S1 end to end (PRD-12). Replies are scripted; items come from the S1 pack sources; the
student's lines are synthetic."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.slice import for_tool
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.scenarios import traced_numbers
from pack_builder.build import load_source

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _items() -> list[dict[str, Any]]:
    """The S1 topic's items (motion in a straight line); the pack also holds the rest of the O level syllabus."""
    return [i for i in load_source(PACK).tables["items"] if i["kc_ids"][0].startswith("kc.phy.o.motion.")]


def _board(engine: Any) -> list[dict[str, Any]]:
    return [f["event"] for f in engine.events.frames if f["event"]["type"] == "board.step"]


def test_working_lines_for_the_tools() -> None:
    assert for_tool("s = 10 m") == "s = 10"
    assert for_tool("a = 2.0 m/s^2") == "a = 2.0"
    assert for_tool("0 = 14² − 2 × 9.8 × s") == "0 = 14^2 - 2 * 9.8 * s"


def test_check_working_marks_every_line(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Your working is checked line by line. Why is the final speed zero at the top?")]
    engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}))
    run(engine.start_problem(STATEMENT))
    working = "v^2 = u^2 + 2as\n0 = 14^2 - 2*9.8*s\n19.6*s = 196\ns = 10 m"
    result = run(engine.check_working(STATEMENT, working))
    run(close(engine))
    student = [e for e in _board(engine) if e["owner"] == "student"]
    assert [e["status"] for e in student] == ["unchecked", "correct", "correct", "correct"]
    assert all(e["check_id"] for e in student[1:]), "each checked line names the tool call that decided it"
    assert engine.state.solved and result.status == "complete"
    names = [c["name"] for c in result.trace["tool_calls"]]
    assert "math_check_step" in names and "math_solve" in names


def test_check_working_finds_the_first_wrong_line(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Look again at your third line. Check the multiplication there.")]
    engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}))
    run(engine.start_problem(STATEMENT))
    working = "v^2 = u^2 + 2as\n0 = 14^2 - 2*9.8*s\n18.6*s = 196\ns = 196/18.6"
    result = run(engine.check_working(STATEMENT, working))
    run(close(engine))
    student = [e for e in _board(engine) if e["owner"] == "student"]
    assert [e["status"] for e in student][:3] == ["unchecked", "correct", "incorrect"]
    assert student[2]["reason"] == "arithmetic"
    assert "carried forward" in (student[3]["reason"] or ""), "later lines are checked against the line before"
    assert not engine.state.solved
    assert "10" not in result.tutor_turn["say"], "the Coach never writes the corrected value"


def test_practice_uses_the_item_and_marks_by_key(tmp_path: Path) -> None:
    item = next(i for i in _items() if i["id"] == "itm.phy.o.motion.0001")
    coach = [
        tutor(SAFE),
        tutor("Have a go first: what does the question give you?"),
        tutor("Not quite yet. Which quantity goes on top?"),
        tutor("That's right (checked). Well done."),
    ]
    engine, _ = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": coach}))
    run(engine.start_practice(item))
    stuck = run(engine.student_turn("I'm stuck"))
    wrong = run(engine.student_turn("0.125 m/s"))
    right = run(engine.student_turn("8.0 m/s"))
    run(close(engine))
    assert stuck.trace and "tpl.entry_question" in str(engine.turn_log[1].get("template")), "attempt before hint"
    statuses = [e["status"] for e in _board(engine) if e["owner"] == "student"]
    assert statuses == ["incorrect", "correct"]
    assert engine.state.solved and engine.state.practice["verdicts"] == ["incorrect", "correct"]
    assert not any(c["role"] in ("solver", "checker") for t in engine.traces for c in t["model_calls"]), (
        "practice uses the stored solution: no Solver or Checker call"
    )
    assert wrong.status == right.status == "complete"
    total, traced = traced_numbers(engine)
    assert total and total == traced, "every board number carries a check id"


@pytest.mark.parametrize("hint_rung", [1])
def test_practice_hint_is_the_authored_one(tmp_path: Path, hint_rung: int) -> None:
    item = next(i for i in _items() if i["id"] == "itm.phy.o.motion.0001")
    coach = [
        tutor(SAFE),
        tutor("Not quite yet. Which quantity is asked for?"),
        tutor("You know the distance and the time. Which quantity are you asked for?", hint_rung=hint_rung),
    ]
    engine, provider = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": coach}))
    run(engine.start_practice(item))
    run(engine.student_turn("150 m/s"))
    run(engine.student_turn("I'm stuck"))
    run(close(engine))
    last_request = provider.requests[-1]
    assert "rephrase this authored hint" in str(last_request), "the Coach is given the authored rung to rephrase"


def test_practice_pushes_the_topic_teaching_skill(tmp_path: Path) -> None:
    """SKL-08 subset: the engine, not the model, pushes the reviewed (in dev builds, draft) teaching skill whose KCs
    contain the item's KC and whose levels include the session level; with it the first pedagogy skill it names
    (SKL-15)."""
    item = next(i for i in _items() if i["id"] == "itm.phy.o.motion.0001")
    engine, _ = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": [tutor(SAFE)]}))
    result = run(engine.start_practice(item))
    run(close(engine))
    pushed = [s for s in result.trace["skills"] if s["delivery"] == "pushed"]
    assert [s["name"] for s in pushed] == ["phy-o-motion", "pedagogy-guided-solve"]
    skills = engine.deps.assets.skills
    assert skills.teaching_for(["kc.phy.o.motion.free_fall"], "O").name == "phy-o-motion"
    assert skills.teaching_for(["kc.phy.o.motion.free_fall"], "A") is None, "no skill for another level"
    assert skills.teaching_for(["kc.mth.o.algebra.rearrange_linear"], "O") is None


def prd12_s1_topic_end_to_end(tmp_path: Path) -> None:
    """A scripted student completes guided solve, check my working and five practice items on the S1 topic, on the
    mid hardware class, offline, with every board number verified. (Scripted replies; the same run against a local
    model is the device-lab evidence of the M9 record.)"""
    from jana_tools.harness.egress import offline_run

    boards: list[tuple[int, int]] = []
    with offline_run() as egress:
        # Guided solve.
        guided = [
            tutor(SAFE),
            tutor("Good start. What is the ball's speed at the very top?"),
            tutor("That's right (checked): it rises 10 m. Why is the speed zero at the top?"),
        ]
        engine, _ = run(make_engine(tmp_path / "g", {"solver": solver_steps(), "checker": checker_steps(),
                                                     "coach": guided}, hardware_class="mid"))  # fmt: skip
        run(engine.start_problem(STATEMENT))
        run(engine.student_turn("v^2 = u^2 + 2as"))
        run(engine.student_turn("s = 10 m"))
        run(close(engine))
        assert engine.state.solved
        boards.append(traced_numbers(engine))
        # Check my working.
        coach = [tutor(SAFE), tutor("Every line checks. Why is the final speed zero at the top?")]
        engine, _ = run(make_engine(tmp_path / "w", {"solver": solver_steps(), "checker": checker_steps(),
                                                     "coach": coach}, hardware_class="mid"))  # fmt: skip
        run(engine.start_problem(STATEMENT))
        run(engine.check_working(STATEMENT, "v^2 = u^2 + 2as\n0 = 14^2 - 2*9.8*s\n19.6*s = 196\ns = 10 m"))
        run(close(engine))
        assert engine.state.solved
        boards.append(traced_numbers(engine))
        # Five practice items, one per KC family, each answered with its key.
        picked: dict[str, dict[str, Any]] = {}
        for item in _items():
            kc = item["kc_ids"][0]
            if kc not in picked and item["parts"][0]["answer"]["kind"] == "numeric":
                picked[kc] = item
        for n, item in enumerate(list(picked.values())[:5]):
            answer = item["parts"][0]["answer"]
            coach = [tutor(SAFE), tutor("That's right (checked). Well done.")]
            engine, _ = run(make_engine(tmp_path / f"p{n}", {"solver": [], "checker": [], "coach": coach},
                                        hardware_class="mid"))  # fmt: skip
            run(engine.start_practice(item))
            run(engine.student_turn(f"{answer['value']} {answer['unit']}"))
            run(close(engine))
            assert engine.state.solved, item["id"]
            boards.append(traced_numbers(engine))
    assert egress.attempts == [], "offline"
    total = sum(t for t, _ in boards)
    traced = sum(c for _, c in boards)
    assert total > 0 and traced == total, f"{traced}/{total} board numbers carry a check id"
