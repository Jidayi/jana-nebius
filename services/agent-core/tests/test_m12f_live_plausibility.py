"""VER-26 in live sessions: the pushed teaching skill's plausibility bands go with every worker call of a turn, and a
result the worker flags `implausible` is never shown as verified without the Checker's review (AGT-13 otherwise
unchanged). End to end through the engine with a scripted provider, the real worker and a bound learner store whose
session was opened on the motion topic (SKL-08 lesson context). Problems and replies are synthetic."""

from __future__ import annotations

import asyncio
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.engine.gates import untraced_numbers
from engine_harness import close, make_engine, reply, tutor
from memory_harness import SAFE, bind, store

LOOP = asyncio.new_event_loop()  # one loop for an engine and its worker
TOPIC = "cur.phy.o.motion_forces_and_energy.motion"
THROWN = "A ball is thrown straight up at 198 m/s. Take g = 9.8 m/s^2. How high does it rise?"
GENTLE = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def solve(speed: int) -> dict[str, Any]:
    return {"equations": ["v^2 = u^2 + 2*a*h"], "unknowns": ["h"], "units": {"h": "m"},
            "quantities": {"u": f"{speed} m/s", "a": "-9.8 m/s^2", "v": "0 m/s"}}  # fmt: skip


def last_check(body: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    for message in reversed(body["messages"]):
        if message["role"] == "tool":
            shown = json.loads(message["content"])
            return shown["check_id"], shown
    raise AssertionError("no tool result in the request")


def solver(speed: int, value: str, seen: list[dict[str, Any]]) -> list[Any]:
    """The Solver computes the height with the worker and hands over a plan citing that check."""

    def plan(body: dict[str, Any]) -> dict[str, Any]:
        check, shown = last_check(body)
        seen.append(shown)
        step = {"index": 1, "latex": f"h = {speed}^2 / (2 \\cdot 9.8)", "reason": "v = 0 at the top", "check_id": check,
                "kc_ref": None, "value": value, "unit": "m"}  # fmt: skip
        return reply(json.dumps({
            "status": "complete", "method_summary": "Use v^2 = u^2 + 2ah with v = 0 at the top.", "steps": [step],
            "final_answer": {"latex": f"h = {value}\\,m", "value": value, "unit": "m", "check_id": check,
                             "plausible": True},
            "blocked_step": None, "blocked_reason": None}))  # fmt: skip

    return [reply("", [("s0", "math_solve", solve(speed))]), plan]


def checker(verdict: str, tasks: list[str]) -> Any:
    """The Checker's verdict on the plan it is given, citing every check id in its task."""

    def judge(body: dict[str, Any]) -> dict[str, Any]:
        task = next(m["content"] for m in body["messages"] if m["role"] == "user")
        tasks.append(task)
        ids = sorted(set(re.findall(r"chk_[0-9A-Za-z]+", task)))
        wrong = verdict == "incorrect"
        return reply(json.dumps({
            "subject_of_check": "solver_plan", "verdict": verdict, "first_wrong_step": 1 if wrong else None,
            "error_category": "value" if wrong else "none", "why": "the launch speed reads as 19.8 m/s",
            "counterexample": None, "misconception_ref": None, "method": "re_derive",
            "step_marks": [{"step": 1, "status": "invalid" if wrong else "valid", "check_id": ids[0]}],
            "check_ids": ids}))  # fmt: skip

    return judge


def engine_on_topic(tmp_path: Path, script: dict[str, list[Any]]) -> tuple[Any, Any]:
    engine, provider = run(make_engine(tmp_path, script))
    held = store()
    sid = held.session(engine.state.session_id)
    held.conn.execute("UPDATE sessions SET topic_id = ? WHERE session_id = ?", (TOPIC, sid))
    bind(engine, held)
    return engine, provider


def _texts(engine: Any) -> str:
    """Every event the client gets, without its clock times and ids: a millisecond timestamp or an id can hold the
    digits of a canary value by chance (1792028420004 holds "2000"), and neither is anything a student reads."""

    def content(value: Any) -> Any:
        if isinstance(value, dict):
            return {k: content(v) for k, v in value.items() if not (k in ("ts", "id") or k.endswith(("_ts", "_id")))}
        if isinstance(value, list):
            return [content(v) for v in value]
        return value

    return json.dumps([content(f["event"]) for f in engine.events.frames])


def _roles(provider: Any) -> list[str]:
    return [r.get("_role") for r in provider.requests]


def test_ver26_live_implausible_result_not_shown_as_verified(tmp_path: Path) -> None:
    seen: list[dict[str, Any]] = []
    tasks: list[str] = []
    script = {"solver": solver(198, "2000.2", seen) * 2, "checker": [checker("incorrect", tasks)] * 2,
              "coach": [tutor(SAFE)]}  # fmt: skip
    engine, provider = engine_on_topic(tmp_path, script)
    try:
        assert engine._teaching_skill().name == "phy-o-motion", "the session's topic pushes the motion skill"
        bands = engine._tool_session("solver", "full").plausibility
        assert {b["quantity"] for b in bands} == {"speed", "acceleration", "height"}
        result = run(engine.start_problem(THROWN))
    finally:
        run(close(engine))
    # The worker flagged the height against the skill's band, and the Solver saw the warning with the value.
    assert seen and all(w["code"] == "implausible" for s in seen for w in s["warnings"])
    assert any("height" in w["message"] for w in seen[0]["warnings"])
    (check, flags), *_ = engine.state.implausible.items()
    assert check.startswith("chk_") and any("height" in f for f in flags)
    assert not any(abs(v - Fraction(20002, 10)) < 1 for v in engine.state.provenance()), "not a checked value"
    # The Checker reviewed it each time, given the flagged warning; it found a misread given, so the Solver was asked
    # again naming the implausible result, and in the end no plan is shown: the honest fallback, no number.
    assert _roles(provider).count("checker") == 2 and all("Flagged:" in t and check in t for t in tasks[:1])
    retry = [r for r in provider.requests if r.get("_role") == "solver"][2]
    assert "outside the plausible range" in json.dumps(retry["messages"])
    assert engine.state.plan is None and result.status == "complete"
    end = [f["event"] for f in engine.events.frames if f["event"]["type"] == "turn.end"][-1]
    assert end["degraded"] is True and end["degraded_reason"] == "plan_unverified"
    assert end["verification"] == "not_applicable", "never reported as verified"
    assert "2000" not in _texts(engine).replace(check, ""), "the implausible value reaches the student nowhere"
    assert engine.state.reviewed == []
    # The Solver and the Checker were given their slice of the skill (SKL-08): the sequence, the checklist and the
    # bands, never the Coach's hint ladder or worked exchange.
    for role in ("solver", "checker"):
        system = str(next(r for r in provider.requests if r.get("_role") == role)["messages"][0]["content"])
        assert "Plausible ranges" in system and "- height: 0.1 to 100 m" in system, role
        assert "Verification checklist" in system and "Hint ladder" not in system and "Worked exchange" not in system


def test_ver26_checker_review_clears_a_flagged_plan(tmp_path: Path) -> None:
    """A flagged result the Checker confirms against the question is shown, as a reviewed value."""
    seen: list[dict[str, Any]] = []
    tasks: list[str] = []
    script = {"solver": solver(198, "2000.2", seen), "checker": [checker("correct", tasks)], "coach": [tutor(SAFE)]}
    engine, provider = engine_on_topic(tmp_path, script)
    try:
        run(engine.start_problem(THROWN))
    finally:
        run(close(engine))
    assert _roles(provider).count("checker") == 1 and engine.state.plan is not None
    (check,) = engine.state.implausible
    assert engine.state.reviewed == [check] and engine.state.plan.final_check_id == check
    assert untraced_numbers({"say": "It rises 2000.2 m."}, engine.state, set()) == [], "reviewed: now traced"


def test_ver26_in_band_plan_skips_the_checker(tmp_path: Path) -> None:
    """With the same bands, an in-band result is verified by its check alone (AGT-13 unchanged)."""
    seen: list[dict[str, Any]] = []
    script = {"solver": solver(14, "10", seen), "checker": [], "coach": [tutor(SAFE)]}
    engine, provider = engine_on_topic(tmp_path, script)
    try:
        run(engine.start_problem(GENTLE))
    finally:
        run(close(engine))
    assert "warnings" not in seen[0] and engine.state.implausible == {}
    assert engine.state.plan is not None and "checker" not in _roles(provider)


def test_pushed_skill_is_cut_to_the_topic_budget(tmp_path: Path) -> None:
    """A pushed skill larger than the topic tier keeps its first whole sections instead of failing the call."""
    from agent_core.config import Settings
    from engine_harness import solver_steps

    budget = list(Settings().prompt_budget_compact)
    budget[4] = 1800  # tier 5, topic context
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), prompt_budget_compact=tuple(budget))
    engine, provider = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": [], "coach": [tutor(SAFE)]},
                                       settings=settings))  # fmt: skip
    held = store()
    held.conn.execute(
        "UPDATE sessions SET topic_id = ? WHERE session_id = ?", (TOPIC, held.session(engine.state.session_id))
    )
    bind(engine, held)
    try:
        result = run(engine.start_problem(GENTLE))
    finally:
        run(close(engine))
    assert result.status == "complete" and engine.state.plan is not None
    coach = next(r for r in provider.requests if r.get("_role") == "coach")
    system = str(coach["messages"][0]["content"])
    assert '<skill-procedure name="phy-o-motion"' in system and "## Worked exchange" not in system
    assert "## Objectives" in system or "## When to use" in system, "the first sections are kept"
    first_line = next(line for line in engine.deps.assets.roles["coach"].body.splitlines() if line.strip())
    assert first_line in system, "the role's own prompt is untouched by the cut"


