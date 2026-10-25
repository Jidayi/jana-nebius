"""M4.i and M4.j: per-turn traces, structured logs, redaction, tool events and the scenario runner (OBS-01 to OBS-07,
OBS-11, OBS-12, OBS-14, OBS-19, SEC-30, TOL-15, EVL-03)."""

import asyncio
import datetime
import json
import shutil
from pathlib import Path

import pytest
import yaml
from agent_core.contracts import errors as contract_errors
from agent_core.trace.logs import JsonLogger
from agent_core.trace.payloads import PayloadStore
from agent_core.trace.record import TraceBuilder
from agent_core.trace.telemetry import as_text, debug_bundle, telemetry_export
from engine_harness import STATEMENT, checker_steps, close, make_engine, reply, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools import scenarios as runner
from jana_tools.skills import build_bundle
from jana_tools.traceview import gather, tier_diff

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
CANARY_SECRET = "sk-canary0000000000secretkey"  # noqa: S105 - a seeded canary, not a credential
CANARY_STUDENT = "my name is Canarina Kweku and I live at 12 Canary Road"


def run(coro):
    return LOOP.run_until_complete(coro)


def session(tmp_path: Path, coach: list, logs: Path | None = None, **kw):
    engine, provider = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach},
                                       **kw))  # fmt: skip
    if logs is not None:
        engine.logger = JsonLogger(logs, "core", "epoch-test-0001")
        engine.worker_logger = JsonLogger(logs, "worker", "epoch-test-0001")
    return engine, provider


# --- OBS-01 ---------------------------------------------------------------------------------------------------------


def obs01_trace_validates_against_contract(tmp_path: Path):
    engine, _ = session(tmp_path, [tutor(SAFE), tutor(SAFE), tutor("That's right (checked): 10 m. Why?")])
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("I'm stuck"))
    run(engine.student_turn("s = 3 m"))
    run(engine.student_turn("s = 10 m"))
    run(close(engine))
    assert len(engine.traces) == 4
    for trace in engine.traces:
        assert contract_errors("trace/turn-trace", trace) == []
    # The scenario suite's turns validate too (every record is checked when the turn ends).
    for result in runner.run_suites():
        assert all(contract_errors("trace/turn-trace", t) == [] for t in result.traces)


def obs01_partial_trace_on_crash(tmp_path: Path):
    engine, _ = session(tmp_path, [tutor(SAFE)])
    run(engine.start_problem(STATEMENT))

    async def explode(*args, **kwargs):
        raise RuntimeError("the core was killed mid-call")

    engine.deps.router.complete = explode  # type: ignore[method-assign]
    with pytest.raises(RuntimeError):
        run(engine.student_turn("s = 3 m"))
    run(close(engine))
    crashed = engine.traces[-1]
    assert crashed["status"] in ("error", "interrupted") and contract_errors("trace/turn-trace", crashed) == []
    assert [p["phase"] for p in crashed["phases"]] == ["prepare"]  # the phases recorded so far


# --- OBS-02 to OBS-06 -----------------------------------------------------------------------------------------------


def obs02_tier_fingerprint_isolates_change(tmp_path: Path):
    content = tmp_path / "agent"
    shutil.copytree(REPO_ROOT / "content" / "agent", content)

    def one_turn(root: Path, folder: str):
        from agent_core.engine import assembly

        original = assembly.assemble

        async def build():
            engine, _ = await make_engine(tmp_path / folder, {"solver": solver_steps(), "checker": checker_steps(),
                                                              "coach": [tutor(SAFE)]})  # fmt: skip
            from agent_core.assets.agent import AgentAssets

            engine.deps.assets = AgentAssets.load(root, REPO_ROOT / "skills", frozenset({"draft", "reviewed"}))
            result = await engine.start_problem(STATEMENT)
            await close(engine)
            return result.trace

        _ = original
        return run(build())

    before = one_turn(content, "a")
    block = content / "guidance" / "one-question-per-turn.md"
    block.write_text(block.read_text().replace("Ask exactly one question", "Ask a single question"))
    after = one_turn(content, "b")
    assert tier_diff(before, after, role="coach") == ["guidance"]


