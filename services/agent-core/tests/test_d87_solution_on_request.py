"""D87: the full worked solution on request (PED-09 `on_request`, PED-02, AGT-20, AGT-24, AGT-25, PRD-06,
TCH-13, UXS-18, JRN-09).

A request for the full solution switches the session to solution mode at once, on every path the build has: nothing
(no attempt, rung, skill pacing or setting) holds it back, and only a running mock exam does. Guided mode still never
volunteers the answer unasked. Replies are scripted; questions, items and student lines are synthetic."""

from __future__ import annotations

import asyncio
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.state import numbers_in, state_from_json, state_to_json
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import scenarios as runner
from memory_harness import item, store

LOOP = asyncio.new_event_loop()  # one loop for the module: the sandboxed workers belong to the loop that started them
SAFE = "Which quantities does the question give you, and which one does it ask for?"
LEAK = "It rises 10 m. Which equation did you use?"
SOLVED = "The worked solution is on the board with every number checked. Shall we try a similar one step by step?"
REQUEST = "Just tell me the answer"
STRUCTURAL = {Fraction(0), Fraction(1), Fraction(2)}


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


async def opened(tmp_path: Path, coach: list[Any], *, problems: int = 1, **kw: Any) -> tuple[Any, Any]:
    """An engine whose Solver can plan `problems` questions; the first is opened in guided mode."""
    solver = [step for _ in range(problems) for step in solver_steps()]
    engine, provider = await make_engine(tmp_path, {"solver": solver, "checker": checker_steps(), "coach": coach}, **kw)
    await engine.start_problem(STATEMENT)
    return engine, provider


def events(engine: Any, turn_id: str | None = None, kind: str | None = None) -> list[dict[str, Any]]:
    frames = [f for f in engine.events.frames if turn_id is None or f["turn_id"] == turn_id]
    return [f["event"] for f in frames if kind is None or f["event"]["type"] == kind]


def solution_shown(engine: Any, result: Any) -> bool:
    """The turn switched to solution mode with no template and put the verified answer on the board under its
    check, every number on the board traced to a check of the session or given in the question (AGT-20)."""
    state = engine.state
    if state.mode != "solution" or result.tutor_turn is None or engine.turn_log[-1]["template"] is not None:
        return False
    steps = [s for s in events(engine, result.turn_id, "board.step") if s["owner"] == "tutor"]
    givens = set(numbers_in(state.problem.statement))
    for step in steps:
        shown = [n for n in numbers_in(runner.EXPONENT.sub("", step["latex"])) if n not in STRUCTURAL | givens]
        checked = state.check_values.get(step["check_id"] or "", [])
        if shown and not all(any(abs(n - v) <= abs(v) / 1000 for v in checked) for n in shown):
            return False
    final = state.plan.final_check_id
    return any(s["check_id"] == final for s in steps)


def learned(held: Any, kind: str) -> list[dict[str, Any]]:
    rows = held.conn.execute("SELECT payload FROM events WHERE type = ? ORDER BY seq", (kind,)).fetchall()
    return [json.loads(r[0]) for r in rows]


# --- PED-09 -----------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("before", [[], ["I'm stuck"], ["I'm stuck", "I'm stuck", "I'm stuck"], ["s = 3 m"]],
                         ids=["no_attempt", "after_entry_question", "at_rung_2", "after_wrong_attempt"])  # fmt: skip
def ped09_solution_on_request(tmp_path: Path, before: list[str]) -> None:
    """No attempt, rung or earlier turn gates a request, and nothing configures it: a retired answer-policy value on
    the engine state is never read, and a stored session from an earlier build with fields this one dropped loads."""
    coach = [tutor(SAFE)] + [tutor(SAFE, hint_rung=n) for n in (1, 2)] + [tutor(SOLVED)]
    if before == ["s = 3 m"]:
        coach = [tutor(SAFE), tutor("Not quite yet. Which equation did you use?"), tutor(SOLVED)]
    engine, _ = run(opened(tmp_path, coach))
    try:
        for line in before:
            run(engine.student_turn(line))
        assert engine.state.mode == "guided" and engine.state.withheld()
        engine.state.solution_policy = "never"  # retired (D86, D87): no value of it is a gate
        result = run(engine.student_turn(REQUEST))
        assert solution_shown(engine, result)
        assert engine.state.withheld() == [], "the leak gate is off in solution mode; the verified gate stays on"
    finally:
        run(close(engine))
    stored = state_to_json(engine.state) | {"answer_limit": "never"}  # a field no build of this one keeps
    assert state_from_json(stored).mode == "solution"


