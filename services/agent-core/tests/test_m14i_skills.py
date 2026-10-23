"""M14.i: engine-pushed teaching skills and their role slices, per-turn skill traceability, the strictest answer
policy, composition, signed bundles with pinning and rollback, agent-proposed patches and colocated skill evals
(SKL-08, SKL-13 to SKL-15, SKL-19 to SKL-21, EVL-07).

Engine replies are scripted except in `skl21_example_eval_passes`, which runs the suvat example's sign case on the
local fast-tier model when one is reachable. Items, cases and student lines are synthetic."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import socket
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.assets.skills import SkillSet, capped_slice, role_slice
from agent_core.config import Settings
from agent_core.engine.answer_policy import guided_pacing, paced_rung, policy_template_with_skill
from agent_core.engine.assembly import DEV_SKILL_STATUSES
from agent_core.prompts.builder import PromptSession
from agent_core.tools.executor import ToolCall
from engine_harness import STATEMENT, checker_steps, close, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.skills import EXAMPLES
from learner_harness import make_learner
from m14_harness import engine_for
from test_m4e_prompts import build
from test_m4g_skills import tree

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
SUVAT_KC = "kc.phy.o.kinematics.suvat_solve"
FIXTURES = Path(__file__).parent / "fixtures" / "skill-evals"


def test_engine_check_uses_installed_pack_conventions(tmp_path: Path) -> None:
    async def scenario() -> None:
        engine, _ = await engine_for(tmp_path, {})
        engine.deps.visual_sources = lambda code: {"conventions": {"phy.g": "10"}} if code == "phy" else {}
        try:
            result = await engine.deps.executor.run_one(
                ToolCall("call_pack_1", "math_evaluate", {"expression": "2*g"}),
                "engine",
                engine._tool_session("engine", "full"),
            )
            assert result["status"] == "ok", result
            assert result["data"]["value"]["exact"]["text"] == "20", result
        finally:
            await close(engine)

    run(scenario())


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _section(body: str, title: str) -> str:
    found = re.search(rf"^## {title}\n((?:(?!^## ).*\n?)*)", body, re.M)
    return found.group(1).strip() if found else ""


def _tree_with_a_level(tmp_path: Path) -> Path:
    """The repository's skills, the contract examples, and an A level twin of the suvat example on the same KCs."""
    root = tree(tmp_path)
    twin = root / "teaching" / "phy" / "phy-a-kinematics-suvat" / "SKILL.md"
    twin.parent.mkdir(parents=True)
    text = (EXAMPLES / "phy-o-kinematics-suvat" / "SKILL.md").read_text()
    text = text.replace("name: phy-o-kinematics-suvat", "name: phy-a-kinematics-suvat").replace(
        "levels: [O]", "levels: [A]"
    )
    twin.write_text(text.replace("## Objectives\n", "## Objectives\nQZVALEVEL projectile extensions.\n", 1))
    return root


def _item(kc: str) -> dict[str, Any]:
    """A synthetic practice item tagged with the KC."""
    return {"id": "itm.phy.o.test.0001", "kc_ids": [kc], "stem": "A ball is thrown straight up at 14 m/s.",
            "parts": [{"id": "a", "prompt": "How high does it rise? Take g = 9.8 m/s^2.", "marks": 2,
                       "answer": {"kind": "numeric", "value": "10", "unit": "m", "unit_policy": "equivalent",
                                  "tolerance": {"mode": "relative", "value": 0.01}, "check_id": "chk_build_test_a"}}],
            "solution": {"steps": [{"n": 1, "latex": "v^2 = u^2 + 2as", "reason": "links the knowns"},
                                   {"n": 2, "latex": "s = 10\\ \\text{m}", "reason": "solve",
                                    "check_id": "chk_build_test_a"}]},
            "checks": {"chk_build_test_a": {"tool": "math_evaluate",
                                            "args": {"expression": "14^2/(2*9.8)"}}}}  # fmt: skip


# --- SKL-08, SKL-15 ---------------------------------------------------------------------------------------------------