def obs03_skill_version_recorded(tmp_path: Path):
    load = reply("", [("c1", "skill", {"skill_name": "pedagogy-guided-solve"})])
    engine, _ = session(tmp_path, [load, tutor(SAFE)])
    result = run(engine.start_problem(STATEMENT))
    run(close(engine))
    manifest = {m["name"]: m for m in build_bundle(release=False).manifest}
    delivered = [s for s in result.trace["skills"] if s["name"] == "pedagogy-guided-solve"]
    assert delivered and delivered[0]["version"] == manifest["pedagogy-guided-solve"]["version"]
    assert delivered[0]["sha256"] == manifest["pedagogy-guided-solve"]["sha256"] and delivered[0]["receipt"] is False


def obs04_fallback_chain_recorded(tmp_path: Path):
    from agent_core.providers.scripted import ScriptedProvider, default_capabilities

    cloud = ScriptedProvider(lambda m, msgs, body: {"error": {"status": 503}}, kind="cloud",
                             caps={"fast-model": default_capabilities("cloud", context=32768)})  # fmt: skip

    def enable(data):
        data["cloud"]["enabled"] = True
        data["roles"]["coach"]["prefer"] = "cloud"

    engine, _ = session(tmp_path, [tutor(SAFE)], overrides=enable, cloud=cloud)
    engine.deps.router.cloud_on = lambda role: role == "coach"
    result = run(engine.start_problem(STATEMENT))
    run(close(engine))
    coach_calls = [c for c in result.trace["model_calls"] if c["role"] == "coach"]
    cloud_calls = [c for c in coach_calls if c["provider_kind"] == "cloud"]
    local = [c for c in coach_calls if c["provider_kind"] == "local"]
    assert cloud_calls and local and local[0]["fallback_from"] == "cloud:primary/fast-model"
    assert local[0]["model_served"] != "fast-model"
    # MDL-30: each entry carries the filtered candidate list and the prompt mode; the failed attempt names the
    # TABLE MDL-07a reason for the fallback that followed it.
    assert all("cloud:primary/fast-model" in c["candidates"] and c.get("prompt_mode") for c in coach_calls)
    assert cloud_calls[-1]["reason"] == "overloaded"  # a 503, by TABLE MDL-07a
    assert all(contract_errors("trace/turn-trace#/properties/model_calls/items", c) == [] for c in coach_calls)


def obs05_repair_steps_recorded(tmp_path: Path):
    solver = [reply("", [("0", "MathSolve", {"equations": ["0 = 14^2 - 2*9.8*s"], "unknowns": ["s"]})]),
              solver_steps()[1]]  # fmt: skip
    engine, _ = run(make_engine(tmp_path, {"solver": solver, "checker": checker_steps(), "coach": [tutor(SAFE)]}))
    result = run(engine.start_problem(STATEMENT))
    run(close(engine))
    call = next(c for c in result.trace["tool_calls"] if c["name"] == "math_solve")
    assert call["name_emitted"] == "MathSolve" and "name_repair" in call["repairs"] and "unique_id" in call["repairs"]


def obs06_gate_firing_recorded(tmp_path: Path):
    leak = tutor("It rises 10 m. Which equation did you use?", hint_rung=1)
    engine, _ = session(tmp_path, [tutor(SAFE), tutor(SAFE), leak, tutor(SAFE, hint_rung=1)])
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 3 m"))
    result = run(engine.student_turn("I'm stuck"))
    run(close(engine))
    gate = next(g for g in result.trace["gates"] if g["gate"] == "no_answer_leak")
    assert gate["fired"] and gate["nudges"] == 1 and gate["outcome"] == "passed_after_nudge"


