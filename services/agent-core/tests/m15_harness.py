"""Shared fixtures for the M15.a-d learner-model tests: synthetic opportunities written through the real learner
service, a small invented prerequisite graph and a learner over the physics pack. Every learner, answer and timing
here is synthetic test data."""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from agent_core.config import Settings
from agent_core.engine.plans import PlanDesk
from agent_core.learner.mastery import DAY_MS, MasteryParams
from agent_core.learner.projections import NoContent
from agent_core.learner.service import Learner
from agent_core.store.ids import new_ulid
from learner_harness import Clock, make_learner
from memory_harness import PACK, Store, store

SETTINGS = Settings()
# An invented chain for the propagation tests: A is a prerequisite of B, B of C, C of D.
A, B, C, D = (f"kc.mth.o.chain.step_{n}" for n in "abcd")
CHAIN = NoContent(prereqs={B: [A], C: [B], D: [C]})


def chain_learner(clock: Clock | None = None, params: MasteryParams | None = None) -> Learner:
    return make_learner(clock=clock or Clock(), content=CHAIN, params=params)


@dataclass
class Practice:
    """Writes whole opportunities: a session, hints, attempts and verdicts, the last one closing."""

    learner: Learner
    clock: Clock
    session: str | None = None
    problems: int = 0
    sessions: list[str] = field(default_factory=list)

    def start(self) -> str:
        self.clock.now += 60_000
        sid = new_ulid(self.clock.now)
        self.learner.record("session_started", {"session_id": sid, "mode": "practice", "entry": "question",
                                                "hardware_class": "mid"}, source="engine", session_id=sid)  # fmt: skip
        self.session = sid
        self.sessions.append(sid)
        return sid

    def end(self, reason: str = "completed", active_ms: int = 600_000) -> None:
        assert self.session is not None
        self.clock.now += 1000
        self.learner.record("session_ended", {"session_id": self.session, "reason": reason, "active_ms": active_ms},
                            source="engine", session_id=self.session)  # fmt: skip
        self.session = None

    def opportunity(
        self,
        kcs: Sequence[str] | str,
        outcomes: Sequence[str] = ("correct",),
        *,
        rung: int = 0,
        mode: str = "practice",
        time_ms: int = 20_000,
        item_id: str | None = None,
        problem: str | None = None,
        first_error_kc: str | None = None,
        close: bool = True,
        confidence: int | None = None,
        source: str = "pack",
        kc_confidence: float | None = None,
    ) -> list[str]:
        """One step's attempts with the given graded outcomes (the last verdict closes unless `close` is False);
        hints up to `rung` before the first attempt. Returns the verdict ids."""
        if self.session is None:
            self.start()
        sid = self.session
        assert sid is not None
        kc_list = [kcs] if isinstance(kcs, str) else list(kcs)
        self.problems += 1
        ref = problem or f"prob_{self.problems}"
        for r in range(1, rung + 1):
            self.clock.now += 15_000
            self.learner.record("hint", {"session_id": sid, "problem_ref": ref, "step_index": 0, "rung": r,
                                         "trigger": "student_request"}, source="engine", session_id=sid)  # fmt: skip
        verdicts = []
        for index, outcome in enumerate(outcomes, start=1):
            self.clock.now += max(time_ms, 1000)
            aid = new_ulid(self.clock.now)
            attempt: dict[str, Any] = {
                "attempt_id": aid, "session_id": sid, "mode": mode, "item_id": item_id, "problem_ref": ref,
                "step_index": 0, "kc_ids": [{"kc_id": k, "weight": round(1 / len(kc_list), 6)} for k in kc_list],
                "kc_source": source, "attempt_index": index, "response_kind": "typed", "time_ms": time_ms,
            }  # fmt: skip
            if kc_confidence is not None:
                attempt["kc_confidence"] = kc_confidence
            if confidence is not None:
                attempt["confidence_rating"] = confidence
            self.learner.record("attempt", attempt, source="student", session_id=sid)
            vid = new_ulid(self.clock.now)
            last = index == len(outcomes)
            verdict: dict[str, Any] = {"verdict_id": vid, "attempt_id": aid, "outcome": outcome,
                                       "check_ids": ["chk_test_key"], "closes_opportunity": last and close,
                                       "marker_version": "test.1"}  # fmt: skip
            if first_error_kc is not None and outcome == "incorrect":
                verdict["first_error_kc"] = first_error_kc
            self.learner.record("verdict", verdict, source="checker", session_id=sid)
            verdicts.append(vid)
        return verdicts

    def day(self, days: float = 1.0) -> None:
        self.clock.now += int(days * DAY_MS)


def row(learner: Learner, kc: str) -> dict[str, Any]:
    found = learner.conn.execute(
        "SELECT status, p_mastery, n_eff, succ_w, fail_w, implied_w, attempts, fading_stage, stuck_count, moved_on_at"
        " FROM kc_mastery WHERE kc_id = ?",
        (kc,),
    ).fetchone()
    if found is None:
        return {}
    keys = ("status", "p", "n_eff", "succ_w", "fail_w", "implied_w", "attempts", "fading", "stuck", "moved_on_at")
    return dict(zip(keys, found, strict=True))


def card(learner: Learner, kc: str) -> dict[str, Any] | None:
    found = learner.conn.execute(
        "SELECT state, stability, difficulty, due_at, reps, lapses, last_review_at FROM review_cards WHERE kc_id = ?",
        (kc,),
    ).fetchone()
    keys = ("state", "stability", "difficulty", "due_at", "reps", "lapses", "last_review_at")
    return dict(zip(keys, found, strict=True)) if found else None


def physics(day: str = "2026-10-09", exam: str | None = "2027-06-01", subjects: Sequence[str] = ("physics",)
            ) -> tuple[Store, Practice, PlanDesk]:  # fmt: skip
    """A learner over the physics pack, with its practice writer and plan desk on the same clock."""
    held = store(day=day)
    held.conn.execute("UPDATE profile SET subjects = ?, exam_date = ?", (json.dumps(list(subjects)), exam))
    practice = Practice(held.learner, held.clock)
    desk = PlanDesk(held.learner, PACK, SETTINGS, clock_ms=held.clock)
    return held, practice, desk
