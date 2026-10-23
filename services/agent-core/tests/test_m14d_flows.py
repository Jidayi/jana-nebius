"""M14.d: tutor flows, modes, the hint ladder's progression and the answer policy (AGT-19 to AGT-23, AGT-25, PED-01,
PED-02, PED-04, PED-06, PED-07, PED-09, PED-22, PED-24, PED-25, TOL-22).

The real engine with a scripted provider and the sandboxed tool worker where tools run; the S1 physics pack sources
for items and lessons; synthetic dialogues and the synthetic seeded-error set in `fixtures/seeded_errors.yaml`."""

from __future__ import annotations

import asyncio
import json
import socket
import sqlite3
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine import slice as flows
from agent_core.engine.gates import untraced_numbers
from agent_core.engine.learn import LearnDesk
from agent_core.engine.state import Plan, PlanStep, SessionState
from agent_core.engine.tutor_flows import (
    GUIDED_EDGES,
    MODE_CONTRACTS,
    MODES,
    POLICY_VALUES,
    GuidedFlow,
    LessonFlow,
    LessonPlan,
    MisconceptionFlow,
    PlanRefused,
    PolicyRefused,
    SavedQuestions,
    TutorFlows,
    contract,
    decide_mode_change,
    hint_request,
    mastery_weight,
    mode_tools,
    rung_source,
    skill_ladder,
    solution_template,
    validate_policy,
)
from agent_core.learner.mastery import MasteryParams, Opportunity, observations
from agent_core.store.generated.schema import DATABASES
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import connect
from agent_core.tools.catalogue import role_tools
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.scenarios import suite_errors
from pack_builder.build import load_source
from test_m10a_profiles import Api, code, student, with_api

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
SETTINGS = Settings()
LESSON = "les.phy.o.motion.speed_and_acceleration"
SEEDED = Path(__file__).parent / "fixtures" / "seeded_errors.yaml"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def plan_script(coach: list[Any]) -> dict[str, list[Any]]:
    return {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}


def shown(engine: Any, turn_id: str) -> str:
    return str(engine.events.student_text(turn_id))


def fake_clock(engine: Any) -> list[int]:
    now = [1_800_000_000_000]
    engine.events.clock_ms = lambda: now[0]
    return now


def collect(engine: Any) -> list[Any]:
    learned: list[Any] = []
    engine.learning = learned.extend
    return learned


def valid_payload(kind: str, payload: dict[str, Any]) -> bool:
    return contract_errors(f"learning/learning-event#/$defs/payload_{kind}", payload) == []


def items() -> list[dict[str, Any]]:
    return list(load_source(PACK).tables["items"])


def learner_db(path: Path) -> sqlite3.Connection:
    conn = connect(path)
    conn.executescript(DATABASES["learner"])
    return conn


# --- AGT-19 ----------------------------------------------------------------------------------------------------------


def agt19_guided_flow_edges() -> None:
    walked: set[tuple[str, str]] = set()

    def walk(flow: GuidedFlow) -> list[str]:
        walked.update(zip(flow.path, flow.path[1:], strict=False))
        return flow.path

    out_of_scope = GuidedFlow()
    out_of_scope.guard(in_scope=False)
    assert walk(out_of_scope) == ["question", "input_guard", "template"]
    unclear = GuidedFlow()
    unclear.guard(True)
    unclear.diagnosed(needs_clarification=True)
    assert walk(unclear)[-1] == "clarify"
    concept = GuidedFlow()
    concept.guard(True)
    concept.diagnosed(False, conceptual=True)  # a definition with nothing to calculate (D122)
    assert walk(concept) == ["question", "input_guard", "diagnoser", "concept", "coach_rung"]
    blocked = GuidedFlow()
    blocked.guard(True)
    blocked.diagnosed(False)
    blocked.plan_checked(False)
    blocked.plan_checked(False)
    assert walk(blocked) == ["question", "input_guard", "diagnoser", "solver", "checker_plan", "solver",
                             "checker_plan", "honest_blocker"]  # fmt: skip
    taught = GuidedFlow()
    taught.guard(True)
    taught.diagnosed(False)
    taught.plan_checked(True)
    taught.reply("answer")
    taught.checked(correct=False, last_step=False)
    taught.reply("stuck")
    taught.reply("side_question")
    taught.reply("answer")
    taught.checked(correct=True, last_step=False)
    taught.reply("answer")
    taught.checked(correct=True, last_step=True)
    assert walk(taught) == [
        "question", "input_guard", "diagnoser", "solver", "checker_plan", "coach_rung",
        "student_reply", "checker_diagnoser", "raise_rung_or_target", "coach_rung",
        "student_reply", "raise_rung_or_target", "coach_rung",
        "student_reply", "side_fork", "coach_rung",
        "student_reply", "checker_diagnoser", "coach_rung",
        "student_reply", "checker_diagnoser", "wrap_up",
    ]  # fmt: skip
    assert walked == set(GUIDED_EDGES), f"edges not covered: {set(GUIDED_EDGES) - walked}"
    with pytest.raises(ValueError, match="no edge"):
        GuidedFlow().reply("answer")  # code decides: no reply before the Coach has taught a rung