@pytest.mark.parametrize("wording", ["Show me the full worked solution", "give me the complete solution please",
                                     "Tell me the whole working", "show me the answer", "Show me the full solution",
                                     "just tell me the step-by-step solution"])  # fmt: skip
def test_d87_every_wording_of_the_request_is_one(wording: str) -> None:
    """D87, PED-09: a request for the full solution is one however it is worded; a line that only mentions working or
    an answer is not."""
    from agent_core.engine.pedagogy import wants_solution

    assert wants_solution(wording), wording
    assert not wants_solution("I showed the working on the board"), "a mention is not a request"
    assert not wants_solution("is my answer right?")


def test_ped09_policy_table_engine(tmp_path: Path) -> None:
    """TABLE PED-09a's one value, `on_request`: in guided mode the answer stays withheld (a Coach draft that states it
    is regenerated before anything reaches the student) until the student asks; the request opens the verified
    solution at once, and a running mock exam is the only lock."""
    coach = [tutor(SAFE), tutor(LEAK), tutor(SAFE), tutor(SOLVED)]
    engine, provider = run(opened(tmp_path, coach))
    try:
        guided = run(engine.student_turn("I think it goes up quite high"))
        assert next(g for g in guided.trace["gates"] if g["gate"] == "no_answer_leak")["fired"]
        assert "10 m" not in " ".join(e["delta"] for e in events(engine, guided.turn_id, "text.delta"))
        engine.state.mock_running = True
        calls = len(provider.requests)
        locked = run(engine.student_turn(REQUEST))
        assert engine.turn_log[-1]["template"] == "tpl.mock_running" and locked.tutor_turn is None
        assert len(provider.requests) == calls and engine.state.mode == "guided", "no model call during a sitting"
        engine.state.mock_running = False
        assert solution_shown(engine, run(engine.student_turn(REQUEST)))
    finally:
        run(close(engine))


# --- PED-02, AGT-25 ---------------------------------------------------------------------------------------------------


def ped02_switch_on_request(tmp_path: Path) -> None:
    """Guided → solution at once on the request: every board step and the plan stay, the change is recorded as a
    `mode_change` learning event with its reason and reaches the client as `session.updated`."""
    held = store()
    coach = [tutor(SAFE), tutor("Not quite yet. Which equation did you use?"), tutor(SOLVED)]
    engine, _ = run(opened(tmp_path, coach))
    engine.learning = held.learner.record_batch
    try:
        run(engine.student_turn("s = 3 m"))
        board_before = [s.step_id for s in engine.state.board.steps]
        plan_before = engine.state.plan
        result = run(engine.student_turn(REQUEST))
    finally:
        run(close(engine))
    assert solution_shown(engine, result)
    assert [s.step_id for s in engine.state.board.steps][: len(board_before)] == board_before
    assert engine.state.plan is plan_before
    [change] = learned(held, "mode_change")
    assert change == {"session_id": engine.state.session_id.removeprefix("ses_"), "from_mode": "guided",
                      "to_mode": "solution", "reason": "student_request"}  # fmt: skip
    assert {"type": "session.updated", "mode": "solution"} in events(engine, result.turn_id, "session.updated")


# --- AGT-20 -----------------------------------------------------------------------------------------------------------


