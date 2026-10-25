"""Real saved source journeys: resumable learning work, not a second mastery model."""

import asyncio
import json

import pytest
from agent_core.engine.study import StudyError
from agent_core.engine.study_journey import StudyJourney
from agent_core.store.sqlite import open_database
from test_study_workspace import queue_for, seeded


def make(d, source, kind, parent=None):
    request = {
        "kind": kind,
        "execution": "local",
        "sources": [{"source_id": source["source_id"], "revision": source["revision"]}],
    }
    if kind == "chat":
        request.update(prompt="Teach me from the beginning", learning_intent="lesson")
    if parent:
        request["context_aid_id"] = parent["aid_id"]
    job = d.create_job(request)
    asyncio.run(queue_for(d).run(d, job["job_id"]))
    result = d.job(job["job_id"])
    assert result["state"] == "completed", result
    return d.aid(result["result_ids"][0])


def current(d):
    return StudyJourney(d).current(lambda _: None)


def rate(d, aid):
    card = d.deck(aid["deck_id"])["cards"][0]
    d.review(
        aid["deck_id"],
        {
            "client_review_id": "srv_" + "1" * 26,
            "card_id": card["card_id"],
            "card_revision": card["revision"],
            "rating": "good",
            "revealed": True,
        },
    )


def submit(d, quiz, option="a", n="1", kind="submit"):
    return d.submit(
        quiz["quiz_id"],
        {
            "attempt_id": "sqa_" + n * 26,
            "quiz_revision": 1,
            "submission_kind": kind,
            "answers": [{"item_id": "q1", "answer": option}],
        },
    )


def test_resume_lesson_cards_quiz_result_and_due_review_without_changing_mastery(tmp_path):
    d, s = seeded(tmp_path)
    now = [d.clock()]
    d.clock = lambda: now[0]
    lesson = make(d, s, "chat")
    assert current(d)["phase"] == "lesson"
    cards = make(d, s, "flashcards", lesson)
    assert current(d)["phase"] == "flashcards"
    assert current(d)["cards_reviewed"] == 0  # Opening/revealing cannot advance a review.
    quiz = make(d, s, "quiz", cards)
    assert current(d)["phase"] == "flashcards"
    rate(d, cards)
    assert current(d)["cards_reviewed"] == 1
    assert current(d)["phase"] == "quiz"
    draft = {"quiz_revision": 1, "position": 0, "answers": [{"item_id": "q1", "answer": "a"}]}
    d.save_draft(quiz["quiz_id"], draft)
    assert current(d)["questions_answered"] == 1
    reopened, _ = open_database(tmp_path / "learner.db", "learner")
    assert current(type(d)(reopened, d.clock, d.settings)) == current(d)
    answer = submit(d, quiz)
    assert StudyJourney(d).saved_result(quiz["quiz_id"])[0] == answer
    assert d.quiz(quiz["quiz_id"])["submission"] == {
        "attempt_id": answer["attempt_id"],
        "answers": [{"item_id": "q1", "answer": "a"}],
    }
    assert current(d)["phase"] == "complete"
    now[0] = current(d)["next_review_at"] + 1
    assert current(d)["phase"] == "flashcards"
    # Job retention cannot erase lineage, saved quiz results, or reset a journey.
    d.conn.execute("DELETE FROM study_jobs")
    assert current(d)["quiz_aid_id"] == quiz["aid_id"]
    assert current(d)["questions_correct"] == 1
    assert d.conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
    assert d.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_wrong_or_unverifiable_quiz_requires_review_and_partial_checks_are_not_completion(tmp_path):
    d, s = seeded(tmp_path)
    now = [d.clock()]
    d.clock = lambda: now[0]
    lesson = make(d, s, "chat")
    cards = make(d, s, "flashcards", lesson)
    rate(d, cards)
    quiz = make(d, s, "quiz", cards)
    submit(d, quiz, kind="check")
    assert StudyJourney(d).saved_result(quiz["quiz_id"]) is None
    assert current(d)["questions_answered"] == 0
    submit(d, quiz, option="b", n="2")
    assert current(d)["phase"] == "review"
    assert current(d)["questions_to_review"] == 1
    assert not current(d)["retry_quiz"]
    StudyJourney(d).resume(lesson["aid_id"])
    assert current(d)["phase"] == "review"  # A page view is not an acknowledgement.
    now[0] += 1000
    StudyJourney(d).resume(lesson["aid_id"], reviewed=True)
    assert current(d)["phase"] == "quiz" and current(d)["retry_quiz"]
    d.save_draft(quiz["quiz_id"], {"quiz_revision": 1, "position": 0, "answers": []})
    assert StudyJourney(d).saved_result(quiz["quiz_id"]) is None
    assert current(d)["phase"] == "quiz"


