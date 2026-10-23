"""Support calendars and incident evidence (OPS-21, OPS-26, OPS-30..34, OPS-38)."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from agent_core.config import Settings

from .operations import DIGEST


@dataclass(frozen=True)
class Action:
    description: str
    owner: str
    due: datetime


def _actions_valid(actions: tuple[Action, ...]) -> bool:
    return bool(actions) and all(a.description.strip() and a.owner.strip() and a.due.tzinfo for a in actions)


@dataclass(frozen=True)
class SchoolCalendar:
    timezone: str
    holidays: frozenset[date]

    def school_day(self, day: date) -> bool:
        return day.weekday() < 5 and day not in self.holidays

    def support_hours(self, start: datetime, end: datetime, cfg: Settings | None = None) -> float:
        cfg = cfg or Settings()
        if start.tzinfo is None or end.tzinfo is None or end < start:
            raise ValueError("OPS-26: invalid support interval")
        zone = ZoneInfo(self.timezone)
        first, last = start.astimezone(zone), end.astimezone(zone)
        day, total = first.date(), 0.0
        while day <= last.date():
            if self.school_day(day):
                opened = datetime.combine(day, time(cfg.ops_support_open_hour), zone)
                closed = datetime.combine(day, time(cfg.ops_support_close_hour), zone)
                total += max(0, (min(last, closed) - max(first, opened)).total_seconds())
            day += timedelta(days=1)
        return total / 3600

    def working_days(self, start: datetime, end: datetime) -> int:
        if end < start:
            raise ValueError("OPS-33: invalid review interval")
        day, total = start.astimezone(ZoneInfo(self.timezone)).date(), 0
        while day < end.astimezone(ZoneInfo(self.timezone)).date():
            day += timedelta(days=1)
            total += self.school_day(day)
        return total


@dataclass(frozen=True)
class SupportTicket:
    ticket_id: str
    priority: str
    opened_at: datetime
    responded_at: datetime | None
    workaround_at: datetime | None
    next_release_at: datetime | None = None


def sla_report(
    tickets: list[SupportTicket], calendar: SchoolCalendar, now: datetime, cfg: Settings | None = None
) -> dict[str, Any]:
    cfg = cfg or Settings()
    day_hours = cfg.ops_support_close_hour - cfg.ops_support_open_hour
    targets = {
        "P1": (cfg.ops_p1_response_hours, cfg.ops_p1_workaround_days * day_hours),
        "P2": (cfg.ops_p2_response_days * day_hours, cfg.ops_p2_workaround_days * day_hours),
        "P3": (cfg.ops_p3_response_days * day_hours, None),
    }
    rows = []
    for ticket in tickets:
        if ticket.priority not in targets or not ticket.ticket_id.strip():
            raise ValueError("OPS-26: invalid ticket")
        response, workaround = targets[ticket.priority]
        response_hours = calendar.support_hours(ticket.opened_at, ticket.responded_at or now, cfg)
        workaround_hours = calendar.support_hours(ticket.opened_at, ticket.workaround_at or now, cfg)
        rows.append(
            {
                "ticket_id": ticket.ticket_id,
                "response_hours": response_hours,
                "workaround_hours": workaround_hours,
                "response_met": ticket.responded_at is not None and response_hours <= response,
                "workaround_met": ticket.workaround_at is not None
                and (
                    workaround_hours <= workaround
                    if workaround is not None
                    else ticket.next_release_at is not None and ticket.workaround_at <= ticket.next_release_at
                ),
            }
        )
    return {
        "tickets": len(rows),
        "response_met": sum(r["response_met"] for r in rows),
        "workaround_met": sum(r["workaround_met"] for r in rows),
        "rows": rows,
    }


@dataclass(frozen=True)
class Page:
    signal: str
    sent_at: datetime
    acknowledged_at: datetime
    operator: str
    evidence_sha256: str


def page_errors(page: Page, cfg: Settings | None = None) -> list[str]:
    cfg = cfg or Settings()
    if (
        page.signal not in {"SEV1", "SEV2", "objective_burn"}
        or not page.operator.strip()
        or not DIGEST.fullmatch(page.evidence_sha256)
        or page.acknowledged_at < page.sent_at
    ):
        return ["OPS-21: invalid page evidence"]
    if page.signal == "SEV1" and page.acknowledged_at - page.sent_at > timedelta(hours=cfg.ops_sev1_ack_hours):
        return ["OPS-21: acknowledgment overdue"]
    return []


@dataclass(frozen=True)
class Review:
    summary: str
    impact: str
    timeline: tuple[str, ...]
    causes: str
    detection_gap: str
    actions: tuple[Action, ...]
    regressions: tuple[str, ...]
    evidence_sha256: str


@dataclass(frozen=True)
class Incident:
    incident_id: str
    severity: str
    commander: str
    communications_lead: str
    declared_at: datetime
    category: str
    state: str = "declared"
    acknowledged_at: datetime | None = None
    contained_at: datetime | None = None
    resolved_at: datetime | None = None
    reviewed_at: datetime | None = None
    timeline: tuple[tuple[datetime, str, str], ...] = ()
    review: Review | None = None


def incident_errors(record: Incident, cfg: Settings | None = None, calendar: SchoolCalendar | None = None) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    if (
        record.severity not in {"SEV1", "SEV2", "SEV3"}
        or not all(
            s.strip() for s in (record.incident_id, record.commander, record.communications_lead, record.category)
        )
        or record.declared_at.tzinfo is None
        or record.state not in {"declared", "contained", "resolved", "reviewed"}
    ):
        errors.append("OPS-30: invalid incident identity")
    if record.category in {"child_safety", "privacy", "signing_key"} and record.severity != "SEV1":
        errors.append("OPS-30: critical category requires SEV1")
    if record.acknowledged_at is None or not record.timeline or record.contained_at is None:
        errors.append("OPS-30: acknowledgment, containment and timeline required")
    moments = [record.declared_at, record.acknowledged_at, record.contained_at, record.resolved_at, record.reviewed_at]
    present = [m for m in moments if m is not None]
    if any(m.tzinfo is None for m in present) or present != sorted(present):
        errors.append("OPS-30: timestamps out of order")
    if record.severity == "SEV1":
        if record.acknowledged_at and record.acknowledged_at - record.declared_at > timedelta(
            hours=cfg.ops_sev1_ack_hours
        ):
            errors.append("OPS-30: late acknowledgment")
        if record.contained_at and record.contained_at - record.declared_at > timedelta(
            hours=cfg.ops_sev1_contain_hours
        ):
            errors.append("OPS-30: late containment")
    if record.severity == "SEV2":
        if calendar is None:
            errors.append("OPS-30: school calendar required")
        elif (
            record.acknowledged_at
            and calendar.support_hours(record.declared_at, record.acknowledged_at, cfg) > cfg.ops_sev2_ack_hours
        ):
            errors.append("OPS-30: late acknowledgment")
        elif (
            record.contained_at
            and calendar.working_days(record.declared_at, record.contained_at) > cfg.ops_sev2_contain_days
        ):
            errors.append("OPS-30: late containment")
    return errors


def acknowledge(record: Incident, at: datetime, actor: str) -> Incident:
    if actor != record.commander or record.acknowledged_at or at < record.declared_at:
        raise ValueError("OPS-30: invalid acknowledgment")
    return replace(record, acknowledged_at=at, timeline=(*record.timeline, (at, actor, "acknowledged")))


def transition(
    record: Incident,
    state: str,
    at: datetime,
    actor: str,
    *,
    review: Review | None = None,
    cfg: Settings | None = None,
    calendar: SchoolCalendar | None = None,
) -> Incident:
    cfg = cfg or Settings()
    expected = {"declared": "contained", "contained": "resolved", "resolved": "reviewed"}
    latest = record.timeline[-1][0] if record.timeline else record.declared_at
    if actor != record.commander or expected.get(record.state) != state or not record.acknowledged_at or at < latest:
        raise ValueError("OPS-32: invalid transition")
    if state == "reviewed" and record.severity in {"SEV1", "SEV2"}:
        if (
            review is None
            or not all(s.strip() for s in (review.summary, review.impact, review.causes, review.detection_gap))
            or not review.timeline
            or not review.regressions
            or not all(s.strip() for s in review.regressions)
            or not _actions_valid(review.actions)
            or not DIGEST.fullmatch(review.evidence_sha256)
        ):
            raise ValueError("OPS-33: review incomplete")
        school = calendar or SchoolCalendar("UTC", frozenset())
        if school.working_days(record.resolved_at or record.declared_at, at) > cfg.ops_review_workdays:
            raise ValueError("OPS-33: review overdue; record escalation before closure")
    return replace(
        record,
        state=state,
        contained_at=at if state == "contained" else record.contained_at,
        resolved_at=at if state == "resolved" else record.resolved_at,
        reviewed_at=at if state == "reviewed" else record.reviewed_at,
        timeline=(*record.timeline, (at, actor, state)),
        review=review or record.review,
    )


@dataclass(frozen=True)
class Tabletop:
    incident_id: str
    safety_lead: str
    handed_off_at: datetime
    no_student_contact: bool
    category_only: bool
    session_confirmation_checked: bool
    deletion_verified: bool
    evidence_sha256: str
    hold_group: frozenset[str]


def tabletop_errors(record: Incident, drill: Tabletop, cfg: Settings | None = None) -> list[str]:
    cfg = cfg or Settings()
    if (
        record.severity != "SEV1"
        or record.contained_at is None
        or record.acknowledged_at is None
        or drill.incident_id != record.incident_id
        or not drill.safety_lead.strip()
        or drill.safety_lead not in drill.hold_group
        or not drill.no_student_contact
        or not drill.category_only
        or not drill.session_confirmation_checked
        or not drill.deletion_verified
        or not DIGEST.fullmatch(drill.evidence_sha256)
        or drill.handed_off_at < record.declared_at
        or drill.handed_off_at - record.declared_at > timedelta(hours=cfg.ops_sev1_ack_hours)
    ):
        return ["OPS-31: invalid child-safety tabletop evidence"]
    return []


@dataclass(frozen=True)
class Notification:
    licence_id: str
    recipient_kind: str
    route: str
    first_contact_at: datetime
    email_at: datetime
    kit_id: str
    instructions: str
    evidence_sha256: str


def notification_errors(
    record: Incident, affected: set[str], receipts: list[Notification], cfg: Settings | None = None
) -> list[str]:
    cfg = cfg or Settings()
    if record.contained_at is None:
        return ["OPS-32: containment required"]
    deadline = record.contained_at + timedelta(hours=cfg.ops_school_notice_hours)
    notified = {
        r.licence_id
        for r in receipts
        if r.recipient_kind == "registered_contact"
        and r.route in {"phone", "sms"}
        and record.contained_at <= r.first_contact_at <= r.email_at <= deadline
        and r.kit_id.strip()
        and r.instructions.strip()
        and DIGEST.fullmatch(r.evidence_sha256)
    }
    return [f"OPS-32: notification missing {licence}" for licence in sorted(affected - notified)]


DRILLS = {
    "release": "release",
    "halt": "term",
    "safety_configuration": "release",
    "content_correction": "term",
    "skill_pin": "term",
    "model_withdrawal": "halfyear",
    "signing_compromise": "year",
    "child_safety": "stage",
    "data_breach": "year",
    "cloud_failover": "quarter",
    "cloud_switch": "quarter",
    "cost_spike": "halfyear",
    "origin_usb": "halfyear",
    "school_update": "term",
    "checkout": "year",
}


def required_drills(stage: str) -> dict[str, str]:
    if stage not in {"S2", "S3", "S4", "S5"}:
        raise ValueError("OPS-34: unknown operations stage")
    return {**DRILLS, **({"lan_restore": "term", "web_rollback": "quarter"} if stage >= "S4" else {})}


@dataclass(frozen=True)
class Drill:
    name: str
    owner: str
    at: datetime
    passed: bool
    evidence_sha256: str
    trigger: str
    steps: tuple[str, ...]
    verification: str
    rollback: str
    offline_copy: str
    actions: tuple[Action, ...]


def drill_errors(
    stage: str,
    now: datetime,
    drills: list[Drill],
    *,
    term_start: datetime,
    release_at: datetime,
    stage_gate_at: datetime | None = None,
    cfg: Settings | None = None,
) -> list[str]:
    cfg = cfg or Settings()
    cutoffs = {
        "release": release_at,
        "term": term_start,
        "stage": stage_gate_at or release_at,
        "quarter": now - timedelta(days=cfg.ops_drill_quarter_days),
        "halfyear": now - timedelta(days=cfg.ops_drill_halfyear_days),
        "year": now - timedelta(days=cfg.ops_drill_year_days),
    }
    errors = []
    for name, frequency in required_drills(stage).items():
        matching = [d for d in drills if d.name == name and cutoffs[frequency] <= d.at <= now]
        if not matching:
            errors.append(f"OPS-34: drill missing or stale {name}")
            continue
        drill = max(matching, key=lambda d: d.at)
        if (
            not all(
                s.strip() for s in (drill.owner, drill.trigger, drill.verification, drill.rollback, drill.offline_copy)
            )
            or not drill.steps
            or not DIGEST.fullmatch(drill.evidence_sha256)
        ):
            errors.append(f"OPS-34: invalid runbook evidence {name}")
        if not drill.passed:
            errors.append(
                f"OPS-34: failed drill {name}" + ("; action required" if not _actions_valid(drill.actions) else "")
            )
    return errors


WEEKLY_AREAS = frozenset(
    {"reliability", "releases", "fleet", "experience", "safety", "content", "cloud", "support", "incidents", "delivery"}
)


@dataclass(frozen=True)
class Weekly:
    start: datetime
    end: datetime
    attendees: frozenset[str]
    metrics: dict[str, dict[str, Any]]
    decisions: tuple[str, ...]
    actions: tuple[Action, ...]


def weekly_errors(record: Weekly, *, cloud_live: bool, cfg: Settings | None = None) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    required = {"safety", "support", "cloud"} if cloud_live else {"safety", "support"}
    if (
        record.end <= record.start
        or record.end - record.start > timedelta(days=cfg.ops_weekly_window_days)
        or not required <= record.attendees
        or not record.decisions
        or not _actions_valid(record.actions)
    ):
        errors.append("OPS-38: weekly window, attendees, decisions or actions missing")
    if set(record.metrics) != WEEKLY_AREAS:
        errors.append("OPS-38: aggregate areas differ from the catalogue")
    for area in WEEKLY_AREAS:
        metric = record.metrics.get(area, {})
        if metric.get("value") is None:
            if set(metric) != {"value", "reason"} or not str(metric.get("reason", "")).strip():
                errors.append(f"OPS-38: unavailable reason missing {area}")
        elif (
            set(metric) != {"value", "sample_size", "start", "end"}
            or not isinstance(metric["value"], int | float)
            or not math.isfinite(metric["value"])
            or type(metric.get("sample_size")) is not int
            or metric["sample_size"] <= 0
            or not record.start <= metric["start"] < metric["end"] <= record.end
        ):
            errors.append(f"OPS-38: invalid aggregate or window {area}")
    return errors
