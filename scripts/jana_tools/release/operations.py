"""Release decisions and evidence checks (OPS-02..19, OPS-37).

These checks consume evidence. A passing synthetic regression is not a release approval.
"""

from __future__ import annotations

import calendar
import hashlib
import math
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Literal, TypedDict

from agent_core.config import Settings

DAY_S = 86400
HOUR_S = 3600
DIGEST = re.compile(r"[a-f0-9]{64}")
Kind = Literal["app", "agent_bundle", "content_pack", "model_pack"]


def semver(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-rc\.[1-9]\d*)?", value)
    if not match:
        raise ValueError(f"invalid version: {value}")
    return tuple(map(int, match.groups()))  # type: ignore[return-value]


def add_months(at: datetime, months: int) -> datetime:
    year, month = divmod(at.year * 12 + at.month - 1 + months, 12)
    return at.replace(year=year, month=month + 1, day=min(at.day, calendar.monthrange(year, month + 1)[1]))


def pack_change_errors(previous: str, candidate: str, old_min_app: str, new_min_app: str) -> list[str]:
    from agent_core.config.operations import version

    old, new = semver(previous), semver(candidate)
    if new <= old:
        return ["OPS-02: pack version must increase"]
    return (
        ["OPS-02: patch raises min_app_version"]
        if old[:2] == new[:2] and version(new_min_app) > version(old_min_app)
        else []
    )


@dataclass(frozen=True)
class AppSupport:
    version: str
    stable_since: datetime


def supported(app: AppSupport, apps: list[AppSupport], now: datetime, cfg: Settings | None = None) -> bool:
    cfg = cfg or Settings()
    newer = {
        semver(a.version)[:2]
        for a in apps
        if semver(a.version)[:2] > semver(app.version)[:2]
        and add_months(a.stable_since, cfg.ops_newer_stable_months) <= now
    }
    return now < add_months(app.stable_since, cfg.ops_support_months) or len(newer) < cfg.ops_newer_minors


def correction_errors(
    apps: list[AppSupport], covered: set[str], now: datetime, cfg: Settings | None = None
) -> list[str]:
    return [
        f"OPS-03: correction missing for {a.version}"
        for a in apps
        if supported(a, apps, now, cfg) and a.version not in covered
    ]


@dataclass(frozen=True)
class Candidate:
    kind: Kind
    version: str
    sha256: str
    channel: str
    security_hotfix: bool = False
    severity: str | None = None


def freeze_errors(c: Candidate, now: datetime, freezes: list[tuple[datetime, datetime]]) -> list[str]:
    if c.channel not in {"dev", "pilot", "stable"}:
        return ["OPS-04: unknown channel"]
    if any(end <= start for start, end in freezes):
        return ["OPS-04: invalid freeze calendar"]
    frozen = c.channel != "dev" and any(start <= now < end for start, end in freezes)
    return ["OPS-04: school freeze"] if frozen and not (c.security_hotfix or c.severity in {"SEV1", "SEV2"}) else []


COMMON_GATES = frozenset(
    {"ci", "evaluation", "critical_safety", "security", "supply_chain", "lifecycle", "compatibility"}
)
EXTRA_GATES = {
    "app": {"bundle_budgets", "antivirus", "migrations", "dpia", "red_team", "bandwidth", "release_notes"},
    "agent_bundle": {"red_team"},
    "content_pack": {"pack_signing", "bandwidth", "release_notes"},
    "model_pack": {"red_team", "release_notes"},
}


def required_gates(kind: str) -> frozenset[str]:
    if kind not in EXTRA_GATES:
        raise ValueError("OPS-06: unsupported artefact")
    return COMMON_GATES | EXTRA_GATES[kind]


@dataclass(frozen=True)
class GateResult:
    candidate_sha256: str
    passed: bool
    report_sha256: str
    measured_at: datetime
    reviewer: str


@dataclass(frozen=True)
class Signoffs:
    manager: str
    evaluation: str
    safety: str
    security: str
    decision: str


