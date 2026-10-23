"""M15.e the background Reflector (AGT-26, MEM-06, MEM-08 engine half): write points only, one job each, after the
reply and never mid-turn; a student's message goes first and a paused job completes once in the next idle period;
an output with a number outside its lists fails whole, with one correction retry. Every learner, note and message
is synthetic."""

from __future__ import annotations

import asyncio
import json
import logging
import statistics
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.engine.reflection import (
    JOB_ACTION,
    ReflectorJob,
    ReflectorModel,
    ReflectorQueue,
    job_cursor,
    reflect,
    window_cursor,
)
from agent_core.memory.reflect_input import JobKey
from agent_core.store.ids import new_ulid
from agent_core.tools.executor import ToolExecutor
from api_harness import STATEMENT, ask, scripted, stop_core
from engine_harness import checker_steps, close, make_engine, solver_steps, tutor
from memory_harness import (
    DAY,
    PROFILE_A,
    SAFE,
    SPEED,
    core_with_reflector,
    note,
    reflection,
    requests_of,
    run,
    store,
    user_texts,
    wait_for,
)

TODAY = datetime.now(UTC).date().isoformat()
NOTE = "Divides distance by time correctly once the units match"
STUCK = [tutor(SAFE), tutor("Not quite yet. What is the speed at the very top?"),
         tutor("Think about the speed at the very top.", hint_rung=1)]  # fmt: skip


async def _turn(r: Any, session: str, text: str, intent: str = "ask") -> str:
    answered = await r.post(f"/v1/sessions/{session}/turns", ask(text, intent))
    assert answered.status_code == 202, answered.text
    await r.wait_idle(session)
    return str(answered.json()["turn_id"])


async def _stuck(r: Any, session: str) -> None:
    """A problem, a wrong attempt, then a hint: learning evidence a note can cite."""
    await _turn(r, session, STATEMENT)
    await _turn(r, session, "s = 7 m", "answer")
    await _turn(r, session, "I'm stuck", "stuck")


def _notes(r: Any) -> list[tuple[str, str]]:
    return r.runtime.learner.conn.execute("SELECT text, status FROM notes WHERE status <> 'deleted'").fetchall()


# --- MEM-08 (engine half): integer refs, one correction retry, then nothing ----------------------------------------


def _hints(held: Any, count: int) -> str:
    sid = held.session(new_ulid())
    for n in range(count):
        held.clock.now += 1000
        held.learner.record("hint", {"session_id": sid, "problem_ref": f"prob_{n}", "step_index": 0, "rung": 1,
                                     "trigger": "student_request", "kc_ids": [SPEED]},
                            source="engine", session_id=sid)  # fmt: skip
    return sid


async def _job(tmp_path: Path, held: Any, steps: list[Any]) -> tuple[Any, Any, Any]:
    engine, provider = await make_engine(tmp_path, {"reflector": steps}, worker=False)
    try:
        deps = engine.deps
        model = ReflectorModel(deps.router, deps.assets, deps.settings, deps.bundled_schemas,
                               frozenset(deps.registry.specs))  # fmt: skip
        sid = held.conn.execute("SELECT session_id FROM sessions").fetchone()[0]
        key = JobKey(PROFILE_A, sid, "problem_end", window_cursor(held.conn, sid))
        outcome = await reflect(held.source(), model, ToolExecutor(deps.registry, deps.settings, deps.executor.spill),
                                key, session_date=DAY, subject="physics")  # fmt: skip
    finally:
        await close(engine)
    return outcome, provider, key