# --- OBS-07 ---------------------------------------------------------------------------------------------------------


def obs07_release_default_no_payloads(tmp_path: Path):
    engine, _ = session(tmp_path, [tutor(SAFE), tutor(SAFE)])
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn(f"s = 3 m, {CANARY_STUDENT}"))
    run(close(engine))
    stored = json.dumps(engine.traces)
    assert all(t["capture"]["mode"] == "hashes" for t in engine.traces)
    assert STATEMENT not in stored and SAFE not in stored and "Canarina" not in stored


def obs07_support_mode_expires(tmp_path: Path):
    now = [datetime.datetime(2026, 10, 9, 10, 0, tzinfo=datetime.UTC)]
    store = PayloadStore(tmp_path, clock=lambda: now[0])
    store.put("prof_1", "t1", "prompt", "not stored in hashes mode")
    assert store.files() == []
    expiry = store.enable_full("prof_1")
    assert expiry == now[0] + datetime.timedelta(hours=24) and store.mode("prof_1") == "full"
    store.put("prof_1", "t2", "completion", "stored while support mode is on")
    assert len(store.files()) == 1
    now[0] += datetime.timedelta(hours=23)
    assert store.purge() == 0 and store.files()
    now[0] += datetime.timedelta(hours=1)
    assert store.purge() == 1 and store.files() == [] and store.mode("prof_1") == "hashes"


# --- OBS-11, OBS-12, OBS-14 -----------------------------------------------------------------------------------------


def obs11_logs_structured_and_rotated(tmp_path: Path):
    logger = JsonLogger(tmp_path, "core", "epoch-0001", max_bytes=4000, keep=3)
    for n in range(200):
        logger.log("info", "engine", "turn.start", turn_id=f"trn_{n:026d}", count=n)
    files = logger.files()
    assert 1 < len(files) <= 3
    for path in files:
        assert path.stat().st_size <= 4000
        for line in path.read_text().splitlines():
            record = json.loads(line)
            assert {"ts", "level", "process", "epoch", "component", "event"} <= set(record)


def obs12_cross_process_correlation(tmp_path: Path):
    logs = tmp_path / "logs"
    engine, _ = session(tmp_path, [tutor(SAFE)], logs=logs)
    result = run(engine.start_problem(STATEMENT))
    run(close(engine))
    lines = gather(logs, result.turn_id)
    processes = {line["process"] for line in lines}
    assert {"core", "worker"} <= processes  # the shell and runtime logs join in M5 and M11
    assert any(line["event"] == "fn.call" for line in lines)


def obs14_monotonic_phase_timing():
    mono = [100.0]
    wall = [datetime.datetime(2026, 10, 9, 12, 0, tzinfo=datetime.UTC)]
    trace = TraceBuilder("ses", "prof", monotonic=lambda: mono[0], wall=lambda: wall[0])
    start = trace.offset_ms()
    mono[0] += 0.25
    wall[0] -= datetime.timedelta(hours=3)  # the system clock is set back during the turn
    trace.phase("call", 0, start, "continue")
    assert trace.phases[0]["duration_ms"] == 250 and trace.record()["duration_ms"] == 250


# --- OBS-19, SEC-30, TOL-15 -----------------------------------------------------------------------------------------


def _canary_session(tmp_path: Path):
    logs = tmp_path / "logs"
    engine, _ = session(tmp_path, [tutor(SAFE), tutor(SAFE)], logs=logs)
    engine.logger.fields = {"api_key": CANARY_SECRET}
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn(f"s = 3 m. {CANARY_STUDENT}. Token {CANARY_SECRET}"))
    engine.logger.log("info", "api", "request", text=CANARY_STUDENT, authorization=f"Bearer {CANARY_SECRET}")
    run(close(engine))
    return engine, logs


