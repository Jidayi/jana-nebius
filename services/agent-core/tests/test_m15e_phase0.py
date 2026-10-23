"""M15 phase 0: note erasure on delete (LRN-37, MEM-14), learning evidence from the tutor (LRN-01, G54), batched
writes with the notes writer capability (MEM-01), the early memory tools (TOL-23), the memory keys and the pack index.
Every learner, note and canary here is synthetic test data."""

from __future__ import annotations

import asyncio
import io
import sqlite3
import zipfile
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.contracts import validate
from agent_core.learner.service import NOTES_WRITER as SERVICE_TOKEN
from agent_core.learner.service import Capability, NestedTransaction, NewEvent, WriterRefused
from agent_core.memory.write import NOTES_WRITER, compact_storage, forget
from agent_core.store.exports import open_with_passphrase
from agent_core.store.ids import new_ulid
from agent_core.store.pack_index import PackIndex
from agent_core.store.packs import TABLES, table_sha256, write_pack
from agent_core.tools.catalogue import Availability, role_tools, visible_tools
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.registry import EARLY_TOOLS, build_entries, register_entries
from agent_core.tools.spec import SessionCtx
from agent_core.tools.specs import registry
from api_harness import STATEMENT, ask, start_core, stop_core
from engine_harness import checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from learner_harness import make_learner
from pack_builder.build import load_source
from pack_builder.signing import sign
from signing_service.keys import DEV_KEY_ID, dev_key
from test_m10a_profiles import Api, student
from test_m10d_deletion_export import PASSPHRASE, _export, _settings

LOOP = asyncio.new_event_loop()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
CANARY = "qzvcanary8812"  # one lower-case token, so the full-text index holds it byte for byte


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _note(text: str) -> dict[str, Any]:
    return {"note_id": new_ulid(), "text": text, "source_event_ids": [new_ulid()], "status": "active"}


# --- LRN-37, MEM-14: a deleted note's text is gone everywhere ----------------------------------------------------


def _index_rows(conn: sqlite3.Connection) -> bytes:
    """Every row of the notes full-text index's shadow tables, as bytes."""
    out = b""
    query = "SELECT name FROM sqlite_schema WHERE type = 'table' AND name LIKE 'notes_fts_%'"
    names = [r[0] for r in conn.execute(query)]
    assert names, "the notes index has shadow tables"
    for name in names:
        for row in conn.execute(f'SELECT * FROM "{name}"'):  # noqa: S608 - names read from the file itself
            out += b"".join(v if isinstance(v, bytes) else str(v).encode() for v in row)
    return out


def lrn37_note_text_erased(tmp_path: Path) -> None:
    needle = CANARY.encode()

    async def scenario() -> None:
        r = await start_core(tmp_path / "device", settings=_settings(), worker=False)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = (await api.unlock(profile)).json()["profile_token"]
            learner = r.core.records.learner
            note = _note(f"Mixes up {CANARY} speed and velocity")
            learner.record("note_written", note, source="reflector", writer=NOTES_WRITER)
            kept = _note("Gives the unit with every final answer")
            learner.record("note_written", kept, source="reflector", writer=NOTES_WRITER)
            path = r.runtime.directory.learner_path(profile)
            wal = path.with_name(path.name + "-wal")
            conn = learner.conn
            # The checks below can see the text while it is stored.
            assert needle in path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")
            assert needle in _index_rows(conn)

            deleted = await api.call("DELETE", f"/v1/memory/mem_{note['note_id']}", profile=token)
            assert deleted.status_code == 204, deleted.text
            again = await api.call("DELETE", f"/v1/memory/mem_{note['note_id']}", profile=token)
            assert again.status_code == 404
            assert compact_storage(conn).wal_busy is False  # the next compaction finds nothing left to move

            assert needle not in path.read_bytes(), "the database file"
            assert not wal.exists() or needle not in wal.read_bytes(), "the write-ahead log"
            assert needle not in _index_rows(conn), "the full-text index"
            payloads = b"".join(str(p).encode() for (p,) in conn.execute("SELECT payload FROM events"))
            assert needle not in payloads, "the event log"
            assert conn.execute("SELECT status, text FROM notes WHERE note_id = ?", (note["note_id"],)).fetchone() == (
                "deleted",
                "",
            )
            deletion = conn.execute(
                "SELECT source, json_extract(payload, '$.actor_role') FROM events WHERE type = 'note_deleted'"
            ).fetchall()
            assert deletion == [("student", "student")]
            # The other note is untouched, and only one write event was erased.
            assert conn.execute("SELECT text FROM notes WHERE note_id = ?", (kept["note_id"],)).fetchone() == (
                kept["text"],
            )
            assert conn.execute("SELECT count(*) FROM events WHERE erased_at IS NOT NULL").fetchone() == (1,)

            _, archive = await _export(api, None, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                       passphrase=PASSPHRASE)  # fmt: skip
            opened = zipfile.ZipFile(io.BytesIO(open_with_passphrase(archive.read_bytes(), PASSPHRASE)))
            contents = b"".join(opened.read(name) for name in opened.namelist())
            assert b"Gives the unit" in contents, "the export carries the kept note"
            assert needle not in contents, "a fresh export"
        finally:
            await stop_core(r)

    run(scenario())


