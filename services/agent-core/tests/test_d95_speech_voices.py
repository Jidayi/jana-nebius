"""D95: the pack's own voices for read-aloud, the LGPL rule of the licence gate and the read-aloud-only profile.

Synthetic bytes and a stand-in engine only: no speech weights load here. The real voices are exercised by the pack
build's end-to-end check on a device (scripts/packaging/speech_pack_e2e.py)."""

import asyncio
import base64
import hashlib
import json
import sys
import types

import pytest
from agent_core.config.environments import Environment
from agent_core.contracts import errors
from agent_core.net.voice import LocalVoiceEndpoint, VoiceTransportError
from agent_core.net.voice_launch import memory_budget
from agent_core.net.voice_speech import SpeakServer, speech_units
from agent_core.store.speech_packs import SpeechPackError, SpeechPackStore, licence_use
from signing_service.hierarchy import dev_trust
from test_m31_voice_activities import accepted, headers
from test_m32_adapter import contents, setup_adapter
from test_m32_speech_pack_trust import link_for
from test_m32_speech_packs import pack, signed

LGPL = "LGPL-2.1-or-later"
LIBRARY = "https://pypi.org/project/num2words/0.5.14/"


def with_files(folder, document, extra):
    """`document` (unsigned) plus synthetic runtime files [(path, spdx, source, role)], re-signed."""
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    for path, spdx, source, role in extra:
        payload = ("synthetic " + path).encode()
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(payload)
        unsigned["files"].append(
            {
                "path": path,
                "role": role,
                "engine": "speech-to-speech" if role == "sidecar" else "qwen3",
                "classes": ["mid", "high"],
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "licence": {"spdx": spdx, "source_url": source, "attribution": "Synthetic runtime library."},
            }
        )
    return signed(folder, unsigned)


SEPARATE = [
    ("sidecar/site/num2words/__init__.py", LGPL, LIBRARY, "sidecar"),
    ("sidecar/site/num2words/lang_EN.py", LGPL, LIBRARY, "sidecar"),
    ("sidecar/site/num2words-0.5.14.dist-info/COPYING", LGPL, LIBRARY, "sidecar"),
]


@pytest.mark.parametrize(
    "case", ["separate", "as_model", "mixed_folder", "no_licence_text", "beside_entry_point", "gpl", "agpl"]
)
def voc02_lgpl_separate_library(tmp_path, case):
    """D95: an LGPL library ships in a speech pack only as a separate library, a folder of its own with its licence
    text, in the runtime and never as a model or the entry point; GPL and AGPL stay refused everywhere."""
    source = tmp_path / "usb"
    document = pack(source)
    extra = list(SEPARATE)
    if case == "as_model":
        extra = [(p, s, u, "tts") for p, s, u, _ in extra]
    elif case == "mixed_folder":
        extra.append(("sidecar/site/num2words/helper.py", "MIT", "https://pypi.org/project/helper/1.0/", "sidecar"))
    elif case == "no_licence_text":
        extra = extra[:2]
    elif case == "beside_entry_point":
        extra = [("sidecar/lgpl_module.py", LGPL, LIBRARY, "sidecar"), ("sidecar/COPYING", LGPL, LIBRARY, "sidecar")]
    elif case in ("gpl", "agpl"):
        spdx = "GPL-2.0-or-later" if case == "gpl" else "AGPL-3.0-only"
        extra = [(p, spdx, u, r) for p, _, u, r in extra]
    with_files(source, document, extra)
    store = SpeechPackStore(tmp_path / "installed", Environment.DEV, "linux-x86_64", "0.0.0", "mid", trust=dev_trust)
    if case == "separate":
        installed = store.install(source)
        rows = {row["path"]: row for row in store.licences(installed)}
        assert rows["sidecar/site/num2words-0.5.14.dist-info/COPYING"]["spdx"] == LGPL
        return
    with pytest.raises(SpeechPackError, match="licence_refused"):
        store.install(source)
    assert not (tmp_path / "installed").exists() or not list((tmp_path / "installed").glob("sp.en.*"))


