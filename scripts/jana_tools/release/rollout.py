"""Staged rollout of a `stable` release (PLT-16, ring R2 of TABLE OPS-08a).

A stable release reaches a growing share of online devices in steps (`rollout_steps`, proposal 10%, 50%, 100%) spread
over `rollout_days`. The update response carries the current `rollout_fraction`; each device compares it with a random
bucket it made at install and never sends (OPS-08), so the server needs no device identifier.

Before each step the release manager's job reads the opt-in crash reports (OBS-17) for the release: when the
crash-free session rate is below `rollout_crash_free_gate`, the rollout halts where it is and the next step is not
taken; a halted rollout resumes only by an explicit decision recorded with a reason. A step with no reports yet is not
evidence of health either: the rollout waits at that step.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from agent_core.config import Settings

DAY_S = 86_400.0


@dataclass(frozen=True)
class CrashStats:
    """Opt-in crash-report aggregates for one release since the current step began (OBS-17)."""

    sessions: int
    crashed_sessions: int

    def crash_free(self) -> float | None:
        if self.sessions <= 0:
            return None
        return 1.0 - self.crashed_sessions / self.sessions


@dataclass(frozen=True)
class Rollout:
    version: str
    step: int  # index into the configured steps
    step_started_s: float
    halted: bool = False
    reason: str | None = None


def start(version: str, now_s: float) -> Rollout:
    return Rollout(version, 0, now_s)


def fraction(rollout: Rollout, settings: Settings | None = None) -> float:
    """The `rollout_fraction` the update response publishes now."""
    if rollout.halted:
        return 0.0
    steps = (settings or Settings()).rollout_steps
    return float(steps[min(rollout.step, len(steps) - 1)])


def soak_s(settings: Settings | None = None) -> float:
    settings = settings or Settings()
    return settings.rollout_days * DAY_S / len(settings.rollout_steps)


def advance(rollout: Rollout, now_s: float, stats: CrashStats, settings: Settings | None = None) -> Rollout:
    """The daily rollout job: halt on a failing crash gate, otherwise take the next step once the soak has passed."""
    settings = settings or Settings()
    if rollout.halted:
        return rollout
    rate = stats.crash_free()
    if rate is not None and rate < settings.rollout_crash_free_gate:
        return replace(rollout, halted=True, reason=f"crash-free sessions {rate:.4f} below the gate")
    if rate is None or now_s - rollout.step_started_s < soak_s(settings):
        return rollout
    if rollout.step >= len(settings.rollout_steps) - 1:
        return rollout
    return replace(rollout, step=rollout.step + 1, step_started_s=now_s)


def resume(rollout: Rollout, now_s: float, reason: str) -> Rollout:
    """Lift a halt after a fix or a recorded decision; the step's soak starts again."""
    if not reason.strip():
        raise ValueError("a halted rollout resumes only with a recorded reason")
    return replace(rollout, halted=False, reason=reason, step_started_s=now_s)


def offered(bucket: float, published_fraction: float) -> bool:
    """Device side (OPS-08): the update is offered when the local bucket is within the published fraction."""
    import math

    return (
        math.isfinite(bucket)
        and math.isfinite(published_fraction)
        and 0 <= bucket < 1
        and 0 <= published_fraction <= 1
        and bucket < published_fraction
    )


def device_bucket(path: Path) -> float:
    """OPS-08: persisted locally; the publication never contains this value."""
    import os
    import secrets

    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="ascii") as handle:
            os.chmod(path, 0o600)
            handle.write(str(secrets.SystemRandom().random()))
    except FileExistsError:
        pass
    bucket = float(path.read_text(encoding="ascii"))
    if not 0 <= bucket < 1:
        raise ValueError("OPS-08: invalid local bucket")
    return bucket


def publication(rollout: Rollout, settings: Settings | None = None) -> dict[str, object]:
    return {
        "version": rollout.version,
        "rollout_fraction": fraction(rollout, settings),
        "listed": not rollout.halted,
        "kits_allowed": not rollout.halted,
    }