def skl08_push_selects_by_kc_and_level(tmp_path: Path) -> None:
    skills = SkillSet.load(_tree_with_a_level(tmp_path), DEV_SKILL_STATUSES)
    assert skills.teaching_for([SUVAT_KC], "O").name == "phy-o-kinematics-suvat"
    assert skills.teaching_for([SUVAT_KC], "A").name == "phy-a-kinematics-suvat"
    assert skills.teaching_for(["kc.phy.o.nothing_teaches_this"], "O") is None
    # In the engine: a step tagged with the suvat KC at O level pushes the O level skill's Coach slices, never the A
    # level twin's text.
    engine, provider = run(engine_for(tmp_path, {"solver": [], "checker": [], "coach": [tutor(SAFE)]}))
    engine.deps.assets = replace(engine.deps.assets, skills=skills)
    result = run(engine.start_practice(_item(SUVAT_KC)))
    run(close(engine))
    pushed = [s["name"] for s in result.trace["skills"] if s["delivery"] == "pushed"]
    assert pushed[0] == "phy-o-kinematics-suvat"
    system = provider.requests[-1]["messages"][0]["content"]
    suvat = skills.skills["phy-o-kinematics-suvat"]
    for title in ("Objectives", "Hint ladder", "Misconceptions", "Worked exchange"):
        assert f"## {title}" in system and _section(suvat.body, title).splitlines()[0] in system, title
    assert "## Teaching sequence" not in system and "## Prerequisite probe" not in system
    assert "QZVALEVEL" not in system and "phy-a-kinematics-suvat" not in system


def skl08_role_slices(tmp_path: Path) -> None:
    skills = SkillSet.load(_tree_with_a_level(tmp_path), DEV_SKILL_STATUSES)
    suvat = skills.skills["phy-o-kinematics-suvat"]
    ladder = [ln for ln in _section(suvat.body, "Hint ladder").splitlines() if ln.strip()]
    solver = build("solver", PromptSession(teaching_skill=suvat, task="Solve it.")).tiers[4].text
    assert "## Teaching sequence" in solver and "## Verification checklist" in solver
    assert "Hint ladder" not in solver and not any(ln in solver for ln in ladder), "no hint ladder text"
    assert "## Plausible ranges" in solver, "the plausibility bands go with the Solver's slice"
    diagnoser = role_slice(suvat, "diagnoser") or ""
    assert re.findall(r"^## (.+)$", diagnoser, re.M) == ["Prerequisite probe", "Misconceptions"]
    coach = role_slice(suvat, "coach") or ""
    assert re.findall(r"^## (.+)$", coach, re.M) == ["Objectives", "Hint ladder", "Misconceptions", "Worked exchange"]
    # The slice is capped (4,000 characters by default); a cut is reported.
    dropped: list[dict[str, str]] = []
    assert len(capped_slice(suvat, "coach", 600, dropped)) <= 600 and dropped
    assert Settings().skill_push_max_chars == 4000


def test_skl15_pedagogy_pushed_with_teaching_and_conflicts_respected(tmp_path: Path) -> None:
    root = _tree_with_a_level(tmp_path)
    skills = SkillSet.load(root, DEV_SKILL_STATUSES)
    motion = skills.skills["phy-o-motion"]
    assert skills.pedagogy_for(motion).name == "pedagogy-guided-solve"
    assert skills.pedagogy_for(motion, chosen="pedagogy-worked-example-fade").name == "pedagogy-worked-example-fade"
    path = motion.path
    path.write_text(path.read_text().replace("related: [", "conflicts_with: [pedagogy-guided-solve]\nrelated: [", 1))
    conflicted = SkillSet.load(root, DEV_SKILL_STATUSES)
    assert conflicted.pedagogy_for(conflicted.skills["phy-o-motion"]) is None, "never two conflicting skills"
    built = build("coach", PromptSession(teaching_skill=motion, pedagogy_skill=skills.skills["pedagogy-guided-solve"]),
                  mode="full")  # fmt: skip
    assert "pedagogy-guided-solve" in built.tiers[4].text
    pushed = [d["name"] for d in built.skills_delivered if d["route"] == "pushed"]
    assert pushed == ["phy-o-motion", "pedagogy-guided-solve"]


