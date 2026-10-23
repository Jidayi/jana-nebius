"""M10.c: checkpoints, resume after a crash or power loss, integrity at open and disk-low behaviour (DAT-07, DAT-13,
ARC-25). The core runs as the shell runs it, a separate process, and is killed with SIGKILL: no shutdown, no final
save, as when the power goes. Synthetic sessions only."""

import json
import os
import random
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
from agent_core.contracts._compat import current
from jana_tools import REPO_ROOT

STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
SCRIPT = [(STATEMENT, "ask"), ("I'm stuck", "stuck"), ("v^2 = u^2 + 2as, so 0 = 14^2 - 2(9.8)s", "answer"),
          ("s = 10 m", "answer")]  # fmt: skip
TERMINAL = {"final", "correct", "incorrect", "equivalent_unsimplified", "unchecked"}
ORIGIN = "tauri://localhost"


class Core:
    """`python -m agent_core.api` on a data directory, driven over HTTP with the launch token."""

    def __init__(self, data: Path) -> None:
        import secrets

        self.token = secrets.token_urlsafe(32)
        env = {k: v for k, v in os.environ.items() if not k.startswith("JANA_")}
        self.proc = subprocess.Popen([sys.executable, "-m", "agent_core.api"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env,
                                     start_new_session=True)  # fmt: skip
        control = current("control")  # the shell speaks the core's control-channel version (ARC-29)
        for message in ({"type": "control.hello", "protocol": {"major": control.major, "minor": control.minor}},
                        {"type": "control.config", "data_dir": str(data), "release": False, "scripted": True,
                         "content_root": str(REPO_ROOT / "content" / "agent"),
                         "skills_root": str(REPO_ROOT / "skills")},
                        {"type": "control.secret", "name": "launch_token", "value": self.token}):  # fmt: skip
            assert self.proc.stdin is not None
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        assert self.proc.stdout is not None
        ready = json.loads(self.proc.stdout.readline())
        assert ready["type"] == "control.ready", ready
        self.base = f"http://127.0.0.1:{ready['api_port']}"
        self.client = httpx.Client(timeout=30)

    def headers(self, mutating: bool = False) -> dict[str, str]:
        out = {"authorization": f"Bearer {self.token}", "origin": ORIGIN}
        if mutating:
            out["idempotency-key"] = f"cli_{os.urandom(13).hex()[:26].upper()}"
        return out

    def post(self, path: str, body: dict) -> httpx.Response:
        return self.client.post(self.base + path, json=body, headers=self.headers(True))

    def get(self, path: str) -> httpx.Response:
        return self.client.get(self.base + path, headers=self.headers())

    def power_pull(self) -> None:
        os.killpg(self.proc.pid, signal.SIGKILL)  # the core and its worker processes, at once
        self.proc.wait(timeout=10)
        self.client.close()

    def stop(self) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps({"type": "control.shutdown"}) + "\n")
        self.proc.stdin.flush()
        self.proc.wait(timeout=60)
        self.client.close()


def _completed_steps(core: Core, session_id: str, stop: threading.Event, seen: list[dict]) -> None:
    """Every board step the client saw reach a terminal status before the power went (the SSE stream)."""
    try:
        with httpx.stream("GET", f"{core.base}/v1/sessions/{session_id}/events", headers=core.headers(),
                          timeout=httpx.Timeout(5.0, read=None)) as response:  # fmt: skip
            for line in response.iter_lines():
                if stop.is_set():
                    return
                if line.startswith("data: "):
                    event = json.loads(line[6:]).get("event", {})
                    if event.get("type") == "board.step" and event.get("status") in TERMINAL:
                        seen.append({"step_id": event["step_id"], "status": event["status"]})
    except (httpx.HTTPError, OSError):
        return


def _pull_once(data: Path, rng: random.Random) -> tuple[list[dict], dict]:
    core = Core(data)
    body = {"client_session_id": f"cli_{os.urandom(13).hex()[:26].upper()}", "mode": "guided", "subject": "physics",
            "level": "O", "origin": {"kind": "ask", "ref": None}}  # fmt: skip
    session_id = core.post("/v1/sessions", body).json()["session_id"]
    seen: list[dict] = []
    stop = threading.Event()
    watcher = threading.Thread(target=_completed_steps, args=(core, session_id, stop, seen), daemon=True)
    watcher.start()
    turns = rng.randint(1, len(SCRIPT))
    for text, intent in SCRIPT[:turns]:
        core.post(
            f"/v1/sessions/{session_id}/turns",
            {
                "client_message_id": f"cli_{os.urandom(13).hex()[:26].upper()}",
                "intent": intent,
                "content": [{"type": "text", "text": text}],
            },
        )
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and core.get(f"/v1/sessions/{session_id}/snapshot").json().get(
                "active_turn"):  # fmt: skip
            time.sleep(0.05)
    # The power goes at a random moment: during a turn or between turns.
    if rng.random() < 0.5:
        core.post(
            f"/v1/sessions/{session_id}/turns",
            {
                "client_message_id": f"cli_{os.urandom(13).hex()[:26].upper()}",
                "intent": "stuck",
                "content": [{"type": "text", "text": "?"}],
            },
        )
    time.sleep(rng.uniform(0.0, 1.5))
    stop.set()
    completed = list(seen)
    core.power_pull()
    restarted = Core(data)
    try:
        snapshot = restarted.get(f"/v1/sessions/{session_id}/snapshot").json()
    finally:
        restarted.stop()
    return completed, snapshot


