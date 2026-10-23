"""Durable rollout monitoring (OPS-08, OPS-09)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.operations import atomic_json
from pydantic import TypeAdapter

from .operations import DIGEST, Ring, RingHealth, advance_ring, kits_allowed


@dataclass(frozen=True)
class HealthReport:
    version: str
    measured_at: datetime
    evidence_sha256: str
    health: RingHealth


class ReleaseMonitor:
    def __init__(self, state: Path, cfg: Settings | None = None) -> None:
        self.path, self.cfg = state, cfg or Settings()
        if self.cfg.ops_rollout_poll_s > self.cfg.ops_halt_deadline_s:
            raise ValueError("OPS-09: monitor interval exceeds the halt budget")

    def current(self) -> Ring:
        return TypeAdapter(Ring).validate_python(json.loads(self.path.read_text())["ring"])

    def save(self, ring: Ring, now: datetime) -> dict[str, Any]:
        fraction = float(self.cfg.rollout_steps[ring.step]) if ring.name == "R2" else 1.0
        listed = not ring.halted and ring.name != "R0"
        result = {
            "checked_at": now.isoformat(),
            "ring": TypeAdapter(Ring).dump_python(ring, mode="json"),
            "publication": {
                "version": ring.version,
                "rollout_fraction": fraction if listed else 0.0,
                "listed": listed,
                "kits_allowed": kits_allowed(ring),
            },
        }
        atomic_json(self.path, result)
        return result

    def tick(self, report: HealthReport, now: datetime) -> dict[str, Any]:
        ring = self.current()
        if report.version != ring.version or not DIGEST.fullmatch(report.evidence_sha256):
            raise ValueError("OPS-09: health report belongs to another release or has no evidence")
        age = (now - report.measured_at).total_seconds()
        if age < 0 or age > self.cfg.ops_halt_deadline_s:
            ring = replace(ring, halted=True, reason="OPS-09: health collector stale")
        else:
            ring = advance_ring(ring, now, report.health, self.cfg)
        return self.save(ring, now)

    def resume(self, reason: str, now: datetime) -> dict[str, Any]:
        if not reason.strip():
            raise ValueError("OPS-09: resume reason required")
        return self.save(replace(self.current(), halted=False, reason=reason, started=now), now)

    async def watch(self, health_path: Path, *, once: bool = False) -> dict[str, Any]:
        while True:
            now = datetime.now(UTC)
            try:
                report = TypeAdapter(HealthReport).validate_json(health_path.read_bytes(), strict=True)
                result = self.tick(report, now)
            except (OSError, ValueError, KeyError, TypeError):
                result = self.save(
                    replace(self.current(), halted=True, reason="OPS-09: health report unavailable"), now
                )
            if once:
                return result
            await asyncio.sleep(self.cfg.ops_rollout_poll_s)
