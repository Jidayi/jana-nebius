"""Synthetic evidence only: S2 must block missing, stale, pooled, malformed or failing measurements."""

from __future__ import annotations

import copy
import json
import subprocess

import pytest
from jana_tools import REPO_ROOT
from jana_tools.harness import report as rep
from jana_tools.release import bakeoff, evaluation, prompts
from test_m7b_devlab import _results

CANDIDATE = "a" * 40


def evidence_fixture():
    suites = {m.suite for m in evaluation.MEASURES} | {"perception", "bakeoff"}
    locks = {name: {"version": "synthetic-1", "files": {}} for name in suites}
    reports = []
    for hw in [*evaluation.CLASSES, "content_only"]:
        by_suite = {}
        for name in suites:
            criteria = {m.criterion: rep.result(1000, 1000) for m in evaluation.MEASURES if m.suite == name}
            if name in ("pedagogy_rubric", "teacher_review"):
                criteria = {f"{key}:{judge}": value for key, value in criteria.items() for judge in ("first", "second")}
            if name == "perception":
                criteria = {key: rep.result(200, 200) for key in ("camera_exact", "accepted_regions_exact")}
            if name == "bakeoff":
                criteria = {
                    f"structured_first_pass:{p.stem}": rep.result(1000, 1000)
                    for p in (REPO_ROOT / "content/agent/roles").rglob("*.md")
                }
            criteria["held_out"] = rep.result(1000, 1000)
            if name == "safety":
                criteria["no_answer_leak"] = rep.result(1000, 1000)
            by_suite[name] = {
                "version": locks[name]["version"],
                "lock_sha256": rep.lock_sha256(locks[name]),
                "split": "held_out",
                "status": "ran",
                "result": rep.result(1000, 1000),
                "criteria": criteria,
            }
        reports.append(
            {
                "report_version": 1,
                "run_id": f"synthetic-{hw}",
                "mode": "release",
                "created_at": "2026-10-15T00:00:00Z",
                "build": {"app_version": "0.0.0", "commit": CANDIDATE, "stage": "S2"},
                "models": [],
                "fingerprints": {"prompts": {}, "skills": {}},
                "hardware": {"hardware_class": hw, "os": "synthetic", "arch": "synthetic", "ram_gb": 16},
                "network": {"state": "disabled", "egress_attempts": 0},
                "seeds": [1, 2, 3],
                "suites": by_suite,
                "cases": [],
                "diff": {"against": None},
                "valid": True,
                "eval_only_paths": [],
            }
        )
    minimums = {f"{m.suite}.{m.criterion}": 1 for m in evaluation.MEASURES}
    minimums.update(
        {
            "perception.camera_exact": 200,
            "perception.accepted_regions_exact": 1,
            "bakeoff.structured_first_pass": 100,
            "scenarios.network_cut": 1,
        }
    )
    cuts = copy.deepcopy(reports[:3])
    for report in cuts:
        report["network"]["state"] = "enabled"
        report["suites"]["scenarios"]["criteria"]["network_cut"] = rep.result(10, 10)
    dossier = {
        "version": 1,
        "candidate": CANDIDATE,
        "reports": reports,
        "minimums": minimums,
        "minimums_registered_at": "2026-10-14T00:00:00Z",
        "network_cuts": cuts,
        "judges": {key: ["first", "second"] for key in ("pedagogy_rubric", "teacher_review")},
        "devices": [
            {
                "candidate": CANDIDATE,
                "hardware_class": hw,
                "network": "disabled",
                "egress_attempts": 0,
                "all_gates_enabled": True,
                "runs": {metric: [0.5] * 22 for metric in ("first_text_s", "restatement_s", "step_s")},
            }
            for hw in evaluation.CLASSES
        ],
        "mastery": {
            "candidate": CANDIDATE,
            "subjects": {
                "synthetic": {
                    "ece": 0.05,
                    "ready_to_check": rep.result(60, 100),
                    "held_out": True,
                    "log_kind": "synthetic",
                    "model": "pfa_elo",
                    "parameter_replay_no_worse": True,
                }
            },
        },
    }
    return dossier, locks


