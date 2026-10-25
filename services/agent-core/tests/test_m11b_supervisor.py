"""M11.b: the core's side of the runtime the shell supervises (ARC-02, MDL-19): the launch plan, the restart policy as
the core sees it, the single retry from Prepare and an API that keeps answering while the runtime is down. The
runtime is the loopback FakeLlamaServer; models and probes are synthetic. The shell's side is apps/desktop/src-tauri
(tests/runtime.rs)."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Callable
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.assembly import AppRuntime
from agent_core.engine.runtime_link import RuntimeLink, plan_path, write_launch_plan
from agent_core.engine.state import Plan, PlanStep, Problem, SessionState
from agent_core.router.probe import Probe
from api_harness import STATEMENT, ask, start_core, stop_core
from engine_harness import reply, tutor
from jana_tools import REPO_ROOT
from jana_tools.fakes import FakeLlamaServer
from jana_tools.fakes.models import install

MODEL = "qwen3-vl-8b"
KEYS = ("k" * 64, "q" * 64)
SETTINGS = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), runtime_liveness_interval_s=0.05,
                    runtime_restart_wait_s=10.0)  # fmt: skip
PROBES = Path(__file__).parent / "fixtures" / "probe"
RESTART = {"backoff_s": [1.0, 2.0, 4.0], "max_restarts": 3, "window_s": 300.0}
COACH = tutor("Write the equation first.", board=[{"op": "add_step", "latex": "v^2 = u^2 + 2as",
                                                   "reason": "links u, v, a and s", "status": "draft",
                                                   "owner": "tutor"}])  # fmt: skip


def _plan(*models: str) -> dict[str, Any]:
    return {"plan_version": 1, "epoch": "0123456789abcdef", "model": models[0], "reason": None,
            "attempts": [{"model": m, "context": 6144, "args": []} for m in models], "restart": RESTART}  # fmt: skip


def _probe(name: str) -> Probe:
    return Probe.from_json(json.loads((PROBES / f"{name}.json").read_text())["probe"])


def _preset(core: Any, session_id: str) -> None:
    """An open problem with a verified plan, so the turn needs only the Coach."""
    state = core.sessions[session_id].engine_state
    state.problem = Problem("prb_f", STATEMENT, "prb_f#statement")
    state.plan = Plan([PlanStep(1, "s = 10", "10", "m", "chk_F01")], "10", "m", "chk_F01")
    state.check_values["chk_F01"] = [Fraction(10)]


async def _until(condition: Callable[[], bool], timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out"
        await asyncio.sleep(0.01)


def _events(core: Any, session_id: str) -> list[dict[str, Any]]:
    ring = core.pool.ring(session_id)
    return [json.loads(data.decode().split("data: ", 1)[1])["event"] for _, data in ring.entries]


def _answers(coach: dict[str, Any]) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """A runtime that passes the touch generation (8 tokens) and answers every Coach call with `coach`."""
    return lambda body: reply("OK") if body.get("max_tokens") == 8 else coach


async def _crash_mid_turn(tmp_path: Path, coach: dict[str, Any]) -> dict[str, Any]:
    """A turn whose Coach call is in flight when the runtime dies; while it is down the API is polled; then the
    shell's restart attaches a new runtime with a new key, which answers the Coach with `coach`."""
    first = await FakeLlamaServer([MODEL], api_key=KEYS[0], script=[reply("OK"), {"stall_s": 0.3, "drop": True}]
                                  ).start()  # fmt: skip
    r = await start_core(tmp_path, worker=False, settings=SETTINGS)
    link = RuntimeLink(SETTINGS, _plan(MODEL), alive=r.runtime.runtime_alive)
    r.runtime.link = link

    def report(readiness: str, component: str) -> None:  # as the sidecar reports it (agent_core.api.__main__)
        r.core.readiness, r.core.components["runtime"] = readiness, component

    link.on_change = report
    link.start()
    second: FakeLlamaServer | None = None
    try:
        assert await r.runtime.connect_runtime(first.url, KEYS[0], MODEL)
        sid = await r.session()
        _preset(r.core, sid)
        await r.post(f"/v1/sessions/{sid}/turns", ask("what next", "answer"))
        await _until(lambda: len(first.requests) >= 2)  # the Coach's call is in flight
        await first.close()  # the runtime dies mid-generation: the call drops and nothing listens any more
        await _until(lambda: link.state == "restarting")
        latencies = []
        for _ in range(20):
            for path in ("/v1/health", f"/v1/sessions/{sid}/snapshot"):
                started = time.monotonic()
                answer = await r.get(path)
                latencies.append((time.monotonic() - started) * 1000)
                assert answer.status_code == 200, answer.text
        health_down = (await r.get("/v1/health")).json()
        second = await FakeLlamaServer([MODEL], api_key=KEYS[1], script=_answers(coach)).start()
        await r.runtime.connect_runtime(second.url, KEYS[1], MODEL)  # the shell's new endpoint
        await r.wait_idle(sid)
        r.runtime.traces.flush() if r.runtime.traces else None
        traces = r.runtime.traces.records() if r.runtime.traces else []
        return {"events": _events(r.core, sid), "latencies": latencies, "health_down": health_down,
                "health_after": (await r.get("/v1/health")).json(), "second": list(second.requests),
                "phases": [p for t in traces for p in t.get("phases", [])]}  # fmt: skip
    finally:
        await stop_core(r)
        if second is not None:
            await second.close()


