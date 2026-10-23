"""INP-33: actual asynchronous trace persistence and lifecycle; metadata-only capture/health/telemetry."""

from __future__ import annotations

import asyncio
import base64
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.contracts import errors
from agent_core.engine.assembly import AppRuntime
from agent_core.trace.metrics import catalogue, from_traces
from agent_core.trace.store import TraceStore
from test_m21_capture_drafts import QUAD, create, setup


@pytest.mark.parametrize("outcome", ["confirmed", "unreadable", "refused", "cancelled"])
def inp33_trace_fields_no_content(tmp_path: Path, outcome: str) -> None:
    async def check() -> None:
        core, engine, desk, sid = setup(tmp_path)
        store = TraceStore(tmp_path / "traces/traces.db", max_bytes=1_000_000, retention_days=30)
        sent: list[dict] = []
        enabled = [True]
        telemetry = SimpleNamespace(add=lambda metrics, **metadata: sent.append({"metrics": metrics, **metadata}))
        runtime = SimpleNamespace(
            traces=store,
            storage_low=lambda: False,
            settings=core.settings,
            online=SimpleNamespace(features_on=lambda: {"telemetry"} if enabled[0] else set(), telemetry=telemetry),
        )
        core.capture_trace_sink = lambda record: AppRuntime._trace_sink(runtime, record)
        core.trace_records = store.records
        core.capture_summary = store.perception_summary
        engine.processed["lines"][0]["text"] = "Find PRIVATE_TRANSCRIPTION_CANARY if x=10."
        engine.processed["ocr_model_version"] = "fixture-v1"
        if outcome == "unreadable":
            engine.processed["lines"][0]["confidence"] = 0.59
        if outcome == "refused":
            engine.processed["refusal"] = "contains_person"
        try:
            cap = create(desk, sid)["capture_id"]
            if outcome != "cancelled":
                await desk.crop(cap, {"corners": QUAD, "rotation": 0})
                if outcome != "refused":
                    desk.read(cap, {})
                    await desk.tasks[cap]
                    if outcome == "confirmed":
                        desk.confirm(cap, {"text": "Find EDITED_TRANSCRIPTION_CANARY if x=12."})
            else:
                desk.delete(cap)
            store.flush()
            assert len(sent) == 1 and "CANARY" not in json.dumps(sent)
            if outcome == "confirmed":
                desk.put(desk.get(cap))
                store.flush()
                assert len(sent) == 1  # an update/view never double-counts the terminal observation
            records = store.records()
            assert desk.trace_failures == store.failures == 0 and len(records) == 1
            record = records[0]
            assert errors("trace/turn-trace", record) == []
            assert record["job_name"] == "capture" and record["trace_version"] == "1.3"
            photo = record["perception"]
            assert photo["source"] == "photo_file" and photo["outcome"] == outcome
            assert set(photo) == {
                "source",
                "outcome",
                "reader",
                "quality_checks",
                "region_confidences",
                "durations_ms",
                "confirm_method",
                "confirm_edit_distance",
            }
            if outcome in ("confirmed", "unreadable"):
                assert photo["quality_checks"] == engine.processed["checks"]
                assert photo["reader"]["model_version"] == "fixture-v1"
                assert photo["reader"]["path"] == "ocr_pipeline"
                assert photo["region_confidences"] == [0.98 if outcome == "confirmed" else 0.59]
            if outcome == "confirmed":
                assert photo["confirm_method"] == "edited" and photo["confirm_edit_distance"] > 0
            assert all(type(value) is int and value >= 0 for value in photo["durations_ms"].values())
            encoded = json.dumps(record)
            for canary in [
                "PRIVATE_TRANSCRIPTION_CANARY",
                "EDITED_TRANSCRIPTION_CANARY",
                "synthetic-original-never-stored",
                engine.processed["jpeg"],
                base64.b64encode(b"synthetic-original-never-stored").decode(),
            ]:
                assert canary not in encoded
            for field in ["text", "jpeg", "regions", "attachments", "prompt", "image"]:
                bad = copy.deepcopy(record)
                bad["perception"][field] = "PRIVATE_TRANSCRIPTION_CANARY"
                assert errors("trace/turn-trace", bad)
            health = core.health()
            assert errors("api/commands#/$defs/Health", health) == []
            assert health["perception"] == [
                {
                    "hardware_class": "mid",
                    "captures": 1,
                    "confirmed": int(outcome == "confirmed"),
                    "edited": int(outcome == "confirmed"),
                    "unreadable": int(outcome == "unreadable"),
                }
            ]
            report = catalogue(records, [])
            metrics = from_traces(records)
            assert "turn_duration_ms" not in metrics and "guided_step_ms" not in metrics
            assert metrics["photo_captures"]["sum"] == 1
            assert "CANARY" not in json.dumps(report) and "profile_ref" not in json.dumps(report)
            assert store.timings_since(0) == []  # capture time never masquerades as tutor latency
            if outcome in ("confirmed", "unreadable", "refused"):
                desk.delete(cap)
                store.flush()
                assert store.records()[0]["perception"] == photo  # disposal cannot erase the read outcome/edit evidence
            assert not desk.trace_builders and not desk.preprocess_ms
            enabled[0] = False
            # A new capture remains local with telemetry switched off, including its terminal cancellation.
            second = create(desk, sid)["capture_id"]
            desk.delete(second)
            store.flush()
            assert len(sent) == 1
            store.delete_profile("implicit")
            assert store.records() == [] and core.health()["perception"] == []
        finally:
            await desk.close()
            store.close()
            core.store.conn.close()

    asyncio.run(check())


def test_profile_deletion_drains_pending_capture_observations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import threading

    async def check() -> None:
        core, _engine, desk, sid = setup(tmp_path)
        store = TraceStore(tmp_path / "traces/traces.db", max_bytes=1_000_000, retention_days=30)
        entered, release = threading.Event(), threading.Event()
        write = store._write

        def delayed(conn, record) -> None:
            entered.set()
            assert release.wait(2)
            write(conn, record)

        monkeypatch.setattr(store, "_write", delayed)
        core.capture_trace_sink = store.submit
        timer = threading.Timer(0.05, release.set)
        try:
            create(desk, sid)
            assert entered.wait(1)
            await desk.close()  # the profile's producers stop before its eraser runs
            timer.start()
            store.delete_profile("implicit")  # queued draft/cancel records cannot resurrect after deletion
            assert store.records() == [] and store.failures == 0
        finally:
            release.set()
            timer.cancel()
            await desk.close()
            store.close()
            core.store.conn.close()

    asyncio.run(check())
