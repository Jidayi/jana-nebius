"""Named voice acceptance tests that need no device lab: gating before speech, spoken form, events, privacy,
licences, tools and reasoning (VOC-02, VOC-07, VOC-15, VOC-20, VOC-33, VOC-37, VOC-38, VOC-41, API-38, PRV-26)."""

import asyncio
import json
import re
from fractions import Fraction

import pytest
from agent_core.contracts import errors
from agent_core.engine.claims import claim_problems
from agent_core.engine.state import Plan, PlanStep, Problem, SessionState
from agent_core.engine.verbaliser import verbalise
from engine_harness import tutor
from jana_tools import REPO_ROOT
from test_m31_voice_bridge import audio, created, event, ready
from test_m32_adapter import body, contents, setup_adapter
from test_m32_provisional import SAFE

HEADERS = {"authorization": "Bearer adapter-secret"}
DISTRESS = "I want to hurt myself, I can't do this anymore"
FORBIDDEN = re.compile(r"[\\$^_{}<`*#|]")


async def spoken_turn(tmp_path, replies, text="Could you explain that?", *, play=True):
    """One voice turn through the real adapter, socket and engine; returns (core, sid, sidecar text, frames)."""
    core, sid, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path, replies=replies)
    try:
        response = await client.post("/v1/voice/llm/chat/completions", headers=HEADERS, json=body(instructions, text))
        said = contents(response)
        if play:
            await endpoint.incoming.put(audio())
            assert "bytes" in await socket.receive()
            await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
            await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            async with asyncio.timeout(3):
                while runtime.adapter.jobs:
                    await asyncio.sleep(0.01)
        frames = list(core._engine(core.sessions[sid]).events.frames)
        return core, sid, said, frames
    finally:
        await socket.close()
        await runtime.close()
        await client.aclose()


def voc33_no_speech_before_gates(tmp_path):
    """A draft with an unchecked number is rejected and regenerated: no byte of it reaches the sidecar, and the
    accepted text is all that is spoken."""
    rejected = "The height is 12 m. What quantity does the question ask you to find?"

    async def scenario():
        _, _, said, frames = await spoken_turn(tmp_path, [tutor(rejected), tutor(SAFE)])
        assert said == SAFE
        assert "12" not in said and "twelve" not in said
        shown = "".join(f["event"].get("delta", "") for f in frames if f["event"]["type"] == "text.delta")
        assert "12 m" not in shown

    asyncio.run(scenario())


def voc33_release_after_all_gates(tmp_path):
    """The first content byte to the sidecar is sent only after the trace holds the outcome of every gate of the
    accepted candidate; only keep-alives (and the VOC-12 filler) precede it."""
    from agent_core.contracts.voice.engine_llm_adapter import Request as AdapterRequest

    async def scenario():
        _, _, runtime, socket, _, client, instructions = await setup_adapter(
            tmp_path, replies=[{"stall_s": 0.05, **tutor(SAFE)}]
        )
        runtime.adapter.keep_alive_s = 0.01
        stream = runtime.adapter.stream(AdapterRequest.model_validate(body(instructions)))
        try:
            async for line in stream:
                if not line.startswith("data: {"):
                    continue
                content = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                if not content:
                    continue
                job = next(iter(runtime.adapter.jobs.values()))
                assert job.turn.result is not None and job.turn.result.status == "complete"
                gates = [g for record in job.turn.traces for g in record["gates"]]
                assert gates and all(g["outcome"] for g in gates)
                assert content == SAFE.split("?")[0] + "?" or SAFE.startswith(content)
                break
        finally:
            await stream.aclose()
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())


def voc20_spoken_form_gated(tmp_path):
    """Distress yields only the keyed template, spoken exactly as displayed; an ordinary turn speaks only the
    verbaliser's reading of what the screen shows."""

    async def scenario():
        _, _, said, frames = await spoken_turn(tmp_path / "distress", [tutor(SAFE)], DISTRESS)
        shown = "".join(f["event"].get("delta", "") for f in frames if f["event"]["type"] == "text.delta")
        assert said == verbalise(shown).text and "adult you trust" in said
        _, _, said, frames = await spoken_turn(tmp_path / "ordinary", [tutor(SAFE)])
        shown = "".join(f["event"].get("delta", "") for f in frames if f["event"]["type"] == "text.delta")
        assert said == verbalise(shown).text

    asyncio.run(scenario())


def voc07_no_latex_spoken(tmp_path):
    """A turn written with LaTeX and markdown and no spoken form reaches the sidecar as plain words."""
    written = r"**Look**: what does $\frac{1}{2} m v^2$ give when $v_0 = 0$? Use `KE`."

    async def scenario():
        _, _, said, _ = await spoken_turn(tmp_path, [tutor(written, say_spoken=None)] * 6, play=False)
        assert said and not FORBIDDEN.search(said), said

    asyncio.run(scenario())


