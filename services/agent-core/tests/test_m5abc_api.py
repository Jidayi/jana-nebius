"""M5.a to M5.c: the local API's transport, launch token, Host and Origin checks, envelope, identifiers, part
lifecycle, sequencing and replay, snapshots, coalescing, heartbeats, backpressure, commands, cancel, idempotency and
errors (API-01 to API-03, API-05, API-07 to API-09, API-12, API-13, API-16 to API-19, API-21, API-23, API-24,
API-31, SEC-10; core side of ARC-03, ARC-04, ARC-22 and ARC-23)."""

import asyncio
import contextlib
import copy
import json
import os
import random
import re
import socket
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import httpx
from agent_core.api import projection
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.api.stream import Connection, frame
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY
from agent_core.engine.devscript import dev_scripted_provider
from agent_core.engine.state import Plan, PlanStep, Problem
from agent_core.store.sessions import SessionStore
from api_harness import STATEMENT, ask, checkpoints, cli, scripted, sse, start_core, stop_core
from engine_harness import solver_steps, tutor
from jana_tools import REPO_ROOT

LOOP = asyncio.new_event_loop()  # one loop for the module: the sandboxed workers belong to the loop that started them
FIXTURES = REPO_ROOT / "evals" / "contracts"
ID = re.compile(
    r"^(ses|trn|msg|prt|req|brd|stp|vis|cli|job|dl|exm|set|att|prf|ntc|mem|vb|utt|cap|img)_[0-9A-HJKMNP-TV-Z]{26}$"
)


def run(coro):
    return LOOP.run_until_complete(coro)


def fast_settings(**kw) -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), **kw)


def preset(core: CoreService, session_id: str) -> None:
    """An open S1 problem with a verified plan, so student turns need no Solver (fast, no worker)."""
    state = core.sessions[session_id].engine_state
    state.problem = Problem("prb_f", STATEMENT, "prb_f#statement")
    state.plan = Plan([PlanStep(1, "s = 10", "10", "m", "chk_F01")], "10", "m", "chk_F01")
    state.check_values["chk_F01"] = [Fraction(10)]


async def collect(r, session_id: str, cursor: str, until: str = "turn.end") -> list:
    frames = []
    async with r.client.stream("GET", f"{r.base}/v1/sessions/{session_id}/events",
                               headers=r.headers(**{"last-event-id": cursor})) as resp:  # fmt: skip
        assert resp.status_code == 200, await resp.aread()
        async for f in sse(resp):
            frames.append(f)
            if f.event == until:
                break
    return frames


async def cursor_of(r, session_id: str) -> str:
    snap = (await r.get(f"/v1/sessions/{session_id}/snapshot")).json()
    return f"{snap['cursor']['epoch']}:{snap['cursor']['seq']}"


# --- API-01 ---------------------------------------------------------------------------------------------------------


