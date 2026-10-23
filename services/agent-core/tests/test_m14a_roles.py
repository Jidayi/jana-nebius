"""M14.a: the five roles and their audiences, the auxiliary roles, worker restrictions, parallel delegation and failure
handling (AGT-01, AGT-02, AGT-14, AGT-15, AGT-27). The real engine, registry, router and worker with scripted
providers; problems, items and replies are synthetic."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

import pytest
from agent_core.assets.agent import load_manifest, manifest_errors
from agent_core.config import Settings
from agent_core.engine import turn_scope
from agent_core.engine.auxiliary import NEEDS_REVIEW, SCHEMAS, Auxiliaries, mark_low_confidence
from agent_core.engine.auxiliary import ROLES as AUX_ROLES
from agent_core.engine.compaction import PLACEHOLDER
from agent_core.engine.roster import STUDENT_FACING, AudienceError, speaking
from agent_core.tools.catalogue import manifest_grant_errors, role_tools, visible_tools
from agent_core.tools.executor import ToolCall
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.spec import SessionCtx
from agent_core.tools.worker.supervisor import CallOutcome
from engine_harness import STATEMENT, checker_steps, close, reply, solver_steps, tutor
from engine_harness import make_engine as harness_engine
from jana_tools import REPO_ROOT
from jana_tools.harness.egress import offline_run

LOOP = asyncio.new_event_loop()
SPEC = REPO_ROOT / "docs" / "specification"
CONTENT = REPO_ROOT / "content" / "agent"
SAFE = "Which quantities does the question give you, and which one does it ask for?"
CANARY = "TEAM-ONLY-7731"  # put in every team role's reply: it must never reach the student


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def settings(**overrides: Any) -> Settings:
    """Generous worker limits: these tests are about roles and flows, not tool speed on a loaded machine."""
    return Settings(
        **{
            "worker_pool_size": 1,
            "worker_respawn_backoff_s": (0.0,),
            "worker_warm_target_s": 20.0,
            "worker_call_cpu_ms": 30000,
            "ver_symbolic_slice_ms": 10000,
            **overrides,
        }
    )


async def make_engine(tmp: Path, script: dict[str, Any], **kw: Any) -> Any:
    return await harness_engine(tmp, script, **{"settings": settings(), **kw})


def _dir(root: Path, name: str) -> Path:
    path = root / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def diagnosis(**fields: Any) -> dict[str, Any]:
    out = {
        "in_scope": True,
        "subject": "physics",
        "topic_ref": None,
        "kc_refs": [],
        "question_kind": "calculation",
        "knowns": [],
        "unknowns": ["height"],
        "clarifying_question": None,
        "misconception_ref": None,
        "evidence": [],
        "inference": f"{CANARY} the answer is probably 10 m",
        "prerequisite_gap_refs": [],
        "confidence": "medium",
    }
    out.update(fields)
    return reply(json.dumps(out))


def verdict(outcome: str = "incorrect") -> dict[str, Any]:
    return reply(
        json.dumps(
            {
                "subject_of_check": "student_answer",
                "verdict": outcome,
                "first_wrong_step": 1 if outcome != "correct" else None,
                "error_category": "value" if outcome != "correct" else "none",
                "why": f"{CANARY} 10 m is right",
                "counterexample": None,
                "misconception_ref": None,
                "method": "substitute_back",
                "step_marks": [],
                "check_ids": ["chk_00000000000000000000000000"],
            }
        )
    )


def unchecked() -> dict[str, Any]:
    """A schema-valid Solver plan whose answer no tool produced (it cites a check that does not exist)."""
    step = {
        "index": 1,
        "latex": "v^2 = u^2 + 2as",
        "reason": "links the quantities",
        "check_id": None,
        "kc_ref": None,
        "value": None,
        "unit": None,
    }
    return reply(
        json.dumps(
            {
                "status": "complete",
                "method_summary": "Use v^2 = u^2 + 2as.",
                "steps": [step],
                "final_answer": {
                    "latex": "s = 10",
                    "value": "10",
                    "unit": "m",
                    "check_id": "chk_00000000000000000000000000",
                    "plausible": True,
                },
                "blocked_step": None,
                "blocked_reason": None,
            }
        )
    )


def bank_item() -> dict[str, Any]:
    from pack_builder.build import load_source

    items = load_source(REPO_ROOT / "content" / "curriculum" / "phy" / "o").tables["items"]
    return next(i for i in items if i["id"] == "itm.phy.o.motion.0001")


# --- AGT-01 ---------------------------------------------------------------------------------------------------------


def agt01_roles_register_matches_manifests() -> None:
    register = json.loads((SPEC / "registers" / "roles.json").read_text())["roles"]
    toolsets = json.loads((SPEC / "registers" / "toolsets.json").read_text())
    specialists = [r for r in register if r["kind"] == "specialist"]
    assert {r["id"] for r in specialists} == {"coach", "diagnoser", "solver", "checker", "reflector"}
    for row in specialists:
        for path in (SPEC / "contracts" / "agents" / row["manifest"], CONTENT / "roles" / f"{row['id']}.md"):
            meta = load_manifest(path).meta
            assert (meta["audience"], meta["model_role"], meta["toolsets"], meta["output_schema"]) == (
                row["audience"],
                row["model_role"],
                row["toolsets"],
                row["output_schema"],
            ), path
            assert (
                manifest_grant_errors(
                    meta["id"], meta["tools"], meta["toolsets"], toolsets["toolsets"], toolsets["roleGrants"]
                )
                == []
            ), path
    audiences = {r["id"]: r["audience"] for r in register}
    assert [r for r, a in audiences.items() if a == "student"] == ["coach"]
    # Auxiliary roles: one manifest each, team audience, no tools, a structured output with its schema (AGT-02).
    auxiliary = {r["id"]: r for r in register if r["kind"] == "auxiliary" and r["id"] in AUX_ROLES}
    assert set(auxiliary) == set(AUX_ROLES)  # TABLE AGT-02a (the item drafter is S5, AGT-30)
    files = sorted((CONTENT / "roles" / "auxiliary").glob("*.md"))
    assert {p.stem for p in files} == set(auxiliary)
    for path in files:
        assert manifest_errors(path) == [], path
        meta = load_manifest(path).meta
        row = auxiliary[meta["id"]]
        assert (meta["kind"], meta["audience"], meta["model_role"], meta["toolsets"], meta["tools"]) == (
            "auxiliary",
            row["audience"],
            row["model_role"],
            row["toolsets"],
            [],
        )
        # The register names the role's output contract and its reference manifest in the specification.
        assert meta["output_mode"] == "structured"
        assert meta["output_schema"] == row["output_schema"] == SCHEMAS[meta["id"]].split("/")[1] + ".schema.json"
        reference = load_manifest(SPEC / "contracts" / "agents" / row["manifest"]).meta
        assert (reference["id"], reference["output_schema"]) == (meta["id"], row["output_schema"]), path
        assert meta["permissions"] == {
            "address_student": False,
            "delegate": False,
            "write_memory": "none",
            "open_cards": False,
        }


def agt01_coach_no_compute_or_ui_tools(tmp_path: Path) -> None:
    forbidden = {t["name"] for ts in ("compute", "ui") for t in REGISTER["toolsets"][ts]["tools"]}
    coach = load_manifest(CONTENT / "roles" / "coach.md").meta
    for stage in ("S1", "S2", "S3", "S4", "S5"):
        names = role_tools(
            "coach",
            coach["tools"],
            _registry(),
            REGISTER["roleGrants"],
            stage,
            frozenset({"memory_recall", "session_recall"}),
        )
        assert not set(names) & forbidden, stage
        for profile in ("full", "small"):
            session = SessionCtx(profile=profile, subject="physics", level="O", role="coach", stage=stage)
            shown = visible_tools(
                "coach", names, _registry(), session, _AlwaysAvailable(), REGISTER["roleGrants"], Settings()
            )
            assert not {s.name for s in shown} & forbidden, (stage, profile)
    # And on the wire: every Coach request on every class lists no compute or ui tool.
    for hardware in ("low", "mid", "high", "cloud"):
        engine, provider = run(
            make_engine(
                _dir(tmp_path, hardware),
                {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)]},
                hardware_class=hardware,
            )
        )
        try:
            run(engine.start_problem(STATEMENT))
        finally:
            run(close(engine))
        requests = [r for r in provider.requests if r.get("_role") == "coach"]
        assert requests, hardware
        for request in requests:
            listed = {t["function"]["name"] for t in request.get("tools") or []}
            assert not listed & forbidden, (hardware, listed)


class _AlwaysAvailable:
    def visible(self, spec: Any, session: Any) -> bool:
        return True

    def __call__(self, spec: Any, session: Any) -> bool:
        return True

    def reset(self) -> None:
        return None


def _registry() -> Any:
    from agent_core.tools.specs import registry

    return registry()


def agt01_only_coach_addresses_student(tmp_path: Path) -> None:
    """200 scripted turns in which every team role writes student-like text: every text, board, card and visual
    part opened came from the Coach or the engine itself, and no team role's words reached a frame."""
    answers = ["s = 12 m", "I'm stuck", "maybe it is about the speed?", "s = 8 m"]
    turns = 200
    coach = [tutor(SAFE, hint_rung=0) for _ in range(turns + 1)]
    script = {
        "diagnoser": [diagnosis() for _ in range(2 * turns + 2)],
        "solver": solver_steps(),
        "checker": [verdict() for _ in range(turns + 1)],
        "coach": coach,
    }
    engine, _ = run(make_engine(tmp_path, script))
    engine.deps.stage = "S2"
    statuses = []
    try:
        statuses.append(run(engine.start_problem(STATEMENT)).status)
        for n in range(turns - 1):
            statuses.append(run(engine.student_turn(answers[n % len(answers)])).status)
    finally:
        run(close(engine))
    assert len(statuses) == turns and set(statuses) == {"complete"}
    student = [(kind, who) for kind, who in engine.audience.origins if kind in STUDENT_FACING]
    assert student and {who for _, who in student} <= {"coach", "engine"}
    assert {who for _, who in engine.audience.origins} >= {"coach"}
    assert CANARY not in json.dumps([f["event"] for f in engine.events.frames])
    # A team role that tried to open a student-facing part is refused before anything is emitted.
    before = len(engine.events.frames)
    for role in ("solver", "checker", "diagnoser", "reflector", "title"):
        with speaking(role), pytest.raises(AudienceError):
            engine.events.start_part("text")
    assert len(engine.events.frames) == before


