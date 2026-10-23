"""M11.a: the hardware class over an install's life (PLT-08, PLT-09, PLT-29, ARC-31).

The benchmark runs for real against a loopback stand-in for llama-server that reports a chosen generation speed, with
every non-loopback connection refused; the probes are the synthetic reference-laptop fixtures of EVL-14. The
reference laptops' own repeated runs come from the device lab (`JANA_DEVLAB_RESULTS`): until the lab has them, the
part of a test that needs them skips, after everything that can run here has run. Synthetic machines and timings
only."""

from __future__ import annotations

import asyncio
import json
import os
import random
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.assembly import AppRuntime
from agent_core.engine.runtime_link import write_launch_plan
from agent_core.providers.gguf import read_header
from agent_core.providers.llama import LlamaServerProvider
from agent_core.router import hardware
from agent_core.router.fit import choose_context, estimate_bytes
from agent_core.router.probe import GB, Benchmark, Probe, choose_class
from jana_tools import REPO_ROOT
from jana_tools.fakes.llama_server import FakeLlamaServer
from jana_tools.fakes.models import install
from jana_tools.harness.egress import offline_run

FIXTURES = Path(__file__).parent / "fixtures" / "probe"
SETTINGS = Settings()
EPOCH = "0123456789abcdef"
LAB = os.environ.get("JANA_DEVLAB_RESULTS")  # a directory of <laptop>.json measurement files from the device lab


def _fixture(name: str) -> tuple[Probe, Benchmark | None, str]:
    data = json.loads((FIXTURES / f"{name}.json").read_text())
    assert data["synthetic"] is True
    bench = Benchmark(**data["benchmark"]) if data["benchmark"] else None
    return Probe.from_json(data["probe"]), bench, data["expected"]


def _answer(body: dict[str, Any]) -> dict[str, Any]:
    message = {"role": "assistant", "content": "OK"}
    return {"reply": {"model": body.get("model"), "choices": [{"message": message, "finish_reason": "stop"}]}}


def _lab_laptops() -> list[dict[str, Any]]:
    assert LAB is not None
    return [json.loads(p.read_text()) for p in sorted(Path(LAB).glob("*.json"))]


# --- PLT-08 -----------------------------------------------------------------------------------------------------


def plt08_benchmark_offline(tmp_path: Path) -> None:
    """With every non-loopback connection refused, the benchmark runs on the smallest planned model once the runtime
    is ready, records its result, and the next start's plan uses the measured class."""
    probe, _, _ = _fixture("mid")
    install(tmp_path)
    first = write_launch_plan(tmp_path, SETTINGS, False, EPOCH, probe=probe)
    assert first["hardware_reason"] == "predicted" and first["benchmark_due"] is True
    smallest = first["attempts"][-1]["model"]

    async def scenario() -> Any:
        fake = FakeLlamaServer([a["model"] for a in first["attempts"]], api_key="k", script=_answer)
        fake.timings["predicted_per_second"] = 12.0  # the mid class: at least 10 tokens/s, not 25
        async with fake:
            runtime = AppRuntime(SETTINGS, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path)
            runtime.plan, runtime.probe = first, probe
            assert await runtime.connect_runtime(fake.url, "k", first["model"])  # the touch generation (MDL-20)
            assert runtime.measuring is not None
            choice = await runtime.measuring
            await runtime.close()
            return choice, [r for r in fake.requests if "n_predict" in r]

    with offline_run() as seen:
        choice, probes = asyncio.run(scenario())
    assert seen.attempts == [], seen.attempts
    assert choice.hardware_class == "mid" and not choice.provisional
    [request] = probes
    assert request["model"] == smallest and request["cache_prompt"] is False
    record = hardware.load_record(tmp_path)
    assert record is not None and record.fingerprint == probe.fingerprint()
    assert record.benchmark is not None and record.benchmark["generation_tokens_s"] == 12.0
    again = write_launch_plan(tmp_path, SETTINGS, False, EPOCH, probe=probe)
    assert (again["hardware_class"], again["hardware_reason"], again["benchmark_due"]) == ("mid", "measured", False)


