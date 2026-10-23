"""Candidate-bound field evidence for M24. Unit fixtures never stand in for these records."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from agent_core.config import Settings
from agent_core.config.support import HelpCatalogue, settings_sections
from agent_core.contracts import validate
from agent_core.contracts.ops.field_evidence import FieldEvidenceIndex
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..evidence.placeholders import placeholder_paths
from . import incidents as inc
from . import operations as ops

SOURCES = {
    "ops07_offline_lifecycle_script": "device_lab",
    "ops07_skip_version_upgrades": "device_lab",
    "ops11_each_target_kind": "device_lab",
    "ops12_global_cloud_off": "staging_probe",
    "ops15_physical_kit_verified": "device_lab",
    "ops17_slo_alerting": "staging_probe",
    "ops17_cloud_first_words_budget": "staging_probe",
    "ops18_load_test_at_twice_peak": "staging_probe",
    "ops20_failover_drill": "staging_probe",
    "ops21_after_hours_page_drill": "staff_drill",
    "ops25_docs_match_version": "device_lab",
    "uxs46_sections_complete": "ui_runner",
    "uxs46_no_answers_or_pin_sections": "ui_runner",
    "uxs46_sections_offline": "ui_runner",
    "ops27_wrong_key_hotfix_flow": "device_lab",
    "cur36_withdraw_and_remark": "learner_replay",
    "ops31_child_safety_tabletop": "staff_drill",
    "ops32_schools_notified": "staff_drill",
    "ops34_drills_current": "staff_drill",
}
FORBIDDEN = frozenset(
    {
        "pin",
        "password",
        "passphrase",
        "recoverycode",
        "privatekey",
        "apikey",
        "accesstoken",
        "studentname",
        "studentid",
        "profileid",
        "sessionid",
        "conversation",
        "prompt",
        "completion",
        "messages",
    }
)


# OPS-11: the behaviour a test device must show for each safety-configuration target kind.
OPS11_EXPECTED = {
    "item": "not_served",
    "lesson": "placeholder",
    "worked_example": "placeholder",
    "diagram": "placeholder",
    "visual_kind": "board_text",
    "skill": "previous_or_omitted",
    "model_pack": "allowed_fallback_or_content_only",
    "router_candidate": "skipped",
    "tool": "unavailable",
    "online_feature": "off_payloads_purged_tombstones_kept",
    "app_version": "update_advice",
}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


# The evidence index is the `ops/field-evidence` contract (D92); a probe record is `ops/probe-record`, read here with
# its times as datetimes after the contract has checked it.
EvidenceIndex = FieldEvidenceIndex


class ProbeRecord(_Strict):
    format: Literal["jana.ops.probe.1"]
    test_name: str
    candidate_commit: str = Field(pattern=r"^[a-f0-9]{40}$")
    spec_revision: str = Field(pattern=r"^[a-f0-9]{40}$")
    source: str
    started_at: datetime
    completed_at: datetime
    data: dict[str, Any]


@dataclass(frozen=True)
class FieldEvidence:
    record: ProbeRecord
    proofs: dict[str, Path]


def _scan(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if re.sub(r"[^a-z]", "", key.casefold()) in FORBIDDEN:
                raise ValueError("M24: prohibited personal or secret field in evidence")
            _scan(child)
    elif isinstance(value, list):
        for child in value:
            _scan(child)
    elif isinstance(value, float) and not math.isfinite(value):
        raise ValueError("M24: nonfinite evidence value")


def read_evidence(path: Path, test_name: str, candidate: str, spec_revision: str, now: datetime) -> FieldEvidence:
    raw = json.loads(path.read_bytes())
    validate("ops/field-evidence", raw)
    if placeholder_paths(raw):
        raise ValueError("M24: evidence index still holds a template placeholder or rehearsal value")
    index = EvidenceIndex.model_validate(raw)
    if index.candidate_commit != candidate or index.spec_revision != spec_revision or not index.synthetic_data_only:
        raise ValueError("M24: evidence belongs to another candidate, specification or data context")
    receipt = index.records.get(test_name)
    if receipt is None or receipt.source != SOURCES.get(test_name) or not receipt.reviewer.strip():
        raise ValueError("M24: missing record, source or reviewer")
    root = path.parent.resolve()
    proofs = {}
    ordered = []
    for proof in receipt.proofs:
        relative = Path(proof.path)
        source = (root / relative).resolve()
        if relative.is_absolute() or not source.is_relative_to(root) or not source.is_file():
            raise ValueError("M24: proof must be a file inside the evidence folder")
        with source.open("rb") as handle:
            digest = hashlib.file_digest(handle, "sha256").hexdigest()
        if digest != proof.sha256:
            raise ValueError("M24: proof digest mismatch")
        if digest in proofs:
            raise ValueError("M24: duplicate proof")
        proofs[digest] = source
        ordered.append(source)
    first = json.loads(ordered[0].read_bytes())
    validate("ops/probe-record", first)
    if placeholder_paths(first):
        raise ValueError("M24: probe record still holds a template placeholder or rehearsal value")
    record = ProbeRecord.model_validate_json(json.dumps(first))
    if (
        record.test_name != test_name
        or record.candidate_commit != candidate
        or record.spec_revision != spec_revision
        or record.source != receipt.source
        or record.started_at.tzinfo is None
        or record.completed_at.tzinfo is None
        or not record.started_at <= record.completed_at <= now
    ):
        raise ValueError("M24: proof identity or timing mismatch")
    _scan(record.data)
    return FieldEvidence(record, proofs)


def _parse(kind: Any, value: Any) -> Any:
    return TypeAdapter(kind).validate_json(json.dumps(value), strict=True)


def field_errors(name: str, evidence: FieldEvidence, now: datetime, cfg: Settings | None = None) -> list[str]:
    cfg = cfg or Settings()
    data, digests = evidence.record.data, set(evidence.proofs)
    try:
        if name.startswith("ops07_"):
            if data["os_network_blocked"] is not True or not data["supported_apps"]:
                return ["OPS-07: network isolation and supported-version inventory required"]
            if not isinstance(data.get("candidate_version"), str):
                return ["OPS-07: the candidate's own app version is required"]
            return ops.lifecycle_errors(
                _parse(list[ops.LifecycleRun], data["runs"]),
                tuple(data["supported_apps"]),
                tuple(data["platforms"]),
                data["candidate_version"],
            )
        if name == "ops11_each_target_kind":
            return (
                []
                if data["observed"] == OPS11_EXPECTED and data["unverified_numbers_shown"] == 0
                else ["OPS-11: target effects missing"]
            )
        if name == "ops12_global_cloud_off":
            good = (
                type(data["turns"]) is int
                and data["turns"] > 0
                and data["failed_turns"] == 0
                and data["local_turns"] == data["turns"]
                and data["time_to_local_s"] <= cfg.ops_switch_max_age_s
                and data["max_refusal_s"] < cfg.ops_switch_response_s
            )
            return [] if good else ["OPS-12: staged local-fallback load drill failed"]
        if name == "ops15_physical_kit_verified":
            checks = _parse(list[ops.USBCheck], data["checks"])
            if not all(c.evidence_sha256 in digests for c in checks):
                return ["OPS-15: physical sample proof missing"]
            return ops.usb_batch_errors(data["batch_size"], data["kit_sha256"], checks, cfg)
        if name == "ops17_slo_alerting":
            report = ops.slo_report(_parse(list[ops.ServiceSample], data["samples"]), cfg)
            errors = list(report["errors"])
            if set(report["alerts"]) != set(data["services"]):
                errors.append("OPS-17: outage alert missing")
            return errors
        if name == "ops17_cloud_first_words_budget":
            if data["measurement"] != "accepted_text_after_api10" or data["all_gates_enabled"] is not True:
                return ["OPS-17: accepted-text probe with all gates required"]
            return ops.first_words_errors({k: tuple(v) for k, v in data["samples"].items()}, cfg, stage=cfg.build_stage)
        if name == "ops18_load_test_at_twice_peak":
            return ops.load_errors(
                data["active_students"],
                data["tested_concurrency"],
                data["contracted_concurrency"],
                data["objectives_passed"] is True,
                data["school_quotas_enforced"] is True,
                next(iter(digests), ""),
                cfg,
            )
        if name == "ops20_failover_drill":
            outage, fallback, healthy, restored = [
                datetime.fromisoformat(data[key])
                for key in ("outage_at", "fallback_at", "primary_healthy_since", "primary_restored_at")
            ]
            good = (
                outage <= fallback <= healthy <= restored
                and (fallback - outage).total_seconds() <= cfg.ops_switch_max_age_s
                and (restored - healthy).total_seconds() >= cfg.ops_failback_healthy_s
                and data["failed_turns"] == 0
                and data["fallback_turns"] > 0
            )
            return [] if good else ["OPS-20: failover or recovery drill failed"]
        if name == "ops21_after_hours_page_drill":
            page = _parse(inc.Page, data["page"])
            calendar = _parse(inc.SchoolCalendar, data["calendar"])
            local = page.sent_at.astimezone(ZoneInfo(calendar.timezone))
            if (
                (
                    calendar.school_day(local.date())
                    and cfg.ops_support_open_hour <= local.hour < cfg.ops_support_close_hour
                )
                or page.evidence_sha256 not in digests
                or page.signal != "SEV1"
            ):
                return ["OPS-21: after-hours SEV1 page proof required"]
            return inc.page_errors(page, cfg)
        if name == "ops25_docs_match_version":
            manifest = data["manifest"]
            checked = {}
            for guide, entry in manifest["files"].items():
                if entry["sha256"] not in evidence.proofs or entry["reader_checked"] is not True:
                    return ["OPS-25: checked PDF proof missing"]
                checked[guide] = {"path": str(evidence.proofs[entry["sha256"]]), "sha256": entry["sha256"]}
            return HelpCatalogue(data["app_version"]).docs_errors({**manifest, "files": checked})
        if name.startswith("uxs46_"):
            section_ids = [s["id"] for s in settings_sections(cfg.build_stage)]
            good = (
                data["sections"] == section_ids
                and data["pin_prompts"] == 0
                and data["removed_keys"] == []
                and data["os_network_blocked"] is True
                and data["nonloopback_attempts"] == 0
                and set(data["rendered_sections"]) == set(section_ids)
            )
            return [] if good else ["UXS-46: offline UI route/render evidence incomplete"]
        if name in {"ops27_wrong_key_hotfix_flow", "cur36_withdraw_and_remark"}:
            confirmed, withdrawn, corrected = [
                datetime.fromisoformat(data[k]) for k in ("confirmed_at", "withdrawn_at", "corrected_at")
            ]
            good = (
                confirmed <= withdrawn <= corrected
                and (withdrawn - confirmed).total_seconds() <= cfg.ops_withdraw_hours * ops.HOUR_S
                and (corrected - confirmed).total_seconds() <= cfg.ops_correction_days * ops.DAY_S
                and data["old_item_id"] != data["new_item_id"]
                and data["old_item_served"] is False
                and data["affected_attempts"] > 0
                and data["remarked_attempts"] == data["affected_attempts"]
                and data["original_attempts_sha256"] == data["retained_attempts_sha256"]
                and data["projections_equal_full_replay"] is True
            )
            if name == "ops27_wrong_key_hotfix_flow":
                reported, triaged, notified = [
                    datetime.fromisoformat(data[k]) for k in ("reported_at", "triaged_at", "notified_at")
                ]
                calendar = _parse(inc.SchoolCalendar, data["calendar"])
                triage_budget = cfg.ops_triage_school_days * (cfg.ops_support_close_hour - cfg.ops_support_open_hour)
                good = (
                    good
                    and reported <= triaged <= confirmed
                    and calendar.support_hours(reported, triaged, cfg) <= triage_budget
                    and withdrawn <= notified <= withdrawn + timedelta(hours=cfg.ops_school_notice_hours)
                    and bool(data["affected_licences"])
                    and set(data["notified_licences"]) == set(data["affected_licences"])
                )
            return [] if good else ["CUR-36/OPS-27: installed correction and learner replay evidence missing"]
        if name == "ops31_child_safety_tabletop":
            record, tabletop = _parse(inc.Incident, data["incident"]), _parse(inc.Tabletop, data["tabletop"])
            if tabletop.evidence_sha256 not in digests:
                return ["OPS-31: tabletop proof missing"]
            return inc.incident_errors(record, cfg) + inc.tabletop_errors(record, tabletop, cfg)
        if name == "ops32_schools_notified":
            record, receipts = _parse(inc.Incident, data["incident"]), _parse(list[inc.Notification], data["receipts"])
            if (
                record.severity != "SEV2"
                or not data["offline_licences"]
                or any(r.evidence_sha256 not in digests for r in receipts)
            ):
                return ["OPS-32: offline-school SEV2 receipt proof required"]
            return inc.notification_errors(record, set(data["affected_licences"]), receipts, cfg)
        if name == "ops34_drills_current":
            drills = _parse(list[inc.Drill], data["drills"])
            if any(d.evidence_sha256 not in digests for d in drills):
                return ["OPS-34: drill proof missing"]
            return inc.drill_errors(
                cfg.build_stage,
                now,
                drills,
                term_start=datetime.fromisoformat(data["term_start"]),
                release_at=datetime.fromisoformat(data["release_at"]),
                cfg=cfg,
            )
    except (KeyError, TypeError, ValueError):
        return [f"M24: malformed field record for {name}"]
    return ["M24: unsupported field evidence kind"]
