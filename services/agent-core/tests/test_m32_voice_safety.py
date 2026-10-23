"""Voice safety through the real adapter, socket and engine (VOC-20, PRV-14): distress is handled as typed."""

import asyncio

import pytest
from agent_core.engine.records import SessionRecords
from agent_core.store.transcript import TranscriptStore
from learner_harness import learner_db
from test_m31_voice_bridge import audio, event
from test_m32_adapter import body, contents, setup_adapter

DISTRESS = "I want to hurt myself, I can't do this anymore"


@pytest.mark.parametrize("ending", ["voice_off", "expiry", "profile_close", "spoken"])
def test_distress_voice_turn_keeps_flag_and_calm_screen_then_rests_idle(tmp_path, ending):
    """Whatever ends the voice turn, the safety flag and the calm screen land; voice then rests idle."""

    async def scenario():
        core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        store = TranscriptStore(learner_db())
        records = SessionRecords(store)
        core.records = records
        records.session_started(core.sessions[sid].meta)
        flagged = []
        original = records.learning

        def learning(events):
            flagged.extend(e for e in events if e.type == "safety_flagged")
            original(events)

        records.learning = learning
        try:
            response = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(instructions, DISTRESS),
            )
            spoken = contents(response)
            assert "adult you trust" in spoken  # the keyed template only, no model text
            job = next(iter(runtime.adapter.jobs.values()))
            if ending == "voice_off":
                await socket.close()
            elif ending == "expiry":
                runtime.adapter.unreleased_s = 0.01
                job.expiry.cancel()
                job.expiry = asyncio.create_task(runtime.adapter._expire(job))
            elif ending == "profile_close":
                runtime.adapter._close_profile(job.binding.profile_id)
                assert [e.payload["category"] for e in flagged] == ["distress"]  # before the database closes
            else:
                await endpoint.incoming.put(audio())
                assert "bytes" in await socket.receive()
                await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
                await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            async with asyncio.timeout(3):
                while not job.turn.finished and ending != "profile_close":
                    await asyncio.sleep(0.01)
            assert [e.payload["category"] for e in flagged] == ["distress"]
            frames = core._engine(core.sessions[sid]).events.frames
            assert [f["event"]["code"] for f in frames if f["event"]["type"] == "notice"] == ["calm_screen"]
            if ending == "profile_close":
                return
            assert sid in runtime.calm_sessions
            if ending == "spoken":
                bridge = runtime._active.bridge
                async with asyncio.timeout(2):
                    while bridge.state != "idle":
                        await asyncio.sleep(0.01)
                await socket.send({"type": "ptt", "pressed": True})
                await socket.incoming.put({"type": "websocket.receive", "bytes": bytes(960)})
                await asyncio.sleep(0.05)
                assert bridge.state == "idle" and not bridge.pressed
                while not endpoint.sent.empty():
                    assert endpoint.sent.get_nowait()["type"] != "input_audio_buffer.append"
                await socket.send({"type": "mode", "mode": "push_to_talk"})  # "Back to my lesson when I'm ready"
                async with asyncio.timeout(2):
                    while sid in runtime.calm_sessions:
                        await asyncio.sleep(0.01)
                assert not bridge.calm
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
            store.conn.close()

    asyncio.run(scenario())


def test_voice_utterance_during_a_typed_turn_is_redacted_before_it_becomes_steering(tmp_path):
    """VOC-32 queues the utterance as steering; PRV-03 redaction runs first, as for a voice turn's own text."""
    from engine_harness import tutor
    from test_m32_provisional import SAFE

    private = "my email is kid.student@example.com and my phone is 0803 555 1234"

    async def scenario():
        core, sid, runtime, socket, _, client, instructions = await setup_adapter(
            tmp_path, replies=[{"stall_s": 1.0, **tutor(SAFE)}, tutor(SAFE), tutor(SAFE)]
        )
        try:
            core.start_turn(sid, {"client_message_id": "cli_01JZ0000000000000000000002", "intent": "answer",
                                  "content": [{"type": "text", "text": "I think the answer is 12"}]})  # fmt: skip
            await asyncio.sleep(0.05)
            entry = core.sessions[sid]
            assert entry.task is not None and not entry.task.done()
            response = await client.post("/v1/voice/llm/chat/completions",
                                         headers={"authorization": "Bearer adapter-secret"},
                                         json=body(instructions, private))  # fmt: skip
            assert response.status_code == 200 and contents(response) == ""
            queued = [message.text for message in core._engine(entry).steering.queued]
            assert queued and not any("kid.student@example.com" in t or "555 1234" in t for t in queued)
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def test_calm_hold_survives_voice_off_and_on_and_clears_on_profile_lock(tmp_path):
    async def scenario():
        _, sid, runtime, socket, _, client, instructions = await setup_adapter(tmp_path)
        try:
            response = await client.post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json=body(instructions, DISTRESS),
            )
            assert "adult you trust" in contents(response)
            await socket.close()
            async with asyncio.timeout(2):
                while runtime.adapter.jobs:
                    await asyncio.sleep(0.01)
            assert runtime.calm_sessions == {sid: None}
            runtime._forget_profile(None)
            assert not runtime.calm_sessions
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())
