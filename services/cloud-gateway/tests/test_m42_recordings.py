"""Real sandboxed media decode; scripted ASR checks protocol, not transcription quality."""

import asyncio
import base64
import hashlib
import io
import json
import wave

from gateway_stubs import Device, Output, gateway_config, harness
from test_m42_study import JID, SID


def recording(seconds=2):
    stream = io.BytesIO()
    with wave.open(stream, "wb") as audio:
        audio.setnchannels(1)
        audio.setsampwidth(2)
        audio.setframerate(8000)
        audio.writeframes(b"\x00\x00" * 8000 * seconds)
    return stream.getvalue()


def test_recording_real_sandbox_timestamp_uncertainty_and_cleanup(tmp_path):
    async def run():
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        raw = recording(61)
        grant = await h.client.post(
            "/v1/study/uploads",
            json={
                "request_id": JID,
                "kind": "recording",
                "mime_type": "audio/wav",
                "byte_length": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
            },
            headers=device.headers(),
        )
        assert grant.status_code == 200, grant.text
        uid = grant.json()["upload_id"]
        for offset in range(0, len(raw), 1048576):
            part = raw[offset : offset + 1048576]
            response = await h.client.put(
                f"/v1/study/uploads/{uid}/chunks/{offset // 1048576}",
                json={
                    "offset": offset,
                    "sha256": hashlib.sha256(part).hexdigest(),
                    "data_base64": base64.b64encode(part).decode(),
                },
                headers=device.headers(),
            )
            assert response.status_code == 200
        h.stubs["gemini"].say(
            Output(
                text=json.dumps({"text": "Enzymes are biological catalysts.", "uncertain": False, "language": "en"})
            ),
            Output(
                text=json.dumps({"text": "do not publish uncertain words", "uncertain": True, "language": "unknown"})
            ),
        )
        body = {"request_id": JID, "upload_id": uid, "source_id": SID, "revision": 1, "locale": "en"}
        result = await h.client.post("/v1/study/extract", json=body, headers=device.headers())
        assert result.status_code == 200, result.text
        value = result.json()
        assert value["duration_ms"] == 61000 and value["unreadable_units"] == [2]
        assert len(value["chunks"]) == 1 and value["chunks"][0]["locator"] == {
            "kind": "time",
            "start_ms": 0,
            "end_ms": 60000,
        }
        assert "uncertain words" not in result.text
        assert value["usage"]["cost_usd"] > 0
        assert (await h.client.post("/v1/study/extract", json=body, headers=device.headers())).json() == value
        assert len(h.stubs["gemini"].seen) == 2
        assert (await h.client.delete("/v1/study/requests/" + JID, headers=device.headers())).status_code == 204
        assert not h.client._transport.app.state.study.buffers
        for path in tmp_path.rglob("*"):
            if path.is_file():
                assert b"Enzymes" not in path.read_bytes() and b"RIFF" not in path.read_bytes()

    asyncio.run(run())


def test_recording_duration_limit_refuses_before_provider(tmp_path):
    import pytest
    from study_worker import DocumentError
    from study_worker.media import decode

    with pytest.raises(DocumentError, match="source_too_large"):
        decode(recording(61), None, 1)