def mem08_integer_refs_bounded(tmp_path: Path) -> None:
    held = store()
    _hints(held, 6)  # six evidence lines are listed
    events = held.conn.execute("SELECT count(*) FROM events").fetchone()[0]
    outcome, provider, key = run(_job(tmp_path, held, [reflection(note(NOTE, [1, 9])), reflection(note(NOTE, [9]))]))
    calls = requests_of(provider, "reflector")
    assert len(calls) == 2, "one correction retry, no more"
    assert (outcome.status, outcome.reason) == ("dropped", "ref_out_of_range")
    assert held.conn.execute("SELECT count(*) FROM notes").fetchone()[0] == 0, "nothing of the output was applied"
    assert held.conn.execute("SELECT count(*) FROM events").fetchone()[0] == events, "no event either"
    correction = calls[1]["messages"][-1]["content"]
    assert "not in the lists" in correction and NOTE not in correction
    assert job_cursor(held.conn, key.session_id) == key.cursor_seq, "the dropped window is not tried again"
    # The same job with a good retry applies once.
    good = store()
    _hints(good, 6)
    outcome, provider, _ = run(_job(tmp_path / "good", good, [reflection(note(NOTE, [9])),
                                                              reflection(note(NOTE, [6], kc=1))]))  # fmt: skip
    assert outcome.status == "applied" and len(requests_of(provider, "reflector")) == 2
    assert [t for (t,) in good.conn.execute("SELECT text FROM notes")] == [NOTE]
    trace = outcome.trace
    assert trace is not None and trace["kind"] == "job" and trace["job_name"] == "reflector"
    assert contract_errors("trace/turn-trace", trace) == []
    assert {"gate": "output", "fired": True, "nudges": 0, "attempt": 1, "outcome": "passed_after_nudge"} in trace[
        "gates"
    ]
    assert NOTE not in json.dumps(trace), "a job trace carries no note text"


# --- MEM-06: the four write points, one job each, never mid-turn --------------------------------------------------


def mem06_write_points_only(tmp_path: Path) -> None:
    during_turn: list[bool] = []
    holder: dict[str, Any] = {}

    def reflector(body: dict[str, Any]) -> dict[str, Any]:
        during_turn.append(holder["r"].core._turn_running())
        task = body["messages"][-1]["content"]
        if "asked to remember" in task:
            return reflection(note("Finds a labelled sketch helpful before a formula", [1], date=TODAY))
        return reflection(note(NOTE, [1], date=TODAY))

    coach = [*STUCK, tutor("Thanks. Go on."), tutor("That's right."), tutor("Think about the top.", hint_rung=2),
             tutor("Think about the top again.", hint_rung=3), tutor(SAFE)]  # fmt: skip
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach,
                         "reflector": [reflector] * 8})  # fmt: skip

    async def scenario() -> Any:
        # Hint requests here come seconds apart: without the pacing gap of PED-06 each one is a hint, not a pause.
        r = await core_with_reflector(tmp_path, provider, hint_min_gap_s=0.0)
        holder["r"] = r
        queue = r.core.reflector
        assert queue is not None
        try:
            session = await r.session()
            await _stuck(r, session)
            await queue.idle()
            assert requests_of(provider, "reflector") == [], "no write point yet: no job"
            # An explicit request before the problem ends: its job keeps the student's note and leaves the window
            # to the next write point, which still reflects the hint before it (AGT-26, MEM-06).
            await _turn(r, session, "remember that a labelled sketch helps me first")
            await queue.idle()
            await _turn(r, session, "s = 10 m", "answer")  # the problem ends, with nothing new since the request
            await queue.idle()
            await _turn(r, session, "I'm stuck", "stuck")  # more evidence, then a long pause
            real = r.core.clock_ms
            r.core.clock_ms = lambda: real() + int(r.core.settings.memory_idle_write_min * 60_000) + 1000
            queued = r.core.idle_check()
            assert r.core.idle_check() == [], "one idle job per quiet period"
            r.core.clock_ms = real
            await queue.idle()
            await _turn(r, session, "I'm stuck", "stuck")
            other = await r.session()  # switching away ends the learning session
            # Saving on, but no learning evidence in this session: nothing can be kept, and the student is told so
            # in the turn that asked (MEM-11, G91).
            empty = await _turn(r, other, "remember that I like the units first", "ask")
            await queue.idle()
            declines = [f for f in r.core.sessions[other].engine.events.frames if f["event"]["type"] == "notice"]
            return [key.point for key, _ in queue.outcomes], queued, session, declines, empty, list(queue.outcomes)
        finally:
            await stop_core(r)

    points, queued, session, declines, empty, outcomes = run(scenario())
    assert queued == [session]
    assert points == ["explicit_request", "problem_end", "idle", "session_end", "explicit_request"], points
    assert len(requests_of(provider, "reflector")) == 5, "one Reflector call per write point"
    assert during_turn and not any(during_turn), "never while a turn runs"
    assert outcomes[0][1].saved and not outcomes[-1][1].saved, "the request with no evidence kept nothing"
    assert [(f["turn_id"], f["event"]["message_key"]) for f in declines] == [(empty, "memory.declined")]


