"""STU-15 dictated voice notes, core side (G116): audio discarded and the note stored, the dictation states with no
consent step, and own voice only. Speech is synthetic: PCM filler bytes and a scripted transcription event."""

import asyncio
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from agent_core.engine.events import new_id
from agent_core.store.checkpoints import CheckpointStore
from jana_tools import REPO_ROOT
from learner_harness import learner_db
from test_m31_voice_activities import headers
from test_m31_voice_bridge import event
from test_m32_adapter import setup_adapter
from test_m32_voice_named import _audio_files

PCM = b"\x01\x02" * 2400  # one synthetic 100 ms frame; its pattern is searched for on disk afterwards
SPOKEN = "Revise the speed formula, then units"
GALLERY = REPO_ROOT / "packages" / "ui" / "gallery" / "states"


async def _dictate_note(core: Any, sid: str, runtime: Any, socket: Any, endpoint: Any, client: Any,
                        profile: dict[str, str] | None = None) -> str:  # fmt: skip
    """Dictate one note through the session's voice socket: microphone frames reach the sidecar, the transcription
    comes back, and the draft waits for the learner. Returns the draft's capture id."""
    response = await client.post(
        f"/v1/sessions/{sid}/voice/dictations",
        headers={**headers(), **(profile or {})},
        json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question",
              "destination": "note"},
    )  # fmt: skip
    assert response.status_code == 200, response.text
    identity = response.json()["capture_id"]
    await socket.send({"type": "dictate", "capture_id": identity, "pressed": True})
    async with asyncio.timeout(2):
        while runtime._active.bridge.dictation_id != identity:
            await asyncio.sleep(0.001)
    await endpoint.incoming.put(event("input_audio_buffer.speech_started", item_id="note_item", audio_start_ms=0))
    for _ in range(3):
        await socket.incoming.put({"type": "websocket.receive", "bytes": PCM})
    async with asyncio.timeout(2):
        appended = 0
        while appended < 3:
            appended += (await endpoint.sent.get())["type"] == "input_audio_buffer.append"
    await socket.send({"type": "dictate", "capture_id": identity, "pressed": False})
    await endpoint.incoming.put(
        event("conversation.item.input_audio_transcription.completed", item_id="note_item", content_index=0,
              transcript=SPOKEN, usage={})
    )  # fmt: skip
    await endpoint.incoming.put(event("response.done", response={"id": "note_resp", "status": "completed"}))
    async with asyncio.timeout(2):
        while runtime._active.bridge.dictation_id is not None:
            await asyncio.sleep(0.001)
    return str(identity)