def _assert_resumed(completed: list[dict], snapshot: dict) -> None:
    steps = {sid: s for board in snapshot["boards"].values() for sid, s in board["steps"].items()}
    for step in completed:
        assert step["step_id"] in steps and steps[step["step_id"]]["status"] == step["status"], step
    assert snapshot["active_turn"] is None  # an open turn found at start is closed interrupted
    assert all(m.get("status") != "streaming" for m in snapshot["messages"] if m["role"] == "tutor")


def dat07_power_pull_resume(tmp_path: Path):
    """Twenty power pulls at random points of guided sessions: each resumes at its last completed board step."""
    rng = random.Random(7)
    for run in range(20):
        completed, snapshot = _pull_once(tmp_path / f"run{run}", rng)
        _assert_resumed(completed, snapshot)


def arc25_power_pull_resume(tmp_path: Path):
    """The same guarantee on one data directory used again and again: each pull resumes, and the next session
    starts cleanly beside the interrupted ones."""
    rng = random.Random(25)
    data = tmp_path / "data"
    for _ in range(20):
        completed, snapshot = _pull_once(data, rng)
        _assert_resumed(completed, snapshot)


# --- DAT-13 ----------------------------------------------------------------------------------------------------------


def _in_process(tmp_path: Path, scenario, worker: bool = True):
    import asyncio

    from api_harness import start_core, stop_core

    async def go():
        r = await start_core(tmp_path, worker=worker)
        try:
            return await scenario(r)
        finally:
            await stop_core(r)

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(go())
    finally:
        loop.close()


async def _guided_turn(api, r, token: str) -> str:
    import asyncio

    from api_harness import ask, cli

    body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
            "origin": {"kind": "ask", "ref": None}}  # fmt: skip
    session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
    await api.call("POST", f"/v1/sessions/{session}/turns", ask(STATEMENT), profile=token)
    for _ in range(600):
        entry = r.core.sessions.get(session)
        if entry is not None and (entry.task is None or entry.task.done()):
            break
        await asyncio.sleep(0.05)
    return session


def dat13_corruption_recovery(tmp_path: Path):
    import sqlite3

    from agent_core.store.integrity import quick_check
    from test_m10a_profiles import Api, student

    async def first(r):
        api = Api(r)
        profile = await api.add(student("Ama"))
        await _guided_turn(api, r, (await api.unlock(profile)).json()["profile_token"])
        return profile

    profile = _in_process(tmp_path, first)
    learner = tmp_path / "profiles" / profile[4:] / "learner.db"
    conn = sqlite3.connect(learner)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    pages = conn.execute("PRAGMA page_count").fetchone()[0]
    size = conn.execute("PRAGMA page_size").fetchone()[0]
    conn.close()
    with learner.open("r+b") as handle:  # scribble over a page in the second half of the file
        handle.seek(size * (pages * 2 // 3))
        handle.write(b"\xa5" * size)
    assert not quick_check(learner)

    async def after(r):
        api = Api(r)
        unlocked = await api.unlock(profile)
        assert unlocked.status_code == 200, unlocked.text
        session = await _guided_turn(api, r, unlocked.json()["profile_token"])
        health = (await api.call("GET", "/v1/health")).json()
        return session, health

    session, health = _in_process(tmp_path, after)
    assert session and health["components"].get("learner_store") == "degraded"
    # The damaged file itself, not the -wal/-shm files kept beside it (which may be empty).
    damaged = [p for p in learner.parent.glob("learner.db.damaged-*") if not p.name.endswith(("-wal", "-shm"))]
    assert len(damaged) == 1 and damaged[0].stat().st_size > 0  # never deleted without the adult's confirmation
    assert quick_check(learner)


def dat13_disk_low_behaviour(tmp_path: Path, monkeypatch):
    import collections
    import shutil

    from test_m10a_profiles import Api, student

    usage = collections.namedtuple("usage", "total used free")
    real = shutil.disk_usage

    async def scenario(r):
        api = Api(r)
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        before_traces = len(r.runtime.traces.records())
        monkeypatch.setattr(shutil, "disk_usage", lambda path: usage(10**12, 10**12 - 400 * 1024**2, 400 * 1024**2))
        with r.runtime.directory.open_learner(profile) as conn:
            before_events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        session = await _guided_turn(api, r, token)
        r.runtime.traces.flush()
        with r.runtime.directory.open_learner(profile) as conn:
            after_events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        health = (await api.call("GET", "/v1/health")).json()
        snapshot = (await api.call("GET", f"/v1/sessions/{session}/snapshot", profile=token)).json()
        monkeypatch.setattr(shutil, "disk_usage", real)
        return before_events, after_events, before_traces, len(r.runtime.traces.records()), health, snapshot

    before, after, traces_before, traces_after, health, snapshot = _in_process(tmp_path, scenario)
    assert after > before  # progress is still saved
    assert traces_after == traces_before  # traces stop first
    assert health["components"]["storage"] == "degraded" and health["components"]["capture"] == "down"
    assert any(m["role"] == "tutor" for m in snapshot["messages"])  # the session continues