# --- AGT-20 ----------------------------------------------------------------------------------------------------------


def agt20_solution_numbers_checked(tmp_path: Path) -> None:
    unchecked = tutor("Substituting gives s = 12 m, so it rises 12 m.")
    checked = tutor("With v = 0 at the top, 0 = 14^2 - 2(9.8)s, so s = 10 m. Shall we try a similar problem?")
    coach = [tutor(SAFE), tutor("Not quite yet. What is the speed at the very top?"), unchecked, checked]
    engine, _ = run(make_engine(tmp_path, plan_script(coach)))
    learned = collect(engine)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))  # a checked attempt: solution mode is open under after_attempt
    board_before = [s.step_id for s in engine.state.board.steps]
    result = run(TutorFlows(engine).switch_mode("solution"))
    run(close(engine))
    text = shown(engine, result.turn_id)
    assert engine.state.mode == "solution" and result.status == "complete"
    assert "10" in text, "the leak gate is off in solution mode"
    assert "12" not in text, "the verified gate stays on"
    assert untraced_numbers({"say": text}, engine.state, engine._context_numbers()) == []
    verified = next(g for g in result.trace["gates"] if g["gate"] == "verified")
    assert verified["fired"] and verified["outcome"] == "passed_after_nudge"
    assert [s.step_id for s in engine.state.board.steps][: len(board_before)] == board_before
    kinds = [e.type for e in learned]
    assert "mode_change" in kinds and {"kind": "solution_view"} in [e.payload for e in learned]
    assert "attempt" not in kinds[kinds.index("mode_change") :], "solution mode adds no mastery observation"
    assert engine.state.scheduled and engine.state.scheduled[-1]["reason"] == "bottom_out"
    assert observations(Opportunity("solution", ("correct",), 0), MasteryParams()) == []


def test_agt20_policy_blocks_solution_mode(tmp_path: Path) -> None:
    engine, provider = run(make_engine(tmp_path, plan_script([tutor(SAFE), tutor("Not quite yet."), tutor(SAFE)])))
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))
    engine.state.solution_policy = "never"
    calls = len(provider.requests)
    result = run(TutorFlows(engine).switch_mode("solution"))
    run(close(engine))
    assert engine.state.mode == "solution" and len(provider.requests) > calls
    assert "switched full solutions off" not in shown(engine, result.turn_id)


# --- AGT-21 ----------------------------------------------------------------------------------------------------------


def agt21_first_error_rate(tmp_path: Path) -> None:
    seeded = yaml.safe_load(SEEDED.read_text())["items"]
    engine, _ = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": []}))
    turn = engine._begin("answer")
    found = 0
    for item in seeded:
        plan = Plan([], item["answer"], None, "chk_seed", "", f"{item['unknown']} = {item['answer']}")
        results = run(flows.check_lines(engine, turn, item["lines"], plan))
        first = next((i for i, r in enumerate(results) if r.status == "incorrect"), None)
        found += first == item["first_wrong"]
        if first is not None:
            assert all(r.carried_forward for r in results[first + 1 :]), "later lines carry the error forward"
    run(close(engine))
    rate = found / len(seeded)
    assert rate >= SETTINGS.gate_check_working_first_error, f"first wrong line found in {rate:.0%}"