def _raw_bytes(path: Path) -> bytes:
    wal = path.with_name(path.name + "-wal")
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b"")


def test_every_note_deletion_erases_the_text(tmp_path: Path) -> None:
    """Not only the API's forget: a Reflector drop, a bound expiry, a Reflector update (the old wording), accepting a
    review (the replaced note), rejecting one (the pending note) and accepting a drop proposal all leave no byte of
    the old text in the database file, its log, the full-text index's shadow tables, the event payloads or a fresh
    export, with no caller compacting by hand (LRN-37, MEM-14, D71)."""
    from agent_core.memory import queries
    from agent_core.memory.write import NoteAction, apply_reflection, resolve_review

    canaries = {case: f"qzv{case}gone" for case in ("drop", "expiry", "update", "accept", "reject", "dropreview")}

    async def scenario() -> None:
        r = await start_core(tmp_path / "device", settings=_settings(), worker=False)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            await api.unlock(profile)
            learner = r.core.records.learner
            conn = learner.conn
            day = "2026-10-09"
            sid = new_ulid()
            conn.execute("INSERT INTO sessions (session_id, mode, subject, started_at) VALUES (?, 'guided',"
                         " 'physics', 0)", (sid,))  # fmt: skip

            def hint() -> str:
                return learner.record("hint", {"session_id": sid, "problem_ref": "p", "step_index": 0, "rung": 1,
                                               "trigger": "student_request"}, source="engine",
                                      session_id=sid).event_id  # fmt: skip

            def apply(*actions: NoteAction, role: str = "reflector", settings: Settings | None = None) -> Any:
                return apply_reflection(learner, list(actions), session_id=sid, session_date=day, summary=None,
                                        settings=settings or Settings(), role=role)  # type: ignore[arg-type]  # fmt: skip

            def add(text: str, role: str = "reflector") -> str:
                done = apply(NoteAction("add", text, day, (hint(),), subject="physics"), role=role)
                assert done.applied, done
                return str(done.applied[0])

            def review(review_id: str, accept: bool) -> None:
                item = next(i for i in queries.review_items(conn) if i.review_id == review_id)
                assert resolve_review(learner, review_id, seen_pending_event_id=item.pending_event_id,
                                      seen_target_event_id=item.target_event_id, accept=accept,
                                      actor="student")  # fmt: skip

            expiring = add(f"Checks {canaries['expiry']} units at the end")
            gone = add(f"Mixes up {canaries['drop']} speed and velocity")
            assert apply(NoteAction("drop", "", day, (hint(),), target_note_id=gone)).dropped == (gone,)
            old = add(f"Rounds {canaries['update']} values too early")
            assert apply(NoteAction("update", "Rounds intermediate values only at the end", day, (hint(),),
                                    target_note_id=old)).applied == (old,)  # fmt: skip
            target = add(f"Uses the wrong sign {canaries['accept']} for g")
            pending = apply(NoteAction("contradiction", "Uses a negative g for upward motion", day, (hint(),),
                                       target_note_id=target)).pending_review[0]  # fmt: skip
            review(pending, accept=True)
            kept = add("Draws a labelled sketch before choosing an equation")
            refused = apply(NoteAction("contradiction", f"Skips {canaries['reject']} the labelled sketch", day,
                                       (hint(),), target_note_id=kept)).pending_review[0]  # fmt: skip
            review(refused, accept=False)
            owned = add(f"Wants {canaries['dropreview']} more graph questions", role="student_request")
            proposal = apply(NoteAction("drop", "", day, (hint(),), target_note_id=owned)).pending_review[0]
            review(proposal, accept=True)
            # The bound: the oldest Reflector note (written first) expires to make room.
            small = Settings(notes_max_per_subject=len(queries.stored_notes(conn)))
            assert expiring in apply(NoteAction("add", "Writes the formula before substituting", day, (hint(),),
                                                subject="physics"), settings=small).expired  # fmt: skip

            path = r.runtime.directory.learner_path(profile)
            raw, index = _raw_bytes(path), _index_rows(conn)
            payloads = b"".join(str(p).encode() for (p,) in conn.execute("SELECT payload FROM events"))
            _, archive = await _export(api, None, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                       passphrase=PASSPHRASE)  # fmt: skip
            opened = zipfile.ZipFile(io.BytesIO(open_with_passphrase(archive.read_bytes(), PASSPHRASE)))
            contents = b"".join(opened.read(name) for name in opened.namelist())
            assert b"Rounds intermediate values only at the end" in contents, "the export carries the current text"
            for case, canary in canaries.items():
                needle = canary.encode()
                left = {"file+log": needle in raw, "index": needle in index, "events": needle in payloads,
                        "export": needle in contents}  # fmt: skip
                assert not any(left.values()), (case, left)
        finally:
            await stop_core(r)

    run(scenario())


