"""M31 named tests closed without a device (G116): licences shown, the client's network and engines, the speech
release gate against the answer-seeker persona, spoken forms of templates and rungs, and dictated notes."""

import ast
import asyncio
import copy
import json
import re
import shutil
import typing
from pathlib import Path
from typing import Any

import pytest
from agent_core.config.environments import Environment
from agent_core.store.model_packs import ATTRIBUTION_LICENCES
from agent_core.store.speech_packs import SpeechPackStore
from api_harness import stop_core
from jana_tools import REPO_ROOT
from jana_tools.bundle_scan import client_network_errors
from signing_service.hierarchy import dev_trust
from test_m20b_packs import _core, run
from test_m32_speech_packs import pack, signed

CC_BY_ATTRIBUTION = "Synthetic speech-to-text weights, CC-BY-4.0, for this test only; credit to the synthetic authors."


def _cc_by_pack(folder: Path) -> None:
    """The fixture pack with a CC-BY speech-to-text component (as Parakeet-TDT is in TABLE VOC-02a)."""
    document = pack(folder)
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    stt = next(f for f in unsigned["files"] if f["role"] == "stt")
    stt["engine"] = "parakeet-tdt"
    stt["licence"] = {
        "spdx": "CC-BY-4.0",
        "source_url": "https://example.invalid/stt",
        "attribution": CC_BY_ATTRIBUTION,
    }
    for profile in unsigned["profiles"].values():
        profile["stt"] = "parakeet-tdt"
    signed(folder, unsigned)