def _class_runs(probe: Probe, speed: float, runs: int, seed: int) -> list[str]:
    """The benchmark `runs` times through the shipped provider against a runtime whose speed varies by up to 10% from
    run to run, as a real laptop's does; the class each run picks."""
    rng = random.Random(seed)

    async def go() -> list[str]:
        picked = []
        fake = FakeLlamaServer(["qwen3-vl-8b"], api_key="k", script=_answer)
        async with fake:
            provider = LlamaServerProvider(fake.url, "k")
            for _ in range(runs):
                fake.timings["predicted_per_second"] = speed * rng.uniform(0.9, 1.1)
                bench = await hardware.run_benchmark(provider, "qwen3-vl-8b", SETTINGS)
                picked.append(choose_class(probe, bench, SETTINGS).hardware_class)
            await provider.close()
        return picked

    return asyncio.run(go())


def plt08_hardware_class_choice_reference_laptops() -> None:
    """Here: each synthetic reference laptop, benchmarked `benchmark_reference_runs` times at its recorded speed with
    run-to-run variation, lands in its class every time. On the lab's reference laptops: the same, from their own
    runs (`jana_tools classbench`)."""
    runs = SETTINGS.benchmark_reference_runs
    for seed, name in enumerate(("low", "mid", "high")):
        probe, bench, expected = _fixture(name)
        assert bench is not None
        picked = _class_runs(probe, bench.generation_tokens_s, runs, seed)
        assert picked == [expected] * runs, (name, picked)
    if LAB is None:
        pytest.skip("needs the reference laptops' class runs (device lab: jana_tools classbench on each laptop)")
    laptops = [lap for lap in _lab_laptops() if lap.get("hardware_class") in ("low", "mid", "high")]
    assert {lap["hardware_class"] for lap in laptops} == {"low", "mid", "high"}, "one reference laptop per class"
    for lap in laptops:
        picked = [r["hardware_class"] for r in lap.get("class_runs", [])]
        assert len(picked) >= runs, f"{lap['name']}: {len(picked)} class runs, fewer than {runs}"
        assert set(picked) == {lap["hardware_class"]}, (lap["name"], picked)
        assert lap.get("network") == "disabled", f"{lap['name']}: the benchmark runs offline"


# --- PLT-09 -----------------------------------------------------------------------------------------------------


def test_plt09_hardware_change_makes_the_benchmark_due(tmp_path: Path) -> None:
    probe, bench, _ = _fixture("mid")
    assert bench is not None
    record = hardware.HardwareRecord(probe.fingerprint(), probe.to_json(), dict(bench.__dict__), 1)
    hardware.save_record(tmp_path, record)
    same = hardware.current(probe, hardware.load_record(tmp_path), SETTINGS)
    assert (same.choice.hardware_class, same.choice.provisional, same.benchmark_due) == ("mid", False, False)
    # Free disk and free memory change all the time and are not a hardware change.
    busier = Probe.from_json({**probe.to_json(), "free_disk_bytes": 20 * GB, "available_bytes": 3 * GB})
    assert busier.fingerprint() == probe.fingerprint()
    # More memory, another GPU or another CPU is: the class is predicted again and the benchmark is due.
    for change in ({"ram_bytes": 32 * GB}, {"gpus": []}, {"cpu_model": "AMD Ryzen 5 5600U"}):
        changed = Probe.from_json({**probe.to_json(), **change})
        now = hardware.current(changed, hardware.load_record(tmp_path), SETTINGS)
        assert now.hardware_changed and now.benchmark_due and now.choice.provisional, change
    # Below the minimum laptop's hardware checks no model runs, so nothing is due.
    below, _, _ = _fixture("below_minimum")
    assert not hardware.current(below, None, SETTINGS).benchmark_due


