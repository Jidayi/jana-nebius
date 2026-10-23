"""Mastery pool diversity and waiting-check locks across the installed-subject paths."""

import hashlib
import math

import pytest
from agent_core.engine.assessment.service import Refused
from test_m16_assessment import KC, answer, item, run
from test_m16_assessment import desk as fixture_desk

desk = fixture_desk


def test_extra_mock_reserve_keeps_three_available_surfaces(desk):
    d, _ = desk
    bank = [item(n) for n in range(100, 120)]
    by_hash = sorted(bank, key=lambda i: hashlib.sha256(i["id"].encode()).digest())
    for i in bank:
        i["template_id"] = "repeat"
    by_hash[0]["template_id"], by_hash[1]["template_id"] = "unique-b", "unique-c"
    d.content.records["mock_papers"] = {}
    d.content.records["items"] = {i["id"]: i for i in bank}
    reserved = d._reserved()
    assert len(reserved) == math.ceil(len(bank) * d.settings.mock_reserved_bank_share)
    assert len({d._surface(i) for i in d.eligible("mastery_check", [KC], "mathematics")}) == 3
    d.content.records["items"] = dict(reversed(list(d.content.records["items"].items())))
    assert d._reserved() == reserved


def test_incomplete_mastery_pool_waits_without_exposing_or_locking(desk):
    d, _ = desk
    bank = [item(n) for n in range(100, 120)]
    for i in bank:
        i["template_id"] = "same"
    d.content.records["mock_papers"] = {}
    d.content.records["items"] = {i["id"]: i for i in bank}
    state = d.start_assessment("mastery_check", "mathematics", KC)
    assert state["state"] == "waiting" and state["current_item"] is None and state["answered_count"] == 0
    assert not any(e.type == "item_exposed" for e in d.learner.log.by_seq())
    d.guard_tutor()
    for n in (121, 122):
        new = item(n)
        d.content.records["items"][new["id"]] = new
    state = d.assessment(state["assessment_id"])
    assert state["state"] == "in_progress" and state["current_item"] is not None
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()


def _waiting(d, clock):
    state = d.start_assessment("mastery_check", "mathematics", KC)
    for n in range(2):
        state = run(d.assessment_answer(state["assessment_id"], str(n), state["current_item"]["item_id"], answer()))
    clock.advance(24 * 3_600_000)
    return state


def test_listing_a_due_check_does_not_serve_or_lock(desk):
    d, clock = desk
    state = _waiting(d, clock)
    exposures = [e for e in d.learner.log.by_seq() if e.type == "item_exposed"]
    listed = d.list_assessments()[0]
    assert listed["state"] == "waiting" and listed["current_item"] is None
    assert len([e for e in d.learner.log.by_seq() if e.type == "item_exposed"]) == len(exposures)
    d.guard_tutor()
    assert d.assessment(state["assessment_id"])["current_item"] is not None
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()


def test_stopping_a_due_check_does_not_serve_or_lock(desk):
    d, clock = desk
    state = _waiting(d, clock)
    exposures = [e for e in d.learner.log.by_seq() if e.type == "item_exposed"]
    stopped = d.stop_assessment(state["assessment_id"])
    assert stopped["state"] == "stopped" and stopped["current_item"] is None
    assert len([e for e in d.learner.log.by_seq() if e.type == "item_exposed"]) == len(exposures)
    d.guard_tutor()
    assert d.resume_assessment(state["assessment_id"])["current_item"] is not None
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()


def test_presentation_cache_still_validates_changed_content(desk, monkeypatch):
    from agent_core.engine.assessment import items

    d, _ = desk
    source = item(125)
    original = items.errors
    calls = []

    def record(contract, shown):
        calls.append(contract)
        return original(contract, shown)

    monkeypatch.setattr(items, "errors", record)
    items._PRESENTATION_VALID.clear()
    assert items.ready(source, d.content, d.settings, automatic=True)
    assert items.ready(source, d.content, d.settings, automatic=True)
    assert len(calls) == 1
    source["stem"] = 123  # The changed projection must go through the complete schema again.
    assert not items.ready(source, d.content, d.settings, automatic=True)
    assert len(calls) == 2
    source["parts"][0]["answer"]["kind"] = "short_text"
    assert not items.ready(source, d.content, d.settings, automatic=True)


def test_resolving_one_subject_does_not_release_another_subjects_active_check(desk, tmp_path):
    from agent_core.api.core import CoreService
    from agent_core.api.errors import ApiError
    from agent_core.store.pack_index import PackIndex
    from agent_core.store.sessions import SessionStore

    d, _ = desk
    packs = []
    subjects = {"mathematics": "mth", "physics": "phy", "chemistry": "chm", "accounting": "acc"}
    for code in subjects.values():
        kc = f"kc.{code}.o.number.add"
        topic = f"cur.{code}.o.number"
        bank = [item(n) for n in range(100, 120)]
        for source in bank:
            source.update(id=source["id"].replace(".mth.", f".{code}."), kc_ids=[kc])
        packs.append(
            (
                {"pack_id": f"pack.{code}.o", "subject": code, "version": "1.0.0"},
                {
                    "items": bank,
                    "kcs": [
                        {
                            "id": kc,
                            "statement": "Synthetic skill",
                            "node_id": topic,
                            "status": "active",
                            "prerequisites": [],
                            "misconception_ids": [],
                        }
                    ],
                    "curriculum_nodes": [
                        {"id": f"cur.{code}.o", "title": code, "kind": "subject"},
                        {"id": topic, "title": "Synthetic topic", "kind": "topic", "parent_id": f"cur.{code}.o"},
                    ],
                },
            )
        )
    d.content = PackIndex.from_tables(packs)
    core = CoreService(d.settings, lambda entry: None, SessionStore(tmp_path / "tutor"))
    core.assessments = lambda: d
    states = [d.start_assessment("mastery_check", name, f"kc.{code}.o.number.add") for name, code in subjects.items()]
    locked_count = len(states)
    for state in states:
        with pytest.raises(Refused, match="tutor_locked"):
            d.guard_tutor()
        with pytest.raises(ApiError) as blocked:
            core.create_session({})
        assert blocked.value.status == 423 and blocked.value.code == "tutor_locked"
        failed = run(
            d.assessment_answer(state["assessment_id"], state["subject"], state["current_item"]["item_id"], answer("b"))
        )
        assert failed["state"] == "failed" and failed["last_mark"]["verdict"] == "incorrect"
        assert (
            d.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id=?", (state["kc_id"],)).fetchone()[0]
            == "learning"
        )
        with pytest.raises(Refused, match="retry_not_due"):
            d.start_assessment("mastery_check", state["subject"], state["kc_id"])
        locked_count -= 1
        if locked_count:
            with pytest.raises(Refused, match="tutor_locked"):
                d.guard_tutor()
        else:
            d.guard_tutor()
            opened = core.create_session(
                {
                    "client_session_id": "cli_00000000000000000000000001",
                    "mode": "guided",
                    "subject": "physics",
                    "level": "O",
                    "origin": {"kind": "ask", "ref": None},
                }
            )
            assert opened["session_id"].startswith("ses_")