def voc02_attributions_shown(tmp_path: Path) -> None:
    """Every CC-BY component of the installed speech pack reaches the data Settings → About → Licences reads
    (`GET /v1/models`), with its attribution; the model manager's rows are untouched."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path)
        try:
            desk.speech = SpeechPackStore(
                tmp_path / "data" / "speech-packs", Environment.DEV, "linux-x86_64", "0.0.0", "mid", trust=dev_trust()
            )
            _cc_by_pack(tmp_path / "usb")
            desk.speech.install(tmp_path / "usb")
            reply = await r.get("/v1/models")
            assert reply.status_code == 200, reply.text
            rows = [row for row in reply.json()["installed"] if row.get("kind") == "speech_pack"]
            assert [row["speech_pack_id"] for row in rows] == ["sp.en.1_0"]
            attributed = [c for c in rows[0]["licences"] if c["spdx"] in ATTRIBUTION_LICENCES]
            assert attributed and all(c["attribution"] for c in attributed)
            assert {c["attribution"] for c in attributed} == {CC_BY_ATTRIBUTION}
            assert CC_BY_ATTRIBUTION in rows[0]["attributions"]
            # Every component the class runs is listed, so nothing shipped lacks its record (VOC-02).
            assert {c["path"] for c in rows[0]["licences"]} == {
                f["path"] for f in desk.speech.licences(desk.speech.root / "sp.en.1_0")
            }
        finally:
            await stop_core(r)

    run(scenario())


# --- VOC-01: the UI talks only to the core; only the standard engines, and nothing trains -----------------------


def voc01_ui_talks_only_to_core(tmp_path: Path) -> None:
    """The client opens connections only through the core client (whose voice socket refuses any non-loopback
    origin), never uses the webview's speech recognition, takes only installed OS voices, names no speech endpoint,
    and the desktop's content security policy lets the webview connect only to the core's loopback origin. Each rule
    is proven by a seeded violation."""
    assert client_network_errors(REPO_ROOT) == []
    voice = (REPO_ROOT / "packages/client-core/src/voice.ts").read_text()
    assert "voice_core_origin_required" in voice and '["127.0.0.1", "[::1]"]' in voice

    root = tmp_path / "repo"
    for rel in ("packages/client-core/src", "packages/ui/src", "apps/desktop/src", "apps/desktop/src-tauri"):
        shutil.copytree(REPO_ROOT / rel, root / rel, ignore=shutil.ignore_patterns("node_modules", "target", "gen"))
    (root / "packages/ui/src/direct.ts").write_text(
        'const socket = new WebSocket("ws://127.0.0.1:8765/v1/realtime");\n'
    )
    (root / "apps/desktop/src/listen.ts").write_text("const heard = new webkitSpeechRecognition();\n")
    (root / "apps/desktop/src/cloud.ts").write_text('await fetch("https://api.elevenlabs.io/v1/text-to-speech");\n')
    (root / "packages/ui/src/voices.ts").write_text("const all = speechSynthesis.getVoices();\n")
    config = root / "apps/desktop/src-tauri/tauri.conf.json"
    document = json.loads(config.read_text())
    document["app"]["security"]["csp"]["connect-src"] += " https://voice.example.invalid"
    config.write_text(json.dumps(document))
    found = client_network_errors(root)
    assert any("packages/ui/src/direct.ts:1: opens a network connection" in e for e in found)
    assert any("packages/ui/src/direct.ts:1: names a speech endpoint (/v1/realtime)" in e for e in found)
    assert any("apps/desktop/src/listen.ts:1: uses the webview's speech recognition" in e for e in found)
    assert any("apps/desktop/src/cloud.ts:1: opens a network connection" in e for e in found)
    assert any("apps/desktop/src/cloud.ts:1: names a speech endpoint (api.elevenlabs.io)" in e for e in found)
    assert any("packages/ui/src/voices.ts: chooses OS synthesiser voices" in e for e in found)
    assert any("connect-src allows more than the core: ['https://voice.example.invalid']" in e for e in found)


# The standard engines of TABLE VOC-02a by role (the S4 candidate Qwen3-ASR is not shipped in S3).
STANDARD_ENGINES = {
    "vad": {"silero"},
    "turn": {"smart-turn"},
    "stt": {"faster-whisper", "parakeet-tdt"},
    "tts": {"qwen3", "kokoro", "pocket"},
    "sidecar": {"speech-to-speech"},
    "wake": {"sherpa-kws"},  # the wake-word detector (VOC-49, D103): sherpa-onnx keyword spotting, TABLE VOC-02a
}
# Any of these in voice code would be a training, fine-tuning, adaptation or cloning path (D56, D80).
TRAINING_NAMES = {
    "train", "backward", "zero_grad", "optimizer", "optim", "Trainer", "TrainingArguments", "peft", "lora",
    "LoraConfig", "finetune", "fine_tune", "trl", "accelerate", "deepspeed", "adapt", "enroll", "enrol", "clone_voice",
}  # fmt: skip
VOICE_CODE = (
    "services/agent-core/agent_core/net/voice.py",
    "services/agent-core/agent_core/net/voice_launch.py",
    "services/agent-core/agent_core/net/voice_sidecar.py",
    "services/agent-core/agent_core/engine/voice_bindings.py",
    "services/agent-core/agent_core/engine/voice_bridge.py",
    "services/agent-core/agent_core/engine/voice_dictation.py",
    "services/agent-core/agent_core/engine/voice_turn.py",
    "services/agent-core/agent_core/engine/verbaliser.py",
    "services/agent-core/agent_core/store/speech_packs.py",
    "services/agent-core/agent_core/api/voice.py",
    "services/agent-core/agent_core/api/voice_activities.py",
    "services/agent-core/agent_core/api/voice_adapter.py",
    "scripts/packaging/voice-sidecar.spec",
)


def _names(source: str) -> set[str]:
    tree = ast.parse(source)
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name):
            found.add(node.id)
        elif isinstance(node, ast.Attribute):
            found.add(node.attr)
        elif isinstance(node, ast.Import):
            found.update(part for alias in node.names for part in alias.name.split("."))
        elif isinstance(node, ast.ImportFrom):
            found.update((node.module or "").split("."))
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and re.fullmatch(r"[\w.]+", node.value):
            found.update(node.value.split("."))  # importlib.import_module("...") names
    return found


def voc01_standard_engines_only(tmp_path: Path) -> None:
    """A speech pack and the sidecar can name only the standard engines of TABLE VOC-02a, with fixed launch options
    and no cloning; a manifest naming any other engine never installs; and no voice code path trains, fine-tunes or
    adapts a speech model."""
    from agent_core.net.voice_sidecar import LOCAL_TTS_LOADERS, argument_values
    from agent_core.store import speech_packs
    from agent_core.store.speech_packs import ENGINES, SpeechPackError, SpeechProfile
    from test_m32_sidecar_launcher import launch

    assert ENGINES == STANDARD_ENGINES
    # `none` is no engine: a read-aloud-only profile runs no speech-to-text at all (TABLE VOC-03a).
    assert set(typing.get_args(SpeechProfile.model_fields["stt"].annotation)) - {"none"} <= STANDARD_ENGINES["stt"]
    assert set(typing.get_args(SpeechProfile.model_fields["tts"].annotation)) <= STANDARD_ENGINES["tts"]
    assert LOCAL_TTS_LOADERS <= STANDARD_ENGINES["tts"]
    for stt in sorted(STANDARD_ENGINES["stt"]):
        profile = SpeechProfile.model_validate(
            {"stt": stt, "tts": "qwen3", "device": "cpu", "vad_path": "vad", "turn_path": "turn/model.onnx",
             "stt_path": "stt", "tts_path": "tts", "sidecar_path": "sidecar/jana-voice", "speaker": "Aiden"}
        )  # fmt: skip
        values = argument_values(launch(hardware="mid"), profile)
        assert values["module"]["stt"] in STANDARD_ENGINES["stt"] and values["module"]["tts"] in STANDARD_ENGINES["tts"]
        assert values["vad"]["vad"] == "silero"
        assert values["tts"]["qwen3_tts_ref_audio"] is None and values["tts"]["qwen3_tts_ref_spk"] is None
        model_paths = [v for stage in values.values() for k, v in stage.items() if k.endswith(("_model_name", "_path"))]
        assert all(str(v).startswith(str(launch(hardware="mid").pack_dir)) for v in model_paths if v), model_paths

    for role, engine in (("stt", "whisper-finetuned"), ("tts", "xtts-clone"), ("vad", "webrtc"), ("tts", "mms-tts")):
        source = tmp_path / f"{role}-{engine}"
        document = pack(source)
        unsigned = {k: v for k, v in document.items() if k != "signature"}
        next(f for f in unsigned["files"] if f["role"] == role)["engine"] = engine
        signed(source, unsigned)
        store = SpeechPackStore(tmp_path / "installed", Environment.DEV, "linux-x86_64", "0.0.0", "mid",
                                trust=dev_trust())  # fmt: skip
        with pytest.raises(SpeechPackError, match="speech_pack_licence_refused"):
            store.install(source)

    seeded = "import peft\nfrom torch import optim\nmodel.train()\nloss.backward()\n"
    assert _names(seeded) & TRAINING_NAMES == {"peft", "optim", "train", "backward"}
    for rel in VOICE_CODE:
        text = (REPO_ROOT / rel).read_text()
        names = _names(text)
        assert not names & TRAINING_NAMES, (rel, sorted(names & TRAINING_NAMES))
    spec = (REPO_ROOT / "scripts/packaging/voice-sidecar.spec").read_text()
    handlers = set(re.findall(r"speech_to_speech\.(?:STT|TTS|VAD)\.(\w+)", spec))
    assert handlers == {"faster_whisper_handler", "parakeet_tdt_handler", "qwen3_tts_handler", "vad_handler"}
    assert speech_packs.EXCLUDED.search("libespeak-ng.so") and speech_packs.EXCLUDED.search("phonemizer")


# --- VOC-33: no withheld answer reaches any speech engine in the answer-seeker voice suite -------------------------

# Candidate Coach replies that each leak the withheld answer (h = 10 m) in one form; the release gate must reject every
# one before a byte reaches the sidecar. The final reply is safe.
LEAKS = (
    {"say": "The height is 10 m."},
    {"say": "It comes out as ten metres."},
    {"say": r"So $h = 10\,\text{m}$ is the result."},
    {"say": "What quantity does the question ask you to find?", "say_spoken": "The answer is ten metres."},
    {"say": "Nearly there: it is 10.", "say_spoken": "Nearly there: it is ten."},
)
WITHHELD = re.compile(r"\b(?:10|ten)\b", re.IGNORECASE)


def voc33_no_leak_to_tts(tmp_path: Path) -> None:
    """Each line of the scripted answer-seeker persona is spoken as a voice turn whose Coach first tries leaking forms
    of the withheld answer (digits, words, LaTeX, a spoken form that says more than the screen). While the answer is
    withheld, no form of it reaches the sidecar, and none is in the text read aloud (the OS synthesiser's input).

    A line that asks outright for the answer switches the session to the worked solution at once (D87); the withheld
    set is then empty by PED-08, so that turn may state the answer, yet it speaks no more than the screen shows."""
    from agent_core.engine.verbaliser import verbalise
    from engine_harness import tutor
    from jana_tools.harness.personas import PERSONAS
    from test_m32_provisional import SAFE
    from test_m32_voice_named import spoken_turn

    lines = PERSONAS["answer_seeker"]
    assert len(lines) >= 4

    async def scenario() -> int:
        guarded = 0
        for index, line in enumerate(lines):
            order = LEAKS[index % len(LEAKS) :] + LEAKS[: index % len(LEAKS)]
            replies = [tutor(**leak) for leak in order] + [tutor(SAFE)]
            core, sid, said, frames = await spoken_turn(tmp_path / f"turn{index}", replies, line)
            state = core.sessions[sid].engine_state
            shown = "".join(f["event"].get("delta", "") for f in frames if f["event"]["type"] == "text.delta")
            assert said and said == verbalise(shown).text, (line, said, shown)
            if state.mode == "solution":  # D87: the student asked for the solution; nothing is withheld now
                assert state.withheld() == []
                continue
            guarded += 1
            assert {value for value, _ in state.withheld()} == {10}, "the answer stays withheld"
            assert not WITHHELD.search(said), (line, said)
            assert not WITHHELD.search(shown), (line, shown)
        return guarded

    assert asyncio.run(scenario()) >= 3, "most answer-seeker lines press without asking outright"


# --- PED-26: keyed spoken forms of templates and rungs; stopping read-aloud changes nothing ------------------------

TEMPLATES = REPO_ROOT / "content" / "agent" / "templates" / "en.yaml"
SAFETY_VALUES = {"emergency_number": "999", "child_helpline": "the helpline on 0800 1111"}  # synthetic values


def ped26_spoken_forms(tmp_path: Path) -> None:
    """Every template and every rung's canned hint has a spoken form that passes the VOC-07 no-LaTeX check and reads
    the same through the VOC-08 verbaliser (its conventions are already applied); safety numbers are read digit by
    digit. Voice speaks a template from its keyed form, with no model call, and a canned rung from its spoken form."""
    from agent_core.engine.pedagogy import Templates
    from agent_core.engine.verbaliser import verbalise
    from engine_harness import tutor
    from test_m32_voice_named import FORBIDDEN

    for templates in (Templates.load(TEMPLATES), Templates.load(TEMPLATES).with_verified(SAFETY_VALUES)):
        forms = [templates.spoken(t) for t in templates.texts] + [templates.spoken_hint(r) for r in templates.hints]
        assert len(forms) == len(templates.texts) + 5
        for form in forms:
            assert form and not FORBIDDEN.search(form), form
            again = verbalise(form)
            assert again.text == form and not again.fallbacks, form
            assert not re.search(r"\d", form), form
    distress = Templates.load(TEMPLATES).with_verified(SAFETY_VALUES)
    assert "call nine nine nine" in distress.spoken("tpl.distress")
    assert "zero eight zero zero one one one one" in distress.spoken("tpl.distress")
    assert "999" in distress.render("tpl.distress")  # the screen keeps the number as written

    async def scenario() -> None:
        from dataclasses import replace

        from agent_core.engine.voice_turn import ProvisionalVoiceTurn
        from test_m32_provisional import SAFE, prepared
        from test_m32_voice_named import DISTRESS

        live, factory = await prepared(tmp_path, [tutor(SAFE)])

        def with_safety(state: Any) -> Any:
            engine = factory(state)
            engine.deps = replace(engine.deps, templates=engine.deps.templates.with_verified(SAFETY_VALUES))
            return engine

        provisional = ProvisionalVoiceTurn(live, with_safety, DISTRESS)
        await provisional.evaluate()
        assert provisional.result is not None and provisional.result.tutor_turn is None, "a template, not the Coach"
        assert "nine nine nine" in provisional.spoken_text and "999" not in provisional.spoken_text
        assert provisional.spoken_text == distress.spoken("tpl.distress")
        await provisional.discard()

        engine = factory(live.state)
        engine.state.rung = 3
        assert engine._canned()["say_spoken"] is None, "outside voice say_spoken stays null"
        engine.voice_mode = True
        assert engine._canned()["say_spoken"] == engine.deps.templates.spoken_hint(3)

    asyncio.run(scenario())


RUNG_FOUR = "Here is this step in full. Look at the worked step on the board, then try the next one yourself."
RUNG_FOUR_STEP = {"op": "add_step", "step": None, "latex": r"h = 10\,\text{m}", "reason": "the current step at rung 4"}
RUNG_FOUR_BOARD = [{**RUNG_FOUR_STEP, "owner": "tutor", "status": "final", "terms": [], "prompt": None,
                    "check_id": "chk_test"}]  # fmt: skip


def ped26_stop_keeps_accepted_turn(tmp_path: Path) -> None:
    """Reading a rung 4 reply aloud and stopping it part-way leaves the accepted turn's board, hint rung and learning
    events exactly as they were (read-aloud is an engine-owned utterance, never a turn)."""
    from agent_core.engine.events import new_id
    from agent_core.engine.state import state_to_json
    from engine_harness import tutor
    from test_m31_voice_activities import headers
    from test_m31_voice_bridge import audio, event
    from test_m32_adapter import setup_adapter

    async def scenario() -> None:
        replies = [tutor(RUNG_FOUR, hint_rung=4, board=RUNG_FOUR_BOARD, reveals="current_step")]
        core, sid, runtime, socket, endpoint, client, _ = await setup_adapter(
            tmp_path, replies=replies, early_response=False
        )
        learned: list[Any] = []
        core._engine(core.sessions[sid]).learning = learned.extend
        prior = core.sessions[sid].engine_state  # one attempt and rung 3 on this step: "I'm stuck" asks for rung 4
        prior.attempts, prior.hint_step, prior.rung = {prior.step: 1}, prior.step, 3
        try:
            stuck = {"type": "text", "text": "I'm stuck, can you show me this step?"}
            core.start_turn(sid, {"client_message_id": new_id("cli"), "intent": "stuck", "content": [stuck]})
            await core.sessions[sid].task
            parts = core.sessions[sid].state["parts"].values()
            part_id = next(p["part_id"] for p in parts if p["kind"] == "text" and p["status"] == "complete")
            state = core.sessions[sid].engine_state
            assert state.rung == 4 and any(s.check_id == "chk_test" for s in state.board.steps), "rung 4 on the board"
            before, events, board = state_to_json(state), list(learned), copy.deepcopy(state.board)
            hints = [e.payload for e in events if getattr(e, "type", None) == "hint"]
            assert hints and hints[-1]["rung"] == 4, "the accepted turn recorded its rung 4 hint"
            response = await client.post(
                f"/v1/sessions/{sid}/voice/utterances",
                headers=headers(),
                json={"type": "read_aloud", "part_id": part_id},
            )
            assert response.status_code == 200, response.text
            utterance = response.json()
            await socket.send({"type": "speak", "utterance_id": utterance["utterance_id"]})
            assert (await asyncio.wait_for(endpoint.sent.get(), 2))["type"] == "conversation.item.create"
            assert (await endpoint.sent.get())["type"] == "response.create"
            await endpoint.incoming.put(event("response.created", response={"id": "resp_read"}))
            await endpoint.incoming.put(audio("resp_read"))
            assert "bytes" in await socket.receive()
            await socket.send({"type": "playback", "response_id": "resp_read", "played_ms": 300, "ended": False})
            await socket.send({"type": "stop"})
            assert json.loads((await socket.receive())["text"])["utterance_id"] == utterance["utterance_id"]
            assert (await endpoint.sent.get())["type"] == "response.cancel"
            await asyncio.sleep(0.05)
            state = core.sessions[sid].engine_state
            assert state.board == board and state.rung == 4
            assert learned == events and state_to_json(state) == before
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())
