"""Exercise both activities against the pinned speech router; speech workers remain deterministic substitutes."""

import asyncio
import contextlib
from queue import Empty

import pytest
from agent_core.engine.events import new_id
from agent_core.engine.state import state_to_json
from test_m31_voice_activities import accepted, headers
from test_m31_voice_socket import Endpoint
from test_m32_adapter import contents, setup_adapter
from test_m32_upstream_protocol import Socket, upstream


@pytest.mark.parametrize("activity", ["read_aloud", "dictation"])
def test_activities_through_actual_upstream_router(tmp_path, activity):
    async def scenario():
        app, guarded, unit = upstream()
        from speech_to_speech.pipeline.control import SESSION_END, is_control_message
        from speech_to_speech.pipeline.events import (
            AssistantOutputEvent,
            AssistantResponseDoneEvent,
            SpeechStartedEvent,
            SpeechStoppedEvent,
            TranscriptionCompletedEvent,
        )
        from speech_to_speech.pipeline.messages import AUDIO_RESPONSE_DONE, AudioOutput

        class EndpointWire(Endpoint):
            def __init__(self, wire):
                super().__init__()
                self.wire = wire

            async def send(self, frame):
                await super().send(frame)
                await self.wire.send(frame)

            async def receive(self):
                return await self.wire.receive()

            async def close(self):
                self.closed = True
                await self.wire.close()

        async def connect():
            wire = Socket(guarded)
            assert (await wire.packet())["type"] == "websocket.accept"
            return EndpointWire(wire)

        async with app.router.lifespan_context(app):
            core, sid, runtime, socket, endpoint, client, _ = await setup_adapter(
                tmp_path, early_response=False, connect_factory=connect
            )
            before = None
            generated = []
            microphone_seen = False

            async def workers():
                nonlocal microphone_seen
                while True:
                    try:
                        item = unit.input_queue.get_nowait()
                        if is_control_message(item, SESSION_END.kind):
                            unit.output_queue.put(item)
                        elif activity == "dictation" and not microphone_seen:
                            microphone_seen = True
                            unit.text_output_queue.put(SpeechStartedEvent(turn_id="synthetic", turn_revision=1))
                            await asyncio.sleep(0.03)
                            unit.text_output_queue.put(
                                SpeechStoppedEvent(turn_id="synthetic", turn_revision=1, duration_s=0.1)
                            )
                            unit.text_output_queue.put(
                                TranscriptionCompletedEvent(
                                    transcript="three quarters",
                                    language_code="en",
                                    turn_id="synthetic",
                                    turn_revision=1,
                                )
                            )
                    except Empty:
                        pass
                    if not unit.text_prompt_queue.empty():
                        request = unit.text_prompt_queue.get_nowait()
                        response = await client.post(
                            "/v1/voice/llm/chat/completions",
                            headers={"authorization": "Bearer adapter-secret"},
                            json={
                                "model": "jana-tutor-voice",
                                "stream": True,
                                "reasoning_effort": "none",
                                "messages": [
                                    {"role": "system", "content": request.runtime_config.session.instructions},
                                    *request.runtime_config.chat.to_transformers_chat(),
                                ],
                            },
                        )
                        speech = contents(response)
                        generated.append(speech)
                        if speech:
                            unit.output_queue.put(
                                AssistantOutputEvent(
                                    text=speech, turn_id="synthetic", turn_revision=1, response_key=request.response_key
                                )
                            )
                            unit.output_queue.put(
                                AudioOutput(
                                    audio=b"\x00\x00" * 1600,
                                    cancel_generation=unit.cancel_scope.generation,
                                    response_key=request.response_key,
                                )
                            )
                        unit.output_queue.put(
                            AssistantResponseDoneEvent(
                                turn_id="synthetic", turn_revision=1, response_key=request.response_key
                            )
                        )
                        unit.output_queue.put(
                            AudioOutput(
                                audio=AUDIO_RESPONSE_DONE,
                                cancel_generation=unit.cancel_scope.generation,
                                response_key=request.response_key,
                            )
                        )
                    await asyncio.sleep(0.002)

            pump = asyncio.create_task(workers())
            try:
                if activity == "read_aloud":
                    part = await accepted(core, sid)
                    before = state_to_json(core.sessions[sid].engine_state)
                    minted = await client.post(
                        f"/v1/sessions/{sid}/voice/utterances",
                        headers=headers(),
                        json={"type": "read_aloud", "part_id": part},
                    )
                    utterance = minted.json()
                    await socket.send({"type": "speak", "utterance_id": utterance["utterance_id"]})
                    frames = []
                    async with asyncio.timeout(3):
                        while True:
                            while not socket.outgoing.empty():
                                packet = await socket.receive()
                                assert "bytes" in packet, packet
                                frames.append(packet["bytes"])
                            response = runtime._active.bridge._response
                            if (
                                response
                                and response.done
                                and frames
                                and sum(len(frame) - 16 for frame in frames) == response.pcm_bytes
                            ):
                                break
                            if pump.done():
                                pump.result()
                            await asyncio.sleep(0.01)
                    assert generated == [utterance["text"]]
                    await socket.send(
                        {
                            "type": "playback",
                            "utterance_id": utterance["utterance_id"],
                            "played_ms": sum(len(frame) - 16 for frame in frames) // 48,
                            "ended": True,
                        }
                    )
                    async with asyncio.timeout(2):
                        while runtime._active.bridge._response is not None:
                            await asyncio.sleep(0.01)
                else:
                    before = state_to_json(core.sessions[sid].engine_state)
                    created = await client.post(
                        f"/v1/sessions/{sid}/voice/dictations",
                        headers=headers(),
                        json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
                    )
                    identity = created.json()["capture_id"]
                    await socket.send({"type": "dictate", "capture_id": identity, "pressed": True})
                    await socket.incoming.put({"type": "websocket.receive", "bytes": b"\x01\x00" * 2400})
                    async with asyncio.timeout(3):
                        while (
                            not generated
                            or not runtime._active.bridge._dictation_final
                            or not runtime._active.bridge._dictation_done
                        ):
                            if pump.done():
                                pump.result()
                            await asyncio.sleep(0.01)
                    assert runtime.activities.drafts[identity][1]["status"] == "drafting"
                    await socket.send({"type": "dictate", "capture_id": identity, "pressed": False})
                    async with asyncio.timeout(3):
                        while not generated or runtime._active.bridge.dictation_id is not None:
                            if pump.done():
                                pump.result()
                            await asyncio.sleep(0.01)
                    assert generated == [""] and socket.outgoing.empty()
                    assert runtime.activities.drafts[identity][1]["text"] == r"\(3/4\)"
                    assert runtime.activities.drafts[identity][1]["status"] == "awaiting_confirmation"
                    configurations = []
                    while not endpoint.sent.empty():
                        frame = endpoint.sent.get_nowait()
                        if frame["type"] == "session.update":
                            configurations.append(frame["session"]["instructions"])
                    assert configurations[-1] == runtime._active.bridge.binding.instructions
                assert state_to_json(core.sessions[sid].engine_state) == before
                assert not runtime.adapter.jobs and not core.voice_engines
            finally:
                await socket.close()
                await runtime.close()
                await client.aclose()
                async with asyncio.timeout(2):
                    while unit.session is not None:
                        await asyncio.sleep(0.01)
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump

    asyncio.run(scenario())
