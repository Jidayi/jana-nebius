"""End-to-end read-aloud check of a speech pack on this computer, through the real agent core (VOC-18, D95).

    uv run python -m jana_tools.release.speech_pack_e2e PACK_DIR [--work DIR] [--reads 3]

The pack must be signed: a development-signed copy for a development core (`signing_service sign-speech-pack --dev`;
the test hierarchy is trusted by development builds only), the owner's Updater-signed pack for a release core. The
check plays the desktop shell and the webview: it starts the agent core over its control channel in a fresh data
folder with the scripted tutor, installs the pack through `POST /v1/packs/install` as Settings does, creates and opens
a profile, gets one accepted tutor reply, opens the session's voice socket, and on the core's `control.voice_start`
starts the pack's sidecar exactly as the shell does (verified entry point, cleared environment, offline flags,
credentials on stdin). It then reads the reply aloud through the sidecar and records time to first audio.

The scripted core runs the low hardware class (Kokoro-82M `af_heart`, the slow-laptop voice); `--sidecar-only high`
instead drives the high-class sidecar (Qwen3-TTS `Ryan` on MLX) with a stand-in adapter. Results are printed and
written as JSON beside the work folder. No network is used beyond loopback; no audio is kept.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import queue
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from jana_tools import REPO_ROOT


class Shell:
    """The agent core over its control channel, as the desktop shell drives it, including the voice sidecar."""

    def __init__(self, data_dir: Path) -> None:
        from agent_core.contracts._compat import current

        self.token = secrets.token_urlsafe(32)
        self.messages: queue.Queue[dict[str, Any]] = queue.Queue()
        self.sidecar: subprocess.Popen[bytes] | None = None
        self.sidecar_started: float | None = None
        self.sidecar_ready: float | None = None
        self.log = (data_dir.parent / f"{data_dir.name}.core.log").open("w")
        self.core = subprocess.Popen(
            [sys.executable, "-m", "agent_core.api"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=self.log,
            text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()
        control = current("control")
        self.send({"type": "control.hello", "protocol": {"major": control.major, "minor": control.minor}})
        self.send(
            {
                "type": "control.config",
                "data_dir": str(data_dir),
                "content_root": str(REPO_ROOT / "content" / "agent"),
                "skills_root": str(REPO_ROOT / "skills"),
                "release": False,
                "scripted": True,
            }
        )
        self.send({"type": "control.secret", "name": "launch_token", "value": self.token})

    def send(self, message: dict[str, Any]) -> None:
        assert self.core.stdin is not None
        self.core.stdin.write(json.dumps(message) + "\n")
        self.core.stdin.flush()

    def _read(self) -> None:
        assert self.core.stdout is not None
        for line in self.core.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if message.get("type") == "control.voice_start":
                threading.Thread(target=self._start_voice, args=(message,), daemon=True).start()
            elif message.get("type") == "control.voice_stop" and self.sidecar is not None:
                self.sidecar.terminate()
            else:
                self.messages.put(message)

    def _start_voice(self, start: dict[str, Any]) -> None:
        """What the shell's voice supervisor does (VOC-23): check the entry point's digest, start it with a cleared
        environment and the offline flags, send the launch on stdin and relay its readiness to the core."""
        program = Path(start["program"])
        if hashlib.sha256(program.read_bytes()).hexdigest() != start["program_sha256"]:
            self.send({"type": "control.voice_failed", "request_id": start["request_id"], "code": "voice_start_failed"})
            return
        realtime = secrets.token_urlsafe(32)
        env = {"HOME": os.environ["HOME"], "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        self.sidecar_started = time.monotonic()
        self.sidecar = subprocess.Popen(
            [str(program)],
            cwd=start["pack_dir"],
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert self.sidecar.stdin is not None and self.sidecar.stdout is not None
        launch = {
            key: start[key]
            for key in (
                "pack_dir",
                "hardware",
                "platform",
                "app_version",
                "environment",
                "adapter_url",
                "adapter_token",
            )
        }
        self.sidecar.stdin.write(json.dumps({"protocol": 1, **launch, "realtime_token": realtime}).encode() + b"\n")
        self.sidecar.stdin.flush()  # stdin stays open: the sidecar stops when the shell goes
        reply = json.loads(self.sidecar.stdout.readline() or b"{}")
        if reply.get("type") != "voice.ready":
            self.send({"type": "control.voice_failed", "request_id": start["request_id"], "code": "voice_start_failed"})
            return
        self.sidecar_ready = time.monotonic()
        self.send(
            {
                "type": "control.voice_endpoint",
                "request_id": start["request_id"],
                "url": f"ws://127.0.0.1:{reply['port']}/v1/realtime",
                "token": realtime,
            }
        )

    def wait(self, kind: str, timeout_s: float) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                message = self.messages.get(timeout=0.2)
            except queue.Empty:
                continue
            if message.get("type") == kind:
                return message
        raise TimeoutError(kind)

    def call(self, method: str, port: int, path: str, body: Any = None, profile: str | None = None) -> Any:
        headers = {
            "authorization": f"Bearer {self.token}",
            "origin": "tauri://localhost",
            "content-type": "application/json",
            "idempotency-key": f"cli_{secrets.token_hex(13).upper()}",
        }
        if profile:
            headers["x-profile-token"] = profile
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=120) as reply:  # noqa: S310 -- loopback only
                text = reply.read().decode()
                return json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            raise RuntimeError(f"{method} {path}: {error.code} {error.read().decode()[:300]}") from None

    def close(self) -> None:
        try:
            self.send({"type": "control.shutdown", "grace_ms": 2000})
            self.core.wait(timeout=15)
        except (OSError, subprocess.TimeoutExpired):
            self.core.kill()
        if self.sidecar is not None and self.sidecar.poll() is None:
            self.sidecar.terminate()


def accepted_part(shell: Shell, port: int, profile: str, session_id: str) -> tuple[str, str]:
    shell.call(
        "POST",
        port,
        f"/v1/sessions/{session_id}/turns",
        {
            "client_message_id": f"cli_{secrets.token_hex(13).upper()}",
            "intent": "ask",
            "content": [{"type": "text", "text": "A ball is thrown straight up at 14 m/s. How high does it go?"}],
        },
        profile,
    )
    deadline, best = time.monotonic() + 60, None
    while time.monotonic() < deadline:
        snapshot = shell.call("GET", port, f"/v1/sessions/{session_id}/snapshot", profile=profile)
        complete = [
            (str(part.get("text") or part.get("content")), str(part["part_id"]))
            for part in _parts(snapshot)
            if part.get("kind") == "text"
            and part.get("status") == "complete"
            and (part.get("text") or part.get("content"))
        ]
        if complete:
            best = max(complete, key=lambda item: len(item[0]))  # the Coach's reply, not a short status line
            if best[0].endswith("?") or time.monotonic() > deadline - 50:
                return best[1], best[0]
        time.sleep(0.2)
    if best is not None:
        return best[1], best[0]
    raise TimeoutError("no accepted tutor reply")


def _parts(value: Any) -> list[dict[str, Any]]:
    """Every text part anywhere in the session snapshot (its projection nests them under turns or a parts map)."""
    found: list[dict[str, Any]] = []
    if isinstance(value, dict):
        if isinstance(value.get("part_id"), str) and value.get("kind"):
            found.append(value)
        for item in value.values():
            found += _parts(item)
    elif isinstance(value, list):
        for item in value:
            found += _parts(item)
    return found


async def read_aloud(
    shell: Shell, port: int, profile: str, session_id: str, part_id: str, reads: int
) -> list[dict[str, Any]]:
    from websockets.asyncio.client import connect
    from websockets.typing import Origin, Subprotocol

    url = f"ws://127.0.0.1:{port}/v1/sessions/{session_id}/voice"
    names = ["jana.voice.1", f"jana.bearer.{shell.token}", f"jana.profile.{profile}"]
    protocols = [Subprotocol(name) for name in names]
    results = []
    clicked = time.monotonic()  # the first press opens the socket, so its time includes starting the sidecar
    async with connect(
        url,
        subprotocols=protocols,
        origin=Origin("tauri://localhost"),
        max_size=2**20,
        proxy=None,
        compression=None,
        open_timeout=300,
    ) as socket:
        await socket.send(json.dumps({"type": "mode", "mode": "push_to_talk"}))
        for read in range(reads):
            if read:
                clicked = time.monotonic()
            utterance = await asyncio.to_thread(
                shell.call,
                "POST",
                port,
                f"/v1/sessions/{session_id}/voice/utterances",
                {"type": "read_aloud", "part_id": part_id},
                profile,
            )
            await socket.send(json.dumps({"type": "speak", "utterance_id": utterance["utterance_id"]}))
            tag = hashlib.sha256(utterance["utterance_id"].encode()).digest()[:16]
            first, samples, played = None, 0, 0
            while True:
                try:  # the first audio may wait for the sidecar to start; after it, a 1.5 s gap ends the reading
                    message = await asyncio.wait_for(socket.recv(), 1.5 if first is not None else 240)
                except TimeoutError:
                    break
                if isinstance(message, bytes) and message[:16] == tag:
                    if first is None:
                        first = time.monotonic() - clicked
                    samples += (len(message) - 16) // 2
                    played = samples * 1000 // 24_000
                    # Report playback as the webview does, so captions and completion follow it (VOC-09).
                    await socket.send(
                        json.dumps({"type": "playback", "utterance_id": tag.hex(), "played_ms": played, "ended": False})
                    )
            await socket.send(
                json.dumps({"type": "playback", "utterance_id": tag.hex(), "played_ms": played, "ended": True})
            )
            results.append(
                {
                    "read": read + 1,
                    "transport": utterance["transport"],
                    "text": utterance["text"],
                    "first_audio_s": round(first, 3) if first is not None else None,
                    "audio_s": round(samples / 24_000, 2),
                }
            )
            await asyncio.sleep(0.5)
    return results


def run(pack: Path, work: Path, reads: int) -> dict[str, Any]:
    data = Path(tempfile.mkdtemp(prefix="speech-e2e-", dir=work))
    shell = Shell(data)
    report: dict[str, Any] = {"pack": str(pack), "data_dir": str(data)}
    try:
        port = int(shell.wait("control.ready", 120)["api_port"])
        job = shell.call("POST", port, "/v1/packs/install", {"source": {"kind": "usb", "path": str(pack)}})
        started = time.monotonic()
        while time.monotonic() - started < 300:
            state = shell.call("GET", port, f"/v1/jobs/{job['job_id']}")
            if state.get("state") in ("done", "failed"):
                break
            time.sleep(0.5)
        report["install"] = {
            "state": state.get("state"),
            "seconds": round(time.monotonic() - started, 1),
            "result": state.get("result_ref"),
            "error": state.get("error"),
        }
        meta = shell.call("GET", port, "/v1/meta")
        report["capabilities"] = [c for c in meta["capabilities"] if c.startswith("voice")]
        created = shell.call(
            "POST",
            port,
            "/v1/profiles",
            {
                "display_name": "Speech check",
                "avatar": "owl",
                "level": "O",
                "subjects": ["physics"],
                "age_band": "16_17",
            },
        )
        profile = shell.call("POST", port, f"/v1/profiles/{created['profile_id']}/open", {})["profile_token"]
        session = shell.call(
            "POST",
            port,
            "/v1/sessions",
            {
                "client_session_id": f"cli_{secrets.token_hex(13).upper()}",
                "mode": "guided",
                "subject": "physics",
                "level": "O",
                "origin": {"kind": "ask", "ref": None},
            },
            profile,
        )["session_id"]
        part_id, text = accepted_part(shell, port, profile, session)
        report["reply"] = text
        report["reads"] = asyncio.run(read_aloud(shell, port, profile, session, part_id, reads))
        if shell.sidecar_started and shell.sidecar_ready:
            report["sidecar_start_s"] = round(shell.sidecar_ready - shell.sidecar_started, 2)
    finally:
        shell.close()
    return report


SAMPLE = (
    "Every transaction touches at least two accounts: when cash comes in, something else goes up or down by "
    "the same amount. If the two sides ever disagree, a step was missed."
)


def run_sidecar(pack: Path, work: Path, hardware: str, reads: int) -> dict[str, Any]:
    """The pack's sidecar for one class, started as the shell starts it, against a stand-in engine LLM adapter that
    answers the speak directive with a fixed tutor line (the core's adapter is exercised by the core run)."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from agent_core.config.environments import Environment
    from agent_core.net.voice import LocalVoiceEndpoint
    from agent_core.store.speech_packs import SpeechPackStore
    from signing_service.hierarchy import dev_trust

    data = Path(tempfile.mkdtemp(prefix=f"speech-sidecar-{hardware}-", dir=work))
    installed = SpeechPackStore(
        data / "speech-packs",
        Environment.DEV,
        "macos-aarch64",
        "0.0.0",
        hardware,
        trust=dev_trust(),
    ).install(pack)
    manifest = json.loads((installed / "manifest.json").read_text())
    program = installed / manifest["profiles"][hardware]["sidecar_path"]
    adapter_token, realtime = secrets.token_urlsafe(32), secrets.token_urlsafe(32)

    class Adapter(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("content-length", "0"))
            self.rfile.read(length)
            if self.headers.get("authorization") != f"Bearer {adapter_token}":
                self.send_response(401)
                self.end_headers()
                return
            chunk = {"choices": [{"index": 0, "delta": {"content": SAMPLE}, "finish_reason": "stop"}]}
            body = f"data: {json.dumps(chunk)}\n\ndata: [DONE]\n\n".encode()
            self.send_response(200)
            self.send_header("content-type", "text/event-stream")
            self.send_header("content-length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: Any) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), Adapter)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {"HOME": os.environ["HOME"], "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
    started = time.monotonic()
    sidecar = subprocess.Popen(
        [str(program)], cwd=installed, env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )
    assert sidecar.stdin is not None and sidecar.stdout is not None
    launch = {
        "protocol": 1,
        "pack_dir": str(installed),
        "hardware": hardware,
        "platform": "macos-aarch64",
        "app_version": "0.0.0",
        "environment": "dev",
        "realtime_token": realtime,
        "adapter_token": adapter_token,
        "adapter_url": f"http://127.0.0.1:{server.server_address[1]}/v1/voice/llm",
    }
    sidecar.stdin.write(json.dumps(launch).encode() + b"\n")
    sidecar.stdin.flush()
    report: dict[str, Any] = {"pack": str(pack), "hardware": hardware, "voice": manifest["profiles"][hardware]}
    try:
        ready = json.loads(sidecar.stdout.readline() or b"{}")
        report["sidecar_start_s"] = round(time.monotonic() - started, 2)
        if ready.get("type") != "voice.ready":
            report["error"] = ready
            return report

        async def speak() -> list[dict[str, Any]]:
            socket = await LocalVoiceEndpoint(f"ws://127.0.0.1:{ready['port']}/v1/realtime", realtime).open()
            results = []
            try:
                assert (await socket.receive())["type"] == "session.created"
                binding = "jana-voice-binding: vb_" + "0" * 26
                await socket.send({"type": "session.update", "session": {"type": "realtime", "instructions": binding}})
                for read in range(reads):
                    await socket.send(
                        {
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message",
                                "role": "user",
                                "content": [{"type": "input_text", "text": "jana-speak: utt_" + "0" * 26}],
                            },
                        }
                    )
                    clicked = time.monotonic()
                    await socket.send({"type": "response.create"})
                    first, samples, units = None, 0, []
                    while True:
                        event = await asyncio.wait_for(socket.receive(), 120)
                        if event["type"] == "response.output_audio.delta":
                            first = first if first is not None else time.monotonic() - clicked
                            samples += len(event["delta"]) * 3 // 8
                        elif event["type"] == "response.output_audio_transcript.delta":
                            units.append(event["delta"])
                        elif event["type"] == "response.done":
                            break
                    results.append(
                        {
                            "read": read + 1,
                            "first_audio_s": round(first, 3) if first else None,
                            "audio_s": round(samples / 24_000, 2),
                            "wall_s": round(time.monotonic() - clicked, 2),
                            "first_unit": units[0] if units else None,
                        }
                    )
            finally:
                await socket.close()
            return results

        report["reads"] = asyncio.run(speak())
    finally:
        sidecar.terminate()
        server.shutdown()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="speech_pack_e2e")
    parser.add_argument("pack", type=Path)
    parser.add_argument("--work", type=Path, default=Path(tempfile.gettempdir()))
    parser.add_argument("--reads", type=int, default=3)
    parser.add_argument("--sidecar-only", choices=["low", "mid", "high"], help="drive one class's sidecar directly")
    args = parser.parse_args(argv)
    args.work.mkdir(parents=True, exist_ok=True)
    pack = args.pack.expanduser().resolve()
    if args.sidecar_only:
        report = run_sidecar(pack, args.work, args.sidecar_only, args.reads)
        out = args.work / f"speech-sidecar-{args.sidecar_only}.json"
        out.write_text(json.dumps(report, indent=1) + "\n")
        print(json.dumps(report, indent=1))
        return 0 if report.get("reads") else 1
    report = run(pack, args.work, args.reads)
    out = args.work / "speech-e2e.json"
    out.write_text(json.dumps(report, indent=1) + "\n")
    for read in report.get("reads", []):
        print(
            f"read-aloud {read['read']}: transport={read['transport']} first_audio={read['first_audio_s']}s "
            f"audio={read['audio_s']}s"
        )
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
