"""The sketch correctness suite (EVL-28, D103, D106, D107): its report and its TABLE EVL-17a gates.

The scenarios (evals/sketch/scenarios.yaml, frozen and hash-locked, EVL-18) run on the online tier only, through the
gateway with the evaluation allowance. Each run gives one result per scenario: what the template selector chose,
whether a sketch was made and shown, its checkable elements and how many were correct after the engine's checks,
whether any shown number was unverified, whether every label and caption passed the output guard, the teachers'
judgements (EVL-21) and the latency from the turn's acceptance to the sketch being ready, measured through the gateway.
The selector half needs no model: `selector_results` runs it on every scenario offline.

`report` computes every measure, a correctness score per diagram kind (the share of the kind's sketches whose
checkable elements are all correct and that no teacher judges misleading) and the latency p50 and p95 with the share
that missed `sketch_deadline_ms`; `release_failures` names each missed TABLE EVL-17a row (any one fails the release);
`live_kinds` is the kinds whose gate passed, the only ones the engine may make sketch calls for
(`sketch_live_kinds`)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

SCENARIOS = REPO_ROOT / "evals" / "sketch" / "scenarios.yaml"
KINDS = ("graph", "geometry", "forces", "ray_diagram", "other")
# TABLE EVL-17a rows for online sketches (owner-approved values, D107).
CHECKED_WRONG_MAX = 0.02
UNVERIFIED_MAX = 0
MISLEADING_MAX = 0.05
KIND_SCORE_MIN = 0.90
CATALOGUE_REPLACED_MAX = 0
GUARD_PASS_MIN = 1.0
P50_MAX_MS = 3000
P95_MAX_MS = 8000
DEADLINE_MS = 3000


def scenarios(path: Path = SCENARIOS) -> list[dict[str, Any]]:
    return list(yaml.safe_load(path.read_text())["scenarios"])


def selector_results(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The template selector on every scenario (no model): which catalogue kind it chose, if any."""
    from agent_core.engine.sketch_flow import template_for

    return [{"id": s["id"], "kind": s["kind"], "catalogue_fits": s["catalogue_fits"],
             "chosen": template_for(s["wanted"], {}, s["subject"])} for s in items]  # fmt: skip


def _percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, math.ceil(share * len(ordered)) - 1)
    return float(ordered[index])


def _rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def report(results: list[dict[str, Any]], deadline_ms: int = DEADLINE_MS) -> dict[str, Any]:
    """Every EVL-28 measure from one run's per-scenario results."""
    sketched = [r for r in results if r.get("sketch_shown")]
    checkable = sum(int(r.get("checkable", 0)) for r in sketched)
    correct = sum(int(r.get("checkable_correct", 0)) for r in sketched)
    checked = [r for r in sketched if r.get("status") == "checked"]
    unchecked = [r for r in sketched if r.get("status") == "not_checked"]
    fitted = [r for r in results if r.get("catalogue_fits")]
    per_kind: dict[str, dict[str, Any]] = {}
    for kind in sorted({str(r["kind"]) for r in results} | set(KINDS)):
        mine = [r for r in sketched if r["kind"] == kind]
        good = [r for r in mine if int(r.get("checkable_correct", 0)) == int(r.get("checkable", 0))
                and not r.get("teacher_misleading") and not r.get("teacher_wrong")]  # fmt: skip
        per_kind[kind] = {"sketches": len(mine), "score": _rate(len(good), len(mine))}
    latencies = [float(r["latency_ms"]) for r in sketched if r.get("latency_ms") is not None]
    latency = {"p50": _percentile(latencies, 0.5), "p95": _percentile(latencies, 0.95),
               "missed_deadline": _rate(sum(1 for v in latencies if v > deadline_ms), len(latencies))}  # fmt: skip
    return {
        "scenarios": len(results),
        "sketches": len(sketched),
        "checkable_correct": _rate(correct, checkable),
        "unverified_number_sketches": sum(1 for r in sketched if r.get("unverified_number")),
        "catalogue_replaced": sum(1 for r in fitted if r.get("sketch_shown") or r.get("selector_chose_sketch")),
        "selector_chose_sketch_when_fitted": _rate(
            sum(1 for r in fitted if r.get("selector_chose_sketch")), len(fitted)
        ),
        "guard_pass": _rate(sum(1 for r in sketched if r.get("guard_pass", True)), len(sketched)),
        "checked_judged_wrong": _rate(sum(1 for r in checked if r.get("teacher_wrong")), len(checked)),
        "not_checked_misleading": _rate(sum(1 for r in unchecked if r.get("teacher_misleading")), len(unchecked)),
        "per_kind": per_kind,
        "latency_ms": latency,
    }


def live_kinds(summary: dict[str, Any]) -> tuple[str, ...]:
    """The kinds whose correctness gate passed: the only ones the engine may sketch (`sketch_live_kinds`). A kind with
    no sketches in the run has no evidence and stays off."""
    rows = summary["per_kind"].items()
    return tuple(k for k, row in rows if row["score"] is not None and row["score"] >= KIND_SCORE_MIN)


def release_failures(summary: dict[str, Any]) -> list[str]:
    """Each missed TABLE EVL-17a row; any one fails the release. Missing evidence is a failure, never a pass."""
    failures: list[str] = []

    if not summary["sketches"]:
        return ["no sketches in the run: no evidence"]

    def above(name: str, value: float | None, limit: float) -> None:
        # A rate over no cases (no checked sketch, say) has nothing to exceed; the run itself has sketches.
        if value is not None and value > limit:
            failures.append(f"{name}: {value} > {limit}")

    above("checked sketches judged wrong", summary["checked_judged_wrong"], CHECKED_WRONG_MAX)
    above("sketches showing an unverified number", summary["unverified_number_sketches"], UNVERIFIED_MAX)
    above("not-checked sketches judged misleading", summary["not_checked_misleading"], MISLEADING_MAX)
    above("sketches where a catalogue visual fitted", summary["catalogue_replaced"], CATALOGUE_REPLACED_MAX)
    if summary["latency_ms"]["p50"] is None:
        failures.append("no gateway-measured latency")
    above("latency p50 (ms)", summary["latency_ms"]["p50"], P50_MAX_MS)
    above("latency p95 (ms)", summary["latency_ms"]["p95"], P95_MAX_MS)
    if summary["guard_pass"] is None or summary["guard_pass"] < GUARD_PASS_MIN:
        failures.append(f"label and caption text through the output guard: {summary['guard_pass']} < 1.0")
    for kind, row in summary["per_kind"].items():
        if row["sketches"] and (row["score"] is None or row["score"] < KIND_SCORE_MIN):
            failures.append(f"correctness score for {kind}: {row['score']} < {KIND_SCORE_MIN}")
    return failures