def test_licence_use_by_role():
    assert licence_use("MIT", "tts") == "approved" and licence_use("MPL-2.0", "tts") == "refused"
    assert licence_use("MPL-2.0 AND MIT", "sidecar") == "approved"
    assert licence_use("Apache-2.0 AND Apache-2.0 WITH LLVM-exception AND BSL-1.0", "sidecar") == "approved"
    assert licence_use("Apache-2.0 AND CNRI-Python", "sidecar") == "approved"  # regex: the Python licence stack
    assert licence_use("MIT OR LGPL-3.0-only", "sidecar") == "approved"  # the alternative without LGPL wins
    assert licence_use("LGPL-2.1-or-later", "sidecar") == "lgpl" and licence_use(LGPL, "tts") == "refused"
    for refused in ("GPL-3.0-only", "AGPL-3.0-only", "GPL-2.0-or-later WITH Classpath-exception-2.0", "LicenseRef-x"):
        assert licence_use(refused, "sidecar") == "refused"


def read_aloud_pack(folder):
    """A read-aloud-only pack (TABLE VOC-03a `stt: none`): a voice and the sidecar, no VAD, turn or STT model."""
    document = pack(folder)
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    unsigned["files"] = [f for f in unsigned["files"] if f["role"] in ("tts", "sidecar")]
    for name in ("vad", "turn", "stt"):
        for path in (folder / name).rglob("*"):
            path.unlink()
    unsigned["profiles"] = {
        "mid": {
            "stt": "none",
            "tts": "qwen3",
            "device": "cpu",
            "tts_path": "tts",
            "sidecar_path": "sidecar/jana-voice",
            "speaker": "Ryan",
        }
    }
    return signed(folder, unsigned)


def voc03_read_aloud_only_profile(tmp_path):
    """A read-aloud-only profile installs without speech input, offers read-aloud through its voice, and offers no
    dictation and no voice turns (VOC-14, VOC-46); a profile with speech-to-text still needs its VAD."""
    root = tmp_path / "speech-packs"
    root.mkdir()
    read_aloud_pack(root / "sp.en.1_0")
    link = link_for(root, "mid")
    assert link.scan() and link.selected is not None
    assert not link.dictation and not link.tutoring
    document = json.loads((root / "sp.en.1_0" / "manifest.json").read_text())
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    unsigned["profiles"]["mid"]["stt"] = "faster-whisper"  # speech input without its files and paths
    signed(root / "sp.en.1_0", unsigned)
    assert not link_for(root, "mid").scan()


def voc03_memory_budget_uses_the_measured_voice(tmp_path):
    """The voice stack's memory is its measured peak by class, not its file sizes (D95 bake-off, VOC-03)."""
    root = tmp_path / "speech-packs"
    root.mkdir()
    pack(root / "sp.en.1_0")
    gib = 1024**3
    plan = {"attempts": [{"model": "synthetic", "context": 8192, "args": [], "resident_bytes": 10 * gib}]}
    measured = (2.6, 2.6, 5.6)
    roomy = link_for(root, memory_fits=memory_budget(plan, int(14.6 * gib) + 1, 2.0, measured))
    tight = link_for(root, memory_fits=memory_budget(plan, int(14.6 * gib) - gib, 2.0, measured))
    assert roomy.scan() and roomy.tutoring
    assert tight.scan() and not tight.tutoring  # the 2.6 GB voice does not fit; files alone (bytes) would have


@pytest.mark.parametrize(
    ("text", "units"),
    [
        (
            "Every transaction touches at least two accounts: when cash comes in, the total moves. Then check.",
            [
                "Every transaction touches at least two accounts: ",
                "when cash comes in, the total moves. ",
                "Then check.",
            ],
        ),
        ("Yes, that is right.", ["Yes, that is right."]),  # too few words before the first clause
        ("Good start. Before you divide, look again.", ["Good start. ", "Before you divide, look again."]),
        ("Not quite; the units must stay the same", ["Not quite; the units must stay the same"]),
        ("Try writing both fractions - then add.", ["Try writing both fractions - ", "then add."]),
        ("", []),
    ],
)
def voc18_first_unit_ends_at_the_first_clause(text, units):
    """Read-aloud's first unit is the first clause of the first sentence once enough words precede it (D95: first
    audio grows with the first unit on a slow laptop); the units always join back to the exact text."""
    assert speech_units(text, 4) == units
    assert "".join(speech_units(text, 4)) == text
    assert "".join(speech_units(text, 0)) == text


