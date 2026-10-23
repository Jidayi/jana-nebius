"""Speech packs are updater artefacts checked against the live revocation list (D88, SEC-12a, SEC-16), and the
class rules of TABLE VOC-03a, the VOC-03 memory budget, per-launch adapter tokens (VOC-23) and the install path."""

import asyncio
import json
import logging
import os

import pytest
from agent_core.config.environments import Environment
from agent_core.config.trust import ARTEFACT_PURPOSE, Purpose
from agent_core.net.voice import LocalVoiceEndpoint
from agent_core.net.voice_launch import TTS_BY_CLASS, VoiceLaunch, class_bytes, memory_budget
from agent_core.net.voice_sidecar import argument_values
from agent_core.store.speech_packs import SpeechPackError, SpeechPackStore, verify_pack
from m20_fixtures import SIGNED_AT
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import DEV_KEY_IDS
from signing_service.keys import Purpose as SigningPurpose
from test_m31_voice_socket import Endpoint
from test_m32_sidecar_launcher import launch
from test_m32_speech_packs import pack, signed

UPDATER_KEY = DEV_KEY_IDS[SigningPurpose.UPDATER]


def resign(folder, document, purpose, artefact):
    unsigned = {k: v for k, v in document.items() if k != "signature"}
    (folder / "manifest.json").write_text(json.dumps(dev_signer(purpose).sign(artefact, unsigned, now=SIGNED_AT)))


def link_for(root, hardware="mid", *, trust=None, memory_fits=None, timeout=1):
    return VoiceLaunch(root, hardware, "linux-x86_64", "0.0.0", Environment.DEV, "http://127.0.0.1:8765/v1/voice/llm",
                       "synthetic_" + "a" * 32, lambda frame: None, start_timeout_s=timeout,
                       trust=trust or dev_trust, memory_fits=memory_fits)  # fmt: skip


def test_speech_pack_is_an_updater_artefact():
    assert ARTEFACT_PURPOSE["speech_pack"] is Purpose.UPDATER


@pytest.mark.parametrize("signer", ["model", "content"])
def test_sec12_speech_pack_signed_by_a_non_updater_key_is_refused(tmp_path, signer):
    source = tmp_path / "usb"
    document = pack(source)
    purpose = SigningPurpose.MODEL if signer == "model" else SigningPurpose.CONTENT
    artefact = "model_manifest" if signer == "model" else "content_pack"
    resign(source, document, purpose, artefact)
    store = SpeechPackStore(tmp_path / "installed", Environment.DEV, "linux-x86_64", "0.0.0", "mid", trust=dev_trust)
    with pytest.raises(SpeechPackError, match="manifest_refused"):
        store.install(source)
    assert not (tmp_path / "installed").exists()


def test_sec16_revoked_updater_key_refuses_install_and_every_launch(tmp_path):
    revoked: set[str] = set()

    def live():  # the device's live list: a revocation adopted after install applies at the next launch
        return dev_trust().with_revoked(revoked)

    source = tmp_path / "usb"
    pack(source)
    root = tmp_path / "speech-packs"
    link = link_for(root, trust=live)
    installed = link.store.install(source)
    assert link.scan() and link.selected[0] == installed

    revoked.add(UPDATER_KEY)
    assert not link.scan(manifest_only=True) and not link.scan()
    with pytest.raises(SpeechPackError, match="manifest_refused"):
        link.store.install(source)

    async def first_use():
        from agent_core.net.voice import VoiceTransportError

        with pytest.raises(VoiceTransportError, match="voice_pack_unavailable"):
            await link.connect()
        await link.close()

    asyncio.run(first_use())


def test_sidecar_checks_layout_and_signature_but_leaves_hashing_to_the_core(tmp_path):
    folder = tmp_path / "sp.en.1_0"
    document = pack(folder)
    model = folder / "stt/model.bin"
    model.write_bytes(b"Y" * document["files"][2]["size_bytes"])  # same size, different bytes
    with pytest.raises(SpeechPackError):
        verify_pack(folder, "mid", "linux-x86_64", "0.0.0", Environment.DEV, trust=dev_trust())
    assert verify_pack(folder, "mid", "linux-x86_64", "0.0.0", Environment.DEV, trust=dev_trust(), hashes=False)
    model.write_bytes(b"short")
    with pytest.raises(SpeechPackError):
        verify_pack(folder, "mid", "linux-x86_64", "0.0.0", Environment.DEV, trust=dev_trust(), hashes=False)
    resign(folder, document, SigningPurpose.MODEL, "model_manifest")
    with pytest.raises(SpeechPackError):  # the shipped anchors still refuse a model-signed pack in the sidecar
        verify_pack(folder, "mid", "linux-x86_64", "0.0.0", Environment.DEV, hashes=False)


