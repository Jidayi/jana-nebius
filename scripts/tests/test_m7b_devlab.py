"""M7.b: device-lab timing (EVL-14) and the model bake-off report (EVL-15). The EVL-14 acceptance tests read the
measurements the reference laptops produce and skip until the lab has them; the numbers below are synthetic."""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

import pytest
from jana_tools.harness import bakeoff, devlab

LAB = os.environ.get("JANA_DEVLAB_RESULTS")  # a directory of <laptop>.json measurement files from the lab
needs_lab = pytest.mark.skipif(LAB is None, reason="needs the reference laptops' measurements (device lab)")


def _laptops() -> list[dict[str, Any]]:
    assert LAB is not None
    laptops = [json.loads(p.read_text()) for p in sorted(Path(LAB).glob("*.json"))]
    assert {lap["hardware_class"] for lap in laptops} >= set(devlab.CLASSES), "one reference laptop per class"
    return laptops


@needs_lab
def evl14_latency_gates_per_class() -> None:
    errors = [e for lap in _laptops() for e in devlab.lab_errors(lap) if "peak memory" not in e]
    assert errors == []


@needs_lab
def evl14_memory_budget() -> None:
    errors = [e for lap in _laptops() for e in devlab.lab_errors(lap) if "peak memory" in e]
    assert errors == []


def _laptop(hw: str, first_text: float, peak: float = 6.0, ram: float = 16.0, **kw: Any) -> dict[str, Any]:
    runs = {"first_text_s": [9.0, 9.0] + [first_text] * 20, "restatement_s": [0.4] * 22, "step_s": [8.0] * 22}
    return {"name": f"ref-{hw}", "hardware_class": hw, "network": "disabled", "all_gates_enabled": True,
            "runs": runs, "peak_memory_gb": peak, "installed_ram_gb": ram} | kw  # fmt: skip


def test_devlab_gate_logic() -> None:
    assert devlab.scripts().keys() == {"cold_start", "s1_guided_step", "tool_latency"}
    assert devlab.summarise([100.0, 1.0, 2.0, 3.0], warmup=1) == {"n": 3, "median": 2.0, "p95": 3.0}
    assert devlab.lab_errors(_laptop("low", 4.5)) == []
    assert "exceeds the mid gate of 3.0 s" in devlab.lab_errors(_laptop("mid", 3.5))[0]
    assert "peak memory" in devlab.lab_errors(_laptop("low", 4.0, peak=6.5, ram=8.0))[0]
    assert any("gate was off" in e for e in devlab.lab_errors(_laptop("high", 1.0, all_gates_enabled=False)))
    assert any("networking enabled" in e for e in devlab.lab_errors(_laptop("high", 1.0, network="enabled")))
    short = _laptop("high", 1.0)
    short["runs"]["step_s"] = [1.0] * 5
    assert any("fewer than" in e for e in devlab.lab_errors(short))


# --- EVL-15 ---------------------------------------------------------------------------------------------------------

PARAMS = {"qwen3-vl-8b": 8.0, "gemma-4-12b": 12.0, "gemma-4-26b-a4b": 26.0, "qwen3-vl-30b": 30.0, "gemma-4-31b": 31.0}


def _results() -> dict[str, dict[str, Any]]:
    """Synthetic bake-off results for the D58 candidates (no model was run to make them)."""
    out = {}
    for n, model in enumerate(bakeoff.candidates()):
        size = PARAMS[model]
        fits = {"low": size <= 8, "mid": size <= 12, "high": True}
        runs = {hw: {"safety": {"critical_failures": 0, "leak_gate_failures": 0},
                     "criteria": {c: (80 + n, 100) for c in bakeoff.CRITERIA}} for hw in bakeoff.CLASSES}  # fmt: skip
        out[model] = {"params_b": size, "ram_fit": fits, "tiers": ["fast", "judge"] if size <= 12 else ["strong"],
                      "licence": {"spdx": "Apache-2.0", "file_sha256": "a" * 64},
                      "runtime": {"tool_calling": True, "json_schema": True}, "runs": runs,
                      "held_out": {t: {hw: (24, 30) for hw in bakeoff.CLASSES} for t in bakeoff.TIERS}}  # fmt: skip
    return out


def evl15_bakeoff_report_complete() -> None:
    results = _results()
    assert set(results) == set(PARAMS), "the report covers the D58 candidates"
    report = bakeoff.build(results, "bko_test", "2026-10-09")
    assert bakeoff.report_errors(report) == []
    assert abs(sum(report["weights"].values()) - 1.0) < 1e-9
    assert report["decision"]["fast"]["low"] == "qwen3-vl-8b", "only the 8B class fits the minimum laptop"
    for row in report["candidates"]:
        for per in row["classes"].values():
            assert set(per["filters"]) == {"licence", "ram_fit", "tool_calling", "json_schema", "min_params"}
            if per["excluded"] is None:
                assert all(len(s["interval"]) == 2 for s in per["scores"].values())

    missing = copy.deepcopy(report)
    missing["candidates"] = [r for r in missing["candidates"] if r["model"] != "gemma-4-31b"]
    assert "candidate gemma-4-31b is missing from the report" in bakeoff.report_errors(missing)
    unconfirmed = copy.deepcopy(results)
    for model in unconfirmed:
        unconfirmed[model]["held_out"] = {}
    errors = bakeoff.report_errors(bakeoff.build(unconfirmed, "bko_test", "2026-10-09"))
    assert any("has no held-out confirmation" in e for e in errors)

    unsafe = copy.deepcopy(results)
    unsafe["gemma-4-12b"]["runs"]["mid"]["safety"]["critical_failures"] = 1
    unsafe["gemma-4-12b"]["licence"] = {"spdx": "LicenseRef-Gemma-Terms", "file_sha256": "b" * 64}
    row = next(r for r in bakeoff.build(unsafe, "bko", "2026-10-09")["candidates"] if r["model"] == "gemma-4-12b")
    assert row["classes"]["mid"]["excluded"].startswith("filter: licence")

    tied = copy.deepcopy(results)
    for model in tied:
        tied[model]["runs"]["high"]["criteria"] = {c: (90, 100) for c in bakeoff.CRITERIA}
    ranking = bakeoff.build(tied, "bko", "2026-10-09")["ranking"]["strong"]["high"]
    assert ranking[0] == "gemma-4-26b-a4b", "ties go to the smaller model"
