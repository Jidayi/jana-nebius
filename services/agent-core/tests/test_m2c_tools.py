"""M2.c: tool contract, registry, risk classes, errors, batching and bounded results (TOL-01 to TOL-05, TOL-10 to
TOL-12; the registry half of SEC-09)."""

import asyncio
import copy
import dataclasses
import json
import random
import re
import string
import sys
from pathlib import Path

import pytest
import yaml
from agent_core.config import Settings
from agent_core.tools.executor import ToolCall, ToolExecutor, plan
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.policy import denial
from agent_core.tools.registry import RegistrationError, Registry, build, build_entries, register_entries, spec_errors
from agent_core.tools.results import ERROR_RULES, envelope_errors, error_result
from agent_core.tools.spec import InitCtx, SessionCtx, ToolMeta, ToolSpec
from agent_core.tools.specs import OFFERED_EARLY, registry, specs
from agent_core.tools.spill import SpillStore
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from jana_tools import REPO_ROOT
from jana_tools.toolcheck import committed, snapshot, snapshot_errors

HARNESS = REPO_ROOT / "services" / "tool-worker" / "tests" / "harness.py"
FIXTURES = REPO_ROOT / "services" / "agent-core" / "agent_core" / "tools" / "fixtures"
SPEC_DOCS = REPO_ROOT / "docs" / "specification"
SESSION = SessionCtx(subject="physics", level="O", session_id="ses_01JZ0000000000000000000001")


def _settings(**overrides) -> Settings:
    base = {
        "worker_pool_size": 2,
        "worker_respawn_backoff_s": (0.0,),
        "worker_warm_target_s": 10.0,
        "worker_circuit_restarts": 100,
    }
    return Settings(**{**base, **overrides})


async def _executor(
    tmp_path: Path, argv: list[str] | None = None, extra: list[ToolSpec] = (), **settings
) -> ToolExecutor:
    config = _settings(**settings)
    supervisor = WorkerSupervisor(process_factory(config, argv, tmp_path / "scratch"), config)
    await supervisor.start()
    reg = registry() if not extra else Registry({**registry().specs, **{s.name: s for s in extra}})
    return ToolExecutor(reg, config, SpillStore(tmp_path / "spill"), supervisor)


def _test_spec(name: str, timeout_ms: int | None = 5000, **meta) -> ToolSpec:
    entry = {**register_entries(REGISTER, "S1")["math_parse"][1], "timeoutMs": timeout_ms, **meta}
    return ToolSpec(name, "compute", 1, "S1", "Test-only tool.", {"type": "object"}, ToolMeta.from_register(entry))


# --- TOL-01 -----------------------------------------------------------------------------------------------


def tol01_spec_contract_roundtrip():
    # The public register is the source of ToolMeta names; the runtime may not invent wire metadata.
    entries = [tool for toolset in REGISTER["toolsets"].values() for tool in toolset["tools"]]
    declared = set().union(*(entry.keys() for entry in entries))
    assert {"risk", "executor", "parallelSafe", "timeoutMs", "sideEffects"} <= declared
    for spec in specs():
        data = spec.data()
        again = ToolSpec.from_data(json.loads(json.dumps(data)))
        assert again.data() == data and again == dataclasses.replace(spec, description=again.description)
        assert set(data["meta"]) <= declared, set(data["meta"]) - declared


def tol01_meta_never_sent():
    meta_words = {"risk", "sideEffects", "parallelSafe", "executor", "timeoutMs", "maxResultChars", "meta"}
    for profile in ("small", "full"):
        body = {"tools": [s.model_definition(InitCtx(profile=profile)) for s in specs() if s.meta.risk != "ui"]}
        serialised = json.dumps(body)
        assert not any(f'"{word}"' in serialised for word in meta_words), profile


# --- TOL-02 -----------------------------------------------------------------------------------------------


def _fuzz_args(rng: random.Random, spec: ToolSpec) -> dict:
    valid = yaml.safe_load((FIXTURES / f"{spec.name}.yaml").read_text())["valid_args"]
    choice = rng.random()
    if choice < 0.35:
        return copy.deepcopy(rng.choice(valid))
    if choice < 0.6:
        args = copy.deepcopy(rng.choice(valid))
        key = rng.choice(list(args))
        args[key] = rng.choice(
            [
                "",
                "x" * rng.randint(1, 3000),
                0,
                -1,
                None,
                [],
                {},
                "".join(rng.choice(string.printable) for _ in range(rng.randint(1, 40))),
            ]
        )
        return args
    return {rng.choice(["text", "a", "b", "expression", "quantity", "zzz"]): rng.choice(["x+1", 7, None, ["x"]])}


