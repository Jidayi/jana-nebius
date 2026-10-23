"""The pedagogy rubric and its judges (EVL-05, EVL-06).

A rubric (`evals/rubrics/*.yaml`, contract `evals/rubric`) holds binary criteria written as "PASS if …" and
"FAIL if …", frozen before the runs it grades: the suite lock refuses an edit without a version bump (EVL-18), and a
grading record carries the rubric's sha256, so an edited rubric cannot grade under an old version.

Two judges grade every excerpt independently (neither sees the other's verdict). Agreement is the verdict; a
disagreement goes to a teacher's queue and counts as FAIL until a teacher resolves it; a judge error is a FAIL; a
criterion that does not apply is not counted. A critical criterion failing fails the run. The report gives the
criterion pass rate, the all-pass rate, per-criterion rates and the judges' agreement, each with a Wilson 95% interval.

A judge grades only with a passing calibration record for this rubric version, its pinned model, quantisation and
prompt hash: agreement with the teachers' majority label on at least `eval_judge_calibration_excerpts` labelled
excerpts, at least `eval_judge_min_agreement` on every critical criterion. The model under test never judges its own
outputs. Judges run in the evaluation environment only, never on a student device."""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT

RUBRICS = REPO_ROOT / "evals" / "rubrics"
CALIBRATION = RUBRICS / "calibration"
PROMPT = RUBRICS / "judge-prompt.md"
VERDICTS = ("pass", "fail", "n/a")
Judge = Callable[[dict[str, Any], str], str]  # (criterion, excerpt) -> pass | fail | n/a; raising is a judge error


class RubricError(ValueError):
    pass


class UncalibratedJudge(PermissionError):
    pass


@dataclass(frozen=True)
class Rubric:
    data: dict[str, Any]
    sha256: str

    @property
    def id(self) -> str:
        return str(self.data["id"])

    @property
    def version(self) -> str:
        return str(self.data["version"])

    @property
    def criteria(self) -> list[dict[str, Any]]:
        return list(self.data["criteria"])

    def judge_pin(self, ref: str) -> dict[str, Any]:
        for judge in self.data["judging"]["judges"]:
            if judge["ref"] == ref:
                return dict(judge)
        raise RubricError(f"{ref} is not a judge of {self.id}")


def load_rubric(path: Path) -> Rubric:
    from agent_core.contracts import errors as contract_errors

    raw = path.read_bytes()
    data = yaml.safe_load(raw)
    problems = contract_errors("evals/rubric", data)
    if problems:
        raise RubricError(f"{path.name}: {problems[0]}")
    if len({c["id"] for c in data["criteria"]}) != len(data["criteria"]):
        raise RubricError(f"{path.name}: criterion ids repeat")
    return Rubric(data, hashlib.sha256(raw).hexdigest())


def judge_prompt(criterion: dict[str, Any], excerpt: str, template: str | None = None) -> str:
    text = template if template is not None else PROMPT.read_text()
    for key, value in (("criterion_id", criterion["id"]), ("pass_if", criterion["pass_if"]),
                       ("fail_if", criterion["fail_if"]), ("applies_when", f"Applies when: {criterion['applies_when']}"
                                                            if criterion.get("applies_when") else ""),
                       ("excerpt", excerpt.replace("</excerpt>", "&lt;/excerpt&gt;"))):  # fmt: skip
        text = text.replace("{" + key + "}", str(value))
    return text


def prompt_sha256(path: Path = PROMPT) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def wilson(passed: int, total: int, z: float = 1.96) -> tuple[float, float]:
    """The Wilson score interval for a proportion (95% by default)."""
    if total == 0:
        return (0.0, 1.0)
    p = passed / total
    centre = (p + z * z / (2 * total)) / (1 + z * z / total)
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / (1 + z * z / total)
    return (round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4))


# --- calibration (EVL-06) --------------------------------------------------------------------------------------------


def _slug(ref: str) -> str:
    return "".join(c if c.isalnum() or c in "-." else "_" for c in ref)


def calibration_path(rubric: Rubric, ref: str, folder: Path = CALIBRATION) -> Path:
    return folder / f"{rubric.id}.{_slug(ref)}.json"


