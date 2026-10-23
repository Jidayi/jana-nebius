"""CUR-36, ASM-23, D98: after a re-mark, misconception evidence follows its verdict and every reader of verdicts
reads a superseded verdict as its latest re-mark.

Synthetic items and learners only. The wrong key's item claims that the truly right option shows a misconception;
the control learner answers the same questions at the same times with the corrected key from the start. After the
re-mark, the wrong-key learner's misconceptions must equal the control's, and each reader of verdicts (the session
summary, the Reflector's input, "help with this item", research rows) must give what it gives for the control."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine.assessment.remark import remark_withdrawn
from agent_core.engine.assessment.service import AssessmentDesk
from agent_core.learner.remark import pending_notice, take_notice
from agent_core.learner.service import NOTES_WRITER, NewEvent
from agent_core.memory.reflect_input import JobKey, build_input
from agent_core.memory.write import code_summary
from agent_core.store.exports import research_rows
from agent_core.store.ids import new_ulid
from test_m24_remark import DAY, KC, OTHER, Clock, answer, index, make_desk, model

OLD = "itm.mth.o.number.0001"  # shipped with a wrong key: option b marked correct
NEW = "itm.mth.o.number.0002"  # the correction: option a correct
WRONG_CLAIM = "mc.mth.o.adds_the_rate"  # the wrong key's claim on the truly right option a
REAL = "mc.mth.o.drops_the_carry"  # option c's misconception, under either key
SESSION = "0" * 26


def keyed(item_id: str, key: str, claims: dict[str, str]) -> dict[str, Any]:
    options = [{"id": x, "text": x, "correct": x == key, "misconception_id": None if x == key else claims.get(x)}
               for x in "abcd"]  # fmt: skip
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


WRONG = keyed(OLD, "b", {"a": WRONG_CLAIM, "c": REAL})
RIGHT_OLD = keyed(OLD, "a", {"c": REAL})
CORRECTED = keyed(NEW, "a", {"c": REAL})
OTHER_ITEM = keyed(OTHER, "a", {})
# The student's answers: option a is truly right; option c shows the real misconception.
HISTORY = [(OLD, "a"), (OTHER, "a"), (OLD, "a"), (OLD, "c"), (OTHER, "c"), (OLD, "a")]


def answer_all(desk: AssessmentDesk, clock: Clock, keyed_items: dict[str, dict[str, Any]]) -> None:
    state = {"id": SESSION, "kind": "practice", "subject": "mathematics"}
    for n, (item_id, option) in enumerate(HISTORY):
        clock.wall = 1_800_000_000_000 + n * DAY // 2
        shown = keyed_items[item_id]
        verdicts = asyncio.run(desk._mark(shown, answer(option)))
        _, events, transcript = desk._attempt_events(state, shown, verdicts, answer(option), 30_000)
        desk.learner.record_batch(events, extra=lambda conn, stored, t=transcript: t())


@pytest.fixture
def learners(tmp_path: Path):
    clock_a, clock_b = Clock(), Clock()
    wrong = make_desk(tmp_path, "wrong", index(WRONG, CORRECTED, OTHER_ITEM), clock_a)
    control = make_desk(tmp_path, "control", index(RIGHT_OLD, OTHER_ITEM), clock_b)
    answer_all(wrong, clock_a, {OLD: WRONG, OTHER: OTHER_ITEM})
    answer_all(control, clock_b, {OLD: RIGHT_OLD, OTHER: OTHER_ITEM})
    clock_a.wall += 3 * DAY
    yield wrong, control
    wrong.learner.conn.close()
    control.learner.conn.close()


def misconceptions(desk: AssessmentDesk) -> dict[str, tuple[str, int]]:
    rows = desk.learner.conn.execute("SELECT misconception_id, status, evidence_count FROM learner_misconceptions")
    return {r[0]: (r[1], r[2]) for r in rows}


def test_a_wrong_keys_misconception_is_withdrawn_and_the_corrected_one_counts_once(learners):
    """The wrong key's claim disappears from the learner model with its verdicts; the misconception the corrected
    marking also finds is counted once, not once per marking; the model equals the control's (DAT-05)."""
    wrong, control = learners
    assert WRONG_CLAIM in misconceptions(wrong)
    report = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert report.evidence_recorded == 1 and report.appended == 4  # option c's match, recorded with its re-mark
    assert report.projections_equal_full_replay
    assert misconceptions(wrong) == misconceptions(control) == {REAL: ("suspected", 1)}
    assert model(wrong) == model(control)
    again = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert again.appended == again.evidence_recorded == 0
    assert misconceptions(wrong) == {REAL: ("suspected", 1)}


def test_evidence_arriving_on_a_remarked_attempt_folds_as_a_rebuild_would(learners):
    """Evidence naming a re-marked attempt that lands after the re-mark replays the projections, so the incremental
    tables equal a rebuild (DAT-05)."""
    wrong, _ = learners
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    attempt = wrong.learner.conn.execute(
        "SELECT json_extract(payload, '$.attempt_id') FROM events WHERE type = 'verdict'"
        " AND json_extract(payload, '$.supersedes') IS NOT NULL ORDER BY seq LIMIT 1"
    ).fetchone()[0]
    late = {"misconception_id": WRONG_CLAIM, "kc_id": KC, "evidence_source": "signature", "attempt_id": attempt,
            "weight": 1.0}  # fmt: skip
    wrong.learner.record_batch([NewEvent("misconception_evidence", late, source="engine", session_id=SESSION)])
    checksum = wrong.learner.projector.checksum()
    wrong.learner.projector.rebuild()
    assert wrong.learner.projector.checksum() == checksum


