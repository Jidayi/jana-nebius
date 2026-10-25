"""Start the original browser app with an optional verified, local NVIDIA tutor.

No download happens at launch and no Nebius provider key is needed here. The
separately running gateway owns that secret and the persistent inference budget.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from pathlib import Path

import httpx

from jana_tools import REPO_ROOT

MODEL = "nvidia-nemotron-nano-4b"
MODEL_SHA256 = "be5d9a656a51922f24f1f09a759cebb694e1f5d9728bf0ef9f8c972c5a0b5ef2"
MODEL_SOURCE = "https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-GGUF"


def verify_model(path: Path) -> None:
    with path.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != MODEL_SHA256:
        raise ValueError("Local model does not match NVIDIA's published SHA-256")


def stop(child: subprocess.Popen[bytes]) -> None:
    if child.poll() is None:
        child.terminate()
        try:
            child.wait(timeout=15)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-model", type=Path)
    parser.add_argument("--port", type=int, default=5187)
    parser.add_argument("--data-dir", type=Path, default=Path(tempfile.gettempdir()) / "jana-nebius-browser")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("port must be between 1 and 65535")
    env = {key: value for key, value in os.environ.items() if key not in {"NEBIUS_API_KEY", "TAVILY_API_KEY"}}
    env.update(
        JANA_NEBIUS_GATEWAY_CONFIG="services/cloud-gateway/deploy/nebius-dev.toml",
        JANA_DEV_DATA_DIR=str(args.data_dir.resolve()),
        JANA_DEV_HOST="127.0.0.1",
        PORT=str(args.port),
    )
    pnpm = shutil.which("pnpm")
    if not pnpm:
        parser.error("pnpm is not installed")
    with tempfile.TemporaryDirectory(prefix="jana-nebius-runtime-") as folder:
        runtime = None
        try:
            if args.local_model:
                verify_model(args.local_model)
                program = shutil.which("llama-server")
                if not program:
                    parser.error("Install llama.cpp before selecting a local NVIDIA model")
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                key = secrets.token_urlsafe(32)
                key_file = Path(folder) / "runtime.key"
                key_file.touch(mode=0o600)
                key_file.write_text(key)
                runtime = subprocess.Popen(
                    [
                        program,
                        "--model",
                        str(args.local_model.resolve()),
                        "--alias",
                        MODEL,
                        "--host",
                        "127.0.0.1",
                        "--port",
                        str(port),
                        "--api-key-file",
                        str(key_file),
                        "--ctx-size",
                        "65536",
                        "--parallel",
                        "4",
                        "--n-gpu-layers",
                        "99",
                        "--jinja",
                        "--reasoning",
                        "off",
                        "--no-webui",
                        "--log-disable",
                    ],
                    cwd=REPO_ROOT,
                    env=env,
                )
                endpoint = f"http://127.0.0.1:{port}"
                with httpx.Client(trust_env=False, headers={"authorization": f"Bearer {key}"}) as client:
                    deadline = time.monotonic() + 120
                    while time.monotonic() < deadline:
                        if runtime.poll() is not None:
                            raise RuntimeError("The local NVIDIA runtime exited during loading")
                        try:
                            if client.get(endpoint + "/health", timeout=2).status_code == 200:
                                break
                        except httpx.HTTPError:
                            pass
                        time.sleep(0.5)
                    else:
                        raise RuntimeError("The local NVIDIA runtime did not load within two minutes")
                # Native control.runtime_endpoint performs the real tool-template
                # readiness generation; /health above only sequences startup.
                env["JANA_DEV_RUNTIME"] = f"{endpoint} {key} {MODEL}"
                print("Verified NVIDIA Nemotron Nano 4B loaded locally; native readiness check follows.", flush=True)
            app = subprocess.Popen([pnpm, "--filter", "@jana/desktop", "dev"], cwd=REPO_ROOT, env=env)
            try:
                return app.wait()
            finally:
                stop(app)
        except KeyboardInterrupt:
            return 130
        finally:
            if runtime is not None:
                stop(runtime)


if __name__ == "__main__":
    raise SystemExit(main())
