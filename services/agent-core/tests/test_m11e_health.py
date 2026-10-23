"""M11.e: the core's side of the health panel (OBS-15) and the runtime's priorities in the launch plan (ARC-31).

Each condition the panel names is seeded for real where the machine allows it (a worker started without its sandbox,
the SEC-17 file key store, synthetic turn traces, a disk-usage reading under the DAT-13 floor) and read back through
`GET /v1/health` and `GET /v1/models`, each answer valid against its contract. The client's lines and actions for
these components are `obs15_health_panel_conditions` in packages/ui. Synthetic models, traces and timings only."""

from __future__ import annotations

import asyncio
import collections
import json
import shutil
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.health import speed
from agent_core.engine.runtime_link import RuntimeLink, class_reason, write_launch_plan
from agent_core.router.probe import Probe, choose_class
from agent_core.store.keystore import ShellKeyStore
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from api_harness import Running, start_core, stop_core
from jana_tools.fakes.models import install

PROBES = Path(__file__).parent / "fixtures" / "probe"
EPOCH = "0123456789abcdef"
# A generous handshake wait: the worker starts cold, and the machine may be busy.
SETTINGS = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0)


def _probe(name: str) -> Probe:
    return Probe.from_json(json.loads((PROBES / f"{name}.json").read_text())["probe"])


def _turn(n: int, duration_ms: int, first_call_ms: int = 200, ttft_ms: int = 1000, status: str = "complete",
          mode: str = "guided") -> dict[str, Any]:  # fmt: skip
    """A synthetic committed turn trace with only the fields the speed condition reads."""
    return {"trace_id": f"trace-{n:04d}", "kind": "turn", "session_ref": "ses_synthetic", "profile_ref": "",
            "mode": mode, "status": status, "duration_ms": duration_ms,
            "phases": [{"phase": "prepare", "iteration": 0, "start_offset_ms": 0, "duration_ms": first_call_ms},
                       {"phase": "call", "iteration": 0, "start_offset_ms": first_call_ms, "duration_ms": 500}],
            "model_calls": [{"role": "coach", "latency": {"total_ms": 900, "ttft_ms": ttft_ms}}]}  # fmt: skip


def _run(scenario: Any, tmp_path: Path, worker: bool = False) -> Any:
    async def go() -> Any:
        r = await start_core(tmp_path / "data", settings=SETTINGS, worker=worker)
        try:
            return await scenario(r)
        finally:
            await stop_core(r)

    return asyncio.run(go())


async def _health(r: Running) -> dict[str, Any]:
    answer = await r.get("/v1/health")
    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert contract_errors("api/commands#/$defs/Health", body) == [], body
    return dict(body["components"])


def test_obs15_core_reports_seeded_conditions(tmp_path: Path, monkeypatch: Any) -> None:
    install(tmp_path / "device")
    plan = write_launch_plan(tmp_path / "device", SETTINGS, False, EPOCH, probe=_probe("low"))
    assert plan["hardware_class"] == "low" and plan["hardware_reason"] == "predicted"
    assert plan["model_pack"] == {"pack_id": "models.synthetic", "version": "0.1.0"}
    usage = collections.namedtuple("usage", "total used free")
    real_usage = shutil.disk_usage

    async def scenario(r: Running) -> dict[str, Any]:
        runtime = r.runtime
        runtime.plan = plan
        runtime.link = RuntimeLink(SETTINGS, plan)
        runtime.keys = ShellKeyStore("user_file", {}, lambda message: None)  # the shell's SEC-17 file fallback
        out: dict[str, Any] = {}

        # Healthy apart from the keychain: the planned model serves, the worker is sandboxed, steps are in budget.
        runtime.link.attaching("synthetic-large")  # the shell's endpoint for the plan's first model
        runtime.model = "synthetic-large"
        assert runtime.traces is not None
        for n in range(SETTINGS.health_min_turns):
            runtime.traces.submit(_turn(n, duration_ms=12_000))
        runtime.traces.flush()
        out["healthy"] = await _health(r)
        models = await r.get("/v1/models")
        assert models.status_code == 200, models.text
        out["models"] = models.json()

        # Runtime fallback: the shell's restarts were spent and the next smaller model now serves (MDL-19).
        runtime.link.attaching("synthetic-small")
        runtime.model = "synthetic-small"
        # Slow steps: the window's median guided step is over the low class's budget.
        for n in range(SETTINGS.health_min_turns, 3 * SETTINGS.health_min_turns):
            runtime.traces.submit(_turn(n, duration_ms=int(SETTINGS.guided_step_budget_s[0] * 1000) + 15_000))
        runtime.traces.flush()
        # Sandbox unavailable: a worker that started without its OS sandbox (SEC-06).
        runtime.supervisor = WorkerSupervisor(process_factory(SETTINGS, scratch_root=tmp_path / "scratch",
                                                              sandbox=False), SETTINGS)  # fmt: skip
        await runtime.supervisor.start()
        # Low disk: free space under the DAT-13 floor.
        low = int(SETTINGS.disk_low_free_mb - 100) * 1024**2
        monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 10**12 - low, low))
        out["seeded"] = await _health(r)
        monkeypatch.setattr(shutil, "disk_usage", real_usage)
        out["models_fallback"] = (await r.get("/v1/models")).json()
        return out

    out = _run(scenario, tmp_path)
    healthy, seeded = out["healthy"], out["seeded"]
    assert healthy["runtime_fallback"] == "ok" and healthy["speed"] == "ok"
    assert healthy["keychain"] == "degraded"  # the file fallback (SEC-17): itself a condition the panel names
    assert "storage" not in healthy
    assert seeded["runtime_fallback"] == "degraded"
    assert seeded["sandbox"] == "degraded" and seeded["worker"] == "ok"
    assert seeded["keychain"] == "degraded"
    assert seeded["speed"] == "degraded"
    assert seeded["storage"] == "degraded" and seeded["capture"] == "down"

    # GET /v1/models: valid, with the hardware class and why, the model pack's version and the model that serves.
    for body in (out["models"], out["models_fallback"]):
        assert contract_errors("api/commands#/$defs/ModelCatalogue", body) == [], body
    models = out["models"]
    assert models["recommended"] == {"fast": "synthetic-large", "strong": "synthetic-large",
                                     "reason_key": "hardware_class.low.predicted"}  # fmt: skip
    assert models["assignment"] == {"fast": "synthetic-large", "strong": "synthetic-large"}
    assert {m["model_id"]: m["pack_version"] for m in models["installed"]} == {"synthetic-large": "0.1.0",
                                                                              "synthetic-small": "0.1.0"}  # fmt: skip
    assert out["models_fallback"]["assignment"]["fast"] == "synthetic-small"


