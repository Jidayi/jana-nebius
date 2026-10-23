"""PRV-07, PRV-21, PRV-23, SEC-25, SEC-26: candidate-bound evidence gates."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
from datetime import date
from pathlib import Path
from typing import Any

from agent_core.config import Settings

LEGAL_TOPICS = (
    "law_and_regulator",
    "lawful_basis",
    "child_consent",
    "child_protection",
    "registration",
    "impact_assessment",
    "notices",
    "data_rights",
    "security",
    "breach_notification",
    "international_transfer",
    "retention",
    "privacy_officer",
)
SECURITY_TESTS = (
    "static_analysis",
    "fuzzing",
    "sandbox_escape",
    "local_api",
    "tampering",
    "injection",
    "external_penetration",
)
FUZZ_TARGETS = ("expression_parser", "visual_validator", "pack_loader", "jsonrpc", "control_channel", "image_decoder")


def _dated(value: Any, today: date, maximum_days: int) -> bool:
    try:
        return 0 <= (today - date.fromisoformat(value)).days <= maximum_days
    except (TypeError, ValueError):
        return False


def _held(value: Any, today: date) -> bool:
    """A real date on or before today: the exercise took place."""
    try:
        return date.fromisoformat(value) <= today
    except (TypeError, ValueError):
        return False


def release_errors(
    evidence: dict[str, Any],
    *,
    candidate: str,
    stage: str,
    gate: str,
    today: date | None = None,
    languages: tuple[str, ...] = ("en",),
    settings: Settings | None = None,
) -> list[str]:
    today = today or date.today()
    settings = settings or Settings()
    if not evidence:
        return ["M23: missing release evidence"]
    from .records import errors as record_errors

    malformed = record_errors("release", evidence)
    if malformed:
        return ["M23 PRV-07 PRV-21 PRV-23 SEC-25: " + problem for problem in malformed]
    errors = []
    if evidence.get("candidate") != candidate or evidence.get("stage") != stage or evidence.get("gate") != gate:
        errors.append("M23: evidence belongs to another candidate, stage or gate")
    errors += redteam_errors(
        evidence.get("redteam", {}),
        candidate=candidate,
        stage=stage,
        today=today,
        languages=languages,
        settings=settings,
    )
    errors += tabletop_errors(evidence.get("tabletop", {}), stage=stage, gate=gate, today=today, settings=settings)
    if gate in COUNSEL_GATES:
        errors += counsel_errors(evidence.get("counsel", {}), today=today)
    errors += security_errors(evidence.get("security", {}), candidate=candidate, settings=settings)
    return errors


# The stage gates a release record names (the governance-records contract's release `gate`).
RELEASE_GATES = ("s1_foundation", "pilot_start", "cloud_tier", "s2_launch", "s3_launch", "s4_launch", "s5_launch")
# PRV-07: counsel's review gates the pilot and every later gate, but not the S1 foundation gate.
COUNSEL_GATES = ("pilot_start", "cloud_tier", "s2_launch", "s3_launch", "s4_launch", "s5_launch")


def section_errors(
    kind: str,
    record: Any,
    *,
    candidate: str,
    stage: str,
    gate: str | None = None,
    today: date | None = None,
    languages: tuple[str, ...] = ("en",),
    settings: Settings | None = None,
) -> list[str]:
    """One release section (counsel, tabletop, redteam or security) checked on its own, before it is assembled into
    the release evidence: its contract `$defs` entry, template placeholders, then the same rules release_errors
    applies to it. A tabletop is checked for `gate`, or, when no gate is given, for the gate the record names."""
    from .records import errors as record_errors

    today = today or date.today()
    settings = settings or Settings()
    malformed = record_errors(kind, record)
    if malformed:
        return malformed
    if kind == "counsel":
        return counsel_errors(record, today=today)
    if kind == "tabletop":
        held_for = gate if gate is not None else record.get("gate") if isinstance(record, dict) else None
        return tabletop_errors(record, stage=stage, gate=str(held_for or ""), today=today, settings=settings)
    if kind == "redteam":
        return redteam_errors(
            record, candidate=candidate, stage=stage, today=today, languages=languages, settings=settings
        )
    if kind == "security":
        return security_errors(record, candidate=candidate, settings=settings)
    raise KeyError(f"not a release section: {kind!r}")


def redteam_errors(
    red: Any,
    *,
    candidate: str,
    stage: str,
    today: date,
    languages: tuple[str, ...],
    settings: Settings,
) -> list[str]:
    errors = []
    if (
        red.get("candidate") != candidate
        or red.get("stage") != stage
        or not red.get("owner")
        or not _dated(red.get("date"), today, settings.redteam_max_age_days)
    ):
        errors.append("PRV-23: missing or stale candidate red-team report")
    if not set(languages) <= set(red.get("languages", [])) or not {"safety", "photo_injection"} <= set(
        red.get("categories", [])
    ):
        errors.append("PRV-23: red-team coverage incomplete")
    if "failures" not in red or any(not row.get("regression_ref") for row in red.get("failures", [])):
        errors.append("PRV-23: every new failure needs a safety regression")
    if not red.get("privacy_audit_ref"):
        errors.append("PRV-23: privacy audit evidence missing")
    return errors


def tabletop_errors(tabletop: Any, *, stage: str, gate: str, today: date, settings: Settings) -> list[str]:
    """PRV-21: a SEV1 tabletop held for this stage gate. Each gate needs its own exercise: the record names the gate
    it was held for, so an exercise held for pilot_start never counts for s2_launch."""
    errors = []
    if not tabletop.get("gate"):
        errors.append("PRV-21: the tabletop does not name the stage gate it was held for")
    elif tabletop.get("gate") != gate:
        errors.append(f"PRV-21: no tabletop recorded for the {gate} gate")
    if (
        tabletop.get("stage") != stage
        or tabletop.get("severity") != "SEV1"
        or not _held(tabletop.get("date"), today)  # PRV-21: one per stage gate, no recency window
        or not tabletop.get("owner")
    ):
        errors.append("PRV-21: missing stage tabletop")
    timings = tabletop.get("timings", {})
    for name in ("triage_hours", "notify_hours", "mitigate_hours", "review_workdays"):
        value = timings.get(name)
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0:
            errors.append(f"PRV-21: missing timing {name}")
    if (
        timings.get("triage_hours", math.inf) > settings.incident_triage_hours
        or timings.get("review_workdays", math.inf) > settings.incident_review_workdays
    ):
        errors.append("PRV-21: incident exercise missed response targets")
    deadline = tabletop.get("notification_deadline_hours")
    if (
        type(deadline) not in (int, float)
        or not math.isfinite(deadline)
        or deadline <= 0
        or timings.get("notify_hours", math.inf) > deadline
    ):
        errors.append("PRV-21: counsel notification deadline absent or missed")
    if not {"online", "usb"} <= set(tabletop.get("channels", [])) or not all(
        tabletop.get(k) for k in ("regression_ref", "review_ref")
    ):
        errors.append("PRV-21: containment channels or follow-up missing")
    return errors


def counsel_errors(counsel: Any, *, today: date) -> list[str]:
    errors = []
    if (
        not counsel.get("country")
        or not counsel.get("reviewer")
        or not _dated(counsel.get("reviewed_at"), today, (today - date.min).days)
    ):
        errors.append("PRV-07: counsel review missing")
    topics = counsel.get("topics", {})
    for name in LEGAL_TOPICS:
        row = topics.get(name, {})
        if row.get("reviewed") is not True or not row.get("reference") or not row.get("finding"):
            errors.append(f"PRV-07: counsel has not reviewed {name}")
    return errors


def security_errors(security: Any, *, candidate: str, settings: Settings) -> list[str]:
    errors = []
    if security.get("candidate") != candidate:
        errors.append("SEC-25: security evidence belongs to another candidate")
    tests = security.get("tests", {})
    for name in SECURITY_TESTS:
        row = tests.get(name, {})
        if row.get("status") != "pass" or not row.get("evidence"):
            errors.append(f"SEC-25: missing or failing {name}")
    for target in FUZZ_TARGETS:
        hours = security.get("fuzz_hours", {}).get(target)
        if (
            type(hours) not in (int, float)
            or not math.isfinite(hours)
            or hours < settings.security_fuzz_hours_per_target
        ):
            errors.append(f"SEC-25: insufficient fuzzing for {target}")
    if not {"windows", "macos", "linux"} <= set(security.get("sandbox_os", [])):
        errors.append("SEC-25: missing sandbox operating system")
    if "findings" not in security or any(
        row.get("severity") in ("high", "critical") and row.get("status") != "closed"
        for row in security.get("findings", [])
    ):
        errors.append("SEC-25: unresolved penetration findings")
    return errors


def security_release(update_pack: Path, output: Path, *, version: str, contacts: list[str]) -> dict[str, Any]:
    from jana_tools.evidence.placeholders import placeholder_paths

    if (
        not update_pack.is_file()
        or not contacts
        or not all(isinstance(c, str) and c.strip() for c in contacts)
        or placeholder_paths(contacts)
    ):
        raise ValueError("SEC-26: update pack and registered licence-contact references required")
    output.mkdir(parents=True, exist_ok=False)
    offline = "security-update.janaupdate"
    shutil.copyfile(update_pack, output / offline)
    notification = {
        "version": version,
        "contacts": sorted(set(contacts)),
        "channels": ["online", "usb"],
        "offline_pack": offline,
        "status": "pending_dispatch",
    }
    (output / "notifications.json").write_text(json.dumps(notification, indent=2) + "\n")
    result = {
        "version": version,
        "offline_pack": offline,
        "channels": ["online", "usb"],
        "sha256": hashlib.sha256(update_pack.read_bytes()).hexdigest(),
        "notifications": "notifications.json",
    }
    (output / "security-release.json").write_text(json.dumps(result, indent=2) + "\n")
    return result