def class_pack(root, name, *, classes, profiles):
    folder = root / name
    document = pack(folder)
    document["speech_pack_id"] = name
    for file in document["files"]:
        file["classes"] = classes
    document["profiles"] = profiles
    signed(folder, {k: v for k, v in document.items() if k != "signature"})
    return folder


def test_voc03a_class_rules_choose_engines_by_class(tmp_path):
    root = tmp_path / "speech-packs"
    root.mkdir()
    base = json.loads(json.dumps(pack(tmp_path / "template")["profiles"]["mid"]))
    qwen = class_pack(root, "sp.en.1_0", classes=["low", "mid", "high"],
                      profiles={c: dict(base) for c in ("low", "mid", "high")})  # fmt: skip
    assert TTS_BY_CLASS == {"low": ("kokoro", "pocket"), "mid": ("kokoro", "qwen3"), "high": ("qwen3", "kokoro")}
    # Qwen3-TTS on mid and high; never on low, which runs Kokoro or Pocket only (TABLE VOC-03a).
    for hardware, offered in (("mid", True), ("high", True), ("low", False)):
        link = link_for(root, hardware)
        assert link.scan(manifest_only=True) is offered, hardware
        if offered:
            assert link.selected[0] == qwen and link.tutoring
    assert not link_for(root, "content_only").scan()  # content-only: no sidecar, OS synthesiser read-aloud
    # D95: Kokoro loads from the pack's local files now, so a newer mid-class Kokoro pack is offered and chosen.
    kokoro_pack = class_pack(root, "sp.en.1_1", classes=["mid"], profiles={"mid": {**base, "tts": "kokoro"}})
    document = json.loads((kokoro_pack / "manifest.json").read_text())
    for file in document["files"]:
        if file["role"] == "tts":
            file["engine"] = "kokoro"
    signed(kokoro_pack, {k: v for k, v in document.items() if k != "signature"})
    link = link_for(root, "mid")
    assert link.scan(manifest_only=True) and link.selected[0] == kokoro_pack


def test_voc03_memory_budget_turns_voice_tutoring_off_but_keeps_read_aloud(tmp_path):
    root = tmp_path / "speech-packs"
    root.mkdir()
    folder = root / "sp.en.1_0"
    pack(folder)
    gib = 1024**3
    probe = link_for(root)
    assert probe.scan()
    speech = class_bytes(probe.selected[1], "mid")
    plan = {"attempts": [{"model": "synthetic", "context": 8192, "args": [], "resident_bytes": 10 * gib}]}
    roomy = link_for(root, memory_fits=memory_budget(plan, 12 * gib + speech, 2.0))
    tight = link_for(root, memory_fits=memory_budget(plan, 12 * gib + speech - 1, 2.0))
    assert roomy.scan() and roomy.tutoring
    assert tight.scan() and tight.selected is not None and not tight.tutoring
    assert memory_budget({}, 1, 2.0)(probe.selected[1], "mid")  # no local model resident: nothing competes


@pytest.mark.parametrize(("hardware", "device", "backend"),
                         [("mid", "cpu", "ggml"), ("high", "cuda", "torch"), ("high", "mps", "mlx")])  # fmt: skip
def test_voc03a_qwen3_backend_follows_the_class(hardware, device, backend):
    profile = {"stt": "parakeet-tdt", "tts": "qwen3", "device": device, "vad_path": "vad",
               "turn_path": "turn/model.onnx", "stt_path": "stt", "tts_path": "tts",
               "sidecar_path": "sidecar/jana-voice", "speaker": "Aiden"}  # fmt: skip
    from agent_core.store.speech_packs import SpeechProfile

    values = argument_values(launch(hardware=hardware), SpeechProfile.model_validate(profile))
    assert values["tts"]["qwen3_tts_backend"] == backend
    assert values["vad"]["smart_turn"] and values["vad"]["speculative_reopen_ms"] == 1500


