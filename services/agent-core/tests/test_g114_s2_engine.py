"""G114: the S2 engine as the build runs it. The build stage from configuration (ARC-27, AGT-15), the input-guard and
rule-matcher roles on the turn path (AGT-02, PED-15, PRV-18), the guided and misconception flows driving live turns
(AGT-19, PED-22), the saved-question triggers (PED-24, LRN-26), the nearest topic for a question beyond the level
(PRV-13), the lesson flow over the API (AGT-22, TOL-22) and the spoken-form overlay (PRM-26).

The real engine, registry, router and worker with scripted providers; questions, items and replies are synthetic, and
the lesson and items are the S1 physics pack's sources."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config.resolve import app_settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine import live_flows
from agent_core.engine.assembly import assemble
from agent_core.engine.events import new_id
from agent_core.engine.state import SessionState
from agent_core.engine.tone import fit_spoken
from agent_core.engine.tutor_flows import GUIDED_EDGES
from agent_core.prompts.builder import PromptSession, build_prompt
from agent_core.providers.scripted import ScriptedProvider
from agent_core.retrieval.index import KnowledgeIndex
from engine_harness import STATEMENT, close, reply, solver_steps, tutor
from engine_harness import make_engine as harness_engine
from jana_tools import REPO_ROOT
from pack_builder.build import load_source

LOOP = asyncio.new_event_loop()
PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
SAFE = "Which quantities does the question give you, and which one does it ask for?"
MISCONCEPTION_ITEM = "itm.phy.o.atom.0016"  # option B is the matched misconception, A is right
MISCONCEPTION = "mc.phy.o.isotopes_differ_in_protons"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def settings(**overrides: Any) -> Settings:
    return Settings(**{"worker_pool_size": 1, "worker_respawn_backoff_s": (0.0,), "worker_warm_target_s": 20.0,
                       "worker_call_cpu_ms": 30000, **overrides})  # fmt: skip


async def make_engine(tmp: Path, script: dict[str, Any], **kw: Any) -> Any:
    return await harness_engine(tmp, script, **{"settings": settings(), "stage": "S2", **kw})


def structured(payload: dict[str, Any]) -> dict[str, Any]:
    return reply(json.dumps(payload))


def guard(cls: str = "in_scope", confidence: float = 0.9) -> dict[str, Any]:
    return structured({"class": cls, "confidence": confidence})


def diagnosis(**fields: Any) -> dict[str, Any]:
    out = {"in_scope": True, "subject": "physics", "topic_ref": None, "kc_refs": [], "question_kind": "calculation",
           "knowns": [], "unknowns": ["height"], "clarifying_question": None, "misconception_ref": None,
           "evidence": [], "inference": "", "prerequisite_gap_refs": [], "confidence": "medium"}  # fmt: skip
    out.update(fields)
    return structured(out)


def cannot_verify() -> dict[str, Any]:
    return structured({"subject_of_check": "student_answer", "verdict": "cannot_verify", "first_wrong_step": None,
                       "error_category": "none", "why": "", "counterexample": None, "misconception_ref": None,
                       "method": "substitute_back", "step_marks": [], "check_ids": []})  # fmt: skip


def unverified_plan() -> dict[str, Any]:
    """A schema-valid plan whose answer no tool produced: it cannot pass the verified gate."""
    step = {"index": 1, "latex": "v^2 = u^2 + 2as", "reason": "links the quantities", "check_id": None,
            "kc_ref": None, "value": None, "unit": None}  # fmt: skip
    return structured({"status": "complete", "method_summary": "Use v^2 = u^2 + 2as.", "steps": [step],
                       "final_answer": {"latex": "s = 12", "value": "12", "unit": "m", "check_id": "chk_missing00",
                                        "plausible": True}, "blocked_step": None, "blocked_reason": None})  # fmt: skip


def item(item_id: str) -> dict[str, Any]:
    return next(i for i in load_source(PACK).tables["items"] if i["id"] == item_id)


def knowledge() -> KnowledgeIndex:
    source = load_source(PACK)
    return KnowledgeIndex.from_tables([(dict(source.pack), {t: list(rows) for t, rows in source.tables.items()})])


def roles(provider: ScriptedProvider) -> list[str]:
    return [str(r.get("_role")) for r in provider.requests]


# --- the build stage (ARC-27 layers, AGT-15) -----------------------------------------------------------------------


def test_the_build_runs_the_s2_stage_from_configuration(tmp_path: Path) -> None:
    """The app's engine runs the stage its build is configured for (S2); a development build can run S1 through the
    developer layer, and a release build ignores that override (ARC-27)."""
    assert Settings().build_stage == "S2"
    assert app_settings("development", {}).build_stage == "S2"
    assert app_settings("development", {"JANA_BUILD_STAGE": "S1"}).build_stage == "S1"
    assert app_settings("release", {"JANA_BUILD_STAGE": "S1"}).build_stage == "S2"
    state = SessionState(new_id("ses"))
    engine = assemble({}, Settings(), state, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path / "spill")
    assert engine.deps.stage == "S2"
    assert engine.rules is not None and engine.rules.judge is not None, "the rule matcher role judges from S2"
    s1 = assemble({}, Settings(build_stage="S1"), SessionState(new_id("ses")), REPO_ROOT / "content" / "agent",
                  REPO_ROOT / "skills", tmp_path / "spill1")  # fmt: skip
    assert s1.deps.stage == "S1" and s1.rules is not None and s1.rules.judge is None


# --- AGT-19 on the live turn loop -----------------------------------------------------------------------------------


def test_agt19_live_dialogue_walks_the_diagram(tmp_path: Path) -> None:
    """A scripted dialogue through the S2 engine takes the guided flow's edges at the live turn points: input guard,
    Diagnoser, plan checks, the rung, each kind of reply, the code's verdict and the wrap-up (AGT-19)."""
    walked: set[tuple[str, str]] = set()
    script = {
        "input_guard": [guard()] * 6,
        "diagnoser": [diagnosis(), diagnosis(), diagnosis()],
        "solver": solver_steps(),
        "checker": [cannot_verify(), cannot_verify()],
        "coach": [tutor(SAFE)] * 6,
    }  # fmt: skip
    engine, provider = run(make_engine(tmp_path / "taught", script))
    try:
        run(engine.start_problem(STATEMENT))
        assert engine.guided.path == ["question", "input_guard", "diagnoser", "solver", "checker_plan", "coach_rung"]
        run(engine.student_turn("s = 7 m"))  # wrong: the Checker and Diagnoser read it, the engine raises the rung
        assert engine.guided.path[-4:] == ["student_reply", "checker_diagnoser", "raise_rung_or_target", "coach_rung"]
        assert engine.state.rung == 1, "a wrong answer raises the rung (to the start rung on the first)"
        run(engine.student_turn("I'm stuck", stuck=True))
        assert engine.guided.path[-3:] == ["student_reply", "raise_rung_or_target", "coach_rung"]
        run(engine.side_question("What does deceleration mean?"))
        assert engine.guided.path[-3:] == ["student_reply", "side_fork", "coach_rung"]
        run(engine.student_turn("v^2 = u^2 + 2as"))  # a line no check settles: back to the step's rung
        assert engine.guided.path[-3:] == ["student_reply", "checker_diagnoser", "coach_rung"]
        run(engine.student_turn("s = 10 m"))
        assert engine.guided.path[-3:] == ["student_reply", "checker_diagnoser", "wrap_up"]
        assert engine.state.solved
        walked.update(zip(engine.guided.path, engine.guided.path[1:], strict=False))
    finally:
        run(close(engine))
    assert "input_guard" in roles(provider) and "diagnoser" in roles(provider)

    # A question the input guard routes to a template.
    engine, _ = run(make_engine(tmp_path / "scope", {"input_guard": [guard("off_topic")]}, worker=False))
    try:
        result = run(engine.start_problem("Who will win on Saturday?"))
        assert result.stop_reason == "safety" and engine.guided.path == ["question", "input_guard", "template"]
        walked.update(zip(engine.guided.path, engine.guided.path[1:], strict=False))
    finally:
        run(close(engine))

    # The Diagnoser needs one clarifying question: the Coach asks it and the turn ends; the reply completes it.
    clarify = {"input_guard": [guard(), guard()], "diagnoser": [diagnosis(clarifying_question="Which height?")],
               "solver": solver_steps(), "coach": [tutor("Which value of g do we use?"), tutor(SAFE)]}  # fmt: skip
    engine, _ = run(make_engine(tmp_path / "clarify", clarify))
    try:
        run(engine.start_problem("A ball is thrown straight up at 14 m/s. How high?"))
        assert engine.guided.path[-1] == "clarify" and engine.state.plan is None
        walked.update(zip(engine.guided.path, engine.guided.path[1:], strict=False))
        run(engine.student_turn("Take g = 9.8 m/s^2 and find the greatest height."))
        assert engine.state.plan is not None and engine.guided.path[-1] == "coach_rung"
    finally:
        run(close(engine))

    # A definition with nothing to calculate skips the Solver (D122): the Coach explains and asks one check question,
    # and the student's reply goes on through the ordinary reply edges.
    concept = {"input_guard": [guard(), guard()],
               "diagnoser": [diagnosis(question_kind="definition", unknowns=["formula for kinetic energy"])],
               "coach": [tutor("Kinetic energy is the energy of motion. What does each letter stand for?"),
                         tutor(SAFE)]}  # fmt: skip
    engine, provider = run(make_engine(tmp_path / "concept", concept))
    try:
        run(engine.start_problem("What is the formula for kinetic energy?"))
        assert engine.guided.path[-3:] == ["diagnoser", "concept", "coach_rung"] and engine.state.plan is None
        assert "solver" not in roles(provider)
        walked.update(zip(engine.guided.path, engine.guided.path[1:], strict=False))
        run(engine.student_turn("v is the speed and m is the mass."))
        assert "solver" not in roles(provider)
    finally:
        run(close(engine))

    # The plan fails its check twice: the honest blocker.
    blocked = {"input_guard": [guard()], "diagnoser": [diagnosis()],
               "solver": [unverified_plan(), unverified_plan(), unverified_plan(), unverified_plan()]}  # fmt: skip
    engine, _ = run(make_engine(tmp_path / "blocked", blocked, worker=False))
    try:
        result = run(engine.start_problem(STATEMENT))
        assert result.degraded_reason == "plan_unverified"
        assert engine.guided.path[-3:] == ["solver", "checker_plan", "honest_blocker"]
        walked.update(zip(engine.guided.path, engine.guided.path[1:], strict=False))
    finally:
        run(close(engine))
    assert walked >= set(GUIDED_EDGES) - {("checker_plan", "solver")} - {("checker_diagnoser", "raise_rung_or_target")}


