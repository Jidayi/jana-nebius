"""M43.f demonstration: talk naturally, point precisely, demonstrate the next step (VOC-51, VOC-52, UXS-63, VSL-45,
UXS-64, PED-28), first on a maths board, then with the same mechanism on the physics pack's labelled refraction drawing.

    uv run --all-packages python -m jana_tools.point_demo [--out FILE]
    uv run --all-packages python -m jana_tools.point_demo --sidecar INSTALLED_PACK --hardware low|high [--out FILE]

What runs for real: the agent core's engine (input routing, the stop gates, Finalise, the board and visual handlers,
the voice turn fork, release and finish), the cue resolver and the voice bridge. What is scripted: the Coach's tutor
turns (no language model runs; the replies are invented for this demo and pass the same gates as a model's would) and
the student's words (typed here as if transcribed). Without `--sidecar` the audio is SIMULATED: each spoken unit gets
silent audio of the length the VOC-09 synchroniser estimates, so the timeline shows the mechanism, not a measurement.
With `--sidecar` the accepted spoken forms are spoken by an installed, signed speech pack's sidecar (Kokoro on the low
class, Qwen3-TTS on the high class), through the Realtime subset, and every timing in the `measured` block comes from
that run on this computer. Nothing is downloaded; no audio is kept; the student's playback device is not part of the
run (cue firing on the device clock is covered by the client tests), and the report says so.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import secrets
import statistics
import subprocess
import tempfile
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Any

from jana_tools import REPO_ROOT

TURN_ID_BINDING = "jana-voice-binding: vb_" + "0" * 26
SYLLABLES_PER_S = 3.83  # the VOC-09 fallback synchroniser


def _op(op: str, **fields: Any) -> dict[str, Any]:
    return {
        "op": op,
        "step": None,
        "latex": None,
        "reason": None,
        "owner": None,
        "status": None,
        "terms": [],
        "prompt": None,
        "check_id": None,
        **fields,
    }


def _tutor(say: str, **fields: Any) -> dict[str, Any]:
    turn = {
        "say_spoken": None,
        "say": say,
        "board": [],
        "visual": [],
        "card": None,
        "hint_rung": 0,
        "expects": "student_answer",
        "numbers_from": [],
        "cites": [],
        "reveals": "none",
        "confidence": "medium",
    }
    turn.update(fields)
    message = {"role": "assistant", "content": json.dumps(turn)}
    return {
        "reply": {
            "model": "qwen3-vl-8b",
            "choices": [{"message": message, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        }
    }


# --- the scripted lesson (invented for the demo) --------------------------------------------------------------------

MATHS = "Solve 2x + 3 = 11."
OPERATION = "2x + 3 - 3 = 11 - 3"
MATHS_TURNS = [
    (
        "Why do we take away three?",
        _tutor(
            "This line adds 3 to 2x, so we take 3 from both sides and they stay equal. What do you get on the right?",
            say_spoken='This line <point at="1"/> adds three to two x, so we take three from both sides and they stay '
            "equal. What do you get on the right?",
            board=[_op("highlight", step=1)],
        ),
    ),
    (
        "I'm stuck, show me",
        _tutor(
            "We take 3 from both sides: 2x + 3 - 3 = 11 - 3. What does the right side come to?",
            say_spoken='This line <point at="1"/> adds three to two x, so we take three from both sides. '
            '<write at="2">Two x plus three minus three equals eleven minus three.</write> '
            "What does the right side come to?",
            hint_rung=4,
            board=[
                _op("highlight", step=1),
                _op(
                    "add_step",
                    latex=OPERATION,
                    reason="take 3 from both sides",
                    owner="tutor",
                    status="final",
                    check_id="chk_step2",
                ),
            ],
        ),
    ),
    (
        "It comes to eight, so 2x = 8",
        _tutor(
            "Right, the right side is 8, so 2x = 8. What is x?",
            say_spoken='Right <point at="3"/>, the right side comes to eight. What is x?',
        ),
    ),
]
PHYSICS = "A ray of light goes from air into a glass block. Explain what happens to the ray."
REFRACTION = "dgm.phy.refraction_glass_block.v1"
PHYSICS_TURNS = [
    (
        "I'm stuck",
        _tutor(
            "Here is the ray going into the block. Which line is the normal?",
            visual=[
                {
                    "spec_version": 1,
                    "type": "library_diagram",
                    "ref": REFRACTION,
                    "params": {},
                    "steps": [{"highlight": ["incident_ray"]}],
                }
            ],
        ),
    ),
    (
        "Why does the ray bend towards the normal?",
        _tutor(
            "Glass slows the light, so the ray bends towards the normal and the angle of refraction is smaller. "
            "Which angle is smaller?",
            say_spoken='Here is the normal <point at="normal_entry"/> where the ray goes in. '
            'Glass slows the light, so the ray <point at="refracted_ray"/> bends towards it '
            'and this angle <point at="angle_r"/> is smaller. '
            "Which angle is smaller?",
        ),
    ),
    # VSL-45: a part name the drawing does not have, and a line that is not on the board, draw nothing.
    (
        "Why is the normal at right angles?",
        _tutor(
            "The normal is the line at right angles to the surface, so we measure both angles from it. Which angle is "
            "measured from the normal inside the glass?",
            say_spoken='The normal <point at="normal"/> is at right angles to the surface <point at="4"/>, '
            "so we measure both angles from it. Which angle is measured from the normal inside the glass?",
        ),
    ),
]


def _engine(work: Path, replies: list[dict[str, Any]], subject: str) -> tuple[Any, Any]:
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.scripted import ScriptedProvider

    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,)).model_copy(update={"build_stage": "S1"})
    provider = ScriptedProvider({"coach": replies}, kind="local", installed_models=["qwen3-vl-8b", "gemma-4-12b"])

    async def no_sleep(_: float) -> None:
        return None

    def build(state: Any) -> Any:
        return assemble(
            {"local": provider},
            settings,
            state,
            REPO_ROOT / "content" / "agent",
            REPO_ROOT / "skills",
            work / "spill",
            None,
            sleep=no_sleep,
            session_date="2026-10-17",
        )

    return build(SessionState(new_id("ses"), subject=subject, level="O", hardware_class="mid")), build


def _maths_state(state: Any) -> None:
    from agent_core.engine.state import BoardStep, Plan, PlanStep, Problem
    from agent_core.engine.ui import open_board

    state.problem = Problem("prb_demo_lin", MATHS, "prb_demo_lin#statement")
    state.plan = Plan(
        [
            PlanStep(1, "2x + 3 = 11", None, None, None),
            PlanStep(2, OPERATION, "8", None, "chk_step2"),
            PlanStep(3, "x = 4", "4", None, "chk_step3"),
        ],
        "4",
        None,
        "chk_step3",
    )
    state.check_values = {"chk_step2": [Fraction(8), Fraction(3), Fraction(11)], "chk_step3": [Fraction(4)]}
    open_board(state)
    state.board.steps = [
        BoardStep("stp_01JZ0000000000000000000001", 0, "2x + 3 = 11", "the equation", "tutor", "final")
    ]
    state.step, state.rung, state.attempts, state.hint_step = 2, 3, {2: 1}, 2


def _physics_sources(engine: Any) -> None:
    import yaml
    from agent_core.store.svg import normalise

    pack = REPO_ROOT / "content" / "curriculum" / "phy" / "o"
    entry = yaml.safe_load((pack / "diagrams" / f"{REFRACTION}.yaml").read_text())
    entry = {**entry, "svg": normalise((pack / entry["svg_path"]).read_text())}
    sources = {"diagrams": {REFRACTION: entry}, "presets": {}, "conventions": {}, "pack_values": {}}
    engine.deps.visual_sources = lambda code: sources


# --- speech: simulated, or the installed pack's sidecar -----------------------------------------------------------


def _units(text: str) -> list[str]:
    return [u for u in re.split(r"(?<=[.!?])\s+", text.strip()) if u]


def _estimate_ms(text: str) -> int:
    syllables = sum(max(1, len(re.findall(r"[aeiouy]+", w.lower()))) for w in text.split())
    return round(syllables * 1000 / SYLLABLES_PER_S)


class Sidecar:
    """An installed speech pack's sidecar started as the shell starts it, with a stand-in adapter that streams the
    accepted spoken text it is given, unit by unit, as the core's adapter does (VOC-33)."""

    def __init__(self, installed: Path, hardware: str) -> None:
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        manifest = json.loads((installed / "manifest.json").read_text())
        self.voice = manifest["profiles"][hardware]
        self.text = ""
        adapter_token, self.realtime = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        outer = self

        class Adapter(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                self.rfile.read(int(self.headers.get("content-length", "0")))
                if self.headers.get("authorization") != f"Bearer {adapter_token}":
                    self.send_response(401)
                    self.end_headers()
                    return
                # Exactly the core adapter's delivery units: sentence by sentence, spaces kept (VOC-33).
                frames = [
                    {"choices": [{"index": 0, "delta": {"content": unit}, "finish_reason": None}]}
                    for unit in re.split(r"(?<=[.!?])(?=\s)", outer.text)
                ]
                body = "".join(f"data: {json.dumps(f)}\n\n" for f in frames) + "data: [DONE]\n\n"
                data = body.encode()
                self.send_response(200)
                self.send_header("content-type", "text/event-stream")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args: Any) -> None:
                return None

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Adapter)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        env = {"HOME": os.environ["HOME"], "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1"}
        started = time.monotonic()
        self.process = subprocess.Popen(
            [str(installed / self.voice["sidecar_path"])],
            cwd=installed,
            env=env,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert self.process.stdin is not None and self.process.stdout is not None
        launch = {
            "protocol": 1,
            "pack_dir": str(installed),
            "hardware": hardware,
            "platform": "macos-aarch64",
            "app_version": "0.0.0",
            "environment": "dev",
            "realtime_token": self.realtime,
            "adapter_token": adapter_token,
            "adapter_url": f"http://127.0.0.1:{self.server.server_address[1]}/v1/voice/llm",
        }
        self.process.stdin.write(json.dumps(launch).encode() + b"\n")
        self.process.stdin.flush()
        ready = json.loads(self.process.stdout.readline() or b"{}")
        self.start_s = round(time.monotonic() - started, 2)
        if ready.get("type") != "voice.ready":
            self.close()
            raise RuntimeError(f"sidecar did not start: {ready}")
        self.port = ready["port"]

    async def speak(self, text: str) -> tuple[list[tuple[float, dict[str, Any]]], float]:
        """Speak `text`; returns the sidecar's Realtime events with their arrival times (s after the request)."""
        from agent_core.net.voice import LocalVoiceEndpoint

        self.text = text
        socket = await LocalVoiceEndpoint(f"ws://127.0.0.1:{self.port}/v1/realtime", self.realtime).open()
        events: list[tuple[float, dict[str, Any]]] = []
        try:
            assert (await socket.receive())["type"] == "session.created"
            await socket.send(
                {"type": "session.update", "session": {"type": "realtime", "instructions": TURN_ID_BINDING}}
            )
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
            asked = time.monotonic()
            await socket.send({"type": "response.create"})
            while True:
                event = await asyncio.wait_for(socket.receive(), 120)
                events.append((time.monotonic() - asked, event))
                if event["type"] == "response.done":
                    break
        finally:
            await socket.close()
        return events, asked

    def close(self) -> None:
        self.process.terminate()
        self.server.shutdown()


def _simulated(text: str) -> list[tuple[float, dict[str, Any]]]:
    """SIMULATED sidecar output: per unit, its transcript delta then silent audio of the synchroniser's length."""
    events: list[tuple[float, dict[str, Any]]] = [(0.0, {"type": "response.created", "response": {"id": "resp_sim"}})]
    for n, unit in enumerate(_units(text)):
        events.append(
            (
                0.0,
                {
                    "type": "response.output_audio_transcript.delta",
                    "response_id": "resp_sim",
                    "item_id": "out_1",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": (" " if n else "") + unit,
                },
            )
        )
        pcm = b"\x00\x00" * (24 * _estimate_ms(unit))
        for at in range(0, len(pcm), 48_000):
            events.append(
                (
                    0.0,
                    {
                        "type": "response.output_audio.delta",
                        "response_id": "resp_sim",
                        "item_id": "out_1",
                        "output_index": 0,
                        "content_index": 0,
                        "delta": base64.b64encode(pcm[at : at + 48_000]).decode(),
                    },
                )
            )
    events.append((0.0, {"type": "response.done", "response": {"id": "resp_sim", "status": "completed"}}))
    return events


def _deliver(
    provisional: Any, events: list[tuple[float, dict[str, Any]]], interrupt_at_ms: int | None, measured: bool
) -> dict[str, Any]:
    """Feed the sidecar's events to a real voice bridge bound to the accepted turn, then play (or interrupt) it."""
    from agent_core.engine.voice_bindings import VoiceBindings
    from agent_core.engine.voice_bridge import VoiceBridge, VoiceProtocolError

    bridge = VoiceBridge(VoiceBindings("demo").mint(provisional.live.state.session_id, None))
    bridge.server({"type": "session.created", "event_id": "e0", "session": {"type": "realtime"}}, 0)
    captions: list[dict[str, Any]] = []
    unit_starts: list[tuple[float, int, str]] = []  # (arrival s, audio ms received before it, transcript delta)
    first_audio_s: float | None = None
    response_id: str | None = None
    for at, event in events:
        frame = {"event_id": "e", **event}
        if event["type"] == "response.created":
            response_id = event["response"]["id"]
            bridge.server(frame, 0)
            bridge.authorise_response(response_id, provisional.ids.turn_id, provisional.spoken_text, provisional.cues)
            continue
        if event["type"] == "response.output_audio_transcript.delta":
            received = bridge._response.pcm_bytes // 48 if bridge._response is not None else 0
            unit_starts.append((round(at, 3), received, event["delta"].strip()))
        if event["type"] == "response.output_audio.delta" and first_audio_s is None:
            first_audio_s = round(at, 3)
        if event["type"] not in (
            "response.created",
            "response.output_audio.delta",
            "response.output_audio_transcript.delta",
            "response.output_audio_transcript.done",
            "response.done",
            "response.output_audio.done",
        ):
            continue
        if event["type"] == "response.done" and interrupt_at_ms is not None:
            continue
        try:
            effects = bridge.server(frame, 0)
        except VoiceProtocolError as error:  # the bridge refuses a transcript that is not the accepted text
            spoken = "".join(e["delta"] for _, e in events if e["type"] == "response.output_audio_transcript.delta")
            raise RuntimeError(f"{error}: sidecar said {spoken!r}, accepted {provisional.spoken_text!r}") from None
        captions += [e for e in effects.events if e["type"] == "voice.caption"]
    response = bridge._response
    total_ms = response.pcm_bytes // 48 if response is not None else 0
    words = captions[-1]["words"] if captions else []
    cues = []
    for cue in captions[-1]["cues"] if captions else []:
        index = len(provisional.spoken_text[: cue["char_offset"]].split())
        cues.append(
            {
                "target": cue["target"],
                "char_offset": cue["char_offset"],
                "word": words[index]["w"] if index < len(words) else None,
                "fires_at_ms": words[index]["start_ms"] if index < len(words) else None,
                "timing": "estimated",
            }
        )
    if interrupt_at_ms is not None and response is not None:
        bridge.control(
            {"type": "playback", "response_id": response.response_id, "played_ms": interrupt_at_ms, "ended": False}
        )
        stop = bridge.control({"type": "stop"})
        cancel = next(a for a in stop.actions if a["type"] == "cancel")
        provisional.finish(interrupted=True, played_ms=cancel["played_ms"], heard_chars=cancel["heard_chars"])
    else:
        provisional.finish(interrupted=False, played_ms=total_ms, total_ms=total_ms)
    units = []
    for n, (arrived, received_ms, unit) in enumerate(unit_starts):
        ends = unit_starts[n + 1][1] if n + 1 < len(unit_starts) else total_ms
        units.append(
            {
                "unit": unit,
                "audio_ms": ends - received_ms,
                "estimate_ms": _estimate_ms(unit),
                "transcript_arrived_s": arrived,
                "audio_received_before_ms": received_ms,
            }
        )
    return {
        "audio": "measured" if measured else "SIMULATED",
        "first_audio_s": first_audio_s if measured else None,
        "audio_ms": total_ms,
        "units": units,
        "cues": cues,
        "delivery": provisional.delivery,
    }


async def _lesson(
    name: str,
    turns: list[tuple[str, dict[str, Any]]],
    subject: str,
    work: Path,
    sidecar: Sidecar | None,
    interrupt: dict[int, int],
    write_cues: bool = False,
) -> list[dict[str, Any]]:
    from agent_core.engine import pointing
    from agent_core.engine.voice_turn import ProvisionalVoiceTurn

    # The pinned events contract (D102) has no write cues, so a write travels as a point and its line shows whole on
    # release; `write_cues` runs the lesson as it will run once the contract carries them (API 1.9, D103).
    supported = pointing.cue_actions_supported
    if write_cues:
        pointing.cue_actions_supported = lambda: True  # type: ignore[assignment]

    live, factory = _engine(work / name, [reply for _, reply in turns], subject)
    learned: list[Any] = []
    live.learning = learned.extend
    if subject == "mathematics":
        _maths_state(live.state)
    else:
        from agent_core.engine.state import Problem

        live.state.problem = Problem("prb_demo_ray", PHYSICS, "prb_demo_ray#statement")
        live.state.attempts, live.state.deflected = {1: 1}, {1}  # one try already made: "I'm stuck" gets a hint
        _physics_sources(live)
    out = []
    for n, (said, _) in enumerate(turns):
        started = time.monotonic()
        provisional = ProvisionalVoiceTurn(live, factory, said)
        if subject != "mathematics":  # library drawings are an S2 kind (VSL-03)
            provisional.engine.deps.visual_sources = live.deps.visual_sources
            provisional.engine.deps.stage = "S2"
        await provisional.evaluate()
        accepted_s = time.monotonic() - started
        before = len(learned)
        engine = provisional.release(live.events)
        if sidecar is not None:
            events, _ = await sidecar.speak(provisional.spoken_text)
            heard = _deliver(provisional, events, interrupt.get(n), measured=True)
        else:
            heard = _deliver(provisional, _simulated(provisional.spoken_text), interrupt.get(n), measured=False)
        frames = [f["event"] for f in engine.events.frames if f.get("turn_id") == provisional.ids.turn_id]
        out.append(
            {
                "student": said,
                "engine_accept_ms": round(accepted_s * 1000, 1),
                "gates": [g["gate"] for g in provisional.engine.traces[-1]["gates"] if g["fired"]],
                "board": [
                    {"line": i + 1, "latex": s.latex, "owner": s.owner, "status": s.status, "check": s.check_id}
                    for i, s in enumerate(engine.state.board.steps)
                ],
                "highlights": [e["step_ids"] for e in frames if e["type"] == "board.highlight"],
                "visuals": [{"visual_id": v["visual_id"], "parts": v["parts"]} for v in engine.state.shown_visuals],
                "spoken": provisional.spoken_text,
                "missed_targets": list(provisional.cue_misses),
                "hint_rung": engine.state.rung,
                "learning": [e.type for e in learned[before:]],
                **heard,
            }
        )
        live = engine
    pointing.cue_actions_supported = supported  # type: ignore[assignment]
    return out


def run(work: Path, sidecar: Sidecar | None) -> dict[str, Any]:
    report: dict[str, Any] = {
        "what_is_real": "engine, gates, Finalise, board and visual handlers, voice turn fork and finish, cue resolver, "
        "voice bridge" + (", the installed speech pack's sidecar (audio and its timing)" if sidecar else ""),
        "what_is_scripted": "the Coach's replies and the student's words",
        "what_is_simulated": "nothing"
        if sidecar
        else "the audio: silent frames of the synchroniser's estimated length",
        "not_part_of_the_run": "the student's playback device (cue firing on its clock, output latency): covered by "
        "the client tests with a scripted clock, unmeasured on hardware",
    }
    if sidecar is not None:
        report["sidecar"] = {"voice": sidecar.voice, "start_s": sidecar.start_s}
    # The maths lesson; the second turn is interrupted 3 s into its audio, before the demonstrated line's words.
    report["maths"] = asyncio.run(_lesson("maths", MATHS_TURNS, "mathematics", work, sidecar, {1: 3000}))
    report["maths_after_d103_repin"] = asyncio.run(
        _lesson("maths-d103", MATHS_TURNS, "mathematics", work, sidecar, {1: 3000}, write_cues=True)
    )
    report["diagram"] = asyncio.run(_lesson("diagram", PHYSICS_TURNS, "physics", work, sidecar, {}))
    if sidecar is not None:
        errors = [
            u["audio_ms"] - u["estimate_ms"] for part in ("maths", "diagram") for t in report[part] for u in t["units"]
        ]
        firsts = [t["first_audio_s"] for part in ("maths", "diagram") for t in report[part] if t["first_audio_s"]]
        report["measured"] = {
            "units": len(errors),
            "unit_length_minus_estimate_ms": {
                "median": statistics.median(errors),
                "min": min(errors),
                "max": max(errors),
                "median_abs": statistics.median(abs(e) for e in errors),
            },
            "tts_first_audio_s": {"median": statistics.median(firsts), "max": max(firsts)},
            "transcript_before_audio": all(
                u["audio_received_before_ms"] <= sum(v["audio_ms"] for v in t["units"][:i])
                for part in ("maths", "diagram")
                for t in report[part]
                for i, u in enumerate(t["units"])
            ),
        }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="point_demo")
    parser.add_argument("--sidecar", type=Path, help="an installed speech pack folder (its manifest and bin/)")
    parser.add_argument("--hardware", choices=["low", "mid", "high"], default="low")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    work = Path(tempfile.mkdtemp(prefix="point-demo-"))
    sidecar = Sidecar(args.sidecar.expanduser().resolve(), args.hardware) if args.sidecar else None
    try:
        report = run(work, sidecar)
    finally:
        if sidecar is not None:
            sidecar.close()
    text = json.dumps(report, indent=1, default=str)
    if args.out:
        args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