def test_private_archived_deleted_and_stale_material_do_not_reappear_or_leak(tmp_path):
    d, s = seeded(tmp_path)
    make(d, s, "chat")
    before = current(d)

    def deny(_):
        raise StudyError("grant_expired")

    assert StudyJourney(d).current(deny) is None
    assert current(d) == before
    d.archive_source(s["source_id"], True)
    assert current(d) is None
    d.archive_source(s["source_id"], False)
    assert current(d)["root_aid_id"] == before["root_aid_id"]
    d.conn.execute("UPDATE study_aids SET body=json_set(body,'$.status','stale')")
    assert current(d)["phase"] == "unavailable"
    d.delete(s["source_id"])
    assert current(d) is None
    assert d.conn.execute("SELECT count(*) FROM study_journeys").fetchone()[0] == 0


def test_unrelated_sets_and_regenerated_branches_do_not_replace_saved_work(tmp_path):
    d, s = seeded(tmp_path)
    lesson = make(d, s, "chat")
    first = make(d, s, "flashcards", lesson)
    quiz = make(d, s, "quiz", first)
    make(d, s, "quiz")  # Same material is not sufficient to infer a learning link.
    assert current(d)["quiz_aid_id"] == quiz["aid_id"]
    second = make(d, s, "flashcards", lesson)
    assert current(d)["cards_aid_id"] == second["aid_id"]
    assert current(d)["quiz_aid_id"] is None
    StudyJourney(d).resume(quiz["aid_id"])
    assert current(d)["cards_aid_id"] == first["aid_id"]
    assert current(d)["quiz_aid_id"] == quiz["aid_id"]
    StudyJourney(d).resume(lesson["aid_id"])
    assert current(d)["cards_aid_id"] == first["aid_id"]
    explanation = make(d, s, "chat", lesson)
    StudyJourney(d).resume(explanation["aid_id"])
    assert current(d)["quiz_aid_id"] == quiz["aid_id"]


def test_migration_backfills_explicit_links_without_rewriting_existing_rows(tmp_path):
    from agent_core.store.migration_v16 import LEARNER
    from agent_core.store.sqlite import statements

    d, s = seeded(tmp_path)
    lesson = make(d, s, "chat")
    cards = make(d, s, "flashcards", lesson)
    make(d, s, "quiz", cards)
    queries = (
        "SELECT * FROM study_aids",
        "SELECT * FROM study_flashcards",
        "SELECT * FROM study_quizzes",
        "SELECT * FROM study_jobs",
    )
    snapshots = {sql: list(d.conn.execute(sql)) for sql in queries}
    for table in ("study_journeys", "study_aid_parents", "study_quiz_submissions"):
        d.conn.execute(f"DROP TABLE {table}")
    for sql in statements(LEARNER):
        d.conn.execute(sql)
    for sql, rows in snapshots.items():
        assert list(d.conn.execute(sql)) == rows
    assert current(d)["root_aid_id"] == lesson["aid_id"]
    assert current(d)["cards_aid_id"] == cards["aid_id"]


def test_invalid_intent_and_cross_source_parent_cannot_create_a_journey(tmp_path):
    d, s = seeded(tmp_path)
    with pytest.raises(StudyError):
        d.create_job(
            {
                "kind": "summary",
                "execution": "local",
                "sources": [{"source_id": s["source_id"], "revision": 1}],
                "learning_intent": "lesson",
            }
        )
    lesson = make(d, s, "chat")
    other = d.create({"kind": "text", "title": "Other", "text": "Other material."})
    with pytest.raises(StudyError):
        make(d, other, "flashcards", lesson)
    assert current(d)["cards_aid_id"] is None
    assert "learning_intent" not in json.dumps(
        d.brief({"kind": "chat", "sources": lesson["sources"], "learning_intent": "lesson"})
    )


