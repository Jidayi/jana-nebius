"""Real bounded loopback WebSocket transport, independent of speech models and the public internet."""

import asyncio
import json
import secrets

import pytest
from agent_core.net.voice import LocalVoiceEndpoint, VoiceTransportError
from websockets.asyncio.server import serve


@pytest.mark.parametrize(
    "url",
    [
        "wss://voice.example.invalid/v1/realtime",
        "ws://192.168.1.2:8765/v1/realtime",
        "ws://localhost:8765/v1/realtime",
        "ws://127.0.0.1:8765/other",
        "ws://127.0.0.1/v1/realtime",
        "ws://127.0.0.1:8765/v1/realtime?token=secret",
        "ws://user:secret@127.0.0.1:8765/v1/realtime",
    ],
)
def test_voice_endpoint_accepts_literal_loopback_only(url):
    with pytest.raises(VoiceTransportError, match=r"^invalid_local_voice_endpoint$"):
        LocalVoiceEndpoint(url, secrets.token_hex(32))


def voc27_endpoint_swap(monkeypatch):
    async def scenario():
        credential = secrets.token_hex(32)
        received = []

        async def peer(socket):
            assert socket.request.headers["Authorization"] == "Bearer " + credential
            await socket.send(json.dumps({"type": "session.created", "event_id": "e", "session": {"type": "realtime"}}))
            received.append(json.loads(await socket.recv()))

        for _ in range(2):
            async with serve(peer, "127.0.0.1", 0, compression=None) as server:
                port = server.sockets[0].getsockname()[1]
                endpoint = LocalVoiceEndpoint(f"ws://127.0.0.1:{port}/v1/realtime", credential)
                assert credential not in repr(endpoint)
                socket = await endpoint.open()
                assert (await socket.receive())["type"] == "session.created"
                await socket.send({"type": "session.update", "session": {"type": "realtime", "tools": []}})
                await socket.close()
        assert received == [{"type": "session.update", "session": {"type": "realtime", "tools": []}}] * 2

    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:12345")
    monkeypatch.setenv("HTTPS_PROXY", "http://192.0.2.1:12345")
    asyncio.run(scenario())


def test_realtime_wrong_token_fails_without_exposing_credentials(caplog):
    async def scenario():
        async def reject(connection, _request):
            return connection.respond(401, "refused")

        async def peer(_socket):
            raise AssertionError("unauthenticated handler must not run")

        async with serve(peer, "127.0.0.1", 0, process_request=reject) as server:
            port = server.sockets[0].getsockname()[1]
            credential = secrets.token_hex(32)
            endpoint = LocalVoiceEndpoint(f"ws://127.0.0.1:{port}/v1/realtime", credential)
            with pytest.raises(VoiceTransportError, match=r"^voice_endpoint_unavailable$") as raised:
                await endpoint.open()
            assert credential not in repr(raised.value) and credential not in caplog.text

    asyncio.run(scenario())


@pytest.mark.parametrize("payload", [b"not a JSON audio event", "[]", "invalid json"])
def test_bad_endpoint_frames_are_reason_only(payload):
    async def scenario():
        async def peer(socket):
            await socket.send(payload)

        async with serve(peer, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            socket = await LocalVoiceEndpoint(f"ws://127.0.0.1:{port}/v1/realtime", secrets.token_hex(32)).open()
            try:
                with pytest.raises(VoiceTransportError, match=r"^voice_receive_failed$"):
                    await socket.receive()
            finally:
                await socket.close()

    asyncio.run(scenario())