class Recording:
    """A real loopback Realtime socket that also keeps what the bridge sent (the adapter test helper reads it)."""

    def __init__(self, socket):
        self.socket, self.sent = socket, asyncio.Queue()

    async def send(self, frame):
        await self.sent.put(frame)
        await self.socket.send(frame)

    async def receive(self):
        return await self.socket.receive()

    async def close(self):
        await self.socket.close()


class Voice:
    """A stand-in engine: 0.15 s of PCM per unit, recording the units it was given."""

    def __init__(self):
        self.units = []

    def stream(self, text):
        self.units.append(text)
        yield b"\x01\x00" * 3600


def voc18_read_aloud_through_the_pack_voice(tmp_path):
    """Read-aloud with a read-aloud-only pack: the bridge's speak directive reaches the sidecar's speak server over a
    real loopback socket, the adapter answers the owned text verbatim, the voice speaks it unit by unit (first clause
    first), every server frame is in the Realtime contract, and the UI receives the utterance's tagged audio."""
    from websockets.asyncio.server import serve

    async def scenario():
        voice = Voice()
        holder = {}

        async def adapter(instructions, directive):
            response = await holder["client"].post(
                "/v1/voice/llm/chat/completions",
                headers={"authorization": "Bearer adapter-secret"},
                json={
                    "model": "jana-tutor-voice",
                    "stream": True,
                    "reasoning_effort": "none",
                    "messages": [
                        {"role": "system", "content": instructions},
                        {"role": "user", "content": directive},
                    ],
                },
            )
            return contents(response)

        token = "synthetic_" + "r" * 32
        speaker = SpeakServer(voice, adapter, token, first_clause_words=4)
        frames = []

        async def session(websocket):
            original = websocket.send

            async def send(message):
                frames.append(json.loads(message))
                await original(message)

            websocket.send = send
            await speaker.session(websocket)

        def admit(connection, request):
            return None if speaker.authorised(request.path, request.headers) else connection.respond(401, "")

        async with serve(session, "127.0.0.1", 0, process_request=admit) as server:
            port = next(iter(server.sockets)).getsockname()[1]
            url = f"ws://127.0.0.1:{port}/v1/realtime"
            with pytest.raises(VoiceTransportError):  # a wrong token never reaches the speak server
                await LocalVoiceEndpoint(url, "synthetic_" + "w" * 32).open()

            async def connect():
                return Recording(await LocalVoiceEndpoint(url, token).open())

            core, sid, runtime, socket, _, client, _ = await setup_adapter(
                tmp_path, early_response=False, connect_factory=connect
            )
            holder["client"] = client
            try:
                part_id = await accepted(core, sid)
                reply = await client.post(
                    f"/v1/sessions/{sid}/voice/utterances",
                    headers=headers(),
                    json={"type": "read_aloud", "part_id": part_id},
                )
                assert reply.status_code == 200, reply.text
                utterance = reply.json()
                assert utterance["transport"] == "sidecar"
                await socket.send({"type": "speak", "utterance_id": utterance["utterance_id"]})
                tag = hashlib.sha256(utterance["utterance_id"].encode()).digest()[:16]
                audio, expected = b"", len(speech_units(utterance["text"], 4)) * 7200
                async with asyncio.timeout(10):
                    while len(audio) < expected:
                        packet = await socket.receive()
                        if packet.get("bytes"):
                            assert packet["bytes"][:16] == tag
                            audio += packet["bytes"][16:]
                    while not any(f["type"] == "response.done" for f in frames):
                        await asyncio.sleep(0.01)
                assert len(audio) == expected and set(audio) == {0, 1}
                assert "".join(voice.units) == utterance["text"]
                assert voice.units[0] == speech_units(utterance["text"], 4)[0]
                for frame in frames:
                    assert errors("voice/realtime-events", frame) == [], frame["type"]
                done = [f for f in frames if f["type"] == "response.output_audio_transcript.done"]
                assert done[0]["transcript"] == utterance["text"]
                assert frames[-1]["response"]["status"] == "completed"
                assert base64.b64decode(next(f for f in frames if f["type"].endswith("audio.delta"))["delta"])
            finally:
                await socket.close()
                await runtime.close()
                await client.aclose()

    asyncio.run(scenario())