def test_note_deletion_through_the_api_is_recorded_as_the_student(tmp_path: Path) -> None:
    async def scenario() -> list[Any]:
        r = await start_core(tmp_path, settings=_settings(), worker=False)
        api = Api(r)
        try:
            profile = await api.add(student("Kofi"))
            token = (await api.unlock(profile)).json()["profile_token"]
            note = _note("Draws the graph before calculating")
            r.core.records.learner.record("note_written", note, source="reflector", writer=NOTES_WRITER)
            reply = await api.call("DELETE", f"/v1/memory/mem_{note['note_id']}", profile=token)
            assert reply.status_code == 204, reply.text
            return r.core.records.learner.conn.execute(
                "SELECT source, json_extract(payload, '$.actor_role') FROM events WHERE type = 'note_deleted'"
            ).fetchall()
        finally:
            await stop_core(r)

    assert run(scenario()) == [("student", "student")]


def test_forget_is_one_transaction_and_idempotent() -> None:
    learner = make_learner()
    note = _note("Checks units at the end")
    learner.record("note_written", note, source="reflector", writer=NOTES_WRITER)
    assert forget(learner, new_ulid(), "student") is None, "no such note: nothing written"
    done = forget(learner, note["note_id"], "system_expiry")
    assert done is not None and len(done.erased_event_ids) == 1
    assert forget(learner, note["note_id"], "student") is None, "already deleted"
    rows = learner.conn.execute("SELECT type, source, erased_at IS NOT NULL FROM events ORDER BY seq").fetchall()
    assert rows == [("note_written", "reflector", 1), ("note_deleted", "engine", 0)]
    for event in learner.log.by_seq():
        validate("learning/learning-event", event.envelope())


# --- MEM-01 groundwork: batches and the notes writer -------------------------------------------------------------


def _session_started(sid: str) -> NewEvent:
    payload = {"session_id": sid, "mode": "guided", "entry": "question", "hardware_class": "mid",
               "subject": "physics"}  # fmt: skip
    return NewEvent("session_started", payload, source="engine", session_id=sid)


def test_record_batch_is_atomic() -> None:
    learner = make_learner()
    sid = new_ulid()
    ended = NewEvent("session_ended", {"session_id": sid, "reason": "completed", "active_ms": 10}, source="engine",
                     session_id=sid)  # fmt: skip
    stored = learner.record_batch([_session_started(sid), ended], extra=lambda c, s: c.execute("SELECT 1"))
    assert [e.type for e in stored] == ["session_started", "session_ended"]

    def boom(conn: sqlite3.Connection, stored: list[Any]) -> None:
        raise RuntimeError("extra step failed")

    with pytest.raises(RuntimeError):
        learner.record_batch([_session_started(new_ulid())], extra=boom)
    bad = NewEvent("hint", {"session_id": sid, "rung": 9}, source="engine")
    with pytest.raises(ValueError, match="learning/learning-event"):
        learner.record_batch([_session_started(new_ulid()), bad])
    assert learner.conn.execute("SELECT count(*) FROM events").fetchone() == (2,), "failed batches leave nothing"