def agt21_no_correction_leak(tmp_path: Path) -> None:
    # The literal corrected value traces to no check (a step check returns a verdict, not 19.6): the verified gate
    # stops it (AGT-10). Written from traced numbers, the same correction is an expression equal to the withheld
    # 19.6, which only the leak gate catches (AGT-09).
    literal = tutor("Line 3: 2 times 9.8 is 19.6, not 18.6, so it should read 19.6 s = 196.")
    leaky = tutor("Line 3 should read 2*9.8*s = 196, not 18.6*s = 196.")
    safe = tutor("Look again at line 3. Check the multiplication on its left side.")
    engine, _ = run(make_engine(tmp_path, plan_script([tutor(SAFE), literal, leaky, safe])))
    run(engine.start_problem(STATEMENT))
    working = "v^2 = u^2 + 2as\n0 = 14^2 - 2*9.8*s\n18.6*s = 196\ns = 196/18.6"
    result = run(engine.check_working(STATEMENT, working))
    run(close(engine))
    text = shown(engine, result.turn_id)
    assert "19.6" not in text and "10" not in text, "no corrected value for the wrong line"
    gates = {g["gate"]: g for g in result.trace["gates"]}
    assert gates["verified"]["fired"], "the unchecked corrected value was refused"
    assert gates["no_answer_leak"]["fired"], "the corrected value was withheld by the gate"


# --- AGT-22 / TOL-22 -------------------------------------------------------------------------------------------------


def _desk(db: Path) -> LearnDesk:
    tables = load_source(PACK).tables
    index = PackIndex.from_tables([({"pack_id": "pack.physics.o", "version": "0.1.0"}, tables)])
    return LearnDesk(index, connect(db), SETTINGS)


def agt22_lesson_resume(tmp_path: Path) -> None:
    db = tmp_path / "learner.db"
    learner_db(db).close()
    clock = iter(range(1_000, 100_000, 1_000))
    lesson = LessonFlow(_desk(db), LESSON, lambda: next(clock))
    first = lesson.open()
    record = load_source(PACK).tables["lessons"]
    pack_order = [b.get("type") for b in next(r for r in record if r["id"] == LESSON)["blocks"]]
    played = [first["type"]]
    played.append(lesson.advance()["type"])  # type: ignore[index]
    played.append(lesson.advance()["type"])  # type: ignore[index]
    assert played == pack_order[:3], "blocks play in pack order"
    assert [t["status"] for t in lesson.plan.todos[:4]] == ["done", "done", "in_progress", "pending"]
    # Restart: a fresh player over the same learner database resumes at the same block.
    again = LessonFlow(_desk(db), LESSON, lambda: next(clock))
    assert again.open() == lesson.block() and again.index == 2
    assert LessonFlow.route_question("what does acceleration mean again?") == "side_question"
    assert LessonFlow.route_question("a car goes from 3 m/s to 9 m/s in 2 s, what is its acceleration?") == (
        "after_lesson")  # fmt: skip


def test_tol22_lesson_plan_write() -> None:
    plan = LessonPlan()
    todos = [{"id": "a", "title": "Speed", "kc_ids": ["kc.phy.o.motion.average_speed"], "status": "in_progress"},
             {"id": "b", "title": "Check", "kc_ids": [], "status": "pending"}]  # fmt: skip
    assert plan.write(todos) == todos
    with pytest.raises(PlanRefused, match="dropped"):
        plan.write([todos[0]])
    with pytest.raises(PlanRefused, match="exactly one"):
        plan.write([{**todos[0], "status": "done"}, todos[1]])
    plan.write([{**todos[0], "status": "done"}, {**todos[1], "status": "in_progress"}])
    plan.write([{**todos[0], "status": "done"}, {**todos[1], "status": "skipped"},
                {"id": "c", "title": "Next", "kc_ids": [], "status": "in_progress"}])  # fmt: skip
    card = plan.card("Today")
    assert [i["id"] for i in card["items"]] == ["a", "c"]
    assert contract_errors("api/events#/$defs/card_plan", card) == []


