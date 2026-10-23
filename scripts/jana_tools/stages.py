"""ARC-17 pipeline stages: the CI workflow runs every required stage in order, and a
release (or merge) is refused unless every required stage ran and succeeded."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# Required stages in pipeline order. Every stage runs checks and must report success.
REQUIRED_STAGES: tuple[str, ...] = (
    "lint-and-layer",
    "codegen-check",
    "unit-and-property-tests",
    "sidecar-builds",
    "security-scans",
    "offline",
    "gallery",
    "eval-gate",
    "content-ci",
    "packaged-smoke",
)
GATE_JOB = "stages-complete"
RELEASE_JOB = "release"


def needs_errors(needs: dict[str, Any]) -> list[str]:
    """Errors for a GitHub `needs` context (job id -> {"result": ...}) at the gate job."""
    errors = []
    for stage in REQUIRED_STAGES:
        result = (needs.get(stage) or {}).get("result", "missing")
        if result != "success":
            errors.append(f"required stage {stage} did not succeed: {result}")
    return errors


def _needs_of(job: dict[str, Any]) -> list[str]:
    needs = job.get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs)


def workflow_errors(workflow: dict[str, Any]) -> list[str]:
    """Structural errors in the CI workflow that would let a stage be skipped or reordered."""
    jobs: dict[str, Any] = workflow.get("jobs", {})
    errors = []
    previous = None
    for stage in REQUIRED_STAGES:
        job = jobs.get(stage)
        if job is None:
            errors.append(f"required stage {stage} is not defined")
            previous = stage
            continue
        if "if" in job:
            errors.append(f"required stage {stage} has a condition that can skip it")
        if job.get("continue-on-error"):
            errors.append(f"required stage {stage} may fail without failing the pipeline")
        if any(step.get("continue-on-error") for step in job.get("steps", [])):
            errors.append(f"required stage {stage} has a step that may fail silently")
        if previous and previous not in _needs_of(job):
            errors.append(f"required stage {stage} does not run after {previous}")
        previous = stage
    gate = jobs.get(GATE_JOB)
    if gate is None:
        errors.append(f"gate job {GATE_JOB} is not defined")
    else:
        missing = [s for s in REQUIRED_STAGES if s not in _needs_of(gate)]
        if missing:
            errors.append(f"gate job {GATE_JOB} does not need: {', '.join(missing)}")
        if gate.get("if") != "always()":
            errors.append(f"gate job {GATE_JOB} must run with if: always() so a skipped stage fails it")
        if "jana_tools stages-needs" not in json.dumps(gate.get("steps", [])):
            errors.append(f"gate job {GATE_JOB} must check every stage result")
    release = jobs.get(RELEASE_JOB)
    if release is None:
        errors.append(f"release job {RELEASE_JOB} is not defined")
    elif GATE_JOB not in _needs_of(release):
        errors.append(f"release job {RELEASE_JOB} must need {GATE_JOB}")
    return errors


def load_workflow(path: Path) -> dict[str, Any]:
    import yaml  # tooling dependency; imported here so the gate job runs on the system Python

    data: dict[str, Any] = yaml.safe_load(path.read_text())
    return data
