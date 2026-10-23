"""Durable correction records and a re-mark execution port (OPS-27..29, CUR-36).

The caller supplies the existing marker/replay integration; this module never rewrites learner evidence.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.operations import atomic_json

from .incidents import SchoolCalendar
from .operations import DIGEST


class HotfixStore:
    def __init__(self, root: Path, cfg: Settings | None = None) -> None:
        self.root, self.cfg = root, cfg or Settings()

    def _path(self, case: str) -> Path:
        if not case.startswith("fix_") or not case.removeprefix("fix_").isalnum():
            raise ValueError("OPS-27: invalid correction id")
        return self.root / f"{case}.json"

    def open(self, incident: str, kind: str, old_id: str, confirmed: datetime, supported: set[str]) -> str:
        if kind not in {"wrong_key", "unsafe", "skill", "model"} or not all((incident, old_id, supported)):
            raise ValueError("OPS-27: invalid correction")
        case = "fix_" + uuid.uuid4().hex
        atomic_json(
            self._path(case),
            {
                "incident_id": incident,
                "kind": kind,
                "old_id": old_id,
                "confirmed": confirmed.isoformat(),
                "supported": sorted(supported),
            },
        )
        return case

    def get(self, case: str) -> dict[str, Any]:
        data: dict[str, Any] = json.loads(self._path(case).read_text())
        return data

    def _update(self, case: str, **fields: Any) -> None:
        atomic_json(self._path(case), {**self.get(case), **fields})

    def record_intake(self, case: str, reported_at: datetime, triaged_at: datetime, calendar: SchoolCalendar) -> None:
        confirmed = datetime.fromisoformat(self.get(case)["confirmed"])
        budget = self.cfg.ops_triage_school_days * (self.cfg.ops_support_close_hour - self.cfg.ops_support_open_hour)
        if (
            not reported_at <= triaged_at <= confirmed
            or calendar.support_hours(reported_at, triaged_at, self.cfg) > budget
        ):
            raise ValueError("OPS-27: triage missing or overdue")
        self._update(case, reported_at=reported_at.isoformat(), triaged_at=triaged_at.isoformat())

    def containment_entry(
        self,
        case: str,
        entry_id: str,
        *,
        previous_reviewed: bool = False,
        fix_artefact: str | None = None,
        fix_version: str | None = None,
    ) -> dict[str, Any]:
        record = self.get(case)
        if not entry_id.strip() or bool(fix_artefact) != bool(fix_version):
            raise ValueError("OPS-27: entry id and complete fix condition required")
        kind = {"wrong_key": "item", "unsafe": "item", "skill": "skill", "model": "model_pack"}[record["kind"]]
        action = (
            "withdraw" if kind == "item" else "pin_previous" if kind == "skill" and previous_reviewed else "disable"
        )
        return {
            "entry_id": entry_id,
            "target_kind": kind,
            "target": record["old_id"],
            "action": action,
            "reason_code": record["kind"],
            "incident_id": record["incident_id"],
            "lift_when": {"artefact_id": fix_artefact, "version": fix_version} if fix_artefact else None,
        }

    def withdraw(self, case: str, at: datetime, safety_entry_id: str) -> None:
        record = self.get(case)
        confirmed = datetime.fromisoformat(record["confirmed"])
        if not safety_entry_id.strip() or not confirmed <= at <= confirmed + timedelta(
            hours=self.cfg.ops_withdraw_hours
        ):
            raise ValueError("OPS-27: withdrawal missing or overdue")
        self._update(case, withdrawn_at=at.isoformat(), safety_entry_id=safety_entry_id)

    def correct(
        self, case: str, new_id: str, version: str, covered: set[str], report_sha256: str, at: datetime
    ) -> None:
        record = self.get(case)
        confirmed = datetime.fromisoformat(record["confirmed"])
        if (
            "withdrawn_at" not in record
            or not new_id.strip()
            or not version.strip()
            or set(record["supported"]) - covered
            or not DIGEST.fullmatch(report_sha256)
            or not confirmed <= at <= confirmed + timedelta(days=self.cfg.ops_correction_days)
        ):
            raise ValueError("OPS-27/28: correction coverage or evidence missing")
        if record["kind"] in {"wrong_key", "unsafe"} and record["old_id"] == new_id:
            raise ValueError("CUR-36: replacement needs a new id")
        self._update(
            case,
            new_id=new_id,
            version=version,
            covered=sorted(covered),
            report_sha256=report_sha256,
            corrected_at=at.isoformat(),
        )

    def remarked(self, case: str, job_id: str, replay_sha256: str, at: datetime) -> None:
        record = self.get(case)
        if (
            "corrected_at" not in record
            or not job_id.strip()
            or not DIGEST.fullmatch(replay_sha256)
            or at < datetime.fromisoformat(record["corrected_at"])
        ):
            raise ValueError("CUR-36: completed replay evidence required")
        self._update(case, remark_job=job_id, replay_sha256=replay_sha256, remarked_at=at.isoformat())

    def execute_remark(self, case: str, replay: Callable[[str, str], tuple[str, str]], at: datetime) -> str:
        record = self.get(case)
        if "remark_job" in record:
            return str(record["remark_job"])
        if "corrected_at" not in record:
            raise ValueError("CUR-36: correction must precede re-mark")
        job, digest = replay(record["old_id"], record["new_id"])
        self.remarked(case, job, digest, at)
        return job

    def notified(self, case: str, schools: set[str], summary: str, at: datetime) -> None:
        record = self.get(case)
        withdrawn = datetime.fromisoformat(record["withdrawn_at"]) if "withdrawn_at" in record else None
        if (
            not schools
            or not summary.strip()
            or withdrawn is None
            or not withdrawn <= at <= withdrawn + timedelta(hours=self.cfg.ops_school_notice_hours)
        ):
            raise ValueError("OPS-27: notification record missing")
        self._update(case, schools=sorted(schools), summary=summary, notified_at=at.isoformat())

    def errors(self, case: str, *, schools: set[str] | None = None) -> list[str]:
        record = self.get(case)
        required = {"withdrawn_at", "safety_entry_id", "new_id", "version", "covered", "report_sha256", "corrected_at"}
        if record["kind"] in {"wrong_key", "unsafe"}:
            required |= {"reported_at", "triaged_at"}
        if record["kind"] == "wrong_key":
            required |= {"remark_job", "replay_sha256", "remarked_at"}
        errors = [f"OPS-27: missing {key}" for key in sorted(required - record.keys())]
        if schools and (schools - set(record.get("schools", [])) or not record.get("summary")):
            errors.append("OPS-27: affected school notification missing")
        return errors

    def select_items(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        retired = {
            record["old_id"]
            for path in self.root.glob("fix_*.json")
            if (record := json.loads(path.read_text())).get("withdrawn_at")
            and record["kind"] in {"wrong_key", "unsafe"}
        }
        return [item for item in items if item["id"] not in retired]