def test_saving_off_writes_nothing(tmp_path: Path) -> None:
    """With saving off no write point makes a job, and what happened while it was off is never reflected later."""
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(),
                         "coach": [*STUCK, tutor("That's right."), tutor(SAFE)], "reflector": []})  # fmt: skip

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        try:
            conn = r.runtime.learner.conn
            conn.execute("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at) VALUES"
                         " ('memory_saving', 'false', 'student', NULL, '0', 0)")  # fmt: skip
            session = await r.session()
            await _stuck(r, session)
            await _turn(r, session, "s = 10 m", "answer")
            await _turn(r, session, "remember that I like a sketch first")
            await r.core.reflector.idle()
            conn.execute("UPDATE settings SET value = 'true' WHERE key = 'memory_saving'")
            backlog = r.core.reflector.backlog("prof_local")
            return job_cursor(conn, session[4:]), window_cursor(conn, session[4:]), backlog
        finally:
            await stop_core(r)

    done, newest, backlog = run(scenario())
    assert requests_of(provider, "reflector") == []
    assert done >= newest - 1 and backlog == 0


# --- AGT-26: the student goes first; a paused job completes once ----------------------------------------------------


async def _first_text_s(r: Any, session: str, text: str) -> float:
    """Seconds from sending a message to its turn's first accepted text on the stream."""
    started = time.monotonic()
    answered = await r.post(f"/v1/sessions/{session}/turns", ask(text, "answer"))
    turn = answered.json()["turn_id"]
    engine = r.core.sessions[session].engine
    await wait_for(
        lambda: any(f["turn_id"] == turn and f["event"]["type"] == "text.delta" for f in engine.events.frames)
    )
    elapsed = time.monotonic() - started
    await r.wait_idle(session)
    return elapsed


def _slow(say: str, seconds: float) -> dict[str, Any]:
    return {**tutor(say), "stall_s": seconds}


def agt26_reflector_yields(tmp_path: Path) -> None:
    """The student's turn is not slowed by a running reflection: it is cancelled and requeued at once. The scripted
    provider has no shared device, so this proves the scheduling only; contention on real hardware (one model
    serving both) is measured by the live memory evaluation."""
    generation = 0.6  # the Coach's own generation time in this script
    coach = [*STUCK, *(_slow("Not quite yet. Look at the top again.", generation) for _ in range(4))]
    reflector = [reflection(note(NOTE, [1], date=TODAY), stall=30.0), reflection(note(NOTE, [1], date=TODAY))]
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach, "reflector": reflector})

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        queue = r.core.reflector
        assert queue is not None
        try:
            session = await r.session()
            await _stuck(r, session)
            await queue.idle()
            baseline = [await _first_text_s(r, session, "s = 6 m") for _ in range(2)]
            assert queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics")
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 1)  # the Reflector is generating
            assert queue.running is not None
            during = [await _first_text_s(r, session, "s = 5 m") for _ in range(2)]
            await queue.idle()
            return baseline, during, list(queue.outcomes), _notes(r)
        finally:
            await stop_core(r)

    baseline, during, outcomes, notes = run(scenario())
    tolerance = Settings().reflector_yield_tolerance
    assert max(during) <= statistics.median(baseline) * (1 + tolerance), (baseline, during)
    assert [o.status for _, o in outcomes] == ["applied"], "the paused job ran again afterwards"
    assert notes == [(NOTE, "active")]


