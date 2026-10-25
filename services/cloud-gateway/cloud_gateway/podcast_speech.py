"""NVIDIA Magpie narration for the hackathon prototype, bounded independently of paid inference.

Only NVIDIA's documented free API-catalog function is reachable. Text and audio are ephemeral here; the trial
provider's own retention is disclosed in Jana. Durable receipts contain opaque identities and character counts.
An uncertain/failed send remains counted, and a transport retry never repeats synthesis automatically.
"""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import io
import json
import logging
import re
import wave
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cloud_gateway import minimise
from cloud_gateway.auth import AuthError

BASE = "https://877104f7-e885-42b9-8de8-f6e4c6303969.invocation.api.nvcf.nvidia.com"
VOICES = ("Magpie-Multilingual.EN-US.Aria", "Magpie-Multilingual.EN-US.Jason")
MAX_TEXT = 600
MAX_AUDIO = 6_000_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS podcast_speech_receipts (
 identity TEXT PRIMARY KEY, input_digest TEXT NOT NULL, day TEXT NOT NULL,
 characters INTEGER NOT NULL, state TEXT NOT NULL
);
"""


class SpeechError(ValueError):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


def validate_audio(data: bytes) -> None:
    """Reject error pages, truncated WAVs and unbounded/unsupported audio before the browser sees it."""
    if not 44 <= len(data) <= MAX_AUDIO:
        raise SpeechError("neural_speech_invalid_audio")
    try:
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            if (
                audio.getnchannels() != 1
                or audio.getsampwidth() != 2
                or audio.getframerate() != 22050
                or audio.getcomptype() != "NONE"
                or not 0 < frames <= 22050 * 120
                or len(audio.readframes(frames)) != frames * 2
            ):
                raise SpeechError("neural_speech_invalid_audio")
    except (wave.Error, EOFError):
        raise SpeechError("neural_speech_invalid_audio") from None


class NvidiaPodcast:
    def __init__(self, gw: Any, client: httpx.AsyncClient | None = None):
        self.gw = gw
        self.key = gw.secrets.get("nvidia_api_key") if gw.config.podcast_speech.enabled else None
        if gw.config.podcast_speech.enabled and self.key is None:
            logging.getLogger(__name__).warning("NVIDIA Podcast key is unavailable to the gateway secret source")
        self.client = client or httpx.AsyncClient(trust_env=False, follow_redirects=False, timeout=60)
        self.lock = asyncio.Lock()
        gw.store._db.executescript(SCHEMA)

    def status(self) -> dict[str, Any]:
        cfg = self.gw.config.podcast_speech
        active = cfg.enabled and cfg.expires_at is not None and self.gw.clock() < cfg.expires_at.timestamp()
        return {"enabled": cfg.enabled, "configured": bool(active and self.key), "provider": "nvidia_magpie"}

    def reserve(self, owner: str, body: dict[str, Any]) -> str:
        cfg, now = self.gw.config.podcast_speech, self.gw.clock()
        if not cfg.enabled or cfg.expires_at is None or now >= cfg.expires_at.timestamp():
            raise SpeechError("neural_speech_limit")
        if self.key is None:
            raise SpeechError("neural_speech_not_configured")
        identity = hashlib.sha256(f"{owner}:{body['request_id']}".encode()).hexdigest()
        digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
        day = dt.datetime.fromtimestamp(now, dt.UTC).date().isoformat()
        size = len(body["text"])
        with self.gw.store._tx() as db:
            prior = db.execute(
                "SELECT input_digest FROM podcast_speech_receipts WHERE identity=?", (identity,)
            ).fetchone()
            if prior:
                raise SpeechError("neural_speech_already_sent")
            daily, total, calls, all_calls = db.execute(
                "SELECT coalesce(sum(CASE WHEN day=? OR state='held' THEN characters ELSE 0 END),0),"
                "coalesce(sum(characters),0),coalesce(sum(CASE WHEN day=? OR state='held' THEN 1 ELSE 0 END),0),"
                "count(*) FROM podcast_speech_receipts",
                (day, day),
            ).fetchone()
            if (
                daily + size > cfg.daily_characters
                or total + size > cfg.total_characters
                or calls + 1 > cfg.daily_requests
                or all_calls + 1 > cfg.total_requests
            ):
                raise SpeechError("neural_speech_limit")
            db.execute("INSERT INTO podcast_speech_receipts VALUES (?,?,?,?,'held')", (identity, digest, day, size))
        return identity

    async def synthesize(self, owner: str, body: dict[str, Any]) -> bytes:
        async with self.lock:
            identity = self.reserve(owner, body)
            assert self.key is not None
            try:
                async with self.client.stream(
                    "POST",
                    BASE + "/v1/audio/synthesize",
                    headers={"authorization": "Bearer " + self.key.reveal()},
                    files={
                        k: (None, v)
                        for k, v in {
                            "text": body["text"],
                            "language": "en-US",
                            "voice": VOICES[body["voice_index"]],
                            "encoding": "LINEAR_PCM",
                            "sample_rate_hz": "22050",
                        }.items()
                    },
                ) as reply:
                    if reply.status_code in (401, 403):
                        raise SpeechError("neural_speech_key_rejected")
                    if reply.status_code == 429:
                        raise SpeechError("neural_speech_limit")
                    if reply.status_code != 200:
                        raise SpeechError("neural_speech_unavailable")
                    data, size = [], 0
                    async for part in reply.aiter_bytes():
                        size += len(part)
                        if size > MAX_AUDIO:
                            raise SpeechError("neural_speech_invalid_audio")
                        data.append(part)
                    audio = b"".join(data)
                validate_audio(audio)
                self.gw.store._db.execute(
                    "UPDATE podcast_speech_receipts SET state='completed' WHERE identity=?", (identity,)
                )
                return audio
            except httpx.HTTPError:
                raise SpeechError("neural_speech_unavailable") from None


def add_routes(app: FastAPI, gw: Any) -> NvidiaPodcast:
    speech = NvidiaPodcast(gw)

    @app.get("/v1/podcast/voice")
    async def status(request: Request) -> Any:
        try:
            gw.auth.authenticate(request.headers.get("authorization"))
            return JSONResponse(speech.status(), headers={"Cache-Control": "no-store"})
        except AuthError:
            return JSONResponse({"error": {"code": "auth"}}, status_code=401)

    @app.post("/v1/podcast/speech")
    async def narrate(request: Request) -> Any:
        try:
            session = gw.auth.authenticate(request.headers.get("authorization"))
            body = await gw.json_body(request, 8192)
            if (
                not isinstance(body, dict)
                or set(body) != {"request_id", "text", "voice_index", "nvidia_consent"}
                or body.get("nvidia_consent") is not True
                or not isinstance(body.get("request_id"), str)
                or re.fullmatch(r"cli_[0-9A-HJKMNP-TV-Z]{26}", body["request_id"]) is None
                or not isinstance(body.get("text"), str)
                or not 1 <= len(body["text"]) <= MAX_TEXT
                or not body["text"].strip()
                or type(body.get("voice_index")) is not int
                or body["voice_index"] not in (0, 1)
                or minimise.refusal(request.headers, body)
            ):
                raise SpeechError("neural_speech_invalid_request")
            if gw.operations.blocked("nvidia", "magpie-tts-multilingual", session.licence_id):
                raise SpeechError("neural_speech_unavailable")
            audio = await speech.synthesize(session.credential_id, body)
            return JSONResponse(
                {"audio_base64": base64.b64encode(audio).decode(), "voice": VOICES[body["voice_index"]]},
                headers={"Cache-Control": "no-store"},
            )
        except AuthError:
            return JSONResponse({"error": {"code": "auth"}}, status_code=401)
        except SpeechError as error:
            return JSONResponse(
                {"error": {"code": error.reason}}, status_code=503, headers={"Cache-Control": "no-store"}
            )

    return speech
