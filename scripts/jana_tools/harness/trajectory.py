"""Trajectory export and replay (OBS-10, EVL-20).

An evaluation or developer build exports a session as one JSON Lines file: a header, then in order the inputs the
engine was given, every model call (the request it sent and the reply it got) and every committed turn trace. Payloads
(inputs, requests, replies) are written only with capture `full`; a release build exports them only inside a debug
bundle the adult consented to.

Replay rebuilds the engine as the header says, feeds the same inputs, and answers each model call with the recorded
reply for that role and position. Ids the tool worker mints at run time (`chk_…`) differ between runs, so each
recorded reply has the run's ids mapped onto the replay's, by position, from the request it answered. Tools run for
real in the sandboxed worker, so a replay reproduces the gate firings and the tool calls of the recorded session, and
a failing session becomes a regression test (`compare` is empty when they match).

Every input and reply in the repository's trajectories is synthetic."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .. import REPO_ROOT

FORMAT = "jana.trajectory.1"
CHECK_ID = re.compile(r"chk_[0-9A-Za-z]{20,32}")
CHANNELS = ("dev", "eval", "release")


class ExportRefused(PermissionError):
    pass


class Recording:
    """Wraps a ScriptedProvider's step source: records each call's role, request and reply in order."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def attach(self, provider: Any) -> Any:
        inner = provider._next

        def recorded(body: dict[str, Any], role: str | None = None) -> Any:
            step = inner(body, role)
            self.calls.append({"role": role, "request": _plain(body), "step": _plain(step)})
            return step

        provider._next = recorded
        return provider


def capture_inputs(engine: Any) -> list[dict[str, Any]]:
    """Record what the engine is given through its public entry points, in order, for the trajectory."""
    inputs: list[dict[str, Any]] = []
    start_problem, start_practice, student_turn = engine.start_problem, engine.start_practice, engine.student_turn

    async def problem(statement: str, *args: Any, source: str = "student_text", **kw: Any) -> Any:
        inputs.append({"call": "start_problem", "args": {"statement": statement, "source": source}})
        return await start_problem(statement, *args, source=source, **kw)

    async def practice(item: dict[str, Any], part_id: str = "a", *args: Any, **kw: Any) -> Any:
        inputs.append({"call": "start_practice", "args": {"item": _plain(item), "part_id": part_id}})
        return await start_practice(item, part_id, *args, **kw)

    async def turn(text: str, *args: Any, stuck: bool = False, **kw: Any) -> Any:
        inputs.append({"call": "student_turn", "args": {"text": text, "stuck": stuck}})
        return await student_turn(text, *args, stuck=stuck, **kw)

    engine.start_problem, engine.start_practice, engine.student_turn = problem, practice, turn
    return inputs


def live_script(url: str, key: str) -> Callable[[str, list[dict[str, Any]], dict[str, Any]], dict[str, Any]]:
    """A ScriptedProvider script that sends each request to a live OpenAI-compatible server (for recording)."""
    import httpx

    def call(model: str, messages: list[dict[str, Any]], body: dict[str, Any]) -> dict[str, Any]:
        request = {k: v for k, v in body.items() if not k.startswith("_")} | {"stream": False}
        reply = httpx.post(f"{url}/v1/chat/completions", json=request, headers={"Authorization": f"Bearer {key}"},
                           timeout=600)  # fmt: skip
        reply.raise_for_status()
        return {"reply": reply.json()}

    return call


def _plain(value: Any) -> Any:
    return json.loads(json.dumps(value, default=str))


def export(path: Path, header: dict[str, Any], inputs: list[dict[str, Any]], recording: Recording,
           traces: list[dict[str, Any]], *, channel: str = "dev", capture: str = "full",
           debug_bundle_consent: bool = False) -> Path:  # fmt: skip
    """Write one session's trajectory. A release build writes payloads only into a consented debug bundle."""
    if channel not in CHANNELS:
        raise ValueError(f"unknown build channel {channel}")
    payloads = capture == "full"
    if channel == "release" and payloads and not debug_bundle_consent:
        raise ExportRefused("a release build exports payloads only in a debug bundle with adult consent (OBS-10)")
    lines: list[dict[str, Any]] = [{"type": "session", "format": FORMAT, "channel": channel, "capture": capture,
                                    "debug_bundle": channel == "release", **header}]  # fmt: skip
    if payloads:
        lines += [{"type": "input", "seq": n, **i} for n, i in enumerate(inputs)]
        lines += [{"type": "model", "seq": n, **c} for n, c in enumerate(recording.calls)]
    lines += [{"type": "trace", "record": t} for t in traces]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines))
    return path