def agt26_reflector_resumes_once(tmp_path: Path) -> None:
    reflector = [reflection(note(NOTE, [1], date=TODAY), stall=30.0), reflection(note(NOTE, [1], date=TODAY)),
                 reflection(note(NOTE, [1], date=TODAY))]  # fmt: skip
    coach = [*STUCK, tutor("Not quite yet. Look at the top again.")]
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach, "reflector": reflector})

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        queue = r.core.reflector
        assert queue is not None
        try:
            session = await r.session()
            await _stuck(r, session)
            assert queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics")
            assert not queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics"), "deduped"
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 1)
            await _turn(r, session, "s = 5 m", "answer")  # the student's turn cancels the running reflection
            await queue.idle()
            again = queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics")
            await queue.idle()
            conn = r.runtime.learner.conn
            cursors = conn.execute("SELECT count(*) FROM audit_log WHERE action = ?", (JOB_ACTION,)).fetchone()[0]
            written = conn.execute("SELECT count(*) FROM events WHERE type = 'note_written'").fetchone()[0]
            return list(queue.outcomes), _notes(r), again, cursors, written
        finally:
            await stop_core(r)

    outcomes, notes, again, cursors, written = run(scenario())
    assert len(requests_of(provider, "reflector")) == 2, "cancelled once, completed once"
    assert [o.status for _, o in outcomes] == ["applied"]
    assert notes == [(NOTE, "active")] and written == 1, "no duplicate note"
    assert again is False and cursors == 1, "a re-trigger with no new events is skipped"


# --- the queue's gates, scope and hygiene ---------------------------------------------------------------------------


def test_job_gates(tmp_path: Path) -> None:
    """Saving off, a safety flag in the window, or no local candidate: no model call, and only the first two mark the
    window done (a job that could not reach a model is reflected later)."""
    held = store()
    sid = _hints(held, 2)
    held.learner.record("safety_flagged", {"category": "personal_data", "template_id": "tpl.personal_details",
                                           "turn_id": new_ulid()}, source="engine", session_id=sid)  # fmt: skip
    outcome, provider, key = run(_job(tmp_path, held, [reflection(note(NOTE, [1]))]))
    assert (outcome.status, outcome.reason) == ("skipped", "safety_flagged") and requests_of(
        provider, "reflector"
    ) == []
    assert job_cursor(held.conn, sid) == key.cursor_seq
    off = store()
    off_sid = _hints(off, 2)
    off.saving(False)
    outcome, provider, key = run(_job(tmp_path / "off", off, [reflection(note(NOTE, [1]))]))
    assert outcome.reason == "memory_saving_off" and requests_of(provider, "reflector") == []
    assert job_cursor(off.conn, off_sid) == key.cursor_seq

    async def no_local() -> Any:
        engine, provider = await make_engine(tmp_path / "cloud", {"reflector": [reflection(note(NOTE, [1]))]},
                                             worker=False)  # fmt: skip
        provider.installed_models = []  # the runtime has no model the Reflector can run on
        try:
            deps = engine.deps
            model = ReflectorModel(deps.router, deps.assets, deps.settings, deps.bundled_schemas, frozenset())
            fresh = store()
            fresh_sid = _hints(fresh, 2)
            key = JobKey(PROFILE_A, fresh_sid, "problem_end", window_cursor(fresh.conn, fresh_sid))
            done = await reflect(fresh.source(), model, ToolExecutor(deps.registry, deps.settings,
                                                                     deps.executor.spill), key,
                                 session_date=DAY, subject="physics")  # fmt: skip
            return done, provider, job_cursor(fresh.conn, fresh_sid)
        finally:
            await close(engine)

    outcome, provider, cursor = run(no_local())
    assert outcome.reason == "no_local_candidate" and requests_of(provider, "reflector") == [] and cursor == 0


