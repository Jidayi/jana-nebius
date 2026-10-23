"""STU-14: local, extractive generation from accepted content; synthetic session and scripted local selector."""

import asyncio
import json
from types import SimpleNamespace

from agent_core.engine.session_notes import COLUMNS, SessionNotesQueue, archive_note, evidence, materialise, note_of
from agent_core.store.sqlite import open_database
from agent_core.store.transcript import TranscriptStore

SID = "00000000000000000000000001"
TURN = "trn_00000000000000000000000001"
TEXT = "Divide distance by time."


class LocalSelector:
    calls = 0

    async def local_ready(self):
        return True

    async def session_note(self, sources):
        self.calls += 1
        assert all("REJECTED" not in s["text"] and "DISCARDED" not in s["text"] for s in sources)
        return {"statements": [{"evidence": 0, "section": "method"}]}, True


def seeded(tmp_path):
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    store = TranscriptStore(conn)
    store.start_session(
        {
            "session_id": "ses_" + SID,
            "mode": "guided",
            "subject": "physics",
            "topic_id": None,
            "title": "Speed",
            "created_ts": 1,
        }
    )
    for n, state, text in [
        (1, "complete", TEXT),
        (2, "error", "REJECTED candidate"),
        (3, "interrupted", "DISCARDED speculative turn"),
    ]:
        turn = f"trn_{n:026d}"
        store.start_turn("ses_" + SID, turn_id=turn, message_id=None, student_text=None, input_kind="typed", ts=n)
        store.put_part(
            turn, {"part_id": f"prt_{n:026d}", "kind": "text", "index": 0, "status": "complete", "text": text}, n
        )
        store.end_turn(turn, status=state, usage=None, ts=n + 10)
    store.end_session("ses_" + SID, reason="completed", ts=100)
    capture = SimpleNamespace(check=lambda text, **kw: SimpleNamespace(blocked=False))
    model = LocalSelector()
    queue = SessionNotesQueue(lambda: conn, lambda: model, lambda: capture, lambda: False, lambda: 200)
    return conn, queue, capture, model


def stu14_notes_from_accepted_turns_only(tmp_path):
    conn, queue, capture, model = seeded(tmp_path)
    queue.scan()
    row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
    asyncio.run(queue.generate(conn, *row))
    note = note_of(conn.execute(f"SELECT {COLUMNS} FROM session_notes").fetchone())  # noqa: S608 - fixed columns
    assert note["state"] == "ready" and model.calls == 1
    assert note["statements"] == [
        {
            "text": TEXT,
            "section": "method",
            "reference": {"session_id": "ses_" + SID, "turn_id": TURN, "trace_id": None},
        }
    ]
    assert [s["text"] for s in evidence(conn, SID, capture)] == [TEXT]
    assert conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0


def stu14_unreferenced_statement_withheld(tmp_path, caplog):
    caplog.set_level("INFO")
    conn, queue, capture, _ = seeded(tmp_path)
    sources = evidence(conn, SID, capture)
    statements, withheld = materialise(
        {
            "statements": [
                {"text": "Unsupported assertion", "section": "method"},
                {"evidence": 99, "section": "method"},
                {"evidence": 0, "section": "method"},
            ]
        },
        sources,
    )
    assert withheld == 2 and len(statements) == 1 and statements[0]["text"] == TEXT
    queue.scan()
    conn.execute(
        "UPDATE session_notes SET statements=?",
        (json.dumps([{"text": "Unsupported assertion", "section": "method"}, *statements]),),
    )
    assert note_of(conn.execute(f"SELECT {COLUMNS} FROM session_notes").fetchone())["statements"] == statements  # noqa: S608 - fixed columns
    assert "withheld at display: 1" in caplog.text
    assert "Unsupported assertion" not in caplog.text


def test_note_generation_queues_without_a_local_model_and_recovers(tmp_path):
    conn, queue, _, model = seeded(tmp_path)
    queue.model = lambda: None
    queue.scan()
    row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
    asyncio.run(queue.generate(conn, *row))
    assert conn.execute("SELECT state FROM session_notes").fetchone()[0] == "no_model"
    queue.model = lambda: model
    asyncio.run(queue.generate(conn, *row))
    assert conn.execute("SELECT state FROM session_notes").fetchone()[0] == "ready"


