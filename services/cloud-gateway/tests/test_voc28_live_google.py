"""Opt-in live smoke checks of cloud voice's Google services (VOC-28, D124). Skipped unless credentials are present.

  JANA_LIVE_GEMINI=1                 Gemini Live reads a sentence: audio comes back and its transcription matches.
  JANA_VOICE_PROJECT=<project id>    With a project, Live runs on Vertex AI (the configured route) with application
                                     default credentials; without one, on the Gemini API with the key from the
                                     owner's secret source (keychain, secrets mount or JANA_DEV_GEMINI_API_KEY).
  JANA_LIVE_GOOGLE_VOICE=1           Cloud Text-to-Speech (Chirp 3 HD) reads a sentence, and Cloud Speech-to-Text v2
  JANA_VOICE_PROJECT=<project id>    (chirp_3) hears that audio back with voice-activity events. Needs the
                                     `google-voice` extra (`uv sync --all-packages --extra google-voice`), both APIs
                                     enabled on the project and application default credentials for an identity
                                     allowed to use them. Nothing here enables an API or creates a credential.

Only synthetic sentences are sent; nothing is stored."""

from __future__ import annotations

import asyncio
import os

import pytest
from cloud_gateway.config import GoogleVoice, load_config
from cloud_gateway.providers.gemini_live import GeminiLive
from cloud_gateway.voice import Reading
from test_m19_gw_live import _owner_secrets

SENTENCE = "Divide both sides by four, then check your answer."


@pytest.mark.skipif(os.environ.get("JANA_LIVE_GEMINI") != "1", reason="live Gemini Live test: set JANA_LIVE_GEMINI=1")
def test_live_reads_a_sentence_exactly() -> None:
    voice = load_config(None, environment="dev").voice_google
    project = os.environ.get("JANA_VOICE_PROJECT")
    if project:
        pytest.importorskip("google.auth")
        from cloud_gateway.providers.google_speech import google_stack

        config = load_config(None, environment="dev")
        config = config.model_copy(update={"voice_google": GoogleVoice(**{**voice.model_dump(), "project": project})})
        live = google_stack(config, {}).live  # type: ignore[arg-type]  # Vertex needs no secret
    else:
        key = _owner_secrets().get("gemini_api_key")
        if key is None:
            pytest.fail("JANA_LIVE_GEMINI=1 needs JANA_VOICE_PROJECT or a gemini_api_key (keychain, secrets mount or "
                        "JANA_DEV_GEMINI_API_KEY)")
        live = GeminiLive(api="gemini", model=voice.live_model, voice=voice.live_voice, key=key)

    async def scenario() -> tuple[bytes, Reading, float | None]:
        loop = asyncio.get_running_loop()
        session = await live.open()
        started, first = loop.time(), None
        reading, audio = Reading(SENTENCE), b""
        try:
            async for voiced in session.say(SENTENCE):
                if voiced.transcript:
                    reading.hear(voiced.transcript)
                if voiced.audio and first is None:
                    first = loop.time() - started
                audio += voiced.audio
                if voiced.done:
                    break
        finally:
            await session.close()
        return audio, reading, first

    audio, reading, first = asyncio.run(scenario())
    print(f"live first audio {first:.3f}s, {len(audio) / 48000:.2f}s of audio, departed={reading.departed}")
    assert len(audio) > 24_000 and len(audio) % 2 == 0
    # A departure is what the gateway guards against; the smoke test reports it rather than hiding it.
    assert reading.complete(), "Live departed from the sentence: the gateway would cut it and use Cloud TTS"


@pytest.mark.skipif(
    os.environ.get("JANA_LIVE_GOOGLE_VOICE") != "1" or not os.environ.get("JANA_VOICE_PROJECT"),
    reason="live Cloud Speech-to-Text and Text-to-Speech test: set JANA_LIVE_GOOGLE_VOICE=1 and JANA_VOICE_PROJECT",
)
def test_cloud_tts_then_streaming_recognition_round_trip() -> None:
    pytest.importorskip("google.cloud.speech_v2")
    pytest.importorskip("google.cloud.texttospeech")
    from cloud_gateway.providers.google_speech import ChirpRecognizer, ChirpSynthesizer

    defaults = load_config(None, environment="dev").voice_google
    voice = GoogleVoice(**{**defaults.model_dump(), "project": os.environ["JANA_VOICE_PROJECT"]})

    async def scenario() -> tuple[bytes, list[tuple[str, int, str]]]:
        tts = ChirpSynthesizer(voice)
        pcm = b"".join([chunk async for chunk in tts.synthesize(SENTENCE)])
        recognizer = ChirpRecognizer(voice)
        stream = await recognizer.open("en")
        heard: list[tuple[str, int, str]] = []

        async def read() -> None:
            async for event in stream.events():
                heard.append((event.kind, event.offset_ms, event.text))
                if event.kind == "final":
                    return

        reader = asyncio.create_task(read())
        audio = bytes(480) * 100 + pcm + bytes(48_000) * 2  # quiet, the sentence, two seconds of quiet
        for at in range(0, len(audio), 4800):
            await stream.send(audio[at : at + 4800])
            await asyncio.sleep(0.1)  # about real time: the service paces by audio sent
        await asyncio.wait_for(reader, 15)
        await stream.close()
        await tts.aclose()
        return pcm, heard

    pcm, heard = asyncio.run(scenario())
    kinds = [kind for kind, _, _ in heard]
    print("recognition events:", kinds)
    assert len(pcm) > 24_000
    assert "begin" in kinds and "final" in kinds
    final = next(text for kind, _, text in heard if kind == "final").casefold()
    assert "divide" in final and "four" in final.replace("4", "four")
