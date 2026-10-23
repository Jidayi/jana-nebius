"""Offline evaluation of the mastery model (LRN-11, LRN-41): the BKT baseline study and the replay gate on parameter
changes. Run by the content pipeline on held-out logs, never on a student's device (S2). Every subject runs `pfa_elo`
(D25, decided in D100); the BKT comparison is a post-pilot study whose `choice` only informs a later decision and gates
no release, while the replay gate does gate every parameter change.

Logs are graded opportunities, one `Graded` per (student, KC) observation in time order, plus the mastery checks the
students sat (`Check`). The held-out split is by student: a frozen, hash-locked set of student references (EVL-18),
whose sha256 the report records so a later run proves it used the same split. Held-out logs are never committed; the
tests feed synthetic ones.

- `bakeoff`: fits `pfa_elo` (the learning-rate pair on a grid) and four-parameter BKT (on a grid) on the training
  students, then reports per subject, on the held-out students, AUC, log loss, expected calibration error and the
  agreement of mastery-check triggers with check outcomes, and the model the evidence favours: `pfa_elo` unless BKT's
  AUC is higher by at least the margin (D25).
- `replay_gate`: replays the held-out logs under the current and the candidate parameter files and fails the
  candidate when its log loss or calibration error is worse (beyond the configured tolerance, none by default); it
  reports the share of students whose plan main block changes.
"""

from __future__ import annotations

import hashlib
import itertools
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from agent_core.config import Settings
from agent_core.learner import planner
from agent_core.learner.mastery import (
    Ability,
    Bkt,
    KcEvidence,
    MasteryParams,
    item_probability,
    kc_probability,
    observe,
)

MODELS = ("pfa_elo", "bkt")


@dataclass(frozen=True)
class Graded:
    student: str
    subject: str
    kc_id: str
    correct: bool
    t_ms: int
    b_item: float = 0.0


@dataclass(frozen=True)
class Check:
    student: str
    subject: str
    kc_id: str
    t_ms: int
    passed: bool


@dataclass
class Predictions:
    """A model's predicted success before each held-out observation, and its mastery estimate at each check."""

    scores: list[tuple[float, bool]]
    checks: list[tuple[float, bool]]


def split_hash(students: Iterable[str]) -> str:
    return hashlib.sha256("\n".join(sorted(set(students))).encode()).hexdigest()


def held_out_split(students: Iterable[str], share: float = 0.2) -> set[str]:
    """A deterministic student-level split: a student is held out when their reference's hash falls in the share."""
    return {s for s in set(students) if int(hashlib.sha256(s.encode()).hexdigest()[:8], 16) / 0xFFFFFFFF < share}


# --- replaying a model over a log -------------------------------------------------------------------------------


def _by_student(logs: Iterable[Graded], checks: Iterable[Check]) -> dict[str, list[Graded | Check]]:
    out: dict[str, list[Graded | Check]] = {}
    for row in [*logs, *checks]:
        out.setdefault(row.student, []).append(row)
    for rows in out.values():
        rows.sort(key=lambda r: (r.t_ms, isinstance(r, Check)))
    return out


def replay_pfa(logs: Sequence[Graded], checks: Sequence[Check], p: MasteryParams) -> Predictions:
    scores: list[tuple[float, bool]] = []
    trigger: list[tuple[float, bool]] = []
    for rows in _by_student(logs, checks).values():
        ability: dict[str, Ability] = {}
        evidence: dict[str, KcEvidence] = {}
        for row in rows:
            theta = ability.setdefault(row.subject, Ability())
            if isinstance(row, Check):
                ev = evidence.get(row.kc_id, KcEvidence())
                trigger.append((kc_probability(theta.theta, ev, p, 0.0, row.kc_id), row.passed))
                continue
            evidence.setdefault(row.kc_id, KcEvidence()).decay_to(row.t_ms, p)
            scores.append((item_probability(theta.theta, {row.kc_id: 1.0}, evidence, p, row.b_item), row.correct))
            observe(y=int(row.correct), w=1.0, t=row.t_ms, weights={row.kc_id: 1.0}, first_error_kc=None,
                    ability=theta, evidence=evidence, p=p, b_item=row.b_item)  # fmt: skip
    return Predictions(scores, trigger)