def gates(dossier, locks, monkeypatch):
    # Bake-off provenance has its own non-mocked tests below. Here isolate table arithmetic and evidence context.
    monkeypatch.setattr(bakeoff, "record_errors", lambda *a, **k: [])
    return evaluation.s2_gates(
        dossier["reports"][0], evidence=dossier, locks=locks, decisions={"D6": "decided", "D25": "decided"}
    )


def test_s2_covers_table_without_silently_claiming_s3_acceptance(monkeypatch):
    dossier, locks = evidence_fixture()
    rows = gates(dossier, locks, monkeypatch)
    assert len(rows) >= 48
    assert all(row.passed for row in rows), [(r.metric, r.measured) for r in rows if not r.passed]
    assert not any("Voice" in row.metric or "handwritten" in row.metric for row in rows)
    assert all(not row.passed for row in evaluation.s2_gates({}))


@pytest.mark.parametrize("metric", evaluation.MEASURES, ids=lambda m: m.metric)
def test_each_rate_or_count_gate_blocks_its_own_failure(metric, monkeypatch):
    dossier, locks = evidence_fixture()
    report = dossier["reports"][3 if metric.suite == "content_only" else 0]
    suite = report["suites"][metric.suite]
    if metric.criterion == "all":
        suite["result"] = rep.result(0, 1000)
    else:
        key = metric.criterion + (":first" if metric.suite in ("pedagogy_rubric", "teacher_review") else "")
        suite["criteria"][key] = rep.result(0, 1000)
    assert not next(row for row in gates(dossier, locks, monkeypatch) if row.metric == metric.metric).passed


@pytest.mark.parametrize(
    "change",
    [
        "stale",
        "lock",
        "egress",
        "skipped",
        "minimum",
        "empty",
        "duplicate",
        "nan",
        "device_gates",
        "teacher",
        "role",
        "late_registration",
    ],
)
def test_bad_evidence_cannot_be_hidden_by_other_passing_classes(change, monkeypatch):
    dossier, locks = evidence_fixture()
    report = dossier["reports"][0]
    if change == "stale":
        report["build"]["commit"] = "b" * 40
    elif change == "lock":
        report["suites"]["marking"]["lock_sha256"] = "b" * 64
    elif change == "egress":
        report["network"]["egress_attempts"] = 1
    elif change == "skipped":
        report["suites"]["marking"]["status"] = "delegated"
    elif change == "minimum":
        dossier["minimums"].pop("marking.first_wrong_line")
    elif change == "empty":
        report["suites"]["safety"]["criteria"]["critical"] = rep.result(0, 0)
    elif change == "duplicate":
        dossier["reports"].append(copy.deepcopy(report))
    elif change == "nan":
        dossier["devices"][0]["runs"]["first_text_s"][0] = float("nan")
    elif change == "device_gates":
        dossier["devices"][0]["all_gates_enabled"] = False
    elif change == "teacher":
        dossier["judges"]["teacher_review"] = ["same", "same"]
    elif change == "role":
        report["suites"]["bakeoff"]["criteria"].pop("structured_first_pass:coach")
    else:
        dossier["minimums_registered_at"] = "2026-10-16T00:00:00Z"
    assert any(not row.passed for row in gates(dossier, locks, monkeypatch))


def test_mastery_gate_asks_for_no_bkt_comparison(monkeypatch):
    """D25 (decided in D100): the mastery row passes on pfa_elo with a no-worse parameter replay (LRN-41) and no
    bake-off choice or BKT metrics; a subject on another model, a worse replay or an undecided D25 still fails it."""
    dossier, locks = evidence_fixture()
    row = dossier["mastery"]["subjects"]["synthetic"]
    assert not {"chosen_model", "bkt", "choice"} & set(row)

    def mastery_row(decisions=None):
        monkeypatch.setattr(bakeoff, "record_errors", lambda *a, **k: [])
        found = evaluation.s2_gates(dossier["reports"][0], evidence=dossier, locks=locks,
                                    decisions=decisions or {"D6": "decided", "D25": "decided"})  # fmt: skip
        return next(r for r in found if r.metric.startswith("Mastery parameter replay"))

    assert mastery_row().passed
    assert "BKT" in mastery_row().metric and "bake-off" not in mastery_row().metric
    for change in ({"model": "bkt"}, {"parameter_replay_no_worse": False}, {"model": None}):
        dossier["mastery"]["subjects"]["synthetic"] = {**row, **change}
        assert not mastery_row().passed, change
    dossier["mastery"]["subjects"]["synthetic"] = row
    assert not mastery_row({"D6": "decided", "D25": "proposed"}).passed