def obs19_canaries_never_leak(tmp_path: Path):
    engine, logs = _canary_session(tmp_path)
    outputs = {"logs": "".join(p.read_text() for p in logs.glob("*.jsonl")), "traces": as_text(engine.traces),
               "telemetry": as_text(telemetry_export(engine.traces))}  # fmt: skip
    for where, text in outputs.items():
        assert CANARY_SECRET not in text, where
        assert "Canarina" not in text and "Canary Road" not in text, where


def sec30_diagnostics_redacted_at_write(tmp_path: Path):
    engine, logs = _canary_session(tmp_path)
    bundle = as_text(debug_bundle(engine.traces, logs, conversation=engine.state.transcript))
    assert CANARY_SECRET not in bundle and "Canarina" not in bundle
    assert STATEMENT not in bundle
    # Only when an adult includes the conversation does it go in; it was redacted when it was written (PRV-20 keeps the
    # student's personal details out of the stored conversation), so even then no seeded secret or detail is there.
    with_conversation = as_text(debug_bundle(engine.traces, logs, engine.state.transcript, include_conversation=True))
    assert STATEMENT in with_conversation
    assert CANARY_SECRET not in with_conversation and "Canarina" not in with_conversation
    assert "Canary Road" not in with_conversation


def tol15_event_pairing(tmp_path: Path):
    engine, _ = session(tmp_path, [tutor(SAFE)])
    run(engine.start_problem(STATEMENT))
    run(close(engine))
    states = [f["event"] for f in engine.events.frames if f["event"]["type"] == "tool.state"]
    by_call: dict[str, list[str]] = {}
    for event in states:
        by_call.setdefault(event["call_id"], []).append(event["state"]["status"])
    assert by_call
    for call_id, sequence in by_call.items():
        assert sequence.count("running") == 1, call_id
        assert sum(s in ("completed", "error", "cancelled") for s in sequence) == 1, call_id
        running = next(e for e in states if e["call_id"] == call_id and e["state"]["status"] == "running")
        assert running["state"]["title"]["pre"]  # the humanised activity label


def tol15_no_args_in_telemetry(tmp_path: Path):
    engine, _ = session(tmp_path, [tutor(SAFE)])
    run(engine.start_problem(STATEMENT))
    run(close(engine))
    exported = as_text(telemetry_export(engine.traces))
    assert "0 = 14^2" not in exported and "equations" not in exported and "math_solve:ok" in exported


# --- EVL-03 ---------------------------------------------------------------------------------------------------------


def evl03_example_scenarios():
    suite = yaml.safe_load((runner.SUITES / "s1_guided_solve.yaml").read_text())
    results = [run(runner.run_scenario(s, runner.SUITES)) for s in suite["scenarios"]]
    assert [r.status for r in results] == ["passed", "passed"]
    disabled = run(runner.run_scenario(suite["scenarios"][0], runner.SUITES,
                                       disabled_gates=frozenset({"no_answer_leak"})))  # fmt: skip
    assert disabled.status == "failed"
    assert any(c.passed is False and "no_answer_leak" in c.expectation for c in disabled.checks)
    # The contract's examples validate; each runs on a build of its stage: the S1 example passes on this build and
    # fails with the leak gate off, and the S2 examples are skipped.
    contract = json.loads((REPO_ROOT / "evals/contracts/evals/scenario/valid/scenario_example.json").read_text())
    assert runner.suite_errors(contract) == []
    outcomes = {s["id"]: run(runner.run_scenario(s, runner.SUITES)).status for s in contract["scenarios"]}
    assert outcomes == {s["id"]: "passed" if s["stage"] == "S1" else "skipped" for s in contract["scenarios"]}
    s1 = next(s for s in contract["scenarios"] if s["stage"] == "S1")
    leaky = run(runner.run_scenario(s1, runner.SUITES, disabled_gates=frozenset({"no_answer_leak"})))
    assert leaky.status == "failed"


def evl03_schema_strict():
    suite = yaml.safe_load((runner.SUITES / "s1_guided_solve.yaml").read_text())
    suite["scenarios"][0]["turns"][0]["expect"].append({"vibes": "good"})
    assert runner.suite_errors(suite)


