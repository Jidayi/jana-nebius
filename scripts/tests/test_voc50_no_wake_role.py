"""VOC-50, D126: the wake word is retired, so no speech pack the build produces declares the `wake` role or a non-null
`wake_path`: neither the development pack (apps/desktop/dev/speech_pack.py) nor the release build
(`jana_tools.release.speech_pack`). Synthetic model files only; signing is not run."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

from jana_tools.release import speech_pack as release

REPO = Path(__file__).resolve().parents[2]


def dev_builder():
    spec = importlib.util.spec_from_file_location(
        "dev_speech_pack", REPO / "apps" / "desktop" / "dev" / "speech_pack.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def dev_source(source: Path) -> None:
    """The smallest SOURCE folder the dev builder reads: every model file it copies, as placeholder bytes."""
    site = source / "venv/lib/python3.12/site-packages"
    models = source / "models"
    paths = [
        site / "silero_vad/data/silero_vad.jit",
        site / "g2p_en/checkpoint20.npz",
        models / "smart-turn-v3/smart-turn-v3.2-cpu.onnx",
        *(models / f"faster-whisper-{size}" / name for size in ("tiny.en", "small.en")
          for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")),
        *(models / "Kokoro-82M" / name for name in ("config.json", "kokoro-v1_0.pth", "voices/af_heart.pt")),
        source / "upstream/src/speech_to_speech/__init__.py",
        source / "nltk_data/tokenizers/punkt_tab/english/README",
    ]  # fmt: skip
    for path in paths:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"placeholder")


def voc50_no_wake_role(tmp_path, monkeypatch):
    builder = dev_builder()
    dev_source(tmp_path / "source")
    monkeypatch.setattr(subprocess, "run", lambda *args, **kwargs: None)  # no dev signing here
    pack = builder.main(tmp_path / "source", tmp_path / "out")
    manifest = json.loads((pack / "manifest.json").read_text())
    assert manifest["files"] and all(file["role"] != "wake" for file in manifest["files"])
    assert all(profile.get("wake_path") is None for profile in manifest["profiles"].values())
    assert not (pack / "models" / "kws").exists()

    assert all(profile.get("wake_path") is None for profile in release.profiles().values())
    assert '"wake"' not in Path(release.__file__).read_text()  # no release entry is given the `wake` role
