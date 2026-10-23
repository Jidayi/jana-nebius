"""Read existing accepted text and dictate editable drafts through real HTTP/socket/adapter boundaries."""

import asyncio
import copy
import hashlib
import json
import sqlite3
from types import SimpleNamespace

import pytest
from agent_core.contracts import errors
from agent_core.engine.events import new_id
from agent_core.engine.state import state_to_json
from agent_core.engine.voice_dictation import spoken_maths
from test_m31_voice_bridge import audio, created, event, ready
from test_m32_adapter import body, contents, setup_adapter


def headers():
    return {"authorization": "Bearer launch-secret", "idempotency-key": new_id("cli")}


async def accepted(core, sid):
    core.start_turn(
        sid,
        {
            "client_message_id": new_id("cli"),
            "intent": "answer",
            "content": [{"type": "text", "text": "Could you explain that?"}],
        },
    )
    await core.sessions[sid].task
    entry = core.sessions[sid]
    part = next(part for part in entry.state["parts"].values() if part["kind"] == "text")
    assert part["status"] == "complete"
    return part["part_id"]


def voc18_stop_never_cancels_turn(tmp_path):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, early_response=False)
        try:
            part_id = await accepted(core, sid)
            before = state_to_json(core.sessions[sid].engine_state)
            snapshot = copy.deepcopy(core.sessions[sid].state["messages"])
            response = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_aloud", "part_id": part_id},
            )
            assert response.status_code == 200, response.text
            utterance = response.json()
            assert not errors("voice/activities", utterance)
            await socket.send({"type": "speak", "utterance_id": utterance["utterance_id"]})
            create = await asyncio.wait_for(endpoint.sent.get(), 2)
            assert create["item"]["content"][0]["text"] == "jana-speak: " + utterance["utterance_id"]
            assert (await endpoint.sent.get())["type"] == "response.create"
            answer = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(instructions, "jana-speak: " + utterance["utterance_id"]),
            )
            assert contents(answer) == utterance["text"]
            replay = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(instructions, "jana-speak: " + utterance["utterance_id"]),
            )
            assert contents(replay) == ""
            await endpoint.incoming.put(event("response.created", response={"id": "resp_read"}))
            await endpoint.incoming.put(audio("resp_read"))
            packet = await socket.receive()
            assert packet["bytes"][:16] == hashlib.sha256(utterance["utterance_id"].encode()).digest()[:16]
            await socket.send({"type": "stop"})
            assert json.loads((await socket.receive())["text"])["utterance_id"] == utterance["utterance_id"]
            assert (await endpoint.sent.get())["type"] == "response.cancel"
            assert state_to_json(core.sessions[sid].engine_state) == before
            assert core.sessions[sid].state["messages"] == snapshot and not runtime.adapter.jobs
            captions = [
                f["event"]
                for f in core._engine(core.sessions[sid]).events.frames
                if f["event"]["type"] == "voice.caption"
            ]
            assert captions[-1]["words"] and captions[-1]["item_id"] == utterance["utterance_id"]
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", ["streaming", "unknown", "foreign", "client_text"])
def test_read_aloud_never_accepts_a_candidate_or_client_prose(tmp_path, bad):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        try:
            part_id = await accepted(core, sid)
            request = {"type": "read_aloud", "part_id": part_id}
            if bad == "streaming":
                core.sessions[sid].state["messages"][-1]["status"] = "streaming"
            elif bad in ("unknown", "foreign"):
                request["part_id"] = new_id("prt")
            else:
                request["text"] = "Speak an unchecked secret"
            response = await client.post(f"/v1/sessions/{sid}/voice/utterances", headers=headers(), json=request)
            assert response.status_code in (400, 409, 422)
            assert not runtime.activities.utterances and not runtime.adapter.jobs
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_os_read_aloud_word_progress_stop_expiry_and_restart_preserve_tutor_state(tmp_path):
    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        try:
            part_id = await accepted(core, sid)
            await socket.close()  # same app without an active speech unit takes the OS path
            before = state_to_json(core.sessions[sid].engine_state)
            response = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_aloud", "part_id": part_id},
            )
            utterance = response.json()
            assert utterance["transport"] == "os"
            path = f"/v1/sessions/{sid}/voice/utterances/{utterance['utterance_id']}/playback"
            for phase, position, elapsed in (("start", 0, 0), ("progress", 5, 200), ("stop", 5, 210)):
                response = await client.post(
                    path,
                    headers=headers(),
                    json={"type": "read_aloud_playback", "phase": phase, "char_index": position, "elapsed_ms": elapsed},
                )
                assert response.status_code == 204, response.text
            replay = await client.post(
                path,
                headers=headers(),
                json={"type": "read_aloud_playback", "phase": "start", "char_index": 0, "elapsed_ms": 0},
            )
            assert replay.status_code == 409
            again = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_aloud", "part_id": part_id},
            )
            assert again.json()["utterance_id"] != utterance["utterance_id"]
            identity = again.json()["utterance_id"]
            runtime.activities.utterances[identity].value["expires_at"] = 0
            expired = await client.post(
                f"/v1/sessions/{sid}/voice/utterances/{identity}/playback",
                headers=headers(),
                json={"type": "read_aloud_playback", "phase": "start", "char_index": 0, "elapsed_ms": 0},
            )
            assert expired.status_code == 404
            assert state_to_json(core.sessions[sid].engine_state) == before
            assert all(not errors("api/events", f) for f in core._engine(core.sessions[sid]).events.frames)
        finally:
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def voc46_dictation_starts_no_turn(tmp_path):
    """A dictated utterance yields a capture awaiting confirmation and no turn, learning, audio or content."""
    _dictation_scenario(tmp_path, speak_after=False)


