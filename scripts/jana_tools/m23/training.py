"""TRN-01, TRN-02, TRN-07, TRN-08: local authorization and explicit-source dataset assembly."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any
from uuid import uuid4

from agent_core.config import Settings

from .programme import moment

RUNGS = ("prompt", "output_shape", "authored_content", "grounding", "engine", "model_choice")
SIGNOFFS = ("Engine lead", "Evaluation lead", "Safety lead")
TARGETS = {
    "coach_dialogue_style",
    "hint_ladder_adherence",
    "structured_output",
    "tool_call_format",
    "explanation_language",
}
ALLOWED = {"synthetic_dialogue", "teacher_exemplar", "content_pack", "public_licensed"}
FORBIDDEN_KEYS = {
    "profile_id",
    "device_id",
    "student_id",
    "session_id",
    "turn_id",
    "notes",
    "transcript",
    "display_name",
    "research_export",
    "debug_bundle",
    "trace",
    "crash_report",
    "problem_report",
}
ARTEFACTS = {
    "debug_bundle",
    "trace_export",
    "research_export",
    "crash_report",
    "learner_export",
    "problem_report",
    "profile_archive",
    "diagnostic_bundle",
}
SOURCE_FIELDS = {
    "source_kind",
    "licence",
    "training_permitted",
    "split",
    "synthetic",
    "text",
    "terms_ref",
    "contributor_agreement",
    "licence_review",
    "content_kind",
    "origin_ref",
}


def justification_errors(record: dict[str, Any], settings: Settings | None = None) -> list[str]:
    settings = settings or Settings()
    from .records import errors as record_errors

    malformed = record_errors("justification", record)
    if malformed:
        return ["TRN-01 TRN-02: " + error for error in malformed]
    errors: list[str] = []
    if not re.fullmatch(r"tjr-\d{4}-\d{3}", str(record.get("id", ""))) or record.get("target") not in TARGETS:
        errors.append("TRN-01: record id or target missing")
    if not all(
        isinstance(record.get("signoffs", {}).get(role), str) and record["signoffs"][role].strip() for role in SIGNOFFS
    ):
        errors.append("TRN-01: missing signoffs")
    for name in ("success_margin", "non_inferiority_margin", "threshold"):
        value = record.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
            errors.append(f"TRN-01: invalid {name}")
    budget = record.get("compute_budget", {})
    for name in ("gpu_hours", "max_usd"):
        value = budget.get(name)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            errors.append("TRN-01: compute budget missing")
    for rung in RUNGS:
        entry = record.get("ladder", {}).get(rung, {})
        revisions = entry.get("revision_ids")
        effect = entry.get("effect")
        tried = (
            isinstance(revisions, list) and bool(revisions) and all(isinstance(r, str) and r.strip() for r in revisions)
        )
        tried = tried and type(effect) in (int, float) and math.isfinite(effect)
        skipped = bool(entry.get("skip_reason", "").strip()) and entry.get("accepted_by") == "Evaluation lead"
        if not tried and not skipped:
            errors.append(f"TRN-02: missing evidence for {rung}")
    candidates = record.get("candidates", [])
    if len(candidates) != 2 or record.get("direction") not in ("higher", "lower") or not record.get("metric"):
        errors.append("TRN-02: two consecutive candidate reports required")
    else:
        try:
            registered = moment(record["registered_at"])
            if candidates[1]["sequence"] != candidates[0]["sequence"] + 1:
                errors.append("TRN-02: candidates are not consecutive")
            if not moment(candidates[0]["created_at"]) < moment(candidates[1]["created_at"]) < registered:
                errors.append("TRN-01: invalid evidence chronology")
            if candidates[0]["candidate"] == candidates[1]["candidate"]:
                errors.append("TRN-02: duplicate candidate")
            for candidate in candidates:
                value = candidate["value"]
                low, high = candidate["interval95"]
                if any(type(v) not in (int, float) or not math.isfinite(v) for v in (low, value, high)):
                    raise ValueError("non-finite evidence")
                threshold = record["threshold"]
                gap = threshold - value if record["direction"] == "lower" else value - threshold
                if not 0 <= low <= value <= high <= 1 or gap > settings.training_gap_margin_points / 100:
                    errors.append("TRN-02: gap no longer marginal or failing")
                if (
                    candidate["split"] != "held_out"
                    or not candidate["report_ref"]
                    or not re.fullmatch(r"[a-f0-9]{40}", candidate["candidate"])
                ):
                    errors.append("TRN-01: invalid report provenance")
        except (KeyError, TypeError, ValueError):
            errors.append("TRN-01: invalid candidate evidence")
    return errors


def authorize_run(config: dict[str, Any], records: dict[str, Any], root: Path, *, now: str) -> dict[str, Any]:
    justification_id = config.get("justification_id")
    if not isinstance(justification_id, str):
        raise ValueError("TRN-01: approved justification id required")
    record = records.get(justification_id, {})
    errors = justification_errors(record)
    if errors:
        raise ValueError("; ".join(errors))
    if moment(now) <= moment(record["registered_at"]):
        raise ValueError("TRN-01: training must follow registration")
    root.mkdir(parents=True, exist_ok=True)
    locked = {name: record[name] for name in ("id", "success_margin", "non_inferiority_margin")}
    path = root / f"{record['id']}.frozen.json"
    try:
        with path.open("x") as target:
            target.write(json.dumps(locked, sort_keys=True, allow_nan=False) + "\n")
    except FileExistsError:
        if json.loads(path.read_text()) != locked:
            raise ValueError("TRN-01: margins frozen after the first run") from None
    run = {
        "run_id": str(uuid4()),
        "justification_id": record["id"],
        "created_at": now,
        "record_sha256": hashlib.sha256(json.dumps(record, sort_keys=True).encode()).hexdigest(),
        "success_margin": locked["success_margin"],
        "non_inferiority_margin": locked["non_inferiority_margin"],
    }
    (root / f"{run['run_id']}.json").write_text(json.dumps(run, indent=2) + "\n")
    return run


def _student(value: Any) -> bool:
    if isinstance(value, dict):
        return (
            bool(set(value) & FORBIDDEN_KEYS)
            or (isinstance(value.get("kind"), str) and value["kind"] in ARTEFACTS)
            or any(_student(v) for v in value.values())
        )
    return isinstance(value, list) and any(_student(v) for v in value)


def build_dataset(records: list[dict[str, Any]], output: Path) -> dict[str, Any]:
    validated = []
    for record in records:
        if not isinstance(record, dict) or _student(record):
            raise ValueError("student_data_refused")
        kind = record.get("source_kind")
        if not isinstance(kind, str):
            raise ValueError("TRN-07: source kind must be an allowed code")
        licence = record.get("licence")
        if (
            kind not in ALLOWED
            or not isinstance(licence, str)
            or not licence.strip()
            or record.get("training_permitted") is not True
        ):
            raise ValueError("TRN-07: source or licence refused")
        if (
            set(record) - SOURCE_FIELDS
            or record.get("split") != "development"
            or not isinstance(record.get("text"), str)
        ):
            raise ValueError("TRN-07: invalid example or split")
        if kind == "synthetic_dialogue" and (record.get("synthetic") is not True or not record.get("terms_ref")):
            raise ValueError("TRN-07: synthetic label missing")
        if kind == "teacher_exemplar" and not record.get("contributor_agreement"):
            raise ValueError("TRN-07: contributor agreement missing")
        review = record.get("licence_review", {})
        if kind == "public_licensed" and (
            not isinstance(review, dict) or review.get("reviewer") != "Curriculum lead" or not review.get("reference")
        ):
            raise ValueError("TRN-07: external licence review missing")
        if kind == "content_pack" and (
            record.get("content_kind") not in ("item", "worked_example", "hint_ladder", "skill")
            or "BY-SA" in record["licence"].upper()
        ):
            raise ValueError("TRN-07: content kind or licence refused")
        validated.append(record)
    # Validate the whole batch before creating any shard. Only explicit records are read; no device traversal.
    output.mkdir(parents=True, exist_ok=False)
    shard = "".join(json.dumps(row, sort_keys=True, allow_nan=False) + "\n" for row in validated)
    (output / "shard-0001.jsonl").write_text(shard)
    manifest = {
        "examples": len(validated),
        "student_data": {"included": False},
        "source_kinds": sorted({row["source_kind"] for row in validated}),
        "sha256": hashlib.sha256(shard.encode()).hexdigest(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest
