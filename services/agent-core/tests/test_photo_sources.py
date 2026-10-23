"""Four desktop sources enter preprocessing with identical fixture bytes; OCR/model quality is not inferred."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from pathlib import Path

import pytest
from agent_core.engine.events import new_id
from perception_worker import image
from test_m21_capture_drafts import QUAD, setup

ROOT = Path(__file__).resolve().parents[3]


@pytest.mark.parametrize("extension", ["jpg", "png", "webp"])
def inp15_sources_equivalent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, extension: str) -> None:
    # Keep the actual decode/EXIF/crop/deskew/encode code. This check deliberately supplies no OCR/model output.
    monkeypatch.setattr(image, "words", lambda _: None)
    raw = (ROOT / f"packages/ui/gallery/photo-source-fixture.{extension}").read_bytes()

    async def check() -> None:
        normalized: list[bytes] = []
        for source in ("photo_file", "photo_paste", "photo_drop", "webcam"):
            (tmp_path / source).mkdir()
            core, engine, desk, sid = setup(tmp_path / source)
            started, release = asyncio.Event(), asyncio.Event()
            seen: list[bytes] = []

            async def preprocess(
                data: bytes,
                corners: list[dict[str, float]] | None,
                rotation: int,
                *,
                received: list[bytes] = seen,
                entered: asyncio.Event = started,
                resume: asyncio.Event = release,
            ) -> dict:
                received.append(data)
                entered.set()
                await resume.wait()
                value = image.preprocess(data, corners=corners, rotation=rotation)
                normalized.append(base64.b64decode(value["jpeg"]))
                return value

            engine.preprocess_photo = preprocess
            try:
                record = desk.create(
                    {"client_capture_id": new_id("cli"), "session_id": sid, "source": source, "purpose": "question"},
                    raw,
                )
                cap = record["capture_id"]
                task = asyncio.create_task(desk.crop(cap, {"corners": QUAD, "rotation": 0}))
                await asyncio.wait_for(started.wait(), 2)
                assert desk.get(cap)["status"] == "preprocessing"
                assert desk.get(cap)["source"] == source
                assert seen == [raw] and desk.raw[cap] == raw
                release.set()
                await task
                assert engine.calls == 0  # no reader or model invocation supplies this equivalence result
            finally:
                await desk.close()
                core.store.conn.close()
        assert len(normalized) == 4 and len({hashlib.sha256(data).hexdigest() for data in normalized}) == 1
        assert normalized[0].startswith(b"\xff\xd8")

    asyncio.run(check())
