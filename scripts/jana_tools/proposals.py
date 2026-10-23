"""Proposal values as configuration keys (plan rule 7; ARC-27 layer 1, ARC-28).

Every `proposal:` value in the specification becomes a named configuration key whose default is the proposed value.
Keys are declared by the milestone that implements the requirement; this check fails when a requirement of a
milestone in force has a proposal and no declared key serves it, and reports coverage for the whole specification.
"""

from __future__ import annotations

import re

from .coverage import primary_requirements
from .spec import requirements

# Milestones whose requirements must have their proposals declared (extended as each milestone starts).
MILESTONES_IN_FORCE = ("M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8", "M9", "M10", "M11", "M12", "M19")
# A proposal is "proposal:" followed by a value, or "(proposal)" / "(proposals ...)" after one or a table of them;
# the configuration rule itself is not.
_PROPOSAL = re.compile(r"proposal:\s*(?!`?\s*values)[^\s`|)]|\(proposals?\b[^)]*\)")


def proposal_counts() -> dict[str, int]:
    counts = {}
    for rid, req in requirements().items():
        if req.retired:
            continue
        text = req.file.read_text()
        body = text.split(f"### {rid} — ", 1)[1].split("\n### ", 1)[0]
        body = body.split("\nAcceptance:", 1)[0]
        n = len(_PROPOSAL.findall(body))
        if n:
            counts[rid] = n
    return counts


def declared_keys() -> dict[str, list[str]]:
    """Every declared key by the requirement it serves: the core's settings, the cloud gateway's and the ingest's
    configuration and the cost model's named proposals (BIZ-08)."""
    from agent_core.config.keys import Settings, declaration
    from cloud_gateway import config as gateway

    from jana_tools import cost_model

    by_requirement: dict[str, list[str]] = {}
    for name in Settings.model_fields:
        for requirement in str(declaration(name)["serves"]).split(", "):  # one value may serve several
            by_requirement.setdefault(requirement, []).append(name)
    from ingest import config as ingest

    for prefix, module in (("gateway", gateway), ("ingest", ingest)):
        for model in (getattr(module, n) for n in dir(module)):
            if isinstance(model, type) and issubclass(model, module.BaseModel) and model.__module__ == module.__name__:
                for name, info in model.model_fields.items():
                    extra = info.json_schema_extra
                    if isinstance(extra, dict) and extra.get("serves"):
                        by_requirement.setdefault(str(extra["serves"]), []).append(f"{prefix}.{model.__name__}.{name}")
    for name, requirement in cost_model.DECLARED.items():
        by_requirement.setdefault(requirement, []).append(f"cost_model.{name}")
    return by_requirement


def proposal_errors() -> list[str]:
    counts, keys = proposal_counts(), declared_keys()
    errors = []
    for milestone in MILESTONES_IN_FORCE:
        for _, rid in primary_requirements(milestone):
            if rid in counts and rid not in keys:
                errors.append(f"{rid} ({milestone}) has {counts[rid]} proposal value(s) and no configuration key")
    return errors


def proposal_report() -> str:
    counts, keys = proposal_counts(), declared_keys()
    covered = [r for r in counts if r in keys]
    return (
        f"{len(counts)} requirements carry {sum(counts.values())} proposal values; "
        f"{len(covered)} have declared keys ({', '.join(sorted(covered))})"
    )
