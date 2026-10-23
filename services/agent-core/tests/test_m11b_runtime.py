"""M11.b: verified model files and no silent context shift (SEC-24, MDL-21). Model files here are small synthetic
stand-ins; the hashes are of their bytes."""

from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest
from agent_core.config.environments import Environment
from agent_core.config.trust import Purpose
from agent_core.providers.base import Message, ProviderError
from agent_core.providers.llama import LlamaServerProvider
from agent_core.router.fit import launch_arguments
from agent_core.store.model_packs import ModelManifestError, prepare_runtime_models, sign_manifest, verify_manifest
from jana_tools.fakes import FakeLlamaServer
from signing_service.keys import DEV_KEY_IDS, dev_key

MODEL_KEY_ID = DEV_KEY_IDS[Purpose.MODEL]  # model manifests are signed by a model key (SEC-12)


def _file(folder: Path, name: str, content: bytes) -> dict:
    (folder / name).write_bytes(content)
    return {"name": name, "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}


def _manifest(installed: Path, licence: str = "Apache-2.0") -> dict:
    installed.mkdir(parents=True, exist_ok=True)
    models = [
        {"model": "qwen3-vl-8b", "licence": licence, "file": _file(installed, "qwen.gguf", b"GGUF synthetic qwen"),
         "projector": _file(installed, "mmproj-qwen.gguf", b"GGUF synthetic projector")},
        {"model": "gemma-4-12b", "licence": "Apache-2.0",
         "file": _file(installed, "gemma.gguf", b"GGUF synthetic gemma")},
    ]  # fmt: skip
    return {"pack_id": "models.dev", "version": "0.1.0", "synthetic": True, "models": models}


def sec24_runtime_loads_only_verified_models(tmp_path: Path) -> None:
    installed = tmp_path / "installed"
    signed = sign_manifest(_manifest(installed), dev_key(Purpose.MODEL), MODEL_KEY_ID)
    (installed / "stray.gguf").write_bytes(b"GGUF dropped in by hand")
    (installed / "gemma.gguf").write_bytes(b"GGUF synthetic gemmA")  # same size, changed bytes
    runtime = tmp_path / "runtime-models"
    prepared = prepare_runtime_models(signed, installed, runtime, tmp_path / "hashes.json", Environment.DEV)
    # Only the verified model reaches the runtime's folder, with its projector; the others are refused with why.
    assert prepared.models == ["qwen3-vl-8b"]
    assert sorted(p.name for p in runtime.iterdir()) == ["qwen3-vl-8b"]
    assert sorted(p.name for p in (runtime / "qwen3-vl-8b").iterdir()) == ["mmproj-qwen.gguf", "qwen.gguf"]
    assert dict(prepared.refused) == {"gemma.gguf": "the file does not match its recorded hash",
                                      "stray.gguf": "not listed in a verified model manifest"}  # fmt: skip
    # The runtime is pointed at that folder, never at the install folder.
    args = launch_arguments(str(runtime), 8192, 18080, str(tmp_path / "key"), slots=1)
    assert args[args.index("--models-dir") + 1] == str(runtime)
    # A manifest changed after signing, or signed under the test root in a production build, loads nothing.
    tampered = json.loads(json.dumps(signed))
    tampered["models"][1]["file"]["sha256"] = hashlib.sha256(b"GGUF synthetic gemmA").hexdigest()
    with pytest.raises(ModelManifestError):
        prepare_runtime_models(tampered, installed, runtime, tmp_path / "hashes.json", Environment.DEV)
    with pytest.raises(ModelManifestError):
        verify_manifest(signed, Environment.PRODUCTION)


def sec24_model_licence_on_approved_list(tmp_path: Path) -> None:
    for licence in ("Gemma Terms of Use", "CC-BY-NC-4.0", "GPL-3.0", None):
        with pytest.raises(ModelManifestError, match="not on LIST SEC-24a"):
            sign_manifest(_manifest(tmp_path / str(licence), licence), dev_key(Purpose.MODEL), MODEL_KEY_ID)  # type: ignore[arg-type]
    attribution = _manifest(tmp_path / "ccby", "CC-BY-4.0")
    with pytest.raises(ModelManifestError, match="attribution"):
        sign_manifest(attribution, dev_key(Purpose.MODEL), MODEL_KEY_ID)
    attribution["models"][0]["attribution"] = "Synthetic model by Example Lab, CC BY 4.0"
    assert sign_manifest(attribution, dev_key(Purpose.MODEL), MODEL_KEY_ID)["signature"]["key_id"] == MODEL_KEY_ID


def mdl21_no_silent_shift(tmp_path: Path) -> None:
    # The runtime is launched with context shift off, so it refuses an over-long prompt instead of dropping its start.
    args = launch_arguments(str(tmp_path), 8192, 18080, str(tmp_path / "key"), slots=1)
    assert "--no-context-shift" in args and "--context-shift" not in args
    # Its refusal (as llama.cpp words it) is classified as context_overflow, which the engine compacts (MEM-15).
    refusal = {
        "code": 400,
        "message": "request (40016 tokens) exceeds the available context size (8192 tokens), try increasing it",
        "type": "exceed_context_size_error",
        "n_prompt_tokens": 40016,
        "n_ctx": 8192,
    }

    async def scenario() -> str:
        async with FakeLlamaServer(["qwen3-vl-8b"], script=lambda body: {"status": 400, "body": {"error": refusal}}
                                   ) as server:  # fmt: skip
            provider = LlamaServerProvider(server.url, server.api_key)
            try:
                await provider.complete("qwen3-vl-8b", [Message("user", "word " * 40000)], [])
            except ProviderError as error:
                return error.reason
            finally:
                await provider.close()
        return "replied"

    assert asyncio.run(scenario()) == "context_overflow"


def test_d123_roles_keep_their_own_llama_slot():
    """The Coach, Solver and Diagnoser each keep a slot (their long prompts stay cached); the rest share the last one,
    and with too few slots nothing is pinned (MDL-22, D123)."""
    from agent_core.providers.llama import LlamaServerProvider, role_slot
    from agent_core.providers.openai_compat import Message

    assert [role_slot(r, 4) for r in ("coach", "solver", "diagnoser", "input_guard", "title")] == [0, 1, 2, 3, 3]
    assert role_slot("coach", 3) is None and role_slot("coach", 0) is None
    provider = LlamaServerProvider("http://127.0.0.1:1", "k")
    provider._slots["m"] = 4
    body, _ = provider._body("m", [Message("user", "hi")], [], {"role": "solver"}, stream=False)
    assert body["id_slot"] == 1 and body["cache_prompt"] is True
    provider._slots["m"] = 1
    body, _ = provider._body("m", [Message("user", "hi")], [], {"role": "solver"}, stream=False)
    assert "id_slot" not in body
