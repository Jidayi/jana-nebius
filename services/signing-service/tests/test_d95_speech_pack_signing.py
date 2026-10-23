"""D88, D95: the speech pack is signed by the Updater key only after it passes its own gate, then read back."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from agent_core.config import Environment
from agent_core.config.trust import Purpose
from agent_core.store.speech_packs import UPSTREAM_COMMIT, SpeechPackError, read_manifest
from signing_service.__main__ import main
from signing_service.hierarchy import SigningRefused, dev_signer, dev_trust, production_signer
from signing_service.speech import sign_speech_pack

FILES = [
    ("tts", "kokoro", "models/kokoro-82m/kokoro-v1_0.pth", "Apache-2.0"),
    ("sidecar", "speech-to-speech", "bin/jana-voice-kokoro", "Apache-2.0"),
    ("sidecar", "speech-to-speech", "runtime/kokoro-cpu/num2words/__init__.py", "LGPL-2.1-or-later"),
    ("sidecar", "speech-to-speech", "runtime/kokoro-cpu/num2words-0.5.14.dist-info/COPYING", "LGPL-2.1-or-later"),
]


def unsigned_pack(folder: Path) -> Path:
    files = []
    for role, engine, path, spdx in FILES:
        payload = ("synthetic " + path).encode()
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(payload)
        source = "https://pypi.org/project/num2words/0.5.14/" if "num2words" in path else "https://example.invalid/x"
        files.append(
            {
                "path": path,
                "role": role,
                "engine": engine,
                "classes": ["low", "mid"],
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "licence": {"spdx": spdx, "source_url": source, "attribution": "Synthetic component."},
            }
        )
    profile = {
        "stt": "none",
        "tts": "kokoro",
        "device": "cpu",
        "tts_path": "models/kokoro-82m",
        "sidecar_path": "bin/jana-voice-kokoro",
        "speaker": "af_heart",
    }
    manifest = {
        "speech_pack_id": "sp.en.1_0",
        "manifest_version": 1,
        "language": "en",
        "platform": "macos-aarch64",
        "upstream_commit": UPSTREAM_COMMIT,
        "min_app_version": "0.0.0",
        "created_at": "2026-10-16T00:00:00Z",
        "profiles": {"low": profile, "mid": profile},
        "files": files,
        "signature": {},
    }
    (folder / "manifest.json").write_text(json.dumps(manifest))
    return folder


def test_d95_speech_pack_signed_by_the_updater_key_after_its_gate(tmp_path):
    folder = unsigned_pack(tmp_path / "sp.en.1_0")
    signed = sign_speech_pack(
        folder, dev_signer(Purpose.UPDATER), dev_trust(), Environment.DEV, now="2026-10-16T12:00:00Z"
    )
    assert signed["signature"]["key_id"] == "key_dev_updater" and signed["created_at"] == "2026-10-16T12:00:00Z"
    assert read_manifest(folder, Environment.DEV, trust=dev_trust()).speech_pack_id == "sp.en.1_0"
    with pytest.raises(SpeechPackError):  # pilot and production builds refuse the test hierarchy
        read_manifest(folder, Environment.PRODUCTION, trust=dev_trust())


@pytest.mark.parametrize("change", ["byte", "unlisted", "gpl", "content_key"])
def test_d95_nothing_is_signed_when_the_pack_fails_its_gate(tmp_path, change):
    folder = unsigned_pack(tmp_path / "sp.en.1_0")
    signer = dev_signer(Purpose.UPDATER)
    if change == "byte":
        (folder / FILES[0][2]).write_bytes(b"tampered weights")
    elif change == "unlisted":
        (folder / "runtime" / "extra.py").write_text("unlisted")
    elif change == "gpl":
        document = json.loads((folder / "manifest.json").read_text())
        for file in document["files"]:
            if "num2words" in file["path"]:
                file["licence"]["spdx"] = "GPL-3.0-only"
        (folder / "manifest.json").write_text(json.dumps(document))
    else:
        signer = dev_signer(Purpose.CONTENT)
    before = (folder / "manifest.json").read_bytes()
    with pytest.raises(SigningRefused):
        sign_speech_pack(folder, signer, dev_trust(), Environment.DEV)
    assert (folder / "manifest.json").read_bytes() == before


def test_d95_production_signing_needs_the_ceremony_updater_key(tmp_path):
    with pytest.raises(SigningRefused, match=r"key ceremony|test root"):
        production_signer("key_rel_updater_missing", ["hsm-sign"])
    folder = unsigned_pack(tmp_path / "sp.en.1_0")
    assert main(["sign-speech-pack", str(folder), "--dev"]) == 0
    assert json.loads((folder / "manifest.json").read_text())["signature"]["alg"] == "ed25519"