def promotion_errors(
    c: Candidate, gates: dict[str, GateResult], signoffs: Signoffs, now: datetime, cfg: Settings | None = None
) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    from .versions import form_errors

    errors.extend(form_errors(c.kind, c.version))
    if not DIGEST.fullmatch(c.sha256) or c.channel not in {"dev", "pilot", "stable"}:
        errors.append("OPS-06: invalid candidate")
    for name in sorted(required_gates(c.kind)):
        gate = gates.get(name)
        if gate is None or not gate.passed or gate.candidate_sha256 != c.sha256 or not gate.reviewer.strip():
            errors.append(f"OPS-06: {name} missing, failed or for another candidate")
        elif not DIGEST.fullmatch(gate.report_sha256) or gate.measured_at > now:
            errors.append(f"OPS-06: {name} invalid evidence")
        elif name == "red_team" and now - gate.measured_at > timedelta(days=cfg.redteam_max_age_days):
            errors.append("OPS-06: red_team expired")
    if signoffs.decision != "go" or not all(
        s.strip() for s in (signoffs.manager, signoffs.evaluation, signoffs.safety, signoffs.security)
    ):
        errors.append("OPS-06: named signoffs and go decision required")
    return errors


@dataclass(frozen=True)
class ReleaseNotes:
    it: str
    reviewers: str
    parents: str
    students: tuple[str, ...]
    privacy_notice: str
    parent_sections: tuple[str, ...] = ()


def notes_errors(
    notes: ReleaseNotes, *, data_changed: bool, previous_notice: str = "", cfg: Settings | None = None
) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    if not all(s.strip() for s in (notes.it, notes.reviewers, notes.parents, *notes.students)) or not notes.students:
        errors.append("OPS-37: audience notes missing")
    if len(notes.students) > cfg.ops_student_note_lines or any("\n" in s for s in notes.students):
        errors.append("OPS-37: student note line budget")
    if data_changed and (
        not notes.privacy_notice.strip()
        or notes.privacy_notice == previous_notice
        or not notes.parent_sections
        or notes.parent_sections[0] != "data_changes"
    ):
        errors.append("OPS-37: data change needs a new privacy notice and renewed scope consent")
    return errors


LIFECYCLE_STEPS = frozenset(
    {
        "first_run",
        "guided",
        "practice",
        "mock",
        "pack_boundary",
        "all_kill_targets",
        "failed_launch_rollback",
        "redacted_export",
    }
)


@dataclass(frozen=True)
class LifecycleRun:
    hardware: str
    platform: str
    previous: str
    route: str
    replay_before: str
    replay_after: str
    zero_egress: bool
    passed: bool
    steps: frozenset[str]
    evidence_id: str


def lifecycle_matrix(
    supported_apps: tuple[str, ...], platforms: tuple[str, ...], candidate: str | None = None
) -> list[tuple[str, str, str, str]]:
    """OPS-07: every (hardware class, platform, starting version, route) run the lifecycle script needs. The very
    first release lists its own version as its baseline (D96): nothing upgrades from it, so it adds no runs."""
    return [
        (h, p, v, route)
        for h in ("low", "mid", "high")
        for p in platforms
        for v in ("fresh", *(s for s in supported_apps if s != candidate))
        for route in (("kit",) if v == "fresh" else ("usb_update", "online_update"))
    ]


def baseline_errors(supported_apps: tuple[str, ...], candidate: str) -> list[str]:
    """OPS-07 and D96: the supported versions a candidate is upgraded from. Every release lists earlier versions only,
    except the very first, which has none and lists its own version alone as its baseline."""
    from agent_core.config.operations import version

    try:
        own = version(candidate)
        listed = [version(v) for v in supported_apps]
    except ValueError:
        return ["OPS-07: candidate and supported versions must be X.Y.Z versions"]
    if not supported_apps:
        return ["OPS-07: no supported version listed (the very first release lists its own version)"]
    if len(set(supported_apps)) != len(supported_apps):
        return ["OPS-07: a supported version is listed twice"]
    if candidate in supported_apps:
        return (
            []
            if supported_apps == (candidate,)
            else [
                "OPS-07: the candidate's own version is listed beside others; only the very first release is its own "
                "baseline"
            ]
        )
    later = [v for v, key in zip(supported_apps, listed, strict=True) if not key < own]
    return [f"OPS-07: supported version {v} is not earlier than the candidate {candidate}" for v in later]


def lifecycle_errors(
    runs: list[LifecycleRun], supported_apps: tuple[str, ...], platforms: tuple[str, ...], candidate: str
) -> list[str]:
    errors = baseline_errors(supported_apps, candidate)
    expected = set(lifecycle_matrix(supported_apps, platforms, candidate))
    valid = set()
    for run in runs:
        key = (run.hardware, run.platform, run.previous, run.route)
        if key in valid:
            errors.append(f"OPS-07: duplicate run {key}")
        valid.add(key)
        if (
            not run.passed
            or not run.zero_egress
            or not run.evidence_id.strip()
            or not DIGEST.fullmatch(run.replay_before)
            or run.replay_before != run.replay_after
            or not LIFECYCLE_STEPS <= run.steps
        ):
            errors.append(f"OPS-07: invalid run {key}")
    return errors + [f"OPS-07: missing run {key}" for key in sorted(expected - valid)]