def test_low_class_practice_with_a_pushed_skill_builds(tmp_path: Path) -> None:
    """On the low class (minimal prompt) the Coach's pushed skill is cut to fit, so a practice item still runs."""
    from jana_tools import REPO_ROOT
    from pack_builder.build import load_source

    items = load_source(REPO_ROOT / "content" / "curriculum" / "phy" / "o").tables["items"]
    item = next(i for i in items if i["id"] == "itm.phy.o.motion.0001")
    engine, provider = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": [tutor(SAFE)]},
                                       hardware_class="low", worker=False))  # fmt: skip
    try:
        result = run(engine.start_practice(item))
    finally:
        run(close(engine))
    assert result.status == "complete"
    sent = next(r for r in provider.requests if r.get("_role") == "coach")["messages"]
    # On the low class the topic opens the first user message, after the cached system prompt (D128).
    assert '<skill-procedure name="phy-o-motion"' in str(sent[1]["content"])


def test_ver26_flagged_value_is_untraced_until_reviewed() -> None:
    """The verified gate: a number traced only to an unreviewed implausible check is no checked value (H1)."""
    from agent_core.engine.state import SessionState

    state = SessionState("ses_01JZ0000000000000000000026")
    state.check_values = {"chk_aaa": [Fraction(20002, 10)], "chk_bbb": [Fraction(10)]}
    state.implausible = {"chk_aaa": ["height 2000.2 m is outside 0.1 to 100 m"]}
    assert untraced_numbers({"say": "It rises 2000.2 m, not 10 m."}, state, set()) == ["say: 10001/5"]
    state.reviewed.append("chk_aaa")
    assert untraced_numbers({"say": "It rises 2000.2 m."}, state, set()) == []
