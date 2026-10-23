"""INP-12: the UI's eight-line fixture traverses the real HTTP/core/checker in order."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.security import LaunchSecret
from agent_core.config import Settings
from agent_core.engine.events import new_id
from agent_core.store.sessions import SessionStore
from engine_harness import close, make_engine, tutor
from test_m21_typed_working import SAFE, prepared

LINES = json.loads((Path(__file__).resolve().parents[3] / "packages/ui/gallery/working-paste-golden.json").read_text())


def inp12_paste_splits_lines(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE)]})
        core = CoreService(Settings(), lambda _: engine, SessionStore(tmp_path / "sessions"))
        try:
            sid = core.create_session(
                {
                    "client_session_id": new_id("cli"),
                    "subject": "physics",
                    "mode": "guided",
                    "origin": {"kind": "ask", "ref": None},
                }
            )["session_id"]
            engine.state = core.entry(sid).engine_state
            engine.events.session_id = sid
            prepared(engine)
            key = new_id("cli")
            app = create_app(core, LaunchSecret("synthetic-token"), lambda: 8787)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://127.0.0.1:8787",
                headers={
                    "authorization": "Bearer synthetic-token",
                    "origin": "tauri://localhost",
                    "idempotency-key": key,
                },
            ) as client:
                reply = await client.post(
                    f"/v1/sessions/{sid}/turns",
                    json={
                        "client_message_id": key,
                        "intent": "board_line",
                        "content": [{"type": "text", "text": "\n".join(LINES)}],
                    },
                )
                assert reply.status_code == 202, reply.text
                await core.entry(sid).task
                steps = engine.state.board.steps
                assert len(steps) == 8
                assert [step.index for step in steps] == list(range(8))
                assert [step.latex for step in steps] == LINES
                assert len({step.step_id for step in steps}) == 8
                assert all(step.owner == "student" and step.status == "correct" and step.check_id for step in steps)
                checking = [
                    frame["event"]
                    for frame in engine.events.frames
                    if frame["event"]["type"] == "board.step" and frame["event"]["status"] == "checking"
                ]
                assert [event["latex"] for event in checking] == LINES
                snapshot = (await client.get(f"/v1/sessions/{sid}/snapshot")).json()
                board = next(iter(snapshot["boards"].values()))
                assert [
                    step["latex"] for step in sorted(board["steps"].values(), key=lambda step: step["index"])
                ] == LINES
        finally:
            await close(engine)

    asyncio.run(check())
