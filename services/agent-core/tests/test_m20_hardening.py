"""Hardening of artefacts the device reads (SEC-12, SEC-13, SEC-15, SEC-18, DAT-10): a root key signs only inside
its validity window, an oversized or unsigned pack is refused before its records are read, the rollback installer
is checked against its signed manifest rather than the unsigned state file, and a crafted profile archive cannot
choose its key-derivation cost, unpack without bound or name SQL columns. Every artefact here is synthetic."""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import struct
import zipfile
from pathlib import Path

import pytest
from agent_core.config.environments import Environment
from agent_core.config.keys import Settings
from agent_core.config.trust import SignatureRefused, TrustStore
from agent_core.store.exports import (
    FORMAT,
    PASSPHRASE_MAGIC,
    ExportError,
    open_with_passphrase,
    read_profile_archive,
    seal_with_passphrase,
)
from agent_core.store.packs import PackRejectedError, verify
from agent_core.store.updates import OFFLINE_ARTEFACT, UpdateRefused, UpdateState
from api_harness import start_core, stop_core
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from m20_fixtures import content_pack, update_pack
from signing_service.hierarchy import Signer, public_b64
from signing_service.keys import Purpose
from test_m10a_profiles import Api

DEV = Environment.DEV
PASSPHRASE = "correct horse battery staple, synthetic"  # noqa: S105 (a synthetic test passphrase)


def test_sec12_root_validity_window_checked() -> None:
    """A document signed after its root key's `not_after` is refused even when the intermediate is still valid."""
    import base64

    from agent_core.config.trust import Certificate, RootKey, canonical_bytes

    root_key = Ed25519PrivateKey.from_private_bytes(b"expired synthetic root".ljust(32, b"\0"))
    root = RootKey("key_root_expired", public_b64(root_key), "test", "2025-01-01T00:00:00Z", "2026-01-01T00:00:00Z")
    key = Ed25519PrivateKey.from_private_bytes(b"synthetic content key".ljust(32, b"\0"))
    # A certificate that outlives its root (the signing service refuses to issue one; a forged anchor file need not).
    unsigned = Certificate("key_content_late", Purpose.CONTENT, public_b64(key), root.key_id,
                           "2025-01-01T00:00:00Z", "2030-01-01T00:00:00Z", "")  # fmt: skip
    signature = base64.b64encode(root_key.sign(canonical_bytes(unsigned.body()))).decode()
    cert = Certificate(*[getattr(unsigned, f) for f in ("key_id", "purpose", "public_key", "root_key_id",
                                                        "not_before", "not_after")], signature)  # fmt: skip
    trust = TrustStore({root.key_id: root}, {cert.key_id: cert})
    signer = Signer(cert, key.sign)
    inside = signer.sign("content_pack", {"pack_id": "pack.x.o"}, now="2025-06-01T00:00:00Z")
    trust.verify("content_pack", inside, DEV, signed_at="2025-06-01T00:00:00Z")
    late = signer.sign("content_pack", {"pack_id": "pack.x.o"}, now="2026-06-01T00:00:00Z")
    with pytest.raises(SignatureRefused, match="not valid at"):
        trust.verify("content_pack", late, DEV, signed_at="2026-06-01T00:00:00Z")