# --- AGT-23 ----------------------------------------------------------------------------------------------------------


def _entry_question_before_hint(tmp_path: Path, start_rung: int = 2) -> None:
    item = next(i for i in items() if i["id"] == "itm.phy.o.motion.0001")
    coach = [tutor(SAFE), tutor("Which formula links distance, time and speed?", hint_rung=start_rung)]
    engine, provider = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": coach}))
    learned = collect(engine)
    engine.start_rung = lambda kcs: start_rung  # the learning system's start rung (LRN-18) for a low-mastery KC
    run(engine.start_practice(item, "a"))
    before = len(provider.requests)
    first = run(engine.student_turn("I'm stuck"))
    assert len(provider.requests) == before, "the entry question must not call a model"
    assert not [e for e in learned if e.type == "hint"]
    second = run(engine.student_turn("I'm stuck"))
    run(close(engine))
    assert shown(engine, first.turn_id) == engine.deps.templates.render("tpl.entry_question")
    assert first.tutor_turn is None, "exactly one entry question, with no model call"
    hints = [e.payload for e in learned if e.type == "hint"]
    assert [h["rung"] for h in hints] == [start_rung] and engine.state.rung == start_rung, (
        "then the first hint at the start rung"
    )
    assert second.tutor_turn is not None
    assert not any(r["_role"] == "solver" for r in provider.requests), "the item's stored solution is the plan"
    assert all(valid_payload("hint", h) for h in hints)


# --- AGT-25 ----------------------------------------------------------------------------------------------------------


