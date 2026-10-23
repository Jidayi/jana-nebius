"""M6.b: transcript persistence, checkpoints, the trace store and the store inventory (DAT-06, MEM-02, OBS-08,
DAT-01)."""

from __future__ import annotations

import asyncio
import fnmatch
import json
import os
import time
from pathlib import Path

from agent_core.api import projection
from agent_core.api.core import CoreService
from agent_core.engine.records import SessionRecords
from agent_core.store.sessions import SessionStore
from agent_core.store.sqlite import connect
from agent_core.store.transcript import TranscriptStore
from agent_core.trace.store import TraceStore
from api_harness import STATEMENT, ask, scripted, start_core, stop_core
from jana_tools import REPO_ROOT
from learner_harness import learner_db
from test_m5abc_api import fast_settings, preset, run, solver_steps

RECORDINGS = REPO_ROOT / "evals" / "recordings"
ENDED = ("complete", "error", "interrupted", "retracted")


def _replay(recording: dict) -> tuple[TranscriptStore, dict]:
    """Fold a recorded stream into a projection and the store, as the core does, sends at their recorded points."""
    session = recording["snapshots"][0]["session"]
    state = projection.empty(dict(session), "replay")
    store = TranscriptStore(learner_db())
    records = SessionRecords(store)
    records.session_started(session)
    sends = list(recording["sends"])
    for frame in recording["frames"]:
        while sends and sends[0]["after_seq"] < frame["seq"]:
            body = sends.pop(0)["body"]
            projection.student_message(state, body["client_message_id"], body["content"])
        projection.apply(state, frame)
        records.on_event(session["session_id"], frame, state)
    assert records.failures == 0
    return store, state


def dat06_parts_roundtrip() -> None:
    for path in sorted(RECORDINGS.glob("*.json")):
        recording = json.loads(path.read_text())
        store, state = _replay(recording)
        sid = recording["session_id"]
        tutor_turns = [t for t in store.turns(sid) if t["speaker"] == "tutor"]
        assert tutor_turns, path.name
        stored = {p["part_id"]: p for t in tutor_turns for p in store.parts(t["turn_id"])}
        for part in state["parts"].values():
            if part["status"] in ENDED and part["kind"] != "notice":
                row = stored[part["part_id"]]
                content = {k: v for k, v in row["content"].items() if k != "visual"}
                assert content == part, (path.name, part["part_id"])
                assert row["status"] == part["status"] and row["kind"] == part["kind"]
                if part.get("visual_id"):
                    assert row["content"]["visual"] == state["visuals"][part["visual_id"]]
        # Every student message is a turn with its text; every tutor turn ended as streamed.
        messages = [m for m in state["messages"] if m["role"] == "student"]
        students = [t for t in store.turns(sid) if t["speaker"] == "student"]
        assert [t["student_text"] for t in students] == [m["content"][0]["text"] for m in messages]
        ended = {m["turn_id"]: m["status"] for m in state["messages"] if m["role"] == "tutor"}
        assert {t["turn_id"]: t["status"] for t in tutor_turns} == ended
        # Board steps are rows with their latest status.
        boards = {s["step_id"]: s for b in state["boards"].values() for s in b["steps"].values()}
        assert {s["step_id"]: s["status"] for s in store.steps(sid)} == {k: v["status"] for k, v in boards.items()}


def dat06_interrupted_partial_kept(tmp_path: Path) -> None:
    solver = [{"stall_s": 5, **solver_steps()[0]}]
    provider = scripted({"solver": solver, "checker": [], "coach": []})

    async def scenario() -> tuple[str, str]:
        r = await start_core(tmp_path, provider=provider)
        try:
            sid = await r.session()
            accepted = (await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))).json()
            await asyncio.sleep(0.3)
            await r.post(f"/v1/turns/{accepted['turn_id']}/cancel")
            await r.wait_idle(sid)
            return sid, accepted["turn_id"]
        finally:
            await stop_core(r)

    sid, turn_id = run(scenario())
    store = TranscriptStore(connect(next((tmp_path / "profiles").glob("*/learner.db"))))
    turns = {t["turn_id"]: t for t in store.turns(sid)}
    assert turns[turn_id]["status"] == "interrupted"
    # The text the student saw before the stop is kept.
    shown = [p["content"]["text"] for p in store.parts(turn_id) if p["kind"] == "text"]
    assert shown == ["Let me look at this problem."]
    student = [t for t in turns.values() if t["speaker"] == "student"]
    assert student[0]["student_text"] == STATEMENT