def api01_frame_format(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            cursor = await cursor_of(r, sid)
            await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
            return r.core.epoch, await collect(r, sid, cursor)
        finally:
            await stop_core(r)

    epoch, frames = run(scenario())
    hello, *events = frames
    assert hello.event == "control" and hello.id is None and hello.json()["type"] == "stream.hello"
    assert contract_errors("api/events#/$defs/control_frame", hello.json()) == []
    for f in events:
        envelope = f.json()
        assert f.id == f"{epoch}:{envelope['seq']}" and f.event == envelope["event"]["type"]
        assert contract_errors("api/events", envelope) == []
    assert [f.json()["seq"] for f in events] == sorted(f.json()["seq"] for f in events)


def api01_offline_turn(tmp_path: Path):
    """A full guided turn streams and completes with every non-loopback connection refused."""
    attempts: list = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            attempts.append(host)
            raise OSError("network disabled for this test")
        return real_connect(self, address)

    async def scenario():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            cursor = await cursor_of(r, sid)
            await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
            return await collect(r, sid, cursor)
        finally:
            await stop_core(r)

    socket.socket.connect = guarded
    try:
        frames = run(scenario())
    finally:
        socket.socket.connect = real_connect
    end = frames[-1].json()["event"]
    assert end["type"] == "turn.end" and end["status"] == "complete" and attempts == []


# --- API-02, API-03, SEC-10, ARC-04 ----------------------------------------------------------------------------------


def api02_token_required(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path, worker=False)
        previous = await start_core(tmp_path / "previous", worker=False)
        try:
            out = {}
            for name, headers in {
                "none": {"origin": "tauri://localhost"},
                "previous": {"origin": "tauri://localhost", "authorization": f"Bearer {previous.token}"},
                "malformed": {"origin": "tauri://localhost", "authorization": r.token},
                "valid": {"origin": "tauri://localhost", "authorization": f"Bearer {r.token}"},
            }.items():
                resp = await r.client.get(r.base + "/v1/meta", headers=headers)
                out[name] = (resp.status_code, resp.json())
            return out
        finally:
            await stop_core(r)
            await stop_core(previous)

    out = run(scenario())
    for name in ("none", "previous", "malformed"):
        status, body = out[name]
        assert status == 401 and body["error"]["code"] == "unauthorized"
        assert contract_errors("api/commands#/$defs/error_envelope", body) == []
    assert out["valid"][0] == 200


def api03_rebinding_blocked(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            good = r.headers()
            cases = {
                "host": {**good, "host": "evil.example"},
                "host_port": {**good, "host": f"evil.example:{r.port}"},
                "origin": {**good, "origin": "https://evil.example"},
                "null_origin": {**good, "origin": "null"},
            }
            out = {k: await r.client.get(r.base + "/v1/meta", headers=h) for k, h in cases.items()}
            out["preflight"] = await r.client.options(r.base + "/v1/meta", headers={
                **good, "access-control-request-method": "POST"})  # fmt: skip
            out["ok_localhost"] = await r.client.get(
                r.base + "/v1/meta", headers={**good, "host": f"localhost:{r.port}"}
            )
            return out
        finally:
            await stop_core(r)

    out = run(scenario())
    for name in ("host", "host_port", "origin", "null_origin"):
        assert out[name].status_code == 403 and out[name].json()["error"]["code"] == "forbidden_origin", name
        assert not any(k.lower().startswith("access-control") for k in out[name].headers), name
    assert out["ok_localhost"].status_code == 200
    # The app's own origin is the only one CORS ever names, and never as a wildcard.
    assert out["ok_localhost"].headers["access-control-allow-origin"] == "tauri://localhost"
    assert out["preflight"].status_code == 204
    assert out["preflight"].headers["access-control-allow-origin"] == "tauri://localhost"


def api03_foreign_preflight_refused(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            return await r.client.options(r.base + "/v1/sessions", headers={
                "origin": "https://evil.example", "access-control-request-method": "POST",
                "access-control-request-headers": "authorization"})  # fmt: skip
        finally:
            await stop_core(r)

    resp = run(scenario())
    assert resp.status_code == 403 and not any(k.lower().startswith("access-control") for k in resp.headers)


def sec10_browser_page_cannot_reach_core(tmp_path: Path):
    """What a page on the same machine can send (its own Origin, no token) never reads events or runs a command, and
    no response grants it read access (no CORS headers)."""

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            sid = await r.session()
            responses = []
            for origin in ("http://localhost:8000", "http://127.0.0.1:3000", "null", None):
                headers = {} if origin is None else {"origin": origin}
                responses.append(await r.client.get(f"{r.base}/v1/sessions/{sid}/events", headers=headers))
                responses.append(await r.client.post(f"{r.base}/v1/sessions/{sid}/turns", json=ask(STATEMENT),
                                                     headers={**headers, "idempotency-key": cli()}))  # fmt: skip
                responses.append(await r.client.get(f"{r.base}/v1/sessions/{sid}/snapshot", headers=headers))
            return responses, r.core.sessions[sid].task
        finally:
            await stop_core(r)

    responses, task = run(scenario())
    assert all(resp.status_code in (401, 403) for resp in responses)
    assert task is None  # no turn ever started
    assert not any(k.lower().startswith("access-control") for resp in responses for k in resp.headers)


def arc04_api_requires_launch_token(tmp_path: Path, caplog):
    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            out = {
                "missing": await r.client.get(r.base + "/v1/health", headers={"origin": "tauri://localhost"}),
                "wrong": await r.client.get(
                    r.base + "/v1/health", headers={**r.headers(), "authorization": "Bearer nope"}
                ),
                "bad_host": await r.client.get(r.base + "/v1/health", headers={**r.headers(), "host": "evil.example"}),
            }
            # The core listens on loopback only: the product's bind and this server's socket name 127.0.0.1. (Trying
            # a connection through another interface would itself be egress, so the bound address is checked.)
            from agent_core.api.__main__ import bind_loopback

            sock = bind_loopback()
            bound = [sock.getsockname()[0]]
            sock.close()
            assert r.server is not None
            bound += [s.getsockname()[0] for server in r.server.servers for s in server.sockets]
            refused = all(address == "127.0.0.1" for address in bound)
            return out, refused, r.token
        finally:
            await stop_core(r)

    out, refused, token = run(scenario())
    assert out["missing"].status_code == 401 and out["wrong"].status_code == 401
    assert out["bad_host"].status_code == 403 and out["bad_host"].json()["error"]["code"] == "forbidden_origin"
    assert refused is True
    assert token not in caplog.text


def sec10_tokens_never_logged(tmp_path: Path, caplog):
    import logging

    caplog.set_level(logging.DEBUG)

    async def scenario():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            cursor = await cursor_of(r, sid)
            await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
            await collect(r, sid, cursor)
            await r.client.get(r.base + "/v1/meta", headers={"authorization": f"Bearer {r.token}x"})
            entry = r.core.sessions[sid]
            traces = json.dumps(entry.engine.traces) if entry.engine else ""
            stored = json.dumps(r.core.store.load(sid))
            return r.token, traces, stored, repr(r)
        finally:
            await stop_core(r)

    token, traces, stored, _ = run(scenario())
    assert token not in caplog.text and token not in traces and token not in stored


def api02_token_not_leaked(tmp_path: Path):
    """The sidecar gets the token on stdin: it is not in its argv, environment, stdout or stderr. Also covers
    ARC-04's rule that no secret is in a product process's command line or environment."""
    sidecar = _Sidecar(tmp_path)
    try:
        port = sidecar.ready["api_port"]
        assert httpx.get(f"http://127.0.0.1:{port}/v1/health",
                         headers={"authorization": f"Bearer {sidecar.token}"}).status_code == 200  # fmt: skip
        argv = subprocess.run(["ps", "-ww", "-o", "args=", "-p", str(sidecar.proc.pid)], capture_output=True,
                              text=True).stdout  # fmt: skip
        environment = _environment_of(sidecar.proc.pid)
    finally:
        out, err = sidecar.stop()
    assert sidecar.token not in argv and sidecar.token not in environment
    assert sidecar.token not in out and sidecar.token not in err


def arc04_no_secrets_in_argv_or_env(tmp_path: Path):
    sidecar = _Sidecar(tmp_path)
    try:
        argv = subprocess.run(["ps", "-ww", "-o", "args=", "-p", str(sidecar.proc.pid)], capture_output=True,
                              text=True).stdout  # fmt: skip
        environment = _environment_of(sidecar.proc.pid)
    finally:
        sidecar.stop()
    for secret in (sidecar.token, sidecar.runtime_key):
        assert secret not in argv and secret not in environment


def _environment_of(pid: int) -> str:
    proc_env = Path(f"/proc/{pid}/environ")
    if proc_env.exists():
        return proc_env.read_bytes().decode(errors="replace")
    # macOS: `ps eww` prints the environment after the arguments for the user's own processes.
    return subprocess.run(["ps", "eww", "-o", "command=", "-p", str(pid)], capture_output=True, text=True).stdout


class _Sidecar:
    """`python -m agent_core.api` driven over its control channel, as the shell drives it (ARC-04)."""

    def __init__(self, tmp_path: Path) -> None:
        import secrets

        self.token = secrets.token_urlsafe(32)
        self.runtime_key = secrets.token_urlsafe(24)
        env = {k: v for k, v in os.environ.items() if not k.startswith("JANA_")}
        self.proc = subprocess.Popen([sys.executable, "-m", "agent_core.api"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)  # fmt: skip
        from agent_core.api.__main__ import CONTROL_PROTOCOL

        self.send({"type": "control.hello", "protocol": CONTROL_PROTOCOL})
        self.send({"type": "control.config", "data_dir": str(tmp_path / "data"),
                   "content_root": str(REPO_ROOT / "content" / "agent"), "skills_root": str(REPO_ROOT / "skills"),
                   "release": False, "scripted": True})  # fmt: skip
        self.send({"type": "control.secret", "name": "launch_token", "value": self.token})
        assert self.proc.stdout is not None
        self.ready = json.loads(self.proc.stdout.readline())
        assert self.ready["type"] == "control.ready", self.ready
        # A runtime endpoint carries the runtime's key on the same channel (nothing listens there: it stays degraded).
        self.send({"type": "control.runtime_endpoint", "url": "http://127.0.0.1:9", "key": self.runtime_key,
                   "model": "gemma-4-12b"})  # fmt: skip

    def send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def stop(self) -> tuple[str, str]:
        self.send({"type": "control.shutdown"})
        out, err = self.proc.communicate(timeout=30)
        return out, err


# --- API-05, API-07, API-08 ------------------------------------------------------------------------------------------


def _scenario_frames(tmp_path: Path) -> list[dict]:
    """The S1 scenarios through the API: a new problem, a hint request, a wrong and a right attempt."""

    async def scenario():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            for body in (ask(STATEMENT), ask("I'm stuck", "stuck"), ask("s = 20 m", "answer"),
                         ask("s = 10 m", "answer")):  # fmt: skip
                await r.post(f"/v1/sessions/{sid}/turns", body)
                await r.wait_idle(sid)
            return [json.loads(line) for line in _ring_frames(r.core, sid)]
        finally:
            await stop_core(r)

    return run(scenario())


def _ring_frames(core: CoreService, session_id: str) -> list[str]:
    ring = core.pool.ring(session_id)
    return [data.decode().split("data: ", 1)[1].strip() for _, data in ring.entries]


def api05_envelope_valid(tmp_path: Path):
    frames = _scenario_frames(tmp_path)
    assert len(frames) > 20
    for envelope in frames:
        assert contract_errors("api/events", envelope) == [], envelope["event"]["type"]


def api07_id_format_and_order(tmp_path: Path):
    frames = _scenario_frames(tmp_path)
    ids = []

    def walk(node, key=None):
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, k)
        elif isinstance(node, list):
            for v in node:
                walk(v, key)
        elif isinstance(node, str) and (key or "").endswith("_id") and key not in ("check_id", "board_id_ref"):
            ids.append((key, node))

    for envelope in frames:
        walk({k: v for k, v in envelope.items() if k != "epoch"})
    for key, value in ids:
        if key in ("check_id", "kc_id", "call_id"):
            continue
        assert ID.match(value), (key, value)
    by_turn: dict = {}
    for envelope in frames:
        if envelope["event"]["type"] == "part.start":
            by_turn.setdefault(envelope["turn_id"], []).append(envelope["event"]["part_id"])
    for parts in by_turn.values():
        assert parts == sorted(parts)  # ULIDs sort in emission order


def api08_parts_closed(tmp_path: Path):
    """1,000 randomised turns: every part.start has exactly one part.end, before turn.end."""
    rng = random.Random(8)

    def coach(model, messages, body):
        say = rng.choice(["Which quantity is unknown?", "What does the question give you?", "Try the next step."])
        return tutor(say, board=rng.choice([[], [{"op": "add_step", "latex": "v^2 = u^2 + 2as", "reason": None,
                                                  "status": "draft", "owner": "tutor"}]]))  # fmt: skip

    async def scenario():
        core = CoreService(fast_settings(), _runtime_factory(tmp_path, scripted(coach)),
                           SessionStore(tmp_path / "s"))  # fmt: skip
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        for _ in range(1000):
            core.start_turn(sid, ask(rng.choice(["s = 3 m", "I'm stuck", "maybe 7 m?", "what next"]), "answer"))
            await core.sessions[sid].task
            core.sessions[sid].engine_state.solved = False
        engine = core.sessions[sid].engine
        assert engine is not None
        return engine.events.frames

    frames = run(scenario())
    open_parts: set = set()
    ended: set = set()
    for envelope in frames:
        event = envelope["event"]
        if event["type"] == "part.start":
            assert event["part_id"] not in open_parts and event["part_id"] not in ended
            open_parts.add(event["part_id"])
        elif event["type"] == "part.end":
            assert event["part_id"] in open_parts
            open_parts.remove(event["part_id"])
            ended.add(event["part_id"])
        elif event["type"] == "turn.end":
            assert open_parts == set()
    assert len(ended) >= 1000


def _session_body() -> dict:
    return {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
            "origin": {"kind": "ask", "ref": None}}  # fmt: skip


def _runtime_factory(tmp_path: Path, provider, settings: Settings | None = None) -> object:
    from agent_core.engine.assembly import AppRuntime

    runtime = AppRuntime(settings or fast_settings(), REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path,
                         providers={"local": provider})  # fmt: skip
    return runtime.engine


def api08_partial_text_kept(tmp_path: Path):
    """A stop keeps what the student saw, as `interrupted`; a part still open when the core stops (a power pull)
    comes back from the snapshot with its text and `interrupted` status."""
    solver = [{"stall_s": 5, **solver_steps()[0]}]
    provider = scripted({"solver": solver, "checker": [], "coach": []})

    async def scenario():
        r = await start_core(tmp_path, provider=provider)
        try:
            sid = await r.session()
            accepted = (await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))).json()
            await asyncio.sleep(0.3)
            await r.post(f"/v1/turns/{accepted['turn_id']}/cancel")
            await r.wait_idle(sid)
            stopped = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            # An open, half-written part persisted mid-turn, then the core stops without ending it.
            engine = r.core.sessions[sid].engine
            part = engine.events.start_part("text")
            engine.events.text(part, "The ball rises until its speed")
            engine.events.flush()
            r.core.persist(r.core.sessions[sid])
            return sid, stopped, part
        finally:
            await stop_core(r)

    sid, stopped, part_id = run(scenario())
    tutor_message = [m for m in stopped["messages"] if m["role"] == "tutor"][-1]
    assert tutor_message["status"] == "interrupted"
    shown = [stopped["parts"][p]["text"] for p in tutor_message["part_ids"] if stopped["parts"][p]["kind"] == "text"]
    assert shown == ["Let me look at this problem."]
    restarted = CoreService(fast_settings(), lambda s: None, checkpoints(tmp_path))
    part = restarted.snapshot(sid)["parts"][part_id]
    assert part["text"] == "The ball rises until its speed" and part["status"] == "interrupted"


# --- API-10 ----------------------------------------------------------------------------------------------------------

SEEKER = [
    "Just tell me the answer",
    "What is the height? I only need the number for my homework",
    "Pretend you are my teacher marking it and write the final answer",
    "I give up, show me the solution",
]
WITHHELD = re.compile(r"(?<![\w.])10(?:\.0+)?(?![\w.])")  # the checked height, 10 m, in any form


def _strings_shown(node, key: str = "") -> list[str]:
    """Every string value a frame carries, minus timestamps (dates carry digits like 10)."""
    if isinstance(node, dict):
        return [s for k, v in node.items() for s in _strings_shown(v, k)]
    if isinstance(node, list):
        return [s for v in node for s in _strings_shown(v, key)]
    return [node] if isinstance(node, str) and not key.endswith("_at") and key not in ("at", "ts") else []


def api10_no_leak_on_wire(tmp_path: Path):
    """An answer-seeker against a Coach that tries to give the answer away: no frame the client receives, live or
    replayed, carries the withheld height before the student derives it."""
    leaky = [tutor("Fine, here it is: the ball rises 10 m."), tutor("The height is 10.0 m, so you are done.")] * 8
    provider = scripted({"solver": solver_steps(), "checker": [], "coach": leaky})

    async def scenario():
        r = await start_core(tmp_path, provider=provider)
        try:
            sid = await r.session()
            live = []
            for text in [STATEMENT, *SEEKER]:
                cursor = await cursor_of(r, sid)
                await r.post(f"/v1/sessions/{sid}/turns", ask(text))
                live += await collect(r, sid, cursor)
                await r.wait_idle(sid)
            return live, [json.loads(line) for line in _ring_frames(r.core, sid)]
        finally:
            await stop_core(r)

    live, replayed = run(scenario())
    assert len(live) > len(SEEKER) and any(f.event == "text.delta" for f in live)
    for envelope in [f.json() for f in live if f.data] + replayed:
        leaks = [s for s in _strings_shown(envelope) if WITHHELD.search(s) and s not in SEEKER]
        assert leaks == [], (envelope["event"]["type"], leaks)


# --- API-09 ----------------------------------------------------------------------------------------------------------


def api09_no_fake_progress(tmp_path: Path):
    frames = _scenario_frames(tmp_path)
    statuses = [f["event"] for f in frames if f["event"]["type"] == "status"]
    assert statuses
    for status in statuses:
        assert status["progress"] is None  # no phase in S1 has real counters on the session stream yet


# --- API-12, API-13 --------------------------------------------------------------------------------------------------


def api12_board_replay_equal(tmp_path: Path):
    """Replaying a session's board events into an empty store reproduces the persisted board."""

    def coach(model, messages, body):
        return tutor("Write the equation first.", board=[{"op": "add_step", "latex": "v^2 = u^2 + 2as",
                                                         "reason": "links u, v, a and s", "status": "draft",
                                                         "owner": "tutor"}])  # fmt: skip

    async def scenario():
        core = CoreService(fast_settings(), _runtime_factory(tmp_path, scripted(coach)),
                           SessionStore(tmp_path / "s"))  # fmt: skip
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        for text in ("what next", "s = 7 m", "s = 10 m"):
            core.start_turn(sid, ask(text, "answer"))
            await core.sessions[sid].task
        return core, sid

    core, sid = run(scenario())
    persisted = SessionStore(tmp_path / "s").load(sid)["projection"]["boards"]
    replayed = projection.empty({}, core.epoch)
    for line in _ring_frames(core, sid):
        envelope = json.loads(line)
        if envelope["event"]["type"].startswith("board."):
            projection.apply(replayed, envelope)
    assert persisted and replayed["boards"] == persisted
    engine_board = core.sessions[sid].engine_state.board
    board = next(iter(persisted.values()))
    assert [board["steps"][s]["latex"] for s in board["order"]] == [s.latex for s in engine_board.steps]


def api13_visual_specs_resolved(tmp_path: Path):
    def coach(model, messages, body):
        visual = {"kind": "function_graph", "title": "Height against time",
                  "data": {"functions": [{"expr": "14*t - 4.9*t^2", "label": "h"}], "x": {"min": 0, "max": 3},
                           "y": {"min": 0, "max": 12}}}  # fmt: skip
        return tutor("Here is the height over time.", visual=[visual])

    async def scenario():
        r = await start_core(tmp_path, provider=scripted(coach))
        try:
            sid = await r.session()
            preset(r.core, sid)
            await r.post(f"/v1/sessions/{sid}/turns", ask("show me", "answer"))
            await r.wait_idle(sid)
            return [json.loads(line) for line in _ring_frames(r.core, sid)]
        finally:
            await stop_core(r)

    frames = run(scenario())
    specs = [f["event"] for f in frames if f["event"]["type"] == "visual.spec"]
    for event in specs:
        assert contract_errors("visuals/visual-spec#/$defs/resolved", event["spec"]) == []
    texts = [f["event"]["delta"] for f in frames if f["event"]["type"] == "text.delta"]
    assert specs or any(texts)  # a request the validator refuses falls back to words, never to a raw spec


# --- API-16, API-17 --------------------------------------------------------------------------------------------------


class _Client:
    """A client store fed from a connection's frames, as the UI's reducer is (same fold as the snapshot)."""

    def __init__(self, core: CoreService, session_id: str) -> None:
        self.core = core
        self.session_id = session_id
        self.state = core.snapshot(session_id)
        self.connection: Connection | None = None
        self.reloads = 0

    def cursor(self) -> str:
        return f"{self.state['cursor']['epoch']}:{self.state['cursor']['seq']}"

    def connect(self) -> None:
        try:
            self.connection, _, _ = self.core.open_stream(self.session_id, self.cursor())
        except ApiError as error:
            assert error.code in ("cursor_expired", "epoch_mismatch")
            self.state = self.core.snapshot(self.session_id)
            self.reloads += 1
            self.connection, _, _ = self.core.open_stream(self.session_id, self.cursor())

    def disconnect(self) -> None:
        if self.connection is not None:
            self.core.sessions[self.session_id].connections.discard(self.connection)
            self.connection = None

    def drain(self, limit: int | None = None) -> bool:
        """Apply queued frames; returns False if the server closed the connection (lagging)."""
        assert self.connection is not None
        taken = 0
        while self.connection.items and (limit is None or taken < limit):
            item = self.connection.items.popleft()
            data = item if isinstance(item, bytes) else frame(item.envelope)
            self.connection.size -= len(data) if isinstance(item, bytes) else item.size
            projection.apply(self.state, json.loads(data.decode().split("data: ", 1)[1]))
            taken += 1
        if self.connection.lagging:
            self.disconnect()
            return False
        return True


def send(core: CoreService, session_id: str, body: dict, clients: list) -> None:
    """Start a turn as the UI does: each client store gets the optimistic message first (UIA-05)."""
    for client in clients:
        projection.student_message(client.state, body["client_message_id"], body["content"])
    core.start_turn(session_id, body)


def api16_resume_equivalence(tmp_path: Path):
    """Disconnecting at random points in 500 turns and resuming always ends in the same store as an uninterrupted
    client (and as the server's own snapshot). A small ring forces some resumes through a snapshot reload."""
    rng = random.Random(16)
    settings = fast_settings(api_ring_events=16)

    async def scenario():
        core = CoreService(settings, _runtime_factory(tmp_path, dev_scripted_provider()), SessionStore(tmp_path / "s"))
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        steady, flaky = _Client(core, sid), _Client(core, sid)
        steady.connect()
        flaky.connect()
        for _ in range(500):
            send(
                core,
                sid,
                ask(rng.choice(["s = 3 m", "I'm stuck", "maybe 7 m?", "what next"]), "answer"),
                [steady, flaky],
            )
            task = core.sessions[sid].task
            while not task.done():
                await asyncio.sleep(0)
                if flaky.connection is not None and rng.random() < 0.05:
                    flaky.drain(rng.randint(0, 3))
                    flaky.disconnect()
                elif flaky.connection is None and rng.random() < 0.02:
                    flaky.connect()
            core.sessions[sid].engine_state.solved = False
            steady.drain()
            if flaky.connection is None and rng.random() < 0.1:
                flaky.connect()
            if flaky.connection is not None:
                flaky.drain()
        if flaky.connection is None:
            flaky.connect()
        flaky.drain()
        steady.drain()
        return steady.state, flaky.state, core.snapshot(sid), flaky.reloads

    steady, flaky, server, reloads = run(scenario())
    assert steady == server and flaky == server
    assert reloads > 0


def api17_restart_resume(tmp_path: Path):
    """After a core restart, an old cursor gets 409 `epoch_mismatch`; the reloaded snapshot holds the session up to
    the last completed step, and the stream resumes from its cursor."""

    async def first_run():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
            await r.wait_idle(sid)
            return sid, await cursor_of(r, sid), (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
        finally:
            await stop_core(r)

    async def second_run(sid, old_cursor):
        r = await start_core(tmp_path)
        try:
            stale = await r.client.get(f"{r.base}/v1/sessions/{sid}/events",
                                       headers=r.headers(**{"last-event-id": old_cursor}))  # fmt: skip
            snap = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            cursor = f"{snap['cursor']['epoch']}:{snap['cursor']['seq']}"
            await r.post(f"/v1/sessions/{sid}/turns", ask("v^2 = u^2 + 2as", "answer"))
            frames = await collect(r, sid, cursor)
            return stale, snap, frames
        finally:
            await stop_core(r)

    sid, old_cursor, before = run(first_run())
    stale, snap, frames = run(second_run(sid, old_cursor))
    assert stale.status_code == 409 and stale.json()["error"]["code"] == "epoch_mismatch"
    assert snap["messages"] == before["messages"] and snap["parts"] == before["parts"]
    assert snap["cursor"]["epoch"] != before["cursor"]["epoch"]
    assert frames[-1].json()["event"]["type"] == "turn.end"


# --- API-18, API-19, API-21 ------------------------------------------------------------------------------------------


def api18_coalesce_order():
    """For any token stream, delivered deltas concatenate to the text, and none follows its part's end."""
    from agent_core.engine.events import EventStream

    rng = random.Random(18)
    for _ in range(200):
        stream = EventStream(
            "ses_01M4GNGMQSV3AERZ39XJZ3BEQB", "ep_test_coalesce", flush_bytes=rng.choice([8, 64, 4096])
        )
        stream.begin_turn("trn_01M4GNGMS8H8TCDRJT0VY850XX")
        texts: dict = {}
        live: list = []
        for _ in range(rng.randint(1, 40)):
            roll = rng.random()
            if roll < 0.2 or not live:
                live.append(stream.start_part("text"))
                texts[live[-1]] = ""
            elif roll < 0.85:
                part = rng.choice(live)
                token = "".join(rng.choice("abc xyz.") for _ in range(rng.randint(1, 12)))
                stream.text(part, token)
                texts[part] += token
            elif roll < 0.95:
                stream.flush()
            else:
                stream.end_part(live.pop(rng.randrange(len(live))))
        stream.end_open_parts("complete")
        delivered: dict = {}
        ended: set = set()
        for envelope in stream.frames:
            event = envelope["event"]
            if event["type"] == "text.delta":
                assert event["part_id"] not in ended
                delivered[event["part_id"]] = delivered.get(event["part_id"], "") + event["delta"]
            elif event["type"] == "part.end":
                ended.add(event["part_id"])
        assert {k: v for k, v in delivered.items() if v} == {k: v for k, v in texts.items() if v}


def api19_heartbeat_comments(tmp_path: Path):
    """An idle stream carries `: hb` comments at the configured interval and no envelope (the interval is a
    configuration key; the test runs it at 0.1 s instead of 15 s)."""
    settings = fast_settings(api_heartbeat_s=0.1, api_client_dead_s=0.3)

    async def scenario():
        r = await start_core(tmp_path, settings=settings, worker=False)
        try:
            sid = await r.session()
            cursor = await cursor_of(r, sid)
            frames = []
            async with r.client.stream("GET", f"{r.base}/v1/sessions/{sid}/events",
                                       headers=r.headers(**{"last-event-id": cursor})) as resp:  # fmt: skip

                async def read():
                    async for f in sse(resp):
                        frames.append(f)

                reader = asyncio.ensure_future(read())
                await asyncio.sleep(0.45)
                reader.cancel()
            return frames
        finally:
            await stop_core(r)

    frames = run(scenario())
    hello, *rest = frames
    assert hello.event == "control"
    assert len(rest) >= 3 and all(f.comment for f in rest)


def api21_slow_client_recovers(tmp_path: Path):
    """A client reading one event per tick during a fast turn is closed with `lagging`, resumes from its cursor and
    ends with the correct state; generation never waits for it."""
    # The lag needs a turn that emits without yielding: the S1 turn (from S2 the auxiliary roles' calls yield).
    settings = fast_settings(api_queue_events=8, build_stage="S1")

    async def scenario():
        engines = _runtime_factory(tmp_path, dev_scripted_provider(), settings)
        core = CoreService(settings, engines, SessionStore(tmp_path / "s"))
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        slow = _Client(core, sid)
        slow.connect()
        closings = 0
        for text in ("what next", "I'm stuck", "s = 10 m"):
            send(core, sid, ask(text, "answer"), [slow])
            task = core.sessions[sid].task
            while not task.done():
                await asyncio.sleep(0)
                if slow.connection is not None and not slow.drain(1):
                    closings += 1
            if slow.connection is not None and slow.connection.lagging:
                slow.disconnect()
                closings += 1
            if slow.connection is None:
                slow.connect()
            slow.drain()
        return slow.state, core.snapshot(sid), closings

    client, server, closings = run(scenario())
    assert closings >= 1 and client == server


def test_connection_relief_keeps_order():
    """Relief merges deltas of a part only across other deltas, and keeps lifecycle events."""
    conn = Connection(max_events=4, max_bytes=10**9)
    seq = iter(range(1, 100))

    def env(event):
        return {"v": 1, "channel": "session", "seq": next(seq), "epoch": "ep_x", "session_id": None,
                "turn_id": None, "ts": 0, "event": event}  # fmt: skip

    for event in ({"type": "part.start", "part_id": "a", "kind": "text", "index": 0},
                  {"type": "text.delta", "part_id": "a", "delta": "one "},
                  {"type": "text.delta", "part_id": "a", "delta": "two "},
                  {"type": "status", "phase": "streaming"},
                  {"type": "status", "phase": "tool"},
                  {"type": "text.delta", "part_id": "a", "delta": "three"}):  # fmt: skip
        conn.put(env(event))
    kinds = [(i.type, i.envelope["event"].get("delta")) for i in conn.items]
    assert kinds == [("part.start", None), ("text.delta", "one two "), ("status", None), ("text.delta", "three")]


# --- API-23, API-24, API-31, API-32, ARC-03 --------------------------------------------------------------------------


def api23_endpoint_fixtures(tmp_path: Path):
    """Every endpoint has a request and a response fixture that validate against its definitions; the S1 endpoints
    also answer live with bodies that validate."""
    for key, endpoint in ENDPOINTS_BY_KEY.items():
        for side in ("request", "response"):
            definition = endpoint[side]
            if definition is None:
                continue
            if "#" not in definition and "/" in definition:
                # A whole contract as the body (the voice activities union, VOC-39): its root fixtures.
                fixture = FIXTURES / definition / "valid" / "minimal.json"
                assert fixture.exists(), (key, side, definition)
                assert contract_errors(definition, json.loads(fixture.read_text())) == [], (key, side)
                continue
            contract, _, name = (
                definition.rpartition("#/$defs/") if "#" in definition else ("api/commands", "", definition)
            )
            fixture = FIXTURES / contract / name / "valid" / "minimal.json"
            assert fixture.exists(), (key, side, definition)
            body = json.loads(fixture.read_text())
            reference = f"{contract}#/$defs/{name}" if name else contract
            assert contract_errors(reference, body) == [], (key, side)

    async def live():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            out = {
                "GET /v1/meta": await r.get("/v1/meta"),
                "GET /v1/health": await r.get("/v1/health"),
                "GET /v1/sessions": await r.get("/v1/sessions"),
                "GET /v1/sessions/{session_id}/snapshot": await r.get(f"/v1/sessions/{sid}/snapshot"),
                "PATCH /v1/sessions/{session_id}": await r.client.patch(
                    f"{r.base}/v1/sessions/{sid}", json={"title": "Projectile"}, headers=r.headers(True)),
                "POST /v1/sessions/{session_id}/turns": await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT)),
            }  # fmt: skip
            turn_id = out["POST /v1/sessions/{session_id}/turns"].json()["turn_id"]
            await r.wait_idle(sid)
            out["POST /v1/turns/{turn_id}/cancel"] = await r.post(f"/v1/turns/{turn_id}/cancel")
            return out
        finally:
            await stop_core(r)

    for key, resp in run(live()).items():
        definition = ENDPOINTS_BY_KEY[key]["response"]
        assert resp.status_code in (200, 202), (key, resp.text)
        assert contract_errors(f"api/commands#/$defs/{definition}", resp.json()) == [], key