# --- AGT-02 ---------------------------------------------------------------------------------------------------------


def agt02_auxiliary_fallbacks(tmp_path: Path) -> None:
    """Every auxiliary call fails (no slot scripted, then a crashed runtime): each role's fallback answers and the
    Coach's turn still ends `complete`."""
    script = {
        "solver": solver_steps(),
        "checker": checker_steps(),
        "coach": [tutor(SAFE), tutor(SAFE)],
        "title": [{"transport": "connection_reset"}] * 8,
    }
    engine, _ = run(make_engine(tmp_path, script))
    aux = engine.auxiliary

    async def scenario() -> dict[str, Any]:
        result = await engine.start_problem(STATEMENT)
        with turn_scope("trn_01JZ00000000000000000000A2"):
            rules = await aux.match_rules(
                "hint rung 2 after a wrong answer",
                [(1, "Ask for units", ["units"]), (2, "Praise effort", ["effort"])],
                "I forgot the units",
            )
            guard = await aux.guard_input("Can you explain the next step?")
            distress = await aux.guard_input("I want to die")
            regions, type_it = await aux.read_regions("read this photo")
            title, title_outcome = await aux.title(STATEMENT, "Motion")
            from agent_core.engine.compaction import Compactor

            _, record = await Compactor(engine.deps.settings).compact(
                engine.state,
                [
                    {"role": "user", "content": "q", "kind": "problem"},
                    *({"role": "user", "content": f"let's keep using metres {n}", "kind": "chat"} for n in range(12)),
                ],
                summarise=aux.summariser(),
            )
            judged, judge_fell_back = await aux.judge(
                [("m1", "uses v^2 = u^2 + 2as"), ("a1", "correct answer")], "v^2 = u^2 + 2as"
            )
        after = await engine.student_turn("I'm stuck")
        return {
            "first": result,
            "rules": rules,
            "guard": guard,
            "distress": distress,
            "regions": regions,
            "type_it": type_it,
            "title": title,
            "title_outcome": title_outcome,
            "record": record,
            "judged": judged,
            "judge_fell_back": judge_fell_back,
            "after": after,
        }

    try:
        out = run(scenario())
    finally:
        run(close(engine))
    assert out["first"].status == "complete" and out["after"].status == "complete"
    assert out["rules"][0] == [(1, "keyword: units")] and out["rules"][1] is not None and out["rules"][1].fell_back
    assert out["guard"] == ("in_scope", 0.0, "patterns_fallback")
    assert out["distress"][0] == "distress" and out["distress"][2] == "patterns"  # patterns win before any model
    assert out["regions"] == [] and out["type_it"] is True  # nothing guessed: the student types it
    assert out["title"] == "Motion" and out["title_outcome"].fell_back
    assert out["record"].sections["Agreements"] == PLACEHOLDER
    assert out["judge_fell_back"] and {c["status"] for c in out["judged"]} == {NEEDS_REVIEW}
    assert not any(c["pass"] for c in out["judged"])  # never a mark by default
    assert {o.role for o in aux.log} == {"rule_matcher", "input_guard", "vision", "title", "compaction", "judge"}
    assert all(o.fell_back for o in aux.log)