def test_deleted_or_private_note_is_not_recreated_or_unmasked_by_generation(tmp_path):
    conn, queue, _, _ = seeded(tmp_path)
    queue.scan()
    row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
    conn.execute("UPDATE session_notes SET private=1")
    asyncio.run(queue.generate(conn, *row))
    note = note_of(conn.execute(f"SELECT {COLUMNS} FROM session_notes").fetchone())  # noqa: S608 - fixed columns
    assert note["title"] is None and note["statements"] == [] and note["kc_ids"] == []
    conn.execute("UPDATE session_notes SET state='deleted',title='',statements='[]'")
    queue.scan()
    asyncio.run(queue.generate(conn, *row))
    assert conn.execute("SELECT state,statements FROM session_notes").fetchone() == ("deleted", "[]")


def test_cloud_result_is_refused_and_source_context_changes_drop_output(tmp_path):
    conn, queue, _, _ = seeded(tmp_path)

    class Cloud:
        async def local_ready(self):
            return True

        async def session_note(self, sources):
            return {"statements": [{"evidence": 0, "section": "method"}]}, False

    queue.model = lambda: Cloud()
    queue.scan()
    row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
    asyncio.run(queue.generate(conn, *row))
    assert conn.execute("SELECT state,statements FROM session_notes").fetchone() == ("failed", "[]")


def test_session_note_archive_shape_keeps_private_mark_and_references(tmp_path):
    conn, queue, _, _ = seeded(tmp_path)
    queue.scan()
    row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
    asyncio.run(queue.generate(conn, *row))
    conn.execute("UPDATE session_notes SET private=1")
    raw = conn.execute(f"SELECT {COLUMNS} FROM session_notes").fetchone()  # noqa: S608 - fixed columns
    record = dict(zip(COLUMNS.split(","), raw, strict=True))
    assert archive_note(record) == raw


def stu14_search_delete_export(tmp_path):
    from agent_core.store.exports import build_profile_archive, read_profile_archive
    from api_harness import start_core, stop_core
    from test_m10a_profiles import Api, student
    from test_m10d_records import _session

    async def scenario():
        r = await start_core(tmp_path)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = (await api.unlock(profile)).json()["profile_token"]
            sid, _ = await _session(api, r, token)
            ended = await api.call("POST", f"/v1/sessions/{sid}/end", {}, profile=token)
            assert ended.status_code == 200, ended.text
            queue = r.core.session_notes
            await queue.close()
            queue.model = lambda: LocalSelector()
            queue.capture = lambda: SimpleNamespace(check=lambda text, **kw: SimpleNamespace(blocked=False))
            queue.scan()
            conn = queue.connection()
            row = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()
            await queue.generate(conn, *row)
            notes = (await api.call("GET", "/v1/session-notes", profile=token)).json()
            assert len(notes) == 1 and notes[0]["state"] == "ready" and notes[0]["statements"]
            identity = notes[0]["note_id"]
            word = notes[0]["statements"][0]["text"].split()[0]
            assert len((await api.call("GET", f"/v1/session-notes?q={word}", profile=token)).json()) == 1
            assert (await api.call("GET", "/v1/session-notes")).status_code == 401
            await api.call("PATCH", f"/v1/session-notes/{identity}", {"private": True}, profile=token)
            assert (await api.call("GET", f"/v1/session-notes?q={word}", profile=token)).json() == []
            listed = (await api.call("GET", "/v1/session-notes", profile=token)).json()[0]
            assert listed["title"] is None and listed["statements"] == [] and listed["kc_ids"] == []
            assert (
                await api.call("POST", f"/v1/session-notes/{identity}/open", {"confirm": False}, profile=token)
            ).status_code == 422
            opened = await api.call("POST", f"/v1/session-notes/{identity}/open", {"confirm": True}, profile=token)
            assert opened.json()["statements"]
            archive = read_profile_archive(
                build_profile_archive(conn, tmp_path, "0.0.0", "2026-10-17T00:00:00Z", [], False)
            )
            assert archive.manifest["version"] == 2
            assert archive.session_notes[0]["private"] == 1
            from agent_core.store.exports import seal_with_passphrase
            from test_m10d_deletion_export import PASSPHRASE

            path = tmp_path / "notes.janaprofile"
            path.write_bytes(
                seal_with_passphrase(
                    build_profile_archive(conn, tmp_path, "0.0.0", "2026-10-17T00:00:00Z", [], False),
                    PASSPHRASE,
                    r.core.settings.passphrase_argon2_memory_kib,
                    r.core.settings.passphrase_argon2_iterations,
                )
            )
            imported = await api.call(
                "POST", "/v1/profiles/import", {"source": {"kind": "file", "path": str(path)}, "passphrase": PASSPHRASE}
            )
            assert imported.status_code == 202, imported.text
            job = (await api.call("GET", f"/v1/jobs/{imported.json()['job_id']}")).json()
            assert job["state"] == "done", job
            restored = job["result_ref"]
            restored_token = (await api.unlock(restored)).json()["profile_token"]
            restored_notes = (await api.call("GET", "/v1/session-notes", profile=restored_token)).json()
            assert len(restored_notes) == 1 and restored_notes[0]["private"] and restored_notes[0]["statements"] == []
            token = (await api.unlock(profile)).json()["profile_token"]
            assert json.loads(archive.session_notes[0]["statements"])[0]["reference"]["session_id"] == sid
            other = await api.add(student("Ben"))
            token_b = (await api.unlock(other)).json()["profile_token"]
            assert (await api.call("GET", "/v1/session-notes", profile=token_b)).json() == []
            assert (
                await api.call("POST", f"/v1/session-notes/{identity}/open", {"confirm": True}, profile=token_b)
            ).status_code == 404
            token = (await api.unlock(profile)).json()["profile_token"]
            assert (await api.call("DELETE", f"/v1/session-notes/{identity}", profile=token)).status_code == 204
            r.core.session_notes.scan()
            assert (await api.call("GET", "/v1/session-notes", profile=token)).json() == []
            archived_deletion = read_profile_archive(
                build_profile_archive(
                    r.core.session_notes.connection(), tmp_path, "0.0.0", "2026-10-17T00:00:00Z", [], False
                )
            )
            assert archived_deletion.session_notes[0]["state"] == "deleted"
            assert archived_deletion.session_notes[0]["statements"] == "[]"
            archive_note(archived_deletion.session_notes[0])
        finally:
            await stop_core(r)

    asyncio.run(scenario())