@dataclass(frozen=True)
class RingHealth:
    sessions: int
    crashes: int
    updates: int
    failures: int
    rollbacks: int
    champion_share: float
    school_days: int
    sev12: bool
    smoke_passed: bool

    def failures_for(self, ring: str, cfg: Settings) -> list[str]:
        if self.sev12 or not self.smoke_passed:
            return ["incident or smoke failure"]
        if ring == "R0":
            return []
        if self.sessions <= 0 or self.updates <= 0:
            return ["no health evidence"]
        if not (
            0 <= self.crashes <= self.sessions
            and 0 <= self.failures <= self.updates
            and 0 <= self.rollbacks <= self.updates
            and 0 <= self.champion_share <= 1
        ):
            return ["invalid health evidence"]
        return [
            name
            for name, failed in (
                ("crashes", 1 - self.crashes / self.sessions < cfg.rollout_crash_free_gate),
                ("updates", self.failures / self.updates >= cfg.ops_update_failure_limit),
                ("rollbacks", self.rollbacks / self.updates >= cfg.ops_rollback_limit),
                ("champions", self.champion_share < cfg.ops_champion_min),
            )
            if failed
        ]


@dataclass(frozen=True)
class Ring:
    version: str
    name: str
    started: datetime
    step: int = 0
    halted: bool = False
    hotfix: bool = False
    reason: str | None = None


def advance_ring(ring: Ring, now: datetime, health: RingHealth, cfg: Settings | None = None) -> Ring:
    cfg = cfg or Settings()
    if ring.name not in {"R0", "R1", "R2", "R3"} or now < ring.started:
        raise ValueError("OPS-08: invalid ring or clock")
    failures = health.failures_for(ring.name, cfg)
    if ring.halted:
        return ring
    if failures:
        return replace(ring, halted=ring.name in {"R1", "R2", "R3"}, reason=", ".join(failures))
    if ring.name == "R3":
        return ring
    soak = {
        "R0": cfg.ops_r0_days * DAY_S,
        "R1": cfg.ops_r1_days * DAY_S,
        "R2": cfg.rollout_days * DAY_S / len(cfg.rollout_steps),
    }[ring.name]
    if ring.hotfix:
        soak = cfg.ops_hotfix_soak_hours * HOUR_S if ring.name != "R2" else 0
    if (now - ring.started).total_seconds() < soak:
        return ring
    if ring.name == "R1" and not ring.hotfix and health.school_days < cfg.ops_pilot_school_days:
        return ring
    if ring.name == "R2" and ring.step < len(cfg.rollout_steps) - 1:
        return replace(ring, step=ring.step + 1, started=now)
    if ring.name == "R2" and not ring.hotfix and (now - ring.started).total_seconds() < cfg.ops_r3_days * DAY_S:
        return ring
    return replace(
        ring,
        name={"R0": "R1", "R1": "R2", "R2": "R3"}[ring.name],
        started=now,
        step=len(cfg.rollout_steps) - 1 if ring.hotfix and ring.name == "R1" else 0,
    )


def kits_allowed(ring: Ring) -> bool:
    return ring.name == "R3" and not ring.halted


FULL_KIT_PARTS = frozenset({"installers", "models", "content", "matrix", "safety", "docs"})


def kit_errors(
    c: Candidate,
    ring: Ring,
    destination: str,
    parts: set[str],
    *,
    update_bytes: int | None = None,
    cfg: Settings | None = None,
) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    if ring.version != c.version or ring.halted:
        errors.append("OPS-15: release mismatch or halted")
    if destination == "school":
        if c.channel != "stable" or not kits_allowed(ring) or "-rc." in c.version:
            errors.append("OPS-15: school kit requires stable R3")
    elif destination != "candidate" or c.channel not in {"dev", "pilot"} or "-rc." not in c.version:
        errors.append("OPS-15: candidate kit needs a candidate version and channel")
    required = FULL_KIT_PARTS if update_bytes is None else {"updates", "diffs", "matrix", "safety", "docs"}
    if not required <= parts:
        errors.append("OPS-15: missing kit component")
    if update_bytes is not None and not 0 <= update_bytes < cfg.ops_update_kit_max_bytes:
        errors.append("OPS-15: update kit size")
    return errors