def mdl19_crash_restart(tmp_path: Path) -> None:
    out = asyncio.run(_crash_mid_turn(tmp_path / "once", COACH))
    events = out["events"]
    (end,) = [e for e in events if e["type"] == "turn.end"]
    assert end["status"] == "complete", end
    # The turn waited for the runtime (queued), then went again from Prepare on the restarted runtime.
    assert [e["phase"] for e in events if e["type"] == "status"].count("queued") == 1
    assert any(e.get("label_key") == "status.runtime_restarting" for e in events if e["type"] == "status")
    steps = [(p["phase"], p["iteration"], p.get("verdict")) for p in out["phases"]]
    assert steps[:3] == [("prepare", 0, "continue"), ("call", 0, "loop"), ("prepare", 1, "continue")], steps
    coach_calls = [b for b in out["second"] if b.get("max_tokens") != 8]
    assert coach_calls, "the retried call reached the restarted runtime"
    assert out["health_after"]["readiness"] == "ready" and out["health_after"]["components"]["runtime"] == "ok"

    # Once only: when the restarted runtime also drops the call, the turn ends `error`.
    out = asyncio.run(_crash_mid_turn(tmp_path / "twice", {"drop": True}))
    (end,) = [e for e in out["events"] if e["type"] == "turn.end"]
    assert end["status"] == "error"
    assert [e["phase"] for e in out["events"] if e["type"] == "status"].count("queued") == 1


def arc02_ui_responsive_during_runtime_crash(tmp_path: Path) -> None:
    """At the API level: while the runtime is killed mid-generation and restarting, the core keeps answering the
    client's reads within the input-to-paint budget, and reports the runtime as restarting. The webview's own paint
    time is measured in the device lab."""
    out = asyncio.run(_crash_mid_turn(tmp_path, COACH))
    budget = Settings().ui_input_paint_ms
    slowest = sorted(out["latencies"])[-1]
    assert slowest < budget, f"slowest read {slowest:.0f} ms"
    assert out["health_down"]["readiness"] == "model_loading"
    assert out["health_down"]["components"]["runtime"] == "starting"
    assert contract_errors("api/commands#/$defs/Health", out["health_down"]) == []


