"""M6.b: the event log, the clock and projections (DAT-04, DAT-05, DAT-16, LRN-01, LRN-02, DAT-12 fixtures)."""

from __future__ import annotations

import itertools
import json
import random
import sqlite3
import threading
import time
from pathlib import Path

import pytest
from agent_core.config.keys import Settings
from agent_core.contracts import document, validate
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.projections import MasteryProjection, Projector
from agent_core.memory.write import NOTES_WRITER
from agent_core.store.events import EventLog, iso_ms, validate_event
from agent_core.store.generated.event_registry import SYNC_CLASS
from agent_core.store.hlc import MAX_COUNTER, MAX_PHYSICAL, PATTERN, ClockRangeError, ClockSkewError, HybridClock, Stamp
from agent_core.store.sqlite import open_database
from agent_core.trace.ids import new_ulid
from learner_harness import (
    DEVICE_A,
    DEVICE_B,
    PROFILE,
    SKEW_MS,
    START_MS,
    Clock,
    Session,
    envelopes,
    learner_db,
    make_learner,
    random_log,
)

CONTRACT_TYPES = {
    branch["properties"]["type"]["const"]
    for branch in document("learning/learning-event")["oneOf"]
    if "const" in branch["properties"]["type"]  # the erased branch takes any type
}


def _session_started(log: EventLog) -> None:
    sid = new_ulid()
    log.append(
        "session_started",
        {"session_id": sid, "mode": "guided", "entry": "question", "hardware_class": "mid"},
        source="engine",
        session_id=sid,
    )


# --- DAT-16 ---------------------------------------------------------------------------------------------------------


def dat16_hlc_encoding_monotonic() -> None:
    rng = random.Random(16)
    wall = Clock()
    conn = learner_db()
    log = EventLog.open(conn, PROFILE, DEVICE_A, wall, SKEW_MS)
    issued = []
    for _ in range(2000):
        # The wall clock jumps backwards and forwards; the stamps never do.
        wall.now += rng.choice((-5000, -1, 0, 0, 0, 1, 7, 3000))
        _session_started(log)
        issued.append(log.clock.last)
    assert all(a < b for a, b in itertools.pairwise(issued))
    stored = [row[0] for row in conn.execute("SELECT hlc FROM events ORDER BY seq")]
    assert all(PATTERN.match(s) for s in stored)
    # String order is (physical, counter) order, across widths of both parts.
    samples = [Stamp(rng.randrange(MAX_PHYSICAL), rng.randrange(MAX_COUNTER + 1)) for _ in range(5000)]
    assert sorted(samples) == sorted(samples, key=lambda s: s.encode())
    assert [Stamp.parse(s.encode()) for s in samples] == samples
    # A restart resumes above the last persisted stamp even when the wall clock is now far behind.
    wall.now = START_MS - 10 * 86_400_000
    restarted = EventLog.open(conn, PROFILE, DEVICE_A, wall, SKEW_MS)
    _session_started(restarted)
    assert restarted.clock.last.encode() > max(stored)


def dat16_future_clock_no_stall() -> None:
    wall = Clock()
    clock = HybridClock(wall, SKEW_MS, Stamp(wall.now, MAX_COUNTER - 1))
    # A far-future remote stamp at counter 99999 is refused before the clock moves.
    before = clock.last
    with pytest.raises(ClockSkewError):
        clock.receive(Stamp(wall.now + 3 * 86_400_000, MAX_COUNTER))
    with pytest.raises(ClockRangeError):
        Stamp.parse("1000000000000000-00000")  # a sixteenth digit does not fit the encoding
    assert clock.last == before
    # At the end of the encoding a merge is refused, not wrapped, and the clock is unchanged.
    edge = HybridClock(lambda: MAX_PHYSICAL, SKEW_MS, Stamp(MAX_PHYSICAL, MAX_COUNTER))
    with pytest.raises(ClockRangeError):
        edge.receive(Stamp(MAX_PHYSICAL, MAX_COUNTER))
    assert edge.last == Stamp(MAX_PHYSICAL, MAX_COUNTER)
    # Local counter rollover moves into the next millisecond at once, with the wall clock frozen.
    conn = learner_db()
    log = EventLog(conn, PROFILE, DEVICE_A, clock)
    started = time.monotonic()
    for _ in range(4):
        _session_started(log)
    assert time.monotonic() - started < 1.0
    stamps = [row[0] for row in conn.execute("SELECT hlc FROM events ORDER BY seq")]
    assert stamps == [
        Stamp(wall.now, MAX_COUNTER).encode(),
        Stamp(wall.now + 1, 0).encode(),
        Stamp(wall.now + 1, 1).encode(),
        Stamp(wall.now + 1, 2).encode(),
    ]
    restarted = EventLog.open(conn, PROFILE, DEVICE_A, wall, SKEW_MS)
    _session_started(restarted)
    assert restarted.clock.last == Stamp(wall.now + 1, 3)


