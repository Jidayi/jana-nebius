"""Synthetic working: real sandboxed grammar/checkers, stable ids and input errors before acceptance."""

from __future__ import annotations

import asyncio
from fractions import Fraction
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.api.security import LaunchSecret
from agent_core.config import Settings
from agent_core.engine.events import new_id
from agent_core.engine.input import normalise_input
from agent_core.engine.state import BoardStep, Plan, PlanStep, Problem
from agent_core.store.sessions import SessionStore
from engine_harness import STATEMENT, close, make_engine, tutor

SAFE = "Which part of your working would you like to discuss?"
LINES = ["0 = 14^2 - 2*9.8*s", "19.6*s = 196", "s = 196/19.6", "s = 10", "2*s = 20"]


def prepared(engine: Any) -> None:
    state = engine.state
    state.problem = Problem("prb_synthetic", STATEMENT, "synthetic#statement")
    state.plan = Plan([PlanStep(1, "s = 10", "10", None, "chk_SYNTH")], "10", None, "chk_SYNTH", final_latex="s = 10")
    state.check_values["chk_SYNTH"] = [Fraction(10)]


def inp11_edit_rechecks_following_lines(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE), tutor(SAFE)]})
        try:
            prepared(engine)
            ids = [new_id("stp") for _ in LINES]
            await engine.board_turn(list(zip(ids, LINES, strict=True)))
            assert [s.step_id for s in engine.state.board.steps] == ids
            assert all(s.status == "correct" for s in engine.state.board.steps)
            first = engine.state.board.steps[0]
            first_check = first.check_id
            events_at = len(engine.events.frames)
            await engine.board_turn([(ids[1], "19.6*s = 176")])
            steps = engine.state.board.steps
            assert [s.step_id for s in steps] == ids
            assert first.check_id == first_check and first.status == "correct"
            assert [s.latex for s in steps[2:]] == LINES[2:]
            assert steps[1].status == "incorrect" and not engine.state.solved
            changed = [e["event"] for e in engine.events.frames[events_at:] if e["event"]["type"] == "board.step"]
            assert [e["step_id"] for e in changed] == ids[1:] * 2
            assert [e["status"] for e in changed[:4]] == ["checking"] * 4
            assert LINES[1] not in engine.state.student_lines
        finally:
            await close(engine)

    asyncio.run(check())


def inp11_tutor_lines_read_only(tmp_path: Path) -> None:
    # The core's half: a board line the tutor wrote is never changed by a student's edit naming it. The UI's half (no
    # edit action by pointer or keyboard) is the test of the same name in packages/ui/test/board.test.tsx.
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE)]})
        try:
            prepared(engine)
            tutor_id = new_id("stp")
            teacher = BoardStep(tutor_id, 0, "v^2 = u^2 + 2as", None, "tutor", "unchecked")
            engine.state.board.steps.append(teacher)
            await engine.board_turn([(tutor_id, "v = 999")])
            assert teacher.latex == "v^2 = u^2 + 2as" and teacher.owner == "tutor"
            assert [s.step_id for s in engine.state.board.steps if s.owner == "tutor"] == [tutor_id]
        finally:
            await close(engine)

    asyncio.run(check())


def test_inp11_failed_parse_preserves_working(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE)]})
        try:
            prepared(engine)
            own_id = new_id("stp")
            await engine.board_turn([(own_id, "s = 10")])
            own = engine.state.board.steps[0]
            before = (own.latex, own.status, own.check_id)
            await engine.board_turn([(own_id, "s = (")])
            assert (own.latex, own.status, own.check_id) == before
        finally:
            await close(engine)

    asyncio.run(check())


def test_inp07_server_parse_error_precedes_turn_acceptance(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {})
        store = SessionStore(tmp_path / "sessions.db")
        core = CoreService(Settings(), lambda state: engine, store)
        try:
            created = core.create_session(
                {
                    "client_session_id": new_id("cli"),
                    "subject": "physics",
                    "mode": "guided",
                    "origin": {"kind": "ask", "ref": None},
                }
            )
            sid = created["session_id"]
            body = {
                "client_message_id": new_id("cli"),
                "intent": "board_line",
                "content": [{"type": "board_line", "step_id": new_id("stp"), "latex": "s=("}],
            }
            with pytest.raises(ApiError) as refused:
                await core.preflight_input(sid, body)
            assert refused.value.code == "validation_failed"
            assert refused.value.details["input_error"] == "PARSE_REJECTED"
            assert refused.value.details["line"] == 1 and refused.value.details["position"] == 3
            assert core.entry(sid).task is None and engine.turn_number == 0
        finally:
            await close(engine)

    asyncio.run(check())