def mem02_resume_after_kill(tmp_path: Path) -> None:
    """The process dies after a completed step, with no shutdown: the next start has the same board, rung and step."""
    from agent_core.engine.devscript import dev_scripted_provider
    from agent_core.engine.state import state_to_json
    from test_m5abc_api import _runtime_factory, _session_body

    async def scenario() -> tuple[dict, dict, dict, dict]:
        core = CoreService(fast_settings(), _runtime_factory(tmp_path, dev_scripted_provider()),
                           SessionStore(tmp_path / "s"))  # fmt: skip
        sid = core.create_session(_session_body())["session_id"]
        preset(core, sid)
        for text, intent in (("what next", "answer"), ("s = 7 m", "answer"), ("I'm stuck", "stuck")):
            core.start_turn(sid, ask(text, intent))
            await core.sessions[sid].task
        engine = state_to_json(core.sessions[sid].engine_state)
        boards = core.snapshot(sid)["boards"]
        # Killed: no shutdown, no final write. A new process reads what the store held.
        restarted = CoreService(fast_settings(), lambda s: None, SessionStore(tmp_path / "s"))
        return boards, engine, restarted.snapshot(sid)["boards"], state_to_json(restarted.sessions[sid].engine_state)

    boards, engine, boards_after, engine_after = run(scenario())
    assert boards_after == boards
    assert engine_after == engine  # board, hint rung, step index and everything else the engine continues from
    assert engine["rung"] >= 1 and engine["board"]["steps"]  # not trivially empty