def tol02_envelope_always_valid(tmp_path: Path):
    async def scenario() -> None:
        executor = await _executor(tmp_path, worker_pool_size=4)
        rng = random.Random(7)
        all_specs = list(executor.registry.specs.values())
        calls = []
        for i in range(10_000):
            spec = rng.choice(all_specs)
            name = spec.name if rng.random() > 0.02 else "not_a_tool"
            calls.append(ToolCall(f"call_fuzz_{i}", name, _fuzz_args(rng, spec)))
        role = rng.choice(["solver", "checker", "coach", "engine"])
        results = []
        for start in range(0, len(calls), 200):
            results += await executor.run_batch(calls[start : start + 200], role, SESSION)
        assert len(results) == 10_000
        assert [r for r in results if envelope_errors(r)] == []
        assert {r["status"] for r in results} <= {"ok", "error", "cancelled", "partial"}
        await executor.supervisor.close()

    asyncio.run(scenario())


def tol02_crash_envelope(tmp_path: Path):
    async def scenario() -> None:
        executor = await _executor(tmp_path, [sys.executable, str(HARNESS)], extra=[_test_spec("crash")])
        executor.available = lambda spec, session: True  # the harness function is test-only
        result = await executor.run_one(ToolCall("call_crash_1", "crash", {}), "engine", SESSION)
        assert result["status"] == "error" and result["error"]["code"] == "worker_crashed"
        assert result["meta"]["action_taken"] is False and envelope_errors(result) == []
        await executor.supervisor.close()

    asyncio.run(scenario())


# --- TOL-03 -----------------------------------------------------------------------------------------------


def tol03_metadata_only_drives_engine():
    original = registry()["math_solve"]
    renamed = dataclasses.replace(original, name="zz_renamed_solver")
    calls_a = [ToolCall("call_a_1", "math_solve", {}), ToolCall("call_a_2", "units_convert", {})]
    calls_b = [ToolCall("call_a_1", "zz_renamed_solver", {}), ToolCall("call_a_2", "units_convert", {})]
    metas = {**{s.name: s.meta for s in specs()}, "zz_renamed_solver": renamed.meta}
    assert plan(calls_a, metas.get) == plan(calls_b, metas.get)
    grants = {"solver": ["compute:*"]}
    assert denial("solver", original, SESSION, grants) == denial("solver", renamed, SESSION, grants)
    assert renamed.meta.timeout_ms == original.meta.timeout_ms


def tol03_interactive_has_no_deadline():
    entry = {**register_entries(REGISTER, "S1")["ask_student"][1], "timeoutMs": 3000}
    spec = dataclasses.replace(registry()["ask_student"], meta=ToolMeta.from_register(entry))
    assert "an interactive tool has no deadline (timeoutMs must be null)" in spec_errors(spec)
    with pytest.raises(RegistrationError, match="ask_student"):
        build([*(s for s in specs() if s.name != "ask_student"), spec], REGISTER, "S1")


# --- TOL-04 -----------------------------------------------------------------------------------------------


def tol04_no_model_calls_ui(tmp_path: Path):
    async def scenario() -> None:
        executor = await _executor(tmp_path)
        for role in ("coach", "diagnoser", "solver", "checker", "reflector"):
            for tool in ("update_board", "ask_student"):
                result = await executor.run_one(ToolCall("call_ui_1", tool, {"ops": []}), role, SESSION)
                assert result["error"]["code"] == "policy_denied" and result["meta"]["action_taken"] is False
        await executor.supervisor.close()

    asyncio.run(scenario())


