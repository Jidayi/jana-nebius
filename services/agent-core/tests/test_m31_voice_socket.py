"""Exercise the actual ASGI socket, guards, SSE event sink and endpoint lifecycle without TCP or speech models."""

import asyncio
import contextlib
import json
from types import SimpleNamespace

import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CURRENT_PROFILE, CoreService
from agent_core.api.security import LaunchSecret
from agent_core.api.voice import VoiceRuntime
from agent_core.config import Settings
from agent_core.contracts import errors
from agent_core.engine.events import EventStream, new_id
from agent_core.engine.voice_bridge import VoiceProtocolError
from agent_core.store.sessions import SessionStore
from test_m31_voice_bridge import TURN, audio, event


class Tokens:
    """The token book's idle sweep, as the profile scope asks it on every request (SEC-19): nothing lapses here."""

    def lapsed_profiles(self):
        return []


class Directory:
    def __init__(self):
        self.live = {"profile-a-secret": "profile_a", "profile-b-secret": "profile_b"}
        self.tokens = Tokens()

    def exists(self):
        return True

    def profile_of(self, presented):
        return self.live.get(presented)


class Endpoint:
    def __init__(self):
        self.incoming = asyncio.Queue(maxsize=16)
        self.sent = asyncio.Queue(maxsize=16)
        self.closed = False
        self.incoming.put_nowait(event("session.created", session={"type": "realtime"}))

    async def send(self, frame):
        await self.sent.put(frame)

    async def receive(self):
        frame = await self.incoming.get()
        if isinstance(frame, Exception):
            raise frame
        return frame

    async def close(self):
        self.closed = True


class Socket:
    def __init__(
        self,
        app,
        session_id,
        *,
        profile="profile-a-secret",
        bearer="launch-secret",
        origin="tauri://localhost",
        host="127.0.0.1:8765",
        extra_protocols=(),
    ):
        self.incoming, self.outgoing = asyncio.Queue(), asyncio.Queue()
        protocols = ["jana.voice.1", *extra_protocols]
        if bearer:
            protocols.append("jana.bearer." + bearer)
        if profile:
            protocols.append("jana.profile." + profile)
        self.scope = {
            "type": "websocket",
            "asgi": {"version": "3.0", "spec_version": "2.4"},
            "scheme": "ws",
            "path": f"/v1/sessions/{session_id}/voice",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", host.encode()), (b"origin", origin.encode())],
            "subprotocols": protocols,
            "client": ("127.0.0.1", 1234),
            "server": ("127.0.0.1", 8765),
        }
        self.incoming.put_nowait({"type": "websocket.connect"})
        self.task = asyncio.create_task(app(self.scope, self.incoming.get, self.outgoing.put))

    async def receive(self):
        return await asyncio.wait_for(self.outgoing.get(), timeout=2)

    async def send(self, control):
        await self.incoming.put({"type": "websocket.receive", "text": json.dumps(control)})

    async def close(self):
        await self.incoming.put({"type": "websocket.disconnect", "code": 1000})
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.wait_for(self.task, timeout=2)


def setup(tmp_path, *, action_failure=False):
    def engine(state):
        return SimpleNamespace(events=EventStream(state.session_id, "epoch"), profile_ref="local")

    core = CoreService(Settings(), engine, SessionStore(tmp_path), epoch="0000000000000001")
    core.directory = Directory()
    sessions = []
    for profile in ("profile_a", "profile_a", "profile_b"):
        token = CURRENT_PROFILE.set(profile)
        try:
            sessions.append(
                core.create_session(
                    {
                        "client_session_id": new_id("cli"),
                        "mode": "guided",
                        "subject": "physics",
                        "level": "O",
                        "origin": {"kind": "ask", "ref": None},
                    }
                )["session_id"]
            )
        finally:
            CURRENT_PROFILE.reset(token)
    endpoints, actions = [], []

    async def connect():
        endpoint = Endpoint()
        endpoints.append(endpoint)
        return endpoint

    async def on_action(action):
        actions.append(action)
        if action_failure and action["type"] == "release":
            raise RuntimeError("sensitive transcript must not be logged")

    runtime = VoiceRuntime(core, connect, on_action, strict=True)
    app = create_app(core, LaunchSecret("launch-secret"), lambda: 8765, voice=runtime)
    return core, sessions, endpoints, actions, runtime, app


