"""Lazy launch/control handoff with synthetic signed pack bytes and an in-memory endpoint."""

import asyncio
import copy

import pytest
from agent_core.config.environments import Environment
from agent_core.contracts import errors
from agent_core.net.voice import LocalVoiceEndpoint, VoiceTransportError
from agent_core.net.voice_launch import VoiceLaunch
from signing_service.hierarchy import dev_trust
from test_m31_voice_socket import Endpoint
from test_m32_speech_packs import pack, signed


def setup(tmp_path, *, timeout=1):
    root = tmp_path / "speech-packs"
    root.mkdir()
    folder = root / "sp.en.1_0"
    document = pack(folder)
    frames = []
    link = VoiceLaunch(
        root,
        "mid",
        "linux-x86_64",
        "0.0.0",
        Environment.DEV,
        "http://127.0.0.1:8765/v1/voice/llm",
        "synthetic_" + "a" * 32,
        frames.append,
        start_timeout_s=timeout,
    )
    link.store.trust = dev_trust()
    return link, frames, folder, document


def test_manifest_scan_is_lazy_and_chooses_numeric_version(tmp_path):
    link, frames, folder, document = setup(tmp_path)
    newer = folder.parent / "sp.en.10_0"
    document = pack(newer)
    document["speech_pack_id"] = "sp.en.10_0"
    signed(newer, document)
    assert link.scan(manifest_only=True) and link.selected[0] == newer and not frames
    # Large weight hashes are deferred until first use, while signatures/licences/profile are checked at startup.
    (newer / "tts/config.json").write_bytes(b"damaged")
    assert link.scan(manifest_only=True) and link.selected[0] == newer
    # SEC-16: the damaged newest pack is not replaced by the older one; voice waits for a pack that verifies.
    assert not link.scan() and link.selected is None


def test_first_use_sends_one_private_control_frame_and_ignores_stale_endpoint(tmp_path, monkeypatch):
    async def scenario():
        link, frames, _, _ = setup(tmp_path)
        opened = []

        async def open(_):
            endpoint = Endpoint()
            opened.append(endpoint)
            return endpoint

        monkeypatch.setattr(LocalVoiceEndpoint, "open", open)
        connecting = asyncio.create_task(link.connect())
        async with asyncio.timeout(2):
            while not frames:
                await asyncio.sleep(0.01)
        start = frames[0]
        assert errors("control/control#/$defs/ToShell", start) == []
        assert start["type"] == "control.voice_start" and "realtime_token" not in start
        reply = {
            "type": "control.voice_endpoint",
            "request_id": "0" * 32,
            "url": "ws://127.0.0.1:2345/v1/realtime",
            "token": "synthetic_" + "b" * 32,
        }
        link.on_shell(reply)
        assert not connecting.done()
        reply["request_id"] = start["request_id"]
        assert errors("control/control#/$defs/ToCore", reply) == []
        link.on_shell(reply)
        connection = await connecting
        assert connection.socket is opened[0]
        assert (await connection.receive())["type"] == "session.created"
        await connection.close()
        second = await link.connect()
        assert second.socket is opened[1] and len(frames) == 1
        await second.close()
        await link.close()
        assert frames[-1] == {"type": "control.voice_stop", "request_id": start["request_id"]}
        with pytest.raises(VoiceTransportError, match="voice_closed"):
            await link.connect()

    asyncio.run(scenario())


@pytest.mark.parametrize("failure", ["timeout", "give_up", "corrupt_pack"])
def test_launch_failure_never_connects_or_leaks_a_credential(tmp_path, failure):
    async def scenario():
        link, frames, folder, _ = setup(tmp_path, timeout=0.03)
        if failure == "corrupt_pack":
            (folder / "tts/config.json").write_bytes(b"bad")
        connecting = asyncio.create_task(link.connect())
        if failure == "give_up":
            async with asyncio.timeout(1):
                while not frames:
                    await asyncio.sleep(0.001)
            link.on_shell(
                {"type": "control.voice_failed", "request_id": frames[0]["request_id"], "code": "voice_gave_up"}
            )
        with pytest.raises(VoiceTransportError) as error:
            await connecting
        assert "synthetic_" not in str(error.value)
        assert link._endpoint is None
        if failure == "corrupt_pack":
            assert not frames
        else:
            assert frames[-1]["type"] == "control.voice_stop"
        await link.close()

    asyncio.run(scenario())


def test_signed_manifest_matches_its_canonical_contract(tmp_path):
    _, _, _, document = setup(tmp_path)
    assert errors("ops/speech-pack", document) == []
    bad = copy.deepcopy(document)
    bad["profiles"]["mid"]["reference_audio"] = "private.wav"
    assert errors("ops/speech-pack", bad)


def test_reconnect_waits_for_the_previous_pipeline_to_drain(tmp_path, monkeypatch):
    async def scenario():
        link, frames, _, _ = setup(tmp_path)
        busy, ready = Endpoint(), Endpoint()
        busy.incoming.get_nowait()
        busy.incoming.put_nowait({"type": "error", "error": {"type": "session_limit_reached"}})
        attempts = []

        async def open(_):
            endpoint = busy if not attempts else ready
            attempts.append(endpoint)
            return endpoint

        monkeypatch.setattr(LocalVoiceEndpoint, "open", open)
        assert link.scan()
        link._endpoint = LocalVoiceEndpoint("ws://127.0.0.1:2345/v1/realtime", "synthetic_" + "b" * 32)
        connection = await link.connect()
        assert len(attempts) == 2 and busy.closed
        assert (await connection.receive())["type"] == "session.created"
        assert not frames
        await connection.close()
        await link.close()

    asyncio.run(scenario())


def test_cached_endpoint_is_not_reused_after_unrelated_update_revokes_its_signer(tmp_path, monkeypatch):
    from signing_service.revocation import dev_revocation_list

    async def scenario():
        link, frames, _, document = setup(tmp_path)
        monkeypatch.setattr(LocalVoiceEndpoint, "open", lambda _: asyncio.sleep(0, result=Endpoint()))
        connecting = asyncio.create_task(link.connect())
        async with asyncio.timeout(2):
            while not frames:
                await asyncio.sleep(0.01)
        link.on_shell(
            {
                "type": "control.voice_endpoint",
                "request_id": frames[0]["request_id"],
                "url": "ws://127.0.0.1:2345/v1/realtime",
                "token": "synthetic_" + "b" * 32,
            }
        )
        connection = await connecting
        await connection.close()
        link.store.revocations.adopt(
            dev_revocation_list(
                2,
                [
                    {
                        "key_id": document["signature"]["key_id"],
                        "reason": "synthetic test",
                        "revoked_at": "2026-10-15T00:00:00.000Z",
                    }
                ],
            )
        )
        with pytest.raises(VoiceTransportError, match="voice_pack_unavailable"):
            await link.connect()
        assert frames[-1]["type"] == "control.voice_stop"
        await link.close()

    asyncio.run(scenario())
