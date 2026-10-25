"""Stage release gating: the release gates (EVL-17), the exit metrics (PRD-17) and the stage release rule (PRD-11).

The gates are computed from the frozen-suite reports of the harness (and, for gates the Python harness does not run,
from the reports of the jobs that do: the gallery's render tests, the bake-off report and the model-in-the-loop
oracle run). A gate with no evidence fails: a candidate is never released on a missing measurement. Thresholds are
the configuration keys of the proposals (TABLE EVL-17a, TABLE PRD-17a).

The release script refuses to tag a stage release when (a) any `must` requirement of the stage or an earlier one
lacks a passing acceptance test, (b) any exit metric is unmet, or (c) any decision blocking the stage's gate is not
decided, and prints the failing items. A closed pilot (`--pilot`) may be tagged before the pilot-measured rows of (b)
are met, labelled as a pilot.
"""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ..coverage import acceptance_tests
from ..spec import DOCS, requirements

STAGES = ("S1", "S2", "S3", "S4", "S5")
STAGE_GATE = {"S1": "s1_foundation", "S2": "s2_launch", "S3": "s3_launch", "S4": "s4_launch", "S5": "s5_launch"}


@dataclass(frozen=True)
class Gate:
    metric: str
    threshold: str
    measured: str
    passed: bool
    evidence: str


def _rate(row: dict[str, Any] | None) -> tuple[int, int]:
    return (int(row["passed"]), int(row["total"])) if row else (0, 0)


def _at_least(metric: str, row: dict[str, Any] | None, share: float, evidence: str) -> Gate:
    passed, total = _rate(row)
    if total == 0:
        return Gate(metric, f"≥ {share:.0%}", "no evidence", False, evidence)
    rate = passed / total
    return Gate(metric, f"≥ {share:.0%}", f"{passed}/{total} ({rate:.1%})", rate >= share, evidence)


def _all(metric: str, row: dict[str, Any] | None, evidence: str) -> Gate:
    passed, total = _rate(row)
    if total == 0:
        return Gate(metric, "100%", "no evidence", False, evidence)
    return Gate(metric, "100%", f"{passed}/{total}", passed == total, evidence)


def s1_gates(
    report: dict[str, Any],
    *,
    gallery: dict[str, Any] | None = None,
    model_oracles: dict[str, Any] | None = None,
    bakeoff: dict[str, Any] | None = None,
    step_pairs: dict[str, Any] | None = None,
    decisions: dict[str, str] | None = None,
    settings: Any = None,
) -> list[Gate]:
    """TABLE EVL-17a, S1 column."""
    from agent_core.config import Settings

    settings = settings or Settings()
    suites = report.get("suites", {})
    scenarios = suites.get("scenarios", {}).get("criteria", {})
    safety = suites.get("safety", {}).get("criteria", {})
    marking = [c for c in report.get("cases", []) if c["suite"] == "marking" and c["status"] != "skipped"]
    golden = {"passed": sum(c["status"] == "passed" for c in marking), "total": len(marking)}
    traced = _merge(scenarios.get("board_numbers_traced"), safety.get("board_numbers_traced"))
    marking_criteria = suites.get("marking", {}).get("criteria", {})
    step_pairs = step_pairs or {
        "first_wrong": marking_criteria.get("step_first_wrong"),
        "category": marking_criteria.get("step_category"),
    }
    leaks = scenarios.get("no_answer_leak")
    gates = [
        _all("Board, visual and final numbers traced to a check_id", traced, "harness scenarios"),
        _at_least(
            "Final answer correct, tool-checkable items (one topic)",
            (model_oracles or {}).get("final_answer"),
            settings.gate_final_answer_correct,
            "model-in-the-loop answer oracles",
        ),
        _all("Marking test suite", suites.get("marking", {}).get("result"), "harness marking"),
        _at_least(
            "math_check_step first wrong step found",
            (step_pairs or {}).get("first_wrong"),
            settings.gate_step_first_wrong_found,
            "seeded step pairs (VER-06)",
        ),
        _at_least(
            "math_check_step category matches the label",
            (step_pairs or {}).get("category"),
            settings.gate_step_category_matches,
            "seeded step pairs (VER-06)",
        ),
        _all("Verification golden sets pass (VER-29)", golden, "harness marking (golden sets)"),
        _at_least(
            "Structured output parses first time, per role",
            (bakeoff or {}).get("structured_first_pass"),
            settings.gate_structured_first_pass,
            "bake-off report",
        ),
        _all("Critical scenarios", scenarios.get("critical"), "harness scenarios"),
        Gate(
            "Detected answer leaks in guided mode",
            "0",
            "no evidence" if not leaks else f"{_rate(leaks)[1] - _rate(leaks)[0]} leak(s)",
            bool(leaks) and _rate(leaks)[0] == _rate(leaks)[1],
            "harness scenarios",
        ),
        _all("Critical safety items", safety.get("critical"), "harness safety"),
        _all("Gallery states render without console errors", gallery, "client gallery job"),
        Gate(
            "Zero egress during offline gate runs",
            "yes",
            str(report.get("network", {}).get("egress_attempts")),
            report.get("network", {}).get("egress_attempts") == 0
            and report.get("network", {}).get("state") == "disabled",
            "harness egress monitor",
        ),
        Gate(
            "Every offline gate run present for the candidate",
            "yes",
            "valid" if report.get("valid") else "invalid",
            bool(report.get("valid")),
            "harness report",
        ),
        Gate(
            "Local model per tier and class chosen by the bake-off (D6)",
            "decided",
            (decisions or {}).get("D6", "unknown"),
            (decisions or {}).get("D6") == "decided",
            "decisions register",
        ),
    ]
    return gates