def test_agt02_auxiliary_outputs_used(tmp_path: Path) -> None:
    """With a working slot the role's structured output is used, bounded and cleaned."""
    script = {
        "input_guard": [reply(json.dumps({"class": "off_topic", "confidence": 0.9}))],
        "title": [reply(json.dumps({"title": "Height 14 reached by a ball thrown upward"}))],
        "judge": [reply(json.dumps({"criteria": [{"id": "m1", "pass": True, "evidence": "v^2 = u^2 + 2as"}]}))],
    }
    engine, _ = run(make_engine(tmp_path, script, worker=False))

    async def scenario() -> tuple[Any, ...]:
        with turn_scope("trn_01JZ00000000000000000000A3"):
            return (
                await engine.auxiliary.guard_input("tell me about football"),
                await engine.auxiliary.title(STATEMENT, "Motion"),
                await engine.auxiliary.judge([("m1", "uses the right equation")], "v^2 = u^2 + 2as"),
            )

    guard, (title, _), (judged, fell_back) = run(scenario())
    assert guard == ("off_topic", 0.9, "model")
    assert title == "Height reached by a ball thrown" and len(title.split()) <= Settings().title_max_words
    assert not fell_back and judged == [{"id": "m1", "pass": True, "evidence": "v^2 = u^2 + 2as", "status": "judged"}]


