"""Launcher security with no speech-library import or model downloads."""

import asyncio
import json
import os
import subprocess
import sys
from types import SimpleNamespace

import pytest
from agent_core.net.voice_sidecar import (
    RealtimeGuard,
    SidecarLaunch,
    allow_connection,
    argument_values,
    engine_tools_only,
    local_nltk,
)
from agent_core.store.speech_packs import SpeechPackError, SpeechProfile

TOKEN = "synthetic_" + "a" * 32


def launch(**extra):
    return SidecarLaunch.model_validate(
        {
            "protocol": 1,
            "pack_dir": "/synthetic/pack",
            "hardware": "mid",
            "platform": "linux-x86_64",
            "app_version": "0.0.0",
            "environment": "dev",
            "adapter_url": "http://127.0.0.1:1234/v1/voice/llm",
            "adapter_token": TOKEN,
            "realtime_token": "synthetic_" + "b" * 32,
            **extra,
        }
    )


@pytest.mark.parametrize(
    "credential", [None, "wrong", "previous_" + "z" * 32, "\u00e9" * 32, "valid", "subprotocol", "duplicate", "both"]
)
def voc23_realtime_token_required(credential):
    async def scenario():
        claimed, output = [], []

        async def upstream(scope, receive, send):
            claimed.append(scope)
            await send({"type": "websocket.accept"})

        headers, protocols = [], []
        if credential == "subprotocol":
            protocols = ["openai-insecure-api-key." + TOKEN]
        elif credential in ("valid", "duplicate", "both"):
            headers = [(b"authorization", ("Bearer " + TOKEN).encode())]
            if credential == "duplicate":
                headers *= 2
            if credential == "both":
                protocols = ["openai-insecure-api-key." + TOKEN]
        elif credential is not None:
            protocols = ["openai-insecure-api-key." + credential]
        scope = {"type": "websocket", "path": "/v1/realtime", "headers": headers, "subprotocols": protocols}

        async def send(message):
            output.append(message)

        await RealtimeGuard(upstream, TOKEN)(scope, None, send)
        assert bool(claimed) == (credential in ("valid", "subprotocol"))
        if claimed:
            assert not claimed[0]["headers"] and not claimed[0]["subprotocols"]
        else:
            assert output == [{"type": "websocket.close", "code": 4401}]
        assert TOKEN not in json.dumps(output)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "path", ["/v1/usage", "/v1/pool", "/v1/realtime/calls", "/v1/chat/completions", "/v1/realtime"]
)
def test_other_routes_answer_404(path):
    async def scenario():
        async def forbidden(*args):
            raise AssertionError("HTTP must never reach upstream")

        output = []

        async def send(message):
            output.append(message)

        await RealtimeGuard(forbidden, TOKEN)({"type": "http", "path": path}, None, send)
        assert output[0]["status"] == 404

    asyncio.run(scenario())


def test_fixed_arguments_have_local_paths_no_cloning_and_no_sidecar_reasoning():
    config = launch()
    profile = SpeechProfile.model_validate(
        {
            "stt": "faster-whisper",
            "tts": "qwen3",
            "device": "cpu",
            "vad_path": "vad",
            "turn_path": "turn/model.onnx",
            "stt_path": "stt",
            "tts_path": "tts",
            "sidecar_path": "sidecar/jana-voice",
            "speaker": "Aiden",
        }
    )
    values = argument_values(config, profile)
    assert values["module"]["num_pipelines"] == 1 and not values["module"]["enable_llm_proxy"]
    assert values["llm"]["responses_api_reasoning_effort"] == "none"
    assert values["llm"]["compact_history"] is False and values["llm"]["stream_batch_sentences"] == 1
    assert values["vad"]["speculative_reopen_ms"] == 1500
    assert values["stt"]["faster_whisper_stt_model_name"] == "/synthetic/pack/stt"
    assert values["tts"]["qwen3_tts_ref_audio"] is None and values["tts"]["qwen3_tts_ref_spk"] is None
    assert TOKEN not in repr(config)
    # D95: Kokoro loads from the pack's files on the CPU; Pocket and a Kokoro on another device stay closed.
    kokoro = argument_values(config, profile.model_copy(update={"tts": "kokoro", "speaker": "af_heart"}))["tts"]
    assert kokoro == {
        "kokoro_model_name": "/synthetic/pack/tts",
        "kokoro_device": "cpu",
        "kokoro_voice": "/synthetic/pack/tts/voices/af_heart.pt",
        "kokoro_lang_code": "a",
        "kokoro_speed": 1.0,
    }
    for change in ({"tts": "pocket"}, {"tts": "kokoro", "device": "mps"}):
        with pytest.raises(SpeechPackError, match="local_tts_loader_unavailable"):
            argument_values(config, profile.model_copy(update=change))


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1/voice/llm",
        "http://localhost:10/v1/voice/llm",
        "http://127.0.0.1/v1/voice/llm",
        "http://127.0.0.1:1/v1/voice/llm?token=bad",
        "http://user:secret@127.0.0.1:1/v1/voice/llm",
    ],
)
def test_adapter_url_is_literal_loopback_only(url):
    with pytest.raises(SpeechPackError):
        launch(adapter_url=url).adapter_base()


def test_external_network_is_refused_even_when_a_dependency_ignores_offline_flag():
    assert allow_connection(("127.0.0.1", 1234)) and allow_connection(("::1", 1234))
    assert not any(allow_connection(a) for a in [("8.8.8.8", 443), "huggingface.co", "/synthetic/socket", None])
    # The hook is process-wide and permanent; test it in its actual separate process, never in the pytest runner.
    code = """
import os, socket
from agent_core.net.voice_sidecar import offline_process
offline_process()
assert os.environ['HF_HUB_OFFLINE'] == '1'
assert 'HTTPS_PROXY' not in os.environ
for action in (lambda: socket.getaddrinfo('huggingface.co', 443),
               lambda: socket.socket().connect(('8.8.8.8', 443))):
    try: action()
    except OSError: pass
    else: raise AssertionError('external access was permitted')
print('offline')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        env={**os.environ, "HTTPS_PROXY": "http://example.invalid"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0 and result.stdout.strip() == "offline", result.stderr


def test_upstream_tool_default_is_removed_but_tools_cannot_escape_to_the_sidecar(monkeypatch):
    class Handler:
        pass

    monkeypatch.setattr(
        "agent_core.net.voice_sidecar.importlib.import_module",
        lambda name: SimpleNamespace(ChatCompletionsApiModelHandler=Handler),
    )
    engine_tools_only()
    handler = Handler()
    assert handler._build_optional_kwargs([], "auto") == {}
    for tools, choice in [([{"type": "function"}], "auto"), ([], "required"), ([], {"name": "x"})]:
        with pytest.raises(SpeechPackError, match="voice_sidecar_tools_refused"):
            handler._build_optional_kwargs(tools, choice)


def test_nltk_uses_only_bundled_resources_and_refuses_downloads(tmp_path, monkeypatch):
    found = []
    fake = SimpleNamespace(data=SimpleNamespace(path=[], find=found.append), download=None)
    monkeypatch.setattr("agent_core.net.voice_sidecar.importlib.import_module", lambda name: fake)
    monkeypatch.setenv("NLTK_DATA", "unused")
    local_nltk(tmp_path)
    assert fake.data.path == [str(tmp_path)]
    assert found == ["tokenizers/punkt_tab", "taggers/averaged_perceptron_tagger_eng"]
    with pytest.raises(SpeechPackError, match="voice_runtime_download_refused"):
        fake.download("punkt_tab")