def agt20_solution_on_request(tmp_path: Path) -> None:
    """Before any attempt the request reaches solution mode with the Solver's plan, every number on the board traced
    to a check; solution mode adds no mastery evidence (an answer to a practice item after its solution records no
    attempt)."""
    engine, _ = run(opened(tmp_path, [tutor(SAFE), tutor(SOLVED)]))
    try:
        assert engine.state.attempts == {}
        result = run(engine.student_turn("Show me the whole solution"))
        assert solution_shown(engine, result)
        assert {c["name"] for c in engine.turn_log[0]["tools"]} >= {"math_solve"}, "the Solver's tool-checked plan"
    finally:
        run(close(engine))

    held = store()
    practice, _ = run(make_engine(tmp_path / "practice", {"coach": [tutor(SAFE), tutor(SOLVED),
                                                                    tutor("That matches the solution.")]}))  # fmt: skip
    practice.learning = held.learner.record_batch
    try:
        run(practice.start_practice(item()))
        shown = run(practice.student_turn("Give me the answer"))
        assert solution_shown(practice, shown)
        run(practice.student_turn("8.0 m/s"))
    finally:
        run(close(practice))
    assert learned(held, "attempt") == [] and learned(held, "verdict") == []


# --- AGT-24 -----------------------------------------------------------------------------------------------------------


def agt24_review_solution_on_request(tmp_path: Path) -> None:
    """During a sitting no tutor turn runs and a request for the solution gets the mock template with no model call.
    After it, on an item with its stored verified solution (what a review loads), guided mode volunteers no answer
    and the item's worked solution is given on request. The review origin itself (`exam_review`, "Show me why") is
    not in this build."""
    engine, provider = run(make_engine(tmp_path, {"coach": [tutor(SAFE), tutor("It is 8.0 m/s. Which formula?"),
                                                            tutor(SAFE), tutor(SOLVED)]}))  # fmt: skip
    try:
        run(engine.start_practice(item()))
        engine.state.mock_running = True
        calls = len(provider.requests)
        for locked in (engine.student_turn("Show me the solution"), engine.show_solution()):
            assert run(locked).tutor_turn is None and engine.turn_log[-1]["template"] == "tpl.mock_running"
        assert len(provider.requests) == calls and engine.state.mode == "guided"
        engine.state.mock_running = False
        guided = run(engine.student_turn("I divided something"))
        assert next(g for g in guided.trace["gates"] if g["gate"] == "no_answer_leak")["fired"]
        assert solution_shown(engine, run(engine.student_turn("Show me the solution")))
    finally:
        run(close(engine))


# --- PRD-06, TCH-13, UXS-18 -------------------------------------------------------------------------------------------

PATHS = ("chat_request", "question_with_request", "mode_menu", "practice_item", "check_my_working")


async def _path(tmp_path: Path, path: str, attempt: bool) -> tuple[Any, Any, int]:
    """One client path of the build to the full solution, with or without an attempt first. Returns the engine, the
    turn that answered the request and the attempts made before it."""
    coach = [tutor(SAFE), tutor("Not quite yet. Which equation did you use?"), tutor(SOLVED)]
    if path == "practice_item":
        engine, _ = await make_engine(tmp_path, {"coach": coach})
        await engine.start_practice(item())
        if attempt:
            await engine.student_turn("6 m/s")
    elif path == "question_with_request":
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                 "coach": coach[2:]})  # fmt: skip
    elif path == "check_my_working":
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                 "coach": coach[1:]})  # fmt: skip
        await engine.check_working(STATEMENT, "v^2 = u^2 + 2as\n0 = 14^2 - 2*9.8*s\n18.6*s = 196")
    else:
        engine, _ = await opened(tmp_path, coach)
        if attempt:
            await engine.student_turn("s = 3 m")
    attempts = sum(engine.state.attempts.values())
    if path == "question_with_request":
        result = await engine.start_problem(f"{STATEMENT} Just give me the answer.")
    elif path == "mode_menu":
        result = await engine.show_solution()
    else:
        result = await engine.student_turn("Give me the answer please")
    return engine, result, attempts


@pytest.mark.parametrize(("path", "attempt"), [(p, a) for p in PATHS for a in (False, True)
                                               if not (a and p == "question_with_request")])  # fmt: skip
def prd06_solution_on_request_all_paths(tmp_path: Path, path: str, attempt: bool) -> None:
    """Every client path of this build gets the full solution on request, before or after an attempt. Not in this
    build, so not covered here: "Show me why" review, the photo question, worked-solution search and voice."""
    engine, result, attempts = run(_path(tmp_path, path, attempt))
    try:
        assert solution_shown(engine, result), path
        if path != "check_my_working":
            assert (attempts > 0) == attempt
    finally:
        run(close(engine))