def voc46_binding_returns_to_tutor(tmp_path):
    """After the dictation the binding is renewed and the next spoken utterance starts a normal tutor turn."""
    _dictation_scenario(tmp_path, speak_after=True)


def _dictation_scenario(tmp_path, *, speak_after):
    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, early_response=False)
        try:
            before = state_to_json(core.sessions[sid].engine_state)
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
            )
            assert response.status_code == 200, response.text
            capture = response.json()
            assert capture["source"] == "voice" and not capture["confirmation"]["confirmed"]
            identity = capture["capture_id"]
            await socket.send({"type": "dictate", "capture_id": identity, "pressed": True})
            async with asyncio.timeout(2):
                while runtime._active.bridge.dictation_id != identity:
                    await asyncio.sleep(0.001)
            request = body(instructions, "x squared plus three x equals ten")
            answer = await client.post(
                "/v1/voice/llm/chat/completions", headers={"authorization": "Bearer adapter-secret"}, json=request
            )
            assert contents(answer) == "" and "chatcmpl-" + identity in answer.text
            await endpoint.incoming.put(
                event("input_audio_buffer.speech_started", item_id="dict_item", audio_start_ms=0)
            )
            await socket.send({"type": "dictate", "capture_id": identity, "pressed": False})
            await endpoint.incoming.put(
                event(
                    "conversation.item.input_audio_transcription.delta",
                    item_id="dict_item",
                    content_index=0,
                    delta="x squared",
                )
            )
            await endpoint.incoming.put(
                event(
                    "conversation.item.input_audio_transcription.completed",
                    item_id="dict_item",
                    content_index=0,
                    transcript="x squared plus three x equals ten",
                    usage={},
                )
            )
            await endpoint.incoming.put(audio())  # malicious/unexpected endpoint audio is never forwarded
            await endpoint.incoming.put(event("response.done", response={"id": "dict_resp", "status": "completed"}))
            async with asyncio.timeout(2):
                while runtime._active.bridge.dictation_id is not None:
                    await asyncio.sleep(0.001)
            result = await client.get(f"/v1/sessions/{sid}/voice/dictations/{identity}", headers=headers())
            assert result.json()["status"] == "awaiting_confirmation"
            assert result.json()["text"] == r"\(x^2+3x=10\)"
            assert not errors("input/captured-question", result.json())
            assert not socket.outgoing.qsize() and not runtime.adapter.jobs and not core.voice_engines
            assert state_to_json(core.sessions[sid].engine_state) == before
            assert not core.sessions[sid].state["messages"]
            # M21's capture repository receives no draft until the student explicitly confirms an edited message.
            with sqlite3.connect(":memory:") as conn:
                conn.execute(
                    "CREATE TABLE captures (capture_id TEXT, session_id TEXT, record TEXT, expires_at INTEGER)"
                )
                core.capture_desk = SimpleNamespace(conn=lambda: conn)
                confirmed = await client.post(
                    f"/v1/sessions/{sid}/voice/dictations/{identity}/confirm",
                    headers=headers(),
                    json={"type": "confirm_dictation", "text": r"\(x^2+3x=11\)"},
                )
                assert confirmed.status_code == 200, confirmed.text
                assert confirmed.json()["confirmation"]["confirmed"]
                assert confirmed.json()["confirmation"]["edit_distance"] == 1
                assert json.loads(conn.execute("SELECT record FROM captures").fetchone()[0])["text"] == r"\(x^2+3x=11\)"
                assert not runtime.adapter.jobs and not core.sessions[sid].state["messages"]
            late = await client.post(
                "/v1/voice/llm/chat/completions", headers={"authorization": "Bearer adapter-secret"}, json=request
            )
            assert contents(late) == ""
            assert runtime._active.bridge.binding.instructions != instructions
            if not speak_after:
                return
            # Subsequent speech with the renewed binding starts the normal guarded tutor pipeline.
            await socket.send({"type": "ptt", "pressed": True})
            await asyncio.sleep(0.01)
            reply = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(runtime._active.bridge.binding.instructions),
            )
            assert contents(reply) and runtime.adapter.jobs
            job = next(iter(runtime.adapter.jobs.values()))
            assert job.binding is runtime._active.bridge.binding and job.entry.session_id == sid
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize("stop", ["stop", "close", "profile"])
def test_dictation_cleanup_suppresses_delayed_transcripts(tmp_path, stop):
    async def scenario():
        core, sid, runtime, socket, _endpoint, client, _ = await setup_adapter(tmp_path, early_response=False)
        entry = core.sessions[sid]
        try:
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "answer"},
            )
            identity = response.json()["capture_id"]
            await socket.send({"type": "dictate", "capture_id": identity, "pressed": True})
            async with asyncio.timeout(2):
                while not runtime._active.bridge.dictation_id:
                    await asyncio.sleep(0.001)
            if stop == "profile":
                core.forget_profile(None)
                await runtime.close()
            elif stop == "close":
                await socket.close()
            else:
                await socket.send({"type": "stop"})
                await asyncio.sleep(0.03)
            value = runtime.activities.drafts.get(identity)
            assert value is None or value[1]["status"] == "cancelled"
            assert not runtime.adapter.jobs and not core.voice_engines
            assert not entry.engine_state.transcript
        finally:
            await runtime.close()
            await client.aclose()
            if not socket.task.done():
                await socket.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("age", ["under_13", "13_15", "16_17", "18_plus"])
