"""Student voice: synthetic notes, visible lesson sources, OS playback and profile isolation."""

import asyncio
import contextlib
from types import SimpleNamespace

from agent_core.api.study_notes import block_text
from agent_core.contracts import errors
from agent_core.engine.events import new_id
from agent_core.store.checkpoints import CheckpointStore
from agent_core.store.exports import build_profile_archive, read_profile_archive
from agent_core.store.migration_v9 import LEARNER as V9_LEARNER
from agent_core.store.sqlite import MIGRATIONS, open_database
from learner_harness import learner_db
from test_m31_voice_activities import headers
from test_m31_voice_bridge import audio, event
from test_m32_adapter import body, contents, setup_adapter


def test_visible_lesson_reading_never_extracts_hidden_keys_or_faded_steps(tmp_path):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        shown = {
            "lesson_id": "les.phy.o.motion.test",
            "version": "1.0.0",
            "blocks": [
                {
                    "type": "quick_check",
                    "items": [
                        {
                            "item_id": "itm.phy.o.motion.0001",
                            "stem": "Find speed.",
                            "answer": "HIDDEN KEY",
                            "parts": [
                                {
                                    "prompt": "Choose a value",
                                    "input": {"options": [{"label": "two"}, {"label": "three"}]},
                                    "answer": "HIDDEN PART KEY",
                                }
                            ],
                        }
                    ],
                }
            ],
        }
        core.learn = lambda: contextlib.nullcontext(SimpleNamespace(lesson=lambda _: shown))
        try:
            source = {
                "kind": "lesson_question",
                "lesson_id": shown["lesson_id"],
                "version": "1.0.0",
                "block_index": 0,
                "item_id": "itm.phy.o.motion.0001",
            }
            before = core.snapshot(sid)
            response = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": source},
            )
            assert response.status_code == 200, response.text
            value = response.json()
            assert not errors("voice/activities", value)
            assert value["turn_id"] is None and value["part_id"] is None
            assert "HIDDEN" not in value["text"] and "three" in value["text"]
            assert core.snapshot(sid) == before and not runtime.adapter.jobs
            source["version"] = "0.9.0"
            response = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": source},
            )
            assert response.status_code == 409
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())
    text = block_text(
        {
            "type": "worked_example",
            "worked_example": {
                "problem": "Problem",
                "steps": [
                    {"n": 1, "latex": "HIDDEN", "reason": "SECRET"},
                    {"n": 2, "latex": "x=2", "reason": "Displayed"},
                ],
                "faded_steps": [1],
                "final_answer": {"latex": "2"},
            },
        }
    )
    assert "HIDDEN" not in text and "SECRET" not in text and "Displayed" in text


def stu15_transcript_confirmed_before_save(tmp_path):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn = learner_db(str(tmp_path / "learner.db"))
        core.store = CheckpointStore(conn)
        try:
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={
                    "type": "create_dictation",
                    "client_capture_id": new_id("cli"),
                    "purpose": "question",
                    "destination": "note",
                },
            )
            assert response.status_code == 200, response.text
            identity = response.json()["capture_id"]
            binding = runtime._active.bridge.binding
            runtime.activities.transcript(binding, identity, "Revise speed and units")
            assert conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 0
            key = headers()
            path = f"/v1/sessions/{sid}/study/notes"
            response = await client.post(
                path,
                headers=key,
                json={"type": "save_note", "text": "Revise speed, then units.", "capture_id": identity},
            )
            assert response.status_code == 200, response.text
            note = response.json()
            assert not errors("voice/activities#/$defs/study_note", note)
            assert note["source"] == "voice"
            assert conn.execute("SELECT count(*) FROM captures").fetchone()[0] == 0
            assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
            retry = await client.post(
                path,
                headers=key,
                json={"type": "save_note", "text": "Revise speed, then units.", "capture_id": identity},
            )
            assert retry.json() == note and conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 1
            found = await client.get("/v1/study/notes?q=units", headers=headers())
            assert found.json()["notes"] == [note]
            read = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": {"kind": "note", "note_id": note["note_id"]}},
            )
            assert read.status_code == 200 and read.json()["turn_id"] is None
            # Switching to another profile's connection cannot find the first profile's notes.
            other = learner_db()
            core.store = CheckpointStore(other)
            assert (await client.get("/v1/study/notes", headers=headers())).json()["notes"] == []
            core.store = CheckpointStore(conn)
            other.close()
            deleted = await client.delete(f"/v1/study/notes/{note['note_id']}", headers=headers())
            assert deleted.status_code == 204
            assert (await client.get("/v1/study/notes?q=units", headers=headers())).json()["notes"] == []
            assert not runtime.adapter.jobs and not core.voice_engines
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            conn.close()

    asyncio.run(scenario())