def _two_devices(seed: int) -> tuple[list[dict], list[dict]]:
    """Two of the student's devices recording on their own, with a shared start."""
    a = random_log(seed, sessions=3)
    b = random_log(seed + 1000, sessions=3, learner=make_learner(device=DEVICE_B))
    return envelopes(a), envelopes(b)


def dat16_idempotent_apply() -> None:
    _, remote = _two_devices(7)
    once = make_learner(clock=Clock(START_MS + 400 * 86_400_000))
    once.receive(remote)
    twice = make_learner(clock=Clock(START_MS + 400 * 86_400_000))
    twice.receive(remote)
    assert twice.receive(remote) == []
    overlapping = make_learner(clock=Clock(START_MS + 400 * 86_400_000))
    half = len(remote) // 2
    overlapping.receive(remote[: half + 5])
    overlapping.receive(remote[half - 5 :])
    for other in (twice, overlapping):
        assert other.conn.execute("SELECT count(*) FROM events").fetchone() == (len(remote),)
        assert other.projector.checksum() == once.projector.checksum()


def dat16_hlc_ordering_under_skew() -> None:
    local, remote = _two_devices(11)
    wall = Clock(START_MS + 400 * 86_400_000)
    learner = make_learner(clock=wall)
    learner.receive(local)
    learner.receive(remote)
    merged = list(learner.log.merged())
    assert [e.order for e in merged] == sorted(e.order for e in merged)
    # A batch holding one stamp three days ahead is refused whole: no event, no clock or cursor change.
    clock_before = learner.log.clock.last
    state_before = learner.projector.state("kc_mastery")
    ahead = make_learner(device="c" * 32, clock=Clock(wall.now + 3 * 86_400_000))
    Session(random.Random(3), ahead, ahead.log.clock.wall_ms).run(1)  # type: ignore[arg-type]
    batch = envelopes(ahead)
    count = learner.conn.execute("SELECT count(*) FROM events").fetchone()
    with pytest.raises(ClockSkewError) as refused:
        learner.receive(batch)
    assert refused.value.reason == "clock_skew"
    assert learner.conn.execute("SELECT count(*) FROM events").fetchone() == count
    assert learner.log.clock.last == clock_before
    assert learner.projector.state("kc_mastery") == state_before
    # The sender keeps the batch; once this device's wall clock is within the bound the retry is accepted.
    wall.now += 2 * 86_400_000 + 3_600_000
    assert len(learner.receive(batch)) == len(batch)


# --- DAT-04, LRN-01 -------------------------------------------------------------------------------------------------


def _append_only(conn: sqlite3.Connection) -> None:
    for statement in (
        "UPDATE events SET type = 'hint' WHERE seq = 1",
        "UPDATE events SET hlc = '000000000000000-00000' WHERE seq = 1",
        "UPDATE events SET payload = '{}' WHERE seq = 1",
        'UPDATE events SET payload = \'{"erased":true,"erased_at":"2020-01-01T00:00:00.000Z"}\', erased_at = 5'
        " WHERE seq = 1",
        "DELETE FROM events WHERE seq = 1",
        "DELETE FROM events",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="append-only"):
            conn.execute(statement)