def mem02_atomic_checkpoint(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    sid = "ses_" + "1" * 26
    store.save(sid, {"n": 1})
    store.save(sid, {"n": 2})
    current = tmp_path / f"{sid}.json"
    # A torn write of the current checkpoint: the previous one is read instead.
    current.write_bytes(current.read_bytes()[:5])
    assert store.load(sid) == {"n": 1}
    # The next save does not discard the last good checkpoint for the torn one.
    store.save(sid, {"n": 3})
    assert store.load(sid) == {"n": 3}
    assert json.loads((tmp_path / f"{sid}.json.prev").read_text()) == {"n": 1}
    # A crash between the two renames leaves no current file: the previous checkpoint is still there.
    store.save(sid, {"n": 4})
    os.replace(current, tmp_path / "lost")
    assert store.load(sid) == {"n": 3}
    assert store.load_all() == {sid: {"n": 3}}
    # A crash while writing the temporary file leaves the current checkpoint untouched.
    store.save(sid, {"n": 5})
    (tmp_path / f"{sid}.json.tmp").write_text('{"n": 6')
    assert store.load(sid) == {"n": 5}


def _record(n: int, size: int = 2000) -> dict:
    return {"trace_id": f"t{n:06d}", "profile_ref": "prof_local", "session_ref": "ses_x", "pad": "x" * size}


def obs08_retention_by_size_and_age(tmp_path: Path) -> None:
    now = [1_760_000_000_000]
    cap = 60_000
    store = TraceStore(tmp_path / "traces" / "traces.db", max_bytes=cap, retention_days=14, clock_ms=lambda: now[0])
    for n in range(200):
        now[0] += 1000
        store.submit(_record(n))
    store.flush()
    kept = [r["trace_id"] for r in store.records()]
    assert store.stored_bytes() <= cap
    assert kept == [f"t{n:06d}" for n in range(200 - len(kept), 200)]  # the newest, contiguous: oldest went first
    assert (tmp_path / "traces" / "traces.db").stat().st_size <= 4 * cap
    # Fifteen days later, a new record removes everything older than the age limit.
    now[0] += 15 * 86_400_000
    store.submit(_record(999))
    store.flush()
    assert [r["trace_id"] for r in store.records()] == ["t000999"]
    # Deleting a profile deletes its traces.
    store.delete_profile("prof_local")
    assert store.records() == []
    store.close()


class FailingTraces(TraceStore):
    def _write(self, conn, record):  # type: ignore[no-untyped-def]
        raise OSError("disk full")


def obs08_writer_failure_isolated(tmp_path: Path) -> None:
    failing = FailingTraces(tmp_path / "traces.db", max_bytes=10**6, retention_days=14)
    started = time.perf_counter()
    for n in range(500):
        failing.submit(_record(n))
    assert time.perf_counter() - started < 0.5  # submitting never waits on the writer
    failing.flush()
    assert failing.failures == 500
    failing.close()

    # A turn with a failing writer completes as usual; so does one whose sink itself raises.
    async def scenario(sink_raises: bool) -> str:
        r = await start_core(tmp_path / ("raise" if sink_raises else "fail"))
        try:
            assert r.runtime.traces is not None
            r.runtime.traces.close()
            r.runtime.traces = FailingTraces(tmp_path / "unused.db", max_bytes=10**6, retention_days=14)
            if sink_raises:

                def boom(record: dict) -> None:
                    raise RuntimeError("sink down")

                r.runtime.traces.submit = boom  # type: ignore[method-assign]
            sid = await r.session()
            await r.post(f"/v1/sessions/{sid}/turns", ask(STATEMENT))
            await r.wait_idle(sid)
            snap = (await r.get(f"/v1/sessions/{sid}/snapshot")).json()
            return [m for m in snap["messages"] if m["role"] == "tutor"][-1]["status"]
        finally:
            await stop_core(r)

    assert run(scenario(False)) == "complete"
    assert run(scenario(True)) == "complete"


def dat01_no_unlisted_stores(tmp_path: Path) -> None:
    """After a scripted session, learner data is only under the paths of TABLE DAT-01a."""

    async def scenario() -> None:
        r = await start_core(tmp_path)
        try:
            sid = await r.session()
            for text, intent in ((STATEMENT, "ask"), ("I'm stuck", "stuck"), ("s = 10 m", "answer")):
                await r.post(f"/v1/sessions/{sid}/turns", ask(text, intent))
                await r.wait_idle(sid)
        finally:
            await stop_core(r)

    run(scenario())
    allowed = (
        "device.db",
        "profiles/*/learner.db",
        "profiles/*/spill/*",
        "traces/traces.db",
        "logs/*",
        # TABLE DAT-01a rows "Session checkpoints (S1)" and "Worker scratch".
        "sessions/ses_*.json",
        "sessions/ses_*.json.prev",
        "scratch/*",
        # TABLE DAT-01a row "Safety configuration, compatibility matrix, revocation list".
        "config/revocations.json",
    )
    found = []
    for path in tmp_path.rglob("*"):
        if path.is_dir():
            continue
        relative = path.relative_to(tmp_path)
        base = Path(str(relative).removesuffix("-wal").removesuffix("-shm").removesuffix(".bak"))
        if not any(fnmatch.fnmatch(str(base), pattern) for pattern in allowed):
            found.append(str(relative))
    assert found == []


def lrn01_session_ended_paired(tmp_path: Path) -> None:
    """A scripted day: every session_started pairs with one session_ended whose reason matches how it ended."""
    from agent_core.engine.assembly import AppRuntime
    from agent_core.engine.devscript import dev_scripted_provider
    from test_m5abc_api import _session_body

    minute = 60_000
    now = [1_760_000_000_000]

    def clock() -> int:
        return now[0]

    def core_over(data: Path) -> tuple[CoreService, AppRuntime]:
        runtime = AppRuntime(fast_settings(), REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", data,
                             providers={"local": dev_scripted_provider()})  # fmt: skip
        records = runtime.open_stores("0.0.0-test")
        return CoreService(fast_settings(), runtime.engine, SessionStore(data / "sessions"), clock_ms=clock,
                           records=records), runtime  # fmt: skip

    async def turn(core: CoreService, sid: str, text: str, intent: str = "answer") -> None:
        core.start_turn(sid, ask(text, intent))
        await core.sessions[sid].task

    async def day() -> dict[str, str]:
        core, _ = core_over(tmp_path)
        ids = {}
        ids["switched"] = core.create_session(_session_body())["session_id"]
        preset(core, ids["switched"])
        await turn(core, ids["switched"], "what next")
        now[0] += minute
        ids["idle"] = core.create_session(_session_body())["session_id"]  # the switch ends the first
        preset(core, ids["idle"])
        await turn(core, ids["idle"], "what next")
        now[0] += 40 * minute
        await turn(core, ids["idle"], "s = 7 m")  # touched after the idle timeout: ended, then begun again
        now[0] += minute
        ids["solved"] = core.create_session(_session_body())["session_id"]
        preset(core, ids["solved"])
        await turn(core, ids["solved"], "s = 10 m")  # the final answer: the problem is finished
        now[0] += minute
        ids["closed"] = core.create_session(_session_body())["session_id"]
        await core.shutdown()  # the app closes with it open
        # Another day: a session in a process that dies before writing its end.
        now[0] += 600 * minute
        crashed_core, _ = core_over(tmp_path)
        ids["crashed"] = crashed_core.create_session(_session_body())["session_id"]
        now[0] += minute
        core_over(tmp_path)  # the next start
        return ids

    ids = run(day())
    from learner_harness import PROFILE  # noqa: F401 - the harness's synthetic data only

    conn = connect(next((tmp_path / "profiles").glob("*/learner.db")))
    events = conn.execute(
        "SELECT type, json_extract(payload, '$.session_id'), json_extract(payload, '$.reason') FROM events"
        " WHERE type IN ('session_started', 'session_ended', 'attempt') ORDER BY seq"
    ).fetchall()
    assert not [e for e in events if e[0] == "attempt"]  # ad-hoc attempts write no attempt event before S2
    reasons: dict[str, list[str]] = {}
    opened: set[str] = set()
    for kind, sid, reason in events:
        if kind == "session_started":
            assert sid not in opened, "a session started twice without ending"
            opened.add(sid)
        else:
            assert sid in opened, "an end without a start"
            opened.discard(sid)
            reasons.setdefault(sid, []).append(reason)
    assert opened == set()
    bare_ids = {name: sid.removeprefix("ses_") for name, sid in ids.items()}
    assert reasons[bare_ids["switched"]] == ["student_left"]
    assert reasons[bare_ids["idle"]] == ["idle_timeout", "student_left"]
    assert reasons[bare_ids["solved"]] == ["completed"]
    assert reasons[bare_ids["closed"]] == ["interrupted"]
    assert reasons[bare_ids["crashed"]] == ["crash_recovered"]
    ended = dict(conn.execute("SELECT session_id, end_reason FROM sessions WHERE session_id = ?",
                              (bare_ids["solved"],)).fetchall())  # fmt: skip
    assert ended == {bare_ids["solved"]: "completed"}
