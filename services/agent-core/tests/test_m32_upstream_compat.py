"""Pin/layout/request-shape compatibility, without importing a speech model or fetching dependencies.

Pack builds must set JANA_SPEECH_SOURCE to their pristine local upstream checkout. Real-model/wire/audio
compatibility is a separate release gate; these tests deliberately cannot certify it.
"""

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from agent_core.contracts import errors
from agent_core.net.voice_sidecar import argument_values
from agent_core.store.speech_packs import UPSTREAM_COMMIT, SpeechProfile
from jana_tools import REPO_ROOT
from test_m32_sidecar_launcher import launch

SOURCE = Path(os.environ["JANA_SPEECH_SOURCE"]) if "JANA_SPEECH_SOURCE" in os.environ else None
pytestmark = pytest.mark.skipif(SOURCE is None, reason="pack build must provide its pinned local JANA_SPEECH_SOURCE")


def tree(relative):
    return ast.parse((SOURCE / "src/speech_to_speech" / relative).read_text())


def test_upstream_checkout_is_pinned_pristine_and_matches_recorded_hashes():
    pin = json.loads((REPO_ROOT / "scripts/packaging/voice-upstream.json").read_text())
    result = subprocess.run(["git", "-C", str(SOURCE), "rev-parse", "HEAD"], capture_output=True, text=True, check=True)
    assert result.stdout.strip() == pin["commit"] == UPSTREAM_COMMIT
    result = subprocess.run(
        ["git", "-C", str(SOURCE), "status", "--porcelain", "--", "src"], capture_output=True, text=True, check=True
    )
    assert not result.stdout
    for name, digest in pin["files"].items():
        assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == digest, name


@pytest.mark.parametrize("stt", ["faster-whisper", "parakeet-tdt"])
def voc45_upstream_compat(stt):
    classes = {}
    for path in (SOURCE / "src/speech_to_speech/arguments_classes").glob("*.py"):
        for node in ast.parse(path.read_text()).body:
            if isinstance(node, ast.ClassDef):
                classes[node.name] = node

    def fields(name):
        node = classes[name]
        inherited = set().union(
            *(fields(base.id) for base in node.bases if isinstance(base, ast.Name) and base.id in classes)
        )
        return inherited | {
            child.target.id
            for child in node.body
            if isinstance(child, ast.AnnAssign) and isinstance(child.target, ast.Name)
        }

    profile = SpeechProfile.model_validate(
        {
            "stt": stt,
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
    values = argument_values(launch(), profile)
    names = {
        "module": "ModuleArguments",
        "vad": "VADHandlerArguments",
        "tts": "Qwen3TTSHandlerArguments",
        "llm": "ChatCompletionsLanguageModelHandlerArguments",
        "stt": "FasterWhisperSTTHandlerArguments" if stt == "faster-whisper" else "ParakeetTDTSTTHandlerArguments",
    }
    for section, name in names.items():
        assert set(values[section]) <= fields(name), (section, set(values[section]) - fields(name))


def test_runtime_hooks_and_packaging_import_names_match_the_pin():
    classes = [node for node in tree("LLM/chat_completions_language_model.py").body if isinstance(node, ast.ClassDef)]
    handler = next(node for node in classes if node.name == "ChatCompletionsApiModelHandler")
    assert any(isinstance(node, ast.FunctionDef) and node.name == "_build_optional_kwargs" for node in handler.body)
    assert any(
        isinstance(node, ast.FunctionDef) and node.name == "_build_runtime"
        for node in tree("configured_runtime.py").body
    )
    recipe = ast.parse((REPO_ROOT / "scripts/packaging/voice-sidecar.spec").read_text())
    modules = next(
        ast.literal_eval(node.value)
        for node in recipe.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "hidden" for target in node.targets)
    )
    for module in modules:
        if module.startswith("speech_to_speech."):
            assert (SOURCE / "src" / (module.replace(".", "/") + ".py")).is_file(), module


def test_pinned_upstream_chat_request_serializes_to_the_adapter_contract():
    # Execute the actual small request-building function in isolation: no SDK, model, network, or fabricated copy.
    pin = json.loads((REPO_ROOT / "scripts/packaging/voice-upstream.json").read_text())
    name = "src/speech_to_speech/LLM/chat_completions_language_model.py"
    assert hashlib.sha256((SOURCE / name).read_bytes()).hexdigest() == pin["files"][name]
    function = next(
        node
        for node in tree("LLM/chat_completions_language_model.py").body
        if isinstance(node, ast.FunctionDef) and node.name == "_request_chat_completions"
    )
    module = ast.Module(
        body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function],
        type_ignores=[],
    )
    namespace = {}
    exec(compile(ast.fix_missing_locations(module), "pinned_request_builder", "exec"), namespace)  # noqa: S102 -- hash-verified pure request builder; fake client only
    calls = []
    completions = SimpleNamespace(create=lambda **body: calls.append(body))
    client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    namespace["_request_chat_completions"](
        client=client,
        model_name="jana-tutor-voice",
        messages=[
            {"role": "system", "content": "jana-voice-binding: vb_" + "0" * 26 + "\n\njana-voice-unbound"},
            {"role": "user", "content": "Could you explain that?"},
        ],
        stream=True,
        extra_body={"reasoning_effort": "none"},
        timeout=20,
        optional_kwargs={},
    )
    request = calls[0]
    request.pop("timeout")
    request.update(request.pop("extra_body"))  # the SDK merges extra_body into its outgoing JSON body
    assert errors("voice/engine-llm-adapter#/$defs/request", request) == []