def dat04_events_append_only() -> None:
    learner = random_log(4, sessions=1)
    _append_only(learner.conn)
    # The erasure path keeps id, type, sequence and stamp and replaces only the payload.
    first = next(learner.log.by_seq())
    learner.log.erase(first.event_id, START_MS + 1234)
    erased = learner.log.get(first.event_id)
    assert erased is not None
    assert erased.payload == {"erased": True, "erased_at": iso_ms(START_MS + 1234)}
    assert (erased.seq, erased.type, erased.hlc) == (first.seq, first.type, first.hlc)
    assert erased.erased_at == START_MS + 1234
    _append_only(learner.conn)


def lrn01_append_only_enforced() -> None:
    conn = learner_db()
    log = EventLog.open(conn, PROFILE, DEVICE_A, Clock(), SKEW_MS)
    _session_started(log)
    _append_only(conn)
    # A REPLACE conflict is a delete too: rewriting an event through it is refused.
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        conn.execute(
            "INSERT OR REPLACE INTO events (seq, event_id, profile_id, device_id, origin_seq, hlc, type,"
            " schema_version, source, sync_class, occurred_at, recorded_at, payload)"
            " SELECT seq, event_id, profile_id, device_id, origin_seq, hlc, type, schema_version, source, sync_class,"
            " occurred_at, recorded_at, '{}' FROM events WHERE seq = 1"
        )


def dat04_event_registry_complete() -> None:
    # Every type the contract defines has exactly one sync class, and the registry names no other type.
    assert set(SYNC_CLASS) == CONTRACT_TYPES
    assert set(SYNC_CLASS.values()) <= {"local", "consented"}
    learner = random_log(5, sessions=6)
    emitted = {row[0] for row in learner.conn.execute("SELECT DISTINCT type FROM events")}
    assert emitted <= set(SYNC_CLASS)
    for type_, sync_class in learner.conn.execute("SELECT type, sync_class FROM events"):
        assert SYNC_CLASS[type_] == sync_class


def dat04_events_validate_against_contract() -> None:
    learner = random_log(6, sessions=5)
    for event in list(learner.log.by_seq())[::7]:
        learner.erase(event.event_id, START_MS)
    for event in learner.log.by_seq():
        validate("learning/learning-event", event.envelope())
    with pytest.raises(ValueError, match="learning/learning-event"):
        learner.record("hint", {"session_id": new_ulid(), "rung": 9}, source="engine")
    with pytest.raises(ValueError, match="learning/learning-event"):
        learner.record("attempt", {"attempt_id": new_ulid()}, source="student")


def lrn01_schema_round_trip() -> None:
    clock = Clock()
    learner = make_learner(clock=clock)
    rng = random.Random(1)
    while learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] < 10_000:
        Session(rng, learner, clock).run(rng.randint(1, 6))
    stored = envelopes(learner)
    for envelope in stored:
        validate_event(envelope)
    for envelope in stored[::50]:
        validate("learning/learning-event", envelope)  # the whole oneOf agrees with the branch check
    # The same events applied on another device come back unchanged, field for field.
    other = make_learner(device=DEVICE_B, clock=Clock(clock.now))
    other.receive(stored)
    assert envelopes(other) == stored


FREE_TEXT_FIELDS = {"normalised_response", "text"}


def _strings(value: object, path: str = "") -> list[tuple[str, str]]:
    if isinstance(value, str):
        return [(path, value)]
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in _strings(v, k)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v, path)]
    return []


def lrn01_no_free_text_payload() -> None:
    learner = random_log(8, sessions=10)
    for event in learner.log.by_seq():
        for key, text in _strings(event.payload):
            assert len(text) <= 200, (event.type, key)
            if key in FREE_TEXT_FIELDS:
                assert (event.type, key) in {("attempt", "normalised_response"), ("note_written", "text")}
    # The contract itself bounds every string a payload can hold (identifiers, refs, enums or short text).
    for name, definition in document("learning/learning-event")["$defs"].items():
        if name.startswith("payload_"):
            for prop, spec in definition.get("properties", {}).items():
                if spec.get("type") == "string" and "pattern" not in spec and "format" not in spec:
                    assert spec.get("maxLength", 10**9) <= 200, (name, prop)


