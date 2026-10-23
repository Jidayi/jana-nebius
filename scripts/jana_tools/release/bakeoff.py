"""Candidate-bound record wrapper for the existing EVL-15 bake-off computations.

Published records live in evals/bakeoff/<run_id>.record.json. Raw device results remain the inputs to
harness.bakeoff.build; this wrapper records their hashes and the frozen evaluation/prompt context.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from ..harness import bakeoff
from .prompts import AGENT, current_files


def digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    ).hexdigest()


def record_errors(
    record: dict[str, Any], *, candidate: str | None = None, expected: list[str] | None = None, root: Path = REPO_ROOT
) -> list[str]:
    from jsonschema import Draft202012Validator, FormatChecker

    schema = json.loads((REPO_ROOT / "evals/bakeoff/record.schema.json").read_text())
    errors = [
        f"bake-off record: {e.message}"
        for e in Draft202012Validator(schema, format_checker=FormatChecker()).iter_errors(record)
    ]
    if errors:
        return errors
    if candidate is not None and record["candidate"] != candidate:
        errors.append("bake-off record belongs to another candidate")
    if record["eval_lock_sha256"] != hashlib.sha256((root / "evals/lock.json").read_bytes()).hexdigest():
        errors.append("bake-off record used another frozen suite lock")
    if record["prompt_files"] != current_files(root / "content/agent"):
        errors.append("bake-off record used different prompt files")
    try:
        from datetime import datetime

        fixed = datetime.fromisoformat(record["report"]["weights_fixed_at"].replace("Z", "+00:00"))
        created = datetime.fromisoformat(record["created_at"].replace("Z", "+00:00"))
        if fixed.utcoffset() is None or created.utcoffset() is None or fixed >= created:
            errors.append("bake-off weights were not fixed before the run")
    except (KeyError, TypeError, ValueError):
        errors.append("bake-off registration timestamps are invalid")
    if record.get("inputs_sha256") != digest(record.get("inputs")):
        errors.append("bake-off raw input hash does not match")
    report = record["report"]
    try:
        rebuilt = bakeoff.build(record["inputs"], record["run_id"], report["weights_fixed_at"])
        if rebuilt != report:
            errors.append("bake-off report does not reproduce from its raw inputs")
    except (KeyError, ValueError, TypeError, AttributeError):
        errors.append("bake-off raw inputs are incomplete")
    if record["run_id"] != report.get("run_id"):
        errors.append("bake-off run id mismatch")
    try:
        errors.extend(bakeoff.report_errors(report, expected=expected))
        chosen = report["decision"]
        for tier in bakeoff.TIERS:
            for hw in bakeoff.CLASSES:
                model = chosen.get(tier, {}).get(hw)
                confirmation = report["held_out_confirmation"].get(tier, {}).get(hw, {})
                if not model or confirmation.get("model") != model or confirmation.get("confirmed") is not True:
                    errors.append(f"bake-off {tier}@{hw}: no held-out-confirmed choice")
    except (KeyError, TypeError, ValueError, AttributeError):
        errors.append("bake-off report is malformed")
    return errors


def record(
    results: dict[str, dict[str, Any]],
    *,
    candidate: str,
    run_id: str,
    created_at: str,
    weights_fixed_at: str,
    root: Path = REPO_ROOT,
) -> dict[str, Any]:
    report = bakeoff.build(results, run_id, weights_fixed_at)
    return {
        "record_version": 1,
        "run_id": run_id,
        "candidate": candidate,
        "created_at": created_at,
        "eval_lock_sha256": hashlib.sha256((root / "evals/lock.json").read_bytes()).hexdigest(),
        "prompt_files": current_files(root / AGENT.relative_to(REPO_ROOT)),
        "inputs_sha256": digest(results),
        "inputs": results,
        "report": report,
    }