def agt25_mode_switch_policy(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Here is the worked solution: s = 10 m.")]
    engine, _ = run(make_engine(tmp_path, plan_script(coach)))
    run(engine.start_problem(STATEMENT))
    flows_ = TutorFlows(engine)
    ids = [s.step_id for s in engine.state.board.steps]
    allowed = run(flows_.switch_mode("solution"))
    run(close(engine))
    assert allowed.status == "complete" and engine.state.mode == "solution"
    assert [s.step_id for s in engine.state.board.steps][: len(ids)] == ids, "every board step id is kept"
    assert engine.state.plan is not None and engine.state.problem is not None
    updated = [f["event"] for f in engine.events.frames if f["event"]["type"] == "session.updated"]
    assert any(e.get("mode") == "solution" for e in updated)


# --- PED-01 ----------------------------------------------------------------------------------------------------------


def ped01_mode_contracts(tmp_path: Path) -> None:
    engine, _ = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": []}, worker=False))
    deps = engine.deps

    def tools_of(role: str) -> list[str]:
        return list(role_tools(role, deps.assets.roles[role].tools, deps.registry, deps.grants, "S2", frozenset()))

    assert set(MODE_CONTRACTS) == set(MODES)
    assert mode_tools("mock", tools_of) == frozenset(), "the tutor is locked during a mock"
    compute = set(tools_of("solver")) - set(tools_of("coach"))
    assert compute and not compute & set(tools_of("coach")), "the Coach has no compute tools"
    for mode in MODES:
        exposed = mode_tools(mode, tools_of)
        declared = {t for role in MODE_CONTRACTS[mode].roles for t in tools_of(role)}
        assert exposed == declared, mode
    # Answer policy per mode: the leak gate withholds in every mode but solution; revision shows after the attempt.
    state = SessionState("ses_x")
    state.plan = Plan([PlanStep(1, "s = 10", "10", "m", "chk_abc")], "10", "m", "chk_abc", "", "s = 10 m")
    for mode in MODES:
        state.mode = mode
        assert bool(state.withheld()) == MODE_CONTRACTS[mode].leak_gate, mode
    state.mode, state.attempts = "revision", {1: 1}
    assert state.withheld() == [], "revision shows the answer right after the attempt (PED-25)"
    assert contract("revision", SETTINGS).rungs == (1, 2) and contract("guided").rungs == (1, 2, 3, 4, 5)


def ped01_mode_weights() -> None:
    params = MasteryParams.from_settings(SETTINGS)
    expected = {"guided": 1.0, "practice": 1.0, "mock": 1.0, "revision": 1.0, "check_working": 0.8, "learn": 0.5,
                "solution": 0.0}  # TABLE LRN-06b  # fmt: skip
    for mode in MODES:
        found = observations(Opportunity(mode, ("correct",), 0), params)
        assert mastery_weight(mode, SETTINGS) == expected[mode] == (found[0][1] if found else 0.0), mode


# --- PED-02 ----------------------------------------------------------------------------------------------------------


def test_ped02_blocked_switch(tmp_path: Path) -> None:
    state = SessionState("ses_x")
    assert decide_mode_change(state, "solution").allowed
    state.solution_policy = "never"
    state.attempts = {1: 2}
    decision = decide_mode_change(state, "solution")
    assert decision.allowed and decision.template is None
    engine, _ = run(make_engine(tmp_path, plan_script([tutor(SAFE)])))
    learned = collect(engine)
    run(engine.start_problem(STATEMENT))
    engine.state.solution_policy = "never"
    engine.state.mock_running = True
    result = run(TutorFlows(engine).switch_mode("solution"))
    run(close(engine))
    assert shown(engine, result.turn_id) == engine.deps.templates.render("tpl.mock_running")
    assert engine.state.mode == "guided" and not [e for e in learned if e.type == "mode_change"]


def ped02_mock_lock(tmp_path: Path) -> None:
    state = SessionState("ses_x", mock_running=True)
    for mode in MODES:
        if mode != "mock":
            assert decide_mode_change(state, mode).template == "tpl.mock_running", mode
    assert not decide_mode_change(SessionState("ses_y"), "mock", queue_empty=False).allowed
    engine, provider = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": []}, worker=False))
    engine.state.mock_running = True
    results = [run(engine.start_problem(STATEMENT)), run(engine.student_turn("I'm stuck")),
               run(engine.check_working(STATEMENT, "s = 10")),
               run(TutorFlows(engine).switch_mode("guided"))]  # fmt: skip
    for result in results:
        assert shown(engine, result.turn_id) == engine.deps.templates.render("tpl.mock_running")
        assert result.tutor_turn is None
    assert provider.requests == [], "no tutor turn and no model call during a sitting"


# --- PED-04 ----------------------------------------------------------------------------------------------------------


def ped04_hint_provenance(tmp_path: Path) -> None:
    engine, _ = run(make_engine(tmp_path, {"solver": [], "checker": [], "coach": []}, worker=False))
    generic = engine.deps.templates.hints
    skills = [s for s in engine.deps.assets.skills.skills.values() if skill_ladder(s)]
    assert skills, "teaching skills carry authored ladders"
    checked = 0
    for item in items():
        for part in item["parts"]:
            for rung in range(1, 6):
                source = rung_source(rung, item=item, part_id=part["id"], step_index=1, generic=generic)
                assert source.ref and source.text, (item["id"], part["id"], rung)
                assert source.source in ("item_ladder", "item_solution", "generic_template")
                checked += 1
    for skill in skills:
        for rung in range(1, 6):
            source = rung_source(rung, skill=skill, generic=generic)
            assert source.source == "skill_ladder" and source.ref == f"{skill.name}#hint-ladder.{rung}"
    assert rung_source(3, generic=generic).ref == "hints.3", "the generic template when no authored rung exists"
    assert checked > 100


# --- PED-06 ----------------------------------------------------------------------------------------------------------


def ped06_dwell_gap(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Not quite yet."), tutor(SAFE, hint_rung=1), tutor("Not quite yet."),
             tutor("Think about the speed at the top.", hint_rung=2)]  # fmt: skip
    engine, _ = run(make_engine(tmp_path, plan_script(coach)))
    learned = collect(engine)
    now = fake_clock(engine)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))
    run(engine.student_turn("I'm stuck"))
    assert engine.state.rung == 1
    now[0] += 4_000
    burst = run(engine.student_turn("I'm stuck"))
    assert engine.state.rung == 1, "two requests 4 s apart raise the rung once"
    assert shown(engine, burst.turn_id) == engine.deps.templates.render("tpl.help_seeking")
    assert {"kind": "hint_burst"} in [e.payload for e in learned if e.type == "integrity_signal"]
    now[0] += 30_000
    paused = run(engine.student_turn("I'm stuck"))
    assert engine.state.rung == 1 and shown(engine, paused.turn_id) == shown(engine, burst.turn_id), (
        "hints stay paused until an attempt arrives (LRN-19)")  # fmt: skip
    run(engine.student_turn("s = 8 m"))
    now[0] += 30_000
    run(engine.student_turn("I'm stuck"))
    run(close(engine))
    assert engine.state.rung == 2
    # The rung resets when the step changes; a barge-in re-ask is not a second request.
    state = SessionState("ses_x", attempts={1: 1, 2: 1})
    hint_request(state, 0, SETTINGS)
    assert hint_request(state, 1_000, SETTINGS, repeat=True).rung == 1 and not state.gaming
    state.step = 2
    assert hint_request(state, 2_000, SETTINGS).rung == 1