def test_d122_a_definition_with_given_quantities_still_plans(tmp_path: Path) -> None:
    """Only a definition or explanation with no quantity to work from skips the Solver (D122)."""
    known = {"symbol": "m", "value": "2", "unit": "kg", "quote": "2 kg"}
    script = {"input_guard": [guard()], "diagnoser": [diagnosis(question_kind="explanation", knowns=[known])],
              "solver": solver_steps(), "coach": [tutor(SAFE)]}  # fmt: skip
    engine, provider = run(make_engine(tmp_path, script))
    try:
        run(engine.start_problem("Explain the kinetic energy of a 2 kg ball moving at 3 m/s."))
        assert "concept" not in engine.guided.path and "solver" in roles(provider)
    finally:
        run(close(engine))


def test_blank_unknowns_never_reach_the_solver(tmp_path: Path) -> None:
    """A small model's blank unknown ([""]) is dropped from the Solver's brief, as it is from the board."""
    known = {"symbol": "m", "value": "2", "unit": "kg", "quote": "2 kg"}
    script = {"input_guard": [guard()], "diagnoser": [diagnosis(knowns=[known], unknowns=["", "  ", "E_k"])],
              "solver": solver_steps(), "coach": [tutor(SAFE)]}  # fmt: skip
    engine, provider = run(make_engine(tmp_path, script))
    try:
        run(engine.start_problem("Find the kinetic energy of a 2 kg ball moving at 3 m/s."))
        brief = next(r for r in provider.requests if r.get("_role") == "solver")
        text = json.dumps(brief)
        assert '\\"unknowns\\": [\\"E_k\\"]' in text, text[-2000:]
    finally:
        run(close(engine))