async def started(app, session_id, endpoints):
    socket = Socket(app, session_id)
    assert (await socket.receive())["subprotocol"] == "jana.voice.1"
    while not endpoints:
        await asyncio.sleep(0)
    config = await asyncio.wait_for(endpoints[-1].sent.get(), timeout=2)
    assert config["type"] == "session.update"
    assert config["session"]["instructions"].startswith("jana-voice-binding: vb_")
    return socket, endpoints[-1]


@pytest.mark.parametrize(
    ("options", "code"),
    [
        ({"bearer": None}, 4401),
        ({"bearer": "wrong"}, 4401),
        ({"profile": None}, 4401),
        ({"profile": "wrong"}, 4401),
        ({"profile": "profile-b-secret"}, 4404),
        ({"origin": "https://foreign.invalid"}, 4403),
        ({"host": "foreign.invalid:8765"}, 4403),
        ({"extra_protocols": ("jana.bearer.duplicate",)}, 4401),
        ({"extra_protocols": ("jana.profile.duplicate",)}, 4401),
    ],
)
def voc26_socket_auth(tmp_path, options, code):
    async def scenario():
        _, sessions, endpoints, _, runtime, app = setup(tmp_path)
        socket = Socket(app, sessions[0], **options)
        reply = await socket.receive()
        assert reply["type"] == "websocket.close" and reply["code"] == code
        await socket.close()
        assert not endpoints
        await runtime.close()

    asyncio.run(scenario())


def voc26_flush_drops_audio(tmp_path):
    async def scenario():
        core, sessions, endpoints, actions, runtime, app = setup(tmp_path)
        socket, endpoint = await started(app, sessions[0], endpoints)
        try:
            await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
            # The trusted adapter authorises only after the bridge has correlated response.created.
            while runtime._active.bridge._response is None:
                await asyncio.sleep(0)
            runtime.authorise_response(runtime._active.bridge.binding, "resp_1", TURN, "Try again.")
            await endpoint.incoming.put(audio())
            binary = await socket.receive()
            assert binary["type"] == "websocket.send" and len(binary["bytes"]) == 4816
            assert actions[0]["type"] == "release"
            await socket.send({"type": "stop"})
            assert json.loads((await socket.receive())["text"]) == {"type": "flush", "response_id": "resp_1"}
            cancel = await asyncio.wait_for(endpoint.sent.get(), timeout=2)
            assert cancel == {"type": "response.cancel", "response_id": "resp_1"}
            await endpoint.incoming.put(audio())
            await socket.send({"type": "capture", "echo_cancellation": True, "headphones": False})
            assert (await asyncio.wait_for(endpoint.sent.get(), timeout=2))["type"] == "session.update"
            assert socket.outgoing.empty()  # delayed chunks after the flush cannot refill playback
            frames = core._engine(core.sessions[sessions[0]]).events.frames
            assert frames and all(errors("api/events", frame) == [] for frame in frames)
        finally:
            await socket.close()
            await runtime.close()
        assert endpoint.closed and not runtime.bindings._live

    asyncio.run(scenario())


def voc24_unit_reset_on_switch(tmp_path):
    async def scenario():
        _, sessions, endpoints, _, runtime, app = setup(tmp_path)
        first, old_endpoint = await started(app, sessions[0], endpoints)
        old_binding = runtime._active.bridge.binding
        second = Socket(app, sessions[1])
        assert (await second.receive())["type"] == "websocket.accept"
        assert (await first.receive())["type"] == "websocket.close"
        assert old_endpoint.closed and not runtime.bindings.contains(old_binding)
        assert runtime._active.bridge.binding.session_id == sessions[1]
        assert runtime._active.bridge.binding.binding_id != old_binding.binding_id
        with pytest.raises(VoiceProtocolError, match="voice_session_not_current"):
            runtime.authorise_response(old_binding, "resp_1", TURN, "Try again.")
        await second.close()
        await first.close()
        await runtime.close()

    asyncio.run(scenario())


@pytest.mark.parametrize("reason", ["expiry", "profile_close", "archive", "shutdown"])
def test_idle_socket_revokes_binding_on_lifecycle_end(tmp_path, reason):
    async def scenario():
        core, sessions, endpoints, _, runtime, app = setup(tmp_path)
        socket, endpoint = await started(app, sessions[0], endpoints)
        binding = runtime._active.bridge.binding
        if reason == "expiry":
            del core.directory.live["profile-a-secret"]
        elif reason == "profile_close":
            core.forget_profile("profile_a")
        elif reason == "archive":
            core.sessions[sessions[0]].meta["archived"] = True
        else:
            await runtime.close()
        reply = await socket.receive()
        assert reply["type"] == "websocket.close"
        assert reply["code"] == {"expiry": 4401, "profile_close": 4401, "archive": 4404, "shutdown": 1001}[reason]
        assert endpoint.closed and not runtime.bindings.contains(binding)
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())