# --- PED-07 ----------------------------------------------------------------------------------------------------------


def ped07_bottom_out_effects(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Not quite yet."), tutor("Here is this step in full: 14^2 = 2(9.8)s at the top.",
                                                          hint_rung=5)]  # fmt: skip
    engine, provider = run(make_engine(tmp_path, plan_script(coach)))
    learned = collect(engine)
    now = fake_clock(engine)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))
    result = run(engine.student_turn("Show this step", show_step=True))
    run(close(engine))
    assert engine.state.rung == 5 and result.tutor_turn is not None
    hint = next(e.payload for e in learned if e.type == "hint")
    assert hint["rung"] == 5 and valid_payload("hint", hint)
    assert observations(Opportunity("guided", ("incorrect", "correct"), hint["rung"]), MasteryParams()) == [(0, 1.0)]
    assert {"kind": "bottom_out"} in [e.payload for e in learned if e.type == "integrity_signal"]
    scheduled = engine.state.scheduled[-1]
    low, high = SETTINGS.bottom_out_review_days
    day = 86_400_000
    from datetime import UTC, datetime

    def iso(ms: int) -> str:
        return datetime.fromtimestamp(ms / 1000, UTC).date().isoformat()

    assert (scheduled["earliest"], scheduled["latest"]) == (iso(now[0] + low * day), iso(now[0] + high * day))
    coach_request = [r for r in provider.requests if r["_role"] == "coach"][-1]
    assert "explain why it works" in json.dumps(coach_request), "the Coach asks the student to explain it back"


# --- PED-09 ----------------------------------------------------------------------------------------------------------


def ped09_policy_table() -> None:
    for value in POLICY_VALUES:
        for path in ("guided", "asked_in_text", "mock_review"):
            state = SessionState("ses_x")  # the one value: nothing in the state selects another (D87)
            assert solution_template(state) is None, (value, path)
            if path == "mock_review":
                state.mock_answer_submitted = True  # a submitted mock answer counts as the attempt
            else:
                state.attempts = {1: 1}
            unlocked = decide_mode_change(state, "solution").allowed
            assert unlocked, (value, path)
            from agent_core.engine.pedagogy import policy_template

            asked = policy_template(state, "just show me the full solution")
            assert asked is None, (value, path)


def ped09_no_policy_setting(tmp_path: Path) -> None:
    """A write of `solution_policy`, whatever its value or the profile's age, is rejected by the API (D86, D87)."""

    async def scenario(api: Api, r: Any) -> None:
        young = await api.add(student("Ama", "13_15"))
        grown = await api.add(student("Kojo", "18_plus"))
        token = (await api.unlock(young)).json()["profile_token"]
        refused = await api.call("PATCH", f"/v1/profiles/{young}/settings", {"solution_policy": "never"},
                                 profile=token)  # fmt: skip
        assert code(refused) == "validation_failed"
        allowed = await api.call("PATCH", f"/v1/profiles/{young}/settings", {"solution_policy": "never"},
                                 profile=token)  # fmt: skip
        assert code(allowed) == "validation_failed"
        own = (await api.unlock(grown)).json()["profile_token"]
        mine = await api.call("PATCH", f"/v1/profiles/{grown}/settings", {"solution_policy": "never"}, profile=own)
        assert code(mine) == "validation_failed", "retired policies cannot be set at any age"

    with_api(tmp_path, scenario)


