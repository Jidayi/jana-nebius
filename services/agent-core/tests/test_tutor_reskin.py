"""UXS-54: changing presentation preserves populated per-profile learning data, including after restart."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

from agent_core.store.ids import new_ulid
from agent_core.store.transcript import TranscriptStore
from api_harness import start_core, stop_core
from learner_harness import Clock
from memory_harness import SPEED, Store
from test_m10a_profiles import Api, student

TABLES = (
    "notes",
    "notes_fts",
    "kc_mastery",
    "learner_misconceptions",
    "review_cards",
    "preferences",
    "subject_ability",
    "attempts",
    "study_notes",
    "session_notes",
    "study_plans",
)


def learning(conn: sqlite3.Connection) -> dict[str, list[Any]]:
    return {table: sorted(conn.execute(f"SELECT * FROM {table}").fetchall(), key=repr) for table in TABLES}  # noqa: S608 - fixed names


def seed(conn: sqlite3.Connection, learner: Any, profile: str, now: int) -> None:
    sid, turn = "ses_" + new_ulid(now), "trn_" + new_ulid(now + 1)
    transcript = TranscriptStore(conn)
    transcript.start_session(
        {
            "session_id": sid,
            "mode": "guided",
            "subject": "physics",
            "topic_id": None,
            "title": "Speed",
            "created_ts": now,
        }
    )
    transcript.start_turn(sid, turn_id=turn, message_id=None, student_text=None, input_kind="typed", ts=now)
    transcript.put_part(
        turn,
        {
            "part_id": "prt_" + new_ulid(now + 2),
            "kind": "text",
            "index": 0,
            "status": "complete",
            "text": "Divide distance by time.",
        },
        now,
    )
    transcript.end_turn(turn, status="complete", usage=None, ts=now + 1)
    transcript.end_session(sid, reason="completed", ts=now + 1)
    Store(learner, Clock(now), profile).note("Checks the units before writing a final answer", sid)
    conn.execute(
        "INSERT INTO kc_mastery (kc_id,status,p_mastery,n_eff,succ_w,attempts,correct,last_seen_at,last_event_seq)"
        " VALUES (?, 'learning', 0.6, 3, 2, 3, 2, ?, 0)",
        (SPEED, now),
    )
    conn.execute(
        "INSERT INTO learner_misconceptions (misconception_id,kc_id,status,evidence_count,first_seen_at,"
        "last_seen_at,last_event_seq) VALUES ('mc.phy.o.speed',?,'active',2,?,?,0)",
        (SPEED, now, now),
    )
    conn.execute(
        "INSERT INTO review_cards (kc_id,state,stability,difficulty,due_at,reps,last_event_seq)"
        " VALUES (?,'review',3,5,?,2,0)",
        (SPEED, now + 30 * 86400000),
    )
    conn.execute("INSERT INTO preferences VALUES ('unprompted_help','false',1,0)")
    conn.execute("INSERT INTO subject_ability VALUES ('physics',0.4,3,0)")
    conn.execute(
        "INSERT INTO attempts (attempt_id,session_id,item_ref,kc_ids,mode,outcome,hints_used,time_ms,occurred_at)"
        " VALUES (?,?,'itm.phy.o.motion.0001',?,'practice','correct',0,1000,?)",
        ("att_" + new_ulid(now + 3), sid.removeprefix("ses_"), json.dumps([SPEED]), now),
    )
    conn.execute(
        "INSERT INTO study_notes (note_id,text,source,created_at,updated_at,private) VALUES (?,?,'typed',?,?,1)",
        ("nt_" + new_ulid(now + 4), "My own synthetic speed note", now, now),
    )
    revision = conn.execute(
        "SELECT max(ended_at)*1000+count(*) FROM turns WHERE session_id=? AND speaker='tutor' AND status='complete'",
        (sid.removeprefix("ses_"),),
    ).fetchone()[0]
    statement = {
        "section": "method",
        "text": "Divide distance by time.",
        "reference": {"session_id": sid, "turn_id": turn, "trace_id": None},
    }
    conn.execute(
        "INSERT INTO session_notes (note_id,session_id,title,subject,kc_ids,statements,state,private,"
        "source_revision,created_at,updated_at) VALUES (?,?,'Speed','physics',?,?,'ready',1,?,?,?)",
        (
            "snt_" + new_ulid(now + 5),
            sid.removeprefix("ses_"),
            json.dumps([SPEED]),
            json.dumps([statement]),
            revision,
            now,
            now,
        ),
    )


def uxs54_reskin_keeps_the_same_tutor(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, worker=False, stage="S2")
        try:
            api = Api(r)
            a, b = await api.add(student("Ama")), await api.add(student("Ben"))
            token = await api.token(a)
            seed(r.runtime.learner.conn, r.runtime.learner, a, r.core.clock_ms())
            before = learning(r.runtime.learner.conn)
            assert all(before[table] for table in TABLES if table != "study_plans"), (
                "Invariance must cover populated data"
            )
            avatars = ("jana", "orbit", "ray", "kite", "prism", "pebble")
            patches = [{"tutor_avatar": f"avatar.{name}", "tutor_name": name.title()} for name in avatars]
            patches += [
                {"tutor_name": "Nova"},
                {"tutor_avatar": "avatar.orbit"},
                {"tutor_avatar": "avatar.jana", "tutor_name": "Jana"},
            ]
            for patch in patches:
                reply = await api.call("PATCH", f"/v1/profiles/{a}/settings", patch, profile=token)
                assert reply.status_code == 200, reply.text
                assert learning(r.runtime.learner.conn) == before, patch
            bad = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"tutor_name": "Bad\nname"}, profile=token)
            assert bad.status_code == 422 and learning(r.runtime.learner.conn) == before
            identities = r.runtime.learner.conn.execute(
                "SELECT key,value FROM settings WHERE key IN ('tutor_name','tutor_avatar') ORDER BY key"
            ).fetchall()
            assert identities == [("tutor_avatar", '"avatar.jana"'), ("tutor_name", '"Jana"')]
            other = await api.token(b)
            assert learning(r.runtime.learner.conn) != before
            effective = (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()
            assert (effective["tutor_name"], effective["tutor_avatar"]) == ("Jana", "avatar.jana")
            token = await api.token(a)
            assert learning(r.runtime.learner.conn) == before
        finally:
            await stop_core(r)
        r = await start_core(tmp_path, worker=False, stage="S2")
        try:
            api = Api(r)
            token = await api.token(a)
            assert learning(r.runtime.learner.conn) == before
            profiles = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            assert {p["profile_id"] for p in profiles} == {a, b}, "No second tutor/profile was created"
            assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()["tutor_name"] == "Jana"
        finally:
            await stop_core(r)

    asyncio.run(scenario())