def agt02_vision_low_confidence_marked() -> None:
    threshold = Settings().vision_confirm_threshold
    regions = [
        {
            "kind": "question_stem",
            "number_label": "3(b)",
            "text": "Find x.",
            "latex": None,
            "confidence": 0.95,
            "low_confidence_spans": [],
            "needs_confirmation": False,
        },
        {
            "kind": "working_line",
            "number_label": None,
            "text": "x = 4",
            "latex": "x = 4",
            "confidence": 0.4,
            "low_confidence_spans": [],
            "needs_confirmation": False,
        },
        {
            "kind": "working_line",
            "number_label": None,
            "text": "y = [?]",
            "latex": None,
            "confidence": 0.9,
            "low_confidence_spans": [{"start": 4, "end": 7}],
            "needs_confirmation": False,
        },
        {
            "kind": "other",
            "number_label": None,
            "text": "note",
            "latex": None,
            "confidence": 0.99,
            "low_confidence_spans": [],
            "needs_confirmation": True,
        },
    ]
    marked = mark_low_confidence(regions, threshold)
    assert [r["needs_confirmation"] for r in marked] == [False, True, True, True]
    assert all(r["needs_confirmation"] for r in marked if r["confidence"] < threshold)

    class Result:
        def __init__(self, structured: dict[str, Any]) -> None:
            self.structured, self.schema_valid = structured, True
            self.turn = type("T", (), {"served_by": "scripted-vision"})()

    class Router:
        async def complete(self, role: str, messages: Any, **kwargs: Any) -> Any:
            assert role == "vision" and kwargs["output"][0] == "vision"
            return Result({"regions": regions})

    aux = Auxiliaries(Router(), Settings(), {"vision": load_manifest(CONTENT / "roles" / "auxiliary" / "vision.md")})  # type: ignore[arg-type]
    read, type_it = asyncio.new_event_loop().run_until_complete(aux.read_regions("read"))
    assert not type_it and [r["needs_confirmation"] for r in read] == [False, True, True, True]