def dat04_no_free_text_in_events() -> None:
    # Canary strings stand for student and tutor text; a session's events never carry them, except a Reflector note
    # (erasable, sync class local).
    canary = "ZEBRA-CANARY-7741"
    learner = random_log(9, sessions=4)
    learner.record(
        "note_written",
        {"note_id": new_ulid(), "text": f"note {canary}", "source_event_ids": [new_ulid()], "status": "active"},
        source="reflector",
        writer=NOTES_WRITER,
    )
    for event in learner.log.by_seq():
        if canary in json.dumps(event.payload):
            assert event.type == "note_written" and event.sync_class == "local"
            learner.erase(event.event_id, START_MS)
    assert learner.conn.execute("SELECT count(*) FROM notes WHERE text LIKE ?", (f"%{canary}%",)).fetchone() == (0,)
    dump = "\n".join(json.dumps(r) for r in learner.conn.execute("SELECT payload FROM events"))
    assert canary not in dump


# --- DAT-05, LRN-02 -------------------------------------------------------------------------------------------------


def dat05_incremental_equals_rebuild() -> None:
    for seed in range(1000):
        learner = random_log(seed, sessions=random.Random(seed).randint(1, 3))
        incremental = learner.projector.checksum()
        learner.projector.rebuild()
        assert learner.projector.checksum() == incremental, seed


def lrn02_incremental_equals_rebuild() -> None:
    # After every single event, the incremental tables equal a rebuild over the log up to that event.
    reference = random_log(42, sessions=4)
    events = envelopes(reference)
    learner = make_learner(device=DEVICE_B, clock=Clock(START_MS + 400 * 86_400_000))
    for envelope in events:
        learner.receive([envelope])
        incremental = learner.projector.checksum()
        rebuilt = make_learner(device=DEVICE_B, clock=Clock(START_MS + 400 * 86_400_000))
        rebuilt.log.apply_remote(events[: events.index(envelope) + 1])
        rebuilt.projector.rebuild()
        assert rebuilt.projector.checksum() == incremental


def lrn02_equal_hlc_replay() -> None:
    # Two devices record at the same wall millisecond: equal stamps, ordered by device id. The lower device id's
    # events arriving last forces a replay; both arrival orders give the same tables, incremental and rebuilt.
    a = make_learner(device=DEVICE_A, clock=Clock())
    b = make_learner(device=DEVICE_B, clock=Clock())
    Session(random.Random(1), a, a.log.clock.wall_ms).run(2)  # type: ignore[arg-type]
    Session(random.Random(1), b, b.log.clock.wall_ms).run(2)  # type: ignore[arg-type]
    ea, eb = envelopes(a), envelopes(b)
    assert {e["hlc"] for e in ea} & {e["hlc"] for e in eb}
    results = []
    for first, second in ((ea, eb), (eb, ea)):
        learner = make_learner(device="c" * 32, clock=Clock(START_MS + 86_400_000))
        learner.receive(first)
        learner.receive(second)
        incremental = learner.projector.checksum()
        learner.projector.rebuild()
        assert learner.projector.checksum() == incremental
        results.append(incremental)
    assert results[0] == results[1]


def lrn02_replay_deterministic() -> None:
    learner = random_log(3, sessions=5)
    dumps = []
    for _ in range(2):
        learner.projector.rebuild()
        dumps.append(
            [learner.conn.execute(f"SELECT * FROM {t} ORDER BY 1").fetchall()  # noqa: S608
             for p in learner.projector.projections for t in p.tables]
        )  # fmt: skip
    assert dumps[0] == dumps[1]


