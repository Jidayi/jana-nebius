"""INP-20 synthetic worksheet; actual local OCR/worker, stored pixels and scripted cloud request bytes."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from agent_core.engine.events import new_id
from agent_core.tools.perception import PerceptionClient
from engine_harness import close
from PIL import Image, ImageDraw, ImageFont
from test_m11f_vision import images_in, reader_engine, run
from test_m21_capture_drafts import QUAD, setup


def inp20_personal_data_masked(tmp_path: Path) -> None:
    picture = Image.new("RGB", (1400, 1000), "white")
    draw = ImageDraw.Draw(picture)
    font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 46)
    for y, text in [
        (110, "Name: Synthetic Person"),
        (210, "Phone: +234 800 123 4567"),
        (400, "Find x if 2x + 5 = 15."),
    ]:
        draw.text((100, y), text, fill="black", font=font)
    raw = io.BytesIO()
    picture.save(raw, "PNG")
    engine, _local, cloud = reader_engine(tmp_path / "reader")

    async def check() -> None:
        core, boundary, desk, sid = setup(tmp_path)
        boundary.preprocess_photo = PerceptionClient().run
        boundary.read_photo = engine.read_photo
        try:
            cap = desk.create(
                {"client_capture_id": new_id("cli"), "session_id": sid, "source": "photo_file", "purpose": "question"},
                raw.getvalue(),
            )["capture_id"]
            crop = await desk.crop(cap, {"corners": QUAD, "rotation": 0})
            assert crop["attachments"] and desk.prepared[cap]["privacy_available"]
            assert "Synthetic Person" not in str(desk.prepared[cap]["lines"])
            assert "800" not in str(desk.prepared[cap]["lines"])
            stored = next(desk.root().glob("*.jpg")).read_bytes()
            desk.read(cap, {"send_to_cloud": True, "override_quality": True})
            await desk.tasks[cap]
            assert images_in(cloud) and all(data == stored for data in images_in(cloud))
            for data in (stored, *images_in(cloud)):
                image = np.array(Image.open(io.BytesIO(data)))
                # Independently specified source regions: formerly thousands of dark text pixels, now masked.
                assert np.min(image[115:165, 100:650]) >= 240
                assert np.min(image[215:265, 100:700]) >= 240
                assert np.count_nonzero(image[405:455, 100:600, 0] < 100) > 100
            assert raw.getvalue() != stored and cap not in desk.raw
            assert "Synthetic Person" not in str(desk.get(cap))
            assert "800 123" not in str(desk.get(cap))
        finally:
            await desk.close()
            core.store.conn.close()

    try:
        run(check())
    finally:
        run(close(engine))