def test_ped09_only_two_values(tmp_path: Path) -> None:
    for bad in ("always", "not_in_homework_hours", "", None):
        with pytest.raises(PolicyRefused):
            validate_policy(bad)
        with pytest.raises(ValueError):
            Settings(solution_policy=bad)
    # The settings table.
    conn = learner_db(tmp_path / "learner.db")
    for bad in ("always", "not_in_homework_hours"):
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO settings (key, value, source, hlc, updated_at) VALUES ('solution_policy', ?,"
                         " 'adult', '000000000000000-00000', 1)", (json.dumps(bad),))  # fmt: skip
    # The evaluation scenario contract.
    suite = yaml.safe_load((REPO_ROOT / "evals" / "safety" / "s2-scope.yaml").read_text())
    assert suite_errors(suite) == []
    suite["scenarios"][0]["setup"]["profile"]["settings"]["solution_policy"] = "always"
    assert suite_errors(suite), "the scenario contract has the two values only"

    # The API.
    async def scenario(api: Api, r: Any) -> None:
        young = await api.add(student("Esi"))
        token = (await api.unlock(young)).json()["profile_token"]
        for bad in ("always", "not_in_homework_hours"):
            reply = await api.call("PATCH", f"/v1/profiles/{young}/settings", {"solution_policy": bad},
                                   profile=token)  # fmt: skip
            assert code(reply) == "validation_failed", bad

    with_api(tmp_path / "api", scenario)


# --- PED-22 ----------------------------------------------------------------------------------------------------------


def ped22_flow_branches() -> None:
    mc, kc = "mc.phy.o.speed_distance_swap", "kc.phy.o.motion.average_speed"
    need = SETTINGS.misconception_active_evidence
    # One match, probe, matches again: name it, check item, correct: resolving.
    flow = MisconceptionFlow(mc, kc, need)
    assert flow.matched(evidence_count=1) == "probe"
    assert flow.probe_answered(matches_again=True) == "name_and_fix" and flow.status == "active"
    assert flow.check_item() == "discriminating_check"
    assert flow.check_answered(correct=True) == "resolving" and flow.status == "resolving"
    # One match, probe, no match: suspected, carry on.
    flow = MisconceptionFlow(mc, kc, need)
    flow.matched(1)
    assert flow.probe_answered(matches_again=False) == "continue" and flow.status == "suspected"
    # Enough evidence: named at once; a wrong check keeps it active and switches representation.
    flow = MisconceptionFlow(mc, kc, need)
    assert flow.matched(evidence_count=need) == "name_and_fix"
    flow.check_item()
    assert flow.check_answered(correct=False) == "switch_representation" and flow.status == "active"
    # A probe item's match is enough on its own.
    assert MisconceptionFlow(mc, kc, need).matched(1, source="probe") == "name_and_fix"
    for kind, payload in flow.events:
        assert valid_payload(kind, payload), payload
    with pytest.raises(ValueError):
        MisconceptionFlow(mc, kc, need).check_answered(True)


# --- PED-24 ----------------------------------------------------------------------------------------------------------


def _saving(tmp_path: Path) -> tuple[sqlite3.Connection, SavedQuestions, SessionState]:
    conn = learner_db(tmp_path / "learner.db")
    state = SessionState("ses_01HZZZZZZZZZZZZZZZZZZZZZZZ")
    conn.execute("INSERT INTO sessions (session_id, mode, started_at) VALUES (?, 'guided', 1)",
                 (state.session_id.removeprefix("ses_"),))  # fmt: skip
    from agent_core.engine.state import Problem

    state.problem = Problem("prb_x", STATEMENT, "prb_x#statement")
    clock = iter(range(1_700_000_000_000, 1_800_000_000_000, 1_000))
    return conn, SavedQuestions(conn, SETTINGS.retention_saved_content_days * 86_400_000, lambda: next(clock)), state