def test_reflector_logs_and_traces_carry_no_learner_text(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    sink: list[dict[str, Any]] = []
    coach = [*STUCK, tutor("Thanks. Go on.")]
    kept = note("Finds a labelled sketch helpful before a formula", [1], date=TODAY)
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach,
                         "reflector": [reflection(kept, summary="You kept going qzvsummary.")]})  # fmt: skip
    caplog.set_level(logging.DEBUG)

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        assert r.core.reflector is not None
        r.core.reflector.trace_sink = sink.append
        try:
            session = await r.session()
            await _stuck(r, session)
            await _turn(r, session, "remember that a labelled sketch qzvrequest helps me first")
            await r.core.reflector.idle()
            return _notes(r)
        finally:
            await stop_core(r)

    notes = run(scenario())
    assert notes == [("Finds a labelled sketch helpful before a formula", "active")]
    assert sink and all(t["kind"] == "job" for t in sink)
    for word in ("labelled sketch", "qzvrequest", "qzvsummary"):
        assert word not in json.dumps(sink) and word not in caplog.text, word


def test_profile_switch_cancels_and_backlog_resumes(tmp_path: Path) -> None:
    """Another profile's activation cancels the queue's jobs; an ended session never reflected is found at the next
    start (AGT-26)."""
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": [*STUCK],
                         "reflector": [reflection(note(NOTE, [1], date=TODAY))]})  # fmt: skip

    async def first() -> str:
        r = await core_with_reflector(tmp_path, provider, reflector_idle_delay_s=3600.0)  # never idle long enough
        try:
            session = await r.session()
            await _stuck(r, session)
            queue = r.core.reflector
            assert queue is not None
            queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics")
            assert queue.pending
            queue.cancel_profile("prof_local")
            assert not queue.pending
            r.core.records.end(session, None, r.core.clock_ms())  # the session ends; its job waits for idle time
            assert [j.key.point for j in queue.pending] == ["session_end"]
            return session
        finally:
            await stop_core(r)  # the app closes before the job ran

    session = run(first())
    assert requests_of(provider, "reflector") == []

    async def second() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        try:
            await r.core.reflector.idle()
            conn = r.runtime.learner.conn
            return [k.point for k, _ in r.core.reflector.outcomes], conn.execute(
                "SELECT summary FROM sessions WHERE session_id = ?", (session[4:],)).fetchone()[0]  # fmt: skip
        finally:
            await stop_core(r)

    points, summary = run(second())
    assert points == ["session_end"] and summary, "the next start reflects the session that was never reflected"
    assert len(requests_of(provider, "reflector")) == 1


def test_announced_note_reply_is_contract_valid(tmp_path: Path) -> None:
    """`memory.saved` carries the note id, its text and the Undo deadline, on the session's stream (MEM-11)."""
    coach = [*STUCK, tutor("Thanks. Go on.")]
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach,
                         "reflector": [reflection(note("Finds a labelled sketch helpful before a formula", [1],
                                                       date=TODAY))]})  # fmt: skip

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider)
        try:
            session = await r.session()
            await _stuck(r, session)
            await _turn(r, session, "remember that a labelled sketch helps me first")
            await r.core.reflector.idle()
            return [f for f in r.core.sessions[session].engine.events.frames if f["event"]["type"] == "memory.saved"]
        finally:
            await stop_core(r)

    saved = run(scenario())
    assert len(saved) == 1
    assert contract_errors("api/events", saved[0]) == []
    assert saved[0]["event"]["note_id"].startswith("mem_") and saved[0]["session_id"].startswith("ses_")