def tol04_no_egress_before_s5():
    for stage in ("S1", "S2", "S3", "S4"):
        everything = register_entries(REGISTER, stage, device=False)
        assert not [n for n, (_, e) in everything.items() if e["risk"] == "external"], stage
        egress = [n for n, (_, e) in everything.items() if e["risk"] == "egress"]
        assert egress in ([], ["python_run"]), (stage, egress)
    python_run = ToolSpec(
        "python_run",
        "compute",
        1,
        "S3",
        "x",
        {"type": "object"},
        ToolMeta.from_register(register_entries(REGISTER, "S3", device=False)["python_run"][1]),
    )
    grants = {"solver": ["compute:*"]}
    assert denial("solver", python_run, SESSION, grants) is not None
    online = dataclasses.replace(SESSION, enabled_online_features=("cloud_tier",))
    assert denial("solver", python_run, online, grants) is None


def tol04_all_core_tools_offline(tmp_path: Path):
    """Every shipped compute tool's golden cases pass through the executor in the sandbox (no network)."""
    from jana_tools import golden

    async def scenario() -> None:
        executor = await _executor(tmp_path)
        sets = golden.load()
        for spec in executor.registry.specs.values():
            if spec.meta.risk != "compute":
                continue
            assert spec.meta.uses_network is False
            subjects = spec.meta.subjects
            session = SESSION if SESSION.subject in subjects or "general" in subjects else dataclasses.replace(
                SESSION, subject=subjects[0])  # fmt: skip
            for case in sets[spec.name]["cases"][:15]:
                result = await executor.run_one(ToolCall("call_off_1", spec.name, case["args"]), "engine", session)
                assert result["status"] == "ok", (spec.name, case["id"], result.get("error"))
                assert golden.matches(result["data"]["value"], case["expect"]), (spec.name, case["id"])
        await executor.supervisor.close()

    asyncio.run(scenario())


# --- TOL-05 -----------------------------------------------------------------------------------------------


def tol05_malformed_schema_rejected():
    bad = dataclasses.replace(registry()["math_parse"], params={"type": "objekt"})
    with pytest.raises(RegistrationError, match=r"^math_parse: params is not a valid JSON Schema"):
        build([*(s for s in specs() if s.name != "math_parse"), bad], REGISTER, "S1")
    external = dataclasses.replace(registry()["math_parse"], params={"$ref": "https://example.invalid/x.json"})
    assert "uses $ref outside the document" in spec_errors(external)[0]
    reserved = dataclasses.replace(
        registry()["math_parse"], params={"type": "object", "properties": {"items": {"type": "string"}}}
    )
    assert "reserved argument names: items" in spec_errors(reserved)[0]


def tol05_registry_matches_register():
    assert set(registry().specs) == set(
        build_entries(REGISTER, "S1", early=OFFERED_EARLY)
    )  # with the early memory tools (TOL-23)
    extra = _test_spec("not_in_register")
    with pytest.raises(RegistrationError, match="not_in_register: in code but not in the tool register"):
        build([*specs(), extra], REGISTER, "S1", early=OFFERED_EARLY)
    with pytest.raises(RegistrationError, match="math_solve: in the tool register for S1 but not in code"):
        build([s for s in specs() if s.name != "math_solve"], REGISTER, "S1", early=OFFERED_EARLY)


def tol05_fixture_coverage():
    kinds = ("valid_args", "invalid_args", "description_lint", "repairs", "envelopes")
    for spec in specs():
        path = FIXTURES / f"{spec.name}.yaml"
        assert path.is_file(), spec.name
        data = yaml.safe_load(path.read_text())
        assert data["version"] == spec.version, f"{spec.name}: fixtures are for version {data['version']}"
        missing = [k for k in kinds if not data.get(k)]
        if spec.meta.risk == "compute" and not (REPO_ROOT / data.get("golden", "")).is_file():
            missing.append("golden")
        assert missing == [], (spec.name, missing)
        validator = __import__("jsonschema").Draft202012Validator(spec.params)
        assert all(validator.is_valid(a) for a in data["valid_args"]), spec.name
        assert not any(validator.is_valid(a) for a in data["invalid_args"]), spec.name
        assert set(data["envelopes"]) == set(ERROR_RULES), spec.name


def tol05_version_bump_enforced():
    assert snapshot_errors(snapshot(), committed()) == []
    version = committed()["math_solve"]["version"]
    changed = copy.deepcopy(snapshot())
    changed["math_solve"]["params_sha256"] = "0" * 64  # a default changed, version not bumped
    assert snapshot_errors(changed, committed()) == [
        f"math_solve: schema or defaults changed without a version bump (still {version})"
    ]
    bumped = copy.deepcopy(changed)
    bumped["math_solve"]["version"] = version + 1
    assert snapshot_errors(bumped, committed()) == [
        "math_solve: version bumped; update the snapshot (tools-snapshot --write)"
    ]