def test_d131_small_talk_is_answered_warmly_and_opens_no_problem(tmp_path: Path) -> None:
    """ "hello" gets a greeting and opens no problem, so the next message is the problem; "thanks" mid-problem gets a
    thank-you, never a board line (D131)."""
    from agent_core.engine.titles import chat_title

    script = {"input_guard": [guard()] * 4, "diagnoser": [diagnosis()], "solver": solver_steps(),
              "coach": [tutor(SAFE)] * 2}  # fmt: skip
    engine, _provider = run(make_engine(tmp_path, script))
    try:
        hello = run(engine.start_problem("hello"))
        assert hello.status == "complete" and engine.state.problem is None
        assert "What are you working on today?" in engine.state.transcript[-1]["content"]
        assert engine.state.problem is None  # the next message opens the new problem
        run(engine.start_problem(STATEMENT))
        assert engine.state.problem is not None
        run(engine.student_turn("thanks!"))
        assert "You're welcome" in engine.state.transcript[-1]["content"] and engine.state.problem is not None
        run(engine.student_turn("hi"))
        assert "Hi again" in engine.state.transcript[-1]["content"]
        run(engine.start_problem("hello"))  # "New question", then a greeting: greeted afresh, not "carry on"
        assert "What are you working on today?" in engine.state.transcript[-1]["content"]
        assert engine.state.problem is None  # the next message opens the new problem
    finally:
        run(close(engine))
    assert (
        chat_title("hello") == "" and chat_title("Hi Jana!") == "" and chat_title("Find the speed") == "Find the speed"
    )