def api24_cancel_keeps_text(tmp_path: Path):
    solver = [{"stall_s": 5, **solver_steps()[0]}]
    provider = scripted({"solver": solver, "checker": [], "coach": []})

    async def scenario():
        r = await start_core(tmp_path, provider=provider)
        try:
            sid = await r.session()
            cursor = await cursor_of(r, sid)
            accepted = (await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))).json()
            await asyncio.sleep(0.3)
            loop = asyncio.get_running_loop()
            asked = loop.time()
            result = (await r.post(f"/v1/turns/{accepted['turn_id']}/cancel")).json()
            frames = await collect(r, sid, cursor)
            took = loop.time() - asked
            again = (await r.post(f"/v1/turns/{accepted['turn_id']}/cancel")).json()
            return result, frames, took, again
        finally:
            await stop_core(r)

    result, frames, took, again = run(scenario())
    end = frames[-1].json()["event"]
    assert result["result"] == "cancelled" and again["result"] == "inactive"
    assert end["type"] == "turn.end" and end["status"] == "interrupted"
    assert took < Settings().api_cancel_budget_ms / 1000
    shown = "".join(f.json()["event"]["delta"] for f in frames if f.event == "text.delta")
    assert shown == "Let me look at this problem."


def api31_duplicate_turn_start(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            body, key = ask(STATEMENT), cli()
            first = await r.post(f"/v1/sessions/{sid}/turns", body, key=key)
            second = await r.post(f"/v1/sessions/{sid}/turns", body, key=key)
            conflict = await r.post(f"/v1/sessions/{sid}/turns", ask("something else"), key=key)
            missing = await r.client.post(f"{r.base}/v1/sessions/{sid}/turns", json=ask(STATEMENT), headers=r.headers())
            await r.wait_idle(sid)
            turns = [json.loads(line)["event"]["turn_id"] for line in _ring_frames(r.core, sid)
                     if json.loads(line)["event"]["type"] == "turn.start"]  # fmt: skip
            return first, second, conflict, missing, turns
        finally:
            await stop_core(r)

    first, second, conflict, missing, turns = run(scenario())
    assert first.status_code == second.status_code == 202 and first.json() == second.json()
    assert turns == [first.json()["turn_id"]]
    assert conflict.status_code == 409 and conflict.json()["error"]["code"] == "request_conflict"
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "invalid_request"


def arc03_boundary_rejects_invalid_payloads(tmp_path: Path):
    """TB1 (UI to core): schema-violating commands are rejected with 422 and change nothing. TB2 and TB3 have their
    own tests (M2, M3)."""

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            sid = await r.session()
            before = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            bad = [
                ("/v1/sessions", {"mode": "guided"}),
                (f"/v1/sessions/{sid}/turns", {"client_message_id": "nope", "intent": "ask", "content": []}),
                (f"/v1/sessions/{sid}/turns", {**ask(STATEMENT), "extra": True}),
                (f"/v1/sessions/{sid}/turns", {**ask(STATEMENT), "intent": "become_admin"}),
            ]
            replies = [await r.post(path, body) for path, body in bad]
            replies.append(await r.client.patch(f"{r.base}/v1/sessions/{sid}", json={"mode": "free_for_all"},
                                                headers=r.headers(True)))  # fmt: skip
            raw = await r.client.post(f"{r.base}/v1/sessions/{sid}/turns", content=b"{not json",
                                      headers=r.headers(True))  # fmt: skip
            after = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            sessions = (await r.get("/v1/sessions")).json()["sessions"]
            return replies, raw, before, after, sessions
        finally:
            await stop_core(r)

    replies, raw, before, after, sessions = run(scenario())
    for resp in replies:
        assert resp.status_code == 422 and resp.json()["error"]["code"] == "validation_failed"
        assert resp.json()["error"]["action_taken"] is False
    assert raw.status_code == 400 and raw.json()["error"]["code"] == "invalid_request"
    assert before == after and len(sessions) == 1


def test_turn_active_conflict(tmp_path: Path):
    solver = [{"stall_s": 2, **solver_steps()[0]}]
    provider = scripted({"solver": solver, "checker": [], "coach": []})

    async def scenario():
        r = await start_core(tmp_path, provider=provider)
        try:
            sid = await r.session()
            first = (await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))).json()
            second = await r.post(f"/v1/sessions/{sid}/turns", ask("again"))
            await r.post(f"/v1/turns/{first['turn_id']}/cancel")
            return first, second
        finally:
            await stop_core(r)

    first, second = run(scenario())
    assert second.status_code == 409 and second.json()["error"]["code"] == "turn_active"
    assert second.json()["error"]["details"]["turn_id"] == first["turn_id"]