def _merge(*rows: dict[str, Any] | None) -> dict[str, Any] | None:
    present = [r for r in rows if r]
    if not present:
        return None
    return {"passed": sum(r["passed"] for r in present), "total": sum(r["total"] for r in present)}


def held_out_drop_failures(report: dict[str, Any], previous: dict[str, Any] | None, max_points: float) -> list[str]:
    """A release fails when a held-out metric drops by more than `max_points` with non-overlapping intervals."""
    if previous is None:
        return []
    failures = []
    for name, suite in report.get("suites", {}).items():
        prior = previous.get("suites", {}).get(name, {})
        # Every held-out metric counts, not only a suite's pooled held_out aggregate (EVL-17).
        now_rows = {**suite.get("criteria", {}), "result": suite.get("result")}
        old_rows = {**prior.get("criteria", {}), "result": prior.get("result")}
        for metric, now in now_rows.items():
            before = old_rows.get(metric)
            if not now or not before or now["rate"] is None or before["rate"] is None:
                continue
            if metric != "held_out" and suite.get("split") != "held_out":
                continue
            drop = (before["rate"] - now["rate"]) * 100
            if drop > max_points and now["interval"][1] < before["interval"][0]:
                label = name if metric == "held_out" else f"{name}.{metric}"
                failures.append(f"{label}: held-out rate fell {drop:.1f} points (EVL-17)")
    return failures


# Rows of TABLE PRD-17a that the stage's release candidate is gated on, and rows measured in the pilot, which are exit
# metrics reported at the end of the stage's pilot and never block the release candidate itself (PRD-17). A closed
# pilot may ship before the pilot rows are met, labelled as a pilot (PRD-11).
RELEASE_GATE = "release_gate"
PILOT = "pilot"


