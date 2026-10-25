"""Cloud voice (VOC-28, D124) end to end: the UI's voice socket, the real bridge and tutor engine on the device, the
real cloud gateway over pinned TLS on loopback, and fakes for Google's speech services (streaming speech to text,
the Gemini Live voice and the verbatim Cloud Text-to-Speech voice).

Nothing reaches the internet: our voice host is dialled at 127.0.0.1, its certificate comes from a throwaway CA, and
the speech services are `cloud_gateway.speech_fakes`. The student's audio is a synthetic tone; the fake recognizer
"hears" a scripted sentence."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import math
import socket
import struct
from pathlib import Path
from typing import Any

import httpx
import pytest
import uvicorn
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.security import LaunchSecret
from agent_core.api.voice_adapter import attach, reply
from agent_core.config import Settings
from agent_core.net import voice_cloud
from agent_core.net.voice import VoiceTransportError
from agent_core.net.voice_cloud import CloudRealtimeConnection, CloudVoice, VoiceRoute
from agent_core.store import consents
from agent_core.store.sessions import SessionStore
from cloud_gateway import voice as gateway_voice
from cloud_gateway.app import create_app as create_gateway
from cloud_gateway.config import load_config
from cloud_gateway.custody import Secret
from cloud_gateway.speech_fakes import FakeRecognizer, fake_stack
from learner_harness import learner_db
from net_harness import HOSTS, enable, layer, make_pki
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from test_m31_voice_socket import Endpoint, Socket
from test_m32_provisional import SAFE, prepared

PROFILE = "prf_test"
HEARD = "Could you explain that?"
STATEMENT = "Find the height of a ball thrown at 14 m/s."


def tone(ms: int, loud: bool = True) -> bytes:
    if not loud:
        return b"\0\0" * (24 * ms)
    samples = [int(9000 * math.sin(2 * math.pi * 220 * n / 24000)) for n in range(24 * ms)]
    return struct.pack(f"<{len(samples)}h", *samples)


class Speech:
    """Google's speech services for one gateway: what they heard and what they were given to say."""

    def __init__(self) -> None:
        self.stack, self.recognizer, self.live, self.tts = fake_stack(recognizer=FakeRecognizer([HEARD]))

    def given(self) -> str:
        return json.dumps([self.live.sentences, self.tts.texts])


class _Secrets:
    def get(self, name: str) -> Secret | None:
        return Secret("stub-gemini-key-not-real") if name == "gemini_api_key" else None


@contextlib.asynccontextmanager
async def gateway(tmp: Path, pki: Any, speech: Speech, events: list[str]):
    """The real cloud gateway app, served over TLS on loopback for every service host."""
    signer = dev_signer(Purpose.LICENCE)
    models = {"fast-model": {"id": "gem-flash"}, "small-model": {"id": "gem-lite"}}
    config = load_config(None, environment="staging", audience_host=HOSTS["gateway"],
                         voice_audience_host=HOSTS["voice"], voice_enabled=True, storage_dir=tmp / "gateway",
                         entitlement_keys={signer.key_id: dev_trust().certificates[signer.key_id].public_key},
                         slots={"primary": "gemini"},
                         providers={"gemini": {"adapter": "gemini", "base_url": "https://gemini.stub/v1beta",
                                               "secret": "gemini_api_key", "models": models}},
                         voice_google={"live_model": "voice-test-model"},
                         prices={m: {"input": 1.0, "cached_input": 0.1, "output": 4.0}
                                 for m in [*(model["id"] for model in models.values()), "voice-test-model"]},
                         quotas={"device_burst": 1000, "licence_burst": 10000})  # fmt: skip
    app = create_gateway(config, secrets=_Secrets(),  # type: ignore[arg-type]
                         speech=speech.stack, client_factory=lambda name, spec: httpx.AsyncClient(
                             transport=httpx.MockTransport(lambda request: httpx.Response(500))))  # fmt: skip
    cert, key = tmp / "voice.pem", tmp / "voice.key"
    cert.write_bytes(pki.cert_pem + pki.ca_pem)
    key.write_bytes(pki.key_pem)
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, ssl_certfile=str(cert), ssl_keyfile=str(key), log_level="warning",
                                           lifespan="on", log_config=None))  # fmt: skip
    served = asyncio.get_running_loop().create_task(server.serve(sockets=[listener]))
    original = gateway_voice.VoiceConnection.audio

    async def audio(self: Any, encoded: Any) -> None:
        if "first_audio" not in events:
            events.append("first_audio")
        await original(self, encoded)

    gateway_voice.VoiceConnection.audio = audio  # type: ignore[method-assign]
    try:
        while not server.started:
            await asyncio.sleep(0.01)
        yield listener.getsockname()[1], app
    finally:
        gateway_voice.VoiceConnection.audio = original  # type: ignore[method-assign]
        server.should_exit = True
        await asyncio.wait_for(served, 5)


