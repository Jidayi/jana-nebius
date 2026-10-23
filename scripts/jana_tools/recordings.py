"""Recorded core streams for the client's regression fixtures (UIA-28, UIA-30) and the snapshot equivalence test
(UIA-02): S1 scenarios run through the shipped core (API service, engine, sandboxed worker) with the development
script as the model. Each recording holds every sequenced envelope and the session snapshot after each one.

    python -m jana_tools recordings --write

Ids and timestamps differ per run, so recordings are refreshed by this command rather than checked for staleness;
the client tests validate every recorded payload against the contracts, so a contract change still fails CI."""

from __future__ import annotations

import asyncio
import copy
import json
import tempfile
from pathlib import Path
from typing import Any

from . import REPO_ROOT

OUT = REPO_ROOT / "evals" / "recordings"
STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
SCENARIOS: dict[str, list[tuple[str, str]]] = {
    "s1_guided_solve": [(STATEMENT, "ask"), ("I'm stuck", "stuck"), ("s = 20 m", "answer"), ("s = 10 m", "answer")],
    "s1_unknown_problem": [("Find the area of a circle of radius 3 cm.", "ask")],
}


async def record(name: str, turns: list[tuple[str, str]], data_dir: Path) -> dict[str, Any]:
    from agent_core.api.core import CoreService
    from agent_core.config import Settings
    from agent_core.engine.assembly import AppRuntime, start_worker_pool
    from agent_core.engine.devscript import dev_scripted_provider
    from agent_core.engine.events import new_id
    from agent_core.store.sessions import SessionStore

    # The committed recordings are the S1 dialogue of the development script; they are regenerated at S1.
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), build_stage="S1")
    runtime = AppRuntime(settings, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", data_dir)
    runtime.supervisor = await start_worker_pool(settings, data_dir / "scratch")
    runtime.providers["local"] = dev_scripted_provider()
    core = CoreService(settings, runtime.engine, SessionStore(data_dir / "sessions"))
    core.closers.append(runtime.close)
    core.readiness = "ready"
    session = core.create_session({"client_session_id": new_id("cli"), "mode": "guided", "subject": "physics",
                                   "level": "O", "origin": {"kind": "ask", "ref": None}})  # fmt: skip
    session_id = session["session_id"]
    frames: list[dict[str, Any]] = []
    snapshots: list[dict[str, Any]] = [core.snapshot(session_id)]
    sends: list[dict[str, Any]] = []
    entry = core.sessions[session_id]
    original = core._on_event

    def capture(target: Any, envelope: dict[str, Any]) -> None:
        original(target, envelope)
        if target is entry:
            frames.append(copy.deepcopy(envelope))
            snapshots.append(copy.deepcopy(entry.state))

    core._on_event = capture  # type: ignore[method-assign]
    try:
        for text, intent in turns:
            body = {"client_message_id": new_id("cli"), "intent": intent, "content": [{"type": "text", "text": text}]}
            sends.append({"after_seq": entry.state["cursor"]["seq"], "body": body})
            core.start_turn(session_id, body)
            assert entry.task is not None
            await entry.task
    finally:
        await core.shutdown()
    return {"name": name, "session_id": session_id, "sends": sends, "frames": frames, "snapshots": snapshots}


def write(out: Path = OUT) -> list[Path]:
    out.mkdir(parents=True, exist_ok=True)
    written = []
    for name, turns in SCENARIOS.items():
        with tempfile.TemporaryDirectory() as scratch:
            recording = asyncio.run(record(name, turns, Path(scratch)))
        path = out / f"{name}.json"
        path.write_text(json.dumps(recording, ensure_ascii=False, indent=1) + "\n")
        written.append(path)
    return written
