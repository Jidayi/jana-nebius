"""Profile-scoped M42 commands. Private-source grants are checked on every request, including idempotent replay."""

from __future__ import annotations

import contextlib
import hashlib
import json
import re
import sqlite3
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from agent_core.api.core import CURRENT_PROFILE, CoreService
from agent_core.api.errors import ApiError
from agent_core.config.personal_data import Redactor
from agent_core.engine.events import new_id
from agent_core.engine.study import StudyDesk, StudyError, atomic, checked
from agent_core.engine.study_journey import StudyJourney
from agent_core.engine.study_topics import matching_topics
from agent_core.engine.verbaliser import verbalise
from agent_core.store.events import iso_ms
from agent_core.store.sqlite import transaction


def add_routes(app: FastAPI, core: CoreService) -> None:
    def desk() -> StudyDesk:
        core._guard()
        if not core.settings.study_workspace_enabled:
            raise ApiError("feature_disabled")
        if CURRENT_PROFILE.get() is None or CURRENT_PROFILE.get() != core.records_profile:
            raise ApiError("profile_token_expired")
        core.assessment_guard()
        return core.study.desk()

    def fail(error: StudyError) -> ApiError:
        if error.reason == "not_found":
            return ApiError("not_found")
        if error.reason in ("consent_required", "allowance_exhausted"):
            return ApiError("feature_disabled", details={"reason": error.reason})
        return ApiError("request_conflict" if error.conflict else "validation_failed", details={"reason": error.reason})

    def authorise(request: Request, selections: list[dict[str, Any]]) -> None:
        for s in selections:
            core.study.authorise(s["source_id"], request.headers.get("x-study-open", ""), s["revision"])

    def refs(request: Request, kind: str, identity: str) -> list[dict[str, Any]]:
        d = desk()
        if kind == "source":
            s = d.source(identity)
            selections = [{"source_id": identity, "revision": s["revision"]}]
        elif kind == "job":
            selections = d.job(identity)["sources"]
        elif kind == "aid":
            selections = d.aid(identity)["sources"]
        elif kind == "deck":
            deck = d.deck(identity)
            selections = d.aid(deck["aid_id"])["sources"]
        else:
            selections = d.aid(d.quiz(identity)["view"]["aid_id"])["sources"]
        authorise(request, selections)
        return selections

    def response(payload: Any, status: int = 200) -> JSONResponse:
        return JSONResponse(payload, status_code=status, headers={"Cache-Control": "no-store"})

    async def command(
        request: Request,
        schema: str | None,
        run: Callable[[StudyDesk, Any], Awaitable[Any]],
        access: tuple[str, str] | None = None,
        *,
        status: int = 200,
        atomic_command: bool = True,
    ) -> Response:
        try:
            d = desk()

            def resolve_access() -> list[dict[str, Any]]:
                if not access:
                    return []
                try:
                    return refs(request, *access)
                except StudyError as error:
                    if not (
                        request.method == "DELETE"
                        and error.reason == "not_found"
                        and d.conn.execute("SELECT 1 FROM study_tombstones WHERE source_id=?", (access[1],)).fetchone()
                    ):
                        raise
                    return []

            if schema in ("SourceCreate", "SourceRevision", "UploadChunk") and core.storage_low and core.storage_low():
                raise ApiError("storage_full")
            raw = await request.body()
            if len(raw) > 1_500_000:
                raise ApiError("payload_too_large")
            try:
                body = json.loads(raw) if raw else {}
            except ValueError:
                raise ApiError("invalid_request") from None
            if schema:
                checked(schema, body)
            elif body != {}:
                raise StudyError("invalid_study_request")
            key = request.headers.get("idempotency-key", "")
            if not key.startswith("cli_") or len(key) > 64:
                raise ApiError("invalid_request")
            core.limit_command(request.url.path)
            sha = core.idempotency.digest(request.method, request.url.path, body)
            key = "study:" + key
            cached = d.conn.execute(
                "SELECT request_sha256,status,response FROM idempotency_responses WHERE idempotency_key=?", (key,)
            ).fetchone()
            if cached:
                if cached[0] != sha:
                    raise ApiError("request_conflict")
                resolve_access()
                stored = json.loads(cached[2])
                authorise(request, stored["sources"])
                return response(stored["body"], cached[1])
            from agent_core.api import screening
            from agent_core.api.app import route_key

            screening.screen(core, route_key(request), request.path_params, body)
            access_sources = resolve_access()
            # Fixed commands do not await external work: their writes and cached response are one transaction.
            # Card editing performs its model check first and commits inside its own guarded apply step.
            with atomic(d.conn) if atomic_command else contextlib.nullcontext():
                payload = await run(d, body)
                selections = []
                if access:
                    selections = access_sources if request.method != "DELETE" else []
                elif isinstance(payload, dict):
                    selections = payload.get("sources", [])
                    if "source_id" in payload and payload.get("state") != "deleted":
                        selections = [{"source_id": payload["source_id"], "revision": payload["revision"]}]
                d.conn.execute(
                    "INSERT INTO idempotency_responses VALUES (?,?,?,?,?)",
                    (key, sha, status, json.dumps({"sources": selections, "body": payload}), core.clock_ms()),
                )
            core.study.poll()
            return response(payload, status)
        except StudyError as error:
            raise fail(error) from None
        except sqlite3.Error:
            raise ApiError("storage_full") from None

    def read(request: Request, run: Callable[[StudyDesk], Any], access: tuple[str, str] | None = None) -> Response:
        try:
            d = desk()
            if access:
                refs(request, *access)
            return response(run(d))
        except StudyError as error:
            raise fail(error) from None

    def number(value: str, low: int, high: int) -> int:
        try:
            n = int(value)
        except ValueError:
            raise StudyError("invalid_study_request") from None
        if not low <= n <= high:
            raise StudyError("invalid_study_request")
        return n

    @app.get("/v1/study/workspace")
    async def workspace(request: Request, cursor: str | None = None) -> Response:
        def get(d: StudyDesk) -> Any:
            jobs = []
            for row in d.conn.execute("SELECT body FROM study_jobs ORDER BY updated_at DESC LIMIT 100"):
                job = json.loads(row[0])
                try:
                    authorise(request, job["sources"])
                except StudyError:
                    continue
                jobs.append(job)
            return checked(
                "StudySnapshot",
                {
                    "sources": d.sources(cursor),
                    "journey": StudyJourney(d).current(lambda selections: authorise(request, selections)),
                    "jobs": jobs,
                    # The UI's deletion notice applies only to erased sources. Active
                    # jobs also hold temporary cleanup receipts, without deleting files.
                    "cleanup_pending": bool(
                        d.conn.execute(
                            "SELECT 1 FROM study_cloud_cleanup c JOIN study_tombstones t "
                            "ON t.source_id=c.source_id LIMIT 1"
                        ).fetchone()
                    ),
                },
            )

        return read(request, get)

    @app.get("/v1/study/library")
    async def library(request: Request) -> Response:
        return read(request, lambda d: d.library())

    @app.post("/v1/study/sources/{source_id}/archive")
    async def archive_source(source_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, _body: Any) -> Any:
            return d.archive_source(source_id, True)

        return await command(request, None, run)

    @app.delete("/v1/study/sources/{source_id}/archive")
    async def restore_source(source_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, _body: Any) -> Any:
            return d.archive_source(source_id, False)

        return await command(request, None, run)

    @app.post("/v1/study/sources")
    async def create_source(request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            return d.create(body)

        return await command(request, "SourceCreate", run, status=201)

    @app.get("/v1/study/sources/{source_id}/topics")
    async def topics(source_id: str, request: Request) -> Response:
        def get(d: StudyDesk) -> Any:
            source = d.source(source_id)
            text = d.curriculum_text({"source_id": source_id, "revision": source["revision"]})
            content = core.study.content() if core.study.content else None
            return checked("TopicLinks", matching_topics(content, text) if content else {"items": []})

        return read(request, get, ("source", source_id))

    @app.get("/v1/study/sources/{source_id}/material-topics")
    async def material_topics(source_id: str, request: Request, revision: str | None = None) -> Response:
        try:
            d = desk()
            rev = number(revision, 1, 2147483647) if revision is not None else d.source(source_id)["revision"]
            selection = [{"source_id": source_id, "revision": rev}]
            authorise(request, selection)
            return response(checked("MaterialTopics", {"items": d.topics(selection)}))
        except StudyError as error:
            raise fail(error) from None

    @app.get("/v1/study/sources/{source_id}/media")
    async def media(source_id: str, request: Request, revision: str | None = None) -> Response:
        try:
            d = desk()
            rev = number(revision, 1, 2147483647) if revision is not None else d.source(source_id)["revision"]
            authorise(request, [{"source_id": source_id, "revision": rev}])
            data, kind = d.media(source_id, rev)
            return Response(data, media_type=kind, headers={"Cache-Control": "no-store"})
        except StudyError as error:
            raise fail(error) from None
        except OSError:
            raise fail(StudyError("not_found")) from None

    @app.get("/v1/study/sets")
    async def sets(request: Request, cursor: str | None = None) -> Response:
        def granted(selections: list[dict[str, Any]]) -> bool:
            try:
                authorise(request, selections)
            except StudyError:
                return False
            return True

        return read(request, lambda d: d.sets(granted, cursor))

    @app.post("/v1/study/retries/{digest}")
    async def retry_identity(digest: str, request: Request) -> Response:
        try:
            d = desk()
            checked("Digest", digest)
            core.limit_command(request.url.path)
            if await request.body() not in (b"", b"{}"):
                raise StudyError("invalid_study_request")
            key, now = "study-pending:" + digest, core.clock_ms()
            ttl = int(core.settings.api_idempotency_hours * 3600000)
            with atomic(d.conn):
                d.conn.execute(
                    "DELETE FROM idempotency_responses WHERE idempotency_key LIKE 'study-pending:%' AND created_at<?",
                    (now - ttl,),
                )
                row = d.conn.execute(
                    "SELECT response FROM idempotency_responses WHERE idempotency_key=?", (key,)
                ).fetchone()
                if row is None:
                    if (
                        d.conn.execute(
                            "SELECT count(*) FROM idempotency_responses WHERE idempotency_key LIKE 'study-pending:%'"
                        ).fetchone()[0]
                        >= 1024
                    ):
                        raise StudyError("queue_full")
                    identity = checked("RetryIdentity", {"client_key": new_id("cli"), "expires_at": iso_ms(now + ttl)})
                    d.conn.execute(
                        "INSERT INTO idempotency_responses VALUES (?,?,?,?,?)",
                        (key, digest, 102, json.dumps(identity), now),
                    )
                else:
                    identity = json.loads(row[0])
            return response(identity)
        except StudyError as error:
            raise fail(error) from None

    @app.delete("/v1/study/retries/{digest}")
    async def acknowledge_retry(digest: str, request: Request) -> Response:
        try:
            d = desk()
            checked("Digest", digest)
            d.conn.execute(
                "DELETE FROM idempotency_responses WHERE idempotency_key=? AND json_extract(response,'$.client_key')=?",
                ("study-pending:" + digest, request.headers.get("idempotency-key", "")),
            )
            return Response(status_code=204, headers={"Cache-Control": "no-store"})
        except StudyError as error:
            raise fail(error) from None

    @app.get("/v1/study/aids/{aid_id}/speech")
    async def speech(
        aid_id: str, request: Request, claim: str = "0", offset: str = "0", limit: str = "3500", neural: bool = False
    ) -> Response:
        def get(d: StudyDesk) -> Any:
            aid = d.aid(aid_id)
            if aid["kind"] != "audio_overview" or aid["status"] != "ready":
                raise StudyError("source_stale")
            if neural:
                if not core.settings.study_neural_speech_enabled or core.study.cloud is None:
                    raise StudyError("neural_speech_not_configured")
                try:
                    core.study.cloud.guard(d.conn)
                except ValueError as error:
                    raise StudyError(getattr(error, "reason", "consent_required")) from None
                if any(d.source(source["source_id"])["private"] for source in aid["sources"]):
                    raise StudyError("neural_speech_private_material")
            index, start = number(claim, 0, len(aid["claims"]) - 1), number(offset, 0, 100000)
            text = verbalise(aid["claims"][index]["text"]).text
            if start >= len(text):
                raise StudyError("invalid_study_request")
            end = min(len(text), start + number(limit, 100, 3500))
            if end < len(text):
                end = max(start + 1, text.rfind(" ", start, end))
            return checked(
                "SpeechPassage",
                {
                    "aid_id": aid_id,
                    "claim_index": index,
                    "text": text[start:end],
                    "next_offset": end if end < len(text) else None,
                    "last_claim": index == len(aid["claims"]) - 1,
                },
            )

        return read(request, get, ("aid", aid_id))

    @app.get("/v1/study/podcast-voice")
    async def podcast_voice(request: Request) -> Response:
        d = desk()
        enabled = core.settings.study_neural_speech_enabled
        status = {"enabled": enabled, "configured": False, "provider": "nvidia_magpie"}
        if enabled and core.study.cloud is not None:
            try:
                remote = await core.study.cloud.send(d.conn, "GET", "/v1/podcast/voice")
                if isinstance(remote, dict) and remote.get("provider") == "nvidia_magpie":
                    status["configured"] = remote.get("enabled") is True and remote.get("configured") is True
            except ValueError:
                pass  # Status never grants consent or silently selects the system voice.
        return response(status)

    @app.post("/v1/study/aids/{aid_id}/neural-speech")
    async def neural_speech(aid_id: str, request: Request) -> Response:
        try:
            d = desk()
            if not core.settings.study_neural_speech_enabled or core.study.cloud is None:
                raise StudyError("neural_speech_not_configured")
            refs(request, "aid", aid_id)
            core.limit_command(request.url.path)
            body = await request.json()
            if (
                not isinstance(body, dict)
                or set(body) != {"claim", "offset", "text_sha256", "nvidia_consent"}
                or body.get("nvidia_consent") is not True
                or type(body.get("claim")) is not int
                or type(body.get("offset")) is not int
                or not isinstance(body.get("text_sha256"), str)
                or not re.fullmatch(r"[0-9a-f]{64}", body["text_sha256"])
            ):
                raise StudyError("invalid_study_request")
            key = request.headers.get("idempotency-key", "")
            if not re.fullmatch(r"cli_[0-9A-HJKMNP-TV-Z]{26}", key):
                raise StudyError("invalid_study_request")
            aid = d.aid(aid_id)
            if aid["kind"] != "audio_overview" or aid["status"] != "ready":
                raise StudyError("source_stale")
            if any(d.source(source["source_id"])["private"] for source in aid["sources"]):
                raise StudyError("neural_speech_private_material")
            # Reuse the exact passage preparation read by the browser, without accepting arbitrary client text.
            passage_response = await speech(aid_id, request, str(body["claim"]), str(body["offset"]), "600")
            passage = json.loads(bytes(passage_response.body))
            text = passage["text"]
            if hashlib.sha256(text.encode()).hexdigest() != body["text_sha256"]:
                raise StudyError("source_stale")
            voice_index = body["claim"] % 2 if aid.get("settings", {}).get("voices") == 2 else 0
            audio = await core.study.cloud.podcast_audio(d.conn, text, key, voice_index)
            # Consent/profile changes, private-grant expiry and deletion during synthesis must withhold playback.
            core.study.cloud.guard(d.conn)
            refs(request, "aid", aid_id)
            if d.aid(aid_id)["status"] != "ready" or any(
                d.source(source["source_id"])["private"] for source in aid["sources"]
            ):
                raise StudyError("source_stale")
            return Response(audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
        except (ValueError, TypeError) as error:
            if isinstance(error, StudyError):
                raise fail(error) from None
            raise fail(StudyError(getattr(error, "reason", "invalid_study_request"))) from None

    @app.get("/v1/study/sources/{source_id}")
    async def source(source_id: str, request: Request) -> Response:
        return read(request, lambda d: d.public(d.source(source_id)))

    @app.post("/v1/study/sources/{source_id}/open")
    async def open_source(source_id: str, request: Request) -> Response:
        # Grants are memory-only and never idempotency/archive/model data. Confirmation may be repeated after expiry.
        try:
            desk()
            body = checked("SourceOpen", await request.json())
            if not request.headers.get("idempotency-key", "").startswith("cli_"):
                raise ApiError("invalid_request")
            return response(core.study.open(source_id, body.get("revision")))
        except (ValueError, StudyError) as error:
            raise fail(error if isinstance(error, StudyError) else StudyError("invalid_study_request")) from None

    @app.delete("/v1/study/sources/{source_id}/open")
    async def close_source(source_id: str, request: Request) -> Response:
        desk()
        tokens = request.headers.get("x-study-open", "").split(",")
        core.study.grants = {
            t: v
            for t, v in core.study.grants.items()
            if not (t in tokens and v[0] is core.study.connection() and v[1] == source_id)
        }
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.post("/v1/study/sources/{source_id}/revisions")
    async def revision(source_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            return d.revise(source_id, body)

        return await command(request, "SourceRevision", run, ("source", source_id), status=201)

    @app.put("/v1/study/sources/{source_id}/chunks/{chunk_index}")
    async def upload(source_id: str, chunk_index: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            return d.upload(source_id, number(chunk_index, 0, 99), body)

        return await command(request, "UploadChunk", run, ("source", source_id))

    @app.patch("/v1/study/sources/{source_id}")
    async def patch(source_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            result = d.patch(source_id, body)
            if body.get("private") is True:
                core.study.grants = {t: v for t, v in core.study.grants.items() if v[1] != source_id}
            return result

        # A private mark changes visibility; current access is checked before mutating, not after it.
        return await command(request, "SourcePatch", run, ("source", source_id))

    @app.delete("/v1/study/sources/{source_id}")
    async def delete(source_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            if (
                core.study.jid
                and core.study.task
                and not core.study.task.done()
                and any(s["source_id"] == source_id for s in d.job(core.study.jid)["sources"])
            ):
                core.study.pause()
            result = d.delete(source_id)
            core.study.grants = {t: v for t, v in core.study.grants.items() if v[1] != source_id}
            return result

        return await command(request, None, run, ("source", source_id))

    @app.get("/v1/study/sources/{source_id}/content")
    async def content(
        source_id: str, request: Request, revision: str = "1", cursor: str | None = None, limit: str = "20"
    ) -> Response:
        try:
            d = desk()
            rev = number(revision, 1, 2147483647) if revision is not None else d.source(source_id)["revision"]
            authorise(request, [{"source_id": source_id, "revision": rev}])
            return response(d.chunks(source_id, rev, cursor, number(limit, 1, 100)))
        except StudyError as error:
            raise fail(error) from None

    @app.get("/v1/study/sources/{source_id}/pages/{page}")
    async def page_raster(source_id: str, page: str, request: Request, revision: str | None = None) -> Response:
        try:
            d = desk()
            source = d.source(source_id)
            rev = number(revision, 1, 100000) if revision is not None else source["revision"]
            authorise(request, [{"source_id": source_id, "revision": rev}])
            png = await d.page_raster(source_id, rev, number(page, 1, 300))
            # Recheck after subprocess work: profile switching, erasure and private expiry invalidate the response.
            if desk().conn is not d.conn:
                raise StudyError("grant_expired")
            authorise(request, [{"source_id": source_id, "revision": rev}])
            d.source(source_id)
            return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})
        except StudyError as error:
            raise fail(error) from None

    @app.post("/v1/study/search")
    async def search(request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            try:
                offset = int(body.get("cursor") or "0")
            except ValueError:
                raise StudyError("invalid_study_request") from None
            if offset < 0:
                raise StudyError("invalid_study_request")
            query = body["query"].casefold()
            hits = []
            for row in d.conn.execute(
                "SELECT c.body FROM study_chunks c JOIN study_sources s USING(source_id) "
                "WHERE s.private=0 AND c.revision=s.current_revision ORDER BY c.source_id,c.ordinal"
            ):
                c = json.loads(row[0])
                at = c["text"].casefold().find(query)
                if at >= 0:
                    hits.append(
                        {k: c[k] for k in ("source_id", "revision", "chunk_id", "locator")}
                        | {"snippet": c["text"][max(0, at - 80) : max(0, at - 80) + 500]}
                    )
            return checked(
                "SearchResult",
                {
                    "items": hits[offset : offset + 50],
                    "next_cursor": str(offset + 50) if len(hits) > offset + 50 else None,
                },
            )

        # Search is a read despite its JSON body: do not persist query/snippets in idempotency storage.
        try:
            d = desk()
            body = checked("SearchRequest", await request.json())
            return response(await run(d, body))
        except (ValueError, StudyError) as error:
            raise fail(error if isinstance(error, StudyError) else StudyError("invalid_study_request")) from None

    @app.post("/v1/study/jobs")
    async def create_job(request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            # A private syllabus file needs its own open grant, like the material (STU-19, STU-21).
            authorise(request, [*body["sources"], *body.get("settings", {}).get("syllabus", [])])
            if body["execution"] == "prefer_cloud":
                if core.study.cloud is None:
                    raise StudyError("consent_required")
                try:
                    core.study.cloud.guard(d.conn)
                except ValueError as error:
                    if (
                        getattr(error, "reason", None) == "allowance_exhausted"
                        and body["kind"] != "extract"
                        and d.local_possible(body)
                    ):
                        job = d.create_job({**body, "execution": "local"})
                        job["notice"] = "allowance_exhausted"
                        d.save_job(job)
                        return job
                    raise StudyError(getattr(error, "reason", "consent_required")) from None
            return d.create_job(body)

        return await command(request, "JobCreate", run, status=202)

    @app.post("/v1/study/quizzes/{quiz_id}/items/{item_id}/help")
    async def quiz_help(quiz_id: str, item_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            authorise(request, body["sources"])
            if body["execution"] == "prefer_cloud":
                if core.study.cloud is None:
                    raise StudyError("consent_required")
                try:
                    core.study.cloud.guard(d.conn)
                except ValueError as error:
                    raise StudyError(getattr(error, "reason", "consent_required")) from None
            return d.create_quiz_help_job(quiz_id, item_id, body)

        return await command(request, "JobCreate", run, ("quiz", quiz_id), status=202)

    @app.post("/v1/study/web")
    async def import_web(request: Request) -> Response:
        """Explicitly import a public web page; no uploaded file is ever sent to Tavily."""
        from urllib.parse import urlsplit

        from agent_core.api import screening

        try:
            d = desk()
            raw = await request.body()
            if len(raw) > 4096:
                raise ApiError("payload_too_large")
            body = json.loads(raw)
            if (
                not isinstance(body, dict)
                or set(body) != {"url", "tavily_consent"}
                or body["tavily_consent"] is not True
                or not isinstance(body["url"], str)
                or not 1 <= len(body["url"]) <= 2048
            ):
                raise StudyError("invalid_public_url")
            key = request.headers.get("idempotency-key", "")
            import re

            if not re.fullmatch(r"cli_[0-9A-HJKMNP-TV-Z]{26}", key):
                raise ApiError("invalid_request")
            core.limit_command(request.url.path)
            screening.screen(core, "POST /v1/study/web", {}, body)
            identifying = d.conn.execute("SELECT display_name,profile_id FROM profile").fetchone()
            if Redactor(identifying or ()).blocks(body):
                raise StudyError("safety_blocked")
            cloud = core.study.cloud
            if cloud is None:
                raise StudyError("consent_required")
            cloud.guard(d.conn)
            sha = core.idempotency.digest(request.method, request.url.path, body)
            cache_key = "study:" + key
            cached = d.conn.execute(
                "SELECT request_sha256,response FROM idempotency_responses WHERE idempotency_key=?", (cache_key,)
            ).fetchone()
            if cached:
                if cached[0] != sha:
                    raise ApiError("request_conflict")
                stored = json.loads(cached[1])
                authorise(request, stored["sources"])
                return response(stored["body"])
            page = await cloud.send(
                d.conn, "POST", "/v1/web/extract", {**body, "request_id": key.replace("cli_", "ask_", 1)}
            )
            if core.study.connection() is not d.conn or CURRENT_PROFILE.get() != core.records_profile:
                raise ApiError("profile_token_expired")
            if (
                not isinstance(page, dict)
                or set(page) != {"url", "title", "text"}
                or not all(isinstance(v, str) for v in page.values())
                or not 1 <= len(page["text"]) <= 180000
                or not 1 <= len(page["title"]) <= 160
            ):
                raise StudyError("web_page_unreadable")
            if (
                urlsplit(page["url"]).scheme != "https"
                or urlsplit(page["url"]).hostname != urlsplit(body["url"]).hostname
            ):
                raise StudyError("web_page_unreadable")
            with atomic(d.conn):
                source = d.create(
                    {
                        "kind": "text",
                        "title": page["title"],
                        "text": "Source URL: " + page["url"] + "\n\n" + page["text"],
                    }
                )
                cached_body = {
                    "body": source,
                    "sources": [{"source_id": source["source_id"], "revision": source["revision"]}],
                }
                d.conn.execute(
                    "INSERT INTO idempotency_responses VALUES (?,?,200,?,?)",
                    (cache_key, sha, json.dumps(cached_body), core.clock_ms()),
                )
            return response(source)
        except (ValueError, StudyError) as error:
            raise fail(StudyError(getattr(error, "reason", "invalid_public_url"))) from None

    @app.get("/v1/study/jobs/{job_id}")
    async def job(job_id: str, request: Request) -> Response:
        return read(request, lambda d: d.job(job_id), ("job", job_id))

    @app.post("/v1/study/jobs/{job_id}/actions")
    async def action(job_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            result = d.action(job_id, body)
            if body["action"] == "cancel" and core.study.jid == job_id:
                core.study.pause()
            return result

        return await command(request, "JobAction", run, ("job", job_id))

    @app.get("/v1/study/aids")
    async def aids(
        request: Request,
        source_id: str | None = None,
        revision: str | None = None,
        cursor: str | None = None,
        limit: str = "20",
    ) -> Response:
        def get(d: StudyDesk) -> Any:
            size = number(limit, 1, 100)
            items = []
            for row in d.conn.execute(
                "SELECT aid_id,body FROM study_aids WHERE aid_id>? ORDER BY aid_id", (cursor or "",)
            ):
                aid = json.loads(row[1])
                if source_id and not any(
                    s["source_id"] == source_id
                    and (revision is None or s["revision"] == number(revision, 1, 2147483647))
                    for s in aid["sources"]
                ):
                    continue
                try:
                    authorise(request, aid["sources"])
                except StudyError:
                    continue
                items.append(aid)
                if len(items) > size:
                    break
            return checked(
                "AidList",
                {"items": items[:size], "next_cursor": items[size - 1]["aid_id"] if len(items) > size else None},
            )

        return read(request, get)

    @app.get("/v1/study/aids/{aid_id}")
    async def aid(aid_id: str, request: Request) -> Response:
        return read(request, lambda d: d.aid(aid_id), ("aid", aid_id))

    @app.post("/v1/study/aids/{aid_id}/journey")
    async def saved_journey(aid_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            journey = StudyJourney(d)
            if body["action"] == "start":
                journey.start(aid_id)
            elif body["action"] == "lesson_reviewed":
                if journey.root(aid_id) != aid_id:
                    raise StudyError("invalid_study_request")
                journey.resume(aid_id, reviewed=True)
            else:
                journey.resume(aid_id)
            return checked("StudyJourneyReply", {"journey": journey.current(lambda s: authorise(request, s))})

        return await command(request, "StudyJourneyAction", run, ("aid", aid_id))

    @app.get("/v1/study/quizzes/{quiz_id}/saved-result")
    async def saved_quiz_result(quiz_id: str, request: Request) -> Response:
        def get(d: StudyDesk) -> Any:
            result = StudyJourney(d).saved_result(quiz_id)
            submission = d.quiz(quiz_id).get("submission")
            answers = (
                {"answers": submission["answers"]}
                if result and submission and submission["attempt_id"] == result[0]["attempt_id"]
                else {}
            )
            return checked("QuizSavedResult", {"result": result[0] if result else None, **answers})

        return read(request, get, ("quiz", quiz_id))

    @app.get("/v1/study/decks/{deck_id}")
    async def deck(deck_id: str, request: Request) -> Response:
        return read(request, lambda d: checked("Deck", d.deck(deck_id)), ("deck", deck_id))

    @app.post("/v1/study/decks/{deck_id}/reviews")
    async def review(deck_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            return d.review(deck_id, body)

        return await command(request, "ReviewSubmit", run, ("deck", deck_id))

    @app.get("/v1/study/quizzes/{quiz_id}")
    async def quiz(quiz_id: str, request: Request) -> Response:
        return read(request, lambda d: d.quiz(quiz_id)["view"], ("quiz", quiz_id))

    @app.post("/v1/study/quizzes/{quiz_id}/attempts")
    async def submit(quiz_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            result = await core.study.submit_quiz(quiz_id, body)
            if desk().conn is not d.conn:
                raise StudyError("source_deleted")
            refs(request, "quiz", quiz_id)
            return result

        return await command(request, "QuizSubmit", run, ("quiz", quiz_id), atomic_command=False)

    @app.put("/v1/study/quizzes/{quiz_id}/draft")
    async def draft(quiz_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            return d.save_draft(quiz_id, body)

        return await command(request, "QuizDraft", run, ("quiz", quiz_id))

    @app.patch("/v1/study/decks/{deck_id}/cards/{card_id}")
    async def edit(deck_id: str, card_id: str, request: Request) -> Response:
        async def run(d: StudyDesk, body: Any) -> Any:
            deck = d.deck(deck_id)
            aid = d.aid(deck["aid_id"])
            card = next((c for c in deck["cards"] if c["card_id"] == card_id), None)
            if card is None:
                raise StudyError("not_found")
            if card["revision"] != body["expected_revision"] or card["suspended"]:
                raise StudyError("source_stale", True)
            for key in ("front", "back"):
                d.citation(body[key], aid["sources"])
            model = core.study.model()
            if model is None or not await model.local_ready():
                raise StudyError("model_unavailable")
            supported, local = await model.study_support(
                {}, d.selected(aid["sources"]), {"claims": [], "flashcards": [{k: body[k] for k in ("front", "back")}]}
            )
            if core.study.connection() is not d.conn:
                raise StudyError("not_found")
            refs(request, "deck", deck_id)
            current = next(c for c in d.deck(deck_id)["cards"] if c["card_id"] == card_id)
            if current["revision"] != card["revision"] or current["suspended"]:
                raise StudyError("source_stale", True)
            if not local or supported != [True]:
                raise StudyError("insufficient_evidence")
            card.update(front=body["front"], back=body["back"], revision=card["revision"] + 1)
            with transaction(d.conn):
                d.conn.execute("DELETE FROM study_reviews WHERE card_id=?", (card_id,))
                d.conn.execute(
                    "UPDATE study_flashcards SET body=?,revision=?,schedule=?,due_at=? WHERE card_id=?",
                    (json.dumps(card), card["revision"], json.dumps(d.empty_schedule()), core.clock_ms(), card_id),
                )
            return card

        return await command(request, "CardEdit", run, ("deck", deck_id), atomic_command=False)