# --- TOL-10 -----------------------------------------------------------------------------------------------

META = {"call_id": "call_e_1", "tool": "math_solve", "tool_version": 1, "duration_ms": 3}


def tol10_error_states_effect():
    for spec in specs():
        envelopes = yaml.safe_load((FIXTURES / f"{spec.name}.yaml").read_text())["envelopes"]
        for code, expected in envelopes.items():
            result = error_result(code, "detail of what happened", META)
            assert result["error"]["message"].startswith(expected["first_clause"]), (spec.name, code)
            assert result["meta"]["action_taken"] == expected["first_clause"].startswith("The action completed")
            assert envelope_errors(result) == []


def tol10_no_internal_detail_leaks():
    detail = (
        'Traceback (most recent call last):\n  File "/Users/someone/projects/jana/x.py", line 3\n'
        "KeyError at C:\\Users\\someone\\x.py and /opt/app/lib/tool.py"
    )
    for code in ERROR_RULES:
        text = error_result(code, detail, META)["output"]
        assert "Traceback" not in text and "/Users/" not in text and "C:\\Users" not in text and "/opt/app" not in text
    long = error_result("execution_error", "x" * 5000, META)
    assert len(long["error"]["message"]) <= 2000 and long["error"]["message"].endswith(
        ERROR_RULES["execution_error"].next_step
    )


def tol10_error_codes_consistent():
    schema = json.loads((REPO_ROOT / "contracts/tools/tool-result.schema.json").read_text())
    in_schema = set(schema["$defs"]["ToolErrorCode"]["enum"])
    typescript = (REPO_ROOT / "packages/contracts-ts/src/generated/tools/tool_result.ts").read_text()
    union = re.search(r"export type ToolErrorCode =(.*?);", typescript, re.DOTALL).group(1)
    in_ts = set(re.findall(r'"([a-z_]+)"', union))
    assert in_schema == in_ts == set(ERROR_RULES)


# --- TOL-11 -----------------------------------------------------------------------------------------------


def tol11_barrier_splits_batch(tmp_path: Path):
    entries = register_entries(REGISTER, "S2")
    metas = {name: ToolMeta.from_register(entry) for name, (_, entry) in entries.items()}
    calls = [
        ToolCall(f"call_b_{i}", n, {})
        for i, n in enumerate(["math_solve", "units_convert", "memory_note", "math_evaluate"])
    ]
    assert plan(calls, metas.get) == [[0, 1], [2], [3]]

    async def scenario(tmp_path: Path) -> None:
        executor = await _executor(tmp_path)
        batch = [
            ToolCall("call_o_1", "math_evaluate", {"expression": "2+2"}),
            ToolCall("call_o_2", "math_parse", {"text": "x"}),
            ToolCall("call_o_3", "update_board", {"ops": []}),
            ToolCall("call_o_4", "units_convert", {"quantity": "1 km", "to": "m"}),
        ]
        results = await executor.run_batch(batch, "solver", SESSION)
        assert [r["meta"]["call_id"] for r in results] == ["call_o_1", "call_o_2", "call_o_3", "call_o_4"]
        await executor.supervisor.close()

    asyncio.run(scenario(tmp_path))


def tol11_deadline_enforced(tmp_path: Path):
    async def scenario() -> None:
        executor = await _executor(tmp_path, [sys.executable, str(HARNESS)], extra=[_test_spec("slow", timeout_ms=300)])
        executor.available = lambda spec, session: True
        result = await executor.run_one(ToolCall("call_s_1", "slow", {"seconds": 5}), "engine", SESSION)
        assert result["error"]["code"] == "timeout" and result["meta"]["action_taken"] is False
        assert len(executor.supervisor.restarts) == 1, "the worker is recycled"
        await executor.supervisor.close()

    asyncio.run(scenario())


