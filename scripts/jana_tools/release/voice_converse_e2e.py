"""Spoken round trips through a running development core: microphone audio in, the answer's voice out (VOC-03, VOC-53).

    uv run python -m jana_tools.release.voice_converse_e2e [--app http://localhost:5180] [--profile NAME]
        [--speech-python PATH] [--question TEXT ...] [--place ask|study] [--source SRC_ID --revision N]

The app must be the Vite dev server (`apps/desktop/dev/sidecar.ts`) with a conversation speech pack installed and
`JANA_DEV_HARDWARE=mid` (or high). The check plays the webview: it opens the named profile and a guided Physics
session (the Home box's session), opens its voice socket in push-to-talk in an open chat (D130: Ask anything by
default, or `--place study` with a non-private source's Chat), and for each question streams synthetic speech (Kokoro,
rendered by the speech venv's interpreter) at real-time pace in 20 ms frames, releases the key and records:

- `heard_s`: release to the final caption of what the student said (speech to text);
- `first_audio_s`: release to the first byte of the tutor's voice (the number a student feels; often the filler);
- `answer_audio_s`: release to the start of the answer itself, when a filler played first;
- `audio_s`: how much speech came back, and the tutor's caption text;
- `answered`: the `voice.answer` the UI was given (VOC-53): its route (`tutor` for a subject question, `ask`, `study`),
  the Ask anything reply's state or the chat aid.

Captions and `voice.state` are session events: they arrive on the session's event stream, not the voice socket, so the
check reads both.

The first question includes starting the sidecar and loading its models. No audio is kept; no network beyond loopback.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import secrets
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

FRAME = 480 * 2  # 20 ms of 24 kHz mono PCM16
QUESTIONS = [
    "What is the formula for kinetic energy?",
    "A car speeds up from rest to twenty metres per second in five seconds. What is its acceleration?",
    "Who wrote the novel Things Fall Apart?",  # a general question: Ask anything, or its offline line (STU-20)
]
SPEAK = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from agent_core.net.voice_speech import KokoroEngine
engine = KokoroEngine(Path(sys.argv[2]), "am_michael")
for line in sys.stdin:
    pcm = b"".join(engine.stream(line.strip()))
    sys.stdout.buffer.write(len(pcm).to_bytes(4, "big") + pcm)
    sys.stdout.buffer.flush()
"""
HEAR = """
import sys
import numpy
import soxr
from faster_whisper import WhisperModel
audio = numpy.frombuffer(sys.stdin.buffer.read(), dtype=numpy.int16).astype(numpy.float32) / 32768
model = WhisperModel(sys.argv[1], device="cpu", compute_type="int8")
print(" ".join(s.text.strip() for s in model.transcribe(soxr.resample(audio, 24000, 16000), language="en")[0]))
"""


def hear(python: Path, models: Path, pcm: bytes) -> str:
    """What the tutor's voice said, transcribed in memory by the speech venv (nothing is written to disk)."""
    done = subprocess.run([str(python), "-c", HEAR, str(models / "faster-whisper-small.en")], input=pcm,
                          capture_output=True, check=False)  # fmt: skip
    return done.stdout.decode().strip()


class Core:
    def __init__(self, app: str) -> None:
        with urllib.request.urlopen(f"{app}/__jana_dev/launch", timeout=300) as reply:  # noqa: S310 -- dev server
            launch = json.loads(reply.read())
        self.base, self.token, self.origin = launch["base_url"], launch["token"], app

    def call(self, method: str, path: str, body: Any = None, profile: str | None = None) -> Any:
        headers = {
            "authorization": f"Bearer {self.token}",
            "origin": self.origin,
            "content-type": "application/json",
            "idempotency-key": f"cli_{secrets.token_hex(13).upper()}",
        }
        if profile:
            headers["x-profile-token"] = profile
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(f"{self.base}{path}", data=data, method=method, headers=headers)  # noqa: S310
        with urllib.request.urlopen(request, timeout=120) as reply:  # noqa: S310 -- loopback only
            text = reply.read().decode()
            return json.loads(text) if text else None


def watch(core: Core, profile: str, session_id: str, seen: list[tuple[float, dict[str, Any]]]) -> None:
    """Append each voice event of the session's stream to `seen`, with its arrival time (a daemon thread)."""

    def run() -> None:
        headers = {"authorization": f"Bearer {core.token}", "origin": core.origin, "x-profile-token": profile,
                   "accept": "text/event-stream"}  # fmt: skip
        request = urllib.request.Request(f"{core.base}/v1/sessions/{session_id}/events", headers=headers)  # noqa: S310
        with urllib.request.urlopen(request, timeout=900) as stream:  # noqa: S310 -- loopback only
            for raw in stream:
                line = raw.decode().strip()
                if not line.startswith("data:"):
                    continue
                with contextlib.suppress(ValueError):
                    frame = json.loads(line[5:])
                    event = frame.get("event", frame) if isinstance(frame, dict) else None  # the envelope's event
                    if isinstance(event, dict) and str(event.get("type", "")).startswith("voice."):
                        seen.append((time.monotonic(), event))

    threading.Thread(target=run, daemon=True).start()