def test_reflector_prompt_is_minimal_and_offers_no_tools(tmp_path: Path) -> None:
    held = store()
    _hints(held, 2)
    _, provider, _ = run(_job(tmp_path, held, [reflection(note(NOTE, [1]))]))
    (call,) = requests_of(provider, "reflector")
    assert not call.get("tools") or all(t["function"]["name"] == "reflection" for t in call["tools"])
    task = user_texts(call)
    assert "<learner-notes>" in task and "[2]" in task and "prob_" not in task
    assert asyncio.iscoroutinefunction(reflect)


def test_queue_starts_jobs_only_between_turns() -> None:
    """The queue starts a job only while no turn runs, and a background job only after the idle delay; an explicit
    request skips the delay (MEM-06: nothing is written mid-step; AGT-26)."""
    clock = [100.0]
    queue = ReflectorQueue(Settings(reflector_idle_delay_s=20.0), lambda: None, ToolExecutor.__new__(ToolExecutor),
                           lambda: None, busy=lambda: True, monotonic=lambda: clock[0])  # fmt: skip
    queue.activity()
    queue.pending.append(ReflectorJob(JobKey(PROFILE_A, new_ulid(), "problem_end", 1), "prof_local", DAY, "physics"))
    assert not queue._ready(), "a turn is running"
    queue.busy = lambda: False
    assert not queue._ready(), "the idle delay has not passed"
    clock[0] += 20.0
    assert queue._ready()
    clock[0] -= 20.0
    queue.pending.appendleft(ReflectorJob(JobKey(PROFILE_A, new_ulid(), "explicit_request", 1), "prof_local", DAY,
                                          "physics", request="a sketch first"))  # fmt: skip
    assert queue._ready(), "an explicit request runs at once after the reply"


def test_live_memory_harness_runs_the_job_entry_point(tmp_path: Path) -> None:
    """The live memory evaluation reflects through the engine's own job (`engine.reflection.reflect`), so it measures
    the code the app ships (EVL-01)."""
    from jana_tools.harness import memory as harness

    seeded = harness.seed(harness.candidates())
    kept = note("Forgets to subtract the starting speed when finding acceleration", [1, 2], date=seeded.session_date)

    async def scenario() -> Any:
        engine, provider = await make_engine(tmp_path, {"reflector": [reflection(kept)]}, worker=False)
        try:
            return await harness._reflect(engine, seeded, harness._labels(), Settings()), provider
        finally:
            await close(engine)

    (made, outcome), provider = run(scenario())
    assert outcome == "applied" and len(made) == 1 and len(requests_of(provider, "reflector")) == 1


# --- the review's fixes: the job cursor, a forget during a job, the cap on restarts -------------------------------


def test_explicit_request_keeps_the_window_for_the_next_write_point(tmp_path: Path) -> None:
    """An explicit request's job records its own audit entry, never the shared job cursor: the hints before it are
    still reflected at the next write point even when nothing happened since (AGT-26, MEM-06)."""
    held = store()
    sid = _hints(held, 3)

    async def go() -> Any:
        engine, _ = await make_engine(tmp_path, {"reflector": [reflection(note(NOTE, [1], date=DAY))]}, worker=False)
        try:
            d = engine.deps
            model = ReflectorModel(d.router, d.assets, d.settings, d.bundled_schemas, frozenset(d.registry.specs))
            key = JobKey(PROFILE_A, sid, "explicit_request", window_cursor(held.conn, sid))
            return await reflect(held.source(), model, ToolExecutor(d.registry, d.settings, d.executor.spill), key,
                                 session_date=DAY, subject="physics", request="sketches help me first")  # fmt: skip
        finally:
            await close(engine)

    outcome = run(go())
    assert outcome.status == "applied" and outcome.applied is not None and len(outcome.applied.applied) == 1
    assert job_cursor(held.conn, sid) == 0 < window_cursor(held.conn, sid)
    queue = ReflectorQueue(Settings(), lambda: None, ToolExecutor.__new__(ToolExecutor), held.source)
    assert queue.trigger("problem_end", "prof_local", sid, session_date=DAY, subject="physics")