def test_d131_the_coach_reads_from_the_current_problem(tmp_path: Path) -> None:
    """A second problem's Coach call carries none of the first problem's conversation (D131)."""
    second = "A box of mass 4 kg is lifted 3 m. Find the work done against gravity."
    script = {"input_guard": [guard()] * 4, "diagnoser": [diagnosis(), diagnosis()],
              "solver": solver_steps() + solver_steps(), "coach": [tutor(SAFE)] * 4}  # fmt: skip
    engine, provider = run(make_engine(tmp_path, script))
    try:
        run(engine.start_problem(STATEMENT))
        run(engine.start_problem(second))
        coach = [r for r in provider.requests if r.get("_role") == "coach"][-1]
        sent = json.dumps(coach.get("messages", coach))
        assert second.split(".")[0] in sent and STATEMENT.split(".")[0] not in sent
    finally:
        run(close(engine))


# --- AGT-02, PRV-18: the input guard role on every message ----------------------------------------------------------


def test_agt02_input_guard_role_runs_before_any_model(tmp_path: Path) -> None:
    """The input-guard role classifies the message before any other call; its class routes a template with no other
    model call, and its failure falls back to the patterns and the local classifier (AGT-02, PRV-18)."""
    engine, provider = run(make_engine(tmp_path / "a", {"input_guard": [guard("medical_legal_advice")]}, worker=False))
    try:
        result = run(engine.start_problem("What should I take for this headache before my exam?"))
    finally:
        run(close(engine))
    assert result.status == "complete" and result.stop_reason == "safety"
    assert roles(provider) == ["input_guard"], "the template answered with no other model call"
    assert {"role": "input_guard", "outcome": "completed"}.items() <= result.trace["delegations"][0].items()

    # The role fails (a provider error): the patterns and the local classifier decide and the turn goes on.
    failing = {"input_guard": [{"error": {"status": 500}}] * 3, "diagnoser": [diagnosis()], "solver": solver_steps(),
               "coach": [tutor(SAFE)]}  # fmt: skip
    engine, provider = run(make_engine(tmp_path / "b", failing))
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    assert result.status == "complete" and engine.state.plan is not None
    aux = [d for d in result.trace["delegations"] if d["role"] == "input_guard"]
    assert aux and aux[0]["outcome"] == "error"
    assert roles(provider).index("input_guard") < roles(provider).index("diagnoser")

    # Distress is decided by the patterns alone: the role is never asked.
    engine, provider = run(make_engine(tmp_path / "c", {"input_guard": [guard()]}, worker=False))
    try:
        result = run(engine.start_problem("I want to hurt myself"))
    finally:
        run(close(engine))
    assert result.stop_reason == "safety" and "input_guard" not in roles(provider)