def test_bakeoff_wrapper_rejects_wrong_context_and_missing_class_confirmation():
    results = _results()
    for result in results.values():
        result["tiers"] = ["fast", "strong", "judge"]
    record = bakeoff.record(
        results,
        candidate=CANDIDATE,
        run_id="synthetic-bakeoff",
        created_at="2026-10-15T00:00:00Z",
        weights_fixed_at="2026-10-14T00:00:00Z",
    )
    assert bakeoff.record_errors(record, candidate=CANDIDATE) == []
    assert bakeoff.record_errors(record, candidate="b" * 40)
    record["report"]["held_out_confirmation"]["fast"]["low"]["confirmed"] = False
    assert bakeoff.record_errors(record)
    record["report"] = {}
    assert bakeoff.record_errors(record)


def test_outcome_only_prompt_record_cannot_clear_production_release(tmp_path):
    agent = tmp_path / "agent"
    (agent / "roles/auxiliary").mkdir(parents=True)
    (agent / "roles/auxiliary/guard.md").write_text('version: "0.1"\nSynthetic guard')
    log = tmp_path / "runs.jsonl"
    prompts.record_run(agent, dict.fromkeys(prompts.REQUIRED_SUITES, "passed"), log, run_id="synthetic")
    assert "roles/auxiliary/guard.md" in prompts.current_files(agent)
    assert prompts.verified_release_errors(agent, log)


def test_prompt_record_proves_committed_prompt_bytes_and_detects_late_version_bypass(tmp_path):
    root = tmp_path / "repo"
    agent = root / "content/agent"
    (agent / "roles").mkdir(parents=True)
    role = agent / "roles/coach.md"
    role.write_text('version: "0.1"\nSynthetic prompt')
    dossier, locks = evidence_fixture()
    (root / "evals").mkdir()
    (root / "evals/lock.json").write_text(json.dumps({"suites": locks}))

    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "synthetic@example.invalid")
    git("config", "user.name", "Synthetic test")
    git("add", ".")
    git("commit", "-qm", "Synthetic fixture")
    candidate = git("rev-parse", "HEAD")
    reports = dossier["reports"][:3]
    for report in reports:
        report["build"]["commit"] = candidate
    log = root / "evals/prompt-runs.jsonl"
    prompts.record_evaluated_run(
        agent, reports, candidate=candidate, run_id="synthetic-prompts", date="2026-10-15", runs=log, root=root
    )
    assert prompts.verified_release_errors(agent, log, candidate=candidate, root=root) == []
    role.write_text('version: "0.1"\nChanged prompt')
    with pytest.raises(ValueError, match="prompt bytes"):
        prompts.record_evaluated_run(
            agent, reports, candidate=candidate, run_id="dirty", date="2026-10-15", runs=log, root=root
        )
    git("add", "content")
    git("commit", "-qm", "Synthetic missing version bump")
    candidate = git("rev-parse", "HEAD")
    for report in reports:
        report["build"]["commit"] = candidate
    prompts.record_evaluated_run(
        agent, reports, candidate=candidate, run_id="new-commit", date="2026-10-15", runs=log, root=root
    )
    assert any("version bump" in e for e in prompts.verified_release_errors(agent, log, root=root))