def test_note_destination_cannot_be_used_with_a_question_capture(tmp_path):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn = learner_db()
        core.store = CheckpointStore(conn)
        try:
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
            )
            identity = response.json()["capture_id"]
            runtime.activities.transcript(runtime._active.bridge.binding, identity, "A question")
            response = await client.post(
                f"/v1/sessions/{sid}/study/notes",
                headers=headers(),
                json={"type": "save_note", "text": "Do not save", "capture_id": identity},
            )
            assert response.status_code == 404
            assert conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 0
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            conn.close()

    asyncio.run(scenario())


def test_forward_migration_preserves_existing_capture_and_adds_notes(tmp_path):
    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", MIGRATIONS["learner"][:3])
    conn.execute("INSERT INTO sessions (session_id, mode, subject, started_at) VALUES ('test','guided','physics',0)")
    identity = new_id("cap")
    conn.execute("INSERT INTO captures VALUES (?, 'test', '{}', 1000)", (identity,))
    conn.close()
    conn, applied = open_database(path, "learner")
    # Every step after v3 runs, the study-notes step (v4) first.
    assert [step.version for step in applied] == [step.version for step in MIGRATIONS["learner"][3:]]
    assert applied[0].version == 4
    assert conn.execute("SELECT capture_id FROM captures").fetchone()[0] == identity
    assert conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 0
    conn.close()


def test_notes_are_in_profile_archive_without_transcripts(tmp_path):
    conn = learner_db()
    # The archive carries session notes too (STU-14); their table comes from learner migration v9, not the contract.
    conn.executescript(V9_LEARNER)
    conn.execute(
        "INSERT INTO profile (profile_id,display_name,avatar,age_band,level,subjects,locale,created_at,updated_at) "
        "VALUES ('test','Synthetic','owl','16_17','O','[\"physics\"]','en',0,0)"
    )
    identity = new_id("nt")
    conn.execute(
        "INSERT INTO study_notes (note_id, text, source, created_at, updated_at) VALUES "
        "(?, 'A saved note', 'voice', 0, 0)",
        (identity,),
    )
    archive = read_profile_archive(build_profile_archive(conn, tmp_path, "0.0.0", "2026-10-15", [], False))
    assert archive.study_notes == [
        {"note_id": identity, "text": "A saved note", "source": "voice", "created_at": 0, "updated_at": 0}
    ]
    assert not archive.sessions and not archive.attachments
    conn.close()