# --- ARC-22, ARC-23 --------------------------------------------------------------------------------------------------


def arc22_health_is_not_readiness(tmp_path: Path):
    """A runtime that answers health but fails the touch generation never makes the core report `ready`."""
    from agent_core.engine.assembly import AppRuntime
    from jana_tools.fakes.llama_server import FakeLlamaServer

    async def scenario():
        failing = {"status": 500, "body": {"error": {"message": "failed to load model"}}}
        async with FakeLlamaServer(["gemma-4-12b"], api_key="k", script=lambda body: failing) as fake:
            runtime = AppRuntime(fast_settings(), REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path)
            core = CoreService(fast_settings(), runtime.engine, SessionStore(tmp_path / "s"))
            async with httpx.AsyncClient() as client:
                health_ok = (await client.get(f"{fake.url}/health")).status_code == 200
            ready = await runtime.connect_runtime(fake.url, "k", "gemma-4-12b")
            core.readiness = "ready" if ready else "degraded"
            await runtime.close()
            return health_ok, ready, core.health()

    health_ok, ready, health = run(scenario())
    assert health_ok and not ready and health["readiness"] != "ready"
    assert contract_errors("api/commands#/$defs/Health", health) == []


def arc23_quit_mid_turn_persists_partial(tmp_path: Path):
    solver = [{"stall_s": 5, **solver_steps()[0]}]
    provider = scripted({"solver": solver, "checker": [], "coach": []})

    async def scenario():
        r = await start_core(tmp_path, provider=provider)
        sid = await r.session()
        await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
        await asyncio.sleep(0.3)
        loop = asyncio.get_running_loop()
        started = loop.time()
        await stop_core(r)
        return sid, loop.time() - started

    sid, took = run(scenario())
    record = checkpoints(tmp_path).load(sid)
    state = record["projection"]
    tutor_message = [m for m in state["messages"] if m["role"] == "tutor"][-1]
    assert tutor_message["status"] == "interrupted" and state["active_turn"] is None
    assert [state["parts"][p]["text"] for p in tutor_message["part_ids"]] == ["Let me look at this problem."]
    assert took < Settings().shutdown_grace_s + 2


