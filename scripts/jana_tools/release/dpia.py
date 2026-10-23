"""The DPIA gate per online feature (PRV-08): the DPIA record, the list a release build carries, and the gate check.

Each online feature of TABLE PRV-08a has its own DPIA, or a section of one recorded with its own identifier, completed
and signed by the Safety lead (the `dpia` governance record). `build_list` turns the signed records into the unsigned
DPIA list, which the offline signing laptop signs with the content key (artefact `dpia_list`, SEC-12) and the release
pipeline bundles as `agent_core/net/dpia_list.json`; the device hides every feature whose DPIA is not on it
(`agent_core.net.dpia`). `gate_errors` refuses a gate while any feature that gate enables lacks an approved,
recorded DPIA on a list the target environment verifies. The records' content is the Safety lead's; nothing here
writes an assessment.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Any

# TABLE PRV-08a, one entry per feature that needs its own DPIA, with the gate it must pass before. The ids are the
# online features of TABLE ARC-07a where the row is one of them; the other rows are named here. Cloud voice is an
# `s4_launch` row (local voice sends nothing and needs no DPIA).
FEATURE_GATES: dict[str, str] = {
    "telemetry": "pilot_start",
    "crash_reports": "pilot_start",
    "downloads": "pilot_start",
    "update_checks": "pilot_start",
    "research_data": "pilot_start",
    "support_bundles": "pilot_start",
    "cloud_tier": "cloud_tier",
    "study_materials": "s3_launch",
    "web_client": "web_launch",
    "cloud_backup": "s4_launch",
    "multi_device": "s4_launch",
    "parent_remote_view": "s4_launch",
    "relay": "s4_launch",
    "cloud_voice": "s4_launch",
    "model_training_research": "s5_launch",
}
# The rows of TABLE PRV-08a as gates, in table order: a structural check (dpia_table_errors) keeps FEATURE_GATES in
# step with the specification's table without copying its wording.
TABLE_GATES = (
    "pilot_start",
    "pilot_start",
    "pilot_start",
    "cloud_tier",
    "s3_launch",
    "web_launch",
    "s4_launch",
    "s4_launch",
    "s5_launch",
    "pilot_start",
)
LIST_VERSION = 1


def required(gate: str) -> list[str]:
    """The features a gate enables that each need an approved DPIA before it passes."""
    return [feature for feature, at in FEATURE_GATES.items() if at == gate]


def record_errors(record: Any, documents: Path | None = None) -> list[str]:
    """One DPIA record: its governance-records format, then the facts the format cannot state: signed by the Safety
    lead on or after completion, covering only features of its own gate, and (when the assessment documents are at
    hand) the referenced document's bytes still match the recorded hash."""
    from ..m23.records import errors as format_errors

    problems = format_errors("dpia", record)
    if problems:
        return [f"PRV-08: {p}" for p in problems]
    errors = []
    wrong = [f for f in record["features"] if FEATURE_GATES.get(f) != record["gate"]]
    if wrong:
        errors.append(f"PRV-08: {record['id']} covers {', '.join(wrong)}, not features of the {record['gate']} gate")
    if record["signed_by"]["role"] != "safety_lead":
        errors.append(f"PRV-08: {record['id']} is not signed by the Safety lead")
    try:
        if date.fromisoformat(record["signed_at"]) < date.fromisoformat(record["completed_at"]):
            errors.append(f"PRV-08: {record['id']} was signed before it was completed")
    except ValueError:
        errors.append(f"PRV-08: {record['id']} has an invalid date")
    if documents is not None:
        path = documents / record["assessment_ref"]
        if not path.is_file():
            errors.append(f"PRV-08: {record['id']}: the assessment {record['assessment_ref']} is not in the folder")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != record["assessment_sha256"]:
            errors.append(f"PRV-08: {record['id']}: the assessment differs from the signed record")
    return errors


def build_list(records: list[dict[str, Any]], *, created_at: str) -> dict[str, Any]:
    """The unsigned DPIA list from signed DPIA records, one entry per record (its id, gate and features). Refuses any
    invalid record or a feature claimed by two records, so the list never carries an unrecorded approval."""
    problems = [p for record in records for p in record_errors(record)]
    seen: dict[str, str] = {}
    for record in records:
        for feature in record.get("features", []):
            if feature in seen and seen[feature] != record.get("id"):
                problems.append(f"PRV-08: {feature} is covered by both {seen[feature]} and {record.get('id')}")
            seen[feature] = str(record.get("id"))
    if problems:
        raise ValueError("; ".join(problems))
    approved = [
        {"dpia_id": r["id"], "gate": r["gate"], "features": sorted(r["features"])}
        for r in sorted(records, key=lambda r: r["id"])
    ]
    return {"dpia_list_version": LIST_VERSION, "created_at": created_at, "approved": approved}


def gate_errors(
    gate: str,
    signed_list: Any,
    records: list[dict[str, Any]],
    *,
    environment: Any,
    trust: Any = None,
) -> list[str]:
    """PRV-08 before `gate`: every feature the gate enables is on a list that verifies in `environment`, under a DPIA
    id with a valid signed record covering it."""
    from agent_core.net.dpia import verify

    features = required(gate)
    if not features:
        return []
    if not isinstance(signed_list, dict) or not signed_list:
        return [f"PRV-08: no signed DPIA list for the {gate} gate"]
    verified = verify(signed_list, environment, trust)
    if verified.problem:
        return [f"PRV-08: the DPIA list does not verify: {verified.problem}"]
    errors = []
    by_id = {r.get("id"): r for r in records if isinstance(r, dict)}
    for record in records:
        errors += record_errors(record)
    entries = [e for e in signed_list.get("approved") or [] if isinstance(e, dict)]
    for feature in features:
        covering = [e for e in entries if feature in (e.get("features") or []) and e.get("gate") == gate]
        if not covering:
            errors.append(f"PRV-08: no approved DPIA for {feature} on the signed list")
            continue
        for entry in covering:
            record = by_id.get(entry.get("dpia_id"))
            if record is None:
                errors.append(f"PRV-08: {entry.get('dpia_id')} ({feature}) has no signed DPIA record")
            elif feature not in record.get("features", []):
                errors.append(f"PRV-08: the record {record.get('id')} does not cover {feature}")
    return errors


def dpia_table_errors(docs: Path) -> list[str]:
    """TABLE PRV-08a still has the rows FEATURE_GATES was written from (row count and each row's gate, in order)."""
    from ..spec import table_rows

    text = (docs / "specification" / "privacy-and-safety.md").read_text()
    gates = tuple(row[1].strip("`") for row in table_rows(text, "TABLE PRV-08a"))
    if gates != TABLE_GATES:
        return [f"PRV-08: TABLE PRV-08a has gates {gates}; the DPIA gate check was written for {TABLE_GATES}"]
    return []
