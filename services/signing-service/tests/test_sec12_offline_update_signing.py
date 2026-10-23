"""SEC-12, SEC-15 (owner ruling 2026-10-17): app updates are signed offline. CI leaves the update bundles unsigned
with a request; the ceremony laptop signs exactly those files through Tauri's signer; publishing takes only what that
result signs. Every key here is a throwaway made in a temporary folder and every bundle is made up."""

from __future__ import annotations

import base64
import hashlib
import json
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, NoEncryption, PrivateFormat
from jana_tools import REPO_ROOT
from signing_service import ceremony
from signing_service.updater import (
    LATEST,
    SIGNED,
    UpdateSigningRefused,
    command_signer,
    configured_public_key,
    pem_public_key,
    request,
    sign,
    signed_entry,
    tauri_public_key,
    verify,
    verify_signature,
)

BASE = "https://updates.example.invalid/v1/files"


def _pem(folder: Path, name: str = "updater") -> Path:
    pem = folder / f"{name}.pem"
    pem.write_bytes(Ed25519PrivateKey.generate().private_bytes(Encoding.PEM, PrivateFormat.PKCS8, NoEncryption()))
    return pem


def _stand_in(pem: Path):  # type: ignore[no-untyped-def]
    return command_signer((sys.executable, "-m", "signing_service.updater", "sign-with-key", str(pem)))


def _bundles(root: Path) -> Path:
    files = {
        "nsis/Jana_1.2.0_x64-setup.exe": b"MZ made-up nsis installer",
        "msi/Jana_1.2.0_x64_en-US.msi": b"made-up msi",
        "macos/Jana.app/Contents/MacOS/jana-shell": b"\xcf\xfa\xed\xfe made-up",
        "macos/Jana.app/Contents/Info.plist": b"<plist/>",
        "appimage/Jana_1.2.0_amd64.AppImage": b"\x7fELF made-up",
    }
    for name, data in files.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_bytes(data)
    return root


def _requested(tmp_path: Path) -> Path:
    bundle, out = _bundles(tmp_path / "bundle"), tmp_path / "update"
    for os_name in ("windows", "macos", "linux"):
        request(bundle, os_name, "1.2.0", out)
    return out