def test_no_await_inside_a_write() -> None:
    learner = make_learner()

    async def later(conn: sqlite3.Connection, stored: list[Any]) -> None:
        return None

    with pytest.raises(TypeError, match="await"):
        learner.record_batch([_session_started(new_ulid())], extra=later)
    assert learner.conn.execute("SELECT count(*) FROM events").fetchone() == (0,)
    learner.conn.execute("BEGIN")
    with pytest.raises(NestedTransaction):
        learner.record_batch([_session_started(new_ulid())])
    learner.conn.execute("ROLLBACK")


def test_notes_need_the_notes_writer() -> None:
    learner = make_learner()
    with pytest.raises(WriterRefused):
        learner.record("note_written", _note("Rounds too early"), source="reflector")
    with pytest.raises(WriterRefused):
        learner.record("note_deleted", {"note_id": new_ulid(), "actor_role": "student"}, source="student",
                       writer=Capability("notes_writer"))  # an equal-looking token is not the token  # fmt: skip
    note_fix = {"target": "note", "target_id": new_ulid(), "action": "dispute", "actor_role": "student"}
    with pytest.raises(WriterRefused):
        learner.record("correction", note_fix, source="student")
    assert learner.conn.execute("SELECT count(*) FROM events").fetchone() == (0,)
    preference = {"target": "preference", "target_id": "pace", "action": "override", "value": "slow",
                  "actor_role": "student"}  # fmt: skip
    learner.record("correction", preference, source="student")  # other layers need no capability
    learner.record("correction", note_fix, source="student", writer=NOTES_WRITER)
    assert NOTES_WRITER is SERVICE_TOKEN


# --- G54: learning evidence from the tutor -------------------------------------------------------------------------


def _collecting(engine: Any) -> Any:
    """A real learner behind the engine's learning sink: every event is validated and folded as the app does."""
    learner = make_learner()
    engine.learning = learner.record_batch
    return learner


def _events(learner: Any) -> list[Any]:
    """The learning evidence the engine recorded, every event validated; each turn's `skills_delivered` record
    (SKL-13) is checked against the contract and left out."""
    out = list(learner.log.by_seq())
    for event in out:
        validate("learning/learning-event", event.envelope())
    return [e for e in out if e.type != "skills_delivered"]


def _item(item_id: str) -> dict[str, Any]:
    return next(i for i in load_source(PACK).tables["items"] if i["id"] == item_id)


def test_practice_records_attempts_verdicts_and_hints(tmp_path: Path) -> None:
    item = _item("itm.phy.o.motion.0001")
    coach = [tutor(SAFE), tutor("Not quite yet. Which quantity goes on top?"),
             tutor("You know the distance and the time. Which quantity are you asked for?", hint_rung=1),
             tutor("That's right (checked). Well done."), tutor(SAFE)]  # fmt: skip
    script = {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}
    engine, _ = run(make_engine(tmp_path, script))
    learner = _collecting(engine)
    run(engine.start_practice(item))
    run(engine.student_turn("0.125 m/s"))
    run(engine.student_turn("I'm stuck"))
    run(engine.student_turn("8.0 m/s"))
    run(engine.start_problem(STATEMENT))  # a new question ends the practice item
    assert engine.state.practice is None
    run(close(engine))
    events = _events(learner)
    assert [e.type for e in events] == ["attempt", "verdict", "hint", "attempt", "verdict"]
    first, wrong, hint, second, right = (e.payload for e in events)
    assert first["item_id"] == first["problem_ref"] == item["id"] and first["kc_source"] == "pack"
    assert first["kc_ids"] == [{"kc_id": "kc.phy.o.motion.average_speed", "weight": 1.0}]
    assert (first["attempt_index"], second["attempt_index"]) == (1, 2)
    assert (wrong["outcome"], wrong["closes_opportunity"]) == ("incorrect", False)
    assert (right["outcome"], right["closes_opportunity"]) == ("correct", True)
    assert right["attempt_id"] == second["attempt_id"] and right["check_ids"]
    assert (hint["rung"], hint["source"], hint["trigger"]) == (1, "skill_ladder", "student_request")
    assert (hint["problem_ref"], hint["step_index"]) == (first["problem_ref"], first["step_index"])
    assert all(e.session_id == engine.state.session_id.removeprefix("ses_") and e.turn_id for e in events)
    assert "0.125" not in str([e.payload for e in events]), "no student text in a payload"
    # The projections fold them: one row per attempt, the closing one with the hint used on the step.
    rows = learner.conn.execute("SELECT outcome, hints_used, max_rung FROM attempts").fetchall()
    assert sorted(rows) == [("correct", 1, 1), ("incorrect", 0, 0)]
    assert learner.conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] >= 1