def test_a_note_forgotten_during_a_job_is_not_written_back(tmp_path: Path) -> None:
    """A forget while the Reflector is thinking: the job's add of the same text is refused (`forgotten`), so the
    deleted note never comes back from a view taken before it was deleted (LRN-37, MEM-14)."""
    held = store()
    sid = _hints(held, 2)
    text = "Checks the units qzvforgotten at the end of each answer"
    note_id = held.note(text, sid)

    def thinking(body: dict[str, Any]) -> dict[str, Any]:
        from agent_core.memory.write import compact_storage, forget

        assert forget(held.learner, note_id, "student") is not None  # the student forgets it meanwhile
        compact_storage(held.conn)
        return reflection(note(text, [1], date=DAY))

    async def go() -> Any:
        engine, _ = await make_engine(tmp_path, {"reflector": [thinking]}, worker=False)
        try:
            d = engine.deps
            model = ReflectorModel(d.router, d.assets, d.settings, d.bundled_schemas, frozenset(d.registry.specs))
            key = JobKey(PROFILE_A, sid, "problem_end", window_cursor(held.conn, sid))
            return await reflect(held.source(), model, ToolExecutor(d.registry, d.settings, d.executor.spill), key,
                                 session_date=DAY, subject="physics")  # fmt: skip
        finally:
            await close(engine)

    outcome = run(go())
    assert outcome.applied is not None and [r.code for r in outcome.applied.rejected] == ["forgotten"]
    texts = [t for (t,) in held.conn.execute("SELECT text FROM notes")]
    assert text not in texts and "qzvforgotten" not in " ".join(texts)


def test_a_forget_restarts_the_running_job_and_restarts_are_capped(tmp_path: Path) -> None:
    """A forget (API or Undo) cancels the open profile's running job and puts it back, to start from a fresh view;
    a job paused more than `reflector_max_starts` times is left for the next write point, and an explicit request
    left that way is declined in its turn (AGT-26, MEM-11)."""
    stall = [reflection(note(NOTE, [1], date=TODAY), stall=30.0) for _ in range(4)]
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": [*STUCK, tutor(SAFE)],
                         "reflector": [*stall[:1], reflection(note(NOTE, [1], date=TODAY)), *stall[1:]]})  # fmt: skip

    async def scenario() -> Any:
        r = await core_with_reflector(tmp_path, provider, reflector_max_starts=2)
        queue = r.core.reflector
        assert queue is not None
        try:
            session = await r.session()
            await _stuck(r, session)
            assert queue.trigger("idle", "prof_local", session, session_date=TODAY, subject="physics")
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 1)
            r.core.memory_forgotten(new_ulid())  # a note of this profile is forgotten while the job thinks
            await queue.idle()
            first = [(k.point, o.status) for k, o in queue.outcomes]
            # An explicit request whose job is paused again and again: dropped after two starts, and declined.
            turn = await _turn(r, session, "remember that a labelled sketch helps me first")
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 3)
            assert queue.pause()
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 4)
            assert queue.pause()
            await queue.idle()
            frames = r.core.sessions[session].engine.events.frames
            declines = [(f["turn_id"], f["event"]["message_key"]) for f in frames if f["event"]["type"] == "notice"]
            return first, [(k.point, o.status, o.reason) for k, o in queue.outcomes], turn, declines
        finally:
            await stop_core(r)

    first, outcomes, turn, declines = run(scenario())
    assert first == [("idle", "applied")], "cancelled by the forget, started again and applied once"
    assert len(requests_of(provider, "reflector")) == 4
    assert outcomes[-1] == ("explicit_request", "dropped", "too_many_starts")
    assert declines == [(turn, "memory.declined")]
