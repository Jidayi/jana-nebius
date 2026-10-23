"""Synthetic installed models for runtime tests (SEC-24, MDL-17 to MDL-19).

`install(data_dir)` writes small GGUF files with made-up 8B-class headers into `<data_dir>/models/` and a model
manifest for them signed with the test hierarchy's model key (trusted by development builds only). The files hold no
weights: they are headers padded to a size, enough for the hash check, the memory estimate and the launch plan, and
for a fake runtime to be pointed at. `python -m jana_tools.fakes.models <data_dir> [count]` does the same from a shell
test (`count` 1 installs only the larger model).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from agent_core.config.trust import Purpose
from agent_core.providers.gguf import write_header
from agent_core.store.model_packs import sign_manifest
from signing_service.keys import DEV_KEY_IDS, dev_key

MODEL_KEY_ID = DEV_KEY_IDS[Purpose.MODEL]  # model manifests are signed by a model key (SEC-12)

MB = 1024**2
# (model id, file size): the larger is the one a plan starts first, the smaller its single fallback (MDL-19).
SYNTHETIC = (("synthetic-large", 3 * MB), ("synthetic-small", 2 * MB))


def _header(path: Path, size: int) -> dict[str, Any]:
    write_header(
        path,
        {
            "general.architecture": "qwen3",
            "qwen3.context_length": 40960,
            "qwen3.block_count": 36,
            "qwen3.embedding_length": 4096,
            "qwen3.attention.head_count": 32,
            "qwen3.attention.head_count_kv": 8,
            "qwen3.attention.key_length": 128,
            "qwen3.attention.value_length": 128,
        },
        pad_to=size,
    )
    data = path.read_bytes()
    return {"name": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def install(data_dir: Path, models: tuple[tuple[str, int], ...] = SYNTHETIC) -> dict[str, Any]:
    folder = data_dir / "models"
    folder.mkdir(parents=True, exist_ok=True)
    entries = [{"model": model, "licence": "Apache-2.0", "file": _header(folder / f"{model}.gguf", size)}
               for model, size in models]  # fmt: skip
    manifest = sign_manifest({"pack_id": "models.synthetic", "version": "0.1.0", "synthetic": True,
                              "models": entries}, dev_key(Purpose.MODEL), MODEL_KEY_ID)  # fmt: skip
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1))
    return manifest


if __name__ == "__main__":
    install(Path(sys.argv[1]), SYNTHETIC[: int(sys.argv[2]) if len(sys.argv) > 2 else len(SYNTHETIC)])
