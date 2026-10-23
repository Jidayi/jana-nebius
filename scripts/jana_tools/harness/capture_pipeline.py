"""Evaluation adapter over the app's actual capture state machine, engine and sandboxed worker.

Only the temporary store and the configured model providers differ from the app. There is no mocked OCR, reader,
quality verdict or confirmation path. Callers own fixture provenance and must never pass learner photographs.
"""

from __future__ import annotations

import copy
import tempfile
import time
from pathlib import Path
from typing import Any

from agent_core.api.captures import CaptureDesk
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.config import Settings
from agent_core.engine.assembly import assemble
from agent_core.engine.state import SessionState
from agent_core.engine.turn import Engine
from agent_core.store.checkpoints import CheckpointStore
from agent_core.store.ids import new_ulid
from agent_core.store.sqlite import open_database

from .. import REPO_ROOT

QUAD = [{"x": 0, "y": 0}, {"x": 1, "y": 0}, {"x": 1, "y": 1}, {"x": 0, "y": 1}]


class CapturePipeline:
    def __init__(self, hardware_class: str = "mid", router: Any = None) -> None:
        self.hardware_class = hardware_class
        self.router = router

    async def __aenter__(self) -> CapturePipeline:
        self.scratch = tempfile.TemporaryDirectory(prefix="jana-photo-eval-")
        root = Path(self.scratch.name)
        self.conn, _ = open_database(root / "learner.db", "learner")
        settings = Settings()

        def engine_for(state: SessionState) -> Engine:
            engine = assemble(
                {}, settings, state, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", root / "spill"
            )
            if self.router is not None:
                engine.deps.router = self.router
            return engine

        self.core = CoreService(settings, engine_for, CheckpointStore(self.conn))
        self.desk = CaptureDesk(self.core)
        self.core.capture_desk = self.desk
        self.sid = self.core.create_session(
            {
                "client_session_id": f"cli_{new_ulid()}",
                "mode": "guided",
                "subject": "mathematics",
                "origin": {"kind": "ask", "ref": None},
            }
        )["session_id"]
        self.core.entry(self.sid).engine_state.hardware_class = self.hardware_class
        return self

    async def __aexit__(self, *_: Any) -> None:
        try:
            await self.core.shutdown()
        finally:
            self.conn.close()
            self.scratch.cleanup()

    async def capture(
        self,
        data: bytes,
        *,
        purpose: str = "question",
        override_quality: bool = False,
        rotation: int = 0,
        confirmed_text: str | None = None,
        selected_question: str | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        first_app_seq = self.core.app_channel.seq
        cap: str | None = None
        try:
            record = self.desk.create(
                {
                    "client_capture_id": f"cli_{new_ulid()}",
                    "session_id": self.sid,
                    "source": "photo_file",
                    "purpose": purpose,
                },
                data,
            )
            cap = record["capture_id"]
            record = await self.desk.crop(cap, {"corners": QUAD, "rotation": rotation})
            result: dict[str, Any] = {"capture_id": cap, "record": copy.deepcopy(record), "derivatives": []}
            before_read = time.perf_counter()
            result["preprocess_ms"] = round((before_read - started) * 1000, 3)
            body: dict[str, Any] = {
                "capture_id": cap,
                "intent": "board_line" if purpose == "working" else "ask",
                "content": [],
            }
            try:
                self.desk.turn_body(self.sid, body)
                result["unconfirmed_refused"] = False
            except ApiError as error:
                result["unconfirmed_refused"] = error.code == "capture_not_ready"
            if record["status"] not in ("refused", "cancelled"):
                try:
                    self.desk.read(cap, {"override_quality": override_quality, "send_to_cloud": False})
                except ApiError as error:
                    result["read_error"] = error.code
                else:
                    await self.desk.tasks[cap]
            record = self.desk.get(cap)
            result["record"] = copy.deepcopy(record)
            result["reader_ms"] = round((time.perf_counter() - before_read) * 1000, 3)
            for attachment in record["attachments"]:
                row = self.conn.execute(
                    "SELECT file_path FROM attachments WHERE attachment_id=?", (attachment["image_id"],)
                ).fetchone()
                result["derivatives"].append((self.desk.root() / row[0]).read_bytes())
            if confirmed_text is not None and record["status"] in ("awaiting_confirmation", "unreadable"):
                confirmed = self.desk.confirm(cap, {"text": confirmed_text, "selected_question": selected_question})
                result["confirmed"] = copy.deepcopy(confirmed)
                result["turn_text"] = self.desk.turn_body(self.sid, body)["content"][0]["text"]
            result["original_volatile"] = cap not in self.desk.raw and cap not in self.desk.prepared
            result["app_event_errors"] = list(self.core.app_channel.rejected)
            result["app_progress_events"] = self.core.app_channel.seq - first_app_seq
            result["total_ms"] = round((time.perf_counter() - started) * 1000, 3)
            return result
        except ApiError as error:
            return {
                "error": error.code,
                "capture_id": cap,
                "total_ms": round((time.perf_counter() - started) * 1000, 3),
            }
        finally:
            if cap is not None:
                self.desk.delete(cap)
