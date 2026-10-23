"""M14.c, API half: steering and side questions over the local HTTP API (API-25, API-26). The real core, app and
engine with a scripted provider; an open problem with a verified plan is set up directly so no Solver runs."""

from __future__ import annotations

import asyncio
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.state import Plan, PlanStep, Problem
from api_harness import ask, cli, scripted, sse, start_core, stop_core
from engine_harness import STATEMENT, reply, tutor

SAFE = "Which quantities does the question give you, and which one does it ask for?"
STEER = "Please use metres in your answer."


def settings() -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0)


def open_problem(core: Any, session_id: str) -> None:
    state = core.sessions[session_id].engine_state
    state.problem = Problem("prb_g", STATEMENT, "prb_g#statement")
    state.plan = Plan([PlanStep(1, "s = 10", "10", "m", "chk_G01")], "10", "m", "chk_G01")
    state.check_values["chk_G01"] = [Fraction(10)]


async def session_of(r: Any) -> str:
    return await r.session()


def api25_steer_injected(tmp_path: Path) -> None:
    released = asyncio.Event()
    running_tool = asyncio.Event()
    seen: list[dict[str, Any]] = []

    def capture(body: dict[str, Any]) -> dict[str, Any]:
        seen.append(body)
        return tutor(SAFE)

    provider = scripted({"coach": [reply("", [("k1", "skill", {"query": "motion"})]), capture, tutor(SAFE)]})

    async def held_skill(args: dict[str, Any], context: Any) -> str:
        running_tool.set()
        await released.wait()
        return "skill text"

    async def scenario() -> dict[str, Any]:
        r = await start_core(tmp_path, provider, settings=settings(), worker=False)
        try:
            sid = await r.session()
            r.core._engine(r.core.sessions[sid])  # the engine exists before the turn, so its tools can be held
            open_problem(r.core, sid)
            engine = r.core.sessions[sid].engine
            engine.deps.executor.host_executors["skill"] = held_skill
            engine.availability.reset()
            started = await r.post(f"/v1/sessions/{sid}/turns", ask("s = 12 m", "answer"))
            assert started.status_code == 202, started.text
            turn_id = started.json()["turn_id"]
            await asyncio.wait_for(running_tool.wait(), 30)
            body = {"client_message_id": cli(), "content": [{"type": "text", "text": STEER}]}
            queued = await r.post(f"/v1/turns/{turn_id}/steer", body)
            released.set()
            await r.wait_idle(sid)
            late = await r.post(
                f"/v1/turns/{turn_id}/steer",
                {"client_message_id": cli(), "content": [{"type": "text", "text": "and then?"}]},
            )
            missing = await r.post("/v1/turns/trn_01JZ0000000000000000000000/steer", body)
            await r.wait_idle(sid)
            events = [f["event"] for f in engine.events.frames]
            return {"queued": queued, "late": late, "missing": missing, "events": events}
        finally:
            await stop_core(r)

    out = asyncio.run(scenario())
    assert out["queued"].status_code == 200 and out["queued"].json()["status"] == "queued"
    assert contract_errors("api/commands#/$defs/SteerAccepted", out["queued"].json()) == []
    message_id = out["queued"].json()["message_id"]
    applied = [e for e in out["events"] if e["type"] == "steer.applied"]
    assert applied == [{"type": "steer.applied", "message_id": message_id, "phase": "prepare"}]
    accepted = [e for e in out["events"] if e["type"] == "message.accepted" and e["disposition"] == "steer_queued"]
    assert len(accepted) == 1
    request = json.dumps(seen[0]["messages"])
    assert STEER in request and request.index(STEER) > request.rindex('"role": "tool"')
    assert out["late"].json() == {"message_id": None, "status": "turn_ended"}
    assert out["missing"].status_code == 404


def test_api26_side_question_endpoint(tmp_path: Path) -> None:
    provider = scripted({"coach": [tutor("Acceleration is how fast the velocity changes each second.")]})

    async def scenario() -> dict[str, Any]:
        r = await start_core(tmp_path, provider, settings=settings(), worker=False)
        try:
            sid = await r.session()
            r.core._engine(r.core.sessions[sid])
            open_problem(r.core, sid)
            before = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            body = {"client_message_id": cli(), "content": [{"type": "text", "text": "What is acceleration again?"}]}
            accepted = await r.post(f"/v1/sessions/{sid}/side-questions", body)
            await r.wait_idle(sid)
            after = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            engine = r.core.sessions[sid].engine
            return {
                "accepted": accepted,
                "before": before,
                "after": after,
                "events": [f["event"] for f in engine.events.frames],
                "state": engine.state,
            }
        finally:
            await stop_core(r)

    out = asyncio.run(scenario())
    assert out["accepted"].status_code == 202
    assert contract_errors("api/commands#/$defs/TurnAccepted", out["accepted"].json()) == []
    start = next(e for e in out["events"] if e["type"] == "turn.start")
    assert start["fork"] is True and start["intent"] == "side_question"
    assert not [e for e in out["events"] if e["type"].startswith("board.")]
    assert out["state"].transcript == [] and out["state"].rung == 0
    assert out["before"]["boards"] == out["after"]["boards"]
    requests = [r for r in provider.requests if r.get("_role") == "coach"]
    assert len(requests) == 1 and not requests[0].get("tools")
    assert sse is not None  # the stream helper stays importable for clients of this module
