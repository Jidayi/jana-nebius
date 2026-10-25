"""M33.b on the device: the consented research export carries what item analytics (CUR-26, ASM-21) and outcomes by
skill version (SKL-28) need, joined on the device so no session, attempt or profile id leaves it, and names the
consent it was made under, which the authoring system's intake checks (AUT-37).

Synthetic items, answers and skills only: pilot response volume does not exist yet."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.research import export_rows
from agent_core.learner.service import NewEvent
from agent_core.trace.research import project, projected
from test_cur36_remark_readers import OTHER_ITEM, REAL, RIGHT_OLD
from test_m24_remark import DAY, OLD, OTHER, Clock, answer, index, make_desk

APPROVAL = {"student_assent": True, "school_approval_ref": "synthetic-school", "protocol_ref": "synthetic-protocol"}
SKILL = {"name": "mth-o-number-add", "kind": "teaching", "version": "1.2", "sha256": "a" * 64, "delivery": "pushed",
         "receipt": True}  # fmt: skip


def answered(desk: Any, clock: Clock, session: str, history: list[tuple[str, str]], start: int) -> None:
    state = {"id": session, "kind": "practice", "subject": "mathematics"}
    items = {OLD: RIGHT_OLD, OTHER: OTHER_ITEM}
    for n, (item_id, option) in enumerate(history):
        clock.wall = 1_800_000_000_000 + (start + n) * DAY // 4
        verdicts = asyncio.run(desk._mark(items[item_id], answer(option)))
        _, events, transcript = desk._attempt_events(state, items[item_id], verdicts, answer(option), 30_000)
        desk.learner.record_batch(events, extra=lambda conn, stored, t=transcript: t())


@pytest.fixture
def desk(tmp_path: Path):
    clock = Clock()
    desk = make_desk(tmp_path, "learner", index(RIGHT_OLD, OTHER_ITEM), clock)
    answered(desk, clock, "1" * 26, [(OLD, "c"), (OTHER, "a"), (OLD, "c")], 0)  # before: one right of three
    answered(desk, clock, "2" * 26, [(OLD, "a")], 3)  # the tutoring session that delivered the skill
    desk.learner.record_batch([NewEvent("skills_delivered", {"turn_id": "3" * 26, "skills": [SKILL]}, "engine",
                                        session_id="2" * 26)])  # fmt: skip
    answered(desk, clock, "4" * 26, [(OLD, "a"), (OTHER, "a"), (OLD, "a")], 4)  # after: three right of three
    yield desk
    desk.learner.conn.close()


def test_cur26_research_export_carries_item_responses(desk):
    """Each first response to a pack item, with its outcome, time and the misconception its distractor shows, and
    never the answer itself or an id."""
    body = export_rows(desk.learner.conn, APPROVAL)
    assert body["kind"] == "research_export"
    assert body["consent"] == {"scope": "research_use", "student_assent": True, "protocol_ref": "synthetic-protocol"}
    responses = body["item_responses"]
    assert [(r["item_id"], r["outcome"], r.get("misconception_id")) for r in responses][:2] == [
        (OLD, "incorrect", REAL), (OTHER, "correct", None)]  # fmt: skip
    assert {r["item_id"] for r in responses} == {OLD, OTHER}
    assert all(set(r) <= {"item_id", "outcome", "time_ms", "misconception_id", "kc_id"} for r in responses)
    text = json.dumps(body)
    assert "synthetic-school" not in text and "0" * 26 not in text and "1" * 26 not in text
    assert projected({k: body[k] for k in ("events", "kc_mastery", "item_responses", "skill_sessions")})


def test_skl28_research_export_carries_skill_sessions(desk):
    """The skill delivered, by (name, version), with the session's hints and the mastery gain on its KCs: the share
    right after the session less the share right before it."""
    (session,) = export_rows(desk.learner.conn, APPROVAL)["skill_sessions"]
    assert session["skills"] == [{"name": SKILL["name"], "version": SKILL["version"]}]
    assert session["hints"] == 0
    assert session["mastery_gain"] == pytest.approx(1.0 - 1 / 3)


def proposed(pointer: str) -> dict[str, Any]:
    """A value proposed in contract-additions-m33b.json (D72), until the specification adopts it."""
    additions = json.loads((Path(__file__).parents[3] / "contract-additions-m33b.json").read_text())["additions"]
    return next(a["value"] for a in additions if a["pointer"] == pointer)


def test_aut37_research_export_body_matches_the_proposed_contract(desk):
    """The body a device seals validates against the proposed ResearchExportBody; one without the student's assent,
    or carrying the answer's words, does not."""
    from jsonschema import Draft202012Validator

    validator = Draft202012Validator(proposed("/$defs/ResearchExportBody"))
    body = export_rows(desk.learner.conn, APPROVAL)
    assert list(validator.iter_errors(body)) == []
    assert list(validator.iter_errors(export_rows(desk.learner.conn, {**APPROVAL, "student_assent": False})))
    wordy = {**body, "item_responses": [{**body["item_responses"][0], "normalised_response": "8 m/s"}]}
    assert list(validator.iter_errors(wordy))


def test_aut37_projection_drops_what_the_intake_refuses():
    """The allow-list the device applies is the one the intake checks: words and ids are dropped, so a payload still
    carrying them is not a projection."""
    raw = {"item_responses": [{"item_id": OLD, "outcome": "correct", "time_ms": 5, "normalised_response": "8 m/s",
                               "attempt_id": "x"}],
           "skill_sessions": [{"skills": [{"name": "Not A Skill", "version": "1.0"}], "hints": 1}]}  # fmt: skip
    kept = project(raw)
    assert kept["item_responses"] == [{"item_id": OLD, "outcome": "correct", "time_ms": 5}]
    assert kept["skill_sessions"] == []
    assert projected(kept) and not projected({**kept, "item_responses": raw["item_responses"]})
