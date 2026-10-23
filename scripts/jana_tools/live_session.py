"""A guided solve on the S1 topic against a real local model (M4 exit evidence; device lab and nightly only).

`python -m jana_tools live-session <url> <key> <model> <out dir> [runs]` drives the shipped engine (assembled as the app
assembles it) with the sandboxed worker and llama-server, and writes each run's turns, board and traces. The problem
and the student's lines are synthetic."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from . import REPO_ROOT

STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
STUDENT = ["I'm stuck", "I don't know where to start", "v^2 = u^2 + 2as, so 0 = 14^2 - 2(9.8)s", "s = 10 m"]


async def open_engine(url: str, key: str, model: str, out: Path, subject: str = "physics",
                      hardware_class: str = "mid") -> tuple[Any, Any, Any, Any]:  # fmt: skip
    """The shipped engine, assembled as the app assembles it, on one local model: (engine, state, supervisor,
    provider). `hardware_class` picks the output caps, prompt profile and iteration budget the app would use on that
    class of machine. The caller closes the supervisor and the provider."""
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.llama import LlamaServerProvider
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    settings = Settings(worker_pool_size=2, worker_respawn_backoff_s=(0.0,))
    supervisor = WorkerSupervisor(process_factory(settings, scratch_root=out / "scratch"), settings)
    await supervisor.start()
    provider = LlamaServerProvider(url, key)

    def only(data: dict[str, Any]) -> None:
        for tier in data["tiers"]:
            data["tiers"][tier] = [f"local:{model}"]

    state = SessionState(new_id("ses"), subject=subject, level="O", hardware_class=hardware_class)
    engine = assemble({"local": provider}, settings, state, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills",
                      out / "spill", supervisor, router_overrides=only, session_date="2026-10-09")  # fmt: skip
    return engine, state, supervisor, provider


async def run_once(url: str, key: str, model: str, out: Path) -> dict[str, Any]:
    engine, state, supervisor, provider = await open_engine(url, key, model, out)
    turns = []
    try:
        for text in [None, *STUDENT]:
            started = time.monotonic()
            result = await (engine.start_problem(STATEMENT) if text is None else engine.student_turn(text))
            turns.append({"student": text, "status": result.status, "stop_reason": result.stop_reason,
                          "degraded_reason": result.degraded_reason, "seconds": round(time.monotonic() - started, 1),
                          "shown": engine.events.student_text(result.turn_id)})  # fmt: skip
            if state.solved:
                break
    finally:
        await supervisor.close()
        await provider.close()
    board = [
        {"owner": s.owner, "status": s.status, "latex": s.latex, "check_id": s.check_id} for s in state.board.steps
    ]
    summary = {"model": model, "plan_verified": state.plan is not None, "solved": state.solved, "turns": turns,
               "board": board,
               "board_numbers_checked": all(s["check_id"] or s["owner"] == "student" for s in board)}  # fmt: skip
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=1))
    (out / "traces.json").write_text(json.dumps(engine.traces, indent=1))
    return summary


def run(url: str, key: str, model: str, out: Path, runs: int = 1) -> list[dict[str, Any]]:
    return [asyncio.run(run_once(url, key, model, out / f"run{n}")) for n in range(runs)]