def test_connection_relief_equivalent():
    """Relief under backpressure never changes the state a client folds (merges and replacements are safe)."""
    rng = random.Random(21)
    session, turn, board = "ses_" + "0" * 26, "trn_" + "0" * 26, "brd_" + "0" * 26
    steps = ["stp_" + str(i).zfill(26) for i in range(3)]
    parts = ["prt_" + str(i).zfill(26) for i in range(3)]
    for _ in range(2000):
        seq = iter(range(1, 10_000))
        events = [{"type": "turn.start", "turn_id": turn, "user_message_id": None, "client_message_id": None,
                   "intent": "ask", "mode": "guided", "fork": False}]  # fmt: skip
        events += [{"type": "part.start", "part_id": p, "kind": "text", "index": i} for i, p in enumerate(parts)]
        for _ in range(rng.randint(5, 40)):
            roll = rng.random()
            if roll < 0.4:
                events.append(
                    {"type": "text.delta", "part_id": rng.choice(parts), "delta": rng.choice(["a", "b ", "c\n"])}
                )
            elif roll < 0.7:
                events.append({"type": "board.step", "board_id": board, "step_id": rng.choice(steps), "index": 0,
                               "latex": "x", "reason": None, "owner": "tutor", "check_id": None, "error": None,
                               "status": rng.choice(["draft", "final", "awaiting", "correct"])})  # fmt: skip
            elif roll < 0.8:
                events.append({"type": "board.await", "board_id": board, "step_id": rng.choice(steps), "prompt": "go",
                               "input_kind": "latex"})  # fmt: skip
            else:
                events.append({"type": "status", "phase": rng.choice(["tool", "checking"]), "label_key": None,
                               "progress": None, "phase_started_ts": 0, "model_tier": "fast"})  # fmt: skip
        envelopes = [{"v": 1, "channel": "session", "seq": next(seq), "epoch": "ep_relief_t", "session_id": session,
                      "turn_id": turn, "ts": 0, "event": e} for e in events]  # fmt: skip
        conn = Connection(max_events=10**6, max_bytes=10**9)
        for envelope in envelopes:
            conn.put(envelope)
        conn._relieve()
        relieved = [i.envelope for i in conn.items]
        raw_state, relieved_state = projection.empty({}, "ep_relief_t"), projection.empty({}, "ep_relief_t")
        for envelope in envelopes:
            projection.apply(raw_state, envelope)
        for envelope in relieved:
            projection.apply(relieved_state, envelope)
        assert relieved_state == raw_state


