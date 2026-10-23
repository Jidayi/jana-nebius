"""INP-34 actual assessment sitting state controls every photo source and pending capture action."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.security import LaunchSecret
from agent_core.engine.events import new_id
from test_m16_assessment import answer, desk, start_mock  # noqa: F401 - imports the real assessment fixture
from test_m21_capture_drafts import QUAD, create, setup


@pytest.mark.parametrize("state", ["in_progress", "paused", "interrupted"])
def inp34_capture_locked_in_exam(tmp_path: Path, request: pytest.FixtureRequest, state: str) -> None:
    async def check() -> None:
        assessment, _clock = request.getfixturevalue("desk")
        folder = tmp_path / "capture"
        folder.mkdir()
        core, engine, old_desk, sid = setup(folder)
        core.assessments = lambda: assessment
        core.mock_active = assessment.mock_active
        app = create_app(core, LaunchSecret("synthetic-exam-secret"), lambda: 8787)
        captures = core.capture_desk
        try:
            pending = create(captures, sid)["capture_id"]
            await captures.crop(pending, {"corners": QUAD, "rotation": 0})
            captures.read(pending, {})
            await captures.tasks[pending]
            calls = engine.calls
            exam = start_mock(assessment)
            if state != "in_progress":
                assessment.transition(exam["exam_id"], "pause" if state == "paused" else "interrupt")
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8787",
                headers={"authorization": "Bearer synthetic-exam-secret", "origin": "tauri://localhost"},
            ) as client:
                for source in [
                    "photo_file",
                    "photo_paste",
                    "photo_drop",
                    "webcam",
                    "device_camera",
                    "handwriting_photo",
                    "pdf_page",
                ]:
                    meta = {
                        "client_capture_id": new_id("cli"),
                        "session_id": sid,
                        "source": source,
                        "purpose": "question",
                    }
                    response = await client.post(
                        "/v1/captures",
                        files={
                            "meta": (None, json.dumps(meta)),
                            "file": ("synthetic.jpg", b"image bytes must never reach a reader", "image/jpeg"),
                        },
                        headers={"idempotency-key": meta["client_capture_id"]},
                    )
                    assert response.status_code == 423 and response.json()["error"]["code"] == "capture_locked", (
                        response.text
                    )
                for method, suffix, body in [
                    ("PATCH", "crop", {"corners": QUAD, "rotation": 0}),
                    ("POST", "read", {}),
                    ("POST", "confirm", {"text": "Find x=10."}),
                ]:
                    response = await client.request(
                        method,
                        f"/v1/captures/{pending}/{suffix}",
                        json=body,
                        headers={"idempotency-key": new_id("cli")},
                    )
                    assert response.status_code == 423 and response.json()["error"]["code"] == "capture_locked"
                assert engine.calls == calls and not captures.raw
                # The actual sitting still accepts and durably saves an answer; the tutor/capture lock is separate.
                if state != "in_progress":
                    assessment.transition(exam["exam_id"], "resume")
                assessment.save_mock_answer(exam["exam_id"], "q1", answer(), False)
                assert assessment.mock(exam["exam_id"])["answers"]["q1"]["answer"] == answer()
                await assessment.submit_mock(exam["exam_id"])
                meta = {
                    "client_capture_id": new_id("cli"),
                    "session_id": sid,
                    "source": "photo_file",
                    "purpose": "question",
                }
                unlocked = await client.post(
                    "/v1/captures",
                    files={
                        "meta": (None, json.dumps(meta)),
                        "file": ("synthetic.jpg", b"new capture after submission", "image/jpeg"),
                    },
                    headers={"idempotency-key": meta["client_capture_id"]},
                )
                assert unlocked.status_code == 200
        finally:
            await captures.close()
            await old_desk.close()
            core.store.conn.close()

    asyncio.run(check())
