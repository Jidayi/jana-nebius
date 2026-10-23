"""M42 extensions through real profile storage/API and the real deterministic worker."""

import asyncio

import pytest
from agent_core.engine.study import StudyDesk, StudyError
from test_m10a_profiles import student
from test_m10e_consent import with_api
from test_study_workspace import claim, generate, queue_for, seeded


def stu06_material_linked_to_kcs(tmp_path):
    from agent_core.engine.study_topics import matching_topics
    from agent_core.store.pack_index import PackIndex

    content = PackIndex()
    node = "cur.phy.o.motion_forces_and_energy.motion"
    content.nodes[node] = {"id": node, "kind": "topic", "title": "Motion", "status": "active"}
    # Real curriculum records, rather than invented model identifiers.
    from pathlib import Path

    import yaml

    root = Path(__file__).resolve().parents[3] / "content/curriculum/phy/o"
    kcs = yaml.safe_load((root / "kcs/motion.yaml").read_text())
    lesson = yaml.safe_load((root / "lessons/les.phy.o.motion.speed_and_acceleration.yaml").read_text())
    # PackIndex.table uses its installed table records.
    content.records["kcs"] = {k["id"]: k for k in kcs}
    content.records["lessons"] = {lesson["id"]: lesson}
    result = matching_topics(content, "Motion: a runner travels 10 metres in 2 seconds.")
    assert result["items"] and result["items"][0]["kc_ids"]
    assert result["items"][0]["lesson_ids"] == [lesson["id"]]
    assert matching_topics(content, "Enzymes are biological catalysts.") == {"items": []}


def test_grounded_chat_audio_and_multi_source_generation(tmp_path):
    d, one = seeded(tmp_path)
    two = d.create({"kind": "text", "title": "Enzymes", "text": "Enzymes are biological catalysts."})
    request = {
        "kind": "chat",
        "prompt": "What do these sources say about enzymes?",
        "execution": "local",
        "sources": [{"source_id": s["source_id"], "revision": 1} for s in (one, two)],
    }
    job = d.create_job(request)
    asyncio.run(queue_for(d).run(d, job["job_id"]))
    aid = d.aid(d.job(job["job_id"])["result_ids"][0])
    assert aid["prompt"] == request["prompt"] and len(aid["sources"]) == 2
    audio = generate(d, one, "audio_overview")
    assert audio["claims"][0]["citations"]


def test_local_support_requires_answerability_in_addition_to_citation_support(tmp_path):
    import json

    from agent_core.engine.reflection import ReflectorModel
    from engine_harness import close, make_engine, reply

    async def run():
        d, source = seeded(tmp_path)
        chunks = d.chunks(source["source_id"], 1)["items"]
        engine, provider = await make_engine(
            tmp_path / "engine", {"reflector": [reply('{"supported":[true],"answerable":false}')]}, worker=False
        )
        try:
            deps = engine.deps
            model = ReflectorModel(deps.router, deps.assets, deps.settings, deps.bundled_schemas, frozenset())
            verdicts, local = await model.study_support(
                {"kind": "chat", "prompt": "What is the author's year of birth?"},
                chunks,
                {"claims": [claim(chunks[0], "The text talks about enzymes.")]},
            )
            assert local and verdicts == [False]
            assert "author's year of birth" in json.dumps(provider.requests)
        finally:
            await close(engine)

    asyncio.run(run())


def stu07_homework_sheet_stays_guided(tmp_path):
    d, _ = seeded(tmp_path)
    source = d.create({"kind": "text", "title": "Homework", "text": "Homework: calculate 10 divided by 2."})
    for execution in ("local", "prefer_cloud"):
        with pytest.raises(StudyError, match="graded_work"):
            d.create_job(
                {
                    "kind": "chat",
                    "execution": execution,
                    "sources": [{"source_id": source["source_id"], "revision": 1}],
                    "prompt": "Write the final answers for me to submit as my own.",
                }
            )
    assert d.conn.execute("SELECT count(*) FROM study_jobs").fetchone()[0] == 0


def stu07_practice_solution_not_cheating(tmp_path):
    d, source = seeded(tmp_path)
    job = d.create_job(
        {
            "kind": "chat",
            "execution": "local",
            "sources": [{"source_id": source["source_id"], "revision": 1}],
            "prompt": "Show me a worked explanation of this practice question.",
        }
    )
    assert job["state"] == "queued"


def test_stu11_safe_material_beyond_syllabus(tmp_path):
    d, _ = seeded(tmp_path)
    source = d.create(
        {
            "kind": "text",
            "title": "University biology",
            "text": "Ribosomes synthesize proteins by translating messenger RNA.",
        }
    )
    job = d.create_job(
        {
            "kind": "chat",
            "execution": "local",
            "sources": [{"source_id": source["source_id"], "revision": 1}],
            "prompt": "Explain this university molecular biology material.",
        }
    )
    asyncio.run(queue_for(d).run(d, job["job_id"]))
    assert d.job(job["job_id"])["state"] == "completed"