def test_api_keeps_private_journeys_results_and_replayed_commands_profile_bound(tmp_path):
    from agent_core.config import Settings
    from api_harness import start_core, stop_core
    from test_m10a_profiles import Api, student

    async def exercise():
        runtime = await start_core(
            tmp_path / "api", settings=Settings(study_workspace_enabled=True, study_offline_enabled=True)
        )
        api = Api(runtime)
        try:
            first = await api.add(student("First learner"))
            token = (await api.unlock(first)).json()["profile_token"]
            d = runtime.core.study.desk()
            source = d.create({"kind": "text", "title": "Biology", "text": "DNA stores genetic information."})

            async def build(kind, parent=None):
                body = {
                    "kind": kind,
                    "execution": "local",
                    "sources": [{"source_id": source["source_id"], "revision": 1}],
                }
                if kind == "chat":
                    body.update(prompt="Teach me from the beginning", learning_intent="lesson")
                if parent:
                    body["context_aid_id"] = parent["aid_id"]
                job = d.create_job(body)
                await queue_for(d).run(d, job["job_id"])
                return d.aid(d.job(job["job_id"])["result_ids"][0])

            lesson = await build("chat")
            cards = await build("flashcards", lesson)
            quiz = await build("quiz", cards)
            result = submit(d, quiz)
            path = f"/v1/study/quizzes/{quiz['quiz_id']}/saved-result"
            assert (await api.call("GET", path)).status_code == 401
            assert (await api.call("GET", path, profile=token)).json() == {
                "result": result,
                "answers": [{"item_id": "q1", "answer": "a"}],
            }
            aid_path = f"/v1/study/aids/{lesson['aid_id']}/journey"
            key = {"idempotency-key": "cli_" + "9" * 26}
            command = await api.call("POST", aid_path, {"action": "resume"}, profile=token, headers=key)
            assert command.status_code == 200, command.text
            d.patch(source["source_id"], {"private": True})
            assert (await api.call("GET", "/v1/study/workspace", profile=token)).json()["journey"] is None
            assert (await api.call("GET", path, profile=token)).status_code == 422
            assert (
                await api.call("POST", aid_path, {"action": "resume"}, profile=token, headers=key)
            ).status_code == 422
            opened = (
                await api.call(
                    "POST", f"/v1/study/sources/{source['source_id']}/open", {"confirm": True}, profile=token
                )
            ).json()
            headers = {"x-study-open": opened["open_token"]}
            assert (await api.call("GET", path, profile=token, headers=headers)).json() == {
                "result": result,
                "answers": [{"item_id": "q1", "answer": "a"}],
            }
            assert (await api.call("GET", "/v1/study/workspace", profile=token, headers=headers)).json()["journey"][
                "root_aid_id"
            ] == lesson["aid_id"]
            second = await api.add(student("Second learner"))
            other = (await api.unlock(second)).json()["profile_token"]
            assert (await api.call("GET", "/v1/study/workspace", profile=other)).json()["journey"] is None
            assert (await api.call("GET", path, profile=other)).status_code == 404
        finally:
            await stop_core(runtime)

    asyncio.run(exercise())


