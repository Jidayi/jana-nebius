"""Library organisation must never discard sources, evidence, aids or learning progress."""

import asyncio

import pytest
from agent_core.config import Settings
from agent_core.engine.study import StudyDesk, StudyError
from agent_core.store.sqlite import open_database
from test_study_workspace import TEXT, generate, seeded


def test_archive_is_persistent_reversible_and_preserves_learning_records(tmp_path):
    desk, source = seeded(tmp_path)
    sid = source["source_id"]
    deck = desk.deck(generate(desk, source, "flashcards")["deck_id"])
    card = deck["cards"][0]
    desk.review(
        deck["deck_id"],
        {
            "client_review_id": "srv_" + "0" * 26,
            "card_id": card["card_id"],
            "card_revision": 1,
            "rating": "good",
            "revealed": True,
        },
    )
    queries = [
        "SELECT * FROM study_sources",
        "SELECT * FROM study_chunks",
        "SELECT * FROM study_aids",
        "SELECT * FROM study_reviews",
        "SELECT * FROM study_jobs",
    ]
    before = {query: desk.conn.execute(query).fetchall() for query in queries}
    assert desk.library() == {"archived_source_ids": []}
    assert desk.archive_source(sid, True) == {"archived_source_ids": [sid]}
    assert desk.archive_source(sid, True) == {"archived_source_ids": [sid]}
    assert desk.source(sid) == source
    assert {query: desk.conn.execute(query).fetchall() for query in queries} == before
    desk.conn.commit()
    desk.conn.close()
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    reopened = StudyDesk(conn, lambda: 1792281600000, Settings(study_offline_enabled=True))
    assert reopened.library() == {"archived_source_ids": [sid]}
    assert reopened.archive_source(sid, False) == {"archived_source_ids": []}
    assert {query: conn.execute(query).fetchall() for query in queries} == before
    with pytest.raises(StudyError):
        reopened.archive_source("src_" + "Z" * 26, True)
    conn.close()


def test_archive_api_replay_and_profile_isolation(tmp_path):
    from api_harness import cli, start_core, stop_core
    from test_m10a_profiles import Api, student

    async def scenario():
        runtime = await start_core(tmp_path, settings=Settings(study_workspace_enabled=True))
        api = Api(runtime)
        try:
            pid = await api.add(student("Library learner"))
            token = (await api.unlock(pid)).json()["profile_token"]
            response = await api.call(
                "POST", "/v1/study/sources", {"kind": "text", "title": "Biology", "text": TEXT}, profile=token
            )
            assert response.status_code == 201, response.text
            sid = response.json()["source_id"]
            key = {"idempotency-key": cli()}
            response = await api.call("POST", f"/v1/study/sources/{sid}/archive", {}, profile=token, headers=key)
            assert response.status_code == 200, response.text
            assert response.json() == {"archived_source_ids": [sid]}
            repeat = await api.call("POST", f"/v1/study/sources/{sid}/archive", {}, profile=token, headers=key)
            assert repeat.json() == response.json()
            assert (await api.call("GET", "/v1/study/library", profile=token)).json() == response.json()
            assert (await api.call("GET", f"/v1/study/sources/{sid}", profile=token)).status_code == 200
            restored = await api.call("DELETE", f"/v1/study/sources/{sid}/archive", {}, profile=token)
            assert restored.status_code == 200, restored.text
            assert restored.json() == {"archived_source_ids": []}
            other = await api.add(student("Other learner"))
            other_token = (await api.unlock(other)).json()["profile_token"]
            assert (
                await api.call("POST", f"/v1/study/sources/{sid}/archive", {}, profile=other_token)
            ).status_code == 404
            assert (await api.call("GET", "/v1/study/library", profile=other_token)).json() == {
                "archived_source_ids": []
            }
            assert (await api.call("GET", "/v1/study/library")).status_code == 401
        finally:
            await stop_core(runtime)

    asyncio.run(scenario())
