"""The journey scripts (JRN-02) and their check against the specification.

Each active journey JRN-03 to JRN-16 (JRN-12 is retired, D52) has a script `evals/journeys/jrnNN.yaml`: its persona,
stage, numbered steps and failure branches, each with the requirements it exercises, and for each step whether the
scripted run plays it (`runs_on: harness`) or only the device lab can (`runs_on: device_lab`: the native installer, a
real webcam, the reference laptop's own timing). Only identifiers are read from the specification (the number of
step rows, the failure-branch ids, the stage and status of each journey), so a journey edited in the specification
fails `script_errors` until its script follows; no specification wording is copied into a script.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from .. import REPO_ROOT
from ..spec import DOCS, requirements

SCRIPTS = REPO_ROOT / "evals" / "journeys"
STAGES = ("S1", "S2", "S3", "S4", "S5")
RUNS_ON = ("harness", "device_lab")
_JOURNEY = re.compile(r"^JRN-(\d{2})$")
_BRANCH = re.compile(r"^- (F\d+) ", re.MULTILINE)
_STEP_ROW = re.compile(r"^\| (\d+) \|", re.MULTILINE)


@dataclass(frozen=True)
class Step:
    n: int
    requirements: tuple[str, ...]
    runs_on: str


@dataclass(frozen=True)
class Branch:
    id: str
    requirements: tuple[str, ...]
    online: bool


@dataclass(frozen=True)
class Script:
    journey: str
    persona: str
    stage: str
    steps: tuple[Step, ...]
    branches: tuple[Branch, ...]

    @property
    def number(self) -> str:
        return self.journey[4:]

    def branch(self, branch_id: str) -> Branch:
        return next(b for b in self.branches if b.id == branch_id)


@dataclass(frozen=True)
class SpecJourney:
    """The structure the specification gives a journey: its stage, step count and failure-branch ids."""

    journey: str
    stage: str
    retired: bool
    steps: int
    branches: tuple[str, ...]


def spec_journeys(docs: Path = DOCS) -> dict[str, SpecJourney]:
    if docs == DOCS:
        inventory = json.loads((REPO_ROOT / "contracts/policies/journeys.json").read_text())
        return {
            rid: SpecJourney(rid, row["stage"], row["retired"], row["steps"], tuple(row["branches"]))
            for rid, row in inventory["journeys"].items()
        }
    found = {}
    for rid, req in requirements(docs).items():
        if not _JOURNEY.match(rid):
            continue
        text = req.file.read_text().split(f"### {rid} — ", 1)[1].split("\n### ", 1)[0]
        body = text.split("\nAcceptance:", 1)[0]
        found[rid] = SpecJourney(rid, req.stage, req.retired, len(_STEP_ROW.findall(body)),
                                 tuple(_BRANCH.findall(body)))  # fmt: skip
    return found


def executable(stage: str, docs: Path = DOCS) -> list[str]:
    """The journeys that must exist as scripts for a build of `stage`: JRN-03 to JRN-16, active, of that stage or an
    earlier one (JRN-01 and JRN-02 are the reference set and this rule, not journeys)."""
    rank = STAGES.index(stage)
    return sorted(
        j.journey
        for j in spec_journeys(docs).values()
        if 3 <= int(j.journey[4:]) <= 16 and not j.retired and STAGES.index(j.stage) <= rank
    )


def _load(path: Path) -> Script:
    raw: dict[str, Any] = yaml.safe_load(path.read_text())
    steps = tuple(
        Step(int(s["n"]), tuple(s.get("requirements", [])), str(s.get("runs_on", "harness"))) for s in raw["steps"]
    )
    branches = tuple(
        Branch(str(b["id"]), tuple(b.get("requirements", [])), bool(b.get("online", False)))
        for b in raw.get("branches", [])
    )
    return Script(str(raw["journey"]), str(raw["persona"]), str(raw["stage"]), steps, branches)


@cache
def scripts(root: Path = SCRIPTS) -> dict[str, Script]:
    return {s.journey: s for s in (_load(p) for p in sorted(root.glob("jrn*.yaml")))}


def script(journey: str) -> Script:
    return scripts()[journey]


def script_errors(stage: str, root: Path = SCRIPTS, docs: Path = DOCS) -> list[str]:
    """Every journey of the stage and earlier has a script whose steps and failure branches are the specification's,
    each naming known requirements; no script exists for a retired journey."""
    errors = []
    found = {s.journey: s for s in (_load(p) for p in sorted(root.glob("jrn*.yaml")))}
    spec = spec_journeys(docs)
    known = (
        json.loads((REPO_ROOT / "contracts/policies/journeys.json").read_text())["requirements"]
        if docs == DOCS
        else requirements(docs)
    )
    for journey in executable(stage, docs):
        if journey not in found:
            errors.append(f"{journey}: no journey script in evals/journeys")
    for journey, s in sorted(found.items()):
        want = spec.get(journey)
        if want is None or want.retired:
            errors.append(f"{journey}: a script for a journey the specification does not have (or retired)")
            continue
        if s.stage != want.stage:
            errors.append(f"{journey}: script stage {s.stage}, specification {want.stage}")
        if [step.n for step in s.steps] != list(range(1, want.steps + 1)):
            errors.append(f"{journey}: script steps {[step.n for step in s.steps]}, specification 1..{want.steps}")
        if tuple(b.id for b in s.branches) != want.branches:
            errors.append(f"{journey}: script branches {[b.id for b in s.branches]}, specification {want.branches}")
        for item in (*s.steps, *s.branches):
            unknown = [r for r in item.requirements if r not in known]
            if unknown:
                errors.append(f"{journey}: unknown requirements {unknown}")
        bad = [step.n for step in s.steps if step.runs_on not in RUNS_ON]
        if bad:
            errors.append(f"{journey}: steps {bad} run on neither the harness nor the device lab")
        if all(step.runs_on == "device_lab" for step in s.steps):
            errors.append(f"{journey}: no step the scripted run can play")
    return errors