def load(path: Path) -> dict[str, Any]:
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    header = next(line for line in lines if line["type"] == "session")
    if header.get("format") != FORMAT:
        raise ValueError(f"{path.name}: not a trajectory")
    return {"header": header, "inputs": [line for line in lines if line["type"] == "input"],
            "calls": [line for line in lines if line["type"] == "model"],
            "traces": [line["record"] for line in lines if line["type"] == "trace"]}  # fmt: skip


def _replay_script(calls: list[dict[str, Any]]) -> Callable[..., Any]:
    """Per role, the recorded replies in order, with the recorded run's check ids mapped onto this run's."""
    queues: dict[str, list[dict[str, Any]]] = {}
    for call in calls:
        queues.setdefault(str(call["role"]), []).append(call)
    ids: dict[str, str] = {}

    def next_step(body: dict[str, Any], role: str | None) -> dict[str, Any]:
        queue = queues.get(str(role), [])
        if not queue:
            raise LookupError(f"the trajectory has no more recorded replies for role {role}")
        call = queue.pop(0)
        old = list(dict.fromkeys(CHECK_ID.findall(json.dumps(call["request"]["messages"]))))
        new = list(dict.fromkeys(CHECK_ID.findall(json.dumps(body["messages"]))))
        ids.update({o: n for o, n in zip(old, new, strict=False) if o not in ids})
        text = json.dumps(call["step"])
        for o, n in ids.items():
            text = text.replace(o, n)
        return dict(json.loads(text))

    return next_step


async def replay(trajectory: dict[str, Any], content_root: Path | None = None,
                 skills_root: Path | None = None) -> list[dict[str, Any]]:  # fmt: skip
    """Run the recorded session again with the recorded model outputs; returns the replay's turn traces."""
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.scripted import ScriptedProvider
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    header = trajectory["header"]
    if not trajectory["calls"] and trajectory["traces"]:
        raise ValueError("this trajectory carries no payloads (capture hashes): it cannot be replayed")
    next_step = _replay_script(trajectory["calls"])
    provider = ScriptedProvider({}, kind="local", installed_models=["qwen3-vl-8b", "gemma-4-12b"])

    def replayed(body: dict[str, Any], role: str | None = None) -> dict[str, Any]:
        provider.requests.append(body)
        return next_step(body, role)

    provider._next = replayed  # type: ignore[method-assign]
    # A long handshake allowance: an evaluation machine may be busy; the tools must be offered for the run to count.
    # The engine replays at the stage it was recorded on (`stage` in the header; S1 before the header carried it).
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0,
                        build_stage=header.get("stage", "S1"))  # fmt: skip
    with tempfile.TemporaryDirectory() as scratch:
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=Path(scratch) / "w"), settings)
        await supervisor.start()

        async def no_sleep(_: float) -> None:
            return None

        state = SessionState(new_id("ses"), subject=header["subject"], level=header["level"], mode=header["mode"],
                             hardware_class=header["hardware_class"])  # fmt: skip
        engine = assemble({"local": provider}, settings, state, content_root or REPO_ROOT / "content" / "agent",
                          skills_root or REPO_ROOT / "skills", Path(scratch) / "spill", supervisor, sleep=no_sleep,
                          session_date=header.get("session_date", "2026-01-01"))  # fmt: skip
        try:
            for step in trajectory["inputs"]:
                call, args = step["call"], step["args"]
                if call == "start_problem":
                    await engine.start_problem(args["statement"], source=args.get("source", "student_text"))
                elif call == "start_practice":
                    await engine.start_practice(args["item"], args.get("part_id", "a"))
                else:
                    await engine.student_turn(args["text"], stuck=bool(args.get("stuck", False)))
        finally:
            await supervisor.close()
        return list(engine.traces)


def signature(trace: dict[str, Any]) -> dict[str, Any]:
    """What a replay must reproduce of one turn: its status, gate firings, tool calls and delivered skills."""
    return {
        "status": trace["status"],
        "gates": [(g["gate"], g["fired"], g.get("outcome"), g.get("nudges")) for g in trace.get("gates", [])],
        "tools": [(c["name"], c["status"]) for c in trace.get("tool_calls", [])],
        "skills": [(s["name"], s["version"], s["sha256"], s["delivery"]) for s in trace.get("skills", [])],
    }


def compare(recorded: list[dict[str, Any]], replayed: list[dict[str, Any]]) -> list[str]:
    """Differences between a recorded session and its replay, turn by turn (empty when the replay reproduces it)."""
    out = []
    if len(recorded) != len(replayed):
        out.append(f"{len(recorded)} recorded turns, {len(replayed)} replayed")
    for n, (a, b) in enumerate(zip(recorded, replayed, strict=False), 1):
        sa, sb = signature(a), signature(b)
        out += [f"turn {n}: {key} {sa[key]} != {sb[key]}" for key in sa if sa[key] != sb[key]]
    return out


def run_replay(path: Path) -> list[str]:
    trajectory = load(path)
    return compare(trajectory["traces"], asyncio.run(replay(trajectory)))