# --- PED-15: the rule matcher role --------------------------------------------------------------------------------


def _judge_example(body: dict[str, Any]) -> dict[str, Any]:
    """The rule matcher keeps the rule about making up an example, by its number in the task."""
    task = next(m["content"] for m in body["messages"] if m["role"] == "user")
    found = re.search(r"(?m)^(\d+)\. Is the tutor about to make up a new example", task)
    applies = [{"rule_ref": int(found.group(1)), "reason": "a new example is coming"}] if found else []
    return structured({"applies": applies})


def test_ped15_rule_matcher_role_judges_each_coach_turn(tmp_path: Path) -> None:
    """From S2 the rule matcher role judges the candidate rules in one call per Coach turn; a failed call falls back
    to the keywords and the turn completes (PED-15, AGT-02)."""
    script = {"input_guard": [guard()] * 2, "diagnoser": [diagnosis(), diagnosis()], "solver": solver_steps(),
              "rule_matcher": [_judge_example, {"error": {"status": 500}}], "coach": [tutor(SAFE)] * 2,
              "checker": [cannot_verify()]}  # fmt: skip
    engine, provider = run(make_engine(tmp_path, script))
    try:
        first = run(engine.start_problem(STATEMENT))
        assert roles(provider).count("rule_matcher") == 1, "one judged call for the Coach turn"
        second = run(engine.student_turn("v^2 = u^2 + 2as"))
    finally:
        run(close(engine))
    assert first.status == second.status == "complete"
    judged, fallen = engine.rule_log[0], engine.rule_log[-1]
    assert judged["calls"] == 1 and judged["fallback"] is None
    assert "local_context_examples" in judged["rules"]
    assert fallen["calls"] == 0 and fallen["fallback"] == "error"
    assert roles(provider).count("rule_matcher") > 1  # the failed call (the router retries it, then falls back)
    traced = [d for d in first.trace["delegations"] if d["role"] == "rule_matcher"]
    assert traced and traced[0]["outcome"] == "completed"


# --- PED-22, PED-24: the misconception flow and the saved-question triggers ---------------------------------------


