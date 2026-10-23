"""The model bake-off report (EVL-15) that decides D6 and feeds the router's bake-off record (MDL-27, MDL-28).

The procedure is fixed before any run: hard filters (approved weights licence with its licence file hashed at run
time, fits the class's RAM budget, tool calls and schema-constrained output work in the embedded runtime, 7B or
larger by D58); exclusion on any critical safety or leak-gate failure; a weighted score with Wilson intervals from
the development splits; then the held-out confirmation of the top candidate per router tier and hardware class, ties
going to the smaller model. This module turns per-candidate results into that report and checks it is complete; the
results themselves come from harness runs on the reference laptops (EVL-14).
"""

from __future__ import annotations

import json
from typing import Any

from .. import REPO_ROOT
from . import report as rep

CRITERIA = ("correctness", "pedagogy", "schema_first_try", "latency", "perception", "memory_battery")
TIERS = ("fast", "strong", "judge")
CLASSES = ("low", "mid", "high")
APPROVED_WEIGHTS_LICENCES = frozenset({"Apache-2.0", "MIT"})  # SEC-24 list for weights, as recorded at writing
MIN_PARAMS_B = 7.0  # D58: nothing smaller is run


def candidates() -> list[str]:
    """The D58 candidate ids, as the router's recommendations file lists them."""
    path = REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "recommended_models.json"
    return [m["model"] for m in json.loads(path.read_text())["models"]]


def weights() -> dict[str, float]:
    from agent_core.config import Settings

    return dict(zip(CRITERIA, Settings().bakeoff_weights, strict=True))


def filters(candidate: dict[str, Any], hardware_class: str) -> dict[str, bool]:
    fit = candidate["ram_fit"].get(hardware_class, False)
    return {
        "licence": candidate["licence"]["spdx"] in APPROVED_WEIGHTS_LICENCES
        and bool(candidate["licence"].get("file_sha256")),
        "ram_fit": bool(fit),
        "tool_calling": bool(candidate["runtime"]["tool_calling"]),
        "json_schema": bool(candidate["runtime"]["json_schema"]),
        "min_params": candidate["params_b"] >= MIN_PARAMS_B,
    }


def build(results: dict[str, dict[str, Any]], run_id: str, weights_fixed_at: str) -> dict[str, Any]:
    """`results[model]` holds licence, params_b, ram_fit, runtime, tiers, and per class: safety (critical failures,
    leak-gate failures) and per criterion (passed, total); `held_out[tier][class]` = held-out correctness as
    (passed, total) once the top candidate was confirmed."""
    w = weights()
    rows = []
    for model in sorted(results):
        r = results[model]
        row: dict[str, Any] = {"model": model, "params_b": r["params_b"], "licence": r["licence"], "classes": {}}
        for hw in CLASSES:
            f = filters(r, hw)
            per: dict[str, Any] = {"filters": f, "excluded": None, "scores": {}, "weighted": None}
            run = r.get("runs", {}).get(hw)
            if not all(f.values()):
                per["excluded"] = "filter: " + ", ".join(k for k, ok in f.items() if not ok)
            elif run is None:
                per["excluded"] = "not run on this class"
            elif run["safety"]["critical_failures"] or run["safety"]["leak_gate_failures"]:
                per["excluded"] = "critical safety or leak-gate failure"
            else:
                per["scores"] = {c: rep.result(*run["criteria"][c]) for c in CRITERIA}
                per["weighted"] = round(sum(w[c] * (per["scores"][c]["rate"] or 0.0) for c in CRITERIA), 6)
            row["classes"][hw] = per
        rows.append(row)
    ranking: dict[str, dict[str, list[str]]] = {}
    confirmation: dict[str, dict[str, Any]] = {}
    for tier in TIERS:
        ranking[tier], confirmation[tier] = {}, {}
        for hw in CLASSES:
            survivors = [r for r in rows if r["classes"][hw]["weighted"] is not None and tier in results[r["model"]]
                         ["tiers"]]  # fmt: skip
            order = sorted(survivors, key=lambda r: (-r["classes"][hw]["weighted"], r["params_b"], r["model"]))
            ranking[tier][hw] = [r["model"] for r in order]
            if not order:
                confirmation[tier][hw] = {"model": None, "confirmed": False, "held_out": None}
                continue
            top = order[0]["model"]
            held = results[top].get("held_out", {}).get(tier, {}).get(hw)
            result = rep.result(*held) if held else None
            development = order[0]["classes"][hw]["scores"]["correctness"]
            # Confirmed when held-out correctness is not significantly below the development split's.
            confirmed = bool(result and result["total"] and result["interval"][1] >= development["interval"][0])
            confirmation[tier][hw] = {"model": top, "held_out": result, "confirmed": confirmed}
    return {"bakeoff_version": 1, "run_id": run_id, "weights": w, "weights_fixed_at": weights_fixed_at,
            "candidates": rows, "ranking": ranking, "held_out_confirmation": confirmation,
            "decision": {t: {hw: c["model"] if c["confirmed"] else None for hw, c in v.items()}
                         for t, v in confirmation.items()}}  # fmt: skip


def report_errors(report: dict[str, Any], expected: list[str] | None = None) -> list[str]:
    """Why the report is not complete enough to decide D6 (EVL-15 acceptance)."""
    errors = []
    listed = {r["model"] for r in report["candidates"]}
    for model in sorted(set(expected if expected is not None else candidates()) - listed):
        errors.append(f"candidate {model} is missing from the report")
    for row in report["candidates"]:
        if not row["licence"].get("file_sha256"):
            errors.append(f"{row['model']}: the licence file hash is not recorded")
        for hw in CLASSES:
            per = row["classes"].get(hw)
            if per is None or set(per["filters"]) != {
                "licence",
                "ram_fit",
                "tool_calling",
                "json_schema",
                "min_params",
            }:
                errors.append(f"{row['model']}@{hw}: filter outcomes missing")
            elif per["excluded"] is None and (set(per["scores"]) != set(CRITERIA) or any(
                    len(s["interval"]) != 2 for s in per["scores"].values())):  # fmt: skip
                errors.append(f"{row['model']}@{hw}: a survivor needs every criterion scored with an interval")
    for tier, by_class in report["held_out_confirmation"].items():
        for hw, c in by_class.items():
            if c["model"] is not None and c["held_out"] is None:
                errors.append(f"{tier}@{hw}: {c['model']} has no held-out confirmation")
    if set(report["weights"]) != set(CRITERIA) or abs(sum(report["weights"].values()) - 1.0) > 1e-9:
        errors.append("the weights must cover every criterion and sum to 1")
    return errors
