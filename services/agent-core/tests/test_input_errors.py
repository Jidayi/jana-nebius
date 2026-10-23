"""INP-07: real worker parse refusal occurs before any message/board turn is accepted."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.config import Settings
from agent_core.engine.events import new_id
from agent_core.store.sessions import SessionStore
from engine_harness import close, make_engine


@pytest.mark.parametrize(
    ("line", "position", "hint", "kind"),
    [
        ("s=(", 3, "unbalanced_bracket", "PARSE_REJECTED"),
        ("s=", 2, "empty_slot", "PARSE_REJECTED"),
        ("x@2", 1, "unknown_word", "PARSE_REJECTED"),
        ("x" * 2001, 2000, "too_long", "LIMIT_EXCEEDED"),
    ],
    ids=["bracket", "empty", "unknown", "length"],
)
def inp07_parse_error_hints(tmp_path: Path, line: str, position: int, hint: str, kind: str) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {})
        core = CoreService(Settings(), lambda _: engine, SessionStore(tmp_path / "sessions.db"))
        try:
            sid = core.create_session(
                {
                    "client_session_id": new_id("cli"),
                    "subject": "mathematics",
                    "mode": "guided",
                    "origin": {"kind": "ask", "ref": None},
                }
            )["session_id"]
            before = repr(core.entry(sid).engine_state)
            body = {
                "client_message_id": new_id("cli"),
                "intent": "board_line",
                "content": [{"type": "board_line", "step_id": new_id("stp"), "latex": line}],
            }
            with pytest.raises(ApiError) as caught:
                await core.preflight_input(sid, body)
            error = caught.value
            assert error.code == "validation_failed"
            assert error.details["input_error"] == kind
            assert error.details["hint_key"] == hint
            assert error.details["position"] == position and error.details["line"] == 1
            assert body["content"][0]["latex"] == line  # input is not rewritten or marked incorrect
            assert core.entry(sid).task is None and engine.turn_number == 0
            after = repr(core.entry(sid).engine_state)
            assert after == before
            assert engine.state.board.steps == [] and engine.events.frames == []
        finally:
            await close(engine)

    asyncio.run(check())
