"""Actual pinned upstream ASGI router/service/resampler, with synthetic worker events and no speech models.

Optional core test: requires JANA_SPEECH_SOURCE plus that checkout's SDK/NumPy/SciPy protocol dependencies.
This is wire compatibility evidence, not STT/TTS accuracy, model startup or device acceptance.
"""

import asyncio
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from queue import Empty, Queue
from threading import Event

import httpx
import pytest
from agent_core.engine.voice_bindings import VoiceBindings
from agent_core.engine.voice_bridge import VoiceBridge
from agent_core.net.voice_sidecar import RealtimeGuard
from agent_core.store.speech_packs import UPSTREAM_COMMIT

if "JANA_SPEECH_SOURCE" not in os.environ or importlib.util.find_spec("openai") is None:
    pytest.skip("provide pinned upstream checkout and its protocol-only dependencies", allow_module_level=True)

TOKEN = "synthetic_" + "a" * 32
TURN = "trn_" + "0" * 26


class Socket:
    def __init__(self, app, token=TOKEN):
        self.input, self.output = asyncio.Queue(), asyncio.Queue()
        scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "scheme": "ws",
            "path": "/v1/realtime",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"authorization", ("Bearer " + token).encode())] if token else [],
            "subprotocols": [],
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 2345),
        }
        self.input.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(scope, self.input.get, self.output.put))

    async def packet(self):
        return await asyncio.wait_for(self.output.get(), 3)

    async def receive(self):
        packet = await self.packet()
        assert packet["type"] == "websocket.send", packet
        return json.loads(packet["text"])

    async def send(self, frame):
        await self.input.put({"type": "websocket.receive", "text": json.dumps(frame)})

    async def close(self):
        await self.input.put({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(self.task, 3)


def upstream():
    root = Path(os.environ["JANA_SPEECH_SOURCE"])
    found = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    assert found == UPSTREAM_COMMIT
    if str(root / "src") not in sys.path:
        sys.path.insert(0, str(root / "src"))
    from speech_to_speech.api.openai_realtime.pipeline_unit import PipelineUnit
    from speech_to_speech.api.openai_realtime.service import RealtimeService
    from speech_to_speech.api.openai_realtime.websocket_router import create_app
    from speech_to_speech.pipeline.cancel_scope import CancelScope

    stop = Event()
    text_prompt_queue = Queue(16)
    unit = PipelineUnit(
        index=0,
        service=RealtimeService(text_prompt_queue=text_prompt_queue, default_instructions="jana-voice-unbound"),
        cancel_scope=CancelScope(),
        should_listen=Event(),
        response_playing=Event(),
        input_queue=Queue(16),
        output_queue=Queue(16),
        text_output_queue=Queue(16),
        text_prompt_queue=text_prompt_queue,
        handlers=[],
    )
    app = create_app([unit], stop, llm_proxy_config=None)
    return app, RealtimeGuard(app, TOKEN), unit


def test_real_upstream_authentication_pool_limit_and_hidden_routes():
    async def scenario():
        app, guarded, unit = upstream()
        async with app.router.lifespan_context(app):
            denied = Socket(guarded, token=None)
            assert (await denied.packet())["code"] == 4401
            await denied.close()
            assert unit.session is None and unit.service.total_usage.connections == 0
            first = Socket(guarded)
            assert (await first.packet())["type"] == "websocket.accept"
            assert (await first.receive())["type"] == "session.created"
            second = Socket(guarded)
            assert (await second.packet())["type"] == "websocket.accept"
            assert (await second.receive())["error"]["type"] == "session_limit_reached"
            await second.close()
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=guarded), base_url="http://127.0.0.1:2345"
            ) as client:
                for path in ("/v1/usage", "/v1/pool", "/v1/realtime/calls", "/v1/chat/completions"):
                    assert (await client.get(path)).status_code == 404
            await first.close()
            unit.session.drained.set()  # synthetic workers acknowledge their reset
            async with asyncio.timeout(2):
                while unit.session is not None:
                    await asyncio.sleep(0.01)

    asyncio.run(scenario())