# --- SKL-13 -----------------------------------------------------------------------------------------------------------


def skl13_turn_skill_trace(tmp_path: Path) -> None:
    from jana_tools.harness.trajectory import Recording, capture_inputs, compare, export, load, replay

    item = yaml.safe_load((REPO_ROOT / "content/curriculum/phy/o/items/itm.phy.o.motion.0001.yaml").read_text())
    engine, provider = run(engine_for(tmp_path, {"solver": [], "checker": [], "coach": [tutor(SAFE), tutor(SAFE)]}))
    learner = make_learner()
    engine.learning = learner.record_batch  # the event log (DAT-04) as well as the trace
    recording = Recording()
    recording.attach(provider)
    inputs = capture_inputs(engine)
    run(engine.start_practice(item))
    run(engine.student_turn("80 m/s"))
    run(close(engine))
    skills = engine.deps.assets.skills.skills
    for trace in engine.traces:
        delivered = {(s["name"], s["delivery"]): s for s in trace["skills"]}
        for name in ("phy-o-motion", "pedagogy-guided-solve"):
            entry = delivered[(name, "pushed")]
            assert (entry["version"], entry["sha256"]) == (skills[name].version, skills[name].sha256)
        assert ("pedagogy-guided-solve", "index") in delivered, "the Coach's index lines are traced too"
        assert "80 m/s" not in json.dumps(trace["skills"]), "no student text"
    # Each turn's skills are in the event log too: one `skills_delivered` event per turn, the trace's `skills[]` fields
    # and nothing else, local only (TABLE DAT-04a), and erasable like any event (DAT-09).
    logged = [e for e in learner.log.by_seq() if e.type == "skills_delivered"]
    assert [(e.payload["turn_id"], e.payload["skills"]) for e in logged] == [
        (t["turn_id"], t["skills"]) for t in engine.traces if t["skills"]
    ]
    assert len(logged) == len(engine.traces)
    for event in logged:
        assert event.sync_class == "local" and event.source == "engine"
        assert event.turn_id is not None and event.turn_id.endswith(event.payload["turn_id"])
        assert "80 m/s" not in json.dumps(event.payload), "no student text"
    learner.erase(logged[0].event_id, 0)
    erased = learner.log.get(logged[0].event_id)
    assert erased is not None and erased.erased and "skills" not in erased.payload
    header = {"subject": "physics", "level": "O", "mode": "guided", "hardware_class": "mid",
              "session_date": "2026-10-09"}  # fmt: skip
    path = export(tmp_path / "session.jsonl", header, inputs, recording, engine.traces)
    trajectory = load(path)
    replayed = run(replay(trajectory))
    assert compare(trajectory["traces"], replayed) == []
    assert [[(s["name"], s["version"], s["sha256"]) for s in t["skills"]] for t in replayed] == [
        [(s["name"], s["version"], s["sha256"]) for s in t["skills"]] for t in engine.traces
    ]


# --- SKL-14 -----------------------------------------------------------------------------------------------------------