def test_voc05a_low_class_turns_smart_turn_off_and_shortens_the_reopen_window():
    from agent_core.store.speech_packs import SpeechProfile

    profile = SpeechProfile.model_validate(
        {"stt": "faster-whisper", "tts": "qwen3", "device": "cpu", "vad_path": "vad", "turn_path": None,
         "stt_path": "stt", "tts_path": "tts", "sidecar_path": "sidecar/jana-voice", "speaker": "Aiden"})  # fmt: skip
    values = argument_values(launch(hardware="low"), profile)
    assert values["vad"]["smart_turn"] is False and values["vad"]["smart_turn_model_path"] is None
    assert values["vad"]["speculative_reopen_ms"] == 200


def voc23_tokens_not_leaked(tmp_path, monkeypatch, caplog):
    """Each sidecar launch gets its own adapter token; a stopped launch's token stops working; neither the adapter
    token nor the Realtime token reaches logs, reprs, the environment or the process arguments."""
    caplog.set_level(logging.DEBUG)

    async def scenario():
        root = tmp_path / "speech-packs"
        root.mkdir()
        pack(root / "sp.en.1_0")
        frames = []
        link = VoiceLaunch(root, "mid", "linux-x86_64", "0.0.0", Environment.DEV,
                           "http://127.0.0.1:8765/v1/voice/llm", "synthetic_" + "a" * 32, frames.append,
                           trust=dev_trust)  # fmt: skip
        current = []
        link.on_token = current.append

        async def open(_):
            return Endpoint()

        monkeypatch.setattr(LocalVoiceEndpoint, "open", open)
        tokens = []
        for _ in range(2):
            connecting = asyncio.create_task(link.connect())
            async with asyncio.timeout(2):
                while not frames or frames[-1]["type"] != "control.voice_start":
                    await asyncio.sleep(0.01)
            start = frames[-1]
            assert start["adapter_token"] == current[-1]
            tokens.append(start["adapter_token"])
            realtime = "synthetic_" + "r" * 32
            link.on_shell({"type": "control.voice_endpoint", "request_id": start["request_id"],
                           "url": "ws://127.0.0.1:2345/v1/realtime", "token": realtime})  # fmt: skip
            await (await connecting).close()
            link._stop()  # the sidecar stops (voice off, crash or give-up): its token is retired
            assert current[-1] != start["adapter_token"]
            secrets_seen = [start["adapter_token"], realtime]
            text = repr(link) + caplog.text + json.dumps(dict(os.environ))
            assert not any(secret in text for secret in secrets_seen)
        assert tokens[0] != tokens[1]
        await link.close()

    asyncio.run(scenario())


def test_voc03_speech_pack_installs_from_a_folder_through_the_pack_desk(tmp_path):
    from agent_core.api.packs import PackDesk

    source = tmp_path / "usb" / "sp.en.1_0"
    source.parent.mkdir()
    pack(source)
    events, rescans = [], []
    desk = PackDesk(tmp_path / "data", Environment.DEV, "0.0.0", events.append, trust=dev_trust())
    link = link_for(tmp_path / "data" / "speech-packs", trust=desk._trust)
    assert not link.scan(manifest_only=True)
    desk.speech, desk.on_speech = link.store, lambda: rescans.append(link.rescan())
    assert desk.install_source({"kind": "file", "path": str(source)}, "job_" + "0" * 26) == ["sp.en.1_0"]
    assert rescans == [True] and link.selected is not None
    assert [e["state"] for e in events] == ["verifying", "done"]
    resign(source, json.loads((source / "manifest.json").read_text()), SigningPurpose.MODEL, "model_manifest")
    with pytest.raises(SpeechPackError):
        desk.install_source({"kind": "file", "path": str(source)}, "job_" + "1" * 26)
    assert events[-1]["state"] == "failed"


def test_read_aloud_and_dictation_only_class_starts_no_voice_turn():
    from test_m31_voice_bridge import TURN, ready

    bridge = ready()
    bridge.tutoring = False
    bridge.control({"type": "mode", "mode": "hands_free"})
    assert bridge.state == "idle" and not bridge.microphone(bytes(960)).upstream
    assert bridge.begin_provisional(TURN) is False
    effects = bridge.start_dictation("cap_01JZ0000000000000000000001", 0)
    assert effects.upstream and bridge.microphone(bytes(960)).upstream  # dictation still captures (VOC-46)
