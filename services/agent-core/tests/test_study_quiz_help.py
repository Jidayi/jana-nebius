"""Quiz coaching uses trusted evidence near the question, while whole-document tools keep full scope."""

import asyncio

import pytest
from agent_core.config import Settings
from agent_core.engine.study import StudyError, digest
from test_study_workspace import TEXT, LocalStudy, claim, queue_for, seeded


def test_question_help_is_scoped_without_changing_the_quiz_or_whole_document_scope(tmp_path):
    desk, _ = seeded(tmp_path)
    desk.settings = Settings(study_offline_enabled=True, study_batch_char_limit=16000)
    source = desk.create(
        {
            "kind": "pdf",
            "file_name": "notes.pdf",
            "mime_type": "application/pdf",
            "byte_length": 3,
            "sha256": digest(b"pdf"),
        }
    )
    desk.commit_units(
        source,
        [{"locator": {"kind": "page", "page": page}, "text": f"Page {page}: " + TEXT * 12} for page in range(1, 70)],
    )
    refs = [{"source_id": source["source_id"], "revision": 1}]
    chunks = desk.selected(refs)
    evidence = claim(chunks[-2])
    quiz_job = desk.create_job({"kind": "quiz", "execution": "local", "sources": refs})
    quiz_job["state"] = "running"
    desk.save_job(quiz_job)
    aid = desk.commit_aid(
        quiz_job,
        {
            "request_id": quiz_job["job_id"],
            "kind": "quiz",
            "claims": [evidence],
            "quiz": {
                "items": [
                    {
                        "item_id": "q1",
                        "type": "choice",
                        "stem": evidence,
                        "options": [{"option_id": "a", "text": "DNA"}, {"option_id": "b", "text": "Water"}],
                    }
                ],
                "keys": [{"item_id": "q1", "answer": "a", "explanation": evidence, "marking": "judged"}],
            },
        },
        [True, True],
    )
    qid = aid["quiz_id"]
    quiz_before = desk.quiz(qid)
    job_body = {
        "kind": "chat",
        "execution": "prefer_cloud",
        "sources": refs,
        "prompt": "Give me a hint for the practice question.",
    }
    job = desk.create_quiz_help_job(qid, "q1", job_body)
    selected = desk.quiz_help_scope(job["job_id"], chunks)
    assert {c["locator"]["page"] for c in selected} == {67, 68, 69}
    assert desk.scoped({"kind": "summary", "sources": refs}, chunks) == chunks
    assert desk.quiz_help_scope(quiz_job["job_id"], chunks) == chunks
    seen = []

    class Coaching:
        async def process(self, _conn, identity, request, material, _attempt, **_kwargs):
            seen.append((request, material))
            return {"request_id": identity, "kind": "chat", "claims": [claim(material[1])]}

    queue = queue_for(desk)
    queue.cloud = Coaching()
    asyncio.run(queue.run(desk, job["job_id"]))
    assert desk.job(job["job_id"])["state"] == "completed"
    assert desk.job(job["job_id"])["total_units"] == 5
    assert len(seen) == 1 and seen[0][1] == selected
    assert "keys" not in seen[0][0] and "answer" not in seen[0][0]
    import json

    withheld = json.loads(seen[0][0]["settings"]["focus"].removeprefix("Coaching withheld wording: "))
    assert "DNA" in withheld and "option 1" in withheld
    stored = desk.one("SELECT checkpoint FROM study_jobs WHERE job_id=?", (job["job_id"],))["request"]
    assert stored == job_body and "settings" not in stored
    assert desk.quiz(qid) == quiz_before
    with pytest.raises(StudyError, match="not_found"):
        desk.create_quiz_help_job(qid, "missing", job_body)
    with pytest.raises(StudyError, match="invalid_study_request"):
        desk.create_quiz_help_job(qid, "q1", {**job_body, "sources": []})


def test_quiz_help_api_replay_and_private_source_grants(tmp_path):
    from api_harness import cli, start_core, stop_core
    from test_m10a_profiles import Api, student

    async def run():
        runtime = await start_core(
            tmp_path, settings=Settings(study_workspace_enabled=True, study_offline_enabled=True)
        )
        api = Api(runtime)
        try:
            pid = await api.add(student("Coaching learner"))
            token = (await api.unlock(pid)).json()["profile_token"]
            runtime.core.study.model = lambda: LocalStudy()
            source = (
                await api.call(
                    "POST", "/v1/study/sources", {"kind": "text", "title": "Biology", "text": TEXT}, profile=token
                )
            ).json()
            sid = source["source_id"]
            refs = [{"source_id": sid, "revision": 1}]
            started = (
                await api.call(
                    "POST", "/v1/study/jobs", {"kind": "quiz", "execution": "local", "sources": refs}, profile=token
                )
            ).json()
            await runtime.core.study.task
            aid_id = runtime.core.study.desk().job(started["job_id"])["result_ids"][0]
            qid = runtime.core.study.desk().aid(aid_id)["quiz_id"]
            path = f"/v1/study/quizzes/{qid}/items/q1/help"
            body = {
                "kind": "chat",
                "execution": "local",
                "sources": refs,
                "prompt": "Give me a hint for this practice question.",
            }
            key = {"idempotency-key": cli()}
            result = await api.call("POST", path, body, profile=token, headers=key)
            assert result.status_code == 202, result.text
            repeat = await api.call("POST", path, body, profile=token, headers=key)
            assert repeat.json() == result.json()
            await runtime.core.study.task
            assert runtime.core.study.desk().job(result.json()["job_id"])["state"] == "completed"
            await api.call("PATCH", f"/v1/study/sources/{sid}", {"private": True}, profile=token)
            assert (await api.call("POST", path, body, profile=token)).status_code == 422
            opened = (await api.call("POST", f"/v1/study/sources/{sid}/open", {"confirm": True}, profile=token)).json()
            allowed = await api.call("POST", path, body, profile=token, headers={"x-study-open": opened["open_token"]})
            assert allowed.status_code == 202, allowed.text
            assert (await api.call("POST", path, body)).status_code == 401
        finally:
            await stop_core(runtime)

    asyncio.run(run())


