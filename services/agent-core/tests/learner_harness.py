"""Synthetic learners for the M6 store and learner tests: in-memory learner databases and random, contract-valid
sessions. Every identifier, knowledge component and note here is invented test data."""

from __future__ import annotations

import random
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from agent_core.learner.mastery import MasteryParams
from agent_core.learner.projections import ContentIndex, Projection
from agent_core.learner.service import Learner
from agent_core.memory.write import NOTES_WRITER
from agent_core.store.generated.schema import LEARNER
from agent_core.store.sqlite import connect, statements
from agent_core.trace.ids import new_ulid

PROFILE = "01J9ZZTESTPR0F1E0000000000"
DEVICE_A = "a" * 32
DEVICE_B = "b" * 32
START_MS = 1_760_000_000_000
SKEW_MS = 86_400_000
KCS = (
    "kc.phy.o.kinematics.speed_from_distance_time",
    "kc.phy.o.kinematics.acceleration_from_velocities",
    "kc.phy.o.kinematics.read_distance_time_graph",
    "kc.phy.o.kinematics.area_under_velocity_time",
    "kc.mth.o.algebra.rearrange_linear",
)
MODES = ("guided", "practice", "learn", "check_working", "solution", "review")


def learner_db(path: str = ":memory:") -> sqlite3.Connection:
    conn = connect(path)
    for statement in statements(LEARNER):
        conn.execute(statement)
    conn.execute("PRAGMA user_version = 1")
    return conn


@dataclass
class Clock:
    now: int = START_MS

    def __call__(self) -> int:
        return self.now

    def tick(self, rng: random.Random, low: int = 1, high: int = 90_000) -> None:
        self.now += rng.randint(low, high)


def make_learner(
    conn: sqlite3.Connection | None = None,
    *,
    device: str = DEVICE_A,
    clock: Callable[[], int] | None = None,
    params: MasteryParams | None = None,
    content: ContentIndex | None = None,
    projections: list[Projection] | None = None,
) -> Learner:
    return Learner.open(
        conn or learner_db(),
        profile_id=PROFILE,
        device_id=device,
        wall_ms=clock or Clock(),
        max_skew_ms=SKEW_MS,
        params=params or MasteryParams(),
        content=content,
        projections=projections,
    )


@dataclass
class Session:
    """Random but well-formed learning activity: problems with attempts, hints and verdicts, checks and notes."""

    rng: random.Random
    learner: Learner
    clock: Clock
    notes: list[str] = field(default_factory=list)

    def emit(self, type_: str, payload: dict[str, Any], **envelope: Any) -> None:
        self.clock.tick(self.rng)
        self.learner.record(type_, payload, **envelope)

    def run(self, problems: int = 4) -> None:
        sid = new_ulid(self.clock.now)
        mode = self.rng.choice(MODES)
        self.emit(
            "session_started",
            {"session_id": sid, "mode": mode, "entry": "question", "hardware_class": "mid"},
            source="engine",
            session_id=sid,
        )
        for n in range(problems):
            self.problem(sid, mode, f"prob_{n}")
        if self.rng.random() < 0.3:
            self.check(sid)
        if self.rng.random() < 0.4:
            self.note(sid)
        self.emit(
            "session_ended",
            {"session_id": sid, "reason": "completed", "active_ms": self.rng.randint(0, 3_600_000)},
            source="engine",
            session_id=sid,
        )

    def problem(self, sid: str, mode: str, ref: str) -> None:
        kcs = self.rng.sample(KCS[:4], self.rng.choice((1, 1, 2)))
        weights = [{"kc_id": kc, "weight": round(1 / len(kcs), 3)} for kc in kcs]
        tries = self.rng.randint(1, 3)
        for index in range(1, tries + 1):
            if self.rng.random() < 0.3:
                self.emit(
                    "hint",
                    {"session_id": sid, "problem_ref": ref, "step_index": 0, "rung": self.rng.randint(1, 5),
                     "trigger": "student_request"},
                    source="engine",
                    session_id=sid,
                )  # fmt: skip
            attempt = new_ulid(self.clock.now)
            self.emit(
                "attempt",
                {
                    "attempt_id": attempt,
                    "session_id": sid,
                    "mode": mode,
                    "item_id": f"phy.o.kin.{ref}",
                    "problem_ref": ref,
                    "step_index": 0,
                    "kc_ids": weights,
                    "kc_source": "pack",
                    "attempt_index": index,
                    "response_kind": "typed",
                    "normalised_response": f"{self.rng.randint(1, 99)} m/s",
                    "time_ms": self.rng.randint(1000, 120_000),
                },
                source="student",
                session_id=sid,
            )
            last = index == tries
            outcome = self.rng.choice(("correct", "incorrect", "partial", "unverifiable")) if last else "incorrect"
            self.emit(
                "verdict",
                {
                    "verdict_id": new_ulid(self.clock.now),
                    "attempt_id": attempt,
                    "outcome": outcome,
                    "check_ids": [f"chk_{self.rng.randrange(16**8):08x}"],
                    "closes_opportunity": last,
                    "marker_version": "numeric.1",
                    **({"first_error_kc": kcs[-1]} if outcome == "incorrect" and self.rng.random() < 0.5 else {}),
                },
                source="checker",
                session_id=sid,
            )

    def check(self, sid: str) -> None:
        kc = self.rng.choice(KCS[:4])
        for item in (1, 2, 3):
            final = item == 3 or self.rng.random() < 0.2
            state = self.rng.choice(("passed", "failed")) if final else "in_progress"
            self.emit(
                "mastery_check",
                {"kc_id": kc, "item_index": item, "attempt_id": new_ulid(self.clock.now),
                 "item_result": "pass" if state != "failed" else "fail", "check_state": state},
                source="checker",
                session_id=sid,
            )  # fmt: skip
            if final:
                return

    def note(self, sid: str) -> None:
        note_id = new_ulid(self.clock.now)
        self.notes.append(note_id)
        self.emit(
            "note_written",
            {"note_id": note_id, "text": "Prefers drawing the graph before calculating",
             "source_event_ids": [new_ulid(self.clock.now)], "status": "active", "subject": "physics"},
            source="reflector",
            session_id=sid,
            writer=NOTES_WRITER,
        )  # fmt: skip
        if self.rng.random() < 0.3:
            self.emit("note_deleted", {"note_id": note_id, "actor_role": "student"}, source="student",
                      writer=NOTES_WRITER)  # fmt: skip


def random_log(seed: int, sessions: int = 3, learner: Learner | None = None, clock: Clock | None = None) -> Learner:
    rng = random.Random(seed)
    clock = clock or Clock()
    learner = learner or make_learner(clock=clock)
    learner.log.clock.wall_ms = clock
    for _ in range(sessions):
        Session(rng, learner, clock).run(rng.randint(1, 4))
        clock.now += rng.randint(3_600_000, 30 * 86_400_000)
    return learner


def envelopes(learner: Learner) -> list[dict[str, Any]]:
    return [event.envelope() for event in learner.log.by_seq()]