def test_session_note_runs_through_the_actual_local_structured_router(tmp_path):
    from agent_core.engine.reflection import ReflectorModel
    from engine_harness import close, make_engine, reply

    async def scenario():
        engine, _provider = await make_engine(
            tmp_path,
            {"reflector": [reply(json.dumps({"statements": [{"evidence": 0, "section": "method"}]}))]},
            worker=False,
        )
        try:
            deps = engine.deps
            model = ReflectorModel(deps.router, deps.assets, deps.settings, deps.bundled_schemas, frozenset())
            output, local = await model.session_note(
                [
                    {
                        "text": TEXT,
                        "section": None,
                        "reference": {"session_id": "ses_" + SID, "turn_id": TURN, "trace_id": None},
                    }
                ]
            )
            assert local and output == {"statements": [{"evidence": 0, "section": "method"}]}
        finally:
            await close(engine)

    asyncio.run(scenario())


def test_late_generation_cannot_replace_a_newer_revision_or_cross_profiles(tmp_path):
    conn, queue, _, _ = seeded(tmp_path)
    queue.scan()
    note_id, sid = conn.execute("SELECT note_id,session_id FROM session_notes").fetchone()

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()

        class Held:
            async def local_ready(self):
                return True

            async def session_note(self, sources):
                started.set()
                await release.wait()
                return {"statements": [{"evidence": 0, "section": "method"}]}, True

        queue.model = lambda: Held()
        job = asyncio.create_task(queue.generate(conn, note_id, sid))
        await started.wait()
        conn.execute("UPDATE session_notes SET source_revision=source_revision+1,state='queued'")
        release.set()
        await job
        assert conn.execute("SELECT state,statements FROM session_notes").fetchone() == ("queued", "[]")
        started.clear()
        release.clear()
        job = asyncio.create_task(queue.generate(conn, note_id, sid))
        await started.wait()
        queue.connection = lambda: None
        release.set()
        await job
        assert conn.execute("SELECT statements FROM session_notes").fetchone()[0] == "[]"

    asyncio.run(scenario())