def test_guided_hint_and_safety_flag(tmp_path: Path) -> None:
    coach = [tutor(SAFE), tutor("Not quite yet. What is the speed at the very top?"),
             tutor("Think about what the speed is at the very top.", hint_rung=1)]  # fmt: skip
    engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}))
    learner = _collecting(engine)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))
    run(engine.student_turn("I'm stuck"))
    flagged = run(engine.student_turn("my home address is 4 Example Lane"))
    run(close(engine))
    events = _events(learner)
    assert [e.type for e in events] == ["hint", "safety_flagged"], "an ad-hoc attempt records no attempt yet (G54)"
    hint, safety = events[0].payload, events[1].payload
    assert hint["problem_ref"].startswith("adhoc:") and STATEMENT not in hint["problem_ref"]
    assert (hint["rung"], hint["source"]) == (1, "generic_template") and "kc_ids" not in hint
    assert safety == {"category": "personal_data", "template_id": "tpl.personal_details", "turn_id": flagged.turn_id}


def test_safety_flag_reaches_the_learner_database(tmp_path: Path) -> None:
    async def scenario() -> list[Any]:
        r = await start_core(tmp_path, worker=False)
        try:
            session = await r.session()
            reply = await r.post(f"/v1/sessions/{session}/turns", ask("my home address is 4 Example Lane"))
            assert reply.status_code == 202, reply.text
            for _ in range(200):
                entry = r.core.sessions[session]
                if entry.task is not None and entry.task.done():
                    break
                await asyncio.sleep(0.05)
            return r.core.records.learner.conn.execute(
                "SELECT json_extract(payload, '$.category'), session_id FROM events WHERE type = 'safety_flagged'"
            ).fetchall()
        finally:
            await stop_core(r)

    rows = run(scenario())
    assert len(rows) == 1 and rows[0][0] == "personal_data" and rows[0][1]


# --- TOL-23 groundwork: the memory tools ride in the S1 build -------------------------------------------------------


def test_memory_tools_registered_and_hidden() -> None:
    reg = registry()
    early = EARLY_TOOLS["S1"]
    assert early <= set(reg.specs) and early <= set(build_entries(REGISTER, "S1"))
    assert not early & set(register_entries(REGISTER, "S1")), "the register's S1 catalogue is unchanged"
    assert {reg[name].stage for name in early} == {"S2"} and {reg[name].toolset for name in early} == {"memory"}
    grants = REGISTER["roleGrants"]
    manifest = ["skill", "memory_recall", "session_recall"]
    assert role_tools("coach", manifest, reg, grants) == ["skill"], "an S1 role is not offered them"
    assert role_tools("coach", manifest, reg, grants, "S2") == manifest
    bound = {"memory_recall"}  # as if the engine had bound this handler only
    for stage, offered in (("S1", []), ("S2", ["memory_recall"])):
        available = Availability(lambda spec, s: spec.name in bound, grace_s=0)
        shown = visible_tools("coach", manifest[1:], reg, SessionCtx(subject="physics", stage=stage), available,
                              grants, Settings())  # fmt: skip
        assert [s.name for s in shown] == offered, stage
    note = reg["memory_note"].params["properties"]["actions"]
    assert note["type"] == "array", "memory_note takes a batch (G89)"
    assert reg["memory_recall"].params["properties"]["query_id"]["enum"] == [
        "profile_summary", "top_kcs", "active_misconceptions", "recent_notes", "preferences"
    ]  # fmt: skip


