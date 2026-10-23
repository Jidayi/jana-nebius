"""INP-23 confidence boundary and character coverage invariants, independent of model calibration."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from agent_core.api.errors import ApiError
from agent_core.engine.events import new_id
from agent_core.engine.vision import PhotoReading
from engine_harness import close, reply
from test_capture_reader_schema import reader_regions
from test_m11f_vision import reader_engine, run
from test_m21_capture_drafts import QUAD, create, setup

CASES = [
    (0.5999, [], False, True),
    (0.6, [], False, False),
    (0.8499, [], False, False),
    (0.85, [], False, False),
    (0.99, [{"start": 0, "end": 6}], False, False),
    (0.99, [{"start": 0, "end": 7}], False, True),
    (0.99, [{"start": 0, "end": 7}], True, True),
    (0.99, [{"start": 0, "end": 6}, {"start": 0, "end": 6}], False, False),
]


@pytest.mark.parametrize("path", ["vision_model", "cloud_vision", "ocr_pipeline"])
@pytest.mark.parametrize("confidence,spans,metadata,unreadable", CASES)
def inp23_no_guess_below_threshold(
    tmp_path: Path, path: str, confidence: float, spans: list[dict], metadata: bool, unreadable: bool
) -> None:
    region = copy.deepcopy(reader_regions()[0])
    region.update(text="Find x if 2x=10.    ", confidence=confidence, low_confidence_spans=spans)
    assert len(region["text"]) == 20
    regions = [region]
    if metadata:
        diagram = copy.deepcopy(reader_regions()[4])
        diagram.update(text="", diagram_description="Description " * 80)
        regions.append(diagram)
    output = {"regions": regions, "refusal": None}
    engine, local, cloud = reader_engine(tmp_path / "reader", cloud_on=path == "cloud_vision")
    local.script = cloud.script = {"vision": [reply(json.dumps(output))]}

    async def check() -> None:
        core, boundary, desk, sid = setup(tmp_path)
        boundary.processed["lines"] = [dict(r, bbox={k: v / 1000 for k, v in r["bbox"].items()}) for r in regions]
        if path != "ocr_pipeline":
            boundary.read_photo = engine.read_photo
        else:

            async def off(*_args: object, **_kwargs: object) -> PhotoReading:
                return PhotoReading("off")

            boundary.read_photo = off
        try:
            cap = create(desk, sid)["capture_id"]
            await desk.crop(cap, {"corners": QUAD, "rotation": 0})
            desk.read(cap, {"send_to_cloud": path == "cloud_vision"})
            await desk.tasks[cap]
            record = desk.get(cap)
            assert record["status"] == ("unreadable" if unreadable else "awaiting_confirmation")
            assert record["regions"][0]["text"] == region["text"]
            assert record["regions"][0]["needs_confirmation"] == (confidence < 0.85 or bool(spans))
            assert record["confirmation"]["confirmed"] is False
            assert core.entry(sid).task is None and not boundary.frames
            if unreadable:
                for forged in ["Find x if 2x=10.", "5"]:
                    with pytest.raises(ApiError, match="capture_not_ready"):
                        desk.confirm(cap, {"text": forged})
                with pytest.raises(ApiError, match="capture_not_ready"):
                    desk.turn_body(
                        sid,
                        {
                            "capture_id": cap,
                            "client_message_id": new_id("cli"),
                            "intent": "ask",
                            "content": [],
                        },
                    )
            else:
                assert desk.confirm(cap, {"text": region["text"]})["status"] == "confirmed"
        finally:
            await desk.close()
            core.store.conn.close()

    try:
        run(check())
    finally:
        run(close(engine))