def test_ped22_live_misconception_flow(tmp_path: Path) -> None:
    """A wrong option whose misconception the marker matches runs PED-22 on the live loop: the first match asks a
    probe, the second names it with the fix and a discriminating question; each match is a learner-model evidence
    event; a right answer to the check moves it to resolving."""
    script = {"input_guard": [guard()] * 4, "diagnoser": [diagnosis()], "coach": [tutor(SAFE)] * 4}
    engine, _ = run(make_engine(tmp_path, script, worker=False))
    engine.bind_knowledge(knowledge())
    learned: list[Any] = []
    engine.learning = learned.extend
    # The learner model folds each event as it is recorded, so the marker's event for a match is already counted.
    engine.misconception_evidence = lambda mc_id: sum(
        e.type == "misconception_evidence" and e.payload["misconception_id"] == mc_id for e in learned
    )
    notes: list[str] = []
    real = engine._coach_turn

    async def noted(turn: Any, intent_note: str, **options: Any) -> Any:
        notes.append(intent_note)
        return await real(turn, intent_note=intent_note, **options)

    engine._coach_turn = noted
    try:
        run(engine.start_practice(item(MISCONCEPTION_ITEM)))
        run(engine.student_turn("B"))
        flow = engine.misconception_flows[MISCONCEPTION]
        assert flow.node == "probe" and "probing question" in notes[-1]
        run(engine.student_turn("B"))
        assert flow.node == "discriminating_check" and flow.status == "active" and "Name it gently" in notes[-1]
        run(engine.student_turn("A"))
        assert flow.node == "resolving" and flow.status == "resolving"
    finally:
        run(close(engine))
    evidence = [e for e in learned if e.type == "misconception_evidence"]
    # One event per match: the marker's (ASM-13, linked to the attempt); the flow does not record the match again.
    assert len(evidence) == 2 and all(e.payload["misconception_id"] == MISCONCEPTION for e in evidence)
    assert all(e.payload.get("attempt_id") for e in evidence)
    assert all(contract_errors("learning/learning-event#/$defs/payload_misconception_evidence", e.payload) == []
               for e in evidence)  # fmt: skip


def test_ped24_live_triggers(tmp_path: Path) -> None:
    """The saved-question triggers the engine's signals reach on the live loop: the stuck cap on a wrong answer
    (LRN-26), a question the installed packs do not cover, and a misconception that survives its fixes (PED-24)."""
    saved: list[str] = []
    script = {"input_guard": [guard()] * 3, "diagnoser": [diagnosis(), diagnosis(in_scope=False)],
              "coach": [tutor(SAFE)] * 3, "solver": solver_steps()}  # fmt: skip
    engine, _ = run(make_engine(tmp_path, script))
    engine.bind_knowledge(knowledge())
    engine.save_question = lambda state, reason: saved.append(reason)
    engine.stuck_cap = lambda kc_ids: bool(kc_ids)
    try:
        run(engine.start_practice(item(MISCONCEPTION_ITEM)))
        run(engine.student_turn("C"))
        assert saved == ["stuck"] and engine.rule_log[-1]["rules"] is not None
        assert engine.flow_signals.get("engine.stuck_cap_reached") is True
        run(engine.start_problem(STATEMENT))  # the Diagnoser finds it outside the syllabus
        assert saved[-1] == "outside_content" and engine.flow_signals.get("content.out_of_pack") is True
    finally:
        run(close(engine))

    # A misconception that survives the configured fixes saves the question once.
    kept: list[str] = []
    fake = SimpleNamespace(misconception_flows={}, misconception_seen={}, misconception_evidence=None, knowledge=None,
                           deps=SimpleNamespace(settings=Settings()), _learn=lambda turn, events: None,
                           _saved=kept.append)  # fmt: skip
    for _ in range(12):
        live_flows.misconception_step(fake, None, "incorrect", MISCONCEPTION)
    flow = fake.misconception_flows[MISCONCEPTION]
    assert flow.fixes >= Settings().misconception_fixes_before_save and kept and set(kept) == {"repeated_error"}


# --- PRV-13: the nearest topic at the level -----------------------------------------------------------------------