@dataclass(frozen=True)
class USBCheck:
    media_id: str
    sha256: str
    hardware: str
    offline_install: bool
    hash_verified: bool
    operator: str
    at: datetime
    evidence_sha256: str = ""


def required_usb_samples(batch_size: int, cfg: Settings | None = None) -> int:
    cfg = cfg or Settings()
    if batch_size < cfg.ops_usb_min_samples:
        raise ValueError("OPS-15: batch smaller than minimum physical sample")
    return max(cfg.ops_usb_min_samples, math.ceil(batch_size / cfg.ops_usb_sample_every))


def usb_batch_errors(batch_size: int, sha256: str, checks: list[USBCheck], cfg: Settings | None = None) -> list[str]:
    required = required_usb_samples(batch_size, cfg)
    valid = {
        c.media_id
        for c in checks
        if c.media_id.strip()
        and c.sha256 == sha256
        and c.hardware == "low"
        and c.offline_install
        and c.hash_verified
        and c.operator.strip()
    }
    return ["OPS-15: physical USB verification incomplete"] if len(valid) < required else []


def bandwidth_limits(cfg: Settings | None = None) -> dict[str, int]:
    cfg = cfg or Settings()
    return {
        "daily_check": cfg.ops_daily_check_bytes,
        "app_patch": cfg.ops_app_patch_bytes,
        "app_minor": cfg.ops_app_minor_bytes,
        "content_diff": cfg.ops_content_diff_bytes,
        "daily_telemetry": cfg.ops_daily_telemetry_bytes,
        "crash": cfg.ops_crash_bytes,
        "metered_month": cfg.ops_metered_month_bytes,
    }


@dataclass(frozen=True)
class ReferenceTransfer:
    flow: str
    file: Path | None
    sha256: str | None
    transmissions: int
    absence_reason: str | None


def measure_bandwidth(transfers: list[ReferenceTransfer], cfg: Settings | None = None) -> dict[str, int]:
    cfg = cfg or Settings()
    expected = set(bandwidth_limits(cfg))
    amounts: dict[str, int] = {}
    counts: dict[str, int] = {}
    for transfer in transfers:
        if (
            transfer.flow not in expected | {"model_download"}
            or type(transfer.transmissions) is not int
            or transfer.transmissions < 0
        ):
            raise ValueError("OPS-16: invalid reference flow")
        counts[transfer.flow] = counts.get(transfer.flow, 0) + transfer.transmissions
        if transfer.transmissions == 0:
            if not transfer.absence_reason or transfer.file is not None or transfer.sha256 is not None:
                raise ValueError("OPS-16: absent flow needs a reason and no payload")
            amounts.setdefault(transfer.flow, 0)
            continue
        if transfer.file is None or transfer.sha256 is None or not DIGEST.fullmatch(transfer.sha256):
            raise ValueError("OPS-16: captured transfer payload and digest required")
        with transfer.file.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != transfer.sha256:
            raise ValueError("OPS-16: transfer payload changed")
        amounts[transfer.flow] = amounts.get(transfer.flow, 0) + transfer.file.stat().st_size * transfer.transmissions
    if expected - amounts.keys():
        raise ValueError("OPS-16: reference flow measurement missing")
    if counts.get("daily_check", 0) > cfg.ops_daily_check_max_count:
        raise ValueError("OPS-16: too many scheduled daily checks")
    return amounts


def budget_errors(
    amounts: dict[str, int],
    exceptions: dict[str, str],
    *,
    model_selected: bool = False,
    metered_authorised: bool = False,
    cfg: Settings | None = None,
) -> list[str]:
    limits = bandwidth_limits(cfg)
    errors = []
    for name, amount in amounts.items():
        if type(amount) is not int or amount < 0 or (name not in limits and name != "model_download"):
            errors.append(f"OPS-16: invalid measurement {name}")
        elif name == "model_download":
            if amount and not (model_selected and metered_authorised):
                errors.append("OPS-16: explicit model and metered choice required")
        elif amount > limits[name] and not exceptions.get(name, "").strip():
            errors.append(f"OPS-16: {name} exceeds budget without exception")
    return errors


def percentile(values: tuple[float, ...], share: float) -> float:
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("OPS-17: invalid samples")
    return sorted(values)[math.ceil(len(values) * share) - 1]


