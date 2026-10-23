"""The observability overhead benchmark (OBS-24).

Tracing, logging and metrics together may add at most `obs24_max_turn_share` to the median turn duration and
`obs24_max_rss_mb` to resident memory on the low-class reference laptop. The benchmark runs the same guided turns
through the shipped engine twice, each in a fresh process: once as the app runs (turn traces to the trace store,
JSON logs, the metrics the trace records carry) and once with all of that removed (no store, no sink, no log
writer). The in-memory turn record stays in both, because the engine's turn result is built from it; what differs
is everything observability keeps or writes. Each process reports its median turn time after warm-up and its peak
resident memory. On the lab laptop the turns run against the real runtime (`--url`/`--key`/`--model`); without one
they run against the development script, which only exercises the mechanism.
"""

from __future__ import annotations

import asyncio
import json
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

from .. import REPO_ROOT

STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
MODES = ("on", "off")


def peak_rss_bytes() -> int:
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return int(peak if sys.platform == "darwin" else peak * 1024)  # bytes on macOS, KB elsewhere


async def _turns(mode: str, turns: int, warmup: int, endpoint: tuple[str, str, str] | None) -> dict[str, Any]:
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble, start_worker_pool
    from agent_core.engine.devscript import dev_scripted_provider
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.llama import LlamaServerProvider
    from agent_core.trace.logs import JsonLogger
    from agent_core.trace.store import TraceStore

    settings = Settings(worker_pool_size=1)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        supervisor = await start_worker_pool(settings, root / "scratch")
        store = TraceStore(root / "traces.db", max_bytes=settings.trace_store_max_bytes,
                           retention_days=settings.trace_retention_days) if mode == "on" else None  # fmt: skip
        logger = JsonLogger(root / "logs", "agent-core", "bench") if mode == "on" else None
        durations = []
        try:
            for _ in range(warmup + turns):
                provider: Any = LlamaServerProvider(endpoint[0], endpoint[1]) if endpoint else dev_scripted_provider()
                state = SessionState(new_id("ses"), subject="physics", level="O", hardware_class="low")
                engine = assemble({"local": provider}, settings, state, REPO_ROOT / "content" / "agent",
                                  REPO_ROOT / "skills", root / "spill", supervisor,
                                  router_overrides=_pin(endpoint[2]) if endpoint else None,
                                  trace_sink=store.submit if store is not None else None)  # fmt: skip
                engine.logger = logger
                started = time.perf_counter()
                await engine.start_problem(STATEMENT)
                durations.append((time.perf_counter() - started) * 1000)
                if hasattr(provider, "close"):
                    await provider.close()
            if store is not None:
                store.flush()
        finally:
            await supervisor.close()
            if store is not None:
                store.close()
    timed = durations[warmup:]
    return {"mode": mode, "turns": len(timed), "median_turn_ms": statistics.median(timed),
            "peak_rss_bytes": peak_rss_bytes()}  # fmt: skip


def _pin(model: str) -> Any:
    def pin(data: dict[str, Any]) -> None:
        for tier in data["tiers"]:
            data["tiers"][tier] = [f"local:{model}"]

    return pin


def child(mode: str, turns: int, warmup: int, endpoint: tuple[str, str, str] | None = None) -> dict[str, Any]:
    """One mode in this process (run by `measure` in a fresh process per mode)."""
    return asyncio.run(_turns(mode, turns, warmup, endpoint))


def measure(turns: int = 20, warmup: int = 2, endpoint: tuple[str, str, str] | None = None) -> dict[str, Any]:
    """Both modes, each in a fresh process, and the overhead of `on` over `off`; the record for a laptop's
    device-lab file under `overhead`."""
    out: dict[str, Any] = {}
    for mode in MODES:
        args = [sys.executable, "-m", "jana_tools", "lab", "overhead-child", mode, str(turns), str(warmup)]
        if endpoint:
            args += list(endpoint)
        done = subprocess.run(args, capture_output=True, text=True, check=True, cwd=REPO_ROOT)
        out[mode] = json.loads(done.stdout.strip().splitlines()[-1])
    on, off = out["on"], out["off"]
    out["turn_share"] = (on["median_turn_ms"] - off["median_turn_ms"]) / off["median_turn_ms"]
    out["rss_mb"] = (on["peak_rss_bytes"] - off["peak_rss_bytes"]) / 1024**2
    out["runtime"] = "real" if endpoint else "development script"
    return out


def gate_errors(laptop: dict[str, Any]) -> list[str]:
    """Why a laptop's overhead record misses OBS-24: none, measured without the real runtime, or over a budget."""
    from agent_core.config import Settings

    settings = Settings()
    name, record = laptop.get("name", "?"), laptop.get("overhead")
    if not record:
        return [f"{name}: no overhead measurement (python -m jana_tools lab overhead)"]
    errors = []
    if record.get("runtime") != "real":
        errors.append(f"{name}: overhead measured without the real runtime")
    if record["turn_share"] > settings.obs24_max_turn_share:
        errors.append(f"{name}: tracing adds {record['turn_share']:.1%} to the median turn, over "
                      f"{settings.obs24_max_turn_share:.0%}")  # fmt: skip
    if record["rss_mb"] > settings.obs24_max_rss_mb:
        errors.append(f"{name}: tracing adds {record['rss_mb']:.0f} MB, over {settings.obs24_max_rss_mb} MB")
    return errors