def test_plt09_class_choice_rules(tmp_path: Path) -> None:
    probe, bench, _ = _fixture("mid")
    assert bench is not None
    install(tmp_path)
    hardware.save_record(tmp_path, hardware.HardwareRecord(probe.fingerprint(), probe.to_json(), dict(bench.__dict__)))
    # Lower is the student's to choose; from low the only lower class is content-only (D58).
    assert hardware.choose_override(tmp_path, probe, "low", False, SETTINGS) == "allowed"
    chosen = hardware.current(probe, hardware.load_record(tmp_path), SETTINGS)
    assert chosen.choice.hardware_class == "low" and chosen.measured.hardware_class == "mid"
    plan = write_launch_plan(tmp_path, SETTINGS, False, EPOCH, probe=probe)
    assert (plan["hardware_class"], plan["hardware_reason"]) == ("low", "chosen")
    # Higher than measured needs the warning confirmed; unconfirmed, nothing is recorded.
    assert hardware.choose_override(tmp_path, probe, "high", False, SETTINGS) == "needs_confirmation"
    assert hardware.current(probe, hardware.load_record(tmp_path), SETTINGS).choice.hardware_class == "low"
    assert hardware.choose_override(tmp_path, probe, "high", True, SETTINGS) == "needs_confirmation"
    assert hardware.current(probe, hardware.load_record(tmp_path), SETTINGS).choice.hardware_class == "high"
    # Clearing the choice returns to the measured class.
    assert hardware.choose_override(tmp_path, probe, None, False, SETTINGS) == "allowed"
    assert hardware.current(probe, hardware.load_record(tmp_path), SETTINGS).choice.hardware_class == "mid"
    # Nothing lifts a machine below the minimum laptop's hardware checks.
    below, _, _ = _fixture("below_minimum")
    assert hardware.choose_override(tmp_path / "below", below, "low", True, SETTINGS) == "refused"
    # Too slow in the benchmark is different: the student may insist, after the warning.
    low, _, _ = _fixture("low")
    slow = choose_class(low, Benchmark("m", 30.0, 3.0, 9.0), SETTINGS)
    assert slow.hardware_class == "content_only"
    assert hardware.override_check(slow, "low") == "needs_confirmation"


def _step(n: int, seconds: float) -> dict[str, Any]:
    return {"kind": "turn", "mode": "guided", "status": "complete", "duration_ms": int(seconds * 1000), "n": n}


def test_plt09_suggests_a_lower_class_when_steps_run_over() -> None:
    budget = SETTINGS.guided_step_budget_s[1]  # mid
    count = 20
    over = int(count * SETTINGS.class_suggest_lower_share)  # exactly the share: not more than it
    rows = [_step(n, budget + 5 if n < over else budget - 5) for n in range(count)]
    assert not hardware.suggest_lower(rows, "mid", SETTINGS)
    rows[over] = _step(over, budget + 5)
    assert hardware.suggest_lower(rows, "mid", SETTINGS)
    assert not hardware.suggest_lower(rows[: SETTINGS.health_min_turns - 1], "mid", SETTINGS)  # too few to say
    assert not hardware.suggest_lower(rows, "low", SETTINGS)  # from low the only lower class loses the tutor


def test_plt09_health_panel_suggests_a_lower_class(tmp_path: Path) -> None:
    """The suggestion reaches `GET /v1/health` as the `class_lower` condition, from the committed turn traces."""
    from agent_core.trace.store import TraceStore
    from test_m11e_health import _turn

    runtime = AppRuntime(SETTINGS, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path)
    runtime.read_battery = lambda: None
    runtime.plan = {"hardware_class": "mid"}
    runtime.traces = TraceStore(tmp_path / "traces.db", max_bytes=10**8, retention_days=14)
    budget_ms = int(SETTINGS.guided_step_budget_s[1] * 1000)
    try:
        for n in range(10):  # 3 of 10 steps over budget: more than the share, while the median stays within it
            runtime.traces.submit(_turn(n, budget_ms + 5_000 if n < 3 else budget_ms - 5_000))
        runtime.traces.flush()
        found = runtime.health_components()
        assert found["class_lower"] == "degraded" and found["speed"] == "ok"
    finally:
        runtime.traces.close()


# --- PLT-29 -----------------------------------------------------------------------------------------------------