def test_real_profile_notes_and_voice_preferences_are_local_and_isolated(tmp_path):
    from agent_core.config import Settings
    from api_harness import cli, start_core, stop_core
    from test_m10a_profiles import Api

    async def scenario():
        running = await start_core(tmp_path, settings=Settings(), worker=False)
        try:
            api = Api(running)
            first = await running.post(
                "/v1/profiles",
                {"display_name": "Ada", "avatar": "disc", "level": "O", "subjects": ["physics"], "age_band": "13_15"},
            )
            profile = first.json()["profile_id"]
            token = (await running.post(f"/v1/profiles/{profile}/open", {})).json()["profile_token"]
            session = await api.call(
                "POST",
                "/v1/sessions",
                {
                    "client_session_id": cli(),
                    "mode": "guided",
                    "subject": "physics",
                    "level": "O",
                    "origin": {"kind": "ask", "ref": None},
                },
                profile=token,
            )
            sid = session.json()["session_id"]
            preferences = await api.call(
                "PATCH",
                f"/v1/profiles/{profile}/settings",
                {"speech_rate": 1.25, "speech_voice": "local-test"},
                profile=token,
            )
            assert preferences.status_code == 200, preferences.text
            assert preferences.json()["speech_rate"] == 1.25 and preferences.json()["speech_voice"] == "local-test"
            bad = await api.call("PATCH", f"/v1/profiles/{profile}/settings", {"speech_rate": 2}, profile=token)
            assert bad.status_code == 422
            saved = await api.call(
                "POST",
                f"/v1/sessions/{sid}/study/notes",
                {"type": "save_note", "text": "A private revision note"},
                profile=token,
            )
            assert saved.status_code == 200, saved.text
            note = saved.json()
            assert (await api.call("GET", "/v1/study/notes", profile=token)).json()["notes"] == [note]
            assert (await api.call("GET", "/v1/study/notes")).status_code == 401
            second = await running.post(
                "/v1/profiles",
                {"display_name": "Ben", "avatar": "disc", "level": "O", "subjects": ["physics"], "age_band": "16_17"},
            )
            other_profile = second.json()["profile_id"]
            other_token = (await running.post(f"/v1/profiles/{other_profile}/open", {})).json()["profile_token"]
            assert (await api.call("GET", "/v1/study/notes", profile=other_token)).json()["notes"] == []
            assert (
                await api.call("DELETE", f"/v1/study/notes/{note['note_id']}", profile=other_token)
            ).status_code == 404
            token = (await running.post(f"/v1/profiles/{profile}/open", {})).json()["profile_token"]
            assert (await api.call("GET", "/v1/study/notes", profile=token)).json()["notes"] == [note]
            assert (await api.call("GET", f"/v1/profiles/{profile}/settings", profile=token)).json()[
                "speech_rate"
            ] == 1.25
        finally:
            await stop_core(running)

    asyncio.run(scenario())


def voc39_speak_directive_verbatim(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, early_response=False)
        core.learn = lambda: contextlib.nullcontext(
            SimpleNamespace(
                lesson=lambda _: {
                    "version": "1.0.0",
                    "blocks": [{"type": "summary", "text": "Use metres and seconds."}],
                }
            )
        )
        try:
            before = core.snapshot(sid)
            mint = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={
                    "type": "read_content",
                    "source": {
                        "kind": "lesson_block",
                        "lesson_id": "les.phy.o.motion.test",
                        "version": "1.0.0",
                        "block_index": 0,
                    },
                },
            )
            utterance = mint.json()
            assert mint.status_code == 200 and utterance["turn_id"] is None
            await socket.send({"type": "speak", "utterance_id": utterance["utterance_id"]})
            assert (await asyncio.wait_for(endpoint.sent.get(), 2))["type"] == "conversation.item.create"
            assert (await endpoint.sent.get())["type"] == "response.create"
            answer = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(instructions, "jana-speak: " + utterance["utterance_id"]),
            )
            assert contents(answer) == utterance["text"]
            await endpoint.incoming.put(event("response.created", response={"id": "resp_read"}))
            await endpoint.incoming.put(audio("resp_read"))
            assert "bytes" in await asyncio.wait_for(socket.receive(), 2)
            await socket.send({"type": "stop", "utterance_id": utterance["utterance_id"]})
            assert "text" in await socket.receive()
            assert core.snapshot(sid)["messages"] == before["messages"]
            assert not runtime.adapter.jobs and not core.voice_engines
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_accepted_question_and_hint_cards_read_only_their_displayed_fields(tmp_path):
    from test_m31_voice_activities import accepted

    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        try:
            part_id = await accepted(core, sid)
            part = core.sessions[sid].state["parts"][part_id]
            part.update(
                kind="card",
                card={
                    "card": {
                        "card_type": "question",
                        "prompt": "Choose a speed",
                        "options": [{"label": "Two metres per second", "answer": "HIDDEN"}],
                        "answer": "HIDDEN",
                    }
                },
            )
            source = {"kind": "session_card", "part_id": part_id}
            read = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": source},
            )
            assert read.status_code == 200, read.text
            assert "HIDDEN" not in read.json()["text"] and "Choose" in read.json()["text"]
            assert read.json()["turn_id"] == part["turn_id"]
            part["card"]["card"] = {
                "card_type": "hint",
                "body": "Try finding the elapsed time",
                "actions": ["next_hint"],
            }
            read = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": source},
            )
            assert read.status_code == 200 and "next_hint" not in read.json()["text"]
            part["status"] = "streaming"
            read = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": source},
            )
            assert read.status_code == 409
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_failed_note_disk_save_keeps_the_confirmable_draft_for_retry(tmp_path):
    import sqlite3

    import pytest
    from agent_core.api.study_notes import StudyNotes

    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn = learner_db()
        core.store = CheckpointStore(conn)
        try:
            capture = runtime.activities.create_dictation(
                sid, {"client_capture_id": new_id("cli"), "purpose": "question", "destination": "note"}
            )
            runtime.activities.transcript(runtime._active.bridge.binding, capture["capture_id"], "Keep this draft")
            notes = StudyNotes(core, runtime.activities)
            command = {"type": "save_note", "text": "Keep this edited draft", "capture_id": capture["capture_id"]}
            conn.execute(
                "CREATE TRIGGER reject_note BEFORE INSERT ON study_notes "
                "BEGIN SELECT RAISE(ABORT, 'synthetic disk failure'); END"
            )
            with pytest.raises(sqlite3.IntegrityError):
                notes.save(sid, command)
            assert runtime.activities.draft(sid, capture["capture_id"])["status"] == "awaiting_confirmation"
            assert conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 0
            conn.execute("DROP TRIGGER reject_note")
            assert notes.save(sid, command)["text"] == command["text"]
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            conn.close()

    asyncio.run(scenario())