def ped24_triggers(tmp_path: Path) -> None:
    conn, saved, state = _saving(tmp_path)
    reasons = ["stuck", "repeated_error", "verification_disagreement", "outside_content", "student_requested"]
    for n, reason in enumerate(reasons, 1):
        assert saved.save(state, reason) is not None  # type: ignore[arg-type]
        assert saved.save(state, reason) is None, "the same trigger does not add a second item"  # type: ignore[arg-type]
        assert conn.execute("SELECT count(*) FROM saved_questions").fetchone()[0] == n
    for (content,) in conn.execute("SELECT content FROM saved_questions"):
        snapshot = json.loads(content)
        assert contract_errors("learning/student-records#/$defs/question_snapshot", snapshot) == []
    # The misconception trigger: three fixes that did not hold.
    flow = MisconceptionFlow("mc.phy.o.speed_distance_swap", "kc.phy.o.motion.average_speed", 1)
    for _ in range(SETTINGS.misconception_fixes_before_save):
        flow.matched(1)
    assert flow.survived(SETTINGS.misconception_fixes_before_save)


def ped24_offline_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    conn, saved, state = _saving(tmp_path)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_schema WHERE type = 'table' AND name NOT LIKE "
                                         "'%fts%'")]  # fmt: skip

    def counts() -> dict[str, int]:
        return {t: conn.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0] for t in tables}  # noqa: S608

    before = counts()

    def refuse(*_: Any, **__: Any) -> None:
        raise AssertionError("a saved question opened a network connection")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    for reason in ("stuck", "student_requested"):
        saved.save(state, reason)  # type: ignore[arg-type]
    after = counts()
    changed = {t for t in tables if after[t] != before[t]}
    assert changed == {"saved_questions"}, "nothing queued for a teacher and nothing sent"
    assert not hasattr(saved, "send") and not hasattr(saved, "share")


# --- PED-25 ----------------------------------------------------------------------------------------------------------


def test_ped25_revision_hints_rungs_one_and_two() -> None:
    state = SessionState("ses_x", mode="revision", attempts={1: 1})
    rungs = []
    for n in range(4):
        rungs.append(hint_request(state, n * 60_000, SETTINGS).rung)
    assert rungs == [1, 2, 2, 2], "revision limits hints to rungs 1 and 2"
    state.plan = Plan([PlanStep(1, "s = 10", "10", "m", "chk_abc")], "10", "m", "chk_abc", "", "s = 10 m")
    assert state.withheld() == [], "the answer shows right after the attempt"
    state.attempts = {}
    assert state.withheld(), "and is withheld until then"


def test_saved_question_snapshot_pins_only_this_problems_checked_lines(tmp_path):
    import hashlib

    from agent_core.engine.state import BoardStep

    conn, saved, state = _saving(tmp_path)
    state.board.problem_key = f"{state.problem.problem_id}:{hashlib.sha256(STATEMENT.encode()).hexdigest()[:16]}"
    state.board.steps = [
        BoardStep("good", 0, "v=20/4", "Checked division", "tutor", "final", "chk_fixture"),
        BoardStep("unchecked", 1, "x=999", "Unsupported", "tutor", "unchecked"),
        BoardStep("bad", 2, "x=9", "A mistake", "student", "incorrect", "chk_bad"),
    ]
    identity = saved.save(state, "student_requested")
    pinned = json.loads(
        conn.execute("SELECT content FROM saved_questions WHERE question_id=?", (identity,)).fetchone()[0]
    )
    assert pinned["board"] == [{"latex": "v=20/4", "reason": "Checked division"}]
    state.board.steps[0].latex = "changed later"
    assert (
        json.loads(conn.execute("SELECT content FROM saved_questions WHERE question_id=?", (identity,)).fetchone()[0])
        == pinned
    )
    state.board.problem_key = "another problem"
    other = saved.save(state, "stuck")
    assert (
        json.loads(conn.execute("SELECT content FROM saved_questions WHERE question_id=?", (other,)).fetchone()[0])[
            "board"
        ]
        == []
    )


def agt23_attempt_before_hint(tmp_path: Path) -> None:
    _entry_question_before_hint(tmp_path)


@pytest.mark.parametrize("start_rung", [1, 2, 3])
def uxs17_attempt_before_hint(tmp_path: Path, start_rung: int) -> None:
    _entry_question_before_hint(tmp_path, start_rung)