def test_s2_cli_uses_s2_rows_and_cannot_tag_from_s1_only_evidence(capsys):
    from jana_tools.__main__ import main

    before = subprocess.run(["git", "tag"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    assert main(["release", "stage", "S2", "--tag", "v0.0.0-s2-test-must-not-exist"]) == 1
    out = capsys.readouterr()
    assert "Method marks agree with teacher marking" in out.out
    assert "camera_exact@low" in out.out
    assert "gates:" in out.err
    after = subprocess.run(["git", "tag"], cwd=REPO_ROOT, capture_output=True, text=True, check=True).stdout
    assert before == after


def test_held_out_regression_cannot_hide_inside_a_passing_suite_aggregate():
    from jana_tools.release.stage import held_out_drop_failures

    previous = {
        "suites": {
            "scenarios": {
                "split": "held_out",
                "result": rep.result(1000, 1000),
                "criteria": {"held_out": rep.result(1000, 1000), "withheld": rep.result(200, 200)},
            }
        }
    }
    current = copy.deepcopy(previous)
    current["suites"]["scenarios"]["criteria"]["withheld"] = rep.result(160, 200)
    assert any("scenarios.withheld" in error for error in held_out_drop_failures(current, previous, 2))


def test_signature_gate_reads_what_the_marking_suite_writes(monkeypatch):
    """TABLE EVL-17a "Misconception signatures match labelled answers" (CUR-18): the S2 gate reads the criterion the
    harness's marking suite writes for the seeded misconception set, so a real run's counts reach the gate."""
    from jana_tools.harness import run as harness

    monkeypatch.setitem(harness.PROGRAMMATIC, "marking", harness._marking_golden_cases)  # the seeded set only
    report = harness.run(mode="development", build_stage="S2", only={"marking"})
    [measure] = [m for m in evaluation.MEASURES if m.metric == "Misconception signatures match labelled answers"]
    [row] = evaluation._criteria([report], measure.suite, measure.criterion, report["hardware"]["hardware_class"])
    passed, total = evaluation.counts(row)
    assert total > 0 and passed / total >= measure.threshold
    gate = evaluation._sample(measure, [row], 1, measure.suite)
    assert gate.passed and gate.measured == f"{passed}/{total}"


def test_s2_exit_metrics_read_the_dossier_per_reference_class():
    """TABLE PRD-17a S2 release-gate rows come from the candidate's frozen release reports, class by class: a failing
    class fails the row whatever the others measure, and a stale or foreign report counts as no evidence."""
    from jana_tools.release.stage import RELEASE_GATE, exit_metrics

    dossier, locks = evidence_fixture()
    report = dossier["reports"][0]

    def gate_rows(evidence):
        rows = exit_metrics("S2", report, None, None, evidence=evidence, locks=locks)
        return {r["metric"]: r for r in rows if r["kind"] == RELEASE_GATE}

    rows = gate_rows(dossier)
    assert [r["status"] for r in rows.values()] == ["met", "met", "met"]
    measured = rows["Final answer correct on tool-checkable items"]["measured"]
    assert measured == "low 1000/1000; mid 1000/1000; high 1000/1000"
    failing = copy.deepcopy(dossier)
    failing["reports"][1]["suites"]["simulated_students"]["criteria"]["withheld_until_earned"] = rep.result(900, 1000)
    assert gate_rows(failing)["Guided mode withholds the answer until earned"]["status"] == "unmet"
    unsafe = copy.deepcopy(dossier)
    unsafe["reports"][2]["suites"]["safety"]["criteria"]["critical"] = rep.result(999, 1000)
    assert gate_rows(unsafe)["Critical safety items handled correctly"]["status"] == "unmet"
    stale = copy.deepcopy(dossier)
    stale["reports"][0]["build"]["commit"] = "b" * 40
    assert {r["status"] for r in gate_rows(stale).values()} == {"unmet"}
    absent = copy.deepcopy(dossier)
    absent["reports"] = [r for r in absent["reports"] if r["hardware"]["hardware_class"] != "high"]
    assert "high" in gate_rows(absent)["Final answer correct on tool-checkable items"]["measured"]
    assert {r["status"] for r in gate_rows({}).values()} == {"missing"}