# --- OBS-09 ---------------------------------------------------------------------------------------------------------


def _seeded_run(tmp_path: Path, content_root: Path, skills_root: Path) -> dict:
    """One scripted problem start whose Coach loads a skill, assembled on the given asset roots."""
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.scripted import ScriptedProvider
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    async def go() -> dict:
        # An S1 dialogue (no Diagnoser replies): the engine runs the S1 stage for it.
        settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), build_stage="S1")
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path / "w"), settings)
        await supervisor.start()
        coach = [reply("", [("k1", "skill", {"skill_name": "pedagogy-guided-solve"})]),
                 tutor("Which equation links u, v, a and s?")]  # fmt: skip
        provider = ScriptedProvider({"solver": solver_steps(), "checker": checker_steps(), "coach": coach},
                                    kind="local", installed_models=["qwen3-vl-8b", "gemma-4-12b"])  # fmt: skip
        state = SessionState(new_id("ses"), subject="physics", level="O")
        engine = assemble({"local": provider}, settings, state, content_root, skills_root, tmp_path / "spill",
                          supervisor, session_date="2026-10-09")  # fmt: skip
        await engine.start_problem(STATEMENT)
        await supervisor.close()
        return engine.traces[-1]

    return run(go())


def obs09_viewer_and_diff(tmp_path: Path):
    from jana_tools.traceview import diff, listing, load, waterfall

    # Every trace of the end-to-end suite renders: the scenario suite's turns and a full API session's trace store.
    traces = [t for result in runner.run_suites() for t in result.traces]
    from api_harness import ask, start_core, stop_core

    async def api_session() -> None:
        r = await start_core(tmp_path / "core")
        try:
            sid = await r.session()
            for text, intent in ((STATEMENT, "ask"), ("I'm stuck", "stuck"), ("s = 10 m", "answer")):
                await r.post(f"/v1/sessions/{sid}/turns", ask(text, intent))
                await r.wait_idle(sid)
            assert r.runtime.traces is not None
            r.runtime.traces.flush()
        finally:
            await stop_core(r)

    run(api_session())
    stored = load(tmp_path / "core" / "traces" / "traces.db")
    assert len(stored) >= 3
    traces += stored
    lines = listing(traces)
    assert len(lines) == len(traces) and all(t["trace_id"] in line for t, line in zip(traces, lines, strict=True))
    for trace in traces:
        shown = "\n".join(waterfall(trace))
        assert all(p["phase"] in shown for p in trace["phases"])
        assert shown.count("  model ") == len(trace["model_calls"])
        assert shown.count("  tool  ") == len(trace["tool_calls"])
    # Exported JSON reads back the same.
    export = tmp_path / "traces.json"
    export.write_text(json.dumps(stored))
    assert load(export) == stored

    # Two seeded runs, the second with one guidance block reworded and the skill a version on: the diff names both.
    assets, skills = tmp_path / "agent", tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "content" / "agent", assets)
    shutil.copytree(REPO_ROOT / "skills", skills)
    first = _seeded_run(tmp_path / "a", assets, skills)
    block = assets / "guidance" / "one-question-per-turn.md"
    block.write_text(block.read_text() + "\nAsk about one quantity at a time.\n")
    manifest = skills / "pedagogy" / "pedagogy-guided-solve" / "SKILL.md"
    manifest.write_text(manifest.read_text().replace('version: "0.1"', 'version: "0.2"', 1))
    second = _seeded_run(tmp_path / "b", assets, skills)
    assert first["skills"] and second["skills"]
    changes = diff(first, second)
    assert any(c.startswith("coach: prompt tier") and c.endswith("guidance changed") for c in changes), changes
    assert "skill `pedagogy-guided-solve` 0.1 → 0.2" in changes, changes
    assert diff(first, first) == []
