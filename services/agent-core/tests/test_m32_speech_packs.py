"""USB-style install, trust, licence and path gates with synthetic bytes; no downloaded speech weights."""

import hashlib
import json
import shutil
import socket

import pytest
from agent_core.config.environments import Environment
from agent_core.store.speech_packs import UPSTREAM_COMMIT, SpeechPackError, SpeechPackStore
from m20_fixtures import SIGNED_AT
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose


def signed(folder, document):
    document = dev_signer(Purpose.UPDATER).sign("speech_pack", document, now=SIGNED_AT)
    (folder / "manifest.json").write_text(json.dumps(document))
    return document


def pack(folder):
    folder.mkdir()
    paths = [
        ("vad", "silero", "vad/silero_vad.jit"),
        ("turn", "smart-turn", "turn/model.onnx"),
        ("stt", "faster-whisper", "stt/model.bin"),
        ("tts", "qwen3", "tts/config.json"),
        ("sidecar", "speech-to-speech", "sidecar/jana-voice"),
    ]
    files = []
    for role, engine, name in paths:
        path = folder / name
        path.parent.mkdir(exist_ok=True)
        payload = b"synthetic " + role.encode()
        path.write_bytes(payload)
        files.append(
            {
                "path": name,
                "role": role,
                "engine": engine,
                "classes": ["mid", "high"],
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "licence": {
                    "spdx": "Apache-2.0",
                    "source_url": "https://example.invalid/synthetic",
                    "attribution": "Synthetic test component; no real model weights.",
                },
            }
        )
    # High-only extra weights are not copied on a mid machine.
    extra = folder / "tts/high.bin"
    extra.write_bytes(b"high only")
    files.append(
        {
            **files[3],
            "path": "tts/high.bin",
            "classes": ["high"],
            "size_bytes": 9,
            "sha256": hashlib.sha256(b"high only").hexdigest(),
        }
    )
    profile = {
        "stt": "faster-whisper",
        "tts": "qwen3",
        "device": "cpu",
        "vad_path": "vad",
        "turn_path": "turn/model.onnx",
        "stt_path": "stt",
        "tts_path": "tts",
        "sidecar_path": "sidecar/jana-voice",
        "speaker": "Aiden",
    }
    return signed(
        folder,
        {
            "speech_pack_id": "sp.en.1_0",
            "manifest_version": 1,
            "language": "en",
            "platform": "linux-x86_64",
            "upstream_commit": UPSTREAM_COMMIT,
            "min_app_version": "0.0.0",
            "created_at": SIGNED_AT,
            "profiles": {"mid": profile},
            "files": files,
        },
    )


def store(path, environment=Environment.DEV):
    return SpeechPackStore(path, environment, "linux-x86_64", "0.0.0", "mid", trust=dev_trust())