def test_sec12_update_bundles_are_signed_offline_and_verified(tmp_path: Path) -> None:
    """The request lists each OS's unsigned bundle with its sha256; signing on the laptop checks each file first,
    verifies every signature against the updater public key and writes the signed result and Tauri's latest.json."""
    out = _requested(tmp_path)
    requests = sorted(p.name for p in out.glob("update-request-*.json"))
    assert requests == ["update-request-linux.json", "update-request-macos.json", "update-request-windows.json"]
    assert not list(out.glob("*.sig")), "CI signs nothing"
    pem = _pem(tmp_path)
    key = pem_public_key(pem)
    result = sign(out, _stand_in(pem), key, BASE)
    targets = sorted(a["target"] for a in result["artefacts"])
    assert targets == ["darwin-aarch64-app", "linux-x86_64-appimage", "windows-x86_64-msi", "windows-x86_64-nsis"]
    latest = json.loads((out / LATEST).read_text())
    assert latest["version"] == "1.2.0"
    assert latest["platforms"]["darwin-aarch64-app"]["url"] == f"{BASE}/Jana.app.tar.gz"
    for artefact in result["artefacts"]:
        path = out / artefact["file"]
        assert artefact["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert "file:" in verify_signature(path, artefact["signature"], key)
    assert verify(out, key)["version"] == "1.2.0"
    # Publishing one artefact takes its entry from the signed result.
    assert signed_entry(out / SIGNED, out / "Jana_1.2.0_x64-setup.exe", key)["target"] == "windows-x86_64-nsis"


def test_sec12_offline_signing_refuses_what_ci_did_not_build(tmp_path: Path) -> None:
    """A bundle changed after CI built it is never signed; a signature from another key, a placeholder host or a
    missing signature is refused, and nothing is written."""
    out = _requested(tmp_path)
    pem = _pem(tmp_path)
    key = pem_public_key(pem)
    changed = out / "Jana_1.2.0_x64_en-US.msi"
    original = changed.read_bytes()
    changed.write_bytes(original + b"!")
    with pytest.raises(UpdateSigningRefused, match="not the file CI built"):
        sign(out, _stand_in(pem), key, BASE)
    assert not (out / SIGNED).exists() and not (out / LATEST).exists()
    changed.write_bytes(original)
    other = pem_public_key(_pem(tmp_path, "other"))
    with pytest.raises(UpdateSigningRefused, match="another key"):
        sign(out, _stand_in(pem), other, BASE)
    with pytest.raises(UpdateSigningRefused, match="production https host"):
        sign(out, _stand_in(pem), key, "https://updates.PLACEHOLDER-production-host/v1")
    with pytest.raises(UpdateSigningRefused, match="left no"):
        sign(out, lambda _path: None, key, BASE)
    assert not (out / SIGNED).exists()


def test_sec12_publishing_takes_only_the_signed_result(tmp_path: Path) -> None:
    """Publishing refuses an unsigned folder, a bundle changed after signing, a result made for another public key and
    an artefact the result does not cover."""
    out = _requested(tmp_path)
    pem = _pem(tmp_path)
    key = pem_public_key(pem)
    with pytest.raises(UpdateSigningRefused, match="sign the update on the ceremony laptop first"):
        verify(out, key)
    sign(out, _stand_in(pem), key, BASE)
    with pytest.raises(UpdateSigningRefused, match="another updater public key"):
        verify(out, pem_public_key(_pem(tmp_path, "other")))
    stray = tmp_path / "Jana_9.9.9_x64-setup.exe"
    stray.write_bytes(b"MZ not signed")
    with pytest.raises(UpdateSigningRefused, match="not an update bundle the offline signing covered"):
        signed_entry(out / SIGNED, stray, key)
    appimage = out / "Jana_1.2.0_amd64.AppImage"
    appimage.write_bytes(appimage.read_bytes() + b"tampered")
    with pytest.raises(UpdateSigningRefused, match="not the file CI built"):
        verify(out, key)


def test_sec12_updater_key_is_the_apps_and_ci_holds_none() -> None:
    """The public key comes from the app's updater configuration (refused while a placeholder); the release workflow
    names no updater private key and builds no signed updater artefacts; the ceremony rehearses the update step."""
    config = REPO_ROOT / "apps" / "desktop" / "src-tauri" / "tauri.updater.conf.json"
    pubkey = json.loads(config.read_text())["plugins"]["updater"]["pubkey"]
    if pubkey.startswith("PLACEHOLDER"):
        with pytest.raises(UpdateSigningRefused, match="key ceremony's step 8"):
            configured_public_key(config)
    else:
        assert configured_public_key(config) == pubkey
    assert json.loads(config.read_text())["bundle"]["createUpdaterArtifacts"] is False
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "TAURI_SIGNING_PRIVATE_KEY" not in workflow
    assert "signing_service.updater request" in workflow
    # The key text has the shape Tauri's `signer generate` prints: base64 of a minisign public key file.
    text = tauri_public_key(Ed25519PrivateKey.generate(), b"\x01" * 8)
    assert base64.b64decode(text).decode().startswith("untrusted comment: minisign public key: ")


def test_sec12_ceremony_dry_run_rehearses_update_signing(tmp_path: Path) -> None:
    said: list[str] = []
    ceremony.dry_run(tmp_path / "dry", say=said.append)
    assert any("Update bundles" in line and "refused" in line for line in said)
    assert any("sign-updates" in line for line in said)
    assert ceremony.main(["sign-updates", str(tmp_path)]) == 1  # refused without its command and host


def test_sec15_release_publish_takes_an_app_update_only_with_its_signatures(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """`release publish --kind app_update` refuses an update with no signed result, and one whose result is not
    signed for the updater public key the app ships (here still the placeholder)."""
    from jana_tools.__main__ import _release

    artefact = tmp_path / "Jana_1.2.0_x64-setup.exe"
    artefact.write_bytes(b"MZ made-up")
    attestation = tmp_path / "attestation.json"
    attestation.write_text(json.dumps({"sha256": hashlib.sha256(artefact.read_bytes()).hexdigest()}))
    base = ["publish", str(artefact), "--kind", "app_update", "--id", "app", "--version", "1.2.0",
            "--attestation", str(attestation)]  # fmt: skip
    assert _release(base) == 1
    assert "SEC-15: an app update needs --signatures" in capsys.readouterr().err
    out = _requested(tmp_path)
    pem = _pem(tmp_path)
    sign(out, _stand_in(pem), pem_public_key(pem), BASE)
    assert _release([*base, "--signatures", str(out / SIGNED)]) == 1
    assert "SEC-15:" in capsys.readouterr().err  # the app's updater public key decides, never the folder's
