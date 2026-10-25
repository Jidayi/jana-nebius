"""No-network neural speech contract, durable limits and key custody; not a voice-quality evaluation."""

import asyncio
import base64
import io
import wave

import httpx
import pytest
from cloud_gateway.custody import NvidiaEnvironmentSecrets
from cloud_gateway.podcast_speech import BASE, NvidiaPodcast, SpeechError, validate_audio
from cloud_gateway.secret_scan import scan_bytes
from gateway_stubs import FAKE_KEYS, Device, FakeSecrets, gateway_config, harness

TEXT = "CANARY: Enzymes are biological catalysts."
KEY = "nvapi-test-not-a-real-key"


def wav():
    output = io.BytesIO()
    with wave.open(output, "wb") as audio:
        audio.setparams((1, 2, 22050, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * 2205)
    return output.getvalue()


def setup(tmp, **limits):
    h = harness(
        gateway_config(
            tmp,
            podcast_speech={
                "enabled": True,
                "expires_at": "2026-11-02T00:46:01Z",
                **limits,
            },
        ),
        secrets=FakeSecrets({**FAKE_KEYS, "nvidia_api_key": KEY}),
    )
    service = h.client._transport.app.state.podcast_speech
    sent = []

    def handle(request):
        sent.append(request)
        assert str(request.url) == BASE + "/v1/audio/synthesize"
        assert request.headers["authorization"] == "Bearer " + KEY
        assert "x-profile-token" not in request.headers
        assert b'name="text"' in request.content and TEXT.encode() in request.content
        assert any(
            v in request.content
            for v in (
                b"Magpie-Multilingual.EN-US.Aria",
                b"Magpie-Multilingual.EN-US.Jason",
            )
        )
        assert b"22050" in request.content
        return httpx.Response(200, content=wav(), headers={"content-type": "audio/wav"})

    service.client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    return h, service, sent


def body(index=0):
    return {"request_id": "cli_" + str(index) * 26, "text": TEXT, "voice_index": 0, "nvidia_consent": True}


def test_nvidia_key_source_and_scanner_do_not_expose_or_cross_providers():
    source = NvidiaEnvironmentSecrets({"NVIDIA_API_KEY": KEY})
    assert source.get("nvidia_api_key").reveal() == KEY
    assert source.get("nebius_api_key") is None and KEY not in repr(source)
    canary = b"nv" + b"api-" + b"A7" * 22
    finding = scan_bytes(canary, "fixture")[0]
    assert finding.pattern == "nvidia_api_key" and canary.decode() not in str(finding)


def test_neural_narration_auth_audio_minimisation_and_no_content_in_storage(tmp_path):
    async def run():
        h, _, sent = setup(tmp_path)
        assert (await h.client.get("/v1/podcast/voice")).status_code == 401
        device = Device()
        await device.login(h.client)
        status = await h.client.get("/v1/podcast/voice", headers=device.headers())
        assert status.json() == {"enabled": True, "configured": True, "provider": "nvidia_magpie"}
        reply = await h.client.post("/v1/podcast/speech", json=body(), headers=device.headers())
        assert reply.status_code == 200, reply.text
        assert base64.b64decode(reply.json()["audio_base64"]) == wav()
        assert reply.headers["cache-control"] == "no-store"
        assert len(sent) == 1
        gw = h.client._transport.app.state.gateway
        assert gw.store._db.execute("SELECT characters,state FROM podcast_speech_receipts").fetchone() == (
            len(TEXT),
            "completed",
        )
        for line in gw.store._db.iterdump():
            assert TEXT not in line and KEY not in line and "RIFF" not in line
        assert not any("NVIDIA" in r.model for stub in h.stubs.values() for r in stub.seen)

    asyncio.run(run())


@pytest.mark.parametrize(
    "change",
    [
        {"nvidia_consent": False},
        {"voice_index": 2},
        {"voice_index": True},
        {"text": ""},
        {"text": "x" * 601},
        {"profile_id": "private"},
        {"request_id": "invalid"},
    ],
)
def test_invalid_requests_never_reach_nvidia(tmp_path, change):
    async def run():
        h, _, sent = setup(tmp_path)
        device = Device()
        await device.login(h.client)
        reply = await h.client.post("/v1/podcast/speech", json={**body(), **change}, headers=device.headers())
        assert reply.status_code != 200 and sent == []

    asyncio.run(run())


def test_limits_and_duplicate_protection_survive_service_restart_and_expiry(tmp_path):
    async def run():
        h, service, sent = setup(tmp_path, daily_characters=len(TEXT), total_characters=2 * len(TEXT))
        device = Device()
        await device.login(h.client)
        headers = device.headers()
        assert (await h.client.post("/v1/podcast/speech", json=body(), headers=headers)).status_code == 200
        gw = h.client._transport.app.state.gateway
        restarted = NvidiaPodcast(gw, service.client)
        with pytest.raises(SpeechError, match="already_sent"):
            await restarted.synthesize(device.credential_id, body())
        with pytest.raises(SpeechError, match="limit"):
            await service.synthesize(device.credential_id, body(1))
        h.clock.now += 86400
        assert len(await service.synthesize(device.credential_id, body(1))) > 44
        h.clock.now += 86400
        with pytest.raises(SpeechError, match="limit"):
            await service.synthesize(device.credential_id, body(2))
        h.clock.now += 40 * 86400
        with pytest.raises(SpeechError, match="limit"):
            await service.synthesize(device.credential_id, body(3))
        assert len(sent) == 2

    asyncio.run(run())


def test_failed_or_uncertain_send_remains_counted_and_cannot_repeat(tmp_path):
    async def run():
        h, service, _ = setup(tmp_path, daily_requests=1)
        device = Device()
        await device.login(h.client)
        calls = []

        def fail(request):
            calls.append(request)
            raise httpx.ReadTimeout("synthetic timeout")

        service.client = httpx.AsyncClient(transport=httpx.MockTransport(fail))
        for item in (body(), body(), body(1)):
            result = await h.client.post("/v1/podcast/speech", json=item, headers=device.headers())
            assert result.status_code != 200
        assert len(calls) == 1
        gw = h.client._transport.app.state.gateway
        assert gw.store._db.execute("SELECT characters,state FROM podcast_speech_receipts").fetchone() == (
            len(TEXT),
            "held",
        )

    asyncio.run(run())


@pytest.mark.parametrize("audio", [b"html error page", b"RIFF" + b"0" * 100, wav()[:-20]])
def test_invalid_audio_is_withheld(audio):
    with pytest.raises(SpeechError, match="invalid_audio"):
        validate_audio(audio)


def test_two_voice_podcast_can_use_the_second_nvidia_voice(tmp_path):
    async def run():
        h, _, sent = setup(tmp_path)
        device = Device()
        await device.login(h.client)
        result = await h.client.post("/v1/podcast/speech", json={**body(), "voice_index": 1}, headers=device.headers())
        assert result.status_code == 200
        assert result.json()["voice"] == "Magpie-Multilingual.EN-US.Jason"
        assert b"Magpie-Multilingual.EN-US.Jason" in sent[0].content

    asyncio.run(run())