def replay_bkt(logs: Sequence[Graded], checks: Sequence[Check], bkt: Bkt) -> Predictions:
    scores: list[tuple[float, bool]] = []
    trigger: list[tuple[float, bool]] = []
    for rows in _by_student(logs, checks).values():
        learned: dict[str, float] = {}
        for row in rows:
            p_l = learned.get(row.kc_id, bkt.p_init)
            if isinstance(row, Check):
                trigger.append((p_l, row.passed))
                continue
            scores.append((bkt.predict(p_l), row.correct))
            learned[row.kc_id] = bkt.update(p_l, row.correct)
    return Predictions(scores, trigger)


# --- metrics -----------------------------------------------------------------------------------------------------


def auc(scores: Sequence[tuple[float, bool]]) -> float | None:
    """The probability a random success outranks a random failure (ties count half); None with one class only."""
    positives = [s for s, y in scores if y]
    negatives = [s for s, y in scores if not y]
    if not positives or not negatives:
        return None
    ranked = sorted(scores, key=lambda r: r[0])
    rank_sum, i = 0.0, 0
    while i < len(ranked):
        j = i
        while j < len(ranked) and ranked[j][0] == ranked[i][0]:
            j += 1
        mean_rank = (i + 1 + j) / 2
        rank_sum += mean_rank * sum(1 for k in range(i, j) if ranked[k][1])
        i = j
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)


def log_loss(scores: Sequence[tuple[float, bool]]) -> float:
    eps = 1e-12
    if not scores:
        return math.nan
    return -sum(math.log(min(max(s if y else 1 - s, eps), 1.0)) for s, y in scores) / len(scores)


def calibration_error(scores: Sequence[tuple[float, bool]], bins: int) -> float:
    """Expected calibration error: the occupancy-weighted gap between mean prediction and outcome per bin."""
    if not scores:
        return math.nan
    groups: dict[int, list[tuple[float, bool]]] = {}
    for s, y in scores:
        groups.setdefault(min(int(s * bins), bins - 1), []).append((s, y))
    return sum(len(g) * abs(sum(s for s, _ in g) / len(g) - sum(y for _, y in g) / len(g)) for g in groups.values()) / (
        len(scores)
    )


def check_agreement(checks: Sequence[tuple[float, bool]], ready: float) -> float | None:
    """How often the model's mastery-check trigger (its estimate at or above the readiness bar) matched the outcome."""
    if not checks:
        return None
    return sum((estimate >= ready) == passed for estimate, passed in checks) / len(checks)


def metrics(found: Predictions, settings: Settings) -> dict[str, float | None]:
    return {
        "auc": auc(found.scores),
        "log_loss": log_loss(found.scores),
        "calibration_error": calibration_error(found.scores, settings.calibration_bins),
        "check_agreement": check_agreement(found.checks, settings.mastery_ready_p),
    }


# --- fitting -----------------------------------------------------------------------------------------------------

PFA_GRID = {"mastery_gamma_default": (0.15, 0.25, 0.35, 0.5), "mastery_rho_default": (-0.3, -0.15, -0.05)}
BKT_GRID = {"p_init": (0.1, 0.3, 0.5), "p_transit": (0.05, 0.12, 0.25), "p_slip": (0.05, 0.1, 0.2),
            "p_guess": (0.1, 0.2, 0.3)}  # fmt: skip


def fit_pfa(logs: Sequence[Graded], base: MasteryParams) -> MasteryParams:
    best: tuple[float, MasteryParams] | None = None
    for values in itertools.product(*PFA_GRID.values()):
        candidate = replace(base, **dict(zip(PFA_GRID, values, strict=True)))
        loss = log_loss(replay_pfa(logs, [], candidate).scores)
        if best is None or loss < best[0]:
            best = (loss, candidate)
    assert best is not None
    return best[1]


def fit_bkt(logs: Sequence[Graded], base: Bkt) -> Bkt:
    best: tuple[float, Bkt] | None = None
    for values in itertools.product(*BKT_GRID.values()):
        candidate = Bkt(*values)
        loss = log_loss(replay_bkt(logs, [], candidate).scores)
        if best is None or loss < best[0]:
            best = (loss, candidate)
    return best[1] if best is not None else base


