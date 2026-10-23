"""CUR-36, ASM-23, OPS-27: a withdrawn item's attempts re-marked against its corrected key, on the device only.

Synthetic items and learners only. The control learner answers the same questions at the same times with the
corrected key in place from the start: after the re-mark, the wrong-key learner's model must equal it."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine.assessment.remark import job_id, remark_withdrawn
from agent_core.engine.assessment.service import AssessmentDesk, aggregate_verdict
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.remark import marked_attempts, original_evidence_sha256, remark_payload
from agent_core.learner.service import Learner, NewEvent
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database

KC = "kc.mth.o.number.add"
TOPIC = "cur.mth.o.number"
OLD = "itm.mth.o.number.0001"  # shipped with a wrong key: option b marked correct
NEW = "itm.mth.o.number.0002"  # the correction, under a new id: option a correct
OTHER = "itm.mth.o.number.0003"  # an unrelated item, keyed correctly throughout


def item(item_id: str, key: str) -> dict[str, Any]:
    options = [{"id": x, "text": x, "correct": x == key, "misconception_id": None} for x in "abcd"]
    return {
        "id": item_id,
        "type": "mcq",
        "stem": "Synthetic sum",
        "kc_ids": [KC],
        "template_id": item_id,
        "review": {"status": "published"},
        "difficulty": {"prior": 0},
        "parts": [{"id": "a", "prompt": "Choose", "marks": 1,
                   "answer": {"kind": "mcq", "diagnostic": False, "check_id": "chk_fixture", "options": options}}],
    }  # fmt: skip


def index(*items: dict[str, Any]) -> PackIndex:
    kc = {"id": KC, "statement": "Add", "node_id": TOPIC, "code": "add", "status": "active", "prerequisites": [],
          "misconception_ids": []}  # fmt: skip
    nodes = [{"id": "cur.mth.o", "title": "Math", "kind": "subject"},
             {"id": TOPIC, "title": "Number", "kind": "topic", "parent_id": "cur.mth.o"}]  # fmt: skip
    manifest = {"pack_id": "pack.mth.o", "version": "1.0.1", "subject": "mth"}
    return PackIndex.from_tables([(manifest, {"items": list(items), "kcs": [kc], "curriculum_nodes": nodes})])


def answer(option: str) -> dict[str, Any]:
    return {"parts": [{"part_id": "a", "kind": "mcq", "option_id": option}]}


class Clock:
    def __init__(self) -> None:
        self.wall = 1_800_000_000_000


def make_desk(tmp_path: Path, name: str, content: PackIndex, clock: Clock) -> AssessmentDesk:
    conn, _ = open_database(tmp_path / f"{name}.db", "learner")
    learner = Learner.open(conn, profile_id="0" * 26, device_id="f" * 32, wall_ms=lambda: clock.wall,
                           max_skew_ms=Settings().sync_clock_skew_max_ms,
                           params=MasteryParams.from_settings(Settings()), content=content)  # fmt: skip
    return AssessmentDesk(learner, content, Settings(), clock_ms=lambda: clock.wall)


# The student's answers, in order: (the item the attempt is at, the option chosen). Option a is truly right.
HISTORY = [(OLD, "a"), (OTHER, "c"), (OLD, "a"), (OTHER, "c"), (OLD, "c"), (OTHER, "c"), (OLD, "a")]
DAY = 86_400_000


def answer_all(desk: AssessmentDesk, clock: Clock, keyed: dict[str, dict[str, Any]]) -> None:
    """Record HISTORY as the assessment does: each attempt with its marker verdict and its kept answer."""
    state = {"id": "0" * 26, "kind": "practice", "subject": "mathematics"}
    for n, (item_id, option) in enumerate(HISTORY):
        clock.wall = 1_800_000_000_000 + n * DAY // 2
        shown = keyed[item_id]
        verdicts = asyncio.run(desk._mark(shown, answer(option)))
        _, events, transcript = desk._attempt_events(state, shown, verdicts, answer(option), 30_000)
        desk.learner.record_batch(events, extra=lambda conn, stored, t=transcript: t())


@pytest.fixture
def learners(tmp_path: Path):
    """A wrong-key learner (the old id shipped with key b) and its control (the old id carried key a all along)."""
    clock_a, clock_b = Clock(), Clock()
    wrong = make_desk(tmp_path, "wrong", index(item(OLD, "b"), item(NEW, "a"), item(OTHER, "a")), clock_a)
    control = make_desk(tmp_path, "control", index(item(OLD, "a"), item(OTHER, "a")), clock_b)
    answer_all(wrong, clock_a, {OLD: item(OLD, "b"), OTHER: item(OTHER, "a")})
    answer_all(control, clock_b, {OLD: item(OLD, "a"), OTHER: item(OTHER, "a")})
    clock_a.wall += 3 * DAY  # the correction lands days later
    yield wrong, control
    wrong.learner.conn.close()
    control.learner.conn.close()


def verdict_events(desk: AssessmentDesk) -> list[tuple[str, dict[str, Any]]]:
    rows = desk.learner.conn.execute("SELECT event_id, payload FROM events WHERE type = 'verdict' ORDER BY seq")
    return [(event_id, json.loads(payload)) for event_id, payload in rows]


def model(desk: AssessmentDesk) -> tuple[Any, ...]:
    """The learner model as the control can be compared with it: every projection's checksum except the attempt
    rows, whose ids are fresh per learner, and those rows without their ids."""
    projector = desk.learner.projector
    tables = tuple(projector.checksum(p.name) for p in projector.projections if p.name != "attempts")
    rows = desk.learner.conn.execute(
        "SELECT item_ref, kc_ids, mode, outcome, hints_used, max_rung, time_ms, error_category, misconception_id,"
        " occurred_at FROM attempts ORDER BY occurred_at"
    ).fetchall()
    return tables, rows


def cur36_withdraw_and_remark(learners):
    """Withdrawing an item with a wrong key and replaying the event log restores the mastery the corrected key
    implies: every attempt at it is re-marked by superseding verdicts, the originals stay as they were, and the
    rebuilt learner model equals the control learner's, table for table."""
    wrong, control = learners
    assert model(wrong) != model(control)
    before = verdict_events(wrong)
    report = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert report.affected_attempts == report.remarked_attempts == 4
    assert report.appended == 4 and report.changed_results == 3  # three right answers were marked wrong
    assert report.original_sha256 == report.retained_sha256
    assert report.projections_equal_full_replay is True
    assert report.job_id == job_id(OLD, NEW)
    after = verdict_events(wrong)
    assert after[: len(before)] == before  # original verdicts never edited (ASM-23)
    appended = [payload for _, payload in after[len(before) :]]
    originals = {p["attempt_id"]: p["verdict_id"] for _, p in before if p["attempt_id"] in
                 {m.attempt["attempt_id"] for m in marked_attempts(wrong.learner, OLD)}}  # fmt: skip
    assert {p["attempt_id"]: p["supersedes"] for p in appended} == originals
    assert model(wrong) == model(control)
    rows = wrong.learner.conn.execute("SELECT outcome FROM attempts WHERE item_ref = ? ORDER BY occurred_at", (OLD,))
    assert [r[0] for r in rows] == ["correct", "correct", "incorrect", "correct"]