def voc16_no_consent_step(tmp_path, age):
    async def scenario():
        core, sid, runtime, socket, _endpoint, client, _ = await setup_adapter(tmp_path, early_response=False)

        def no_consent_query(_):
            raise AssertionError("D87 permits on-device voice without querying obsolete app consent")

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
            for credential in (None, "expired"):
                response = await client.post(
                    f"/v1/sessions/{sid}/voice/dictations",
                    headers={**headers(), **({"x-profile-token": credential} if credential else {})},
                    json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
                )
                assert response.status_code == 401, response.text
                assert response.json()["error"]["code"] == "profile_token_expired"
            response = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers={**headers(), "x-profile-token": "test"},
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
            )
            assert response.status_code == 200, response.text
            assert len(runtime.activities.drafts) == 1
            assert runtime._active.bridge.dictation_id is None and not runtime.adapter.jobs
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


@pytest.mark.parametrize(
    ("speech", "expected"),
    [
        ("x squared plus three x equals ten", r"\(x^2+3x=10\)"),
        ("three quarters", r"\(\frac{3}{4}\)"),
        ("square root of x plus one, end root", r"\(\sqrt{x+1}\)"),
        ("H two S O four", r"\(\mathrm{H_{2}SO_{4}}\)"),
        ("What is x squared", r"What is \(x^2\)"),
        ("Could you explain this diagram?", "Could you explain this diagram?"),
        ("x plus mystery operator", "x plus mystery operator"),
    ],
)
def test_spoken_maths_preserves_uncertain_prose(speech, expected):
    assert spoken_maths(speech).text == expected


def test_dictation_and_read_aloud_controls_cannot_overlap():
    bridge = ready()
    bridge.start_dictation(new_id("cap"), 0)
    with pytest.raises(ValueError, match="dictation_active"):
        bridge.queue_read_aloud(new_id("utt"), new_id("trn"), "Accepted text.")


def test_stopping_a_queued_read_does_not_flush_or_cancel_the_active_tutor():
    bridge = ready()
    created(bridge)
    bridge.server(audio(), 0)
    tutor = bridge._response
    identity = new_id("utt")
    assert not bridge.queue_read_aloud(identity, new_id("trn"), "An older accepted message.").upstream
    effects = bridge.control({"type": "stop", "utterance_id": identity})
    assert not effects.ui and not effects.upstream
    assert effects.actions == [{"type": "read_finished", "utterance_id": identity}]
    assert bridge._response is tutor and tutor.released and bridge._queued_read is None


@pytest.mark.parametrize("overlap", [False, True])
def test_dictation_waits_for_key_release_and_preserves_paused_segments(overlap):
    bridge = ready()
    identity = new_id("cap")
    effects = bridge.start_dictation(identity, 0)
    assert effects.upstream[0]["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 10000
    if overlap:
        for index in range(2):
            bridge.server(event("input_audio_buffer.speech_started", item_id=f"segment_{index}", audio_start_ms=0), 0)
    for index, text in enumerate(("First sentence.", "Second sentence.")):
        item = f"segment_{index}"
        if not overlap:
            bridge.server(event("input_audio_buffer.speech_started", item_id=item, audio_start_ms=0), 0)
        completed = bridge.server(
            event(
                "conversation.item.input_audio_transcription.completed",
                item_id=item,
                content_index=0,
                transcript=text,
                usage={},
            ),
            0,
        )
        done = bridge.server(event("response.done", response={"id": f"response_{index}", "status": "completed"}), 0)
        assert not completed.actions and not done.actions
        assert bridge.dictation_id == identity
    released = bridge.control({"type": "dictate", "capture_id": identity, "pressed": False})
    assert released.upstream[0]["session"]["audio"]["input"]["turn_detection"]["silence_duration_ms"] == 160
    assert released.actions == [
        {"type": "dictation_transcript", "capture_id": identity, "text": "First sentence. Second sentence."},
        {"type": "dictation_finished", "capture_id": identity, "cancelled": False},
    ]