def test_prv13_beyond_level_names_the_nearest_topic(tmp_path: Path) -> None:
    """A question beyond the level gets its template with the nearest topic at the student's level from the
    installed packs, not the generic phrase (TABLE PRV-13a)."""
    engine, _ = run(make_engine(tmp_path, {}, worker=False))
    engine.bind_knowledge(knowledge())
    try:
        result = run(engine.start_problem("How does the Schrodinger equation describe the energy of an atom?"))
    finally:
        run(close(engine))
    text = str(engine.events.student_text(result.turn_id))
    assert engine.turn_log[-1]["template"] == "tpl.beyond_level", engine.turn_log[-1]
    assert "closest topic in your course" not in text
    titles = {n.title for n in engine.knowledge.index.nodes.values() if n.id.startswith("cur.phy.o.")}
    assert any(title in text for title in titles), text
    notices = [
        f["event"]
        for f in engine.events.frames
        if f["event"]["type"] == "notice" and f["event"]["code"] == "beyond_level"
    ]
    assert len(notices) == 1
    assert notices[0]["action"]["label_key"] == "notice.open_topic"
    topic_id = notices[0]["action"]["command"].removeprefix("open_topic:")
    assert engine.knowledge.index.nodes[topic_id].title == notices[0]["params"]["title"]


# --- PRM-26: the spoken-form overlay ------------------------------------------------------------------------------


def test_prm26_spoken_form_overlay(tmp_path: Path) -> None:
    """The overlay joins the Coach's prompt on a voice turn only, with its limits from configuration; a voice turn's
    `say_spoken` keeps its sentence and character caps and no LaTeX or markdown, and outside voice mode it is null."""
    engine, _ = run(make_engine(tmp_path / "p", {}, worker=False))
    try:
        assets, cfg = engine.deps.assets, engine.deps.settings
        for hardware in ("low", "mid", "high"):
            base = PromptSession(hardware_class=hardware)
            spoken = build_prompt("coach", "qwen3", PromptSession(hardware_class=hardware, voice=True), [], set(),
                                  set(), assets, cfg)  # fmt: skip
            plain = build_prompt("coach", "qwen3", base, [], set(), set(), assets, cfg)
            guidance = next(t.text for t in spoken.tiers if t.name == "guidance")
            assert f"{cfg.spoken_max_chars} characters" in guidance, hardware
            assert "say_spoken" not in next(t.text for t in plain.tiers if t.name == "guidance")
            assert {"tier": "3", "item": "guidance:spoken-form", "reason": "not a voice turn"} in plain.dropped
        never = build_prompt("diagnoser", "qwen3", PromptSession(voice=True), [], set(), set(), assets, cfg)
        assert "say_spoken" not in never.messages[0].content
    finally:
        run(close(engine))
    assert fit_spoken("We take up as positive. So u is fourteen. What is v at the top? Then solve.", 600, 3) == (
        "We take up as positive. So u is fourteen. What is v at the top?"
    )
    assert fit_spoken("Use $v^2 = u^2 + 2as$ now.", 600, 3) is None
    assert fit_spoken("**Good.** Next step.", 600, 3) is None
    assert fit_spoken('Look at <point at="stp_01"/> this line.', 600, 3) is not None
    assert fit_spoken("A" * 700 + ".", 600, 3) is None

    def voice_turn(say_spoken: str) -> dict[str, Any]:
        return tutor("Which equation links u, v, a and s?", say_spoken=say_spoken)

    script = {"input_guard": [guard()] * 2, "diagnoser": [diagnosis()], "solver": solver_steps(),
              "coach": [voice_turn("Think about it. Which equation links them?"),
                        voice_turn("Say it in words. Then we go on. And one more. Which one links them?")]}  # fmt: skip
    engine, _ = run(make_engine(tmp_path / "v", script))
    try:
        quiet = run(engine.start_problem(STATEMENT))
        engine.voice_mode = True
        spoken = run(engine.student_turn("I think v squared equals u squared plus two a s"))
    finally:
        run(close(engine))
    assert quiet.tutor_turn is not None and quiet.tutor_turn["say_spoken"] is None
    assert spoken.tutor_turn is not None
    said = spoken.tutor_turn["say_spoken"]
    assert said is not None and len(re.findall(r"[.?!]", said)) <= Settings().spoken_max_sentences


