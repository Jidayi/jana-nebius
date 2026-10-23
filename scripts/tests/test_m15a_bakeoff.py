"""LRN-11 and LRN-41: the BKT baseline bake-off and the replay gate, on synthetic logs (no held-out log is ever
committed; these students and answers are generated here)."""

from __future__ import annotations

import math
import random
from dataclasses import replace

from agent_core.config import Settings
from agent_core.learner.mastery import MasteryParams
from jana_tools.learner_eval import (
    Check,
    Graded,
    auc,
    bakeoff,
    calibration_error,
    held_out_split,
    log_loss,
    replay_gate,
    report_complete,
    split_hash,
)

DAY_MS = 86_400_000
SUBJECTS = {"mathematics": "mth", "physics": "phy"}


def synthetic_logs(seed: int, students: int = 60, kcs: int = 4, steps: int = 14) -> tuple[list[Graded], list[Check]]:
    """Students who learn: each KC's success chance rises with practice from a personal start; a mastery check at the
    end passes when the final chance is high."""
    rng = random.Random(seed)  # noqa: S311 - reproducible synthetic logs
    logs: list[Graded] = []
    checks: list[Check] = []
    for s in range(students):
        student = f"stu{s:03d}"
        for subject, code in SUBJECTS.items():
            start = rng.gauss(-0.5, 1.0)
            for k in range(kcs):
                kc = f"kc.{code}.o.synthetic.skill_{k}"
                skill = start + rng.gauss(0, 0.5)
                t = s * 1000 + k * 37 * DAY_MS // 100
                for _ in range(steps):
                    chance = 1 / (1 + math.exp(-skill))
                    correct = rng.random() < chance
                    logs.append(Graded(student, subject, kc, correct, t))
                    skill += 0.35 if correct else 0.15
                    t += rng.randint(1, 3) * DAY_MS // 4
                checks.append(Check(student, subject, kc, t + 1, rng.random() < 1 / (1 + math.exp(-skill))))
    return logs, checks


def lrn11_bakeoff_report_complete() -> None:
    settings = Settings()
    logs, checks = synthetic_logs(11)
    students = {g.student for g in logs}
    held = held_out_split(students)
    report = bakeoff(logs, checks, settings, held)
    assert report_complete(report) == [], report_complete(report)
    assert set(report["subjects"]) == set(SUBJECTS)
    for subject, row in report["subjects"].items():
        for model in ("pfa_elo", "bkt"):
            found = row[model]
            assert 0.5 < found["auc"] <= 1 and found["log_loss"] > 0, (subject, model)
            assert 0 <= found["calibration_error"] <= 1 and 0 <= found["check_agreement"] <= 1
        assert row["choice"] in ("pfa_elo", "bkt")
        gain = row["bkt"]["auc"] - row["pfa_elo"]["auc"]
        assert (row["choice"] == "bkt") == (gain >= settings.bakeoff_auc_margin), "pfa_elo wins under the margin"
    split = report["split"]
    assert split["by"] == "student" and split["sha256"] == split_hash(held)
    assert split["held_out_students"] == len(held) and split["train_students"] == len(students - held)
    assert 0 < len(held) < len(students), "students on both sides, none on both"
    # The same frozen split gives the same report; a different split is visible in its hash.
    assert bakeoff(logs, checks, settings, held) == report
    other = set(sorted(students)[: len(held)])
    assert bakeoff(logs, checks, settings, other)["split"]["sha256"] != split["sha256"]
    # An incomplete report is caught.
    broken = {"subjects": {"physics": {"pfa_elo": {**report["subjects"]["physics"]["pfa_elo"], "auc": None},
                                       "bkt": report["subjects"]["physics"]["bkt"]}}}  # fmt: skip
    assert report_complete(broken) == ["physics: pfa_elo has no auc"]


def test_metrics_on_known_cases() -> None:
    assert auc([(0.9, True), (0.8, True), (0.2, False), (0.1, False)]) == 1.0
    assert auc([(0.5, True), (0.5, False)]) == 0.5
    assert auc([(0.5, True)]) is None
    assert log_loss([(0.5, True), (0.5, False)]) == math.log(2)
    assert calibration_error([(0.25, False), (0.25, True), (0.75, True), (0.75, True)], 10) == 0.25


def lrn41_replay_gate() -> None:
    settings = Settings()
    logs, _ = synthetic_logs(41, students=30)
    held = held_out_split({g.student for g in logs}, share=0.5)
    held_logs = [g for g in logs if g.student in held]
    current = MasteryParams.from_settings(settings)
    same = replay_gate(current, current, held_logs, settings)
    assert same["passed"] and same["worse"] == [] and same["main_block_changed_share"] == 0.0
    worse = replace(current, mastery_gamma_default=-0.4, mastery_rho_default=0.6)  # learning counted backwards
    gated = replay_gate(current, worse, held_logs, settings)
    assert not gated["passed"] and "log_loss" in gated["worse"]
    assert gated["candidate"]["log_loss"] > gated["current"]["log_loss"]
    assert 0 < gated["main_block_changed_share"] <= 1, "the report says how many students' main block changes"
    # Within the configured tolerance a slightly worse file passes; with none it does not.
    slight = replace(current, mastery_gamma_default=current.mastery_gamma_default + 0.02)
    found = replay_gate(current, slight, held_logs, settings)
    if found["worse"]:
        loose = settings.model_copy(update={"replay_gate_tolerance": 0.1})
        assert replay_gate(current, slight, held_logs, loose)["passed"]