class SloReport(TypedDict):
    alerts: list[str]
    pause_feature_work: bool
    errors: list[str]


@dataclass(frozen=True)
class ServiceSample:
    service: str
    requests: int
    failures: int
    latencies_s: tuple[float, ...]
    alert_delay_s: float


def slo_objectives(cfg: Settings | None = None) -> dict[str, tuple[float, float | None]]:
    """OPS-17: each service's availability objective and p95 latency objective in seconds (None: no latency)."""
    cfg = cfg or Settings()
    return {
        "index": (cfg.ops_index_availability, cfg.ops_index_p95_s),
        "checkout": (cfg.ops_standard_availability, cfg.ops_checkout_p95_s),
        "telemetry": (cfg.ops_standard_availability, None),
        "crash": (cfg.ops_standard_availability, None),
        "support_upload": (cfg.ops_standard_availability, None),
        "cloud_gateway": (cfg.ops_gateway_availability, cfg.ops_gateway_added_p95_s),
    }


def slo_report(samples: list[ServiceSample], cfg: Settings | None = None) -> SloReport:
    cfg = cfg or Settings()
    objectives = slo_objectives(cfg)
    errors, alerts, pause = [], [], False
    for s in samples:
        if s.service not in objectives or s.requests <= 0 or not 0 <= s.failures <= s.requests:
            errors.append(f"OPS-17: invalid measurement {s.service}")
            continue
        availability, latency = objectives[s.service]
        budget_spent = s.failures / (s.requests * (1 - availability))
        pause |= budget_spent >= cfg.ops_error_budget_pause_share
        breached = 1 - s.failures / s.requests < availability
        if latency is not None:
            try:
                breached |= percentile(s.latencies_s, cfg.ops_percentile) > latency
            except ValueError:
                errors.append(f"OPS-17: missing latency {s.service}")
        if breached or budget_spent >= cfg.ops_error_budget_pause_share:
            alerts.append(s.service)
            if not 0 <= s.alert_delay_s <= cfg.ops_alert_delay_s:
                errors.append(f"OPS-17: late alert {s.service}")
    errors += [f"OPS-17: missing service {name}" for name in objectives.keys() - {s.service for s in samples}]
    return {"alerts": alerts, "pause_feature_work": pause, "errors": errors}


def first_words_errors(
    samples: dict[str, tuple[float, ...]], cfg: Settings | None = None, *, stage: str = "S2"
) -> list[str]:
    cfg = cfg or Settings()
    errors = []
    for platform in ("reference_low", "s4_web") if stage >= "S4" else ("reference_low",):
        values = samples.get(platform, ())
        try:
            p95 = percentile(values, cfg.ops_percentile)
        except ValueError:
            errors.append(f"OPS-17: missing valid first-text samples {platform}")
            continue
        if median(values) > cfg.ops_first_words_median_s or p95 > cfg.ops_first_words_p95_s:
            errors.append(f"OPS-17: first-text budget {platform}")
    return errors


def peak_concurrency(active_students: int, cfg: Settings | None = None) -> int:
    if active_students <= 0:
        raise ValueError("OPS-18: active students required")
    return math.ceil(active_students * (cfg or Settings()).ops_peak_share)


def load_errors(
    active_students: int,
    tested: float,
    contracted: float,
    slo_passed: bool,
    school_quotas: bool,
    report_sha256: str,
    cfg: Settings | None = None,
) -> list[str]:
    cfg = cfg or Settings()
    peak = peak_concurrency(active_students, cfg)
    if (
        tested < peak * cfg.ops_load_multiple
        or contracted < peak * cfg.ops_capacity_multiple
        or not slo_passed
        or not school_quotas
        or not DIGEST.fullmatch(report_sha256)
    ):
        return ["OPS-18: capacity, quota or load evidence missing"]
    return []


def cost_alerts(
    today: float,
    history: list[float],
    projected_per_student: float,
    price_floor: float,
    *,
    price_changed: bool = False,
    cfg: Settings | None = None,
) -> list[str]:
    cfg = cfg or Settings()
    if len(history) != cfg.ops_cost_history_days or any(not math.isfinite(v) or v < 0 for v in [today, *history]):
        return ["missing_cost_history"]
    alerts = []
    if today > 0 and today >= cfg.ops_cost_multiple * median(history):
        alerts.append("daily_spike")
    if projected_per_student > price_floor:
        alerts.append("price_floor")
    if price_changed:
        alerts.append("price_change")
    return alerts