# --- AGT-22, TOL-22: the lesson flow over the API -----------------------------------------------------------------


@pytest.mark.parametrize("restart", [False, True])
def test_agt22_lesson_session_plays_blocks_in_order(tmp_path: Path, restart: bool) -> None:
    """A session opened on a lesson plays its blocks in pack order through "Next", each move rewriting the session
    plan (`lesson_plan_write`) shown as the plan card; a check block opens its item; a new problem asked mid-lesson is
    kept for after it; the lesson resumes at its block after a restart (AGT-22, TOL-22, MEM-02)."""
    from api_harness import cli, start_core, stop_core
    from test_m13g_learn import LESSON, SETTINGS, Client, install

    script = {"coach": [tutor(SAFE)] * 8, "input_guard": [guard()] * 8, "rule_matcher": []}

    async def scenario() -> None:
        install(tmp_path, "phy")
        r = await start_core(tmp_path, provider=ScriptedProvider(script, kind="local",
                                                                  installed_models=["qwen3-vl-8b", "gemma-4-12b"]),
                             settings=SETTINGS, stage="S2")  # fmt: skip
        try:
            c = Client(r)
            body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                    "origin": {"kind": "lesson", "ref": LESSON}}  # fmt: skip
            session_id = (await c.ok("POST", "/v1/sessions", body))["session_id"]
            missing = {**body, "client_session_id": cli(), "origin": {"kind": "lesson", "ref": "les.phy.o.x.none"}}
            assert (await c.send("POST", "/v1/sessions", missing)).status_code == 422

            async def turn(intent: str, text: str = "next") -> Any:
                sent = {"client_message_id": cli(), "intent": intent, "content": [{"type": "text", "text": text}]}
                accepted = await c.send("POST", f"/v1/sessions/{session_id}/turns", sent)
                assert accepted.status_code == 202, accepted.text
                await r.wait_idle(session_id)
                return r.core.sessions[session_id].engine

            engine = await turn("next_step")  # block 0: the prior-knowledge check opens its item
            assert engine.lesson.index == 0 and engine.state.practice is not None
            engine = await turn("next_step")  # block 1: the idea, phrased by the Coach
            assert engine.lesson.index == 1 and engine.state.practice is None
            plans = [p["content"] for p in engine.persisted.values() if p["kind"] == "card"
                     and p["content"].get("card_type") == "plan"]  # fmt: skip
            assert [i["status"] for i in plans[-1]["items"]][:3] == ["done", "in_progress", "pending"]
            assert all(contract_errors("api/events#/$defs/card_plan", p) == [] for p in plans)
            engine = await turn("ask", "A car goes 100 m in 20 s. What is its speed?")
            assert engine.state.after_lesson and engine.lesson.index == 1
            if restart:
                engine.lesson = None  # a restarted core: the engine opens the lesson again at its saved block
            engine = await turn("next_step")
            assert engine.lesson.index == (1 if restart else 2)
        finally:
            await stop_core(r)

    run(scenario())


def test_d131_a_bare_expression_reads_as_its_task() -> None:
    """ "1+1" typed as a question is "Work out 1+1" to the team, an equation is "Solve ..."; words, a lone number or a
    value with a unit stay as written (D131)."""
    from agent_core.engine.pedagogy import as_task

    assert [as_task(t) for t in ("1+1", "2x+3=7", "(2+3)^2")] == ["Work out 1+1", "Solve 2x+3=7", "Work out (2+3)^2"]
    assert [as_task(t) for t in ("12", "-5", "12 m/s", "find 1+1", "What is 2+2?")] == [
        "12",
        "-5",
        "12 m/s",
        "find 1+1",
        "What is 2+2?",
    ]