def mdl19_restart_limit(tmp_path: Path) -> None:
    # The plan lists the largest verified model that fits and the next smaller one, with explicit flags.
    install(tmp_path)
    plan = write_launch_plan(tmp_path, Settings(), False, "0123456789abcdef", probe=_probe("low"))
    assert json.loads(plan_path(tmp_path).read_text()) == plan
    assert plan["model"] == "synthetic-large" and plan["hardware_class"] == "low"
    assert [a["model"] for a in plan["attempts"]] == ["synthetic-large", "synthetic-small"]
    assert plan["restart"] == RESTART
    args = plan["attempts"][0]["args"]
    assert "--port" not in args and "--api-key-file" not in args
    # The agent context per request, in a unified pool with room for the pinned role prefixes (D128, MDL-22).
    assert args[args.index("--kv-unified-per-slot") + 1] == "6144" and args[args.index("--ctx-size") + 1] == "8192"
    assert args[args.index("--parallel") + 1] == "4" and args[args.index("--cache-ram") + 1] == "0"
    assert "--kv-unified" in args and "--no-cache-idle-slots" in args and "--slot-save-path" in args
    assert "--no-context-shift" in args and args[args.index("--models-dir") + 1] == plan["models_dir"]
    below = write_launch_plan(tmp_path, Settings(), False, "0123456789abcdef", probe=_probe("below_minimum"))
    assert below["model"] is None and below["reason"] == "content_only_class"
    assert write_launch_plan(tmp_path / "empty", Settings(), False, "0123456789abcdef")["reason"] == "no_model_manifest"

    # The core applies the same policy to the losses it sees: the fourth loss inside the window waits for the smaller
    # model; the smaller model's fourth loss is content-only (degraded, runtime down).
    clock = [0.0]
    changes: list[tuple[str, str]] = []
    link = RuntimeLink(Settings(), plan, on_change=lambda *c: changes.append(c), clock=lambda: clock[0])

    def launch(model: str) -> int:
        generation = link.attaching(model)
        link.attached(generation, True)
        return generation

    for model in ("synthetic-large", "synthetic-small"):
        generation = launch(model)
        for _ in range(3):
            clock[0] += 10
            link.lost(generation)
            assert link.readiness() == ("model_loading", "starting")
            generation = launch(model)
        clock[0] += 10
        link.lost(generation)
    assert link.state == "gave_up" and link.readiness() == ("degraded", "down")
    assert changes[-1] == ("degraded", "down")
    generation = launch("synthetic-small")  # a late endpoint still recovers
    assert link.readiness() == ("ready", "ok")

    # With no smaller model installed, the fourth loss is content-only at once; losses outside the window do not count.
    clock = [0.0]
    link = RuntimeLink(Settings(), _plan(MODEL), clock=lambda: clock[0])
    generation = launch(MODEL)
    for _ in range(3):
        clock[0] += 200
        link.lost(generation)
        generation = launch(MODEL)
    clock[0] += 200
    link.lost(generation)
    assert link.state == "restarting"  # only two of the losses fall inside the five-minute window
    clock[0] += 1000  # and later all of them have left it
    generation = launch(MODEL)
    for _ in range(3):
        clock[0] += 1
        link.lost(generation)
        assert link.state == "restarting"
        generation = launch(MODEL)
    clock[0] += 1
    link.lost(generation)
    assert link.state == "gave_up"
    # An endpoint that never comes (the shell gave up first) is content-only after the configured wait.
    link = RuntimeLink(Settings(), _plan(MODEL), clock=lambda: clock[0])
    link.lost(launch(MODEL))
    clock[0] += Settings().runtime_restart_wait_s + 1
    link.tick()
    assert link.state == "gave_up"

    # Open sessions follow the runtime's model: after the switch to the smaller model they ask the runtime for it.
    async def switch() -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        runtime = AppRuntime(SETTINGS, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path / "switch")
        runtime.link = RuntimeLink(SETTINGS, plan)
        engine = runtime.engine(SessionState("ses_switch"))  # opened before any runtime attached
        cloud_before = {
            tier: [str(c) for c in candidates if c.locality == "cloud"]
            for tier, candidates in engine.deps.router.config.tiers.items()
        }
        async with FakeLlamaServer(["synthetic-small"], api_key=KEYS[0], script=_answers(COACH)) as fake:
            assert await runtime.connect_runtime(fake.url, KEYS[0], "synthetic-small")
        await runtime.close()
        return (
            {tier: [str(c) for c in candidates] for tier, candidates in engine.deps.router.config.tiers.items()},
            cloud_before,
        )

    tiers, cloud_before = asyncio.run(switch())
    assert all(
        [c for c in candidates if c.startswith("local:")] == ["local:synthetic-small"] for candidates in tiers.values()
    )
    assert {
        tier: [c for c in candidates if c.startswith("cloud:")] for tier, candidates in tiers.items()
    } == cloud_before
