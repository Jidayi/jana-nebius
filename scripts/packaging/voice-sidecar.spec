# Optional speech-pack one-dir bundle (VOC-23), built in a dedicated locked speech environment.
# The core environment never gains torch/STT/TTS dependencies. Models, NLTK resources and licence records are
# separate signed pack files; nothing is downloaded by this recipe or at runtime.
# ruff: noqa
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parents[1]
CORE = ROOT / "services" / "agent-core"
datas = collect_data_files("agent_core", includes=["**/*.json"])
datas += collect_data_files("speech_to_speech", includes=["**/*.json", "**/*.yaml", "**/*.txt"])
hidden = ["speech_to_speech.s2s_pipeline", "speech_to_speech.configured_runtime",
          "speech_to_speech.backend_registry", "speech_to_speech.api.openai_realtime.websocket_router",
          "speech_to_speech.STT.faster_whisper_handler", "speech_to_speech.STT.parakeet_tdt_handler",
          "speech_to_speech.TTS.qwen3_tts_handler", "speech_to_speech.LLM.chat_completions_language_model",
          "speech_to_speech.VAD.vad_handler", "uvicorn", "websockets.asyncio.client"]
a = Analysis([str(CORE / "agent_core" / "net" / "voice_sidecar.py")], pathex=[str(CORE)], datas=datas,
             hiddenimports=hidden, excludes=["espeakng_loader", "phonemizer", "espeakng", "tkinter", "IPython", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="jana-voice", console=True, strip=False, upx=False)
COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="jana-voice")
