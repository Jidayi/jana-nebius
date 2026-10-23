"""The release check on local models (MDL-27, MDL-28).

A model may be recommended for a hardware class only on the strength of a recorded bake-off for that class: each
class a recommendations entry names must cite a bake-off report (`evals/bakeoff/<run id>.json`, built by
`harness.bakeoff.build`) that is complete under EVL-15, that ran the model on that class without excluding it, and
whose held-out-confirmed decision is that model for every tier the entry assigns. The file itself must be valid
against its schema with every entry complete. A release that fails any of this is refused.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .. import REPO_ROOT

BAKEOFFS = REPO_ROOT / "evals" / "bakeoff"
RECOMMENDATIONS = REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "recommended_models.json"


def reports(folder: Path = BAKEOFFS) -> dict[str, dict[str, Any]]:
    """The recorded bake-off reports by run id."""
    found = {}
    for path in sorted(folder.glob("*.record.json")) if folder.is_dir() else []:
        from .bakeoff import record_errors

        record = json.loads(path.read_text())
        errors = record_errors(record)
        found[str(record.get("run_id"))] = {"record_errors": errors} if errors else record["report"]
    return found


def bakeoff_errors(document: dict[str, Any], recorded: dict[str, dict[str, Any]]) -> list[str]:
    """Why a model's class assignment has no bake-off record that supports it (MDL-27)."""
    from ..harness import bakeoff

    errors = []
    for entry in document.get("models", []):
        model = entry.get("model")
        for hw, assignment in sorted((entry.get("classes") or {}).items()):
            run_id = assignment.get("bakeoff")
            report = recorded.get(run_id) if run_id else None
            if report is None:
                errors.append(f"{model}@{hw}: no bake-off record" + (f" ({run_id} not found)" if run_id else ""))
                continue
            if report.get("record_errors"):
                errors.append(f"{model}@{hw}: invalid bake-off record ({report['record_errors'][0]})")
                continue
            incomplete = bakeoff.report_errors(report, expected=[r["model"] for r in report["candidates"]])
            if incomplete:
                errors.append(f"{model}@{hw}: bake-off {run_id} is not a complete record ({incomplete[0]})")
                continue
            row = next((r for r in report["candidates"] if r["model"] == model), None)
            if row is None or row["classes"].get(hw, {}).get("excluded") is not None or hw not in row["classes"]:
                errors.append(f"{model}@{hw}: bake-off {run_id} did not run it on this class to the end")
                continue
            for tier in assignment.get("tiers", []):
                chosen = report["decision"].get(tier, {}).get(hw)
                if chosen != model:
                    errors.append(f"{model}@{hw}: bake-off {run_id} chose {chosen} for the {tier} tier, not this model")
    return errors


def release_errors(document: dict[str, Any] | None = None,
                   recorded: dict[str, dict[str, Any]] | None = None) -> list[str]:  # fmt: skip
    """The release check: the recommendations file valid and complete (MDL-28), every class assignment backed by a
    bake-off record (MDL-27)."""
    from agent_core.router.capabilities import recommendation_errors

    document = document if document is not None else json.loads(RECOMMENDATIONS.read_text())
    return recommendation_errors(document) + bakeoff_errors(document, reports() if recorded is None else recorded)