def voc03_usb_install_offline(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("USB installation must not use the network")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    source = tmp_path / "usb"
    pack(source)
    desk = store(tmp_path / "installed")
    installed = desk.install(source)
    assert desk.verify(installed).speech_pack_id == "sp.en.1_0"
    assert not (installed / "tts/high.bin").exists()
    assert len(desk.licences(installed)) == 5
    assert desk.install(source) == installed
    assert not list(desk.root.glob(".speech-staging-*"))


@pytest.mark.parametrize(
    "change",
    [
        "signature",
        "hash",
        "size",
        "unlisted",
        "nested_manifest",
        "symlink",
        "licence",
        "excluded",
        "traversal",
        "absolute",
        "windows_drive",
        "duplicate",
        "class",
        "platform",
        "upstream",
        "too_new",
        "missing_turn",
        "wrong_engine",
    ],
)
def test_refused_pack_never_installs(tmp_path, change):
    source = tmp_path / "usb"
    document = pack(source)
    if change == "signature":
        document["signature"]["value"] = "a" * 88
        (source / "manifest.json").write_text(json.dumps(document))
    elif change == "hash":
        (source / "stt/model.bin").write_bytes(b"X" * document["files"][2]["size_bytes"])
    elif change == "size":
        (source / "stt/model.bin").write_bytes(b"bad size")
    elif change in ("unlisted", "nested_manifest"):
        (source / ("unknown.py" if change == "unlisted" else "stt/manifest.json")).write_text("{}")
    elif change == "symlink":
        path = source / "stt/model.bin"
        path.unlink()
        path.symlink_to(source / "tts/config.json")
    else:
        first = document["files"][0]
        if change == "licence":
            first["licence"]["spdx"] = "GPL-3.0"
        elif change == "excluded":
            first["path"] = "sidecar/libespeak-ng.so"
        elif change in ("traversal", "absolute", "windows_drive"):
            first["path"] = {"traversal": "../escape", "absolute": "/escape", "windows_drive": "C:/escape"}[change]
        elif change == "duplicate":
            document["files"].append(first.copy())
        elif change == "class":
            document["profiles"] = {"high": document["profiles"]["mid"]}
        elif change == "platform":
            document["platform"] = "windows-x86_64"
        elif change == "upstream":
            document["upstream_commit"] = "0" * 40
        elif change == "too_new":
            document["min_app_version"] = "9.0.0"
        elif change == "missing_turn":
            document["profiles"]["mid"]["turn_path"] = None
        elif change == "wrong_engine":
            first["engine"] = "unlicensed-custom-model"
        signed(source, document)
    desk = store(tmp_path / "installed")
    with pytest.raises(SpeechPackError):
        desk.install(source)
    assert not desk.root.exists()


def test_production_refuses_test_signatures_and_load_rechecks_installed_bytes(tmp_path):
    source = tmp_path / "usb"
    pack(source)
    with pytest.raises(SpeechPackError):
        store(tmp_path / "release", Environment.PRODUCTION).install(source)
    desk = store(tmp_path / "installed")
    installed = desk.install(source)
    (installed / "sidecar/jana-voice").write_bytes(b"tampered")
    with pytest.raises(SpeechPackError):
        desk.verify(installed)


def test_model_key_cannot_authorize_executable_speech_and_adopted_revocation_is_live(tmp_path):
    from agent_core.config.trust import bundled_trust
    from signing_service.revocation import dev_revocation_list

    source = tmp_path / "usb"
    document = pack(source)
    desk = store(tmp_path / "installed")
    installed = desk.install(source)
    wrong = dev_signer(Purpose.MODEL).sign("model_manifest", document, now=SIGNED_AT)
    (source / "manifest.json").write_text(json.dumps(wrong))
    with pytest.raises(SpeechPackError):
        desk.verify(source)
    assert desk.verify(installed)
    revoked = dev_revocation_list(
        2,
        [
            {
                "key_id": document["signature"]["key_id"],
                "reason": "synthetic test",
                "revoked_at": "2026-10-15T00:00:00.000Z",
            }
        ],
    )
    assert desk.revocations.adopt(revoked)
    with pytest.raises(SpeechPackError):
        desk.verify(installed)
    # A fresh store sees the same revocation received through an unrelated update.
    with pytest.raises(SpeechPackError):
        fresh = SpeechPackStore(desk.root, Environment.DEV, "linux-x86_64", "0.0.0", "mid", trust=bundled_trust())
        fresh.verify(installed)


def test_sidecar_trust_reads_the_held_revocation_list_without_writing(tmp_path):
    """The sidecar re-checks the signature with the device's held list too (D88, SEC-16): a revocation the device
    adopted after the core's check still stops a launch. It only reads the data folder."""
    from agent_core.config.revocation import HELD
    from agent_core.store.speech_packs import held_trust, verify_pack
    from signing_service.revocation import dev_revocation_list

    source = tmp_path / "usb"
    document = pack(source)
    desk = store(tmp_path / "data" / "speech-packs")
    installed = desk.install(source)
    data_root = installed.parent.parent
    held = data_root / HELD
    before = held.read_bytes() if held.exists() else None

    def launch():
        return verify_pack(
            installed, "mid", "linux-x86_64", "0.0.0", Environment.DEV, trust=held_trust(data_root, Environment.DEV)
        )

    assert launch()
    assert (held.read_bytes() if held.exists() else None) == before
    revoked = dev_revocation_list(
        2,
        [
            {
                "key_id": document["signature"]["key_id"],
                "reason": "synthetic test",
                "revoked_at": "2026-10-15T00:00:00.000Z",
            }
        ],
    )
    assert desk.revocations.adopt(revoked)
    with pytest.raises(SpeechPackError):
        launch()


# --- the USB kit, the pack list and removal (PLT-12, VOC-02, VOC-03) ----------------------------------------------


def _kit_with_speech(tmp_path):
    from agent_core.store.kit_install import SPEECH_FILE
    from signing_service.service import sign_kit

    kit = tmp_path / "kit"
    (kit / "speech").mkdir(parents=True)
    pack(kit / "speech" / "sp.en.1_0")
    files = sorted(p.relative_to(kit).as_posix() for p in (kit / "speech" / "sp.en.1_0").rglob("*") if p.is_file())
    sign_kit(kit, [(name, SPEECH_FILE) for name in files])
    return kit


def test_usb_kit_installs_its_speech_pack_offline(tmp_path, monkeypatch):
    """A speech pack listed in the kit's signed kit.json installs from the kit through the speech pack store's own
    checks, with networking disabled; a listed file that no longer matches the kit refuses only that pack."""
    from agent_core.store.kit_install import install_kit
    from agent_core.store.pack_store import PackStore

    def forbidden(*args, **kwargs):
        raise AssertionError("USB installation must not use the network")

    kit = _kit_with_speech(tmp_path)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    speech = store(tmp_path / "data" / "speech-packs")
    packs = PackStore(tmp_path / "data" / "packs", Environment.DEV)
    report = install_kit(kit, packs, None, Environment.DEV, speech=speech)
    assert report.speech == ["sp.en.1_0"] and report.refused == []
    assert speech.verify(speech.root / "sp.en.1_0").speech_pack_id == "sp.en.1_0"
    assert not (speech.root / "sp.en.1_0" / "tts/high.bin").exists()  # a mid laptop copies only its class's files

    (kit / "speech" / "sp.en.1_0" / "stt" / "model.bin").write_bytes(b"tampered")
    shutil.rmtree(speech.root / "sp.en.1_0")
    report = install_kit(kit, packs, None, Environment.DEV, speech=speech)
    assert report.speech == [] and report.refused == [("sp.en.1_0", "speech.damaged")]
    assert not (speech.root / "sp.en.1_0").exists()


def test_speech_pack_listed_and_removed(tmp_path):
    """The pack list names an installed speech pack with its licences; removing it deletes the folder, stops a sidecar
    running from it first and offers voice again from what remains."""
    from agent_core.api.packs import PackDesk

    pack(tmp_path / "usb")
    calls = []
    desk = PackDesk(tmp_path / "data", Environment.DEV, "1.0.0", lambda *a, **k: None)
    desk.speech = store(tmp_path / "data" / "speech-packs")
    desk.before_speech_remove = lambda pack_id: calls.append(("stop", pack_id))
    desk.on_speech = lambda: calls.append(("rescan", None))
    assert desk.install_source({"kind": "file", "path": str(tmp_path / "usb")}, "job_x") == ["sp.en.1_0"]
    listed = [row for row in desk.catalogue({"installed": []})["installed"] if row.get("kind") == "speech_pack"]
    assert [row["speech_pack_id"] for row in listed] == ["sp.en.1_0"] and listed[0]["signature_ok"]
    assert len(listed[0]["licences"]) == 5 and "model_pack_id" not in listed[0] and "model_id" not in listed[0]

    calls.clear()
    assert desk.remove("sp.en.1_0") is True
    assert calls == [("stop", "sp.en.1_0"), ("rescan", None)]
    assert not (desk.speech.root / "sp.en.1_0").exists() and not list(desk.speech.root.glob(".speech-removing-*"))
    assert desk.remove("sp.en.1_0") is False and desk.remove("sp.en.../x") is False
    assert [row for row in desk.catalogue({"installed": []})["installed"] if row.get("kind") == "speech_pack"] == []


def test_removing_the_running_pack_stops_its_sidecar(tmp_path):
    """The launcher stops the sidecar of the pack being removed and offers no voice until another pack is found."""
    from agent_core.net.voice_launch import VoiceLaunch

    frames = []
    launch = VoiceLaunch(
        tmp_path / "speech-packs", "mid", "linux-x86_64", "0.0.0", Environment.DEV,
        "http://127.0.0.1:1/v1/voice/llm", "t" * 32, frames.append, trust=dev_trust(),
    )  # fmt: skip
    launch.selected = (tmp_path / "speech-packs" / "sp.en.1_0", None)  # type: ignore[assignment]
    launch._request = "req"
    changed = []
    launch.on_change = lambda: changed.append(True)
    launch.release("sp.en.2_0")
    assert launch.selected is not None and frames == []
    launch.release("sp.en.1_0")
    assert launch.selected is None and changed == [True]
    assert frames == [{"type": "control.voice_stop", "request_id": "req"}]