def plt29_below_minimum_notice(tmp_path: Path) -> None:
    """A 4 GB fixture completes setup (the adult PIN and a profile), lands in the content-only class, and the core
    reports which check failed with the figures the unsupported-offline copy names (the copy itself:
    `plt29_below_minimum_notice` in packages/ui)."""
    from api_harness import start_core, stop_core

    probe, _, _ = _fixture("below_minimum")

    async def scenario() -> dict[str, Any]:
        r = await start_core(tmp_path / "data", worker=False)
        try:
            r.runtime.probe, r.runtime.epoch = probe, r.core.epoch
            r.runtime.plan = write_launch_plan(tmp_path / "data", SETTINGS, False, r.core.epoch, probe=probe)
            made = await r.client.post(r.base + "/v1/profiles", headers=r.headers(True),
                                       json={"display_name": "Ama", "avatar": "a1", "age_band": "13_15",
                                             "level": "O", "subjects": ["physics"]})  # fmt: skip
            assert made.status_code in (200, 201), made.text
            models = (await r.get("/v1/models")).json()
            problems = contract_errors("api/commands#/$defs/ModelCatalogue", models)
            plain = (await r.get("/v1/models")).json()
            return {"models": models, "problems": problems, "plain": plain, "plan": r.runtime.plan}
        finally:
            await stop_core(r)

    out = asyncio.run(scenario())
    assert out["problems"] == [], out["problems"]
    report = out["models"]["hardware"]
    assert report["hardware_class"] == "content_only" and report["basis"] == "below_minimum_ram"
    assert report["shortfalls"] == [{"check": "ram", "have": 4, "need": 8.0, "unit": "GB"}]
    assert report["tutor_path"] == "none" and report["benchmark_due"] is False
    assert out["models"]["recommended"]["reason_key"] == "hardware_class.content_only.below_minimum_ram"
    # The bundled contract carries the hardware report (D76), so the plain answer has the figures too and validates.
    assert out["plain"]["hardware"]["shortfalls"] == report["shortfalls"]
    assert contract_errors("api/commands#/$defs/ModelCatalogue", out["plain"]) == []
    assert out["plain"]["recommended"]["reason_key"] == "hardware_class.content_only.below_minimum_ram"
    # No model manifest is needed for the class: setup finished with no tutor model and no runtime planned.
    assert out["plan"]["model"] is None


SAFE = "Which quantities does the question give you, and which one does it ask for?"


def _plan_script() -> dict[str, list[Any]]:
    from engine_harness import checker_steps, solver_steps, tutor

    return {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)]}