def bakeoff(
    logs: Sequence[Graded], checks: Sequence[Check], settings: Settings, held_out: set[str] | None = None
) -> dict[str, Any]:
    """The LRN-11 bake-off report: every metric per subject for both models on the held-out students, and the choice."""
    students = {g.student for g in logs}
    held = held_out if held_out is not None else held_out_split(students)
    if not held or not students - held:
        raise ValueError("the bake-off needs students on both sides of the split")
    base = MasteryParams.from_settings(settings)
    report: dict[str, Any] = {
        "split": {
            "by": "student",
            "held_out_students": len(held),
            "train_students": len(students - held),
            "sha256": split_hash(held),
        },
        "subjects": {},
    }
    for subject in sorted({g.subject for g in logs}):
        train = [g for g in logs if g.subject == subject and g.student not in held]
        test = [g for g in logs if g.subject == subject and g.student in held]
        test_checks = [c for c in checks if c.subject == subject and c.student in held]
        pfa = fit_pfa(train, base)
        bkt = fit_bkt(train, Bkt.from_params(base))
        found = {"pfa_elo": metrics(replay_pfa(test, test_checks, pfa), settings),
                 "bkt": metrics(replay_bkt(test, test_checks, bkt), settings)}  # fmt: skip
        gain = (found["bkt"]["auc"] or 0.0) - (found["pfa_elo"]["auc"] or 0.0)
        report["subjects"][subject] = {
            **found,
            "choice": "bkt" if gain >= settings.bakeoff_auc_margin else "pfa_elo",
            "fitted": {
                "pfa_elo": {k: getattr(pfa, k) for k in PFA_GRID},
                "bkt": {"p_init": bkt.p_init, "p_transit": bkt.p_transit, "p_slip": bkt.p_slip, "p_guess": bkt.p_guess},
            },
        }
    return report


def report_complete(report: Mapping[str, Any]) -> list[str]:
    """What a bake-off report lacks: every subject must list all four metrics for both models."""
    problems = []
    for subject, row in report.get("subjects", {}).items():
        for model in MODELS:
            for metric in ("auc", "log_loss", "calibration_error", "check_agreement"):
                value = (row.get(model) or {}).get(metric)
                if value is None or (isinstance(value, float) and math.isnan(value)):
                    problems.append(f"{subject}: {model} has no {metric}")
    return problems


# --- the replay gate (LRN-41) -------------------------------------------------------------------------------------


def _main_kc(logs: Sequence[Graded], p: MasteryParams, settings: Settings) -> str | None:
    """The plan's main KC for a student's final state under a parameter file (every KC weighted equally)."""
    ability: dict[str, Ability] = {}
    evidence: dict[str, KcEvidence] = {}
    for row in logs:
        observe(y=int(row.correct), w=1.0, t=row.t_ms, weights={row.kc_id: 1.0}, first_error_kc=None,
                ability=ability.setdefault(row.subject, Ability()), evidence=evidence, p=p,
                b_item=row.b_item)  # fmt: skip
    kcs = {
        kc: planner.KcPlanInfo(kc, row_subject, "learning", kc_probability(ability[row_subject].theta, ev, p, 0.0, kc),
                               1.0)
        for kc, ev in evidence.items()
        for row_subject in [next(g.subject for g in logs if g.kc_id == kc)]
    }  # fmt: skip
    subjects = tuple(planner.SubjectInfo(s, None) for s in sorted({k.subject for k in kcs.values()}))
    plan = planner.plan(planner.PlannerState(subjects, kcs, ()), settings)
    main = next((b for b in plan.blocks if b.kind == "main"), None)
    return main.kc_ids[0] if main is not None else None


def replay_gate(
    current: MasteryParams, candidate: MasteryParams, logs: Sequence[Graded], settings: Settings
) -> dict[str, Any]:
    """Pass only when the candidate's held-out log loss and calibration error are no worse than the current file's."""
    before = replay_pfa(logs, [], current).scores
    after = replay_pfa(logs, [], candidate).scores
    bins = settings.calibration_bins
    found = {
        "current": {"log_loss": log_loss(before), "calibration_error": calibration_error(before, bins)},
        "candidate": {"log_loss": log_loss(after), "calibration_error": calibration_error(after, bins)},
    }
    tolerance = settings.replay_gate_tolerance
    worse = [m for m in ("log_loss", "calibration_error") if found["candidate"][m] > found["current"][m] + tolerance]
    students = sorted({g.student for g in logs})
    changed = sum(
        _main_kc([g for g in logs if g.student == s], current, settings)
        != _main_kc([g for g in logs if g.student == s], candidate, settings)
        for s in students
    )
    return {**found, "passed": not worse, "worse": worse,
            "main_block_changed_share": changed / len(students) if students else 0.0}  # fmt: skip