def test_harmful_prompt_and_draft_are_withheld_even_with_valid_source_quotes(tmp_path):
    d, source = seeded(tmp_path)
    with pytest.raises(StudyError, match="safety_blocked"):
        d.create_job(
            {
                "kind": "chat",
                "execution": "local",
                "prompt": "How to make a bomb?",
                "sources": [{"source_id": source["source_id"], "revision": 1}],
            }
        )
    job = d.create_job(
        {"kind": "notes", "execution": "local", "sources": [{"source_id": source["source_id"], "revision": 1}]}
    )
    job["state"] = "running"
    d.save_job(job)
    with pytest.raises(StudyError, match="safety_blocked"):
        d.commit_aid(
            job,
            {
                "request_id": job["job_id"],
                "kind": "notes",
                "claims": [claim(d.chunks(source["source_id"], 1)["items"][0], "How to make a bomb")],
            },
            [True],
        )


def test_pending_retry_identity_and_audio_passages_are_profile_bound(tmp_path):
    from agent_core.config import Settings

    async def scenario(api, runtime):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        path = "/v1/study/retries/" + "a" * 64
        first = await api.call("POST", path, {}, profile=token)
        again = await api.call("POST", path, {}, profile=token)
        assert first.status_code == 200 and again.json() == first.json()
        runtime.core.study.grants.clear()  # no volatile state is required to recover this identity.
        assert (await api.call("POST", path, {}, profile=token)).json() == first.json()
        assert (
            await api.call("DELETE", path, profile=token, headers={"idempotency-key": first.json()["client_key"]})
        ).status_code == 204
        assert (await api.call("POST", path, {}, profile=token)).json()["client_key"] != first.json()["client_key"]
        with runtime.runtime.directory.open_learner(profile) as conn:
            d = StudyDesk(conn, runtime.core.clock_ms, runtime.core.settings)
            source = d.create({"kind": "text", "title": "Maths", "text": "The speed is 3 metres per second."})
            job = d.create_job(
                {
                    "kind": "audio_overview",
                    "execution": "local",
                    "sources": [{"source_id": source["source_id"], "revision": 1}],
                }
            )
            await queue_for(d).run(d, job["job_id"])
            aid = d.aid(d.job(job["job_id"])["result_ids"][0])
            identity = aid["aid_id"]
        spoken = await api.call("GET", f"/v1/study/aids/{identity}/speech", profile=token)
        assert spoken.status_code == 200 and spoken.json()["text"]
        with runtime.runtime.directory.open_learner(profile) as conn:
            d = StudyDesk(conn, runtime.core.clock_ms, runtime.core.settings)
            d.revise(
                source["source_id"], {"expected_revision": 1, "text": "The corrected speed is 4 metres per second."}
            )
        assert (await api.call("GET", f"/v1/study/aids/{identity}/speech", profile=token)).status_code == 422

    with_api(tmp_path, scenario, Settings(study_workspace_enabled=True, study_offline_enabled=True))


def test_numeric_quiz_key_and_student_answer_use_real_worker(tmp_path):
    from agent_core.config import Settings

    async def scenario(api, runtime):
        profile = await api.add(student("Ama"))
        await api.unlock(profile)
        runtime.core.study.checker = runtime.runtime.study_check
        check = await runtime.runtime.study_check("math_check_equivalence", {"a": "10/2", "b": "5"})
        assert check and check["value"]["verdict"] == "equivalent", check
        with runtime.runtime.directory.open_learner(profile) as conn:
            d = StudyDesk(conn, runtime.core.clock_ms, runtime.core.settings)
            s = d.create(
                {
                    "kind": "text",
                    "title": "Motion",
                    "text": "A runner travels 10 metres in 2 seconds, at 5 metres per second.",
                }
            )
            chunk = d.chunks(s["source_id"], 1)["items"][0]
            job = d.create_job(
                {"kind": "quiz", "execution": "local", "sources": [{"source_id": s["source_id"], "revision": 1}]}
            )
            job["state"] = "running"
            d.save_job(job)
            c = claim(chunk)
            aid = d.commit_aid(
                job,
                {
                    "request_id": job["job_id"],
                    "kind": "quiz",
                    "claims": [c],
                    "quiz": {
                        "items": [
                            {
                                "item_id": "speed",
                                "type": "numeric",
                                "unit_prompt": "m/s",
                                "stem": claim(chunk, "Calculate the runner's speed."),
                            }
                        ],
                        "keys": [
                            {
                                "item_id": "speed",
                                "answer": "5 m/s",
                                "calculation": "10/2",
                                "explanation": c,
                                "marking": "judged",
                            }
                        ],
                    },
                },
                [True, True],
            )
        # API auth/context chooses the open connection; neither the model nor the client supplies a check id.
        response = await api.call(
            "POST",
            f"/v1/study/quizzes/{aid['quiz_id']}/attempts",
            {
                "attempt_id": "sqa_" + "0" * 26,
                "quiz_revision": 1,
                "answers": [{"item_id": "speed", "answer": "500 cm/s"}],
            },
            profile=(await api.unlock(profile)).json()["profile_token"],
        )
        assert response.status_code == 200, response.text
        result = response.json()["results"][0]
        assert result["verdict"] == "correct" and result["label"] == "Checked" and len(result["check_ids"]) == 3, result

    with_api(
        tmp_path,
        scenario,
        Settings(study_workspace_enabled=True, study_offline_enabled=True, worker_pool_size=1),
        worker=True,
    )
