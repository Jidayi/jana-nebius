"""Development only: assemble and development-sign an English conversation speech pack from local downloads, so the
offline voice pipeline runs for real in `npm run dev` (VOC-03a, D95) without a release bundle.

Usage: uv run python apps/desktop/dev/speech_pack.py SOURCE OUT
SOURCE holds the dev voice downloads: `venv/` (Python 3.12 with the pinned upstream installed from
`upstream/` and the Kokoro, faster-whisper and Silero runtimes), `nltk_data/` and `models/` with
faster-whisper-small.en, faster-whisper-tiny.en, smart-turn-v3 and Kokoro-82M. The pack ships no wake-word detector
(D126 retired VOC-49): no file has the `wake` role and every profile's `wake_path` is null (VOC-50). OUT is a
speech-packs folder: the pack lands in OUT/sp.en.0_1 and is installed into a dev data folder by copying it to
<data>/speech-packs/ before the app starts (with `JANA_DEV_HARDWARE=mid` so the core offers conversation).

The pack's entry point runs the shared venv's interpreter with the repository's agent core on its path; only the
upstream pipeline must sit inside the pack (the sidecar refuses one from elsewhere). Upstream's Facebook MMS TTS
arguments module is excluded from every pack (TABLE VOC-02a) but imported unconditionally by its backend registry,
so the launcher puts an empty stand-in in its place. Classes: low runs tiny.en without Smart Turn; mid and high run
small.en with Smart Turn. Every profile is Kokoro on the CPU (the only local loader on Apple silicon besides Qwen3).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PACK_ID = "sp.en.0_1"
UPSTREAM_COMMIT = "619e3fe4f71d1c6f35c15870d588a3638de34722"
SPEAKER = "af_heart"
ALL = ["low", "mid", "high"]

LAUNCH = '''"""Dev speech pack entry point: stand in for the excluded MMS module, then run the core's voice sidecar."""
import dataclasses
import sys
import types

name = "speech_to_speech.arguments_classes.facebookmms_tts_arguments"
stub = types.ModuleType(name)


@dataclasses.dataclass
class FacebookMMSTTSHandlerArguments:
    pass


stub.FacebookMMSTTSHandlerArguments = FacebookMMSTTSHandlerArguments
sys.modules[name] = stub

import os  # noqa: E402
import traceback  # noqa: E402

from agent_core.net import voice_sidecar  # noqa: E402

served = voice_sidecar.serve


async def serve(*args, **kwargs):
    """The sidecar reports only a fixed code; in development keep the traceback (JANA_DEV_VOICE_LOG) to debug it."""
    try:
        return await served(*args, **kwargs)
    except BaseException:
        if os.environ.get("JANA_DEV_VOICE_LOG"):
            with open(os.environ["JANA_DEV_VOICE_LOG"], "a") as log:
                log.write(traceback.format_exc())
        raise