def test_quiz_help_includes_prerequisite_definitions_at_start_of_previous_pdf_page(tmp_path):
    from test_study_workspace import generate

    desk, source = seeded(tmp_path)
    aid = generate(desk, source, "quiz")
    refs = aid["sources"]
    cited = desk.selected(refs)[0]
    body = {"kind": "chat", "execution": "local", "sources": refs, "prompt": "Give me a hint."}
    job = desk.create_quiz_help_job(aid["quiz_id"], "q1", body)
    chunks = [
        {**cited, "chunk_id": f"sck_{str(i) * 26}", "ordinal": i, "locator": {"kind": "page", "page": page}}
        for i, page in enumerate((4, 5, 5, 5, 6, 6, 6, 7), 1)
    ]
    chunks[5] = {**cited, "ordinal": 6, "locator": {"kind": "page", "page": 6}}
    kept = desk.quiz_help_scope(job["job_id"], chunks)
    assert chunks[1] in kept  # Definition at the top of page 5, beyond immediate chunk neighbours.
    assert chunks[0] not in kept
    assert {c["locator"]["page"] for c in kept} == {5, 6, 7}
    assert sum(len(c["text"]) for c in kept) <= desk.settings.study_batch_char_limit


def test_withheld_blank_wording_is_inference_only_and_never_saved_in_the_quiz_view(tmp_path):
    from test_study_workspace import generate

    desk, source = seeded(tmp_path)
    aid = generate(desk, source, "quiz")
    quiz = desk.quiz(aid["quiz_id"])
    item = quiz["view"]["items"][0]
    item.update(type="fill_blank", stem={**item["stem"], "text": "Prior influence will ____."})
    item.pop("options")
    quiz["keys"][0]["answer"] = "diminish"
    import json

    desk.conn.execute("UPDATE study_quizzes SET body=? WHERE quiz_id=?", (json.dumps(quiz), aid["quiz_id"]))
    body = {
        "kind": "chat",
        "execution": "local",
        "sources": aid["sources"],
        "prompt": "Give me a hint without the answer.",
    }
    job = desk.create_quiz_help_job(aid["quiz_id"], "q1", body)
    brief = desk.quiz_help_brief(job["job_id"], desk.brief(body))
    assert "diminish" in brief["settings"]["focus"] and "decrease" in brief["settings"]["focus"]
    assert len(brief["settings"]["focus"]) <= 500
    stored_request = desk.one("SELECT checkpoint FROM study_jobs WHERE job_id=?", (job["job_id"],))["request"]
    assert stored_request == body and "settings" not in stored_request
    assert "keys" not in quiz["view"]


def test_choice_help_protects_distinguishing_terms_and_directional_paraphrases(tmp_path):
    import json

    from test_study_workspace import generate

    desk, source = seeded(tmp_path)
    aid = generate(desk, source, "quiz")
    quiz = desk.quiz(aid["quiz_id"])
    item = quiz["view"]["items"][0]
    item["options"] = [
        {"option_id": "a", "text": "It reduces noise and lowers variance."},
        {"option_id": "b", "text": "It increases variance and reduces bias."},
    ]
    quiz["keys"][0]["answer"] = "a"
    desk.conn.execute("UPDATE study_quizzes SET body=? WHERE quiz_id=?", (json.dumps(quiz), aid["quiz_id"]))
    body = {"kind": "chat", "execution": "local", "sources": aid["sources"], "prompt": "Walk me through it."}
    job = desk.create_quiz_help_job(aid["quiz_id"], "q1", body)
    focus = desk.quiz_help_brief(job["job_id"], desk.brief(body))["settings"]["focus"]
    words = json.loads(focus.removeprefix("Coaching withheld wording: "))
    assert {"noise", "lowers", "reduce", "reduces", "decrease", "smaller", "option 1"} <= set(words)
    assert "variance" not in words and "bias" not in words
    assert len(focus) <= 500
    assert desk.one("SELECT checkpoint FROM study_jobs WHERE job_id=?", (job["job_id"],))["request"] == body
    item["options"][0]["text"] = "The posterior probability of the parameters given the dataset"
    quiz["keys"][0]["explanation"]["text"] = "MAP maximizes P(θ|dataset)."
    desk.conn.execute("UPDATE study_quizzes SET body=? WHERE quiz_id=?", (json.dumps(quiz), aid["quiz_id"]))
    focus = desk.quiz_help_brief(job["job_id"], desk.brief(body))["settings"]["focus"]
    words = json.loads(focus.removeprefix("Coaching withheld wording: "))
    assert "P(θ|dataset)" in words
    assert "of the parameters given the dataset" in words
    assert len(focus) <= 500