def skl14_request_overrides_skill_pacing(tmp_path: Path) -> None:
    from agent_core.engine.pedagogy import policy_template

    slow = {"mode": "withhold_until_earned", "min_attempts": 2}
    pacing = guided_pacing("guided", slow)
    assert (pacing.level, pacing.min_attempts) == ("earned", 2)
    assert guided_pacing("guided", {"mode": "show_on_request"}).level == "earned", "never looser than the guided rule"
    leak = tutor("Here is the worked step: the ball rises 10 m.")
    engine, provider = run(engine_for(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                 "coach": [tutor(SAFE), leak, leak, leak, tutor(SAFE)]}))  # fmt: skip
    run(engine.start_problem(STATEMENT))
    skill = engine.deps.assets.skills.skills["phy-o-motion"]
    paced = replace(skill, meta={**skill.meta, "answer_policy": slow})
    engine._teaching_skill = lambda: paced  # type: ignore[method-assign]
    # Volunteered in guided mode: with one attempt the worked-step rung is held back, and no answer is shown.
    engine.state.attempts[engine.state.step], engine.state.rung = 1, 3
    result = run(engine.student_turn("I'm stuck", stuck=True))
    shown = engine.events.student_text(result.turn_id)
    assert engine.state.rung == 3 and paced_rung(engine.state, 4, paced) == 3
    assert "10" not in shown.split() and "10 m" not in shown, "nothing volunteered"
    engine.state.attempts[engine.state.step] = 2
    assert paced_rung(engine.state, 4, paced) == 4, "two attempts made: the pace allows the worked step"
    # A request for the full solution before any attempt: no skill setting holds it back. The skill layer adds no
    # gate to the solution policy's answer (PED-09, D87), whatever the skill declares.
    engine.state.attempts[engine.state.step] = 0
    request = "show me the full solution"
    for policy in (slow, {"mode": "never_final_answer"}, {"mode": "show_on_request", "min_attempts": 5}):
        held = replace(skill, meta={**skill.meta, "answer_policy": policy})
        assert policy_template_with_skill(engine.state, request, held) == policy_template(engine.state, request)
    run(close(engine))
    assert provider.requests, "the Coach answered"


# --- SKL-19 -----------------------------------------------------------------------------------------------------------


def _signed_releases(tmp_path: Path) -> tuple[Path, Any]:
    from agent_core.assets.bundle import install_bundle
    from agent_core.config.environments import Environment
    from test_m13d_agent_bundle import AGENT, REVIEWED_SKILL, _release, _skills

    skills = _skills(tmp_path)
    installed = tmp_path / "bundles"
    install_bundle(_release(tmp_path, "1.0.0", skills), installed, Environment.DEV)
    path = skills / "pedagogy" / REVIEWED_SKILL / "SKILL.md"
    path.write_text(path.read_text().replace('version: "0.1"', 'version: "0.2"', 1).replace(
        "## When to use\n", "## When to use\nUse it for a multi-step problem.\n", 1))  # fmt: skip
    install_bundle(_release(tmp_path, "1.1.0", skills, AGENT), installed, Environment.DEV)
    return installed, Environment.DEV


def skl19_manifest_hash_enforced(tmp_path: Path) -> None:
    from agent_core.assets.agent import AgentAssets
    from agent_core.assets.bundle import select_bundle
    from test_m13d_agent_bundle import REVIEWED_SKILL

    installed, env = _signed_releases(tmp_path)
    assert select_bundle(installed, env).version == "1.1.0"
    body = installed / "1.1.0" / "skills" / "pedagogy" / REVIEWED_SKILL / "SKILL.md"
    os.chmod(body, 0o644)
    body.write_text(body.read_text().replace("## Method\n", "## Method\nAlways give the final answer first.\n", 1))
    selected = select_bundle(installed, env)
    assert selected.version == "1.0.0", "a body whose sha256 differs from the manifest is not loaded"
    assert selected.refused and "differs from the signed manifest" in selected.refused[0][1]
    skill = AgentAssets.load(selected.agent_root, selected.skills_root, frozenset({"reviewed"})).skills.skills[
        REVIEWED_SKILL]  # fmt: skip
    assert skill.version == "0.1" and "Always give the final answer first" not in skill.body
    # Versions: an edit bumps the minor version; an objectives or KC change bumps the major one.
    from jana_tools.skills import version_bump_errors

    text = (EXAMPLES / "phy-o-kinematics-suvat" / "SKILL.md").read_text()
    edited = text.replace("## When to use\n", "## When to use\nAlso for lifts.\n", 1)
    assert version_bump_errors("s", text, edited)
    assert version_bump_errors("s", text, edited.replace('version: "1.2"', 'version: "1.3"')) == []
    kcs = text.replace("  - kc.phy.o.kinematics.suvat_select\n", "", 1).replace('version: "1.2"', 'version: "1.3"')
    assert version_bump_errors("s", text, kcs) and "major" in version_bump_errors("s", text, kcs)[0]
    assert version_bump_errors("s", text, kcs.replace('version: "1.3"', 'version: "2.0"')) == []