def voc45_transcript_after_first_frame():
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

        captured = []

        async def synthetic_worker():
            while True:
                try:
                    item = unit.input_queue.get_nowait()
                    if is_control_message(item, SESSION_END.kind):
                        unit.output_queue.put(item)
                    else:
                        captured.append(item)
                except Empty:
                    pass
                await asyncio.sleep(0.002)

        pump = asyncio.create_task(synthetic_worker())
        async with app.router.lifespan_context(app):
            socket = Socket(guarded)
            bridge = VoiceBridge(VoiceBindings("epoch").mint("ses_" + "0" * 26, None))
            try:
                assert (await socket.packet())["type"] == "websocket.accept"
                config = bridge.server(await socket.receive(), 0).upstream[0]
                await socket.send(config)
                updated = await socket.receive()
                assert updated["type"] == "session.updated", updated
                assert updated["session"]["instructions"] == bridge.binding.instructions
                bridge.server(updated, 0)
                bridge.control({"type": "ptt", "pressed": True})
                for frame in bridge.microphone(b"\x01\x00" * 2400).upstream:
                    await socket.send(frame)
                async with asyncio.timeout(2):
                    while not captured:
                        await asyncio.sleep(0.01)
                unit.text_output_queue.put(SpeechStartedEvent(turn_id="synthetic", turn_revision=1))
                async with asyncio.timeout(3):
                    while True:
                        frame = await socket.receive()
                        bridge.server(frame, 50)
                        if frame["type"] == "input_audio_buffer.speech_started":
                            break
                unit.text_output_queue.put(SpeechStoppedEvent(turn_id="synthetic", turn_revision=1, duration_s=0.1))
                unit.text_output_queue.put(
                    TranscriptionCompletedEvent(
                        transcript="Please explain that.", language_code="en", turn_id="synthetic", turn_revision=1
                    )
                )
                async with asyncio.timeout(3):
                    while unit.text_prompt_queue.empty():
                        await asyncio.sleep(0.01)
                request = unit.text_prompt_queue.get_nowait()
                # The upstream calls its LLM before exposing response.created. Authorize without waiting for it.
                assert bridge.begin_provisional(TURN)
                bridge.authorise_turn(TURN, "Try again.")
                unit.output_queue.put(
                    AssistantOutputEvent(
                        text="Try again.", turn_id="synthetic", turn_revision=1, response_key=request.response_key
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
                    AssistantResponseDoneEvent(turn_id="synthetic", turn_revision=1, response_key=request.response_key)
                )
                unit.output_queue.put(
                    AudioOutput(
                        audio=AUDIO_RESPONSE_DONE,
                        cancel_generation=unit.cancel_scope.generation,
                        response_key=request.response_key,
                    )
                )
                effects = []
                received_types = []
                async with asyncio.timeout(3):
                    while True:
                        frame = await socket.receive()
                        received_types.append(frame["type"])
                        effects.append(bridge.server(frame, 200))
                        if frame["type"] == "response.done":
                            break
                audio = [item for effect in effects for item in effect.ui if isinstance(item, bytes)]
                first_audio = received_types.index("response.output_audio.delta")
                assert received_types[first_audio + 1] == "response.output_audio_transcript.delta", received_types
                assert audio and len(audio[0]) > 16
                assert [action["type"] for effect in effects for action in effect.actions] == ["release"]
                response = bridge._response
                completed = bridge.control(
                    {
                        "type": "playback",
                        "response_id": response.response_id,
                        "played_ms": response.pcm_bytes // 48,
                        "ended": True,
                    }
                )
                assert completed.actions[0]["type"] == "complete"
            finally:
                await socket.close()
                async with asyncio.timeout(2):
                    while unit.session is not None:
                        await asyncio.sleep(0.01)
                pump.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pump
        assert not unit.service._conns

    asyncio.run(scenario())


def test_microphone_to_real_tutor_adapter_to_upstream_audio_and_delivery(tmp_path):
    """Actual router + core socket + gated engine + adapter HTTP + playback, with deterministic STT/TTS workers."""
    from test_m31_voice_socket import Endpoint
    from test_m32_adapter import contents, setup_adapter
    from test_m32_provisional import SAFE

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
            core, sid, runtime, socket, _, client, _ = await setup_adapter(
                tmp_path, early_response=False, connect_factory=connect
            )
            microphone_seen = False
            answered = False

            async def workers():
                nonlocal microphone_seen, answered
                while True:
                    try:
                        item = unit.input_queue.get_nowait()
                        if is_control_message(item, SESSION_END.kind):
                            unit.output_queue.put(item)
                        elif not microphone_seen:
                            microphone_seen = True
                            unit.text_output_queue.put(SpeechStartedEvent(turn_id="synthetic", turn_revision=1))
                            await asyncio.sleep(0.03)
                            unit.text_output_queue.put(
                                SpeechStoppedEvent(turn_id="synthetic", turn_revision=1, duration_s=0.1)
                            )
                            unit.text_output_queue.put(
                                TranscriptionCompletedEvent(
                                    transcript="Could you explain that?",
                                    language_code="en",
                                    turn_id="synthetic",
                                    turn_revision=1,
                                )
                            )
                    except Empty:
                        pass
                    if not unit.text_prompt_queue.empty() and not answered:
                        answered = True
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
                        assert response.status_code == 200 and speech == SAFE
                        assert not core.sessions[sid].engine_state.transcript  # no audio, no commit yet
                        unit.output_queue.put(
                            AssistantOutputEvent(
                                text=speech, turn_id="synthetic", turn_revision=1, response_key=request.response_key
                            )
                        )
                        for audio in (b"\x00\x00" * 1600, AUDIO_RESPONSE_DONE):
                            if audio == AUDIO_RESPONSE_DONE:
                                unit.output_queue.put(
                                    AssistantResponseDoneEvent(
                                        turn_id="synthetic", turn_revision=1, response_key=request.response_key
                                    )
                                )
                            unit.output_queue.put(
                                AudioOutput(
                                    audio=audio,
                                    response_key=request.response_key,
                                    cancel_generation=unit.cancel_scope.generation,
                                )
                            )
                    await asyncio.sleep(0.002)

            pump = asyncio.create_task(workers())
            try:
                await socket.send({"type": "ptt", "pressed": True})
                await socket.incoming.put({"type": "websocket.receive", "bytes": b"\x01\x00" * 2400})
                packet = await socket.receive()
                assert microphone_seen and answered and "bytes" in packet
                assert core.sessions[sid].engine_state.transcript[-1]["content"] == SAFE
                audio_frames = [packet["bytes"]]
                async with asyncio.timeout(3):
                    while True:
                        while not socket.outgoing.empty():
                            frame = await socket.receive()
                            assert "bytes" in frame
                            audio_frames.append(frame["bytes"])
                        response = runtime._active.bridge._response
                        if (
                            response is not None
                            and response.done
                            and sum(len(frame) - 16 for frame in audio_frames) == response.pcm_bytes
                        ):
                            break
                        if pump.done():
                            pump.result()
                        await asyncio.sleep(0.01)
                # The real output resampler can emit a final short tail frame; playback must include it too.
                assert all(frame[:16] == audio_frames[0][:16] for frame in audio_frames)
                await socket.send(
                    {
                        "type": "playback",
                        "response_id": audio_frames[0][:16].hex(),
                        "played_ms": sum(len(frame) - 16 for frame in audio_frames) // 48,
                        "ended": True,
                    }
                )
                async with asyncio.timeout(3):
                    while runtime.adapter.jobs:
                        if pump.done():
                            pump.result()
                        await asyncio.sleep(0.01)
                transcript = core.store.load(sid)["engine"]["transcript"]
                assert transcript[-1]["heard_text"] == transcript[-1]["spoken_text"] == SAFE
                assert not core.voice_engines
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