def test_obs15_keychain_status_follows_the_store(tmp_path: Path) -> None:
    """The keychain line goes away once the shell keeps the secrets in the OS keychain (the bridge, D97)."""

    def keychain() -> ShellKeyStore:
        return ShellKeyStore("os_keychain", {}, lambda message: None)

    async def scenario(r: Running) -> tuple[str, str]:
        before = (await _health(r))["keychain"]
        r.runtime.keys = keychain()
        return before, (await _health(r))["keychain"]

    assert _run(scenario, tmp_path) == ("degraded", "ok")


def _rows(tmp_path: Path, records: list[dict[str, Any]], name: str) -> list[dict[str, Any]]:
    """The timing rows the health panel reads, through a real trace store."""
    from agent_core.trace.store import TraceStore

    store = TraceStore(tmp_path / f"{name}.db", max_bytes=10**8, retention_days=14)
    for record in records:
        store.submit(record)
    store.flush()
    rows = store.timings_since(0)
    store.close()
    return rows


def test_obs15_speed_needs_enough_recent_guided_turns(tmp_path: Path) -> None:
    settings = Settings()
    budget_ms = int(settings.guided_step_budget_s[0] * 1000)

    def judged(records: list[dict[str, Any]], hardware_class: str | None, name: str) -> Any:
        return speed(_rows(tmp_path, records, name), hardware_class, settings)

    slow = [_turn(n, budget_ms + 5_000) for n in range(settings.health_min_turns)]
    # Too few turns to judge: not named slow.
    assert not judged(slow[: settings.health_min_turns - 1], "low", "few").slow
    assert judged(slow, "low", "slow").slow
    assert judged(slow, "mid", "slow_mid").slow  # a faster class has a tighter budget
    # Interrupted turns, other modes and other kinds never count.
    noise = [_turn(100 + n, budget_ms * 3, status="interrupted") for n in range(10)]
    noise += [_turn(200 + n, budget_ms * 3, mode="solution") for n in range(10)]
    fast = [_turn(n, budget_ms // 2) for n in range(settings.health_min_turns)]
    within = judged(fast + noise, "low", "noise")
    assert within.turns == settings.health_min_turns and not within.slow
    # First words alone over the class budget is slow too: the first call's start plus the Coach's first token.
    late_ms = int(settings.coach_first_text_budget_s[0] * 1000) + 2_000
    late = judged([_turn(n, budget_ms // 2, ttft_ms=late_ms) for n in range(settings.health_min_turns)], "low", "late")
    assert late.slow and late.first_words_s == (200 + late_ms) / 1000
    # Content-only and an unknown class have no budget, so no speed line.
    assert speed([], "content_only", settings) is None and speed([], None, settings) is None


def test_obs15_class_reason_keys() -> None:
    settings = Settings()
    assert class_reason(choose_class(_probe("low"), None, settings)) == "predicted"
    assert class_reason(choose_class(_probe("below_minimum"), None, settings)).startswith("below_minimum_")


def test_arc31_plan_carries_runtime_priority(tmp_path: Path) -> None:
    """The shell reads the runtime's priority from the plan, like its restart policy (ARC-31); the 2 GB of memory
    left free is the fit's headroom (MDL-17), already in the router configuration."""
    install(tmp_path)
    settings = Settings(runtime_niceness=7, runtime_reserved_cores=2)
    plan = write_launch_plan(tmp_path, settings, False, EPOCH, probe=_probe("low"))
    assert plan["priority"] == {"niceness": 7, "reserved_cores": 2}
    empty = write_launch_plan(tmp_path / "empty", Settings(), False, EPOCH)
    assert empty["priority"] == {"niceness": Settings().runtime_niceness,
                                 "reserved_cores": Settings().runtime_reserved_cores}  # fmt: skip
    import yaml
    from agent_core.engine.runtime_link import ROUTER_YAML

    assert yaml.safe_load(ROUTER_YAML.read_text())["local"]["memory_headroom_gb"] == 2
