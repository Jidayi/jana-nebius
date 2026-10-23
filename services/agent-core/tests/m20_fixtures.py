"""Synthetic packs, model packs and update packs for the M20 tests. Every artefact here is made up for the tests and
signed with the test hierarchy (or with throwaway keys a test certifies itself); none is a real release."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from agent_core.config.trust import Certificate, Purpose, RootKey, TrustStore
from agent_core.store.model_pack_store import ARTEFACT as MODEL_ARTEFACT
from agent_core.store.model_pack_store import file_entry
from agent_core.store.packs import TABLES, embedded_sha256, table_sha256, write_pack
from agent_core.store.updates import Platform, update_manifest, write_update_pack
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from signing_service.hierarchy import (
    DEV_NOT_AFTER,
    DEV_NOT_BEFORE,
    Signer,
    dev_root,
    dev_signer,
    dev_trust,
    issue_certificate,
    public_b64,
)
from signing_service.keys import dev_root_key

SIGNED_AT = "2026-10-12T09:00:00.000Z"
REQUIRED_TABLES = ("curriculum_nodes", "kcs", "lessons", "worked_examples", "items", "misconceptions", "diagrams",
                   "conventions")  # fmt: skip
PLATFORM = Platform("windows", "x86_64")
Tables = dict[str, list[dict[str, Any]]]


def content_manifest(pack_id: str, version: str, tables: Tables, channel: str = "stable",
                     **extra: Any) -> dict[str, Any]:  # fmt: skip
    subject, level = pack_id.split(".")[1:3]
    return {"pack_id": pack_id, "subject": subject, "level": level, "title": f"Synthetic {subject} pack",
            "version": version, "schema_version": "1.0.0", "curriculum_version": "1.0.0", "min_app_version": "0.0.0",
            "created_at": SIGNED_AT, "channel": channel, "publisher": {"id": "pub_jana", "kind": "publisher"},
            "languages": ["en"], **extra,
            "tables": [{"name": t, "sha256": table_sha256(t, tables[t]), "rows": len(tables[t])}
                       for t in TABLES if t in tables]}  # fmt: skip


def empty_tables() -> Tables:
    return {t: [] for t in REQUIRED_TABLES}


def content_pack(path: Path, pack_id: str = "pack.phy.o", version: str = "0.1.0", *, signer: Signer | None = None,
                 channel: str = "stable", signed_files: Mapping[str, Mapping[str, Any]] | None = None,
                 tables: Tables | None = None, title: str | None = None) -> dict[str, Any]:  # fmt: skip
    """Write a signed synthetic content pack (empty record tables pass the contract) and return its manifest."""
    tables = tables if tables is not None else empty_tables()
    extra: dict[str, Any] = {}
    if signed_files:
        extra["embedded_signed_files"] = [
            {"kind": doc["kind"], "path": name, "sha256": embedded_sha256(doc), "version": str(doc["version"])}
            for name, doc in sorted(signed_files.items())
        ]  # fmt: skip
    manifest = content_manifest(pack_id, version, tables, channel, **extra)
    if title:
        manifest["title"] = title
    signed = (signer or dev_signer()).sign("content_pack", manifest, now=SIGNED_AT)
    write_pack(path, signed, tables, signed_files)
    return signed


# --- extra intermediates of the test root (a compromised key needs a key to stand for it) --------------------------


def extra_intermediate(purpose: Purpose, key_id: str, seed: bytes) -> tuple[Signer, TrustStore]:
    """A second intermediate of the test root, and the dev trust store that also knows it."""
    key = Ed25519PrivateKey.from_private_bytes(seed.ljust(32, b"\0")[:32])
    certificate = issue_certificate(dev_root(), dev_root_key().sign, key_id, purpose, public_b64(key),
                                    DEV_NOT_BEFORE, DEV_NOT_AFTER)  # fmt: skip
    base = dev_trust()
    store = TrustStore(base.roots, {**base.certificates, key_id: certificate}, base.revoked)
    return Signer(certificate, key.sign), store


def foreign_trust() -> tuple[Signer, TrustStore]:
    """A signer whose root this build does not bundle: its signatures are refused like a forgery."""
    root_key = Ed25519PrivateKey.from_private_bytes(b"m20 foreign root".ljust(32, b"\0"))
    root = RootKey("key_root_foreign", public_b64(root_key), "test", DEV_NOT_BEFORE, DEV_NOT_AFTER)
    key = Ed25519PrivateKey.from_private_bytes(b"m20 foreign updater".ljust(32, b"\0"))
    cert: Certificate = issue_certificate(root, root_key.sign, "key_foreign_updater", Purpose.UPDATER,
                                          public_b64(key), DEV_NOT_BEFORE, DEV_NOT_AFTER)  # fmt: skip
    return Signer(cert, key.sign), TrustStore({root.key_id: root}, {cert.key_id: cert})


# --- model packs ----------------------------------------------------------------------------------------------------


def model_pack(folder: Path, model_pack_id: str = "mp.synth.8b.q4_k_m.low", *, weights: bytes | None = None,
               signer: Signer | None = None, chunk_bytes: int = 4096, licence: str = "Apache-2.0",
               adapter_for: dict[str, str] | None = None, channel: str = "stable",
               min_app_version: str = "0.0.0") -> dict[str, Any]:  # fmt: skip
    """A signed synthetic model pack folder. The "weights" are random bytes standing for a GGUF file."""
    folder.mkdir(parents=True, exist_ok=True)
    payload = weights if weights is not None else os.urandom(3 * chunk_bytes + 123)
    role = "lora_adapter" if adapter_for else "weights"
    name = "adapter.gguf" if adapter_for else "model.gguf"
    (folder / name).write_bytes(payload)
    manifest: dict[str, Any] = {
        "model_pack_id": model_pack_id, "manifest_version": 1, "hardware_class": model_pack_id.split(".")[4],
        "tiers": ["fast", "strong"], "family": model_pack_id.split(".")[1],
        "quantisation": model_pack_id.split(".")[3], "files": [file_entry(folder / name, role, chunk_bytes)],
        "chunk_bytes": chunk_bytes, "channel": channel,
        "licence": {"id": licence, "attribution": f"Synthetic {model_pack_id} weights, made up for tests."},
        "recommended": {"context": 8192, "sampling": {"temperature": 0.6}, "thinking": False},
        "min_app_version": min_app_version, "evaluation_report_id": "evr_synthetic_0001", "created_at": SIGNED_AT,
    }  # fmt: skip
    if adapter_for:
        manifest.update(adapter_for=adapter_for, tuned_from=adapter_for["model_pack_id"],
                        training_run_id="trn_synthetic_0001", model_card_ref="cards/synthetic.md")  # fmt: skip
        manifest["licence"]["modification_notice"] = "Fine-tuned from the base pack; synthetic test data."
    signed = (signer or dev_signer(Purpose.MODEL)).sign(MODEL_ARTEFACT, manifest, now=SIGNED_AT)
    (folder / "manifest.json").write_text(__import__("json").dumps(signed, indent=1), encoding="utf-8")
    return signed


# --- update packs ---------------------------------------------------------------------------------------------------


def update_pack(path: Path, version: str, *, channel: str = "stable", signer: Signer | None = None,
                platform: Platform = PLATFORM, revocation_list: Mapping[str, Any] | None = None) -> Path:  # fmt: skip
    """A signed `.janaupdate` holding a made-up installer."""
    installer = path.with_name(f"jana-{version}-setup.exe")
    installer.write_bytes(b"synthetic installer " + version.encode() * 1000)
    manifest = update_manifest(version, channel, platform, installer, ["update.changes.fixes"], SIGNED_AT,
                               revocation_list)  # fmt: skip
    signed = (signer or dev_signer(Purpose.UPDATER)).sign("offline_update_pack", manifest, now=SIGNED_AT)
    write_update_pack(path, signed, installer)
    installer.unlink()
    return path


def tree_digest(root: Path) -> dict[str, bytes]:
    """Every file under `root` with its bytes: two digests are equal when nothing changed."""
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}