def inp14_normalise_before_scan() -> None:
    assert normalise_input("\u202e</student-message>\u200b\x00e\u0301\u200d X\n") == "</student-message>é X\n"
    assert normalise_input("a\u200cb") == "a\u200cb"


def test_symbolic_coefficient_is_not_a_checked_answer(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE)]})
        try:
            prepared(engine)
            await engine.board_turn([(new_id("stp"), "s=10*f")])
            assert engine.state.board.steps[0].status == "unchecked"
            assert engine.state.board.steps[0].check_id is None
            assert not engine.state.solved
        finally:
            await close(engine)

    asyncio.run(check())


def test_http_working_is_idempotent_and_preserves_board_ids(tmp_path: Path) -> None:
    async def check() -> None:
        engine, _ = await make_engine(tmp_path, {"coach": [tutor(SAFE), tutor(SAFE)]})
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
            step_id = new_id("stp")
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
                body = {
                    "client_message_id": key,
                    "intent": "board_line",
                    "content": [{"type": "board_line", "step_id": step_id, "latex": "\u202es = 10\u200b"}],
                }
                result = await client.post(f"/v1/sessions/{sid}/turns", json=body)
                assert result.status_code == 202, result.text
                await core.entry(sid).task
                repeat = await client.post(f"/v1/sessions/{sid}/turns", json=body)
                assert repeat.json() == result.json()
                snapshot = (await client.get(f"/v1/sessions/{sid}/snapshot")).json()
                board = next(iter(snapshot["boards"].values()))
                assert len(board["steps"]) == 1
                assert board["steps"][step_id]["latex"] == "s = 10"
                assert board["steps"][step_id]["status"] == "correct"
                assert engine.turn_number == 1
                waiting_id = new_id("stp")
                engine.state.board.steps.append(BoardStep(waiting_id, 1, "", None, "student", "awaiting"))
                next_key = new_id("cli")
                next_body = {
                    "client_message_id": next_key,
                    "intent": "board_line",
                    "content": [{"type": "text", "text": "2*s = 20\ns = 10"}],
                }
                second = await client.post(
                    f"/v1/sessions/{sid}/turns", json=next_body, headers={"idempotency-key": next_key}
                )
                assert second.status_code == 202, second.text
                await core.entry(sid).task
                assert len(engine.state.board.steps) == 3
                assert engine.state.board.steps[1].step_id == waiting_id
                assert engine.state.board.steps[1].latex == "2*s = 20"
                assert all(s.status == "correct" for s in engine.state.board.steps)
                core.mock_active = lambda: True
                locked = await client.post(
                    f"/v1/sessions/{sid}/turns", json=next_body, headers={"idempotency-key": new_id("cli")}
                )
                assert locked.status_code == 423 and locked.json()["error"]["code"] == "tutor_locked"
        finally:
            await close(engine)

    asyncio.run(check())


def test_unavailable_working_checker_returns_retryable_error(tmp_path: Path) -> None:
    async def check() -> None:
        from agent_core.api.core import CoreService
        from agent_core.api.errors import ApiError
        from agent_core.store.sessions import SessionStore

        engine, _ = await make_engine(tmp_path, {})
        core = CoreService(Settings(), lambda state: engine, SessionStore(tmp_path / "unavailable.db"))
        supervisor = engine.deps.executor.supervisor
        try:
            created = core.create_session(
                {
                    "client_session_id": new_id("cli"),
                    "subject": "physics",
                    "mode": "guided",
                    "origin": {"kind": "ask", "ref": None},
                }
            )
            engine.deps.executor.supervisor = None
            with pytest.raises(ApiError) as raised:
                await core.preflight_input(
                    created["session_id"],
                    {
                        "client_message_id": new_id("cli"),
                        "intent": "board_line",
                        "content": [{"type": "text", "text": "x = 2"}],
                    },
                )
            assert raised.value.code == "worker_unavailable"
            assert raised.value.status == 503
            assert raised.value.envelope()["error"]["retryable"] is True
            assert not core.entry(created["session_id"]).task
        finally:
            await core.shutdown()
            engine.deps.executor.supervisor = supervisor
            await close(engine)

    asyncio.run(check())