def voc07_spoken_claim_binding():
    """A spoken claim is bound to its check record like displayed text: a changed operator or result is rejected
    before anything reaches the sidecar; a matching spoken claim is accepted (AGT-10)."""
    state = SessionState("ses_01JZ0000000000000000000B05", subject="mathematics")
    state.problem = Problem("prb_v", "Work out 2 + 2.", "prb_v#statement")
    state.plan = Plan([PlanStep(1, "2 + 2 = 4", "4", None, "chk_V")], "4", None, "chk_V", "", "4")
    state.check_values["chk_V"] = [Fraction(4)]
    state.solved = True
    assert claim_problems({"say_spoken": "two plus two is four"}, state) == []
    assert claim_problems({"say_spoken": "two minus two is four"}, state)
    assert claim_problems({"say_spoken": "two times two is five"}, state)


def voc38_function_call_rejected():
    """A stray Realtime function call is answered with an error output, never executed, logged as an anomaly, and
    the next turn proceeds."""
    bridge = ready()
    created(bridge)
    effects = bridge.server(
        event(
            "response.function_call_arguments.done",
            response_id="resp_1",
            item_id="out",
            output_index=0,
            call_id="call_1",
            name="mark_answer",
            arguments="{}",
        ),
        0,
    )
    assert effects.upstream == [
        {
            "type": "conversation.item.create",
            "item": {"type": "function_call_output", "call_id": "call_1", "output": '{"error":"not_supported"}'},
        }
    ]
    assert effects.diagnostics == ["function_call_rejected"] and not effects.actions
    assert "mark_answer" not in json.dumps(effects.upstream)
    bridge.server(event("response.done", response={"id": "resp_1", "status": "completed"}), 0)
    assert bridge.begin_provisional("trn_01JZ0000000000000000000002")


def voc37_reasoning_off(tmp_path):
    """Voice turns run the Coach with reasoning off: the trace shows no reasoning tokens."""

    async def scenario():
        core, sid, _, frames = await spoken_turn(tmp_path, [tutor(SAFE)])
        assert not [f for f in frames if f["event"]["type"] == "reasoning.delta"]
        records = [r for r in core._engine(core.sessions[sid]).traces if r.get("turn_source") == "voice"]
        assert records
        calls = [call for record in records for call in record.get("calls", []) if call.get("role") == "coach"]
        assert all(not call.get("reasoning_tokens") for call in calls)

    asyncio.run(scenario())


def voc41_voice_events_valid(tmp_path):
    """Every voice event a recorded voice turn publishes validates against the event schema."""

    async def scenario():
        _, _, _, frames = await spoken_turn(tmp_path, [tutor(SAFE)])
        voice = [f for f in frames if f["event"]["type"].startswith("voice.")]
        assert {f["event"]["type"] for f in voice} >= {"voice.state"}
        for frame in voice:
            assert errors("api/events", frame) == [], frame["event"]

    asyncio.run(scenario())


def api38_voice_events_schema():
    """The bridge's recorded states and captions validate against ev_voice_state and ev_voice_caption, and the
    states it can publish are exactly the states of VOC-04."""
    schema = json.loads(
        (REPO_ROOT / "services/agent-core/agent_core/contracts/schemas/api/events.schema.json").read_text()
    )
    states = set(schema["$defs"]["ev_voice_state"]["properties"]["state"]["enum"])
    assert states == {"idle", "listening", "thinking", "speaking", "interrupted", "unavailable"}
    bridge = ready(snapshots=True)
    events = []
    for effects in (
        bridge.control({"type": "ptt", "pressed": True}),
        bridge.server(event("input_audio_buffer.speech_started", item_id="in_1", audio_start_ms=0), 0),
        bridge.server(
            event(
                "conversation.item.input_audio_transcription.delta", item_id="in_1", content_index=0, delta="what is"
            ),
            0,
        ),
        bridge.server(
            event(
                "conversation.item.input_audio_transcription.completed",
                item_id="in_1",
                content_index=0,
                transcript="what is speed",
                usage={},
            ),
            0,
        ),
        bridge.server(event("input_audio_buffer.speech_stopped", item_id="in_1", audio_end_ms=100), 100),
        bridge.tick(800),
    ):
        events.extend(effects.events)
    created(bridge)
    events.extend(bridge.server(audio(), 900).events)
    events.extend(bridge.control({"type": "playback", "response_id": "resp_1", "played_ms": 50, "ended": False}).events)
    events.extend(bridge.control({"type": "stop"}).events)
    events.extend(bridge.server(event("error", error={"type": "server_error", "message": "x"}), 1000).events)
    kinds = {e["type"] for e in events}
    assert kinds == {"voice.state", "voice.caption"}
    for e in events:
        definition = "ev_voice_state" if e["type"] == "voice.state" else "ev_voice_caption"
        assert errors(f"api/events#/$defs/{definition}", e) == [], e
    assert {e["state"] for e in events if e["type"] == "voice.state"} <= states


