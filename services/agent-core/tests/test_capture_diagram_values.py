"""INP-26 confirmed diagram values reach S2 diagnosis/knowns/Solver; synthetic recognition and agents."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agent_core.api.captures import CaptureDesk
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.engine.events import new_id
from agent_core.engine.vision import PhotoReading
from agent_core.store.checkpoints import CheckpointStore
from agent_core.store.sqlite import open_database
from engine_harness import close, make_engine, reply
from test_m14a_roles import diagnosis
from test_m21_capture_drafts import QUAD, create, prepared


@pytest.mark.parametrize("confirmed,bad", [("3", ""), ("6", ""), ("6", "value"), ("6", "unit"), ("6", "quote")])
def inp26_diagram_values_confirmed(tmp_path: Path, confirmed: str, bad: str) -> None:
    async def check() -> None:
        a = "3" if bad == "value" else confirmed
        knowns = [
            {"symbol": "a", "value": a, "unit": "cm", "quote": f"Side a = {confirmed} cm"},
            {"symbol": "b", "value": "4", "unit": "cm", "quote": "Side b = 4 cm"},
        ]
        if bad == "unit":
            knowns[0]["unit"] = "m"
        if bad == "quote":
            knowns[0]["quote"] = "Unconfirmed side a = 6 cm"
        engine, provider = await make_engine(
            tmp_path,
            {
                "diagnoser": [diagnosis(question_kind="diagram", knowns=knowns, unknowns=["c"], inference="")] * 3,
                "solver": [
                    reply(
                        json.dumps(
                            {
                                "status": "blocked",
                                "method_summary": "Use Pythagoras.",
                                "steps": [],
                                "final_answer": None,
                                "blocked_step": 1,
                                "blocked_reason": "No computation.",
                            }
                        )
                    )
                ]
                * 3,
            },
            worker=False,
            stage="S2",
        )
        conn, _ = open_database(tmp_path / "learner.db", "learner")
        core = CoreService(engine.deps.settings, lambda _: engine, CheckpointStore(conn))
        sid = core.create_session(
            {
                "client_session_id": new_id("cli"),
                "mode": "guided",
                "subject": "physics",
                "origin": {"kind": "ask", "ref": None},
            }
        )["session_id"]
        core._engine(core.entry(sid))
        desk = CaptureDesk(core)
        core.capture_desk = desk
        page = prepared("Find the hypotenuse c of this right triangle.")
        page["lines"].append(
            dict(
                page["lines"][0],
                kind="diagram",
                text="Right triangle ABC.",
                diagram_description="Side a = 3 cm; Side b = 4 cm; find c.",
                bbox={"x": 0.1, "y": 0.2, "w": 0.4, "h": 0.4},
            )
        )

        async def preprocess(*_args: object, **_kwargs: object) -> dict:
            return page

        async def off(*_args: object, **_kwargs: object) -> PhotoReading:
            return PhotoReading("off")

        engine.preprocess_photo = preprocess
        engine.read_photo = off
        try:
            cap = create(desk, sid)["capture_id"]
            await desk.crop(cap, {"corners": QUAD, "rotation": 0})
            desk.read(cap, {})
            await desk.tasks[cap]
            record = desk.get(cap)
            assert any(a["kind"] == "diagram_crop" for a in record["attachments"])
            assert "Side a = 3 cm" in record["text"]
            body = {
                "client_message_id": new_id("cli"),
                "intent": "ask",
                "capture_id": cap,
                "content": [{"type": "text", "text": "forged unconfirmed 999 cm"}],
            }
            with pytest.raises(ApiError, match="capture_not_ready"):
                core.start_turn(sid, body)
            assert not provider.requests
            text = record["text"].replace("Side a = 3 cm", f"Side a = {confirmed} cm")
            desk.confirm(cap, {"text": text})
            core.start_turn(sid, body)
            await core.entry(sid).task
            solvers = [r for r in provider.requests if r.get("_role") == "solver"]
            if bad:
                assert not solvers, "an unconfirmed diagram value must not reach the Solver"
            else:
                assert solvers
                assert {r["value"] for r in engine.state.board.knowns} == {confirmed, "4"}
                assert engine.state.problem.statement == text
                for request in solvers:
                    content = str(request["messages"])
                    assert f"Side a = {confirmed} cm" in content and "Side b = 4 cm" in content
                    assert "999" not in content
                    if confirmed == "6":
                        assert "Side a = 3 cm" not in content
        finally:
            await desk.close()
            await close(engine)
            conn.close()

    asyncio.run(check())