def api32_error_fixtures():
    """Every error code of TABLE API-32a: the core maps it to its HTTP status, its envelope validates against the
    schema, and the client has a copy key for it."""
    from agent_core.api.errors import STATUS, envelope

    text = (REPO_ROOT / "docs" / "specification" / "streaming-and-api.md").read_text()
    table = text.split("TABLE API-32a", 1)[1].split("Acceptance:", 1)[0]
    spec: dict[str, int] = {}
    for line in table.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 2 and cells[0].isdigit():
            for code in re.findall(r"`([a-z_]+)`", cells[1].split("(with", 1)[0]):
                spec[code] = int(cells[0])
    # `tools_not_supported` belongs to the voice adapter's own error body (VOC-30), not the error envelope.
    assert spec and STATUS == {k: v for k, v in spec.items() if k != "tools_not_supported"}
    copy = json.loads((REPO_ROOT / "packages" / "i18n" / "locales" / "en.json").read_text())
    for code in STATUS:
        body = envelope(code, "fixture message", details={"field": "x"}, retry_after_ms=100)
        assert contract_errors("api/commands#/$defs/error_envelope", body) == [], code
        assert f"error.{code}" in copy, code


def _card_coach(model, messages, body):
    options = [{"label": "v^2 = u^2 + 2as", "latex": None, "recommended": False},
               {"label": "s = ut", "latex": None, "recommended": False}]  # fmt: skip
    card = {"card_type": "question", "prompt": "Which equation links u, v, a and s?", "allow_free_text": True,
            "multi": False, "options": options}  # fmt: skip
    return tutor("Pick the equation you would use.", card=card)


