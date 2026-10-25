"""One bounded journey reuses real marking/selection and never promotes Study results to mastery."""

import pytest
from agent_core.engine.assessment.errors import Refused
from agent_core.engine.learning_journey import LearningJourney
from test_m16_assessment import KC, TOPIC, answer, run
from test_m16_assessment import desk as synthetic_assessment


@pytest.fixture
def desk(tmp_path):
    yield from synthetic_assessment.__wrapped__(tmp_path)


def journey(d):
    d.content.records.setdefault("lessons", {})["les.mth.o.number.first"] = {
        "id": "les.mth.o.number.first",
        "kc_ids": [KC],
        "node_id": TOPIC,
    }
    j = LearningJourney(d)
    j.start({"node_id": TOPIC, "kc_id": KC})
    return j


def respond(d, view, option="a", client="cli_first"):
    state = d._get(view["practice_set_id"], "practice")
    return run(d.practice_answer(view["practice_set_id"], client, state["items"][0]["id"], answer(option), 1000))


def test_incorrect_start_lesson_different_independent_check_and_resume(desk):
    d, _ = desk
    j = journey(d)
    assert j.reply()["journey"]["evidence"] == "none"
    initial = j.step("practice")["journey"]
    first_item = d._get(initial["practice_set_id"], "practice")["items"][0]["id"]
    respond(d, initial, "b")
    assert j.reply()["journey"]["phase"] == "repair"
    assert j.reply()["journey"]["evidence"] == "incorrect"
    with pytest.raises(Refused, match="intervention_pending"):
        j.step("check")
    reviewed = j.step("review")["journey"]
    assert reviewed["phase"] == "ready_check" and reviewed["lesson_opened"]
    before = list(d.learner.conn.execute("SELECT * FROM kc_mastery"))
    check = j.step("check")["journey"]
    state = d._get(check["practice_set_id"], "practice")
    assert state["items"][0]["id"] != first_item
    assert j.step("check") == j.reply()  # Retry resumes; it cannot expose another item.
    assert list(d.learner.conn.execute("SELECT * FROM kc_mastery")) == before
    respond(d, check, client="cli_second")
    restored = LearningJourney(d).reply()["journey"]
    assert restored["phase"] == "complete" and restored["evidence"] == "independent_correct"
    assert restored["prior_attempts"] == 2
    assert d.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id=?", (KC,)).fetchone()[0] != "mastered"
    follow_on = j.step("check")["journey"]
    assert follow_on["phase"] == "question" and follow_on["prior_attempts"] == 2
    assert follow_on["practice_set_id"] != check["practice_set_id"]


def test_help_exposed_answer_and_second_try_never_become_independent_success(desk):
    d, _ = desk
    j = journey(d)
    first = j.step("practice")["journey"]
    state = d._get(first["practice_set_id"], "practice")
    d.practice_help(first["practice_set_id"], state["items"][0]["id"])
    respond(d, first)
    assert j.reply()["journey"]["evidence"] == "assisted"
    assert j.reply()["journey"]["phase"] == "repair"
    j.step("review")
    check = j.step("check")["journey"]
    respond(d, check, "b", "cli_miss")
    respond(d, check, "a", "cli_retry")
    assert j.reply()["journey"]["evidence"] == "incorrect"
    assert j.reply()["journey"]["phase"] != "complete"