def test_sec13_pack_signature_checked_before_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pack whose manifest is not signed is refused for its signature before any record table is read."""
    from agent_core.store import packs

    signed = content_pack(tmp_path / "phy.pack")
    unsigned = {k: v for k, v in signed.items() if k != "signature"}
    packs.write_pack(tmp_path / "unsigned.pack", unsigned, packs.read_pack(tmp_path / "phy.pack")[1])

    def no_records(path: Path) -> object:
        raise AssertionError("the records were read before the signature was checked")

    monkeypatch.setattr(packs, "read_pack", no_records)
    with pytest.raises(PackRejectedError, match="signed"):
        verify(tmp_path / "unsigned.pack", DEV)


def test_sec13_oversized_pack_refused_unread(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content_pack(tmp_path / "phy.pack")
    verify(tmp_path / "phy.pack", DEV)
    monkeypatch.setattr(Settings.model_fields["pack_file_max_mb"], "default", 0.001)
    with pytest.raises(PackRejectedError, match="larger than any pack"):
        verify(tmp_path / "phy.pack", DEV)


def test_sec15_rollback_installer_checked_against_signed_manifest(tmp_path: Path) -> None:
    """The state file's own hash cannot stand in for the signed manifest's: an installer swapped together with the
    state file's hash is refused (SEC-15, PLT-15)."""
    package = tmp_path / "u.janaupdate"
    update_pack(package, "1.0.0")
    manifest = json.loads(zipfile.ZipFile(package).read("update.json"))
    assert OFFLINE_ARTEFACT
    state = UpdateState(tmp_path / "data")
    swapped = state.folder / "installers" / "1.0.0" / manifest["installer"]["name"]
    swapped.parent.mkdir(parents=True)
    swapped.write_bytes(b"#!/bin/sh\necho a different program\n")
    entry = {"version": "1.0.0", "installer": str(swapped.relative_to(state.folder)),
             "sha256": hashlib.sha256(swapped.read_bytes()).hexdigest(), "manifest": manifest}  # fmt: skip
    with pytest.raises(UpdateRefused):
        state.installer_plan(entry, "rollback")


def _archive(sessions: dict[str, object] | None = None, extra: int = 0) -> bytes:
    out = io.BytesIO()
    profile = {"display_name": "Imported", "avatar": "disc-teal", "level": "O", "subjects": ["physics"],
               "age_band": "13_15", "exam_date": None}  # fmt: skip
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps({"format": FORMAT, "version": 1, "profile": profile}))
        archive.writestr("events.jsonl", "")
        for name in ("settings.json", "consents.json", "notes.json", "study_notes.json"):
            archive.writestr(name, "[]")
        for session_id, session in (sessions or {}).items():
            archive.writestr(f"sessions/{session_id}.json", json.dumps(session))
        for i in range(extra):
            archive.writestr(f"attachments/zeros-{i}.bin", b"\0" * (1024 * 1024))
    return out.getvalue()


def test_sec18_archive_kdf_cost_bounded() -> None:
    """The archive header cannot ask for a key derivation beyond the app's own declared range."""
    sealed = seal_with_passphrase(_archive(), PASSPHRASE, 8192, 1)
    at = len(PASSPHRASE_MAGIC)
    for memory, passes in ((0xFFFFFFFF, 1), (8192, 255), (1, 1)):
        crafted = sealed[:at] + struct.pack(">IB", memory, passes) + sealed[at + 5 :]
        with pytest.raises(ExportError) as refused:
            open_with_passphrase(crafted, PASSPHRASE)
        assert refused.value.code == "archive_invalid"
    assert read_profile_archive(open_with_passphrase(sealed, PASSPHRASE)).manifest["format"] == FORMAT


def test_dat10_archive_unpack_bounded() -> None:
    data = _archive(extra=3)
    assert len(read_profile_archive(data).attachments) == 3
    with pytest.raises(ExportError, match="larger"):
        read_profile_archive(data, max_bytes=2 * 1024 * 1024)
    with pytest.raises(ExportError, match="larger"):
        read_profile_archive(data, max_entries=4)


def test_dat10_archive_cannot_name_sql_columns(tmp_path: Path) -> None:
    """Transcript rows are written only into the table's own columns; a crafted column name is refused and no
    profile is half-imported with it."""
    hostile = {"sessions": [{"session_id": "s1", "x) VALUES (1); DROP TABLE settings; --": 1}], "turns": [],
               "parts": [], "board_steps": [], "checks": []}  # fmt: skip
    path = tmp_path / "crafted.janaprofile"
    path.write_bytes(seal_with_passphrase(_archive({"s1": hostile}), PASSPHRASE, 8192, 1))

    async def go() -> None:
        r = await start_core(tmp_path / "data", worker=False)
        try:
            reply = await Api(r).call(
                "POST", "/v1/profiles/import", {"source": {"kind": "file", "path": str(path)}, "passphrase": PASSPHRASE}
            )
            assert reply.status_code in (400, 409, 422), reply.text
            assert reply.json()["error"]["code"] == "archive_invalid"
        finally:
            await stop_core(r)

    asyncio.new_event_loop().run_until_complete(go())
