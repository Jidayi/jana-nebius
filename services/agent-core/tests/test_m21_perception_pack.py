"""Executable packs are authorized by updater keys, staged atomically and reverified before launch."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config.environments import Environment
from agent_core.config.trust import Purpose
from agent_core.store.perception_packs import (
    ARTEFACT,
    PerceptionPackError,
    PerceptionPackStore,
    build_manifest,
    target,
)
from signing_service.hierarchy import dev_signer

NOW = "2026-10-14T00:00:00.000Z"


def pack(root: Path, *, signer: Purpose = Purpose.UPDATER, licence: str = "MIT") -> tuple[Path, dict[str, Any]]:
    root.mkdir()
    (root / "worker").write_bytes(b"synthetic fixture; never executed")
    (root / "worker").chmod(0o755)
    (root / "LICENSE").write_text("Synthetic fixture, MIT; no external code")
    os_name, arch = target()
    unsigned = build_manifest(
        root,
        pack_id=f"pp.printed.v1.{os_name}.{arch}",
        release_version="1.0.0",
        min_app_version="0.0.0",
        channel="dev",
        executable="worker",
        hardware_classes=["low", "mid", "high"],
        licences=[{"id": licence, "attribution": "Synthetic fixture", "path": "LICENSE"}],
        report_id="synthetic-passing-report",
        created_at=NOW,
    )
    # Wrong-purpose fixture must be signed under a model artefact before relabelling, since the signer itself
    # correctly refuses to sign perception_pack using a model key.
    manifest = dev_signer(signer).sign(ARTEFACT if signer == Purpose.UPDATER else "model_manifest", unsigned, now=NOW)
    (root / "manifest.json").write_text(json.dumps(manifest))
    return root, manifest


def test_atomic_install_and_hash_recheck_before_every_command(tmp_path: Path) -> None:
    source, manifest = pack(tmp_path / "source")
    store = PerceptionPackStore(tmp_path / "installed", Environment.DEV, "1.0.0")
    pack_id = store.install(source)
    assert store.command("low") == (str((store.root / pack_id / "worker").resolve()),)
    assert store.install(source) == pack_id
    assert not list((store.root / ".staging").iterdir())
    (store.root / pack_id / "worker").write_bytes(b"tampered")
    assert store.command("low") is None
    with pytest.raises(PerceptionPackError):
        store.verify(store.root / pack_id)
    assert manifest["perception_pack_id"] == pack_id


@pytest.mark.parametrize("case", ["model_key", "production_test_root", "unlisted", "link", "gpl", "wrong_platform"])
def test_invalid_or_untrusted_runtime_never_becomes_a_command(tmp_path: Path, case: str) -> None:
    source, manifest = pack(
        tmp_path / "source",
        signer=Purpose.MODEL if case == "model_key" else Purpose.UPDATER,
        licence="GPL-3.0-only" if case == "gpl" else "MIT",
    )
    environment = Environment.PRODUCTION if case == "production_test_root" else Environment.DEV
    store = PerceptionPackStore(tmp_path / "installed", environment, "1.0.0")
    if case == "unlisted":
        (source / "extra").write_text("not declared")
    if case == "link":
        (source / "link").symlink_to(source / "worker")
    if case == "wrong_platform":
        manifest["arch"] = "x86_64" if manifest["arch"] == "arm64" else "arm64"
        unsigned = {k: v for k, v in manifest.items() if k != "signature"}
        (source / "manifest.json").write_text(json.dumps(dev_signer(Purpose.UPDATER).sign(ARTEFACT, unsigned, now=NOW)))
    with pytest.raises(PerceptionPackError):
        store.install(source)
    assert store.command("mid") is None


def test_install_folder_route_and_runtime_callback_share_verified_pack_store(tmp_path: Path) -> None:
    from agent_core.api.packs import PackDesk

    source, manifest = pack(tmp_path / "source")
    events = []
    desk = PackDesk(tmp_path / "data", Environment.DEV, "1.0.0", events.append)
    installed = desk.install_source({"kind": "file", "path": str(source)}, "job_" + "0" * 26)
    assert installed == [manifest["perception_pack_id"]]
    assert desk.perception.command("mid") is not None
    assert events[-1]["state"] == "done"
    assert desk.remove(installed[0]) and desk.perception.command("mid") is None


def test_signing_requires_passing_release_report(tmp_path: Path) -> None:
    from agent_core.store.perception_packs import sign_pack

    _source, manifest = pack(tmp_path / "source")
    with pytest.raises(PerceptionPackError, match="release gates"):
        sign_pack(manifest, lambda kind, body: dev_signer(Purpose.UPDATER).sign(kind, body, now=NOW), lambda _: False)
