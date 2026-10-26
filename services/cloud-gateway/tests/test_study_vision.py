"""Photo and scanned-PDF extraction through real sandboxes; scripted model replies test protocol, not accuracy."""

import asyncio
import base64
import copy
import hashlib
import io
import json
from pathlib import Path

import pytest
from gateway_stubs import PRICES, PROVIDERS, Device, Output, gateway_config, harness
from PIL import Image

JID = "stj_" + "3" * 26
SID = "src_" + "4" * 26
FIXTURE = Path(__file__).resolve().parents[3] / "evals/perception/handwriting/synthetic-maths.png"


def configured(tmp_path, **overrides):
    providers = copy.deepcopy(PROVIDERS)
    providers["nebius"]["models"]["vision-model"] = {"id": "vision-stub", "image_input_token_bound": 32768}
    return gateway_config(
        tmp_path,
        slots={"primary": "nebius"},
        providers=providers,
        prices={**PRICES, "vision-stub": {"input": 1, "cached_input": 1, "output": 4}},
        study_vision_model="primary/vision-model",
        **overrides,
    )


async def upload(h, device, data, kind):
    body = {
        "request_id": JID,
        "kind": kind,
        "mime_type": "application/octet-stream",
        "byte_length": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    grant = await h.client.post("/v1/study/uploads", json=body, headers=device.headers())
    assert grant.status_code == 200, grant.text
    uid = grant.json()["upload_id"]
    part = {"offset": 0, "sha256": body["sha256"], "data_base64": base64.b64encode(data).decode()}
    assert (
        await h.client.put(f"/v1/study/uploads/{uid}/chunks/0", json=part, headers=device.headers())
    ).status_code == 200
    return {"request_id": JID, "upload_id": uid, "source_id": SID, "revision": 1, "locale": "en"}


@pytest.mark.parametrize("kind", ["photo", "pdf"])
def test_real_photo_and_scanned_pdf_keep_page_order_metering_and_frozen_replay(tmp_path, kind):
    async def run():
        h = harness(configured(tmp_path, quotas={"deployment_total_spend_usd": 1}))
        device = Device()
        await device.login(h.client)
        raw = FIXTURE.read_bytes()
        count = 1 if kind == "photo" else 2
        if kind == "pdf":
            image = Image.open(io.BytesIO(raw)).convert("RGB")
            stream = io.BytesIO()
            image.save(stream, format="PDF", save_all=True, append_images=[image])
            raw = stream.getvalue()
        h.stubs["nebius"].say(
            *[Output(text=json.dumps({"text": f"Page {i}: x = 10", "uncertain": False})) for i in range(1, count + 1)]
        )
        asked = await upload(h, device, raw, kind)
        response = await h.client.post("/v1/study/extract", json=asked, headers=device.headers())
        assert response.status_code == 200, response.text
        result = response.json()
        assert [c["locator"]["page"] for c in result["chunks"]] == list(range(1, count + 1))
        assert [c["text"] for c in result["chunks"]] == [f"Page {i}: x = 10" for i in range(1, count + 1)]
        assert not result["unreadable_units"]
        assert result["usage"]["input_tokens"] == count * 40
        assert result["usage"]["cost_usd"] > count * h.config.study_extract_page_usd
        replay = await h.client.post("/v1/study/extract", json=asked, headers=device.headers())
        assert replay.json() == result and len(h.stubs["nebius"].seen) == count
        for seen in h.stubs["nebius"].seen:
            assert seen.model == "vision-stub" and seen.body["store"] is False
            assert "data:image/jpeg;base64," in json.dumps(seen.body)
        gateway = h.client._transport.app.state.gateway
        assert not gateway.store._db.execute("SELECT 1 FROM inference_budget_pending").fetchone()
        assert not gateway.store._db.execute("SELECT 1 FROM study_receipts WHERE state='reserved'").fetchone()
        assert all(not b.data for b in h.client._transport.app.state.study.buffers.values())
        await h.client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "out",
    [{"text": "x = [?]", "uncertain": True}, {"text": "x = [?]", "uncertain": False}, {"text": "", "uncertain": True}],
)
def test_uncertain_recognition_stays_unreadable_instead_of_becoming_evidence(tmp_path, out):
    async def run():
        h = harness(configured(tmp_path))
        device = Device()
        await device.login(h.client)
        h.stubs["nebius"].say(Output(text=json.dumps(out)))
        asked = await upload(h, device, FIXTURE.read_bytes(), "photo")
        response = await h.client.post("/v1/study/extract", json=asked, headers=device.headers())
        assert response.status_code == 200, response.text
        assert response.json()["chunks"] == [] and response.json()["unreadable_units"] == [1]
        assert len(h.stubs["nebius"].seen) == 1

    asyncio.run(run())


def test_budget_exhaustion_blocks_vision_before_any_provider_send(tmp_path):
    async def run():
        h = harness(configured(tmp_path, quotas={"deployment_total_spend_usd": 0}))
        device = Device()
        await device.login(h.client)
        asked = await upload(h, device, FIXTURE.read_bytes(), "photo")
        response = await h.client.post("/v1/study/extract", json=asked, headers=device.headers())
        assert response.status_code == 503 and response.json()["error"]["code"] == "allowance_exhausted"
        assert not h.stubs["nebius"].seen

    asyncio.run(run())