def api14_card_survives_restart(tmp_path: Path):
    """A card opened before a core restart is answerable after it, from the snapshot."""

    async def first():
        r = await start_core(tmp_path, provider=scripted(_card_coach))
        try:
            sid = await r.session()
            preset(r.core, sid)
            r.core.persist(r.core.sessions[sid])
            await r.post(f"/v1/sessions/{sid}/turns", ask("what next", "answer"))
            await r.wait_idle(sid)
            return sid, (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
        finally:
            await stop_core(r)

    async def second(sid):
        r = await start_core(tmp_path, provider=scripted(_card_coach))
        try:
            snap = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            request_id = snap["open_requests"][0]["request_id"]
            reply = await r.post(f"/v1/cards/{request_id}/answer",
                                 {"client_answer_id": cli(), "answer": {"option_ids": ["opt_0"]}})  # fmt: skip
            await r.wait_idle(sid)
            after = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            return snap, reply, after, request_id
        finally:
            await stop_core(r)

    sid, before = run(first())
    assert len(before["open_requests"]) == 1
    snap, reply, after, request_id = run(second(sid))
    assert snap["open_requests"][0]["request_id"] == request_id
    assert reply.status_code == 200 and reply.json()["status"] == "accepted"
    assert contract_errors("api/commands#/$defs/CardAnswerResult", reply.json()) == []
    assert after["open_requests"] == [] or after["open_requests"][0]["request_id"] != request_id
    answered = [p for p in after["parts"].values() if p.get("card", {}).get("request_id") == request_id]
    assert answered[0]["card"]["state"] == "answered"
    students = [m for m in after["messages"] if m["role"] == "student"]
    assert students[-1]["content"][0]["text"] == "v^2 = u^2 + 2as"  # the answer became the next turn


def api14_double_answer(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path, provider=scripted(_card_coach))
        try:
            sid = await r.session()
            preset(r.core, sid)
            await r.post(f"/v1/sessions/{sid}/turns", ask("what next", "answer"))
            await r.wait_idle(sid)
            request_id = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()["open_requests"][0]["request_id"]
            first = await r.post(f"/v1/cards/{request_id}/answer", {"client_answer_id": cli(), "answer": {"text": "a"}})
            await r.wait_idle(sid)
            second = await r.post(
                f"/v1/cards/{request_id}/answer", {"client_answer_id": cli(), "answer": {"text": "b"}}
            )
            return first.json(), second.json()
        finally:
            await stop_core(r)

    first, second = run(scenario())
    assert first["status"] == "accepted" and second["status"] == "already_answered"
    assert second["answered_ts"] == first["answered_ts"]


def api06_ts_schema_parity():
    """The generated TypeScript event union and the JSON Schema list the same event types, and the client handles
    exactly the session event types of the contract."""
    from agent_core.contracts import document

    defs = document("api/events")["$defs"]
    schema_types = set()
    for union in ("tutor_event", "app_event"):
        for ref in defs[union]["oneOf"]:
            schema_types.add(defs[ref["$ref"].rsplit("/", 1)[1]]["properties"]["type"]["const"])
    ts = (REPO_ROOT / "packages" / "contracts-ts" / "src" / "generated" / "api" / "events.ts").read_text()
    ts_types = set(re.findall(r'type: "([a-z_.]+)"', ts))
    assert schema_types == ts_types & schema_types and schema_types <= ts_types
    tutor = {defs[r["$ref"].rsplit("/", 1)[1]]["properties"]["type"]["const"] for r in defs["tutor_event"]["oneOf"]}
    client = (REPO_ROOT / "packages" / "client-core" / "src" / "session.ts").read_text()
    known = set(
        re.findall(
            r'"([a-z]+\.[a-z_]+|status|notice|error)"', client.split("KNOWN_EVENTS = new Set([", 1)[1].split("]);")[0]
        )
    )
    assert known == tutor


def uxs15_no_unchecked_numbers():
    """Across the recorded sessions, no tutor board line shows a final or checked number without a check id."""
    for path in sorted((REPO_ROOT / "evals" / "recordings").glob("*.json")):
        recording = json.loads(path.read_text())
        for envelope in recording["frames"]:
            event = envelope["event"]
            if event["type"] == "board.step" and event["owner"] == "tutor" and event["status"] in ("final", "correct"):
                if re.search(r"(?<![\^_{])\d", event["latex"]):
                    assert event["check_id"] is not None, (path.name, event["latex"])


def uxs19_power_pull_resume(tmp_path: Path):
    """A power cut mid-turn (the core stops without shutting down) resumes at the last completed step: the reloaded
    snapshot holds every completed board line and turn, and nothing after the last persisted point, in 20 of 20 runs."""

    async def one(run_dir: Path) -> tuple[list, list]:
        core = CoreService(
            fast_settings(), _runtime_factory(run_dir, dev_scripted_provider()), SessionStore(run_dir / "s")
        )
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        for text in ("what next", "s = 7 m"):
            core.start_turn(sid, ask(text, "answer"))
            await core.sessions[sid].task
        completed = core.snapshot(sid)
        core.start_turn(sid, ask("s = 10 m", "answer"))  # in flight when the power goes
        await asyncio.sleep(0)  # the turn has started (turn.start emitted, nothing persisted for it yet)
        engine = core.sessions[sid].engine
        assert engine is not None
        part = engine.events.start_part("text")
        engine.events.text(part, "Good, now check")
        engine.events.flush()
        # The power goes: no shutdown, no final persist. The next launch reads the store as it was left.
        restarted = CoreService(fast_settings(), lambda s: None, SessionStore(run_dir / "s"))
        resumed = restarted.snapshot(sid)
        task = core.sessions[sid].task
        task.cancel()  # tidy the abandoned process's work only after the store was read
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        return completed, resumed

    for n in range(20):
        completed, resumed = run(one(tmp_path / f"run{n}"))
        steps = lambda snap: [s for b in snap["boards"].values() for s in b["steps"].values()]  # noqa: E731
        assert [s["latex"] for s in steps(resumed)][: len(steps(completed))] == [s["latex"] for s in steps(completed)]
        done = [m["turn_id"] for m in completed["messages"] if m["role"] == "tutor"]
        assert [m["turn_id"] for m in resumed["messages"] if m["role"] == "tutor"][: len(done)] == done
        assert resumed["active_turn"] is None


def _capture(source: str, confirmed: bool) -> dict:
    photo = source in ("photo_file", "photo_paste", "photo_drop", "webcam", "device_camera", "handwriting_photo")
    kind = {"pdf": "pdf_page", "ink": "ink_strokes", "handwriting_photo": "handwriting"}.get(source, "photo")
    attachment = {"image_id": "img_" + "0" * 26, "kind": kind, "width": 1200, "height": 900, "bytes": 180_000,
                  "sha256": "a" * 64}  # fmt: skip
    attachments = [attachment] if (photo or source in ("pdf", "ink")) else []
    path = {"voice": "speech_to_text", "pdf": "pdf_text_layer"}.get(source, "vision_model" if attachments else "none")
    return {
        "schema_version": 1, "capture_id": "cap_" + "1" * 26, "session_id": None, "source": source,
        "purpose": "question", "locale": "en", "status": "confirmed" if confirmed else "awaiting_confirmation",
        "text": "A ball is thrown up at \\(14\\,m/s\\).", "regions": [], "questions": [], "attachments": attachments,
        "reader": {"path": path, "model_id": None, "hardware_class": "mid", "duration_ms": 0},
        "quality": {"checks": [], "overridden": False},
        "confirmation": {"confirmed": confirmed, "method": "sent" if confirmed else "pending", "edit_distance": 0,
                         "confirmed_at": 1 if confirmed else None},
        "injection": {"flagged": False, "spans_removed": 0}, "refusal": None,
        "egress": {"left_device": False, "destination": "none"}, "created_at": 1, "updated_at": 1,
    }  # fmt: skip


def inp01_capture_fixtures_and_gate(tmp_path: Path):
    from agent_core.contracts import document

    sources = document("input/captured-question")["properties"]["source"]["enum"]
    for source in sources:
        for confirmed in (True, False):
            assert contract_errors("input/captured-question", _capture(source, confirmed)) == [], source

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            sid = await r.session()
            body = {"client_message_id": cli(), "intent": "ask",
                    "content": [{"type": "image_ref", "image_id": "img_" + "0" * 26}]}  # fmt: skip
            return await r.post(f"/v1/sessions/{sid}/turns", body), r.core.sessions[sid].task
        finally:
            await stop_core(r)

    resp, task = run(scenario())
    assert resp.status_code == 409 and resp.json()["error"]["code"] == "capture_not_ready"
    assert task is None  # no turn started from an unconfirmed capture


def vsl16_default_visual_used():
    """A rejected spec in a topic with a default visual shows that visual, marked `fallback` with the reason."""
    from agent_core.assets.visuals import render
    from test_m4fh_context_visuals import ctx, source_examples

    default = copy.deepcopy(source_examples()[0])
    rejected = {**copy.deepcopy(default), "type": "heart_3d"}
    result = render(rejected, ctx(default_visual=default))
    assert result.status == "fallback" and result.resolved is not None
    assert result.resolved["type"] == default["type"] and result.resolved["fallback_reason"] == "visual_kind_unknown"
    assert contract_errors("visuals/visual-spec#/$defs/resolved", result.resolved) == []
    # Without a default visual the same request falls to words, never an error state (the text-only rung).
    words = render(rejected, ctx())
    assert words.status == "text_only" and words.resolved is None and words.alt
