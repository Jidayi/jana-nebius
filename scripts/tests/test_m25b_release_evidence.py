"""M25.b release evidence: the S2 gate suite (PRD-13), the claims register (PRD-09), the teacher review (EVL-21), the
journeys on the reference laptops and their usability results (JRN-02). Records here are synthetic and approve
nothing; the candidate's own evidence is read from JANA_M25_EVIDENCE when it exists."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from datetime import date
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from jana_tools import REPO_ROOT
from jana_tools.coverage import acceptance_tests
from jana_tools.journeys.runner import case_id
from jana_tools.journeys.scripts import executable, scripts
from jana_tools.release import s2_evidence, stage

CANDIDATE = "a" * 40
TODAY = date(2026, 10, 16)


def teacher_reviews(when: str = "2026-10-12") -> list[dict[str, Any]]:
    settings = Settings()
    return [
        {
            "subject": subject,
            "reviewed_at": when,
            "reviewers": ["synthetic-teacher-1", "synthetic-teacher-2"],
            "dialogues": settings.teacher_review_dialogues_min,
            "conceptual_answers": settings.teacher_review_conceptual_min,
            "failing_items_reviewed": True,
            "labels_ref": "synthetic-labels",
        }
        for subject in s2_evidence.shipped_subjects()
    ]


def journey_run(hw: str, status: str = "passed") -> dict[str, Any]:
    known = scripts()
    cases = {
        case_id(j, part): status
        for j in executable("S2")
        if j in known
        for part in ("main", *(b.id for b in known[j].branches))
    }
    return {"candidate": CANDIDATE, "laptop_id": f"synthetic-{hw}", "hardware_class": hw, "network": "disabled",
            "egress_attempts": 0, "cases": cases}  # fmt: skip


def usability(rate: tuple[int, int] = (9, 10)) -> list[dict[str, Any]]:
    known = scripts()
    return [
        {"journey": j, "persona": known[j].persona, "stage": "S2", "participants": rate[1],
         "succeeded_without_help": rate[0], "held_at": "2026-10-10", "sessions_ref": "synthetic-sessions"}
        for j in executable("S2") if j in known
    ]  # fmt: skip


def claims_register(*numbers: int) -> dict[str, Any]:
    return {
        "candidate": CANDIDATE,
        "claims": [
            {
                "claim": n,
                "copy_ref": f"synthetic-copy-{n}",
                # Claim 6 rests on the pre-registered pilot analysis, not on an acceptance test.
                "evidence": [t for rid in s2_evidence.CLAIM_REQUIREMENTS[n] for t in acceptance_tests(rid)]
                or ["synthetic-preregistered-analysis"],
                "run_ref": "synthetic-run",
            }
            for n in numbers
        ],
    }


def evl21_recent_teacher_review() -> None:
    """Release reports include the latest teacher review per shipped subject, within the configured window, by two
    teachers over the weekly sample; a missing subject, a stale or thin review refuses the release."""
    settings = Settings()
    assert s2_evidence.teacher_review_errors(teacher_reviews(), today=TODAY, settings=settings) == []
    subjects = s2_evidence.shipped_subjects()
    assert {"mathematics", "physics", "chemistry", "accounting"} <= set(subjects)
    missing = [r for r in teacher_reviews() if r["subject"] != "chemistry"]
    assert s2_evidence.teacher_review_errors(missing, today=TODAY, settings=settings) == [
        "EVL-21: no teacher review for chemistry"
    ]
    stale = teacher_reviews("2026-09-01")
    assert all("days old" in e for e in s2_evidence.teacher_review_errors(stale, today=TODAY, settings=settings))
    # The latest review counts, so an older stale one beside a recent one is fine, and a thin latest one is not.
    assert s2_evidence.teacher_review_errors(stale + teacher_reviews(), today=TODAY, settings=settings) == []
    thin = teacher_reviews()
    thin[0]["dialogues"] = settings.teacher_review_dialogues_min - 1
    assert any("dialogues" in e for e in s2_evidence.teacher_review_errors(thin, today=TODAY, settings=settings))
    one_teacher = teacher_reviews()
    one_teacher[0]["reviewers"] = ["synthetic-teacher-1", "synthetic-teacher-1"]
    assert s2_evidence.teacher_review_errors(one_teacher, today=TODAY, settings=settings)
    strict = Settings(teacher_review_max_age_days=3)
    assert s2_evidence.teacher_review_errors(teacher_reviews(), today=TODAY, settings=strict)


def prd09_claims_have_evidence() -> None:
    """Each claim of the marketing copy register is one of LIST PRD-09b and links passing evidence of this release;
    the release is blocked when any claim lacks it."""
    every = {t: "pass" for n in range(1, 6) for rid in s2_evidence.CLAIM_REQUIREMENTS[n] for t in acceptance_tests(rid)}
    met = [{"metric": m, "status": "met"} for m in s2_evidence.CLAIM_METRICS.values()]
    register = claims_register(1, 2, 3, 4, 5, 6)
    assert s2_evidence.claim_errors(register, candidate=CANDIDATE, results=every, metrics=met) == []
    failing = {**every, acceptance_tests("PRD-03")[0]: "fail"}
    refused = s2_evidence.claim_errors(register, candidate=CANDIDATE, results=failing, metrics=met)
    assert len(refused) == 1 and refused[0].startswith("PRD-09: claim 1")
    unmet = [{**met[0], "status": "unmet"}, met[1]]
    assert any("claim 3" in e for e in s2_evidence.claim_errors(register, candidate=CANDIDATE, results=every,
                                                                metrics=unmet))  # fmt: skip
    unlinked = copy.deepcopy(register)
    unlinked["claims"][1]["evidence"] = ["synthetic-unrelated-run"]
    assert any("does not link" in e for e in s2_evidence.claim_errors(unlinked, candidate=CANDIDATE, results=every,
                                                                      metrics=met))  # fmt: skip
    invented = copy.deepcopy(register)
    invented["claims"].append({**invented["claims"][0], "claim": 7})
    assert s2_evidence.claim_errors(invented, candidate=CANDIDATE, results=every, metrics=met)
    assert s2_evidence.claim_errors(None, candidate=CANDIDATE, results=every, metrics=met) == [
        "PRD-09: no claims register for this release"
    ]
    other = {**register, "candidate": "b" * 40}
    assert s2_evidence.claim_errors(other, candidate=CANDIDATE, results=every, metrics=met)


def jrn02_usability_results_recorded() -> None:
    """Every S2 journey has usability results (participants, success without help) before the gate, from the named
    persona; the stage release refuses without them or below the configured share."""
    settings = Settings()
    assert s2_evidence.usability_errors(usability(), stage="S2", today=TODAY, settings=settings) == []
    assert s2_evidence.usability_errors(usability()[1:], stage="S2", today=TODAY, settings=settings)
    low = s2_evidence.usability_errors(usability((7, 10)), stage="S2", today=TODAY, settings=settings)
    assert low and all("completed without help by 7/10" in e for e in low)
    wrong = usability()
    wrong[0]["persona"] = "P9"
    assert any("participants were P9" in e for e in s2_evidence.usability_errors(wrong, stage="S2", today=TODAY,
                                                                                settings=settings))  # fmt: skip
    late = usability()
    late[0]["held_at"] = "2026-10-20"
    assert s2_evidence.usability_errors(late, stage="S2", today=TODAY, settings=settings)


def test_journey_runs_are_needed_on_every_reference_class() -> None:
    runs = [journey_run(hw) for hw in s2_evidence.CLASSES]
    assert s2_evidence.journey_run_errors(runs, candidate=CANDIDATE, stage="S2") == []
    assert s2_evidence.journey_run_errors(runs[:2], candidate=CANDIDATE, stage="S2") == [
        "PRD-13: no scripted journey run on a high-class reference laptop"
    ]
    failing = journey_run("low")
    failing["cases"]["e2e_jrn05_f2"] = "failed"
    assert any(
        "e2e_jrn05_f2 failed" in e
        for e in s2_evidence.journey_run_errors([failing, *runs[1:]], candidate=CANDIDATE, stage="S2")
    )
    leaky = journey_run("mid")
    leaky["egress_attempts"] = 1
    assert s2_evidence.journey_run_errors([runs[0], leaky, runs[2]], candidate=CANDIDATE, stage="S2")


def test_m25_evidence_folder_feeds_the_s2_release(tmp_path: Path) -> None:
    """`release stage S2 --m25-evidence DIR`: a complete folder adds no failure; a closed pilot needs the journeys
    and teacher reviews but not yet the usability results or claims, which the pilot and the general release bring."""
    for name, records in (("journey-runs", [journey_run(hw) for hw in s2_evidence.CLASSES]),
                          ("teacher-reviews", teacher_reviews()), ("usability", usability())):  # fmt: skip
        (tmp_path / name).mkdir()
        for i, record in enumerate(records):
            (tmp_path / name / f"{i:02d}.json").write_text(json.dumps(record))
    (tmp_path / "claims.json").write_text(json.dumps(claims_register()))
    found = s2_evidence.m25_evidence_errors(tmp_path, candidate=CANDIDATE, results={}, metrics=[], today=TODAY,
                                            settings=Settings())  # fmt: skip
    assert found == {"journeys": [], "teacher_review": [], "usability": [], "claims": []}
    pilot = s2_evidence.m25_evidence_errors(None, candidate=CANDIDATE, results={}, metrics=[], today=TODAY,
                                            settings=Settings(), closed_pilot=True)  # fmt: skip
    assert set(pilot) == {"journeys"} and pilot["journeys"]


def prd13_s2_gate_suite() -> None:
    """The S2 release candidate passes the S2 release gates (TABLE EVL-17a and the TABLE PRD-17a gate rows) offline on
    the three reference laptops, with the scripted journeys passing on each. The evidence is the candidate's own
    (the device lab and the frozen release runs), read from JANA_M25_EVIDENCE: s2-dossier.json, report.json and the
    M25 folder. The gate machinery itself is covered by test_s2_release.py and the tests above."""
    source = os.environ.get("JANA_M25_EVIDENCE")
    if not source:
        pytest.skip("prd13_s2_gate_suite: needs the candidate's S2 dossier and reference-laptop journey runs "
                    "(device lab, EVL-14); set JANA_M25_EVIDENCE to their folder")  # fmt: skip
    from jana_tools.release.evaluation import s2_gates

    folder = Path(source)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, text=True).strip()
    report = json.loads((folder / "report.json").read_text())
    dossier = json.loads((folder / "s2-dossier.json").read_text())
    assert report["build"]["commit"] == head, "the evidence belongs to another candidate"
    register = json.loads((REPO_ROOT / "docs/specification/registers/decisions.json").read_text())
    decisions = {d["id"]: d["status"] for d in register["decisions"]}
    failing = [f"{g.metric}: {g.measured}" for g in s2_gates(report, evidence=dossier, decisions=decisions)
               if not g.passed]  # fmt: skip
    rows = stage.exit_metrics("S2", report, None, None, evidence=dossier)
    failing += [f"{r['metric']}: {r['measured']}" for r in rows if r["kind"] == stage.RELEASE_GATE
                and r["status"] != "met"]  # fmt: skip
    runs = [json.loads(p.read_text()) for p in sorted((folder / "journey-runs").glob("*.json"))]
    failing += s2_evidence.journey_run_errors(runs, candidate=head, stage="S2")
    assert not failing, failing