def test_unbound_endpoint_audio_is_never_forwarded(tmp_path):
    async def scenario():
        _, sessions, endpoints, actions, runtime, app = setup(tmp_path)
        socket, endpoint = await started(app, sessions[0], endpoints)
        await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
        await endpoint.incoming.put(audio())
        messages = []
        while True:
            message = await socket.receive()
            messages.append(message)
            if message["type"] == "websocket.close":
                break
        assert all("bytes" not in message for message in messages)
        assert actions[0]["type"] == "discard"
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())


def test_adapter_release_failure_never_forwards_audio_or_logs_secrets(tmp_path, caplog):
    async def scenario():
        _, sessions, endpoints, _, runtime, app = setup(tmp_path, action_failure=True)
        socket, endpoint = await started(app, sessions[0], endpoints)
        await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
        while runtime._active.bridge._response is None:
            await asyncio.sleep(0)
        runtime.authorise_response(runtime._active.bridge.binding, "resp_1", TURN, "Try again.")
        await endpoint.incoming.put(audio())
        while True:
            message = await socket.receive()
            assert "bytes" not in message
            if message["type"] == "websocket.close":
                assert message["code"] == 1011
                break
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())
    assert "sensitive transcript" not in caplog.text


def test_disconnect_discards_provisional_work_even_when_flush_cannot_reach_browser(tmp_path):
    async def scenario():
        _, sessions, endpoints, actions, runtime, app = setup(tmp_path)
        socket, endpoint = await started(app, sessions[0], endpoints)
        await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
        while runtime._active.bridge._response is None:
            await asyncio.sleep(0)
        await socket.close()
        assert len(actions) == 1
        assert actions[0]["type"] == "discard" and actions[0]["response_id"] == "resp_1"
        assert actions[0]["turn_id"] is None and actions[0]["session_id"] == sessions[0]
        assert actions[0]["binding_id"].startswith("vb_")
        assert endpoint.closed and runtime._active is None and not runtime.bindings._live
        await runtime.close()

    asyncio.run(scenario())


def test_profile_expiry_during_adapter_release_still_blocks_audio(tmp_path):
    async def scenario():
        core, sessions, endpoints, actions, runtime, app = setup(tmp_path)
        original = runtime.on_action

        async def expire(action):
            await original(action)
            if action["type"] == "release":
                core.directory.live.clear()

        runtime.on_action = expire
        socket, endpoint = await started(app, sessions[0], endpoints)
        await endpoint.incoming.put(event("response.created", response={"id": "resp_1"}))
        while runtime._active.bridge._response is None:
            await asyncio.sleep(0)
        runtime.authorise_response(runtime._active.bridge.binding, "resp_1", TURN, "Try again.")
        await endpoint.incoming.put(audio())
        while True:
            message = await socket.receive()
            assert "bytes" not in message
            if message["type"] == "websocket.close":
                assert message["code"] == 4401
                break
        assert [a["type"] for a in actions] == ["release", "cancel"]
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())


def test_endpoint_failure_closes_and_leaves_unavailable_state(tmp_path, caplog):
    async def scenario():
        core, sessions, _, _, runtime, app = setup(tmp_path)

        async def broken():
            raise RuntimeError("endpoint credential must not appear in diagnostics")

        runtime.connect = broken
        socket = Socket(app, sessions[0])
        assert (await socket.receive())["code"] == 1011
        frames = core._engine(core.sessions[sessions[0]]).events.frames
        assert frames[-1]["event"]["state"] == "unavailable"
        assert not runtime.bindings._live
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())
    assert "endpoint credential" not in caplog.text


def test_socket_accept_waits_for_first_use_sidecar_readiness(tmp_path):
    async def scenario():
        _, sessions, _, _, runtime, app = setup(tmp_path)
        ready = asyncio.Event()

        async def connect():
            await ready.wait()
            return Endpoint()

        runtime.connect = connect
        socket = Socket(app, sessions[0])
        await asyncio.sleep(0.02)
        assert socket.outgoing.empty()
        ready.set()
        assert (await socket.receive())["type"] == "websocket.accept"
        await socket.close()
        await runtime.close()

    asyncio.run(scenario())
