"""INP-19: real 12 MP EXIF pixels/storage; synthetic OCR coordinates isolate mapping from model quality."""

from __future__ import annotations

import asyncio
import hashlib
import io
from pathlib import Path

import numpy as np
import pytest
from agent_core.engine.events import new_id
from agent_core.engine.vision import PhotoReading
from agent_core.tools.perception import PerceptionClient
from perception_worker import image
from PIL import Image
from test_m21_capture_drafts import QUAD, setup


def exif_photo() -> bytes:
    columns = np.arange(3000, dtype=np.uint16) // 8
    rows = np.arange(4000, dtype=np.uint16) // 8
    gray = (120 + 60 * ((rows[:, None] + columns[None, :]) % 2)).astype(np.uint8)
    pixels = np.repeat(gray[:, :, None], 3, axis=2)
    pixels[1200:1600, 600:1650] = [180, 110, 110]  # independent known upright question bounding box
    pixels[50:150, 50:150] = [100, 120, 180]
    pixels[3850:3950, 2850:2950] = [120, 180, 120]
    upright = Image.fromarray(pixels)
    raw = upright.transpose(Image.Transpose.ROTATE_90)  # EXIF 6 must put this back clockwise
    exif = Image.Exif()
    exif[0x0112] = 6
    exif[0x010F] = "JANA SYNTHETIC EXIF SOURCE"
    exif.get_ifd(0x8825).update({1: "N", 2: (0.0, 0.0, 0.0), 3: "E", 4: (0.0, 0.0, 0.0)})
    encoded = io.BytesIO()
    raw.save(encoded, "JPEG", quality=95, exif=exif)
    assert raw.size == (4000, 3000)
    return encoded.getvalue()


def inp19_derivatives_and_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    source = exif_photo()
    seen: list[np.ndarray] = []

    def local_screen(gray: np.ndarray) -> list[dict]:
        seen.append(gray.copy())
        assert gray.shape == (2048, 1536)
        assert int(gray.min()) == 0 and int(gray.max()) == 255
        return [
            {"line": "question", "text": "Find x", "confidence": 0.99, "x": 307.2, "y": 614.4, "w": 537.6, "h": 204.8}
        ]

    monkeypatch.setattr(image, "words", local_screen)

    async def check() -> None:
        core, engine, desk, sid = setup(tmp_path)
        reader_inputs: list[bytes] = []

        async def preprocess(data: bytes, corners: list | None, rotation: int) -> dict:
            return image.preprocess(data, corners=corners, rotation=rotation)

        async def read(data: bytes, **_kwargs: object) -> PhotoReading:
            reader_inputs.append(data)
            return PhotoReading("off")  # only the declared synthetic local screen supplies the coordinates

        engine.preprocess_photo = preprocess
        engine.read_photo = read
        try:
            cap = desk.create(
                {"client_capture_id": new_id("cli"), "session_id": sid, "source": "photo_file", "purpose": "question"},
                source,
            )["capture_id"]
            cropped = await desk.crop(cap, {"corners": QUAD, "rotation": 0})
            assert len(seen) == 1 and len(cropped["attachments"]) == 1
            attachment = cropped["attachments"][0]
            assert (attachment["width"], attachment["height"]) == (1200, 1600)
            assert attachment["scale_from_original"] == 0.4
            paths = list(desk.root().glob("*.jpg"))
            assert len(paths) == 1
            saved = paths[0].read_bytes()
            assert saved != source and hashlib.sha256(saved).hexdigest() == attachment["sha256"]
            stored = Image.open(io.BytesIO(saved))
            assert stored.size == (1200, 1600) and not stored.getexif() and not stored.info.get("exif")
            assert "icc_profile" not in stored.info and b"JANA SYNTHETIC EXIF SOURCE" not in saved
            pixels = np.array(stored)
            blue = pixels[30:50, 30:50].mean(axis=(0, 1))
            assert blue[2] > blue[0] + 30
            green = pixels[1550:1570, 1150:1170].mean(axis=(0, 1))
            assert green[1] > green[0] + 30
            desk.read(cap, {"override_quality": False, "send_to_cloud": False})
            await desk.tasks[cap]
            result = desk.get(cap)
            assert result["status"] == "awaiting_confirmation" and reader_inputs == [saved]
            box = result["regions"][0]["bbox"]
            assert box["image_id"] == attachment["image_id"]
            red = (pixels[:, :, 0] > 150) & (pixels[:, :, 1] < 140) & (pixels[:, :, 2] < 140)
            ys, xs = np.where(red)
            assert len(xs) > 1000
            measured = [xs.min(), ys.min(), xs.max() - xs.min() + 1, ys.max() - ys.min() + 1]
            projected = [box["x"] * 1200, box["y"] * 1600, box["w"] * 1200, box["h"] * 1600]
            for actual, expected, scale in zip(projected, measured, [1200, 1600, 1200, 1600], strict=True):
                assert abs(actual - expected) / scale <= 0.01
            assert all(p.read_bytes() != source for p in paths) and cap not in desk.raw
        finally:
            await desk.close()
            core.store.conn.close()

    asyncio.run(check())


def test_native_perception_ipc_keeps_the_event_loop_responsive() -> None:
    async def check() -> None:
        data = exif_photo()
        task = asyncio.create_task(PerceptionClient().run(data, preview_only=True))
        ticks = 0
        while not task.done():
            await asyncio.sleep(0.01)
            ticks += 1
        result = await task
        assert len(result["outline"]) == 4 and ticks >= 2

    asyncio.run(check())


def test_capture_preprocessing_is_serial_while_other_core_work_can_run(tmp_path: Path) -> None:
    from test_m21_capture_drafts import prepared

    async def check() -> None:
        core, engine, desk, sid = setup(tmp_path)
        engine.flush = lambda: None  # this fixture emits synchronously and has no buffered session events
        active = 0
        maximum = 0
        calls = 0

        async def work(*_args: object, **_kwargs: object) -> dict:
            nonlocal active, maximum, calls
            active += 1
            maximum = max(maximum, active)
            calls += 1
            try:
                await asyncio.sleep(0.01)
                return prepared()
            finally:
                active -= 1

        engine.preprocess_photo = work
        try:
            caps = [
                desk.create(
                    {
                        "client_capture_id": new_id("cli"),
                        "session_id": sid,
                        "source": "photo_file",
                        "purpose": "question",
                    },
                    b"synthetic scheduling fixture",
                )["capture_id"]
                for _ in range(2)
            ]
            pending = asyncio.gather(*(desk.crop(cap, {"corners": QUAD, "rotation": 0}) for cap in caps))
            ticks = 0
            while not pending.done():
                assert core.snapshot(sid)["session"]["session_id"] == sid
                ticks += 1
                await asyncio.sleep(0.001)
            await pending
            assert calls == 2 and maximum == 1 and ticks >= 2
        finally:
            await desk.close()
            core.store.conn.close()

    asyncio.run(check())
