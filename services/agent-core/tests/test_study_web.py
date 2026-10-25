"""Public-page imports use native profile guards, keep provenance and never send local materials to search."""

import asyncio

from agent_core.config import Settings
from agent_core.net.study import StudyCloudError
from test_m10a_profiles import student
from test_m10e_consent import with_api

URL = "https://www.britannica.com/place/Paris"
PAGE = {"url": URL, "title": "Paris", "text": "Paris is the capital of France. It stands on the Seine."}


def test_pending_processing_receipt_does_not_claim_saved_material_was_deleted(tmp_path):
    async def scenario(api, runtime):
        adult = await api.add(student("Synthetic adult", age_band="18_plus"))
        token = (await api.unlock(adult)).json()["profile_token"]
        reply = await api.call(
            "POST", "/v1/study/sources", {"kind": "text", "title": "Paris", "text": PAGE["text"]}, profile=token
        )
        assert reply.status_code == 201
        sid = reply.json()["source_id"]
        runtime.core.study.desk().conn.execute(
            "INSERT INTO study_cloud_cleanup VALUES (?,?,?)", ("stj_" + "1" * 26, sid, 9999999999999)
        )
        saved = await api.call("GET", "/v1/study/workspace", profile=token)
        assert saved.json()["cleanup_pending"] is False
        assert (await api.call("DELETE", "/v1/study/sources/" + sid, profile=token)).status_code == 200
        erased = await api.call("GET", "/v1/study/workspace", profile=token)
        assert erased.json()["cleanup_pending"] is True

    with_api(tmp_path, scenario, Settings(study_workspace_enabled=True))


def test_public_page_import_is_explicit_guarded_idempotent_and_keeps_provenance(tmp_path):
    async def scenario(api, runtime):
        adult = await api.add(student("Synthetic adult", age_band="18_plus"))
        token = (await api.unlock(adult)).json()["profile_token"]
        sent = []

        class Cloud:
            allowed = False

            def guard(self, conn):
                if not self.allowed:
                    raise StudyCloudError("consent_required")

            async def send(self, conn, method, path, body):
                self.guard(conn)
                sent.append((method, path, body))
                return PAGE

        cloud = Cloud()
        runtime.core.study.cloud = cloud
        body = {"url": URL, "tavily_consent": True}
        assert (await api.call("POST", "/v1/study/web", body)).status_code == 401
        assert (
            await api.call("POST", "/v1/study/web", {**body, "tavily_consent": False}, profile=token)
        ).status_code == 422
        assert (await api.call("POST", "/v1/study/web", body, profile=token)).status_code == 403
        assert sent == []
        cloud.allowed = True
        headers = {"idempotency-key": "cli_" + "1" * 26}
        reply = await api.call("POST", "/v1/study/web", body, profile=token, headers=headers)
        assert reply.status_code == 200, reply.text
        source = reply.json()
        assert source["title"] == "Paris" and source["state"] == "ready"
        chunks = runtime.core.study.desk().chunks(source["source_id"], 1)["items"]
        assert URL in chunks[0]["text"] and PAGE["text"] in chunks[0]["text"]
        assert sent == [("POST", "/v1/web/extract", {**body, "request_id": "ask_" + "1" * 26})]
        replay = await api.call("POST", "/v1/study/web", body, profile=token, headers=headers)
        assert replay.status_code == 200 and replay.json()["source_id"] == source["source_id"]
        assert len(sent) == 1
        conflict = await api.call(
            "POST",
            "/v1/study/web",
            {**body, "url": "https://www.britannica.com/place/London"},
            profile=token,
            headers=headers,
        )
        assert conflict.status_code == 409 and len(sent) == 1

    with_api(tmp_path, scenario, Settings(study_workspace_enabled=True))


def test_a_profile_switch_during_web_import_cannot_publish_into_another_profile(tmp_path):
    async def scenario(api, runtime):
        first = await api.add(student("First adult", age_band="18_plus"))
        second = await api.add(student("Second adult", age_band="18_plus"))
        token = (await api.unlock(first)).json()["profile_token"]
        waiting, release = asyncio.Event(), asyncio.Event()

        class Cloud:
            def guard(self, conn):
                pass

            async def send(self, conn, method, path, body):
                waiting.set()
                await release.wait()
                return PAGE

        runtime.core.study.cloud = Cloud()
        pending = asyncio.create_task(
            api.call("POST", "/v1/study/web", {"url": URL, "tavily_consent": True}, profile=token)
        )
        await asyncio.wait_for(waiting.wait(), 5)
        await api.unlock(second)
        release.set()
        reply = await pending
        assert reply.status_code == 401, reply.text
        assert runtime.core.study.desk().conn.execute("SELECT count(*) FROM study_sources").fetchone()[0] == 0

    with_api(tmp_path, scenario, Settings(study_workspace_enabled=True))
