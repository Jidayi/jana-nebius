"""ARC-19 client bundle scan: no client package may contain a model SDK, a model provider
host or a model runtime port. Scans sources, built bundles and declared dependencies."""

from __future__ import annotations

import json
import re
from pathlib import Path

CLIENT_ROOTS = (
    "packages/ui", "packages/client-core", "packages/renderers", "packages/contracts-ts", "packages/i18n",
    "apps/desktop/src", "apps/web", "apps/android", "apps/studio/src",
)  # fmt: skip
MODEL_SDKS = (
    "openai", "@anthropic-ai/sdk", "ollama", "@google/generative-ai", "@google/genai", "@mistralai/mistralai",
    "groq-sdk", "cohere-ai", "@huggingface/inference", "langchain", "@langchain/core", "llamaindex", "ai",
    "@ai-sdk/openai", "node-llama-cpp",
)  # fmt: skip
PROVIDER_HOSTS = (
    "api.openai.com", "openai.azure.com", "api.anthropic.com", "generativelanguage.googleapis.com",
    "aiplatform.googleapis.com", "api.mistral.ai", "api.groq.com", "api.cohere.ai", "api.cohere.com",
    "api-inference.huggingface.co", "router.huggingface.co", "openrouter.ai", "api.together.xyz",
    "api.deepseek.com", "bedrock-runtime", "api.x.ai", "api.fireworks.ai",
)  # fmt: skip
SCANNED_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".json", ".html", ".css", ".map"}

_SDK = "|".join(re.escape(s) for s in MODEL_SDKS)
_IMPORT = re.compile(rf"""(?:from\s*|import\s*\(?\s*|require\s*\(\s*)["']({_SDK})(?:/[^"']*)?["']""")
_HOST = re.compile("|".join(re.escape(h) for h in PROVIDER_HOSTS))
# The core origin is injected at launch; any hard-coded loopback port, or a well-known model
# runtime port or path, means the client is reaching for a runtime directly.
_RUNTIME = re.compile(
    r"(?:localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0):\d{2,5}|\b11434\b|/v1/chat/completions|/v1/completions\b|/api/generate\b"
)


def _files(root: Path) -> list[Path]:
    out = []
    for base in CLIENT_ROOTS:
        for path in sorted((root / base).rglob("*")) if (root / base).exists() else []:
            if path.is_file() and path.suffix in SCANNED_SUFFIXES and "node_modules" not in path.parts:
                out.append(path)
    return out


def bundle_scan_errors(root: Path) -> list[str]:
    errors = []
    for path in _files(root):
        rel = path.relative_to(root)
        text = path.read_text(errors="replace")
        if path.name == "package.json":
            data = json.loads(text)
            for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
                for dep in data.get(field, {}):
                    if dep in MODEL_SDKS:
                        errors.append(f"{rel}: depends on model SDK {dep}")
            continue
        for no, line in enumerate(text.splitlines(), 1):
            for match in _IMPORT.finditer(line):
                errors.append(f"{rel}:{no}: imports model SDK {match[1]}")
            for match in _HOST.finditer(line):
                errors.append(f"{rel}:{no}: names model provider host {match[0]}")
            for match in _RUNTIME.finditer(line):
                errors.append(f"{rel}:{no}: names a model runtime address {match[0]}")
    return sorted(errors)


# VOC-01, ARC-02, SEC-11: the UI talks only to the core origin, during voice as at any other time. Network primitives
# may appear only where the core's injected origin (or the page's own origin) is their target; the webview's own
# speech recognition streams audio to a vendor's servers, so it never appears; the OS synthesiser takes only voices
# installed on the device; and the client names no speech endpoint of the sidecar or a cloud speech service.
NETWORK_ALLOWED = {
    "packages/client-core/src/voice.ts": "voice socket to the core origin; refuses any non-loopback endpoint",
    "packages/client-core/src/stream/client.ts": "event stream from the core origin (API-01)",
    "packages/client-core/src/stream/commands.ts": "commands to the core origin (API-01)",
    "apps/desktop/src/launch.ts": "the page's own origin (development launch file)",
    "apps/studio/src/transport.ts": "the studio page's own origin or its shell",
}
SPEECH_HOSTS = (
    "speech.googleapis.com", "texttospeech.googleapis.com", "speech.microsoft.com", "cognitiveservices.azure.com",
    "polly.", "transcribe.", "api.elevenlabs.io", "api.deepgram.com", "api.assemblyai.com", "api.openai.com/v1/audio",
    "api.cartesia.ai", "api.play.ht", "api.rev.ai", "api.speechmatics.com",
)  # fmt: skip
_NETWORK = re.compile(
    r"\bnew\s+WebSocket\b|\bglobalThis\.fetch\b|(?<![\w.])fetch\s*\(|\bnew\s+EventSource\b|\bXMLHttpRequest\b"
    r"|\bsendBeacon\b|\bRTCPeerConnection\b|\bWebTransport\b"
)
_RECOGNITION = re.compile(r"\b(?:webkit)?SpeechRecognition\b")
_SPEECH_ENDPOINT = re.compile(r"/v1/realtime\b|/v1/voice/llm\b|" + "|".join(re.escape(h) for h in SPEECH_HOSTS))
CONNECT_SOURCES = {"'self'", "http://127.0.0.1:*", "ws://127.0.0.1:*"}
_SOURCE_SUFFIXES = {".ts", ".tsx", ".js", ".jsx", ".mjs"}


def _source_files(root: Path) -> list[Path]:
    """Shipped client sources: the `src` trees of the client roots, without tests."""
    return [
        path
        for path in _files(root)
        if path.suffix in _SOURCE_SUFFIXES
        and "/src/" in "/" + path.relative_to(root).as_posix()
        and ".test." not in path.name
    ]


def client_network_errors(root: Path) -> list[str]:
    errors = []
    for path in _source_files(root):
        rel = path.relative_to(root).as_posix()
        text = path.read_text(errors="replace")
        for no, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(("//", "*", "/*")):
                continue
            for match in _NETWORK.finditer(line):
                if rel not in NETWORK_ALLOWED:
                    found = match[0].strip()
                    errors.append(f"{rel}:{no}: opens a network connection ({found}) outside the core client")
            for match in _RECOGNITION.finditer(line):
                errors.append(f"{rel}:{no}: uses the webview's speech recognition ({match[0]}), off the device")
            # Generated contract bindings carry the schemas of every endpoint as data; they open no connection.
            for match in _SPEECH_ENDPOINT.finditer("" if "/generated/" in rel else line):
                errors.append(f"{rel}:{no}: names a speech endpoint ({match[0]}); speech goes through the core")
        if re.search(r"\bgetVoices\s*\(", text) and not re.search(r"\blocalService\b", text):
            errors.append(f"{rel}: chooses OS synthesiser voices without requiring an installed (localService) voice")
    config = root / "apps/desktop/src-tauri/tauri.conf.json"
    if config.exists():
        csp = json.loads(config.read_text()).get("app", {}).get("security", {}).get("csp", {})
        sources = set(str(csp.get("connect-src", "")).split()) if isinstance(csp, dict) else set()
        if not sources or sources - CONNECT_SOURCES:
            extra = sorted(sources - CONNECT_SOURCES)
            errors.append(f"apps/desktop/src-tauri/tauri.conf.json: connect-src allows more than the core: {extra}")
    return sorted(errors)