def test_study_notes_and_voice_preferences_roundtrip_through_sealed_profile_import(tmp_path):
    from test_m10d_deletion_export import PASSPHRASE, _export, _learner_with_history, _with_exports

    async def scenario(api, running):
        token, profile, _ = await _learner_with_history(api, running)
        token = (await api.unlock(profile)).json()["profile_token"]
        settings = await api.call(
            "PATCH",
            f"/v1/profiles/{profile}/settings",
            {"speech_rate": 1.25, "speech_voice": "installed-test-voice", "read_aloud": True},
            profile=token,
        )
        assert settings.status_code == 200, settings.text
        identity = new_id("nt")
        with running.runtime.directory.open_learner(profile) as conn:
            conn.execute(
                "INSERT INTO study_notes (note_id, text, source, created_at, updated_at) VALUES "
                "(?, 'Synthetic revision note', 'voice', 10, 10)",
                (identity,),
            )
        _, archive = await _export(
            api,
            token,
            tmp_path / "usb",
            kind="profile_archive",
            profile_ids=[profile],
            passphrase=PASSPHRASE,
        )
        imported = await api.call(
            "POST",
            "/v1/profiles/import",
            {"source": {"kind": "file", "path": str(archive)}, "passphrase": PASSPHRASE},
        )
        assert imported.status_code == 202, imported.text
        restored = (await api.call("GET", f"/v1/jobs/{imported.json()['job_id']}")).json()["result_ref"]
        assert restored != profile
        token = (await api.unlock(restored)).json()["profile_token"]
        notes = await api.call("GET", "/v1/study/notes", profile=token)
        assert notes.json()["notes"] == [
            {
                "note_id": identity,
                "text": "Synthetic revision note",
                "source": "voice",
                "created_at": 10,
                "updated_at": 10,
            }
        ]
        settings = (await api.call("GET", f"/v1/profiles/{restored}/settings", profile=token)).json()
        assert settings["speech_rate"] == 1.25 and settings["speech_voice"] == "installed-test-voice"
        assert settings["read_aloud"] is True

    _with_exports(tmp_path, scenario)
