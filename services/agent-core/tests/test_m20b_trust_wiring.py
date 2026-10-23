"""M20.b security fixes: the device's revocation list reaches every reader of packs and models, the tutor reads only
installed packs, an older signed model release never replaces a newer one, and a signed document that cannot be
encoded is refused cleanly (SEC-13, SEC-16, SEC-24). Every pack is synthetic and signed by the test hierarchy."""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from agent_core.api.packs import PackDesk
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.config.revocation import RevocationStore
from agent_core.engine.assembly import AppRuntime
from agent_core.store.model_pack_store import ModelPackError, ModelPackStore
from agent_core.store.pack_store import PackStore
from agent_core.store.packs import MANIFEST_SQL, PackRejectedError
from jana_tools import REPO_ROOT
from m20_fixtures import content_pack, model_pack
from signing_service.revocation import dev_revocation_list

DEV = Environment.DEV
MODEL_ID = "mp.synth.8b.q4_k_m.low"
REVOKE = [
    {"key_id": key_id, "revoked_at": "2026-10-14T00:00:00.000Z", "reason": "key_compromise"}
    for key_id in ("key_dev_test", "key_dev_model")
]


def _runtime(data: Path) -> AppRuntime:
    return AppRuntime(Settings(), REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", data)


def test_sec16_revocation_reaches_every_reader(tmp_path: Path) -> None:
    """Once a list revoking the content and model intermediates is adopted, the tutor's content and search indexes,
    the pack list and the installed model store all refuse what those keys signed, with no restart (SEC-16)."""
    data = tmp_path / "data"
    desk = PackDesk(data, DEV, "1.0.0", publish=lambda _: None,
                    revocations=RevocationStore(data, DEV, bundled=None))  # fmt: skip
    content_pack(tmp_path / "phy.pack")
    desk.packs.install(tmp_path / "phy.pack")
    model_pack(tmp_path / MODEL_ID)
    desk.models.install(tmp_path / MODEL_ID)
    runtime = _runtime(data)
    assert runtime.content().fingerprint and runtime.content().rejected == []
    assert list(runtime.knowledge().packs) == ["pack.phy.o"]
    assert [p["signature_ok"] for p in runtime.packs()] == [True]

    assert desk.revocations is not None and desk.revocations.adopt(dev_revocation_list(version=2, revoked=REVOKE))
    assert [name for name, _ in runtime.content().rejected] == ["pack.phy.o"]
    assert not runtime.content().fingerprint
    assert list(runtime.knowledge().packs) == []
    assert [p["signature_ok"] for p in runtime.packs()] == [False]
    with pytest.raises(ModelPackError):
        desk.models.verify(MODEL_ID)
    linked = ModelPackStore(data / "models" / "packs", DEV, "1.0.0", RevocationStore(data, DEV).trust)
    with pytest.raises(ModelPackError):
        linked.verify(MODEL_ID)


def test_sec13_tutor_reads_only_installed_packs(tmp_path: Path) -> None:
    """A signed `.pack` file copied into the pack folder without an install is not read by the tutor: its index is
    built from the installed record, not a folder listing (SEC-13)."""
    data = tmp_path / "data"
    (data / "packs").mkdir(parents=True)
    content_pack(data / "packs" / "pack.phy.o.pack")
    runtime = _runtime(data)
    assert not runtime.content().fingerprint
    assert list(runtime.knowledge().packs) == []
    PackStore(data / "packs", DEV).install(_moved(data / "packs" / "pack.phy.o.pack", tmp_path / "phy.pack"))
    assert runtime.content().fingerprint and list(runtime.knowledge().packs) == ["pack.phy.o"]


def _moved(source: Path, target: Path) -> Path:
    shutil.move(source, target)
    return target


def test_sec24_model_pack_downgrade_refused(tmp_path: Path) -> None:
    """An older signed release of an installed model pack id never replaces the newer one (SEC-24); the same release
    installs again (a repair) and a newer one replaces it."""
    store = ModelPackStore(tmp_path / "models", DEV, "1.0.0")
    old = model_pack(tmp_path / "old" / MODEL_ID, weights=b"OLD-WEIGHTS" * 100)
    _resign(tmp_path / "new" / MODEL_ID, b"NEW-WEIGHTS" * 100, "2026-10-13T09:00:00.000Z")
    store.install(tmp_path / "new" / MODEL_ID)
    with pytest.raises(ModelPackError, match="downgrade"):
        store.install(tmp_path / "old" / MODEL_ID)
    assert store.verify(MODEL_ID)["created_at"] == "2026-10-13T09:00:00.000Z"
    store.install(tmp_path / "new" / MODEL_ID)  # the same release again
    assert old["created_at"] < store.verify(MODEL_ID)["created_at"]


def _resign(folder: Path, weights: bytes, created_at: str) -> None:
    from agent_core.store.model_pack_store import ARTEFACT, file_entry
    from signing_service.hierarchy import dev_signer
    from signing_service.keys import Purpose

    manifest = model_pack(folder, weights=weights)
    unsigned = {k: v for k, v in manifest.items() if k != "signature"}
    unsigned.update(created_at=created_at, files=[file_entry(folder / "model.gguf", "weights", 4096)])
    signed = dev_signer(Purpose.MODEL).sign(ARTEFACT, unsigned, now=created_at)
    (folder / "manifest.json").write_text(json.dumps(signed), encoding="utf-8")


def test_sec13_lone_surrogate_refused_cleanly(tmp_path: Path) -> None:
    """A manifest holding a lone surrogate is refused as an unsigned pack, leaving nothing staged (SEC-13)."""
    path = tmp_path / "evil.pack"
    conn = sqlite3.connect(path)
    conn.execute(MANIFEST_SQL)
    manifest = '{"pack_id":"pack.phy.o","title":"\\ud800","signature":{"alg":"ed25519","key_id":"k","value":"AA=="}}'
    conn.execute("INSERT INTO manifest VALUES (1, ?)", (manifest,))
    conn.commit()
    conn.close()
    store = PackStore(tmp_path / "packs", DEV)
    with pytest.raises(PackRejectedError):
        store.install(path)
    assert not list((tmp_path / "packs" / ".staging").iterdir())