def test_remark_twice_appends_nothing(learners):
    wrong, _ = learners
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    checksum = wrong.learner.projector.checksum()
    again = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert again.appended == 0 and again.remarked_attempts == again.affected_attempts == 4
    assert wrong.learner.projector.checksum() == checksum


def test_remark_refuses_a_correction_under_the_same_id_or_not_installed(learners):
    wrong, _ = learners
    with pytest.raises(ValueError, match="new id"):
        asyncio.run(remark_withdrawn(wrong, OLD, OLD))
    with pytest.raises(ValueError, match="not installed"):
        asyncio.run(remark_withdrawn(wrong, OLD, "itm.mth.o.number.0099"))


def test_remark_without_a_kept_answer_withdraws_the_evidence(learners):
    """An attempt whose answer is no longer held (transcript retention) cannot be marked against the correction:
    it is re-marked unverifiable, so the wrong key's evidence stops counting and nothing is invented."""
    wrong, _ = learners
    wrong.learner.conn.execute("DELETE FROM turns")
    report = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert report.remarked_attempts == 4
    assert {m.verdict["outcome"] for m in marked_attempts(wrong.learner, OLD)} == {"unverifiable"}
    assert report.projections_equal_full_replay


def asm23_supersede(learners):
    """Re-marking appends superseding verdicts and rebuilds mastery: a superseding verdict recorded through the
    ordinary write path replays the projections, the original stays, and a chain of re-marks reads as its last."""
    wrong, control = learners
    found = marked_attempts(wrong.learner, OLD)
    first = found[0]
    corrected = aggregate_verdict(asyncio.run(wrong._mark(item(NEW, "a"), answer("a"))))
    payload = corrected.payload(verdict_id="0" * 26, attempt_id=first.attempt["attempt_id"], closes_opportunity=True)
    digest = original_evidence_sha256(wrong.learner, OLD)
    one = remark_payload(first, payload)
    assert one is not None and one["supersedes"] == first.original_id
    wrong.learner.record_batch([NewEvent("verdict", one, source="engine", session_id=first.session_id)])
    checksum = wrong.learner.projector.checksum()
    wrong.learner.projector.rebuild()
    assert wrong.learner.projector.checksum() == checksum  # the write path replayed: incremental equals rebuild
    again = marked_attempts(wrong.learner, OLD)[0]
    assert again.original_id == first.original_id and again.verdict["verdict_id"] == one["verdict_id"]
    # A second re-mark of the same attempt supersedes the first; the chain reads as its last verdict.
    back = copy.deepcopy(first.verdict)
    two = remark_payload(again, back)
    assert two is not None and two["supersedes"] == one["verdict_id"]
    wrong.learner.supersede([NewEvent("verdict", two, source="engine", session_id=first.session_id)])
    assert marked_attempts(wrong.learner, OLD)[0].verdict["verdict_id"] == two["verdict_id"]
    assert original_evidence_sha256(wrong.learner, OLD) == digest
    report = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert report.projections_equal_full_replay
    assert model(wrong) == model(control)