def test_upstream_kokoro_loads_the_pack_files(tmp_path, monkeypatch):
    """For a pack with speech input, upstream's CPU Kokoro handler builds its pipeline from the pack's files at setup
    and at every session end, never `KPipeline(lang_code, device)` from the hub (D95)."""
    from agent_core.net import voice_sidecar
    from agent_core.store.speech_packs import SpeechProfile

    class Handler:
        def _setup_kokoro(self):
            raise AssertionError("upstream loader must be replaced")

        def on_session_end(self):
            raise AssertionError("upstream reload must be replaced")

    module = types.ModuleType("speech_to_speech.TTS.kokoro_handler")
    module.KokoroTTSHandler = Handler
    monkeypatch.setitem(sys.modules, "speech_to_speech.TTS.kokoro_handler", module)
    built = []

    class Engine:
        def __init__(self, model_dir, speaker):
            built.append((model_dir, speaker))
            self.pipeline = "local pipeline"

    monkeypatch.setattr("agent_core.net.voice_speech.KokoroEngine", Engine)
    profile = SpeechProfile.model_validate(
        {"stt": "faster-whisper", "tts": "kokoro", "device": "cpu", "vad_path": "vad", "turn_path": None,
         "stt_path": "stt", "tts_path": "tts", "sidecar_path": "sidecar/jana-voice", "speaker": "af_heart"}
    )  # fmt: skip
    voice_sidecar.local_kokoro(tmp_path, profile)
    handler = Handler()
    handler._initial_voice, handler._initial_lang_code = "/pack/tts/voices/af_heart.pt", "a"
    handler.voice, handler.lang_code = "other", "b"
    handler._setup_kokoro()
    handler._setup_kokoro()
    handler.on_session_end()
    assert handler.pipeline == "local pipeline" and built == [(tmp_path / "tts", "af_heart")]
    assert (handler.voice, handler.lang_code) == ("/pack/tts/voices/af_heart.pt", "a")


def voc46_read_aloud_only_pack_offers_no_dictation(tmp_path):
    """With a read-aloud-only pack the core says `voice` but neither `voice_dictation` nor `voice_tutoring`, and a
    dictation request is refused before any capture or binding exists (VOC-14, VOC-46)."""
    from agent_core.engine.events import new_id

    async def scenario():
        core, sid, runtime, socket, _, client, _ = await setup_adapter(tmp_path, early_response=False)
        try:
            runtime.dictation = core.voice_dictation = lambda: False
            core.voice_tutoring = lambda: False
            capabilities = core.meta()["capabilities"]
            assert "voice" in capabilities and "voice_dictation" not in capabilities
            assert "voice_tutoring" not in capabilities
            refused = await client.post(
                f"/v1/sessions/{sid}/voice/dictations",
                headers=headers(),
                json={"type": "create_dictation", "client_capture_id": new_id("cli"), "purpose": "question"},
            )
            assert refused.status_code >= 400 and refused.json()["error"]["code"] == "feature_disabled"
            assert not runtime.activities.drafts
            runtime.dictation = core.voice_dictation = lambda: True
            assert "voice_dictation" in core.meta()["capabilities"]
        finally:
            await socket.close()
            await runtime.close()
            await client.aclose()

    asyncio.run(scenario())
