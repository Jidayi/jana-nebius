"""The S2 release evidence beyond the frozen suites (M25): the scripted journeys on every reference laptop (JRN-02,
PRD-13), the usability results per journey (JRN-02), the latest teacher review per shipped subject (EVL-21) and the
claims register (PRD-09). Each is a governance record (contract-additions-gates.json until adopted); every check
returns the reasons a release is refused, and an empty list only when the evidence is present and passing.

`release stage S2 --m25-evidence DIR` reads DIR/journey-runs/*.json, DIR/usability/*.json,
DIR/teacher-reviews/*.json and DIR/claims.json.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from ..spec import DOCS

CLASSES = ("low", "mid", "high")
# LIST PRD-09b: each permitted claim and the acceptance evidence it needs from the current release. Claim 3 also
# needs the withholding exit row met, claim 6 the pre-registered learning-gain row (TABLE PRD-17a).
CLAIM_REQUIREMENTS: dict[int, tuple[str, ...]] = {
    1: ("PRD-03",),
    2: ("PRD-05",),
    3: ("PRD-06",),
    4: ("CUR-31",),
    5: ("PRD-07", "PRD-21"),
    6: (),
}
CLAIM_METRICS = {
    3: "Guided mode withholds the answer until earned",
    6: "Learning gain versus comparison classes, 8 to 12 weeks",
}


def _load_folder(folder: Path) -> list[Any]:
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


def shipped_subjects(stage: str = "S2") -> list[str]:
    from ..kc_coverage import SUBJECTS, launched

    return sorted({SUBJECTS[code] for code, _ in launched(stage)})


def teacher_review_errors(records: list[Any], *, today: date, settings: Any, stage: str = "S2") -> list[str]:
    """EVL-21: for every shipped subject, the latest teacher review is dated within the configured window, by two
    distinct teachers, over at least the weekly sample, with every failing item reviewed."""
    from ..m23.records import errors as format_errors

    errors = [e for r in records for e in format_errors("teacher_review", r)]
    valid = [r for r in records if not format_errors("teacher_review", r)]
    for subject in shipped_subjects(stage):
        mine = sorted((r for r in valid if r["subject"] == subject), key=lambda r: r["reviewed_at"])
        if not mine:
            errors.append(f"EVL-21: no teacher review for {subject}")
            continue
        latest = mine[-1]
        age = (today - date.fromisoformat(latest["reviewed_at"])).days
        if not 0 <= age <= settings.teacher_review_max_age_days:
            errors.append(f"EVL-21: the latest {subject} review is {age} days old "
                          f"(at most {settings.teacher_review_max_age_days})")  # fmt: skip
        if latest["dialogues"] < settings.teacher_review_dialogues_min:
            errors.append(f"EVL-21: the {subject} review sampled {latest['dialogues']} dialogues "
                          f"(at least {settings.teacher_review_dialogues_min})")  # fmt: skip
        if latest["conceptual_answers"] < settings.teacher_review_conceptual_min:
            errors.append(f"EVL-21: the {subject} review sampled {latest['conceptual_answers']} conceptual answers "
                          f"(at least {settings.teacher_review_conceptual_min})")  # fmt: skip
    return errors


def usability_errors(records: list[Any], *, stage: str, today: date, settings: Any) -> list[str]:
    """JRN-02: every journey of the stage has usability results recorded before the gate, with the named persona,
    and at least the configured share of its participants completed it without help."""
    from ..journeys.scripts import executable, scripts
    from ..m23.records import errors as format_errors

    errors = [e for r in records for e in format_errors("usability", r)]
    valid = [r for r in records if not format_errors("usability", r)]
    known = scripts()
    for journey in executable(stage):
        if journey not in known:
            continue  # its missing script is jrn02_journey_suite_complete's failure
        mine = [r for r in valid if r["journey"] == journey and r["stage"] == stage]
        if not mine:
            errors.append(f"JRN-02: no usability results for {journey}")
            continue
        latest = max(mine, key=lambda r: r["held_at"])
        if latest["persona"] != known[journey].persona:
            errors.append(f"JRN-02: {journey} usability participants were {latest['persona']}, "
                          f"not {known[journey].persona}")  # fmt: skip
        if date.fromisoformat(latest["held_at"]) > today:
            errors.append(f"JRN-02: {journey} usability results are dated after the gate")
        share = latest["succeeded_without_help"] / latest["participants"]
        if latest["succeeded_without_help"] > latest["participants"] or share < settings.exit_s2_task_success:
            errors.append(f"JRN-02: {journey} completed without help by {latest['succeeded_without_help']}/"
                          f"{latest['participants']} (at least {settings.exit_s2_task_success:.0%})")  # fmt: skip
    return errors


def journey_run_errors(records: list[Any], *, candidate: str, stage: str) -> list[str]:
    """JRN-02, PRD-13: the scripted journeys pass, with networking disabled, on a laptop of every reference class."""
    from ..journeys.runner import record_errors
    from ..journeys.scripts import executable, scripts

    known = scripts()
    journeys = [j for j in executable(stage) if j in known]
    errors = []
    for hw in CLASSES:
        runs = [r for r in records if isinstance(r, dict) and r.get("hardware_class") == hw]
        if not runs:
            errors.append(f"PRD-13: no scripted journey run on a {hw}-class reference laptop")
        for run in runs:
            errors += record_errors(run, known, journeys, candidate)
    return errors


def claim_errors(register: Any, *, candidate: str, results: dict[str, str], metrics: list[dict[str, Any]],
                 docs: Path = DOCS) -> list[str]:  # fmt: skip
    """PRD-09: every claim in the release's marketing copy register is one of LIST PRD-09b and is backed by passing
    evidence of this release: the acceptance tests of its requirements and, for claims 3 and 6, the exit rows."""
    from ..coverage import acceptance_tests
    from ..m23.records import errors as format_errors
    from ..product import _list_items, _vision

    if register is None:
        return ["PRD-09: no claims register for this release"]
    errors = format_errors("claims_register", register)
    if errors:
        return [f"PRD-09: {e}" for e in errors]
    permitted = (
        len(json.loads((REPO_ROOT / "contracts/policies/claims.json").read_text())["claims"])
        if docs == DOCS
        else len(_list_items(_vision(docs), "LIST PRD-09b"))
    )
    if permitted != len(CLAIM_REQUIREMENTS):
        errors.append(f"PRD-09: LIST PRD-09b has {permitted} claims; the check knows {len(CLAIM_REQUIREMENTS)}")
    if register["candidate"] != candidate:
        errors.append("PRD-09: the claims register belongs to another candidate")
    rows = {m["metric"]: m for m in metrics}
    for claim in register["claims"]:
        number = claim["claim"]
        tests = [t for rid in CLAIM_REQUIREMENTS[number] for t in acceptance_tests(rid, docs)]
        failing = [t for t in tests if results.get(t) != "pass"]
        if failing:
            errors.append(f"PRD-09: claim {number} ({claim['copy_ref']}) lacks passing evidence: {', '.join(failing)}")
        metric = CLAIM_METRICS.get(number)
        if metric and rows.get(metric, {}).get("status") != "met":
            errors.append(f"PRD-09: claim {number} ({claim['copy_ref']}) needs '{metric}' met in this release")
        unlinked = [t for t in tests if t not in claim["evidence"]]
        if unlinked:
            errors.append(f"PRD-09: claim {number} ({claim['copy_ref']}) does not link {', '.join(unlinked)}")
    return errors


def m25_evidence_errors(folder: Path | None, *, candidate: str, results: dict[str, str],
                        metrics: list[dict[str, Any]], today: date, settings: Any, stage: str = "S2",
                        closed_pilot: bool = False) -> dict[str, list[str]]:  # fmt: skip
    """Every M25 release check over the evidence folder, by category. A closed pilot (PRD-11) needs the journeys on
    the reference laptops and the teacher reviews; usability results are measured in the pilot, so they and the
    claims of a general release wait for it."""
    if folder is None:
        missing = ["M25: no release evidence folder (--m25-evidence)"]
        return {"journeys": missing} if closed_pilot else {"journeys": missing, "claims": missing}
    claims_file = folder / "claims.json"
    found = {
        "journeys": journey_run_errors(_load_folder(folder / "journey-runs"), candidate=candidate, stage=stage),
        "teacher_review": teacher_review_errors(
            _load_folder(folder / "teacher-reviews"), today=today, settings=settings, stage=stage
        ),
    }
    if not closed_pilot:
        found["usability"] = usability_errors(_load_folder(folder / "usability"), stage=stage, today=today,
                                              settings=settings)  # fmt: skip
        register = json.loads(claims_file.read_text()) if claims_file.is_file() else None
        found["claims"] = claim_errors(register, candidate=candidate, results=results, metrics=metrics)
    return found