def test_a_later_answer_after_a_remark_folds_as_a_rebuild_would(learners):
    """After a re-mark, new evidence is folded incrementally and still equals a rebuild (DAT-05)."""
    wrong, _ = learners
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    state = {"id": "1" * 26, "kind": "practice", "subject": "mathematics"}
    shown = item(OTHER, "a")
    verdicts = asyncio.run(wrong._mark(shown, answer("a")))
    _, events, transcript = wrong._attempt_events(state, shown, verdicts, answer("a"), 20_000)
    wrong.learner.record_batch(events, extra=lambda conn, stored: transcript())
    checksum = wrong.learner.projector.checksum()
    wrong.learner.projector.rebuild()
    assert wrong.learner.projector.checksum() == checksum


def test_a_supersedes_naming_another_attempt_is_an_ordinary_verdict(learners):
    """A `supersedes` counts only for an earlier verdict of the same attempt in the same session."""
    wrong, _ = learners
    found = marked_attempts(wrong.learner, OLD)
    stray = {**found[1].verdict, "verdict_id": "1" * 26, "attempt_id": found[0].attempt["attempt_id"],
             "supersedes": found[1].original_id, "outcome": "correct"}  # fmt: skip
    wrong.learner.supersede([NewEvent("verdict", stray, source="engine", session_id=found[0].session_id)])
    now = marked_attempts(wrong.learner, OLD)
    assert [m.original_id for m in now] == [m.original_id for m in found] + ["1" * 26]
    assert all(m.verdict["verdict_id"] == m.original_id for m in now)


def withdraw(policy: Any, item_id: str) -> None:
    """A signed safety configuration withdrawing `item_id` for a wrong key (OPS-10, OPS-27); synthetic."""
    from signing_service.hierarchy import dev_signer

    at = "2026-10-16T00:00:00Z"
    entry = {"entry_id": "drill-wrong-key", "target_kind": "item", "target": item_id, "action": "withdraw",
             "reason_code": "wrong_key", "incident_id": "inc_synthetic", "lift_when": None}  # fmt: skip
    doc = {"sequence": 1, "channel": "stable", "issued_at": at, "entries": [entry]}
    assert policy.adopt_safety(dev_signer().sign("safety_configuration", doc, now=at))


def test_runtime_remarks_the_device_only_once_the_item_is_withdrawn(tmp_path: Path):
    """The learner replay port on the device (CUR-36, OPS-27): it refuses an item still in use, and once the
    withdrawal is applied it re-marks the device's learner database against the installed correction."""
    from agent_core.engine.assembly import AppRuntime

    root = Path(__file__).resolve().parents[3]
    runtime = AppRuntime(Settings(), root / "content" / "agent", root / "skills", tmp_path / "data")
    runtime.open_stores("1.0.0")
    content = index(item(OLD, "b"), item(NEW, "a"), item(OTHER, "a"))
    runtime.content = lambda: content  # type: ignore[method-assign]
    assert runtime.stores is not None
    clock = Clock()
    learner = Learner.open(runtime.stores.learner, profile_id=runtime.stores.profile_id,
                           device_id=runtime.stores.device_id, wall_ms=lambda: clock.wall,
                           max_skew_ms=Settings().sync_clock_skew_max_ms,
                           params=MasteryParams.from_settings(Settings()), content=content)  # fmt: skip
    answer_all(AssessmentDesk(learner, content, Settings(), clock_ms=lambda: clock.wall), clock,
               {OLD: item(OLD, "b"), OTHER: item(OTHER, "a")})  # fmt: skip
    with pytest.raises(ValueError, match="not withdrawn"):
        asyncio.run(runtime.remark_withdrawn(OLD, NEW))
    withdraw(runtime.operation_policy(), OLD)
    (report,) = asyncio.run(runtime.remark_withdrawn(OLD, NEW))
    assert report.affected_attempts == report.remarked_attempts == 4 and report.changed_results == 3
    assert report.original_sha256 == report.retained_sha256 and report.projections_equal_full_replay
    (again,) = asyncio.run(runtime.remark_withdrawn(OLD, NEW))
    assert again.appended == 0