def tol11_missed_heartbeats_cancel(tmp_path: Path):
    async def stalls(args, context):
        for _ in range(3):
            context.progress()
            await asyncio.sleep(0.05)
        await asyncio.sleep(10)  # stops reporting progress

    async def scenario() -> None:
        spec = _test_spec("long_host_job", timeout_ms=20000, executor="host", heartbeatMs=100)
        executor = ToolExecutor(Registry({spec.name: spec}), _settings(), SpillStore(tmp_path))
        executor.host_executors["long_host_job"] = stalls
        executor.grants = {"engine": ["compute:*"]}
        began = asyncio.get_running_loop().time()
        result = await executor.run_one(ToolCall("call_h_1", "long_host_job", {}), "engine", SESSION)
        elapsed = asyncio.get_running_loop().time() - began
        assert result["error"]["code"] == "timeout" and "progress" in result["error"]["message"]
        assert elapsed < 1.5, elapsed

    asyncio.run(scenario())


# --- TOL-12 -----------------------------------------------------------------------------------------------


def tol12_head_tail_spill(tmp_path: Path):
    async def big(args, context):
        return "".join(chr(65 + (i % 26)) for i in range(30_000))

    async def scenario() -> None:
        spec = _test_spec("big_output", executor="host")
        executor = ToolExecutor(Registry({spec.name: spec}), _settings(), SpillStore(tmp_path / "spill"))
        executor.host_executors["big_output"] = big
        executor.grants = {"engine": ["compute:*"]}
        small = dataclasses.replace(SESSION, profile="small")
        result = await executor.run_one(ToolCall("call_big_1", "big_output", {}), "engine", small)
        assert len(result["output"]) <= 8000
        assert "characters omitted; the full result is kept for the board" in result["output"]
        truncated = result["meta"]["truncated"]
        assert re.fullmatch(r"spill_[A-Za-z0-9]{8,64}", truncated["spill_ref"]) and "/" not in truncated["spill_ref"]
        full = executor.spill.resolve(small.session_id, truncated["spill_ref"])
        assert full is not None and len(full) == 30_000
        assert result["output"].startswith(full[:5000]) and result["output"].endswith(full[-1500:])

    asyncio.run(scenario())


def tol12_spill_deleted_with_session(tmp_path: Path):
    store = SpillStore(tmp_path)
    ref = store.save("ses_01JZ0000000000000000000001", "x" * 100)
    other = store.save("ses_01JZ0000000000000000000002", "y" * 100)
    store.delete_session("ses_01JZ0000000000000000000001")
    assert store.resolve("ses_01JZ0000000000000000000001", ref) is None
    assert store.resolve("ses_01JZ0000000000000000000002", other) == "y" * 100
    assert store.resolve("ses_01JZ0000000000000000000002", "../etc/passwd") is None


# --- ARC-21 -----------------------------------------------------------------------------------------------


def arc21_specialist_memory_write_denied(tmp_path: Path):
    """A specialist role cannot write memory, even if a grant were widened by mistake; the Reflector can."""
    import sqlite3

    database = tmp_path / "learner.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE notes (text TEXT)")

    async def note(args: dict, _context) -> dict:
        with sqlite3.connect(database) as db:
            db.execute("INSERT INTO notes VALUES (?)", (args["text"],))
        return {"saved": True}

    def rows() -> int:
        with sqlite3.connect(database) as db:
            return int(db.execute("SELECT COUNT(*) FROM notes").fetchone()[0])

    entry = register_entries(REGISTER, "S2")["memory_note"][1]
    spec = ToolSpec("memory_note", "memory", 1, "S2", "Save a note.", {"type": "object"}, ToolMeta.from_register(entry))

    async def scenario() -> None:
        for grants in (REGISTER["roleGrants"], {**REGISTER["roleGrants"], "solver": ["compute:*", "memory:*"]}):
            executor = ToolExecutor(Registry({"memory_note": spec}), _settings(), SpillStore(tmp_path / "spill"),
                                    grants=grants, host_executors={"memory_note": note})  # fmt: skip
            result = await executor.run_one(ToolCall("call_mem_1", "memory_note", {"text": "x"}), "solver", SESSION)
            assert result["error"]["code"] == "policy_denied" and result["meta"]["action_taken"] is False
            assert rows() == 0
        executor = ToolExecutor(Registry({"memory_note": spec}), _settings(), SpillStore(tmp_path / "spill"),
                                host_executors={"memory_note": note})  # fmt: skip
        result = await executor.run_one(ToolCall("call_mem_2", "memory_note", {"text": "x"}), "reflector", SESSION)
        assert result["status"] == "ok" and rows() == 1

    asyncio.run(scenario())