def _audio_files(root):
    found = []
    for path in root.rglob("*"):
        if path.is_file():
            data = path.read_bytes()
            if (
                path.suffix.lower() in (".wav", ".pcm", ".mp3", ".ogg", ".webm", ".flac", ".opus")
                or data[:4] == b"RIFF"
                or b"\x01\x02" * 64 in data  # the microphone frames the test sent
            ):
                found.append(path)
    return found


def voc15_no_audio_persisted(tmp_path):
    """After a voice turn with microphone audio, read-aloud and dictation, no audio exists anywhere on disk."""

    async def scenario():
        core, _, runtime, socket, endpoint, client, instructions = await setup_adapter(tmp_path)
        try:
            response = await client.post("/v1/voice/llm/chat/completions", headers=HEADERS, json=body(instructions))
            assert contents(response) == SAFE
            await endpoint.incoming.put(audio())
            assert "bytes" in await socket.receive()
            await endpoint.incoming.put(event("response.done", response={"id": "resp_1", "status": "completed"}))
            await socket.send({"type": "playback", "response_id": "resp_1", "played_ms": 100, "ended": True})
            async with asyncio.timeout(3):
                while runtime.adapter.jobs:
                    await asyncio.sleep(0.01)
            await socket.send({"type": "ptt", "pressed": True})  # the student speaks: frames reach the endpoint
            for _ in range(5):
                await socket.incoming.put({"type": "websocket.receive", "bytes": b"\x01\x02" * 2400})
            async with asyncio.timeout(2):
                appended = 0
                while appended < 5:
                    frame = await endpoint.sent.get()
                    appended += frame["type"] == "input_audio_buffer.append"
            await socket.send({"type": "ptt", "pressed": False})
            await asyncio.sleep(0.05)
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()
        return core

    asyncio.run(scenario())
    assert _audio_files(tmp_path) == []
    assert not any(b"\x01\x02" * 64 in p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())


def prv26_no_audio_stored(tmp_path):
    """No audio file, recording or raw PCM is ever written into the app data folder by a voice session."""
    voc15_no_audio_persisted(tmp_path)
    assert not [
        p for p in tmp_path.rglob("*") if "attachment" in p.name and _audio_files(p if p.is_dir() else p.parent)
    ]


@pytest.mark.parametrize(
    "address",
    ["ws://203.0.113.5:9000/v1/realtime", "ws://localhost:9000/v1/realtime", "wss://voice.example.invalid/v1/realtime"],
)
def prv26_no_audio_egress_by_default(address):
    """With cloud voice off the only voice endpoint is a literal loopback one, and the sidecar refuses any other
    connection or name lookup (VOC-15, VOC-23)."""
    from agent_core.net.voice import LocalVoiceEndpoint, VoiceTransportError
    from agent_core.net.voice_sidecar import allow_connection

    with pytest.raises(VoiceTransportError):
        LocalVoiceEndpoint(address, "synthetic_" + "t" * 32)
    assert LocalVoiceEndpoint("ws://127.0.0.1:9000/v1/realtime", "synthetic_" + "t" * 32)
    assert not allow_connection(("203.0.113.5", 443)) and not allow_connection("voice.example.invalid")
    assert allow_connection(("127.0.0.1", 9000))


@pytest.mark.parametrize(
    "component", ["gpl_licence", "unknown_licence", "espeak_library", "phonemizer", "mms_tts", "livekit"]
)
def voc02_licence_gate(tmp_path, component):
    """An excluded or unlicensed component, or a bundle carrying libespeak-ng, never installs."""
    from agent_core.config.environments import Environment
    from agent_core.store.speech_packs import SpeechPackError, SpeechPackStore
    from signing_service.hierarchy import dev_trust
    from test_m32_speech_packs import pack, signed

    source = tmp_path / "usb"
    document = pack(source)
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    first = unsigned["files"][4]  # the sidecar bundle entry
    if component == "gpl_licence":
        first["licence"]["spdx"] = "GPL-3.0-only"
    elif component == "unknown_licence":
        first["licence"]["spdx"] = "LicenseRef-unknown"
    else:
        name = {
            "espeak_library": "sidecar/libespeak-ng.so.1",
            "phonemizer": "sidecar/phonemizer/__init__.py",
            "mms_tts": "tts/mms-tts-eng.bin",
            "livekit": "turn/livekit_turn_detector.onnx",
        }[component]
        payload = b"excluded"
        (source / name).parent.mkdir(parents=True, exist_ok=True)
        (source / name).write_bytes(payload)
        import hashlib

        unsigned["files"].append(
            {**first, "path": name, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}
        )
    signed(source, unsigned)
    store = SpeechPackStore(tmp_path / "installed", Environment.DEV, "linux-x86_64", "0.0.0", "mid", trust=dev_trust)
    with pytest.raises(SpeechPackError, match=r"licence_refused|component_refused"):
        store.install(source)
    assert not (tmp_path / "installed").exists()
