"""Native narration binds audio to a saved cited passage, source grants and current Study consent."""

import asyncio
import hashlib

from agent_core.config import Settings
from agent_core.net.study import StudyCloudError
from test_m10a_profiles import student
from test_m10e_consent import with_api
from test_study_workspace import claim


async def podcast(api, runtime, private=False):
    adult = await api.add(student("Synthetic adult", age_band="18_plus"))
    token = (await api.unlock(adult)).json()["profile_token"]
    d = runtime.core.study.desk()
    source = d.create({"kind": "text", "title": "Biology", "text": "Enzymes are biological catalysts. " * 40})
    chunks = d.selected([{"source_id": source["source_id"], "revision": 1}])
    job = d.create_job(
        {
            "kind": "audio_overview",
            "execution": "local",
            "sources": [
                {"source_id": source["source_id"], "revision": 1},
            ],
        }
    )
    job["state"] = "running"
    d.save_job(job)
    d.commit_aid(job, {"request_id": job["job_id"], "kind": "audio_overview", "claims": [claim(chunks[0])]}, [True])
    aid = d.aid(d.job(job["job_id"])["result_ids"][0])
    if private:
        await api.call("PATCH", "/v1/study/sources/" + source["source_id"], {"private": True}, profile=token)
    opened = await api.call(
        "POST", "/v1/study/sources/" + source["source_id"] + "/open", {"confirm": True}, profile=token
    )
    headers = {"x-study-open": opened.json()["open_token"], "idempotency-key": "cli_" + "1" * 26}
    passage = (
        await api.call("GET", f"/v1/study/aids/{aid['aid_id']}/speech?limit=600", profile=token, headers=headers)
    ).json()
    return token, aid, headers, passage


class Cloud:
    allowed = True

    def __init__(self):
        self.sent = []

    def guard(self, conn):
        if not self.allowed:
            raise StudyCloudError("consent_required")

    async def send(self, conn, method, path):
        self.guard(conn)
        return {"enabled": True, "configured": True, "provider": "nvidia_magpie"}

    async def podcast_audio(self, conn, text, key, voice_index):
        self.guard(conn)
        self.sent.append((text, key, voice_index))
        return b"RIFF" + b"\x00" * 4 + b"WAVE" + b"\x00" * 40


def settings():
    return Settings(study_workspace_enabled=True, study_offline_enabled=True, study_neural_speech_enabled=True)


def test_native_neural_audio_uses_the_saved_passage_not_client_text_and_requires_consent(tmp_path):
    async def run(api, runtime):
        token, aid, headers, passage = await podcast(api, runtime)
        cloud = Cloud()
        runtime.core.study.cloud = cloud
        path = f"/v1/study/aids/{aid['aid_id']}/neural-speech"
        body = {
            "claim": 0,
            "offset": 0,
            "text_sha256": hashlib.sha256(passage["text"].encode()).hexdigest(),
            "nvidia_consent": True,
        }
        assert (await api.call("POST", path, body)).status_code == 401
        for change in ({"text": "invented text"}, {"text_sha256": "0" * 64}, {"nvidia_consent": False}):
            assert (await api.call("POST", path, {**body, **change}, profile=token, headers=headers)).status_code != 200
        assert cloud.sent == []
        cloud.allowed = False
        assert (await api.call("POST", path, body, profile=token, headers=headers)).status_code == 403
        cloud.allowed = True
        result = await api.call("POST", path, body, profile=token, headers=headers)
        assert result.status_code == 200, result.text
        assert result.headers["content-type"] == "audio/wav" and result.headers["cache-control"] == "no-store"
        assert cloud.sent == [(passage["text"], "cli_" + "1" * 26, 0)]

    with_api(tmp_path, run, settings())


def test_private_marked_sources_never_reach_the_nvidia_trial(tmp_path):
    async def run(api, runtime):
        token, aid, headers, passage = await podcast(api, runtime, private=True)
        cloud = Cloud()
        runtime.core.study.cloud = cloud
        body = {
            "claim": 0,
            "offset": 0,
            "text_sha256": hashlib.sha256(passage["text"].encode()).hexdigest(),
            "nvidia_consent": True,
        }
        result = await api.call(
            "POST", f"/v1/study/aids/{aid['aid_id']}/neural-speech", body, profile=token, headers=headers
        )
        assert result.status_code != 200 and cloud.sent == []

    with_api(tmp_path, run, settings())


def test_consent_withdrawal_during_synthesis_withholds_audio(tmp_path):
    async def run(api, runtime):
        token, aid, headers, passage = await podcast(api, runtime)
        waiting, release = asyncio.Event(), asyncio.Event()

        class SlowCloud(Cloud):
            async def podcast_audio(self, *args):
                audio = await super().podcast_audio(*args)
                waiting.set()
                await release.wait()
                return audio

        cloud = SlowCloud()
        runtime.core.study.cloud = cloud
        body = {
            "claim": 0,
            "offset": 0,
            "text_sha256": hashlib.sha256(passage["text"].encode()).hexdigest(),
            "nvidia_consent": True,
        }
        pending = asyncio.create_task(
            api.call("POST", f"/v1/study/aids/{aid['aid_id']}/neural-speech", body, profile=token, headers=headers)
        )
        await waiting.wait()
        cloud.allowed = False
        release.set()
        assert (await pending).status_code == 403

    with_api(tmp_path, run, settings())


def test_buffered_passage_rechecks_consent_before_playback_without_synthesizing_again(tmp_path):
    async def run(api, runtime):
        token, aid, headers, _ = await podcast(api, runtime)
        cloud = Cloud()
        runtime.core.study.cloud = cloud
        path = f"/v1/study/aids/{aid['aid_id']}/speech?limit=600&neural=true"
        assert (await api.call("GET", path, profile=token, headers=headers)).status_code == 200
        cloud.allowed = False
        assert (await api.call("GET", path, profile=token, headers=headers)).status_code == 403
        assert cloud.sent == []

    with_api(tmp_path, run, settings())