def test_memory_keys_declared() -> None:
    settings = Settings()
    expected = {"notes_max_chars": 140, "notes_max_active": 50, "notes_max_per_subject": 40,
                "notes_max_chars_per_subject": 6000, "memory_idle_write_min": 15, "snapshot_recent_notes": 2,
                "snapshot_top_kcs": 3, "snapshot_misconceptions_max": 3, "memory_index_line_chars": 60,
                "session_recall_max_matches": 5, "session_recall_match_chars": 300, "reflector_yield_tolerance": 0.10,
                "misconception_active_evidence": 2, "misconception_dispute_reactivate": 2, "gate_memory_recall": 0.90,
                "gate_note_support": 0.95, "gate_note_capture_violations": 0, "gate_fake_saves": 0}  # fmt: skip
    assert {k: getattr(settings, k) for k in expected} == expected
    assert settings.snapshot_hint_use_high > settings.snapshot_hint_use_medium


# --- the pack index ------------------------------------------------------------------------------------------------


def _signed_pack(folder: Path) -> Path:
    tables = load_source(PACK).tables
    manifest = {"pack_id": "pack.phy.o", "version": "0.1.0",
                "tables": [{"name": t, "sha256": table_sha256(t, tables.get(t, [])), "rows": len(tables.get(t, []))}
                           for t in TABLES]}  # fmt: skip
    path = folder / "pack.phy.o-0.1.0.pack"
    write_pack(path, sign(manifest, dev_key(), DEV_KEY_ID), {t: tables.get(t, []) for t in TABLES})
    return path


def test_pack_index_reads_the_verified_pack(tmp_path: Path) -> None:
    good = _signed_pack(tmp_path)
    index = PackIndex.load([good], Environment.DEV)
    assert index.rejected == [] and len(index.fingerprint) == 64
    kc = "kc.phy.o.motion.average_speed"
    statement = index.kc_statement(kc)
    assert statement and "speed" in statement.lower()
    topic = index.topic_of(kc)
    assert topic is not None and kc in index.kcs_in_topic(topic) and index.topic_title(topic)
    assert index.misconception_name("mc.phy.o.average_of_speeds") == "Averaging the speeds"
    assert index.item_difficulty("itm.phy.o.motion.0001") == -0.8
    assert index.reference_difficulty("kc.phy.o.motion.distance_or_displacement") == -1.0
    assert index.item_difficulty("itm.unknown") == 0.0 and index.kc_statement("kc.phy.o.none.none") is None
    for kc_id, needs in index.prerequisites().items():
        assert all(kc_id in index.dependents()[need] for need in needs)
    # The projections accept it as their content index.
    learner = make_learner(content=index)
    assert learner.projector.ctx.content is index
    # A pack that does not verify labels nothing.
    damaged = tmp_path / "damaged" / good.name
    damaged.parent.mkdir()
    damaged.write_bytes(good.read_bytes())
    conn = sqlite3.connect(damaged)
    conn.execute("UPDATE kcs SET record = json_set(record, '$.statement', 'changed') WHERE rowid = 1")
    conn.commit()
    conn.close()
    other = PackIndex.load([damaged], Environment.DEV)
    assert other.kcs == {} and other.rejected and other.fingerprint == ""
    assert PackIndex.load([good], Environment.PRODUCTION).rejected, "a production build refuses the test root"


@pytest.mark.parametrize("mode", ["guided", "check_working"])
def asm01_mode_tagging(tmp_path: Path, mode: str) -> None:
    """Checked ad-hoc answers carry their actual mode once a synthetic diagnosis supplies a KC."""
    from types import SimpleNamespace

    coach = [tutor(SAFE), tutor("Check the arithmetic in your working.")]
    engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}))
    learner = _collecting(engine)
    try:
        run(engine.start_problem(STATEMENT))
        engine.diagnosis = SimpleNamespace(kc_ids=("kc.phy.o.motion.free_fall",), output={"confidence": "high"})
        if mode == "guided":
            run(engine.student_turn("s = 7 m"))
        else:
            run(engine.check_working(STATEMENT, "s = 0.5*9.8*2.0^2\ns = 4.9*4.0\ns = 18.6"))
    finally:
        run(close(engine))
    attempts = [e.payload for e in _events(learner) if e.type == "attempt"]
    verdicts = [e.payload for e in _events(learner) if e.type == "verdict"]
    assert attempts and {a["mode"] for a in attempts} == {mode}
    assert {a["attempt_id"] for a in attempts} == {v["attempt_id"] for v in verdicts}