@pytest.mark.parametrize("previously_reviewed", [False, True])
def test_again_returns_in_two_minutes_and_survives_reopen_without_resetting_evidence(tmp_path, previously_reviewed):
    d, s = seeded(tmp_path)
    now = [d.clock()]
    d.clock = lambda: now[0]
    lesson = make(d, s, "chat")
    cards = make(d, s, "flashcards", lesson)
    if previously_reviewed:
        rate(d, cards)
    quiz = make(d, s, "quiz", cards)
    saved = submit(d, quiz)
    card = d.deck(cards["deck_id"])["cards"][0]
    original = d.conn.execute("SELECT body FROM study_flashcards").fetchone()[0]
    request = {
        "client_review_id": "srv_" + "2" * 26,
        "card_id": card["card_id"],
        "card_revision": card["revision"],
        "rating": "again",
        "revealed": True,
    }
    reviewed_at = now[0]
    again = d.review(cards["deck_id"], request)
    assert again["reps"] == (2 if previously_reviewed else 1)
    assert again["lapses"] == int(previously_reviewed)
    assert current(d)["phase"] == "complete"
    assert current(d)["next_review_at"] == reviewed_at + 120_000
    now[0] += 119_999
    assert current(d)["review_card_ids"] == []
    reopened, _ = open_database(tmp_path / "learner.db", "learner")
    restored = type(d)(reopened, d.clock, d.settings)
    assert current(restored) == current(d)
    now[0] += 1
    assert current(restored)["phase"] == "flashcards"
    assert current(restored)["review_card_ids"] == [card["card_id"]]
    assert d.review(cards["deck_id"], request) == again  # Network retry cannot move the due time.
    hard = restored.review(cards["deck_id"], {**request, "client_review_id": "srv_" + "3" * 26, "rating": "hard"})
    assert hard["reps"] == again["reps"] + 1
    assert current(restored)["next_review_at"] >= now[0] + 86_400_000
    assert current(restored)["phase"] == "complete"
    assert StudyJourney(restored).saved_result(quiz["quiz_id"])[0] == saved
    assert restored.conn.execute("SELECT body FROM study_flashcards").fetchone()[0] == original
    assert restored.conn.execute("SELECT count(*) FROM study_reviews").fetchone()[0] == (
        3 if previously_reviewed else 2
    )
    assert restored.conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
    assert restored.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_relearning_card_returns_before_creating_a_first_quiz(tmp_path):
    d, s = seeded(tmp_path)
    now = [d.clock()]
    d.clock = lambda: now[0]
    lesson = make(d, s, "chat")
    cards = make(d, s, "flashcards", lesson)
    card = d.deck(cards["deck_id"])["cards"][0]
    d.review(
        cards["deck_id"],
        {
            "client_review_id": "srv_" + "2" * 26,
            "card_id": card["card_id"],
            "card_revision": 1,
            "rating": "again",
            "revealed": True,
        },
    )
    assert current(d)["phase"] == "make_quiz"
    now[0] += 120_000
    assert current(d)["phase"] == "flashcards"
    assert current(d)["review_card_ids"] == [card["card_id"]]


def test_repeated_again_then_hard_keeps_history_and_restarts_each_two_minute_step(tmp_path):
    d, s = seeded(tmp_path)
    now = [d.clock()]
    d.clock = lambda: now[0]
    lesson = make(d, s, "chat")
    cards = make(d, s, "flashcards", lesson)
    rate(d, cards)
    quiz = make(d, s, "quiz", cards)
    result = submit(d, quiz)
    card = d.deck(cards["deck_id"])["cards"][0]
    original = d.conn.execute("SELECT body FROM study_flashcards").fetchone()[0]
    for index in (2, 3):
        request = {
            "client_review_id": "srv_" + str(index) * 26,
            "card_id": card["card_id"],
            "card_revision": 1,
            "rating": "again",
            "revealed": True,
        }
        response = d.review(cards["deck_id"], request)
        assert response["reps"] == index
        assert response["lapses"] == 1  # Repeated relearning failures are the same lapse.
        assert current(d)["next_review_at"] == now[0] + 120_000
        assert current(d)["phase"] == "complete"
        now[0] += 119_999
        assert current(d)["cards_due"] == 0
        now[0] += 1
        assert current(d)["review_card_ids"] == [card["card_id"]]
        assert current(d)["phase"] == "flashcards"
        assert d.review(cards["deck_id"], request) == response
    reopened, _ = open_database(tmp_path / "learner.db", "learner")
    restored = type(d)(reopened, d.clock, d.settings)
    assert current(restored) == current(d)
    hard = restored.review(cards["deck_id"], {**request, "client_review_id": "srv_" + "4" * 26, "rating": "hard"})
    assert hard["reps"] == 4 and hard["lapses"] == 1
    assert current(restored)["phase"] == "complete"
    assert current(restored)["next_review_at"] >= now[0] + 86_400_000
    assert StudyJourney(restored).saved_result(quiz["quiz_id"])[0] == result
    assert restored.conn.execute("SELECT body FROM study_flashcards").fetchone()[0] == original
    assert restored.conn.execute("SELECT count(*) FROM study_reviews").fetchone()[0] == 4
    assert restored.conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0] == 0
