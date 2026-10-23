"""Device-lab timing (EVL-14): fixed scripts on the reference laptops, summarised and checked against class gates.

The lab runs the scripts in `evals/devlab/scripts/` on each reference laptop with networking disabled and every API-10
gate on, and writes one measurements file per laptop. This module summarises the timed runs (after warm-up) into
medians and 95th percentiles and says which gate a laptop misses. The measurements need the laptops; nothing here
fabricates a timing.
"""

from __future__ import annotations

import math
import statistics
import tomllib
from typing import Any

from .. import REPO_ROOT

SCRIPTS = REPO_ROOT / "evals" / "devlab" / "scripts"
CLASSES = ("low", "mid", "high")
METRICS = ("core_ready_s", "ready_s", "first_text_s", "restatement_s", "step_s")


def scripts() -> dict[str, dict[str, Any]]:
    return {p.stem: tomllib.loads(p.read_text()) for p in sorted(SCRIPTS.glob("*.toml"))}


def summarise(values: list[float], warmup: int) -> dict[str, float | int]:
    timed = sorted(values[warmup:])
    if not timed:
        return {"n": 0, "median": math.nan, "p95": math.nan}
    p95 = timed[min(len(timed) - 1, math.ceil(0.95 * len(timed)) - 1)]
    return {"n": len(timed), "median": statistics.median(timed), "p95": p95}


def lab_errors(laptop: dict[str, Any]) -> list[str]:
    """Why a laptop's measurements miss its class's gates (EVL-14; budgets of AGT-28 and MDL-17)."""
    from agent_core.config import Settings

    settings = Settings()
    name, hw = laptop["name"], laptop["hardware_class"]
    errors = []
    if laptop.get("network") != "disabled":
        errors.append(f"{name}: timed with networking {laptop.get('network')}; the lab runs offline (EVL-16)")
    if not laptop.get("all_gates_enabled", False):
        errors.append(f"{name}: a pre-delivery gate was off during the run; such timings never count (EVL-17)")
    index = CLASSES.index(hw)
    budgets = {"first_text_s": settings.coach_first_text_budget_s[index],
               "restatement_s": settings.restatement_budget_s,
               "step_s": settings.guided_step_budget_s[index]}  # fmt: skip
    for metric, budget in budgets.items():
        summary = summarise(laptop["runs"].get(metric, []), settings.devlab_warmup_runs)
        if summary["n"] < settings.devlab_timed_runs:
            errors.append(f"{name}: {metric} has {summary['n']} timed runs, fewer than {settings.devlab_timed_runs}")
        elif summary["median"] > budget:
            errors.append(f"{name}: median {metric} {summary['median']:.2f} s exceeds the {hw} gate of {budget} s")
    peak, ram, headroom = laptop["peak_memory_gb"], laptop["installed_ram_gb"], settings.devlab_ram_headroom_gb
    if peak > ram - headroom:
        errors.append(f"{name}: peak memory {peak} GB leaves less than {headroom} GB of {ram} GB")
    return errors


# VER-28: the tools with a p95 latency budget, by the configuration key that holds it.
TOOL_BUDGETS = {
    "math_parse": "ver_p95_math_parse_ms",
    "math_check_equivalence": "ver_p95_math_check_equivalence_ms",
    "math_check_step": "ver_p95_math_check_step_ms",
    "chem_balance": "ver_p95_chem_balance_ms",
    "acc_statements": "ver_p95_acc_statements_ms",
    "phys_circuit": "ver_p95_phys_circuit_ms",
}


def tool_budget_errors(laptop: dict[str, Any]) -> list[str]:
    """Why a laptop's checker timings miss the budgets of VER-28: each budgeted tool's p95 call latency (host round
    trip, after warm-up), the CPU of every call, and the time from a worker's start to its completed handshake. The
    timings come from `python -m jana_tools worker-bench --lab` run on the laptop (the `tools` object)."""
    from agent_core.config import Settings

    settings = Settings()
    name, tools = laptop["name"], laptop.get("tools")
    if not isinstance(tools, dict):
        return [f"{name}: no checker timings; run worker-bench --lab on it (VER-28)"]
    errors = []
    if laptop.get("network") != "disabled":
        errors.append(f"{name}: timed with networking {laptop.get('network')}; the lab runs offline (EVL-16)")
    calls = tools.get("calls_ms", {})
    for tool, key in TOOL_BUDGETS.items():
        budget = getattr(settings, key)
        summary = summarise(calls.get(tool, []), settings.devlab_warmup_runs)
        if summary["n"] < settings.devlab_timed_runs:
            errors.append(f"{name}: {tool} has {summary['n']} timed calls, fewer than {settings.devlab_timed_runs}")
        elif summary["p95"] > budget:
            errors.append(f"{name}: p95 {tool} {summary['p95']:.1f} ms exceeds its budget of {budget} ms")
    for tool, values in sorted(tools.get("cpu_ms", {}).items()):
        if values and max(values) > settings.worker_call_cpu_ms:
            errors.append(f"{name}: a {tool} call took {max(values):.0f} ms of CPU, over {settings.worker_call_cpu_ms}")
    ready = tools.get("ready_s", [])
    if not ready:
        errors.append(f"{name}: no worker start was timed")
    elif max(ready) > settings.worker_warm_target_s:
        errors.append(f"{name}: a worker took {max(ready):.2f} s to be ready, over {settings.worker_warm_target_s} s")
    return errors


POWER_CLASSES = ("content_only", "low", "mid", "high")  # TABLE PLT-22a's order


def battery_errors(laptop: dict[str, Any]) -> list[str]:
    """Why a laptop's battery run misses PLT-22: average watts over the one-hour scripted run in normal and low-power
    mode against TABLE PLT-22a, and low-power mode at least `low_power_min_saving` lower (`battery`: normal_w,
    low_power_w; measured on battery, screen at 50%, networking disabled)."""
    from agent_core.config import Settings

    settings = Settings()
    name, battery = laptop["name"], laptop.get("battery")
    if not battery:
        return [f"{name}: no battery run"]
    index = POWER_CLASSES.index(laptop["hardware_class"])
    normal, low = float(battery["normal_w"]), float(battery["low_power_w"])
    errors = []
    if normal > settings.battery_budget_normal_w[index]:
        errors.append(f"{name}: {normal:.1f} W in normal mode, over {settings.battery_budget_normal_w[index]} W")
    if low > settings.battery_budget_low_power_w[index]:
        errors.append(f"{name}: {low:.1f} W in low-power mode, over {settings.battery_budget_low_power_w[index]} W")
    if laptop["hardware_class"] != "content_only" and (normal - low) / normal < settings.low_power_min_saving:
        errors.append(f"{name}: low-power mode saves {(normal - low) / normal:.0%}, under "
                      f"{settings.low_power_min_saving:.0%}")  # fmt: skip
    return errors