def stu15_audio_discarded_note_stored(tmp_path: Path) -> None:
    """After dictating and saving a note, a scan of the data folder finds no audio, and the note's text is in the
    learner store, found by search and readable aloud."""

    async def scenario() -> None:
        core, sid, runtime, socket, endpoint, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn = learner_db(str(tmp_path / "learner.db"))
        core.store = CheckpointStore(conn)
        try:
            identity = await _dictate_note(core, sid, runtime, socket, endpoint, client)
            draft = await client.get(f"/v1/sessions/{sid}/voice/dictations/{identity}", headers=headers())
            assert draft.json()["status"] == "awaiting_confirmation" and draft.json()["text"] == SPOKEN
            saved = await client.post(
                f"/v1/sessions/{sid}/study/notes",
                headers=headers(),
                json={"type": "save_note", "text": SPOKEN, "capture_id": identity},
            )
            assert saved.status_code == 200, saved.text
            note = saved.json()
            assert note["source"] == "voice"
            rows = conn.execute("SELECT text FROM study_notes").fetchall()
            assert [r[0] for r in rows] == [SPOKEN]
            found = await client.get("/v1/study/notes?q=units", headers=headers())
            assert [n["note_id"] for n in found.json()["notes"]] == [note["note_id"]]
            read = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_content", "source": {"kind": "note", "note_id": note["note_id"]}},
            )
            assert read.status_code == 200 and read.json()["text"] == SPOKEN and read.json()["turn_id"] is None
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            conn.close()

    asyncio.run(scenario())
    assert _audio_files(tmp_path) == []
    assert not any(PCM[:128] in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


@pytest.mark.parametrize("age", ["under_13", "13_15", "16_17", "18_plus"])
def stu15_dictation_states(tmp_path: Path, age: str) -> None:
    """ "Dictate a note" asks for no app consent on any profile (only the operating system's microphone permission,
    D87), and the voice states walk idle, listening, thinking and back to idle. Each state also needs its gallery
    state in the client (UXS-52); until the client adds them this test stops there with that reason."""

    async def consent() -> None:
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path / "consent", early_response=False)

        def no_consent_query(_: Any) -> Any:
            raise AssertionError("D87: dictating a note never queries an app consent")

        core.directory = SimpleNamespace(
            exists=lambda: True,
            profile_of=lambda credential: "profile" if credential == "test" else None,
            age_band=lambda _: age,
            open_learner=no_consent_query,
            tokens=SimpleNamespace(lapsed_profiles=lambda: []),
        )
        core.sessions[sid].profile_id = "profile"
        runtime._active.bridge.binding = runtime.bindings.mint(sid, "profile")
        socket.scope["subprotocols"].append("jana.profile.test")
        try:
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers={**headers(), "x-profile-token": "test"},
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question",
                      "destination": "note"},
            )  # fmt: skip
            assert response.status_code == 200, response.text
            assert response.json()["status"] == "drafting"
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    async def scenario() -> list[str]:
        core, sid, runtime, socket, endpoint, client, _ = await setup_adapter(tmp_path / "states", early_response=False)
        engine = core._engine(core.sessions[sid])
        start = len(engine.events.frames)
        try:
            await _dictate_note(core, sid, runtime, socket, endpoint, client)
            frames = engine.events.frames[start:]
            return [f["event"]["state"] for f in frames if f["event"]["type"] == "voice.state"]
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(consent())
    states = asyncio.run(scenario())
    walked = [s for i, s in enumerate(states) if i == 0 or s != states[i - 1]]
    assert walked[-1] == "idle" and "unavailable" not in walked, walked
    order = [walked.index(s) for s in ("listening", "thinking")]
    assert order == sorted(order), walked
    missing = [s for s in ("idle", "listening", "thinking") if not list(GALLERY.glob(f"*dictat*.{s}*.json"))]
    if missing:
        pytest.skip(f"client: no gallery state for the Dictate a note control in {missing} (UXS-52, UXS-34); "
                    "the core walks the states above")  # fmt: skip


def stu15_own_voice_only(tmp_path: Path) -> None:
    """The dictation flow offers no recording: the note and dictation endpoints take no audio file or audio field,
    nothing in the client records audio or picks an audio file for a note, and the notes screen shows the own-voice
    line."""

    async def scenario() -> None:
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        conn = learner_db(str(tmp_path / "learner.db"))
        core.store = CheckpointStore(conn)
        clip = "UklGRiQAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQAAAAA="  # a header-only synthetic WAV
        try:
            refused = [
                await client.post(f"/v1/sessions/{sid}/study/notes", headers=headers(),
                                  json={"type": "save_note", "text": "A class recording", "audio": clip}),
                await client.post(f"/v1/sessions/{sid}/study/notes", headers=headers(),
                                  files={"file": ("lesson.wav", b"RIFF" + bytes(40), "audio/wav")}),
                await client.post(f"/v1/sessions/{sid}/voice/dictations", headers=headers(),
                                  json={"type": "create_dictation", "client_capture_id": new_id("cli"),
                                        "purpose": "question", "destination": "note", "audio": clip}),
                await client.post(f"/v1/sessions/{sid}/voice/dictations", headers=headers(),
                                  files={"file": ("teacher.mp3", b"ID3" + bytes(40), "audio/mpeg")}),
            ]  # fmt: skip
            assert all(400 <= r.status_code < 500 for r in refused), [r.status_code for r in refused]
            assert conn.execute("SELECT count(*) FROM study_notes").fetchone()[0] == 0
            assert not runtime.activities.drafts
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            conn.close()

    asyncio.run(scenario())
    assert _audio_files(tmp_path) == []
    sources = [p for root in ("packages/ui/src", "apps/desktop/src", "packages/client-core/src")
               for p in (REPO_ROOT / root).rglob("*.ts*")]  # fmt: skip
    for path in sources:
        text = path.read_text()
        assert "MediaRecorder" not in text, f"{path}: records audio"
        assert not re.search(r"accept=[\"'{][^\"'}]*audio", text), f"{path}: picks an audio file"
    notes = (REPO_ROOT / "packages/ui/src/voice/StudyNotes.tsx").read_text()
    assert 't("notes.own_voice")' in notes
    copy = (REPO_ROOT / "packages/i18n/locales/en.json").read_text()
    assert re.search(r'"notes\.own_voice": "[^"]*your own voice[^"]*isn\'t a recording\.?"', copy)