def calibrate(rubric: Rubric, ref: str, judge: Judge, labelled: Sequence[dict[str, Any]], *, quantisation: str,
              folder: Path = CALIBRATION, settings: Any = None) -> dict[str, Any]:  # fmt: skip
    """Grade the teacher-labelled excerpts with one judge and record its agreement with the teachers' majority, per
    criterion. `labelled` rows: {excerpt_id, excerpt, criterion, labels: [pass|fail|n/a, ...]} from teachers."""
    from agent_core.config import Settings

    settings = settings or Settings()
    pin = rubric.judge_pin(ref)
    by_id = {c["id"]: c for c in rubric.criteria}
    agree: Counter[str] = Counter()
    seen: Counter[str] = Counter()
    for row in labelled:
        majority, count = Counter(row["labels"]).most_common(1)[0]
        if count * 2 <= len(row["labels"]):
            continue  # no teacher majority: the excerpt does not calibrate anything
        try:
            verdict = judge(by_id[row["criterion"]], row["excerpt"])
        except Exception:
            verdict = "error"
        seen[row["criterion"]] += 1
        agree[row["criterion"]] += int(verdict == majority)
    excerpts = len({row["excerpt_id"] for row in labelled})
    rates = {c: round(agree[c] / seen[c], 4) for c in seen}
    critical = [c["id"] for c in rubric.criteria if c["critical"]]
    passed = excerpts >= settings.eval_judge_calibration_excerpts and all(
        rates.get(c, 0.0) >= settings.eval_judge_min_agreement for c in critical)  # fmt: skip
    record = {"rubric_id": rubric.id, "rubric_version": rubric.version, "rubric_sha256": rubric.sha256,
              "judge": {"ref": ref, "quantisation": quantisation, "prompt_sha256": pin.get("prompt_sha256")},
              "excerpts": excerpts, "agreement": rates, "passed": passed,
              "labels_sha256": hashlib.sha256(json.dumps(list(labelled), sort_keys=True).encode())
              .hexdigest()}  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    calibration_path(rubric, ref, folder).write_text(json.dumps(record, indent=1, sort_keys=True) + "\n")
    return record


def calibration_problem(rubric: Rubric, ref: str, folder: Path = CALIBRATION, prompt: Path = PROMPT,
                        under_test: Sequence[str] = ()) -> str | None:  # fmt: skip
    """Why this judge may not grade with this rubric now, or None."""
    model = ref.split(":", 1)[-1].split("@", 1)[0]
    excluded = set(rubric.data["judging"].get("excluded_from_judge_pool", [])) | set(under_test)
    if model in excluded or ref in excluded:
        return f"{ref} is the model under test: it never judges its own outputs"
    try:
        pin = rubric.judge_pin(ref)
    except RubricError as error:
        return str(error)
    if pin.get("prompt_sha256") != prompt_sha256(prompt):
        return f"the judge prompt changed since {rubric.id} pinned it: recalibrate {ref}"
    path = calibration_path(rubric, ref, folder)
    if not path.is_file():
        return f"{ref} has no calibration record for {rubric.id} {rubric.version}"
    record = json.loads(path.read_text())
    if (record.get("rubric_version"), record.get("rubric_sha256")) != (rubric.version, rubric.sha256):
        return f"{ref} was calibrated on another version of {rubric.id}: recalibrate"
    if record.get("judge", {}).get("prompt_sha256") != pin.get("prompt_sha256"):
        return f"{ref} was calibrated with another judge prompt: recalibrate"
    if not record.get("passed"):
        return f"{ref} did not pass calibration for {rubric.id} {rubric.version}"
    return None


# --- grading (EVL-05) ------------------------------------------------------------------------------------------------


@dataclass
class Graded:
    run_id: str
    verdicts: dict[str, str] = field(default_factory=dict)  # criterion -> pass | fail | n/a
    disagreements: list[str] = field(default_factory=list)
    agreed: int = 0
    compared: int = 0