def synthesise(python: Path, models: Path, questions: list[str]) -> list[bytes]:
    core = Path(__file__).resolve().parents[3] / "services" / "agent-core"
    child = subprocess.Popen(
        [str(python), "-c", SPEAK, str(core), str(models / "Kokoro-82M")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    assert child.stdin is not None and child.stdout is not None
    clips = []
    for question in questions:
        child.stdin.write(question.encode() + b"\n")
        child.stdin.flush()
        size = int.from_bytes(child.stdout.read(4), "big")
        clips.append(child.stdout.read(size))
    child.stdin.close()
    child.wait()
    return clips


async def converse(
    core: Core,
    profile: str,
    session_id: str,
    clips: list[bytes],
    questions: list[str],
    place: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    from websockets.asyncio.client import connect
    from websockets.typing import Origin, Subprotocol

    url = core.base.replace("http://", "ws://") + f"/v1/sessions/{session_id}/voice"
    names = ["jana.voice.1", f"jana.bearer.{core.token}", f"jana.profile.{profile}"]
    results = []
    seen: list[tuple[float, dict[str, Any]]] = []
    watch(core, profile, session_id, seen)
    async with connect(url, subprotocols=[Subprotocol(n) for n in names], origin=Origin(core.origin),
                       max_size=2**22, proxy=None, compression=None, open_timeout=300) as socket:  # fmt: skip
        await socket.send(json.dumps({"type": "capture", "echo_cancellation": False, "headphones": True}))
        # D130: the conversation lives in an open chat (VOC-53); without a place the socket only reads aloud.
        await socket.send(json.dumps({"type": "place", **(place or {"place": "ask"})}))
        await socket.send(json.dumps({"type": "mode", "mode": "push_to_talk"}))
        for question, clip in zip(questions, clips, strict=True):
            mark = len(seen)
            await socket.send(json.dumps({"type": "ptt", "pressed": True}))
            silence = bytes(FRAME)
            for chunk in [silence] * 10 + [clip[i : i + FRAME].ljust(FRAME, b"\0") for i in range(0, len(clip), FRAME)]:
                await socket.send(chunk)
                await asyncio.sleep(0.02)
            await socket.send(json.dumps({"type": "ptt", "pressed": False}))
            released = time.monotonic()
            heard = first = answer = None
            bursts, last_audio = 0, -10.0
            heard_text, said, samples, tag, reply = "", "", 0, None, bytearray()
            deadline = 300.0
            while True:
                try:  # the filler can come first; the answer follows once the tutor's checks finish
                    gap = deadline if first is None else 3.0 if bursts >= 2 else 180.0
                    message = await asyncio.wait_for(socket.recv(), gap)
                except TimeoutError:
                    break
                now = time.monotonic() - released
                if isinstance(message, bytes):
                    if first is None:
                        first = now
                    if now - last_audio > 1.0:
                        bursts += 1
                        if bursts == 2:
                            answer = now
                    last_audio = now
                    tag = message[:16].hex()
                    reply += message[16:]
                    samples += (len(message) - 16) // 2
                    await socket.send(json.dumps({"type": "playback", "response_id": tag,
                                                  "played_ms": samples * 1000 // 24_000, "ended": False}))  # fmt: skip
                    continue
            states, answered = [], None
            for at, event in seen[mark:]:
                now = at - released
                if event["type"] == "voice.state":
                    states.append(f"{round(now, 2)}:{event.get('state')}")
                elif event["type"] == "voice.answer" and answered is None:
                    reply_state = (event.get("reply") or {}).get("state")
                    answered = {"route": event.get("route"), "place": event.get("place"), "state": reply_state,
                                "aid_id": event.get("aid_id"), "at_s": round(now, 2)}  # fmt: skip
                elif event["type"] == "voice.caption":
                    if event.get("speaker") == "student" and event.get("final") and heard is None:
                        heard, heard_text = now, event.get("committed_text", "")
                    elif event.get("speaker") != "student":
                        said = event.get("committed_text", said)
            if tag is not None:
                await socket.send(json.dumps({"type": "playback", "response_id": tag,
                                              "played_ms": samples * 1000 // 24_000, "ended": True}))  # fmt: skip
            results.append({
                "question": question, "heard": heard_text, "heard_s": heard and round(heard, 2),
                "first_audio_s": first and round(first, 2),
                "answer_audio_s": answer and round(answer, 2), "audio_s": round(samples / 24_000, 1), "said": said,
                "states": states, "answered": answered, "pcm": bytes(reply),
            })  # fmt: skip
            await asyncio.sleep(1.0)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="voice_converse_e2e")
    parser.add_argument("--app", default="http://localhost:5180")
    parser.add_argument("--profile", default="UI test")
    parser.add_argument("--speech", type=Path, default=Path.home() / ".cache" / "jana-speech")
    parser.add_argument("--question", action="append")
    parser.add_argument("--place", choices=("ask", "study"), default="ask")
    parser.add_argument("--source", help="the study source whose Chat holds the conversation (with --place study)")
    parser.add_argument("--revision", type=int, default=1)
    args = parser.parse_args(argv)
    place: dict[str, Any] = {"place": "ask"}
    if args.place == "study":
        if not args.source:
            parser.error("--place study needs --source")
        place = {"place": "study", "source_id": args.source, "revision": args.revision, "open": ""}
    questions = args.question or QUESTIONS
    clips = synthesise(args.speech / "venv" / "bin" / "python", args.speech / "models", questions)
    core = Core(args.app)
    listed = core.call("GET", "/v1/profiles")
    profiles = listed["profiles"] if isinstance(listed, dict) else listed
    chosen = next(p for p in profiles if p.get("display_name") == args.profile)
    profile = core.call("POST", f"/v1/profiles/{chosen['profile_id']}/open", {})["profile_token"]
    session = core.call("POST", "/v1/sessions", {
        "client_session_id": f"cli_{secrets.token_hex(13).upper()}", "mode": "guided", "subject": "physics",
        "level": "O", "origin": {"kind": "ask", "ref": None},
    }, profile)["session_id"]  # fmt: skip
    for result in asyncio.run(converse(core, profile, session, clips, questions, place)):
        result["said"] = result["said"] or hear(args.speech / "venv" / "bin" / "python", args.speech / "models",
                                                 result.pop("pcm"))  # fmt: skip
        result.pop("pcm", None)
        print(json.dumps(result), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