def plt29_below_minimum_online_or_lan_else_content_only(tmp_path: Path) -> None:
    """On the 4 GB fixture: with the online tier on, the tutor runs there with its egress notices and nothing on this
    computer; with a school server it runs there; with neither, a turn is refused before any model is called while
    lessons' and practice's deterministic parts, packs and progress still answer."""
    from agent_core.engine.marking import mark_choice
    from agent_core.providers.scripted import ScriptedProvider
    from api_harness import ask, scripted, start_core, stop_core
    from engine_harness import STATEMENT, close, make_engine

    assert hardware.tutor_path("content_only", True, False) == "online"
    assert hardware.tutor_path("content_only", True, True) == "school_server"
    assert hardware.tutor_path("content_only", False, False) == "none"
    assert hardware.tutor_path("low", False, False) == "local"

    def enable(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True

    async def online() -> tuple[Any, Any, Any, Any]:
        cloud = ScriptedProvider(_plan_script(), kind="cloud")
        engine, local = await make_engine(tmp_path / "online", {}, overrides=enable, cloud=cloud,
                                          hardware_class="cloud", device_class="content_only")  # fmt: skip
        engine.deps.router.cloud_on = lambda role: True  # type: ignore[method-assign]
        result = await engine.start_problem(STATEMENT)
        await close(engine)
        return engine, local, cloud, result

    engine, local, cloud, result = asyncio.run(online())
    assert local.requests == [], "nothing runs on a computer below the minimum laptop"
    assert {r.get("_role") for r in cloud.requests} >= {"solver", "coach"}
    events = [f["event"] for f in engine.events.frames]
    notices = [e for e in events if e["type"] == "egress.notice"]
    assert notices and {n["state"] for n in notices} == {"started", "ended"}
    assert all(n["feature"] == "cloud_tier" for n in notices)
    assert result.status == "complete", result
    assert engine.events.validate  # every event above was checked against the events contract as it was emitted

    async def school_server() -> tuple[Any, Any]:
        engine, lan = await make_engine(tmp_path / "lan", _plan_script(), device_class="content_only",
                                        local_kind="school_server")  # fmt: skip
        result = await engine.start_problem(STATEMENT)
        await close(engine)
        return lan, result

    lan, lan_result = asyncio.run(school_server())
    assert lan_result.status == "complete" and {r.get("_role") for r in lan.requests} >= {"solver", "coach"}

    # Neither: the same machine with no online tier and no school server.
    probe, _, _ = _fixture("below_minimum")
    spy = scripted({"coach": [], "solver": [], "checker": []})

    async def neither() -> dict[str, Any]:
        r = await start_core(tmp_path / "data", provider=spy, worker=False)
        try:
            r.runtime.probe, r.runtime.epoch = probe, r.core.epoch
            r.runtime.plan = write_launch_plan(tmp_path / "data", SETTINGS, False, r.core.epoch, probe=probe)
            session = await r.session()
            turn = await r.post(f"/v1/sessions/{session}/turns", ask(STATEMENT))
            packs = await r.get("/v1/packs")
            health = (await r.get("/v1/health")).json()
            return {"turn": turn, "packs": packs.status_code, "health": health}
        finally:
            await stop_core(r)

    out = asyncio.run(neither())
    assert out["turn"].status_code == 503 and out["turn"].json()["error"]["code"] == "model_unavailable"
    assert spy.requests == [], "no model call is attempted"
    assert out["packs"] == 200
    # Practice's deterministic marking needs no model.
    part = {"marks": 1, "answer": {"options": [{"id": "a", "correct": False}, {"id": "b", "correct": True}]}}
    assert mark_choice(part, "b").outcome == "correct" and mark_choice(part, "a").outcome == "incorrect"


# --- ARC-31 -----------------------------------------------------------------------------------------------------


def test_arc31_context_sized_from_free_memory(tmp_path: Path) -> None:
    """The model and its fit rest on installed memory (MDL-17); the context rung is sized from what is free now."""
    manifest = install(tmp_path)
    info = read_header(tmp_path / "models" / manifest["models"][0]["file"]["name"])
    ladder, minimum = [4096, 6144, 8192, 12288, 16384], 4096
    roomy = choose_context(info, 16 * GB, "high", ladder, 2, minimum, SETTINGS)
    assert roomy == 16384
    tight = estimate_bytes(info, 8192, SETTINGS) + 1  # free memory holds 8,192 tokens of KV cache but not 12,288
    assert choose_context(info, 16 * GB, "high", ladder, 2, minimum, SETTINGS, available_bytes=tight) == 8192
    # Even less free than the smallest rung needs: the smallest rung that fits installed memory, never no model.
    assert choose_context(info, 16 * GB, "high", ladder, 2, minimum, SETTINGS, available_bytes=GB // 4) == minimum
    probe, _, _ = _fixture("high")
    busy = Probe.from_json({**probe.to_json(), "available_bytes": tight})
    plan = write_launch_plan(tmp_path, SETTINGS, False, EPOCH, probe=busy)
    assert plan["attempts"][0]["context"] == 8192


# --- PLT-04 (the core's side; the shell's selection and fallback are plt04_* in apps/desktop/src-tauri) ----------


def test_plt04_fallback_reason_reaches_the_health_panel(tmp_path: Path) -> None:
    """The build the shell runs and why the first choice was set aside reach `GET /v1/health` (a `runtime_variant`
    condition) and the hardware report the panel shows; a file another core process's shell wrote is ignored."""
    probe, _, _ = _fixture("low")
    runtime = AppRuntime(SETTINGS, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path)
    runtime.probe, runtime.epoch = probe, EPOCH
    assert "runtime_variant" not in runtime.health_components() and runtime.hardware_report()["runtime"] is None
    fallback = {"variant": "vulkan", "reason": "crashed (segmentation fault) during its first generation"}
    record = {"epoch": EPOCH, "variant": "cpu-avx2", "rejected": [], "fallbacks": [fallback]}
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "variant.json").write_text(json.dumps(record))
    assert runtime.health_components()["runtime_variant"] == "degraded"
    report = runtime.hardware_report()
    assert report["runtime"] == {"variant": "cpu-avx2", "fallbacks": [fallback]}
    assert contract_errors("api/commands#/$defs/HardwareReport", report) == []
    (tmp_path / "runtime" / "variant.json").write_text(json.dumps({**record, "fallbacks": []}))
    assert runtime.health_components()["runtime_variant"] == "ok"
    (tmp_path / "runtime" / "variant.json").write_text(json.dumps({**record, "epoch": "fedcba9876543210"}))
    assert "runtime_variant" not in runtime.health_components()