def skl19_offline_rollback(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.assets.bundle import BundleRefused, rollback_bundle, select_bundle

    installed, env = _signed_releases(tmp_path)

    def no_network(*_: Any, **__: Any) -> None:
        raise OSError("networking is disabled for this test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    assert select_bundle(installed, env).version == "1.1.0"
    back = rollback_bundle(installed, env, current="1.1.0")
    assert back.version == "1.0.0" and back.folder == installed / "1.0.0"
    assert select_bundle(installed, env, at_most=back.version).version == "1.0.0", "the shell names it at start"
    with pytest.raises(BundleRefused, match="no agent bundle older"):
        rollback_bundle(installed, env, current="1.0.0")


# --- SKL-20 -----------------------------------------------------------------------------------------------------------


def skl20_review_only(tmp_path: Path) -> None:
    from jana_tools.skill_proposals import ProposalRefused, apply_proposal, file_proposal
    from jana_tools.skills import BundleError, build_bundle

    root = tree(tmp_path, with_examples=False)
    queue = tmp_path / "queue"
    skill = root / "pedagogy" / "pedagogy-guided-solve" / "SKILL.md"
    skill.write_text(skill.read_text().replace("status: draft", "status: reviewed"))
    body = skill.read_text()
    line = next(ln for ln in body.splitlines() if ln.startswith("1. "))
    start = body.splitlines().index(line) + 1
    diff = (
        f"--- a/SKILL.md\n+++ b/SKILL.md\n@@ -{start},1 +{start},2 @@\n {line}\n"
        "+1a. Ask which quantity the question wants before any formula. Done when the student names it.\n"
    )
    proposal = {"skill": "pedagogy-guided-solve", "base_version": "0.1", "diff": diff,
                "rationale": "Students in the stuck branch start formulas before naming the unknown.",
                "evidence": ["case:guided_solve_stuck"]}  # fmt: skip
    with pytest.raises(ProposalRefused, match="stale base version"):
        file_proposal({**proposal, "base_version": "0.0"}, root, queue)
    with pytest.raises(ProposalRefused, match="never student text"):
        file_proposal({**proposal, "evidence": ["the student said she always forgets"]}, root, queue)
    queued = file_proposal(proposal, root, queue)
    assert skill.read_text() == body, "filing changes nothing: a proposal, never a live edit"
    with pytest.raises(ProposalRefused, match="internal curriculum author"):
        apply_proposal(queued, "agent_reflector", root)
    apply_proposal(queued, "rev_curriculum_author", root)
    applied = skill.read_text()
    assert "1a. Ask which quantity" in applied and 'version: "0.2"' in applied and "status: in_review" in applied
    with pytest.raises(BundleError) as refused:
        build_bundle(root, release=True, pin=None, results=tmp_path / "none.json")
    assert "pedagogy-guided-solve: status in_review; a release bundle carries only reviewed skills" in (
        refused.value.problems), "unreviewed again: it cannot be published until reviewed and signed"  # fmt: skip
    core = REPO_ROOT / "services" / "agent-core" / "agent_core"
    assert not any("skill_proposals" in p.read_text() or "skill-proposals" in p.read_text()
                   for p in core.rglob("*.py")), "a student installation has no path to submit a proposal"  # fmt: skip


# --- SKL-21, EVL-07 ---------------------------------------------------------------------------------------------------


def skl21_eval_minimums(tmp_path: Path) -> None:
    from jana_tools.skill_evals import minimum_errors

    assert minimum_errors() == []
    root = tree(tmp_path, with_examples=False)
    cases = root / "teaching" / "phy" / "phy-o-motion" / "evals" / "misconceptions.yaml"
    suite = yaml.safe_load(cases.read_text())
    suite["scenarios"] = suite["scenarios"][:2]
    cases.write_text(yaml.safe_dump(suite, sort_keys=False))
    errors = minimum_errors(root)
    assert any(e.startswith("phy-o-motion: 2 eval cases, fewer than its minimum") for e in errors)
    assert any(e.startswith("phy-o-motion: no eval case for misconception") for e in errors)
    shutil.rmtree(root / "agent" / "agent-check-plan" / "evals")
    assert "agent-check-plan: 0 eval cases, fewer than its minimum 5 (SKL-21)" in minimum_errors(root)
    settings = Settings()
    assert (settings.skill_eval_min_teaching, settings.skill_eval_min_pedagogy, settings.skill_eval_min_agent) == (
        3, 5, 5)  # fmt: skip


def _live_model() -> str | None:
    url = os.environ.get("JANA_LOCAL_MODEL_URL", "http://127.0.0.1:8089")
    try:
        import httpx

        models = httpx.get(f"{url}/v1/models", timeout=2).json()["data"]
    except Exception:
        return None
    return url if any(m["id"] == os.environ.get("JANA_LOCAL_MODEL", "gemma-4-12b") for m in models) else None


@pytest.mark.skipif(
    os.environ.get("JANA_LIVE_SKILL_EVAL") != "1",
    reason="runs on the local fast-tier model: set JANA_LIVE_SKILL_EVAL=1 with a model reachable",
)
def skl21_example_eval_passes(tmp_path: Path) -> None:
    """The suvat example's sign misconception case, colocated with a copy of the example, on the fast tier."""
    from agent_core.assets.skills import parse
    from agent_core.providers.llama import LlamaServerProvider
    from jana_tools.skill_evals import load_cases, run_case

    url = _live_model()
    if url is None:
        pytest.skip("no local fast-tier model is reachable")
    folder = tmp_path / "skills" / "teaching" / "phy" / "phy-o-kinematics-suvat"
    shutil.copytree(EXAMPLES / "phy-o-kinematics-suvat", folder)
    shutil.copytree(FIXTURES / "phy-o-kinematics-suvat" / "evals", folder / "evals")
    skill = parse(folder / "SKILL.md")
    (case,) = [c for c in load_cases(folder)[0] if "sign" in c["tags"]]

    async def go() -> Any:
        provider = LlamaServerProvider(url, "local")
        try:
            return await run_case(case, skill, provider, os.environ.get("JANA_LOCAL_MODEL", "gemma-4-12b"),
                                  tmp_path / "run")  # fmt: skip
        finally:
            await provider.close()

    result = run(go())
    assert result.passed, (result.error, result.failures)


def evl07_skill_requires_eval(tmp_path: Path) -> None:
    from jana_tools.skill_evals import passing_records, review_errors

    root = tree(tmp_path, with_examples=False)
    results = tmp_path / "results.json"
    skill = root / "agent" / "agent-plan-solution" / "SKILL.md"
    skill.write_text(skill.read_text().replace("status: draft", "status: reviewed"))
    assert review_errors(root, results) == [
        "agent-plan-solution: reviewed without a passing colocated eval run for version 0.1 (EVL-07)"
    ]
    records = passing_records(root)
    results.write_text(json.dumps({"skills": records}))
    assert review_errors(root, results) == []
    failing = {**records, "agent-plan-solution": {**records["agent-plan-solution"], "hard_passed": 4,
                                                  "hard_total": 5}}  # fmt: skip
    results.write_text(json.dumps({"skills": failing}))
    assert review_errors(root, results), "a hard assertion failed: not reviewable"
    results.write_text(json.dumps({"skills": records}))
    cases = skill.parent / "evals" / "questions.yaml"
    cases.write_text(cases.read_text().replace("I'm not sure where to start.", "Where do I start?"))
    assert review_errors(root, results), "the evals changed since the run: run them again"
    shutil.rmtree(skill.parent / "evals")
    assert review_errors(root, results), "no colocated evals at all"