def uxs18_solution_on_request(tmp_path: Path) -> None:
    """Before any attempt the mode menu, its key (the same engine entry, or a session opened in solution mode) and a
    chat request each reach solution mode; a running mock exam is the only thing that blocks it."""
    for entry in ("menu", "chat"):
        engine, _ = run(opened(tmp_path / entry, [tutor(SAFE), tutor(SOLVED)]))
        try:
            engine.state.mock_running = True
            blocked = run(engine.show_solution() if entry == "menu" else engine.student_turn(REQUEST))
            assert blocked.tutor_turn is None and engine.state.mode == "guided"
            engine.state.mock_running = False
            result = run(engine.show_solution() if entry == "menu" else engine.student_turn(REQUEST))
            assert solution_shown(engine, result), entry
        finally:
            run(close(engine))
    keyed, _ = run(make_engine(tmp_path / "key", {"solver": solver_steps(), "checker": checker_steps(),
                                                  "coach": [tutor(SOLVED)]}))  # fmt: skip
    keyed.state.mode = "solution"
    try:
        assert solution_shown(keyed, run(keyed.start_problem(STATEMENT))), "a question in solution mode opens solved"
    finally:
        run(close(keyed))


# --- JRN-09 -----------------------------------------------------------------------------------------------------------


def jrn09_solution_on_request(tmp_path: Path) -> None:
    """The answer-seeker journey, scripted: (1) a pasted question with "just give me the answer" opens the verified
    solution at once, no attempt asked for; (2) it adds no mastery evidence; (3) another question starts guided
    again and asking gets its solution too; (4) trying the similar problem is guided, the tutor volunteers nothing
    unasked, and she can still ask. Step 3's photo is not in this build (typed here)."""
    held = store()
    coach = [tutor(SOLVED), tutor(SAFE), tutor(SOLVED), tutor(LEAK), tutor(SAFE), tutor(SOLVED)]
    engine, _ = run(make_engine(tmp_path, {"solver": [s for _ in range(3) for s in solver_steps()],
                                           "checker": checker_steps(), "coach": coach}))  # fmt: skip
    engine.learning = held.learner.record_batch
    try:
        first = run(engine.start_problem(f"{STATEMENT} just give me the answer"))
        assert solution_shown(engine, first) and engine.state.attempts == {}
        assert learned(held, "attempt") == [] and learned(held, "verdict") == []
        run(engine.start_problem(STATEMENT))
        assert engine.state.mode == "guided"
        assert solution_shown(engine, run(engine.student_turn("just give me the answer")))
        similar = run(engine.start_problem(STATEMENT))
        assert engine.state.mode == "guided" and engine.state.withheld()
        assert next(g for g in similar.trace["gates"] if g["gate"] == "no_answer_leak")["fired"]
        assert solution_shown(engine, run(engine.student_turn(REQUEST)))
    finally:
        run(close(engine))
    reasons = [(c["from_mode"], c["to_mode"], c["reason"]) for c in learned(held, "mode_change")]
    assert reasons == [("guided", "solution", "student_request"), ("solution", "guided", "student_request")] * 2 + [
        ("guided", "solution", "student_request")
    ]


@pytest.mark.parametrize(
    ("path", "attempt"), [(p, a) for p in PATHS for a in (False, True) if not (a and p == "question_with_request")]
)
def tch13_solution_on_request(tmp_path: Path, path: str, attempt: bool) -> None:
    """Family settings cannot impose an attempt/rung prerequisite on any engine entry to a solution.

    The API/photo/review and search entries have additional cases under this same acceptance name in their
    integration modules. Real voice-model quality belongs to the separate S3 release evidence.
    """
    engine, result, attempts = run(_path(tmp_path, path, attempt))
    try:
        assert solution_shown(engine, result), path
        if not attempt and path != "check_my_working":
            assert attempts == 0
        assert engine.state.mode == "solution"
    finally:
        run(close(engine))