def test_lesson_tutor_opens_during_journey_review_without_a_new_entry_probe(desk, tmp_path):
    from agent_core.api.core import CoreService
    from agent_core.api.errors import ApiError
    from agent_core.config import Settings
    from agent_core.store.sessions import SessionStore

    d, _ = desk
    j = journey(d)
    lesson_id = j.reply()["journey"]["lesson_id"]
    core = CoreService(Settings(), lambda state: None, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d
    core._installed_lesson = lambda identity: (identity, "Synthetic lesson")
    body = {
        "client_session_id": "cli_" + "0" * 26,
        "mode": "guided",
        "subject": "mathematics",
        "level": "O",
        "origin": {"kind": "lesson", "ref": lesson_id},
    }
    with pytest.raises(ApiError, match="entry probe"):
        core.create_session(body)
    j.step("review")
    assert core.create_session(body)["session_id"]
    assert not list(d.learner.conn.execute("SELECT * FROM kc_mastery"))
    other = "les.mth.o.number.other"
    d.content.records["lessons"][other] = {"id": other, "node_id": TOPIC, "kc_ids": [KC]}
    with pytest.raises(ApiError, match="entry probe"):
        core.create_session({**body, "origin": {"kind": "lesson", "ref": other}})


def test_mapping_requires_installed_ids_and_real_source_match_and_keeps_revision(desk):
    d, _ = desk
    j = LearningJourney(d)
    with pytest.raises(Refused, match="invalid_learning_objective"):
        j.start({"node_id": TOPIC, "kc_id": "kc.mth.o.imaginary"})
    # Mapping logic can be exercised with a frozen selected-source reader; actual FK rows remain real.
    conn = d.learner.conn
    sid = "src_" + "1" * 26
    source = {"source_id": sid, "revision": 1}
    conn.execute("INSERT INTO study_sources VALUES (?,1,0,'{}',0,0)", (sid,))
    conn.execute("INSERT INTO study_revisions VALUES (?,1,?,NULL,1,0)", (sid, "0" * 64))

    class Source:
        text = "Unmapped machine learning material."

        def curriculum_text(self, selection):
            assert selection == source
            return self.text

    material = Source()
    with pytest.raises(Refused, match="unmapped_source"):
        j.start({"node_id": TOPIC, "kc_id": KC, "source": source}, material)
    assert j.reply() == {"journey": None}
    material.text = "Number is the installed topic for these notes."
    j.start({"node_id": TOPIC, "kc_id": KC, "source": source}, material)
    started = j.step("practice")["journey"]
    # The daily plan and lesson browser enter without a source; that must preserve the
    # original material and the unanswered question rather than silently replace them.
    assert j.start({"node_id": TOPIC, "kc_id": KC})["journey"] == started
    conn.execute("UPDATE study_sources SET current_revision=2 WHERE source_id=?", (sid,))
    assert j.reply()["journey"]["source_changed"]
    assert j.reply()["journey"]["source"] == source
    # Deleting a source clears only its journey link through existing source deletion behavior.
    conn.execute("DELETE FROM study_sources WHERE source_id=?", (sid,))
    assert j.reply() == {"journey": None}


def test_chosen_lesson_is_pinned_without_resetting_the_goal_and_must_teach_it(desk):
    d, _ = desk
    j = journey(d)
    chosen = "les.mth.o.number.z_chosen"
    d.content.records["lessons"][chosen] = {"id": chosen, "kc_ids": [KC], "node_id": TOPIC}
    first = j.step("practice")["journey"]
    updated = j.start({"node_id": TOPIC, "kc_id": KC, "lesson_id": chosen})["journey"]
    assert updated["lesson_id"] == chosen
    assert updated["practice_set_id"] == first["practice_set_id"]
    assert LearningJourney(d).reply()["journey"] == updated
    j.step("review")
    assert j.reply()["journey"]["lesson_opened"]
    before = j.saved()
    for lesson in ("les.mth.o.number.missing", "les.mth.o.number.unrelated"):
        d.content.records["lessons"]["les.mth.o.number.unrelated"] = {"id": lesson, "kc_ids": []}
        with pytest.raises(Refused, match="invalid_learning_lesson"):
            j.start({"node_id": TOPIC, "kc_id": KC, "lesson_id": lesson})
        assert j.saved() == before


def test_existing_goal_is_not_reset_and_no_items_is_honest_and_recoverable(desk):
    d, _ = desk
    j = journey(d)
    first = j.step("practice")
    assert j.start({"node_id": TOPIC, "kc_id": KC}) == first
    respond(d, first["journey"])
    d.content.records["items"] = {}
    blocked = j.step("check")["journey"]
    assert blocked["phase"] == "unavailable"
    assert blocked["practice_set_id"] == first["journey"]["practice_set_id"]


def test_check_excludes_intervention_questions_and_same_worded_duplicates_even_after_spacing(desk):
    d, clock = desk
    j = journey(d)
    first = j.step("practice")["journey"]
    respond(d, first, "b")
    initial = d._get(first["practice_set_id"], "practice")["items"][0]["id"]
    lesson_items = [i["id"] for i in d.content.table("items") if i["id"] != initial][:3]
    d.content.records["lessons"]["les.mth.o.number.first"]["blocks"] = [{"item_ids": lesson_items}]
    j.step("review")
    # A duplicate record of an exposed problem is not evidence of transfer either.
    import copy

    duplicate = copy.deepcopy(d.content.record("items", initial))
    duplicate["id"] = "itm.mth.o.number.9999"
    d.content.records["items"][duplicate["id"]] = duplicate
    clock.advance(40 * 86_400_000)
    check = j.step("check")["journey"]
    selected = d._get(check["practice_set_id"], "practice")["items"][0]["id"]
    assert selected not in [initial, duplicate["id"], *lesson_items]


def test_teaching_example_is_excluded_from_later_independent_questions(desk):
    d, _ = desk
    j = journey(d)
    exposed = d.content.table("items")[0]
    d.content.records.setdefault("worked_examples", {})["wex.mth.o.number.9999"] = {
        "id": "wex.mth.o.number.9999",
        "kc_ids": [KC],
        "problem": exposed["stem"],
    }
    before = list(d.learner.conn.execute("SELECT * FROM attempts"))
    j.step("review")
    first = j.step("practice")["journey"]
    selected = d._get(first["practice_set_id"], "practice")["items"][0]["id"]
    assert selected != exposed["id"]
    assert list(d.learner.conn.execute("SELECT * FROM attempts")) == before


def test_corrected_evidence_replaces_a_cached_success_without_an_extra_attempt(desk):
    from agent_core.store.ids import new_ulid

    d, _ = desk
    j = journey(d)
    first = j.step("practice")["journey"]
    respond(d, first)
    assert j.reply()["journey"]["evidence"] == "independent_correct"
    state = d._get(first["practice_set_id"], "practice")
    original = next(e for e in d.learner.log.merged() if e.session_id == state["id"] and e.type == "verdict")
    d.learner.record(
        "verdict",
        {
            **original.payload,
            "verdict_id": new_ulid(),
            "supersedes": original.payload["verdict_id"],
            "outcome": "incorrect",
        },
        source="checker",
        session_id=state["id"],
    )
    current = j.reply()["journey"]
    assert current["evidence"] == "incorrect" and current["phase"] == "repair"
    assert current["prior_attempts"] == 1


def test_missing_or_erased_evidence_does_not_restore_cached_success(desk, monkeypatch):
    d, _ = desk
    j = journey(d)
    first = j.step("practice")["journey"]
    respond(d, first)
    monkeypatch.setattr(d, "item_verdicts", lambda *_: ({}, [], None))
    restored = j.reply()["journey"]
    assert restored["phase"] == "repair" and restored["evidence"] == "not_checked"


def test_readable_pdf_awaiting_review_can_suggest_topics_without_enabling_generation(tmp_path):
    from agent_core.engine.study import StudyError, digest
    from test_study_workspace import seeded

    study, _ = seeded(tmp_path)
    source = study.create(
        {
            "kind": "pdf",
            "file_name": "notes.pdf",
            "mime_type": "application/pdf",
            "byte_length": 3,
            "sha256": digest(b"pdf"),
        }
    )
    study.commit_units(
        source, [{"locator": {"kind": "page", "page": 1}, "text": "Machine learning notes.", "ocr": True}]
    )
    source = study.source(source["source_id"])
    selection = {"source_id": source["source_id"], "revision": 1}
    assert source["state"] == "partial"
    assert study.curriculum_text(selection) == "Machine learning notes."
    assert study.source(source["source_id"]) == source
    with pytest.raises(StudyError, match="confirm_needed"):
        study.selected([selection])
    with pytest.raises(StudyError, match="source_stale"):
        study.curriculum_text({**selection, "revision": 2})


def test_api_profile_isolation_private_source_authorisation_and_persistence(tmp_path, desk):
    import asyncio

    from agent_core.config import Settings
    from api_harness import start_core, stop_core
    from test_m10a_profiles import Api, student

    async def exercise():
        runtime = await start_core(tmp_path / "api", settings=Settings(study_workspace_enabled=True))
        api = Api(runtime)
        try:
            first = await api.add(student("Journey first"))
            token = (await api.unlock(first)).json()["profile_token"]
            original = runtime.runtime.assessments

            def assessments():
                current = original()
                if current:
                    current.content = desk[0].content
                return current

            runtime.core.assessments = assessments
            asked = {"node_id": TOPIC, "kc_id": KC}
            assert (await api.call("GET", "/v1/learning-journey")).status_code == 401
            assert (await api.call("POST", "/v1/learning-journey", asked, profile=token)).status_code == 200
            second = await api.add(student("Journey second"))
            other = (await api.unlock(second)).json()["profile_token"]
            assert (await api.call("GET", "/v1/learning-journey", profile=other)).json() == {"journey": None}
            token = (await api.unlock(first)).json()["profile_token"]
            assert (await api.call("GET", "/v1/learning-journey", profile=token)).json()["journey"]["goal"][
                "kc_id"
            ] == KC
            source = (
                await api.call(
                    "POST",
                    "/v1/study/sources",
                    {
                        "kind": "text",
                        "title": "Number",
                        "text": "Number is the topic of these source notes.",
                    },
                    profile=token,
                )
            ).json()
            sid = source["source_id"]
            await api.call("PATCH", f"/v1/study/sources/{sid}", {"private": True}, profile=token)
            linked = {**asked, "source": {"source_id": sid, "revision": 1}}
            assert (await api.call("POST", "/v1/learning-journey", linked, profile=token)).status_code == 422
            opened = (await api.call("POST", f"/v1/study/sources/{sid}/open", {"confirm": True}, profile=token)).json()
            result = await api.call(
                "POST", "/v1/learning-journey", linked, profile=token, headers={"x-study-open": opened["open_token"]}
            )
            assert result.status_code == 200, result.text
            assert result.json()["journey"]["source"] == linked["source"]
        finally:
            await stop_core(runtime)

    asyncio.run(exercise())
