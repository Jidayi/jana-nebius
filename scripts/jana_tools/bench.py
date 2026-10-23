"""Worker cold start and call latency on this machine (M2 exit evidence; inputs to the S2 performance budgets).

Cold start is spawn to a completed handshake, under the OS sandbox, preload included. Call latency is the host's
round trip through the supervisor for every golden case. Run once per reference laptop class and record the output
in the milestone's acceptance record."""

from __future__ import annotations

import asyncio
import os
import platform
import statistics
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


def _percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(p / 100 * (len(ordered) - 1)))]


def _machine() -> dict[str, Any]:
    cpu = platform.processor() or platform.machine()
    if platform.system() == "Darwin":
        cpu = subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True).stdout
    elif Path("/proc/cpuinfo").is_file():
        names = [
            line.split(":", 1)[1] for line in Path("/proc/cpuinfo").read_text().splitlines() if "model name" in line
        ]
        cpu = names[0] if names else cpu
    memory = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") if hasattr(os, "sysconf") else 0
    return {
        "os": f"{platform.system()} {platform.release()}",
        "cpu": cpu.strip(),
        "cores": os.cpu_count(),
        "memory_gb": round(memory / 2**30, 1),
        "python": platform.python_version(),
    }


async def _measure(starts: int, rounds: int) -> dict[str, Any]:
    machine, mechanism, cold, by_tool = await _samples(starts, rounds)
    latencies = [v for values in by_tool.values() for v in values]
    return {
        "machine": machine,
        "sandbox": mechanism,
        "cold_start_ms": {"runs": starts, "median": round(statistics.median(cold)), "max": round(max(cold))},
        "call_ms": {
            "calls": len(latencies),
            "p50": round(_percentile(latencies, 50), 1),
            "p95": round(_percentile(latencies, 95), 1),
            "max": round(max(latencies), 1),
            "p95_by_tool": {t: round(_percentile(v, 95), 1) for t, v in sorted(by_tool.items())},
        },
    }


async def _samples(starts: int, rounds: int) -> tuple[dict[str, Any], str, list[float], dict[str, list[float]]]:
    """Every timing, unsummarised: the machine, the sandbox, cold starts (ms) and host round trips by tool (ms) in
    the order they ran, so warm-up calls come first."""
    from agent_core.config import Settings
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory
    from tool_worker.functions import FUNCTIONS

    from . import golden

    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))
    with tempfile.TemporaryDirectory() as scratch:
        factory = process_factory(settings, scratch_root=Path(scratch))
        cold = []
        mechanism = "none"
        for _ in range(starts):
            began = time.perf_counter()
            worker = factory()
            await worker.start()
            await worker.hello()
            cold.append((time.perf_counter() - began) * 1000)
            mechanism = worker.sandbox_mechanism
            await worker.close()

        supervisor = WorkerSupervisor(factory, settings)
        await supervisor.start()
        by_tool: dict[str, list[float]] = {}
        for _ in range(rounds):
            for data in golden.load().values():
                tool = data["tool"]
                for case in data["cases"]:
                    began = time.perf_counter()
                    await supervisor.call(tool, FUNCTIONS[tool].version, case["args"], "chk_01JZ0000000000000000000001",
                                          15000)  # fmt: skip
                    by_tool.setdefault(tool, []).append((time.perf_counter() - began) * 1000)
        await supervisor.close()
    return _machine(), mechanism, cold, by_tool


def bench(starts: int = 5, rounds: int = 1) -> dict[str, Any]:
    return asyncio.run(_measure(starts, rounds))


def _cpu_ms() -> dict[str, list[float]]:
    """The CPU time of every golden case run in process, by tool (VER-28: no call may need more than the worker's
    CPU limit, which the sandbox enforces by killing the call)."""
    from . import golden

    by_tool: dict[str, list[float]] = {}
    for data in golden.load().values():
        for case in data["cases"]:
            began = time.process_time()
            golden.run(case, data["tool"])
            by_tool.setdefault(data["tool"], []).append(round((time.process_time() - began) * 1000, 2))
    return by_tool


def lab(starts: int = 25, rounds: int = 1) -> dict[str, Any]:
    """The checker timings a reference laptop adds to its device-lab measurements file as its `tools` object (VER-28;
    checked by `harness.devlab.tool_budget_errors`): host round trips by tool, CPU by tool and worker start times."""
    machine, mechanism, cold, by_tool = asyncio.run(_samples(starts, rounds))
    return {
        "machine": machine,
        "sandbox": mechanism,
        "tools": {
            "calls_ms": {t: [round(v, 2) for v in values] for t, values in sorted(by_tool.items())},
            "cpu_ms": _cpu_ms(),
            "ready_s": [round(ms / 1000, 3) for ms in cold],
        },
    }