def test_readers_take_a_remarked_verdict_as_its_latest_remark(learners):
    """Session summary (MEM-22), the Reflector's input (MEM-06), help with an item and research rows (EVL-22)."""
    wrong, control = learners
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    settings = Settings()
    assert code_summary(wrong.learner.conn, "ses_" + SESSION, "mathematics") == code_summary(
        control.learner.conn, "ses_" + SESSION, "mathematics"
    )
    assert wrong.item_verdicts(SESSION, OLD)[1:] == control.item_verdicts(SESSION, OLD)[1:]
    assert wrong.item_verdicts(SESSION, OLD)[1] == ["correct", "correct", "incorrect", "correct"]

    class Labels:
        def misconception_name(self, mc_id: str) -> str | None:
            return mc_id

        def kc_statement(self, kc_id: str) -> str | None:
            return kc_id

    def lines(desk: AssessmentDesk) -> list[str]:
        key = JobKey("p", "ses_" + SESSION, "session_end", 0)
        task = build_input(desk.learner.conn, Labels(), key, settings, session_date="2027-01-15",  # type: ignore[arg-type]
                           subject="mathematics").task  # fmt: skip
        found = [line for line in task.splitlines() if line.startswith("[")]
        return [line.split("] ", 1)[1] for line in found if "checked" in line or "mistake matched" in line]

    def strip(found: list[str]) -> list[str]:
        return [line.split(" (for evidence")[0] for line in found]

    assert strip(lines(wrong)) == strip(lines(control))
    assert not any(WRONG_CLAIM in line for line in lines(wrong))

    def research(desk: AssessmentDesk) -> list[tuple[str, Any]]:
        rows = research_rows(desk.learner.conn)["events"]
        return [(e["type"], e["payload"].get("outcome")) for e in rows if e["type"] == "verdict"]

    assert research(wrong) == research(control)


def test_asm23_remark_notice_waits_until_told(learners):
    """ASM-23: a re-mark that changed results leaves one notice waiting in the learner database, with the number of
    results changed; it is taken once, and a re-mark that changes nothing adds none."""
    wrong, _ = learners
    report = asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert report.changed_results == 3
    assert pending_notice(wrong.learner.conn) == 3
    assert take_notice(wrong.learner.conn, 1) == 3
    assert take_notice(wrong.learner.conn, 2) == 0
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    assert pending_notice(wrong.learner.conn) == 0
    rows = wrong.learner.conn.execute("SELECT detail FROM audit_log WHERE action = 'remark.notice'").fetchall()
    assert [json.loads(r[0]) for r in rows] == [{"changed_results": 3}]


def test_a_note_resting_only_on_the_wrong_key_is_withdrawn(learners):
    """A Reflector note written from the wrong key's verdicts and match is withdrawn with them; a note that also
    cites a marking the re-mark left standing, and a note written after the re-mark, stay (CUR-36, MEM-06)."""
    wrong, _ = learners
    conn = wrong.learner.conn

    def ids(sql: str, value: str) -> list[str]:
        return [r[0] for r in conn.execute(sql, (value,))]

    claims = "SELECT event_id FROM events WHERE type = 'misconception_evidence'"
    claims += " AND json_extract(payload, '$.misconception_id') = ? ORDER BY seq"
    on_item = "SELECT v.event_id FROM events v JOIN events a ON a.type = 'attempt'"
    on_item += " AND json_extract(a.payload, '$.attempt_id') = json_extract(v.payload, '$.attempt_id')"
    on_item += " WHERE v.type = 'verdict' AND json_extract(a.payload, '$.item_id') = ? ORDER BY v.seq"
    wrong_claims, old_verdicts, other_verdicts = ids(claims, WRONG_CLAIM), ids(on_item, OLD), ids(on_item, OTHER)

    def note(sources: list[str]) -> str:
        note_id = new_ulid()
        payload = {"note_id": note_id, "text": "Synthetic note.", "subject": "mathematics", "kc_ids": [KC],
                   "source_event_ids": sources, "status": "active"}  # fmt: skip
        wrong.learner.record("note_written", payload, source="reflector", session_id=SESSION, writer=NOTES_WRITER)
        return note_id

    only_wrong = note([old_verdicts[0], wrong_claims[0]])
    mixed = note([old_verdicts[1], other_verdicts[0]])
    asyncio.run(remark_withdrawn(wrong, OLD, NEW))
    after = note([old_verdicts[0]])  # written from the corrected marking, which that event now reads as

    def status(note_id: str) -> str:
        return str(conn.execute("SELECT status FROM notes WHERE note_id = ?", (note_id,)).fetchone()[0])

    assert (status(only_wrong), status(mixed), status(after)) == ("deleted", "active", "active")
    checksum = wrong.learner.projector.checksum()
    wrong.learner.projector.rebuild()
    assert wrong.learner.projector.checksum() == checksum