async def device(tmp: Path, port: int, pki: Any, *, switched: bool = True, notice: bool = True,
                 pins: tuple[str, ...] | None = None) -> Any:  # fmt: skip
    online = layer(tmp, settings=Settings(cloud_voice_enabled=True),
                   connect={h: ("127.0.0.1", port) for h in HOSTS.values()}, context=pki.client_context(),
                   pins={h: pins or (pki.ca_pin,) for h in HOSTS.values()})  # fmt: skip
    from net_harness import registration_entitlement

    online.credential.entitlement = registration_entitlement(online.device)
    enable(online, "cloud_voice", on=switched)  # the cloud tutor stays off: voice gets its own token (VOC-28)
    online.connectivity.state = "online"
    online.subscription = lambda: {"period_end": 4_000_000_000_000, "profiles": [PROFILE]}  # type: ignore[method-assign]
    learner = learner_db()
    consents.grant(learner, "cloud_voice", "guardian", "Parent", "v1", "dpia-test", online.clock_ms(),
                   early=("cloud_voice",))  # fmt: skip
    if notice:
        online.record_notice(PROFILE, "cloud_voice", True)
    return online, learner


async def core_with_voice(tmp: Path, online: Any, learner: Any, announced: list[str], pack: bool = False):
    live, factory = await prepared(tmp)
    core = CoreService(live.deps.settings, factory, SessionStore(tmp / "sessions"), epoch="0000000000000001")
    sid = core.create_session({"client_session_id": "cli_01JZ0000000000000000000001", "mode": "guided",
                               "subject": "physics", "level": "O", "origin": {"kind": "ask", "ref": None}}
                              )["session_id"]  # fmt: skip
    live.state.session_id = sid
    live.events.session_id = sid
    core.sessions[sid].engine_state = live.state
    local: list[Endpoint] = []

    async def connect_local() -> Endpoint:
        endpoint = Endpoint()
        local.append(endpoint)
        return endpoint

    runtime = attach(core, connect_local, secret="adapter-secret", strict=True)  # noqa: S106 -- synthetic

    def announce(session_id: str, event: dict[str, Any]) -> None:
        if event["type"] == "egress.notice":
            announced.append("notice_" + event["state"])
        core._announce(session_id, event)

    async def respond(body: Any) -> Any:
        assert runtime.adapter is not None
        return await reply(runtime.adapter, body)

    cloud = CloudVoice(online, lambda: PROFILE, lambda: learner, announce, respond)
    runtime.route = VoiceRoute(cloud, connect_local, lambda: pack)
    app = create_app(core, LaunchSecret("launch-secret"), lambda: 8765, voice=runtime)
    return core, sid, runtime, app, local, cloud


async def in_ask_chat(sock: Socket, runtime: Any) -> None:
    """D130: the conversation lives in Ask anything (VOC-53); a subject question there is a full tutor turn."""
    runtime.adapter.route = lambda _text: "tutor"
    await sock.send({"type": "place", "place": "ask"})
    await sock.send({"type": "mode", "mode": "hands_free"})


