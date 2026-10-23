"""Shared fixtures for the M15 engine and Reflector tests: a profile's learner database with the physics pack's
labels, the shipped capture filter, engines bound to that memory, scripted Reflector replies and an API core with the
Reflector queue attached. Every learner, note and message here is synthetic test data."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.engine.memory_session import MemoryAccess, MemorySource
from agent_core.engine.turn import Engine
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import NOTES_WRITER, Learner
from agent_core.memory.capture import CAPTURE_FILE, CaptureFilter
from agent_core.store.ids import new_ulid
from agent_core.store.pack_index import PackIndex
from api_harness import Running, start_core
from engine_harness import reply
from jana_tools import REPO_ROOT
from learner_harness import Clock, learner_db
from pack_builder.build import load_source

PACK_DIR = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
PACK = PackIndex.from_tables([({"pack_id": "pack.phy.o", "version": "0.1.0"}, load_source(PACK_DIR).tables)])
CAPTURE = CaptureFilter.load(REPO_ROOT / "content" / "agent" / CAPTURE_FILE, Settings())
SPEED = "kc.phy.o.motion.average_speed"
ITEM = "itm.phy.o.motion.0001"
DAY = "2026-10-09"  # the engine harness's session date
PROFILE_A = "01J9ZZTESTPR0F1EAAAAAAAAAA"
PROFILE_B = "01J9ZZTESTPR0F1EBBBBBBBBBB"
SAFE = "Which quantities does the question give you, and which one does it ask for?"


def settings(**kw: Any) -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), **kw)


def item(item_id: str = ITEM) -> dict[str, Any]:
    return next(i for i in load_source(PACK_DIR).tables["items"] if i["id"] == item_id)


def at_ms(day: str = DAY) -> int:
    """Noon UTC of a day, in milliseconds."""
    return int(datetime.fromisoformat(day).replace(hour=12, tzinfo=UTC).timestamp() * 1000)


@dataclass
class Store:
    """One profile's learner database, written through the real learner service."""

    learner: Learner
    clock: Clock
    profile: str

    @property
    def conn(self) -> sqlite3.Connection:
        return self.learner.conn

    def source(self) -> MemorySource:
        return MemorySource(self.learner, PACK, CAPTURE)

    def session(self, session_id: str, subject: str = "physics") -> str:
        sid = session_id.removeprefix("ses_")
        self.conn.execute("INSERT OR IGNORE INTO sessions (session_id, mode, subject, started_at) VALUES (?, 'guided',"
                          " ?, ?)", (sid, subject, self.clock.now))  # fmt: skip
        return sid

    def note(self, text: str, session_id: str, *, subject: str = "physics", source: str = "reflector") -> str:
        """A stored note, written as the notes writer does (evidence: a hint of the session)."""
        sid = self.session(session_id)
        self.clock.now += 1000
        hint = self.learner.record("hint", {"session_id": sid, "problem_ref": "prob_seed", "step_index": 0, "rung": 1,
                                            "trigger": "student_request", "kc_ids": [SPEED]},
                                   source="engine", session_id=sid)  # fmt: skip
        note_id = new_ulid(self.clock.now)
        self.clock.now += 1000
        self.learner.record("note_written", {"note_id": note_id, "text": text, "status": "active", "subject": subject,
                                             "source_event_ids": [hint.event_id]},
                            source=source, session_id=sid, writer=NOTES_WRITER)  # fmt: skip
        return note_id

    def saving(self, on: bool) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at) VALUES ('memory_saving', ?,"
            " 'student', NULL, '0', 0) ON CONFLICT (key) DO UPDATE SET value = excluded.value",
            ("true" if on else "false",),
        )


def store(profile: str = PROFILE_A, *, day: str = DAY, path: str = ":memory:") -> Store:
    clock = Clock(at_ms(day))
    learner = Learner.open(learner_db(path), profile_id=profile, device_id="d" * 32, wall_ms=clock,
                           max_skew_ms=86_400_000, params=MasteryParams(), content=PACK)  # fmt: skip
    conn = learner.conn
    conn.execute("INSERT INTO meta VALUES (1, ?, 1, ?, 'test', ?, 'test')", (profile, clock.now, clock.now))
    conn.execute(
        "INSERT INTO profile (profile_id, display_name, avatar, age_band, level, subjects, exam_date, created_at,"
        " updated_at) VALUES (?, 'Ama', 'disc-teal', '13_15', 'O', '[\"physics\"]', '2027-06-01', ?, ?)",
        (profile, clock.now, clock.now),
    )
    return Store(learner, clock, profile)


def bind(engine: Engine, held: Store | Callable[[], MemorySource | None], profile: str | None = None) -> None:
    """The engine's memory bound to a profile, reading whatever source is open, and its learning events recorded
    there (as the app's core does)."""
    if isinstance(held, Store):
        engine.bind_memory(MemoryAccess(profile or held.profile, held.source))
        engine.learning = held.learner.record_batch
    else:
        assert profile is not None
        engine.bind_memory(MemoryAccess(profile, held))


def reflection(*notes: dict[str, Any], summary: str = "You worked on speed questions today.", stall: float = 0) -> dict:
    """A scripted Reflector reply."""
    step = reply(json.dumps({"notes": list(notes), "summary_for_student": summary, "nothing_new": not notes}))
    return {**step, "stall_s": stall} if stall else step


def note(text: str, evidence: list[int], *, action: str = "add", target: int | None = None, kc: int | None = None,
         date: str = DAY) -> dict[str, Any]:  # fmt: skip
    return {"action": action, "text": text, "date": date, "evidence_refs": evidence, "target_ref": target,
            "kc_ref": kc}  # fmt: skip


def all_text(conn: sqlite3.Connection) -> str:
    """Every payload in the log, every note text, every session summary and every transcript text."""
    parts = [p for (p,) in conn.execute("SELECT payload FROM events")]
    parts += [t for (t,) in conn.execute("SELECT text FROM notes")]
    parts += [s or "" for (s,) in conn.execute("SELECT summary FROM sessions")]
    return " ".join(parts)


def tier(build_or_trace: dict[str, Any], name: str = "learner_snapshot", index: int = -1) -> str:
    """The sha256 of a tier in a turn trace's prompt record (the newest Coach prompt by default)."""
    prompts = [p for p in build_or_trace["prompts"] if p["role"] == "coach"]
    return str(next(t["sha256"] for t in prompts[index]["tiers"] if t["name"] == name))


def requests_of(provider: Any, role: str) -> list[dict[str, Any]]:
    return [r for r in provider.requests if r.get("_role") == role]


def system_of(request: dict[str, Any]) -> str:
    return str(request["messages"][0]["content"])


def user_texts(request: dict[str, Any]) -> str:
    return "\n".join(str(m.get("content")) for m in request["messages"] if m["role"] in ("user", "tool"))


async def wait_for(predicate: Callable[[], bool], timeout: float = 20.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("timed out waiting")
        await asyncio.sleep(0.01)


async def core_with_reflector(tmp_path: Path, provider: Any, *, worker: bool = True, **kw: Any) -> Running:
    """The API core with the device's Reflector queue attached, as the app starts it (no idle delay by default)."""
    r = await start_core(tmp_path, provider=provider, settings=settings(**{"reflector_idle_delay_s": 0.0, **kw}),
                         worker=worker)  # fmt: skip
    r.core.attach_reflector(r.runtime.reflector())
    return r


def run(coro: Any) -> Any:
    return asyncio.run(coro)
