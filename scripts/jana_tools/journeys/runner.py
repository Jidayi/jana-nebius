"""The journey runner (JRN-02): one journey or one failure branch played on the offline harness.

A probe is an async function that drives the shipped core through the journey's steps (the tests bind one per
journey and per failure branch, against a deterministic fake model). The runner plays it inside the harness's egress
monitor (EVL-16): any connect, send or lookup to anything but loopback is refused, recorded and fails the case; the
stand-in online services of an online branch listen on loopback, so the same monitor holds for them. The probe
marks each step with `run.step(n)` as it completes it, in order; a step the script gives to the device lab (the
native installer, a real camera, the reference laptop's own clock) is recorded with `run.device_lab(n, why)`. The
main journey passes only when every step was completed or handed to the device lab as its script says, with zero
egress; a branch passes when its probe completes with zero egress.

Case ids are the end-to-end names of JRN-02: `e2e_jrn03_main`, `e2e_jrn03_f1`, ... A run on a reference laptop is
written as a `journey_run` record (`suite_record`) for the release gate (PRD-13).
"""

from __future__ import annotations

import time
import traceback
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

from ..harness.egress import offline_run
from .scripts import Script

Probe = Callable[["Run"], Awaitable[None]]


class JourneyError(AssertionError):
    """A journey step out of order, unknown, or given to the wrong runner."""


def case_id(journey: str, part: str) -> str:
    return f"e2e_jrn{journey[4:]}_{'main' if part == 'main' else part.lower()}"


@dataclass
class Run:
    """What a probe reports while it plays: the steps completed, those handed to the device lab, and notes."""

    script: Script
    part: str
    reached: list[int] = field(default_factory=list)
    delegated: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def _expect(self, n: int) -> None:
        if self.part != "main":
            raise JourneyError(f"{self.script.journey} {self.part}: steps belong to the main journey")
        done = self.reached + list(self.delegated)
        wanted = len(done) + 1
        if n != wanted:
            raise JourneyError(f"{self.script.journey}: step {n} played, step {wanted} expected next")

    @contextmanager
    def step(self, n: int) -> Iterator[None]:
        """The body plays step `n`; it counts only when the body completes."""
        self._expect(n)
        if self.script.steps[n - 1].runs_on != "harness":
            raise JourneyError(f"{self.script.journey}: step {n} runs on the device lab, not the harness")
        yield
        self.reached.append(n)

    def device_lab(self, n: int, why: str) -> None:
        self._expect(n)
        if self.script.steps[n - 1].runs_on != "device_lab":
            raise JourneyError(f"{self.script.journey}: step {n} is a harness step and must be played")
        self.delegated[n] = why

    def note(self, text: str) -> None:
        self.notes.append(text)


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    journey: str
    part: str
    status: str  # passed | failed
    reached: tuple[int, ...]
    delegated: dict[int, str]
    egress: tuple[str, ...]
    seconds: float
    reason: str = ""
    notes: tuple[str, ...] = ()


async def run_case(script: Script, part: str, probe: Probe) -> CaseResult:
    """Play the main journey (`part="main"`) or one failure branch (`"F1"`...) under the egress monitor."""
    if part != "main" and part not in {b.id for b in script.branches}:
        raise JourneyError(f"{script.journey} has no failure branch {part}")
    run = Run(script, part)
    started = time.monotonic()
    reason = ""
    with offline_run() as seen:
        try:
            await probe(run)
        except Exception as error:  # a failing step is the result, reported with its trace
            reason = f"{type(error).__name__}: {error}\n" + "".join(traceback.format_tb(error.__traceback__)[-3:])
    if not reason and part == "main":
        missing = [s.n for s in script.steps if s.n not in run.reached and s.n not in run.delegated]
        if missing:
            reason = f"steps not played: {missing}"
    if not reason and seen.attempts:
        reason = f"egress during an offline journey: {seen.attempts[:3]}"
    return CaseResult(case_id(script.journey, part), script.journey, part, "failed" if reason else "passed",
                      tuple(run.reached), dict(run.delegated), tuple(seen.attempts), time.monotonic() - started,
                      reason, tuple(run.notes))  # fmt: skip


def suite_record(results: list[CaseResult], *, candidate: str, laptop_id: str, hardware_class: str) -> dict[str, Any]:
    """The `journey_run` record of a scripted suite run on one reference laptop with networking disabled."""
    return {
        "candidate": candidate,
        "laptop_id": laptop_id,
        "hardware_class": hardware_class,
        "network": "disabled",
        "egress_attempts": sum(len(r.egress) for r in results),
        "cases": {r.case_id: r.status for r in results},
    }


def record_errors(record: Any, scripts: dict[str, Script], journeys: list[str], candidate: str) -> list[str]:
    """A reference-laptop `journey_run`: the candidate's, zero egress, and every case of every journey passed."""
    from ..m23.records import errors

    problems = errors("journey_run", record)
    if problems:
        return problems
    found = []
    if record["candidate"] != candidate:
        found.append(f"{record['laptop_id']}: the journey run belongs to another candidate")
    for journey in journeys:
        s = scripts[journey]
        for part in ("main", *(b.id for b in s.branches)):
            status = record["cases"].get(case_id(journey, part))
            if status != "passed":
                found.append(f"{record['laptop_id']}: {case_id(journey, part)} {status or 'missing'}")
    return found