def exit_metrics(
    stage: str,
    report: dict[str, Any] | None,
    timings: dict[str, float] | None,
    contracts: tuple[int, int] | None,
    settings: Any = None,
    *,
    evidence: dict[str, Any] | None = None,
    pilot: dict[str, Any] | None = None,
    locks: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """TABLE PRD-17a rows for the stage, targets from configuration, each measured, met, unmet or missing.

    `evidence` is the stage's candidate-bound evaluation dossier (the S2 dossier of `release.evaluation`); `pilot` is
    the stage's pilot evidence: aggregates only, from opt-in telemetry, the consented pilot export, the pre-registered
    analysis and the usability sessions."""
    from agent_core.config import Settings

    settings = settings or Settings()
    if stage == "S2":
        return _s2_exit_metrics(report, evidence, pilot, settings, locks)
    if stage != "S1":
        return [
            _row(
                f"{stage} exit metrics",
                "TABLE PRD-17a",
                None,
                False,
                "defined from the stage's milestone",
                RELEASE_GATE,
            )
        ]
    traced = None
    if report:
        criteria = report.get("suites", {}).get("scenarios", {}).get("criteria", {})
        traced = criteria.get("board_numbers_traced")
    rows: list[dict[str, Any]] = []

    def row(metric: str, target: str, measured: Any, met: bool | None, by: str) -> None:
        rows.append(_row(metric, target, measured, met, by, RELEASE_GATE))

    row(
        "Board numbers with a check_id on the S1 suite",
        "100%",
        None if not traced or not traced["total"] else f"{traced['passed']}/{traced['total']}",
        bool(traced) and traced["passed"] == traced["total"],
        "evaluation harness",
    )
    first_text = (timings or {}).get("first_text_median_s")
    row(
        "First accepted text, mid-class laptop (median)",
        f"≤ {settings.exit_s1_first_text_median_s} s",
        first_text,
        first_text is not None and first_text <= settings.exit_s1_first_text_median_s,
        "harness timing",
    )
    restatement = (timings or {}).get("restatement_median_s")
    row(
        "Restated question, knowns and status line, mid-class laptop (median)",
        f"≤ {settings.exit_s1_restatement_median_s} s",
        restatement,
        restatement is not None and restatement <= settings.exit_s1_restatement_median_s,
        "harness timing",
    )
    row(
        "Contracts generate types with zero drift",
        "100% of contracts",
        None if contracts is None else f"{contracts[0]}/{contracts[1]}",
        contracts is not None and contracts[0] == contracts[1],
        "CI",
    )
    return rows


def _row(metric: str, target: str, measured: Any, met: bool | None, by: str, kind: str) -> dict[str, Any]:
    status = "missing" if measured is None else ("met" if met else "unmet")
    return {"metric": metric, "target": target, "measured": measured, "status": status, "by": by, "kind": kind}


# TABLE PRD-17a, S2 release-gate rows: (metric, suite, criterion, settings key or None for 100%, measured by).
S2_GATE_ROWS = (
    ("Final answer correct on tool-checkable items", "answer_oracles", "final_answer", "exit_s2_final_answer_correct",
     "answer oracles"),
    ("Guided mode withholds the answer until earned", "simulated_students", "withheld_until_earned",
     "exit_s2_guided_withholding", "simulated students"),
    ("Critical safety items handled correctly", "safety", "critical", None, "safety set"),
)  # fmt: skip


def _s2_exit_metrics(
    report: dict[str, Any] | None,
    evidence: dict[str, Any] | None,
    pilot: dict[str, Any] | None,
    settings: Any,
    locks: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """TABLE PRD-17a, S2 rows. The release-gate rows are read per reference class from the candidate's valid frozen
    release reports, so a passing class never hides a failing one; the pilot rows from the pilot evidence."""
    from .evaluation import CLASSES, checked_reports, counts

    candidate = (report or {}).get("build", {}).get("commit", "")
    reports, problems = checked_reports(evidence or {}, candidate, locks)
    rows = []
    for metric, suite, criterion, key, by in S2_GATE_ROWS:
        share = 1.0 if key is None else float(getattr(settings, key))
        target = ("100%" if key is None else f"≥ {share:.0%}") + " on every reference class"
        # Every run of every class is checked on its own: one large passing run never masks a failing one.
        per_class = {
            hw: [
                counts(r["suites"][suite].get("criteria", {}).get(criterion))
                for r in reports
                if r.get("hardware", {}).get("hardware_class") == hw
                and r.get("suites", {}).get(suite, {}).get("status") == "ran"
            ]
            for hw in CLASSES
        }
        absent = [hw for hw, found in per_class.items() if not found or any(c is None for c in found)]
        if not reports and not problems:
            rows.append(_row(metric, target, None, False, by, RELEASE_GATE))
        elif problems or absent:
            reason = "; ".join(problems) or f"no valid counts for {', '.join(absent)}"
            rows.append(_row(metric, target, reason, False, by, RELEASE_GATE))
        else:
            valid = [(hw, c) for hw, found in per_class.items() for c in found if c is not None]
            measured = "; ".join(f"{hw} {p}/{n}" for hw, (p, n) in valid)
            met = all(p / n >= share for _, (p, n) in valid)
            rows.append(_row(metric, target, measured, met, by, RELEASE_GATE))
    rows.extend(s2_pilot_rows(pilot, settings))
    return rows


def _counted(row: Any) -> tuple[int, int] | None:
    from .evaluation import counts

    return counts(row)


def s2_pilot_rows(pilot: dict[str, Any] | None, settings: Any) -> list[dict[str, Any]]:
    """The S2 rows measured in the pilot, from aggregates only (no student identifier reaches this record)."""
    pilot = pilot if isinstance(pilot, dict) and pilot.get("stage") == "S2" else {}
    rows = []
    crash = _counted(pilot.get("crash_free_sessions"))
    rows.append(
        _row(
            "Crash-free sessions in pilot",
            f"≥ {settings.exit_s2_crash_free_sessions:.1%}",
            None if crash is None else f"{crash[0]}/{crash[1]}",
            crash is not None and crash[0] / crash[1] >= settings.exit_s2_crash_free_sessions,
            "opt-in telemetry (crash-free session rate, OBS-13a)",
            PILOT,
        )
    )
    active = _counted(pilot.get("weekly_active"))
    rows.append(
        _row(
            "Pilot students active in a week",
            f"≥ {settings.exit_s2_weekly_active_share:.0%} of enrolled",
            None if active is None else f"{active[0]}/{active[1]}",
            active is not None and active[0] / active[1] >= settings.exit_s2_weekly_active_share,
            "pilot export (consented)",
            PILOT,
        )
    )
    days = pilot.get("active_days_per_week")
    median = None
    if isinstance(days, list) and days and all(type(d) is int and 0 <= d <= 7 for d in days):
        median = float(statistics.median(days))
    rows.append(
        _row(
            "Median active days per week per active student",
            f"≥ {settings.exit_s2_median_active_days:g}",
            median,
            median is not None and median >= settings.exit_s2_median_active_days,
            "pilot export (consented)",
            PILOT,
        )
    )
    effect, preregistered = _learning_gain(pilot.get("learning_gain"))
    rows.append(
        _row(
            "Learning gain versus comparison classes, 8 to 12 weeks",
            f"≥ {settings.exit_s2_learning_gain_sd:g} SD, pre-registered",
            None if effect is None else f"{effect:g} SD" + ("" if preregistered else ", not pre-registered"),
            effect is not None and preregistered and effect >= settings.exit_s2_learning_gain_sd,
            "pre-test and post-test",
            PILOT,
        )
    )
    task = _counted(pilot.get("core_journey_task_success"))
    rows.append(
        _row(
            "Core-journey task success without help",
            f"≥ {settings.exit_s2_task_success:.0%}",
            None if task is None else f"{task[0]}/{task[1]}",
            task is not None and task[0] / task[1] >= settings.exit_s2_task_success,
            "usability sessions",
            PILOT,
        )
    )
    return rows


def _learning_gain(gain: Any) -> tuple[float | None, bool]:
    """The effect size, and whether its analysis was registered before the first pilot data, frozen by hash, over an
    8 to 12 week study (PRD-17, EVL-22)."""
    if not isinstance(gain, dict):
        return None, False
    effect = gain.get("effect_sd")
    if type(effect) not in (int, float) or not math.isfinite(effect):
        return None, False
    try:
        registered = datetime.fromisoformat(str(gain["registered_at"]).replace("Z", "+00:00"))
        first_data = datetime.fromisoformat(str(gain["first_data_at"]).replace("Z", "+00:00"))
        ordered = registered.utcoffset() is not None and registered < first_data
    except (KeyError, ValueError):
        ordered = False
    weeks = gain.get("weeks")
    frozen = isinstance(gain.get("analysis_sha256"), str) and len(gain["analysis_sha256"]) == 64
    return float(effect), ordered and frozen and type(weeks) is int and 8 <= weeks <= 12


def unmet_requirements(stage: str, results: dict[str, str], docs: Path = DOCS) -> list[str]:
    """(a): every active must requirement of the stage or an earlier one has its acceptance tests passing."""
    rank = STAGES.index(stage)
    failing = []
    for rid, req in sorted(requirements(docs).items()):
        if req.retired or req.priority != "must" or STAGES.index(req.stage) > rank:
            continue
        tests = acceptance_tests(rid, docs)
        bad = [f"{t} → {results.get(t, 'missing')}" for t in tests if results.get(t) != "pass"]
        if bad:
            failing.append(f"{rid}: {', '.join(bad)}")
    return failing


def register_gates(docs: Path = DOCS) -> list[str]:
    """Every gate the decisions register names."""
    data = json.loads((docs / "specification" / "registers" / "decisions.json").read_text())
    return list(data["gates"])


def undecided_for_gate(gate: str, docs: Path = DOCS) -> list[str]:
    """Decisions blocking `gate` that are not decided; a gate the register does not name is itself a failure."""
    path = docs / "specification/registers/decisions.json"
    if not path.is_file():
        return ["missing owner decisions register; no release decision is inferred for this public fork"]
    data = json.loads((docs / "specification" / "registers" / "decisions.json").read_text())
    if gate not in data["gates"]:
        return [f"{gate}: not a gate of the decisions register"]
    return [
        f"{d['id']} ({d['status']}): {d['title']}"
        for d in data["decisions"]
        if gate in d.get("blocks", []) and d["status"] != "decided"
    ]


def undecided(stage: str, docs: Path = DOCS) -> list[str]:
    """(c): decisions blocking the stage's gate that are not decided."""
    return undecided_for_gate(STAGE_GATE[stage], docs)


def release_rule_failures(
    stage: str,
    results: dict[str, str],
    metrics: list[dict[str, Any]],
    docs: Path = DOCS,
    *,
    closed_pilot: bool = False,
) -> dict[str, list[str]]:
    """PRD-11: the failing items under (a), (b) and (c); the stage may be tagged only when all are empty.

    A closed pilot may ship before the pilot-measured exit metrics are met (PRD-11, PRD-17): those rows are reported,
    not blocking, and the release is labelled as a pilot. The release-gate rows still block, and every decision that
    blocks `pilot_start` must be decided too (M25 exit evidence)."""
    decisions = undecided(stage, docs)
    if closed_pilot or stage == "S2":  # M25 exit: s2_launch and pilot_start decisions both decided
        decisions += [d for d in undecided_for_gate("pilot_start", docs) if d not in decisions]
    return {
        "requirements": unmet_requirements(stage, results, docs),
        "exit_metrics": [
            f"{m['metric']}: {m['status']} ({m['measured']}; target {m['target']})"
            for m in metrics
            if m["status"] != "met" and not (closed_pilot and m.get("kind") == PILOT)
        ],
        "decisions": decisions,
    }


def pilot_pending(metrics: list[dict[str, Any]]) -> list[str]:
    """The pilot-measured rows still to be reported at the end of the stage's pilot: what labels a closed pilot."""
    return [f"{m['metric']}: {m['status']}" for m in metrics if m.get("kind") == PILOT and m["status"] != "met"]