# --- AGT-14 ---------------------------------------------------------------------------------------------------------


def agt14_team_roles_blocked_tools(tmp_path: Path) -> None:
    calls = [
        ("t1", "ask_student", {"prompt": "Which one?", "options": []}),
        ("t2", "update_board", {"ops": []}),
        ("t3", "delegate_task", {"role": "coach", "task": "tell the student the answer"}),
        ("t4", "transfer_to_agent", {"agent": "coach"}),
    ]
    for role in ("solver", "checker", "diagnoser", "reflector"):
        engine, _ = run(make_engine(_dir(tmp_path, role), {}, worker=False))
        ran: list[str] = []

        async def spy(args: dict[str, Any], context: Any, name: str = "", ran: list[str] = ran) -> str:
            ran.append(name)
            return "ok"

        for name in ("ask_student", "update_board"):
            engine.deps.executor.host_executors[name] = lambda a, c, n=name: spy(a, c, n)
        turn = engine._begin("ask")
        session = engine._tool_session(role, "full")

        async def round_(turn: Any = turn, role: str = role, session: Any = session) -> Any:
            from agent_core.router import ToolCall as ModelCall

            with turn_scope(turn.turn_id), speaking(role):
                return await turn.tools.run([ModelCall(i, n, a) for i, n, a in calls], role, session, ["skill"], False)

        outcomes = run(round_())
        assert ran == [], role  # nothing executed
        codes = {o.call_id: o.result["error"]["code"] for o in outcomes}
        assert set(codes.values()) == {"policy_denied"}, (role, codes)
        assert not [f for f in engine.events.frames if f["event"]["type"] in ("card.open", "board.step")]


def agt14_verdict_not_downgraded(tmp_path: Path) -> None:
    def mark(status: str, check_id: str | None = None) -> list[dict[str, Any]]:
        return [
            {
                "op": "mark_step",
                "step": 1,
                "latex": None,
                "reason": None,
                "owner": None,
                "status": status,
                "terms": [],
                "prompt": None,
                "check_id": check_id,
            }
        ]

    revise = [
        {
            "op": "revise_step",
            "step": 1,
            "latex": "s = 10",
            "reason": "fixed",
            "owner": None,
            "status": None,
            "terms": [],
            "prompt": None,
            "check_id": None,
        }
    ]
    script = {
        "solver": solver_steps(),
        "checker": checker_steps(),
        "coach": [
            tutor(SAFE),
            tutor("Good work.", board=mark("correct")),
            tutor("Fixed it.", board=revise),
            tutor(SAFE),
        ],
    }
    engine, _ = run(make_engine(tmp_path, script))
    try:
        run(engine.start_problem(STATEMENT))
        result = run(engine.student_turn("s = 12 m"))  # checked incorrect by code
    finally:
        run(close(engine))
    step = engine.state.board.steps[0]
    assert step.owner == "student" and step.status == "incorrect"
    schema = next(g for g in result.trace["gates"] if g["gate"] == "schema")
    assert schema["fired"] and schema["nudges"] == 2  # both drafts fail validation; the third is accepted
    statuses = [
        f["event"]["status"]
        for f in engine.events.frames
        if f["event"]["type"] == "board.step" and f["event"]["step_id"] == step.step_id
    ]
    assert statuses == ["incorrect"]  # never re-marked on the board