async def talk(sock: Socket, runtime: Any) -> bytes:
    """Hands-free speech, then the tutor's audio until the reply ends; playback is reported as fully heard."""
    async with asyncio.timeout(30):  # generous: the full suite runs shards in parallel
        while runtime._active is None or not runtime._active.bridge.ready:
            await asyncio.sleep(0.01)
    await in_ask_chat(sock, runtime)
    pcm = tone(500) + tone(2500, loud=False)
    for at in range(0, len(pcm), 4800):
        await sock.incoming.put({"type": "websocket.receive", "bytes": pcm[at : at + 4800]})
    heard = b""
    async with asyncio.timeout(60):
        while True:
            message = await sock.outgoing.get()
            if message.get("bytes"):
                heard += message["bytes"][16:]
                response = runtime._active.bridge._response
                if response is not None and response.done:
                    break
    response_id = runtime._active.bridge._response.response_id
    await sock.send({"type": "playback", "response_id": response_id, "played_ms": len(heard) // 48, "ended": True})
    return heard


def voc28_egress_announced(tmp_path):
    """A full voice turn over cloud voice: the student is told before any audio leaves, the device's engine writes
    the reply, Google's services only hear and speak, and the turn lands like a local one (same bridge, same events)."""

    async def scenario() -> None:
        pki = make_pki(sorted(set(HOSTS.values())))
        speech, order = Speech(), []
        async with gateway(tmp_path, pki, speech, order) as (port, _):
            online, learner = await device(tmp_path, port, pki)
            core, sid, runtime, app, local, _ = await core_with_voice(tmp_path, online, learner, order)
            sock = Socket(app, sid, profile=None)
            try:
                assert (await asyncio.wait_for(sock.outgoing.get(), 10))["type"] == "websocket.accept"
                heard = await talk(sock, runtime)
                assert heard and not local  # the sidecar was never asked
                async with asyncio.timeout(5):
                    while runtime.adapter.jobs:
                        await asyncio.sleep(0.01)
                state = core.sessions[sid].engine_state
                assert state.transcript[-1]["content"] == SAFE and state.transcript[-1]["heard_text"] == SAFE
                frames = [f["event"] for f in core._engine(core.sessions[sid]).events.frames]
                notices = [f for f in frames if f["type"] == "egress.notice"]
                assert notices[0] == {
                    "type": "egress.notice",
                    "feature": "cloud_voice",
                    "state": "started",
                    "destination_label": "Cloud voice",
                    "data_classes": ["audio", "transcript"],
                }
                captions = [f for f in frames if f["type"] == "voice.caption" and f["speaker"] == "student"]
                assert captions[-1]["committed_text"] == HEARD
            finally:
                await sock.close()
                await runtime.close()
                await online.stop()
        # VOC-28: no audio frame left before `egress.notice started`, and `ended` followed the close.
        assert order.index("notice_started") < order.index("first_audio") and order[-1] == "notice_ended"
        # The recognizer heard the student; the Live voice read the tutor's accepted words, sentence by sentence,
        # exactly, and was given nothing else: not the student's audio or words, nor anything of the lesson.
        assert " ".join(speech.live.sentences) == " ".join(SAFE.split()) and not speech.tts.texts
        assert speech.recognizer.received and HEARD not in speech.given() and STATEMENT not in speech.given()
        # The connection is in the egress ledger (ARC-10), named by its feature and payload class, never its content.
        rows = online.device.execute("SELECT feature, payload_class FROM egress_ledger").fetchall()
        assert ("cloud_voice", "voice_stream") in rows

    asyncio.run(scenario())


def test_cloud_voice_trace_path_is_cloud_voice(tmp_path):
    async def scenario() -> None:
        pki = make_pki(sorted(set(HOSTS.values())))
        async with gateway(tmp_path, pki, Speech(), []) as (port, _):
            online, learner = await device(tmp_path, port, pki)
            _, sid, runtime, app, _, _ = await core_with_voice(tmp_path, online, learner, [])
            paths: list[str] = []
            original = runtime.adapter.stream

            async def watched(request: Any) -> Any:
                async for line in original(request):
                    paths.extend(job.turn.path for job in runtime.adapter.jobs.values())
                    yield line

            runtime.adapter.stream = watched
            sock = Socket(app, sid, profile=None)
            try:
                await asyncio.wait_for(sock.outgoing.get(), 10)
                await talk(sock, runtime)
                assert paths and set(paths) == {"cloud_voice"}
            finally:
                await sock.close()
                await runtime.close()
                await online.stop()

    asyncio.run(scenario())


@pytest.mark.parametrize("why", ["switched_off", "notice_not_accepted"])
def voc28_off_means_local(tmp_path, monkeypatch, why):
    """With cloud voice off (or its notice unanswered) a voice session never dials out: the sidecar serves it."""

    async def scenario() -> None:
        dialled: list[str] = []

        async def no_dial(*_: Any, **__: Any) -> Any:
            dialled.append("dial")
            raise AssertionError("cloud voice dialled out")

        monkeypatch.setattr(voice_cloud, "connect", no_dial)
        pki = make_pki(sorted(set(HOSTS.values())))
        online, learner = await device(tmp_path, 1, pki, switched=why != "switched_off",
                                       notice=why != "notice_not_accepted")  # fmt: skip
        announced: list[str] = []
        _, sid, runtime, app, local, cloud = await core_with_voice(tmp_path, online, learner, announced)
        assert not cloud.ready()
        sock = Socket(app, sid, profile=None)
        try:
            assert (await asyncio.wait_for(sock.outgoing.get(), 5))["type"] == "websocket.accept"
            assert local and runtime._active.path == "local_sidecar"
        finally:
            await sock.close()
            await runtime.close()
        assert not dialled and not announced
        assert online.device.execute("SELECT COUNT(*) FROM egress_ledger").fetchone()[0] == 0

    asyncio.run(scenario())


def test_pin_mismatch_refuses_before_the_token_is_sent(tmp_path):
    async def scenario() -> None:
        pki = make_pki(sorted(set(HOSTS.values())))
        async with gateway(tmp_path, pki, Speech(), []) as (port, app):
            online, learner = await device(tmp_path, port, pki)
            token = await online.credential.token("cloud_voice", HOSTS["voice"])  # the right pins, for the token
            online.pins = {h: ("AAAA" + "A" * 40,) for h in HOSTS.values()}  # now the voice host's pin is wrong
            announced: list[str] = []
            cloud = CloudVoice(online, lambda: PROFILE, lambda: learner,
                               lambda _s, e: announced.append(e["state"]), reply)  # fmt: skip
            with pytest.raises(VoiceTransportError) as refused:
                await cloud.open("ses_test")
            assert str(refused.value) == "cloud_voice_refused"
            assert announced == ["started", "ended"]
            assert not app.state.voice.live and token  # the gateway never authenticated a voice connection
            assert online.client.refusals[-1]["reason"] == "pin_mismatch"
            await online.stop()

    asyncio.run(scenario())


def test_tunnel_answers_only_well_formed_requests_and_honours_cancel():
    class Wire:
        def __init__(self) -> None:
            self.inbox: asyncio.Queue[str] = asyncio.Queue()
            self.sent: list[dict[str, Any]] = []

        async def recv(self) -> str:
            return await self.inbox.get()

        async def send(self, raw: str) -> None:
            self.sent.append(json.loads(raw))

        async def close(self) -> None:
            pass

    async def scenario() -> None:
        wire, started, ended = Wire(), asyncio.Event(), []

        async def respond(body: Any) -> Any:
            async def lines() -> Any:
                yield ": keep-alive\n\n"
                yield 'data: {"choices":[{"index":0,"delta":{"content":"Hi."}}]}\n\n'
                started.set()
                await asyncio.sleep(10)
                yield "data: [DONE]\n\n"

            return 200, lines()

        connection = CloudRealtimeConnection(wire, respond, lambda: ended.append(True))  # type: ignore[arg-type]
        rid = "vlr_" + "a" * 24
        for frame in ({"type": "jana.voice_llm.request", "request_id": "bad", "body": {}},
                      {"type": "jana.voice_llm.request", "request_id": rid, "body": {}},
                      {"type": "session.created", "event_id": "evt_1", "session": {}}):  # fmt: skip
            wire.inbox.put_nowait(json.dumps(frame))
        assert (await connection.receive())["type"] == "session.created"  # tunnel frames never reach the bridge
        await asyncio.wait_for(started.wait(), 2)
        wire.inbox.put_nowait(json.dumps({"type": "jana.voice_llm.cancel", "request_id": rid}))
        wire.inbox.put_nowait(json.dumps({"type": "response.done", "event_id": "e", "response": {}}))
        assert (await connection.receive())["type"] == "response.done"
        await asyncio.sleep(0.05)
        assert [f["type"] for f in wire.sent] == ["jana.voice_llm.chunk"]  # cancelled: no done, no [DONE]
        assert json.loads(wire.sent[0]["data"])["choices"][0]["delta"]["content"] == "Hi."
        await connection.close()
        assert ended == [True]

    asyncio.run(scenario())


def test_cloud_voice_first_use_card_keeps_voice_local_until_ok(tmp_path):
    from test_m19c_cloud import events

    async def scenario() -> None:
        engine, _ = await prepared(tmp_path)
        answers: dict[str, str] = {}
        engine.voice_possible = lambda: True
        engine.voice_notice = lambda: answers.get("cloud_voice")
        engine.record_voice_notice = lambda ok: answers.__setitem__("cloud_voice", "accepted" if ok else "declined")
        await engine.student_turn(HEARD)
        cards = [e for e in events(engine) if e["type"] == "card.open" and e["card"].get("purpose") == "egress"]
        assert len(cards) == 1
        card = cards[0]["card"]
        assert card["cancel_label_key"] == "egress.first_use.keep_voice_local"
        assert "It is not stored." in card["body"]
        assert engine.answer_egress(cards[0]["request_id"], {"action": "confirm"})
        assert answers == {"cloud_voice": "accepted"}

    asyncio.run(scenario())


def test_cloud_voice_consent_scope_exists_only_with_the_capability():
    conn = learner_db()
    assert "cloud_voice" not in consents.shipped_scopes()
    with pytest.raises(consents.ConsentError):
        consents.grant(conn, "cloud_voice", "guardian", "Parent", "v1", "dpia", 0)
    consents.grant(conn, "cloud_voice", "guardian", "Parent", "v1", "dpia", 0, early=("cloud_voice",))
    assert consents.active(conn, "cloud_voice") is not None


def voc29_fallback_to_local(tmp_path):
    """The online endpoint is cut mid-response: the turn is interrupted at the played position with heard text, the
    local sidecar takes over within 3 s with the same binding, and the student is told voice is now on this computer."""
    from cloud_gateway.speech_fakes import FakeLive

    async def scenario() -> None:
        pki = make_pki(sorted(set(HOSTS.values())))
        speech = Speech()
        speech.live.delay = 0.3  # a reply long enough to cut in the middle
        async with gateway(tmp_path, pki, speech, []) as (port, app):
            online, learner = await device(tmp_path, port, pki)
            core, sid, runtime, ui, local, _ = await core_with_voice(tmp_path, online, learner, [], pack=True)
            sock = Socket(ui, sid, profile=None)
            try:
                await asyncio.wait_for(sock.outgoing.get(), 10)
                async with asyncio.timeout(30):
                    while runtime._active is None or not runtime._active.bridge.ready:
                        await asyncio.sleep(0.01)
                bridge = runtime._active.bridge
                await in_ask_chat(sock, runtime)
                pcm = tone(500) + tone(1000, loud=False)
                for at in range(0, len(pcm), 4800):
                    await sock.incoming.put({"type": "websocket.receive", "bytes": pcm[at : at + 4800]})
                heard = b""
                async with asyncio.timeout(30):
                    while len(heard) < 2 * 100 * 48:  # two words of the reply have been played
                        message = await sock.outgoing.get()
                        if message.get("bytes"):
                            heard += message["bytes"][16:]
                response_id = bridge._response.response_id
                await sock.send({"type": "playback", "response_id": response_id, "played_ms": len(heard) // 48,
                                 "ended": False})  # fmt: skip
                assert isinstance(speech.live, FakeLive) and runtime._active.path == "cloud_voice"
                cut = asyncio.get_running_loop().time()
                for connection in list(app.state.voice.live.values()):
                    await connection.socket.close(code=1011)  # the network drops
                async with asyncio.timeout(10):
                    while not local or local[0].sent.empty():
                        await asyncio.sleep(0.01)
                configured = await local[0].sent.get()
                assert asyncio.get_running_loop().time() - cut < 3.0
                # The same binding is replayed on the local endpoint, and the same tutor session goes on.
                assert configured["type"] == "session.update"
                assert configured["session"]["instructions"] == bridge.binding.instructions
                assert runtime._active.path == "local_sidecar" and runtime._active.bridge is bridge
                frames = [f["event"] for f in core._engine(core.sessions[sid]).events.frames]
                states = [f for f in frames if f["type"] == "voice.state"]
                assert any(f["state"] == "interrupted" for f in states)
                notices = [f for f in frames if f["type"] == "notice"]
                assert notices[-1]["message_key"] == "voice.now_local"  # "Voice is now on this computer."
                async with asyncio.timeout(5):
                    while runtime.adapter.jobs:
                        await asyncio.sleep(0.01)
                turn = core.sessions[sid].engine_state.transcript[-1]
                # Interrupted at the played position: what was heard is a strict prefix of the accepted words.
                assert turn["content"] == SAFE and SAFE.startswith(turn["heard_text"]) and turn["heard_text"] != SAFE
            finally:
                await sock.close()
                await runtime.close()
                await online.stop()

    asyncio.run(scenario())


def test_bridge_holds_microphone_audio_while_the_endpoint_is_replaced():
    from agent_core.engine.voice_bindings import VoiceBindings
    from agent_core.engine.voice_bridge import VoiceBridge

    bridge = VoiceBridge(VoiceBindings("0000000000000001").mint("ses_x", "prf_x"))
    bridge.server({"type": "session.created", "event_id": "evt_1", "session": {"type": "realtime"}}, 0)
    bridge.control({"type": "mode", "mode": "hands_free"})
    lost = bridge.endpoint_lost()
    assert not lost.upstream and not bridge.ready
    words = [tone(100)[:4800], tone(100)[:4800][::-1]]
    assert all(not bridge.microphone(pcm).upstream for pcm in words)  # held, not sent anywhere
    effects = bridge.server({"type": "session.created", "event_id": "evt_2", "session": {"type": "realtime"}}, 1)
    kinds = [e["type"] for e in effects.upstream]
    assert kinds == ["session.update", "input_audio_buffer.append", "input_audio_buffer.append"]
    assert [base64.b64decode(e["audio"]) for e in effects.upstream[1:]] == words
    assert bridge.ready