voice_sidecar.serve = serve
voice_sidecar.main()
'''

ENTRY = """#!/bin/sh
# Dev speech pack entry point (apps/desktop/dev/speech_pack.py): the shell clears the environment, so set it here.
pack="$(cd "$(dirname "$0")/.." && pwd)"
JANA_DEV_VOICE_LOG="$HOME/.cache/jana-speech/sidecar-errors.log" PYTHONPATH="$pack/runtime/upstream:{agent_core}" \\
  PYTHONDONTWRITEBYTECODE=1 exec "{python}" -B "$pack/runtime/dev_launch.py"
"""


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def main(source: Path, out: Path) -> Path:
    models = source / "models"
    pack = out / PACK_ID
    if pack.exists():
        shutil.rmtree(pack)
    files: list[dict[str, object]] = []

    def put(src: Path, rel: str, role: str, engine: str, classes: list[str], spdx: str, url: str, who: str) -> None:
        dest = pack / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        files.append({
            "path": rel, "role": role, "engine": engine, "classes": classes, "size_bytes": dest.stat().st_size,
            "sha256": sha256(dest), "licence": {"spdx": spdx, "source_url": url, "attribution": who},
        })  # fmt: skip

    silero = source / "venv/lib/python3.12/site-packages/silero_vad/data/silero_vad.jit"
    put(silero, "models/silero/silero_vad.jit", "vad", "silero", ALL, "MIT",
        "https://github.com/snakers4/silero-vad", "Silero VAD, Silero Team")  # fmt: skip
    put(models / "smart-turn-v3/smart-turn-v3.2-cpu.onnx", "models/smart-turn/smart-turn-v3.2-cpu.onnx", "turn",
        "smart-turn", ["mid", "high"], "BSD-2-Clause", "https://huggingface.co/pipecat-ai/smart-turn-v3",
        "Smart Turn v3, Daily")  # fmt: skip
    for size, classes in (("tiny.en", ["low"]), ("small.en", ["mid", "high"])):
        for name in ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt"):
            put(models / f"faster-whisper-{size}" / name, f"models/faster-whisper-{size}/{name}", "stt",
                "faster-whisper", classes, "MIT", f"https://huggingface.co/Systran/faster-whisper-{size}",
                "Whisper, OpenAI; CTranslate2 conversion, Systran")  # fmt: skip
    for name in ("config.json", "kokoro-v1_0.pth", f"voices/{SPEAKER}.pt"):
        put(models / "Kokoro-82M" / name, f"models/kokoro-82m/{name}", "tts", "kokoro", ALL, "Apache-2.0",
            "https://huggingface.co/hexgrad/Kokoro-82M", "Kokoro-82M, hexgrad")  # fmt: skip

    g2p = next((source / "venv/lib/python3.12/site-packages/g2p_en").glob("checkpoint*.npz"))
    put(g2p, "models/kokoro-82m/g2p/checkpoint20.npz", "tts", "kokoro", ALL, "Apache-2.0",
        "https://github.com/Kyubyong/g2p", "g2p_en, Kyubyong Park and Jongseok Kim")  # fmt: skip

    runtime = {"role": "sidecar", "engine": "speech-to-speech", "classes": ALL}
    upstream = source / "upstream/src/speech_to_speech"
    for src in sorted(upstream.rglob("*")):
        if not src.is_file() or "__pycache__" in src.parts or src.name == "facebookmms_tts_arguments.py":
            continue
        put(src, f"runtime/upstream/speech_to_speech/{src.relative_to(upstream).as_posix()}", **runtime,
            spdx="Apache-2.0", url="https://github.com/huggingface/speech-to-speech",
            who="speech-to-speech, Hugging Face")  # fmt: skip
    for src in sorted((source / "nltk_data").rglob("*")):
        if src.is_file() and src.suffix != ".zip":
            put(src, f"bin/nltk_data/{src.relative_to(source / 'nltk_data').as_posix()}", **runtime, spdx="Apache-2.0",
                url="https://github.com/nltk/nltk_data", who="NLTK Data, NLTK Project")  # fmt: skip
    scratch = pack / ".build"
    scratch.mkdir()
    (scratch / "dev_launch.py").write_text(LAUNCH)
    put(scratch / "dev_launch.py", "runtime/dev_launch.py", **runtime, spdx="MIT",
        url="https://github.com/ruhu-ai/jana", who="Jana")  # fmt: skip
    entry = ENTRY.format(agent_core=REPO / "services" / "agent-core", python=source / "venv" / "bin" / "python")
    (scratch / "jana-voice").write_text(entry)
    put(scratch / "jana-voice", "bin/jana-voice", **runtime, spdx="MIT", url="https://github.com/ruhu-ai/jana",
        who="Jana")  # fmt: skip
    (pack / "bin" / "jana-voice").chmod(0o755)
    shutil.rmtree(scratch)

    def profile(stt: str, turn: str | None) -> dict[str, object]:
        return {"stt": "faster-whisper", "tts": "kokoro", "device": "cpu", "vad_path": "models/silero",
                "turn_path": turn, "stt_path": stt, "wake_path": None, "tts_path": "models/kokoro-82m",
                "sidecar_path": "bin/jana-voice", "speaker": SPEAKER}  # fmt: skip

    turn = "models/smart-turn/smart-turn-v3.2-cpu.onnx"
    manifest = {
        "speech_pack_id": PACK_ID, "manifest_version": 1, "language": "en", "platform": "macos-aarch64",
        "upstream_commit": UPSTREAM_COMMIT, "min_app_version": "0.0.0", "created_at": "2026-10-20T00:00:00.000Z",
        "profiles": {
            "low": profile("models/faster-whisper-tiny.en", None),
            "mid": profile("models/faster-whisper-small.en", turn),
            "high": profile("models/faster-whisper-small.en", turn),
        },
        "files": files, "signature": {},
    }  # fmt: skip
    (pack / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    subprocess.run(
        ["uv", "run", "--quiet", "python", "-m", "signing_service", "sign-speech-pack", str(pack), "--dev"],
        cwd=REPO / "services" / "signing-service", check=True,
    )  # fmt: skip
    return pack


if __name__ == "__main__":
    print(main(Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()))