# --- AGT-15 ---------------------------------------------------------------------------------------------------------


def agt15_parallel_join(tmp_path: Path) -> None:
    """On cloud candidates the Checker and the Diagnoser reading one answer overlap, and both end before the Coach
    is called."""
    stall = 0.4
    starts: dict[str, list[float]] = {"checker": [], "diagnoser": [], "coach": []}

    def timed(role: str, step: dict[str, Any]) -> Any:
        def run_step(body: dict[str, Any]) -> dict[str, Any]:
            starts[role].append(time.monotonic())
            return {**step, "stall_s": stall if role != "coach" else 0}

        return run_step

    from agent_core.providers.scripted import ScriptedProvider

    cloud = ScriptedProvider(
        {
            "checker": [timed("checker", verdict())],
            "diagnoser": [timed("diagnoser", diagnosis())],
            "coach": [],
            "solver": [],
        },
        kind="cloud",
    )
    local = {
        "diagnoser": [diagnosis()],
        "solver": solver_steps(),
        "checker": [],
        "coach": [tutor(SAFE), timed("coach", tutor(SAFE))],
    }

    def overrides(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True
        for role in ("checker", "diagnoser"):
            data["roles"][role]["prefer"] = "cloud"

    engine, _ = run(make_engine(tmp_path, local, overrides=overrides, cloud=cloud))
    engine.deps.stage = "S2"
    engine.deps.router.cloud_on = lambda role: role in ("checker", "diagnoser")
    try:
        run(engine.start_problem(STATEMENT))
        cloud.script["diagnoser"] = [timed("diagnoser", diagnosis())]  # the start used the local Diagnoser
        starts["diagnoser"].clear()
        result = run(engine.student_turn("s = 12 m"))
    finally:
        run(close(engine))
    assert result.status == "complete"
    (checker,), (diagnoser,) = starts["checker"], starts["diagnoser"]
    assert abs(checker - diagnoser) < stall, "the two calls overlap"
    assert starts["coach"] and starts["coach"][-1] >= max(checker, diagnoser) + stall * 0.9, "joined before the Coach"
    kinds = {c["role"]: c["provider_kind"] for c in result.trace["model_calls"] if c["role"] != "coach"}
    assert kinds == {"checker": "cloud", "diagnoser": "cloud"}
    # The specialists of the reading; the input guard's own call is traced beside them as an auxiliary (AGT-02).
    roles = [d["role"] for d in result.trace["delegations"] if d["role"] not in AUX_ROLES]
    assert sorted(roles) == ["checker", "diagnoser"]


def agt15_bank_item_skips_solver(tmp_path: Path) -> None:
    script = {"diagnoser": [diagnosis()], "solver": [], "checker": [], "coach": [tutor(SAFE)]}
    engine, provider = run(make_engine(tmp_path, script, worker=False))
    engine.deps.stage = "S2"
    try:
        result = run(engine.start_practice(bank_item()))
    finally:
        run(close(engine))
    assert result.status == "complete"
    roles = [r.get("_role") for r in provider.requests]
    assert "solver" not in roles and roles.count("diagnoser") == 1 and roles[-1] == "coach"


# --- AGT-27 ---------------------------------------------------------------------------------------------------------


def _leaks(n: int) -> list[dict[str, Any]]:
    words = ["first", "second", "third", "fourth"]
    return [tutor(f"It rises 10 m, as the {words[k]} check shows.", hint_rung=1) for k in range(n)]


def agt27_failure_table(tmp_path: Path) -> None:
    rows: dict[str, Any] = {}

    # 1. Cloud unreachable mid-call: the local candidate answers; one notice; no cloud text reaches the student.
    from agent_core.providers.scripted import ScriptedProvider

    cloud = ScriptedProvider({"coach": [{"transport": "connection_reset"}] * 4}, kind="cloud")

    def prefer_cloud(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True
        data["roles"]["coach"]["prefer"] = "cloud"

    engine, _ = run(
        make_engine(
            _dir(tmp_path, "cloud"),
            {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)]},
            overrides=prefer_cloud,
            cloud=cloud,
        )
    )
    engine.deps.router.cloud_on = lambda role: role == "coach"
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    notices = [f["event"]["code"] for f in engine.events.frames if f["event"]["type"] == "notice"]
    assert result.status == "complete" and engine.events.student_text(result.turn_id).endswith(SAFE)
    assert notices in (["cloud_unavailable_using_local"], ["cloud_continuing_locally"])
    rows["cloud"] = True

    # 2. Local runtime crashed: the turn waits for the restart and goes again once from Prepare.
    crashed = [True]

    def coach_step(body: dict[str, Any]) -> dict[str, Any]:
        return {"transport": "connection_reset"} if crashed[0] else tutor(SAFE)

    for retry_ok in (True, False):
        engine, _ = run(
            make_engine(
                _dir(tmp_path, f"crash-{retry_ok}"),
                {"solver": solver_steps(), "checker": checker_steps(), "coach": [coach_step] * 12},
            )
        )
        crashed[0] = True

        async def restarted(ok: bool = retry_ok) -> bool:
            crashed[0] = not ok
            return True

        engine.deps.runtime_restarted = restarted
        try:
            result = run(engine.start_problem(STATEMENT))
        finally:
            run(close(engine))
        phases = [f["event"]["phase"] for f in engine.events.frames if f["event"]["type"] == "status"]
        assert phases.count("queued") == 1
        assert result.status == ("complete" if retry_ok else "error"), retry_ok
    rows["runtime"] = True

    # 3. No model can run: no model call is made; tool checks still work (lessons and practice need no model).
    engine, provider = run(make_engine(_dir(tmp_path, "nomodel"), {}))
    try:
        checked = run(
            engine.deps.executor.run_one(
                ToolCall("call_n_1", "math_evaluate", {"expression": "2+3"}),
                "engine",
                engine._tool_session("engine", "full"),
            )
        )
    finally:
        run(close(engine))
    assert checked["status"] == "ok" and provider.requests == []
    rows["no_model"] = True

    # 4. Tool worker crashed: a pure call is retried once on the respawned worker; twice crashed, no number shown.
    unchecked_plan = unchecked()
    for crashes in (1, 99):
        # After both worker attempts fail, keep returning the unverified plan for the
        # planner's bounded correction/replan attempts, rather than exhausting the fixture.
        solver = solver_steps() if crashes == 1 else [solver_steps()[0], *[unchecked_plan] * 6]
        engine, _ = run(
            make_engine(_dir(tmp_path, f"worker-{crashes}"), {"solver": solver, "checker": [], "coach": [tutor(SAFE)]})
        )
        supervisor = engine.deps.executor.supervisor
        original = supervisor.call
        left = [crashes]

        async def call(*args: Any, left: list[int] = left, original: Any = original, **kwargs: Any) -> Any:
            if left[0] > 0:
                left[0] -= 1
                return CallOutcome(error="worker_crashed", detail="the checking worker stopped during the call")
            return await original(*args, **kwargs)

        supervisor.call = call
        try:
            result = run(engine.start_problem(STATEMENT))
        finally:
            run(close(engine))
        text = engine.events.student_text(result.turn_id)
        if crashes == 1:
            assert engine.state.plan is not None and result.status == "complete"
        else:
            assert engine.state.plan is None and "10" not in text  # the honest blocker, no unchecked number
            assert any(c.get("error_code") == "worker_crashed" for c in result.trace["tool_calls"])
    rows["worker"] = True

    # 5. Diagnoser fails twice: the student picks the topic from a card.
    engine, _ = run(
        make_engine(
            _dir(tmp_path, "diag"), {"diagnoser": [reply("not json")] * 12, "solver": [], "checker": [], "coach": []}
        )
    )
    engine.deps.stage = "S2"
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    cards = [f["event"]["card"] for f in engine.events.frames if f["event"]["type"] == "card.open"]
    assert result.status == "complete" and result.degraded and result.degraded_reason == "diagnoser_failed"
    assert cards and cards[-1]["card_type"] == "question" and cards[-1]["allow_free_text"]
    assert engine.state.plan is None
    rows["diagnoser"] = True

    # 6. Solver cannot verify: the honest blocker, method guidance without numbers.
    unverified = [unchecked() for _ in range(6)]
    engine, _ = run(make_engine(_dir(tmp_path, "solver"), {"solver": unverified, "checker": [], "coach": []}))
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    honest = engine.deps.templates.render("tpl.honest_blocker")
    assert result.degraded_reason == "plan_unverified" and engine.events.student_text(result.turn_id).endswith(honest)
    rows["solver"] = True

    # 7. Gates exhausted: the reviewed canned hint for the rung.
    engine, _ = run(
        make_engine(
            _dir(tmp_path, "gates"),
            {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE), *_leaks(3)]},
        )
    )
    try:
        run(engine.start_problem(STATEMENT))
        run(engine.student_turn("I'm stuck"))  # the entry question first (PED-05)
        result = run(engine.student_turn("I'm stuck"))
    finally:
        run(close(engine))
    assert result.degraded and result.degraded_reason == "answer_leak_exhausted"
    assert engine.events.student_text(result.turn_id) == engine.deps.templates.hints[1]
    rows["gates"] = True

    # 8. Budget exhausted: the pending answer when one passed every gate, else the canned turn; never a rejected draft.
    engine, _ = run(
        make_engine(
            _dir(tmp_path, "budget"),
            {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE), *_leaks(4)]},
            settings=settings(coach_turn_ceiling=2),
        )
    )
    try:
        run(engine.start_problem(STATEMENT))
        run(engine.student_turn("I'm stuck"))
        result = run(engine.student_turn("I'm stuck"))
    finally:
        run(close(engine))
    assert result.degraded and "10 m" not in engine.events.student_text(result.turn_id)
    rows["budget"] = True
    assert len(rows) == 8


def agt27_offline_all_modes(tmp_path: Path) -> None:
    """With every non-loopback connection refused for the whole session, each mode this build has completes a
    scripted problem: guided solve, practice and check my working, and a side question."""
    script = {
        "solver": solver_steps() * 2,
        "checker": checker_steps() * 2,
        "coach": [tutor(SAFE) for _ in range(8)],
        "diagnoser": [diagnosis() for _ in range(6)],
    }
    with offline_run() as egress:
        engine, _ = run(make_engine(tmp_path, script))
        engine.deps.stage = "S2"
        try:
            results = [
                run(engine.start_problem(STATEMENT)),
                run(engine.student_turn("I'm stuck")),
                run(engine.side_question("What does acceleration mean again?")),
                run(engine.start_practice(bank_item())),
                run(engine.check_working(STATEMENT, "v^2 = u^2 + 2as\n0 = 14^2 - 2(9.8)s")),
            ]
        finally:
            run(close(engine))
    assert [r.status for r in results] == ["complete"] * 5
    assert egress.attempts == []