def grade(rubric: Rubric, runs: Sequence[dict[str, str]], judges: dict[str, Judge], *, folder: Path = CALIBRATION,
          prompt: Path = PROMPT, under_test: Sequence[str] = (),
          teacher: Callable[[str, str], str | None] | None = None) -> dict[str, Any]:  # fmt: skip
    """Grade each run's excerpt ({run_id, excerpt}) with every criterion by the rubric's two judges."""
    pinned = [j["ref"] for j in rubric.data["judging"]["judges"]]
    if sorted(judges) != sorted(pinned):
        raise RubricError(f"{rubric.id} is judged by exactly {', '.join(pinned)}")
    for ref in pinned:
        problem = calibration_problem(rubric, ref, folder, prompt, under_test)
        if problem is not None:
            raise UncalibratedJudge(problem)
    graded: list[Graded] = []
    queue: list[dict[str, str]] = []
    for run in runs:
        row = Graded(run["run_id"])
        for criterion in rubric.criteria:
            said = []
            for ref in pinned:
                try:
                    verdict = judges[ref](criterion, run["excerpt"])
                except Exception:
                    verdict = "error"
                said.append(verdict if verdict in VERDICTS else "error")
            if "error" in said:
                row.verdicts[criterion["id"]] = "fail"  # a judge error is never a pass
                continue
            row.compared += 1
            if said[0] == said[1]:
                row.agreed += 1
                row.verdicts[criterion["id"]] = said[0]
                continue
            row.disagreements.append(criterion["id"])
            queue.append({"run_id": run["run_id"], "criterion": criterion["id"]})
            resolved = teacher(run["run_id"], criterion["id"]) if teacher is not None else None
            row.verdicts[criterion["id"]] = resolved if resolved in ("pass", "fail", "n/a") else "fail"
        graded.append(row)
    return summarise(rubric, graded, queue)


def summarise(rubric: Rubric, graded: list[Graded], queue: list[dict[str, str]]) -> dict[str, Any]:
    critical = {c["id"] for c in rubric.criteria if c["critical"]}
    counted = [(r, c, v) for r in graded for c, v in r.verdicts.items() if v != "n/a"]
    passed = sum(1 for _, _, v in counted if v == "pass")
    all_pass = sum(1 for r in graded if all(v != "fail" for v in r.verdicts.values()))
    per_criterion = {}
    for criterion in rubric.criteria:
        rows = [v for _, c, v in counted if c == criterion["id"]]
        ok = sum(1 for v in rows if v == "pass")
        per_criterion[criterion["id"]] = {"passed": ok, "total": len(rows), "rate": round(ok / len(rows), 4)
                                          if rows else None, "wilson_95": wilson(ok, len(rows))}  # fmt: skip
    agreed, compared = sum(r.agreed for r in graded), sum(r.compared for r in graded)
    critical_failures = sorted({f"{r.run_id}#{c}" for r, c, v in counted if c in critical and v == "fail"})
    return {
        "rubric": rubric.id, "rubric_version": rubric.version, "rubric_sha256": rubric.sha256, "runs": len(graded),
        "criterion_pass_rate": round(passed / len(counted), 4) if counted else None,
        "criterion_wilson_95": wilson(passed, len(counted)),
        "all_pass_rate": round(all_pass / len(graded), 4) if graded else None,
        "all_pass_wilson_95": wilson(all_pass, len(graded)),
        "per_criterion": per_criterion,
        "judge_agreement": round(agreed / compared, 4) if compared else None,
        "judge_agreement_wilson_95": wilson(agreed, compared),
        "critical_failures": critical_failures, "teacher_queue": queue,
    }  # fmt: skip


def gate_errors(report: dict[str, Any], rubric: Rubric) -> list[str]:
    """EVL-05 against TABLE EVL-17a: the criterion pass rate at the gate on enough runs, and no critical failure."""
    scoring = rubric.data["scoring"]
    errors = []
    if report.get("rubric_sha256") != rubric.sha256:
        errors.append(f"the report was graded with another version of {rubric.id}")
    if report.get("runs", 0) < scoring.get("min_runs", 1):
        errors.append(f"{report.get('runs', 0)} graded runs, fewer than {scoring.get('min_runs')}")
    rate = report.get("criterion_pass_rate")
    if rate is None or rate < scoring["criterion_pass_rate_gate"]:
        errors.append(f"criterion pass rate {rate} is below the gate {scoring['criterion_pass_rate_gate']}")
    if report.get("critical_failures"):
        errors.append(f"critical criteria failed: {', '.join(report['critical_failures'][:5])}")
    return errors