def dat05_rebuild_on_version_change(tmp_path: Path) -> None:
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    random_log(2, sessions=3, learner=make_learner(conn))
    # Restarting with the same code rebuilds nothing.
    assert Projector(conn, MasteryParams()).ensure_current() == []

    class Newer(MasteryProjection):
        code_version = "pfa_elo.m6.next"

    reader = sqlite3.connect(tmp_path / "learner.db")
    before = reader.execute("SELECT count(*) FROM kc_mastery").fetchone()
    projector = Projector(conn, MasteryParams(), projections=[Newer()])
    assert projector.stale() == ["kc_mastery"]
    assert projector.ensure_current() == ["kc_mastery"]
    assert projector.ensure_current() == []  # exactly one rebuild
    assert reader.execute("SELECT count(*) FROM kc_mastery").fetchone() == before
    assert conn.execute("SELECT code_version FROM projection_state WHERE name = 'kc_mastery'").fetchone() == (
        "pfa_elo.m6.next",
    )


def lrn02_param_change_rebuild(tmp_path: Path) -> None:
    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner")
    learner = random_log(12, sessions=40, learner=make_learner(conn))
    old = learner.projector.checksum("kc_mastery")
    old_rows = json.dumps(conn.execute("SELECT kc_id, p_mastery FROM kc_mastery ORDER BY kc_id").fetchall())
    # New parameters: the projection is stale and is rebuilt on its own connection while reads continue.
    params = MasteryParams(mastery_gamma_default=0.5)
    worker_conn, _ = open_database(path, "learner")
    projector = Projector(worker_conn, params)
    # Every projection folds with the shared parameter hash, so every one is stale.
    assert set(projector.stale()) == {p.name for p in projector.projections} >= {"attempts", "kc_mastery", "notes"}
    errors: list[BaseException] = []
    seen: set[str] = set()
    done = threading.Event()

    def read() -> None:
        reader = sqlite3.connect(path, check_same_thread=False)
        while not done.is_set():
            try:
                rows = reader.execute("SELECT kc_id, p_mastery FROM kc_mastery ORDER BY kc_id").fetchall()
                assert rows
                seen.add(json.dumps(rows))
            except BaseException as error:
                errors.append(error)
        reader.close()

    thread = threading.Thread(target=read)
    thread.start()
    projector.ensure_current()
    done.set()
    thread.join()
    assert errors == []
    assert projector.checksum("kc_mastery") != old
    # Readers saw the old table or the new one, never a half-built one.
    final = json.dumps(conn.execute("SELECT kc_id, p_mastery FROM kc_mastery ORDER BY kc_id").fetchall())
    assert seen <= {old_rows, final}
    assert projector.stale() == []


def dat05_rebuild_time_budget() -> None:
    settings = Settings()
    clock = Clock()
    learner = make_learner(clock=clock)
    rng = random.Random(5)
    while learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] < settings.projection_rebuild_budget_events:
        Session(rng, learner, clock).run(rng.randint(2, 6))
        clock.now += rng.randint(3_600_000, 3 * 86_400_000)
    started = time.perf_counter()
    learner.projector.rebuild()
    elapsed = time.perf_counter() - started
    # Measured on the development machine; the low hardware class reference laptop runs in the device lab (M7).
    assert elapsed <= settings.projection_rebuild_budget_s, f"{elapsed:.2f} s"


# --- DAT-12 ---------------------------------------------------------------------------------------------------------


def dat12_migrate_all_fixtures(tmp_path: Path) -> None:
    # No version has been released yet: the fixture corpus is one synthetic database per schema version so far.
    from agent_core.store.sqlite import MIGRATIONS

    for version in sorted({m.version for m in MIGRATIONS["learner"]}):
        path = tmp_path / f"learner-v{version}.db"
        conn, _ = open_database(path, "learner", [m for m in MIGRATIONS["learner"] if m.version <= version])
        learner = random_log(version, sessions=4, learner=make_learner(conn))
        before = learner.projector.checksum()
        conn.close()
        migrated, _ = open_database(path, "learner")
        projector = Projector(migrated, MasteryParams())
        projector.rebuild()
        assert projector.checksum() == before
        migrated.close()
