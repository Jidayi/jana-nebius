"""INP-22: all reader paths through real capture projection and closed schema validation."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from agent_core.contracts import errors
from agent_core.engine.vision import PhotoReading, reader_output
from engine_harness import close, reply
from test_m11f_vision import reader_engine, run
from test_m21_capture_drafts import QUAD, create, setup

KINDS = ["question_stem", "sub_part", "answer_options", "table", "diagram", "working_line", "other"]


def reader_regions() -> list[dict]:
    texts = [
        r"Find x if \(2x+5=15\).",
        "Explain your answer.",
        "A: 5; B: 10",
        "Read the values.",
        "Triangle with sides 3 and 4.",
        r"\(2x=10\)",
        "Use the space below.",
    ]
    return [
        {
            "region_id": f"rgn_{i}",
            "kind": kind,
            "order": i,
            "number_label": "1" if i == 0 else None,
            "text": text,
            "latex": "2x=10" if kind == "working_line" else None,
            "bbox": {"x": 100, "y": 100 + i * 100, "w": 400, "h": 50},
            "confidence": 0.99,
            "needs_confirmation": False,
            "low_confidence_spans": [],
            "language": "en",
            "direction": "ltr",
            "diagram_description": "Triangle with labelled sides 3 and 4." if kind == "diagram" else None,
            "table": {"template": "generic", "columns": ["t / s", "v / m s^-1"], "rows": [["0", "2"], ["5", "10"]]}
            if kind == "table"
            else None,
        }
        for i, (kind, text) in enumerate(zip(KINDS, texts, strict=True))
    ]


@pytest.mark.parametrize("path", ["vision_model", "cloud_vision", "ocr_pipeline"])
def inp22_reader_output_schema(tmp_path: Path, path: str) -> None:
    original = reader_regions()
    output = {"regions": original, "refusal": None}
    assert not list(reader_output()[2].iter_errors(output))
    engine, local, cloud = reader_engine(tmp_path / "reader", cloud_on=path == "cloud_vision")
    local.script = {"vision": [reply(json.dumps(output))]}
    cloud.script = {"vision": [reply(json.dumps(output))]}

    async def check() -> None:
        core, boundary, desk, sid = setup(tmp_path)
        # Synthetic local privacy/OCR results isolate schema/routing from model recognition accuracy.
        boundary.processed["lines"] = [dict(r, bbox={k: v / 1000 for k, v in r["bbox"].items()}) for r in original]
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
            assert record["status"] == "awaiting_confirmation"
            assert errors("input/captured-question", record) == []
            assert record["reader"]["path"] == path
            assert record["egress"]["left_device"] == (path == "cloud_vision")
            assert [r["kind"] for r in record["regions"]] == KINDS
            for expected, actual in zip(original, record["regions"], strict=True):
                assert actual["text"] == expected["text"] and actual["latex"] == expected["latex"]
                assert actual["table"] == expected["table"]
                assert actual["bbox"]["image_id"] == record["attachments"][0]["image_id"]
                assert actual["bbox"]["x"] == 0.1 and actual["bbox"]["w"] == 0.4
            requests = local.requests + cloud.requests
            assert len(requests) == (0 if path == "ocr_pipeline" else 1)
            for request in requests:
                assert [m["role"] for m in request["messages"]] == ["user"]
                assert not request.get("tools")
                assert "response_format" in request
                assert "synthetic-original" not in str(request)
        finally:
            await desk.close()
            core.store.conn.close()

    try:
        run(check())
    finally:
        run(close(engine))


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "solver"),
        ("confidence", 1.01),
        ("language", "zz"),
        ("text", "x" * 4001),
        ("bbox", {"x": -1, "y": 0, "w": 1, "h": 1}),
    ],
)
def test_reader_schema_rejects_invalid_regions(field: str, value: object) -> None:
    region = copy.deepcopy(reader_regions()[0])
    region[field] = value
    assert list(reader_output()[2].iter_errors({"regions": [region], "refusal": None}))
