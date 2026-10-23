"""Real HTTP commands with signed synthetic updates; no installer is executed and no network is needed."""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest
from agent_core.api.app import create_app
from agent_core.api.core import CoreService
from agent_core.api.errors import ApiError
from agent_core.api.security import LaunchSecret
from agent_core.api.updates import UpdateDesk
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.contracts import errors as contract_errors
from agent_core.engine.events import new_id
from agent_core.store.sessions import SessionStore
from agent_core.store.updates import HealthCheck, UpdateRefused
from m20_fixtures import PLATFORM, foreign_trust, tree_digest, update_pack
from signing_service.hierarchy import dev_trust
from signing_service.service import sign_kit


def desk_at(root: Path) -> tuple[CoreService, UpdateDesk, list[dict[str, Any]]]:
    core = CoreService(Settings(), lambda _: None, SessionStore(root / "sessions"))  # type: ignore[arg-type,return-value]
    frames: list[dict[str, Any]] = []
    desk = UpdateDesk(core, root, Environment.DEV, "1.0.0", platform=PLATFORM, trust=dev_trust(), say=frames.append)
    old = root / "original.exe"
    old.write_bytes(b"synthetic previous installer")
    desk.state.record_installed("1.0.0", old)
    core.update_desk = desk
    return core, desk, frames


def test_http_update_staging_restart_and_quiescence(tmp_path: Path) -> None:
    async def scenario() -> None:
        core, desk, frames = desk_at(tmp_path / "data")
        pack = update_pack(tmp_path / "new.janaupdate", "1.1.0")
        app = create_app(core, LaunchSecret("synthetic-launch-token"), lambda: 8787)
        headers = {"authorization": "Bearer synthetic-launch-token", "origin": "tauri://localhost"}
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8787", headers=headers
        ) as client:
            key = new_id("cli")
            first = await client.post("/v1/updates/install", json={"source": {"kind": "usb", "path": str(pack)}},
                                      headers={"idempotency-key": key})  # fmt: skip
            assert first.status_code == 202, first.text
            again = await client.post("/v1/updates/install", json={"source": {"kind": "usb", "path": str(pack)}},
                                      headers={"idempotency-key": key})  # fmt: skip
            assert again.json() == first.json() and len(core.jobs) == 1
            await desk.close()
            status = (await client.get("/v1/updates")).json()
            assert contract_errors("api/commands#/$defs/UpdateStatus", status) == []
            assert status["checks"] == "usb_or_school_only" and status["staged"]["version"] == "1.1.0"
            assert status["apply_blocked"] is None
            job = (await client.get(f"/v1/jobs/{first.json()['job_id']}")).json()
            assert job["state"] == "done" and contract_errors("api/commands#/$defs/Job", job) == []
            assert core.app_channel.seq == 1 and core.app_channel.rejected == []
            restart_key = new_id("cli")
            response = await client.post("/v1/updates/restart-now", headers={"idempotency-key": restart_key})
            assert response.status_code == 204 and frames == [{"type": "control.exit_requested"}]
            response = await client.post("/v1/updates/restart-now", headers={"idempotency-key": restart_key})
            assert response.status_code == 204 and len(frames) == 1
            refused = await client.post("/v1/updates/install", json={"source": {"kind": "file", "path": str(pack)}},
                                        headers={"idempotency-key": new_id("cli")})  # fmt: skip
            assert refused.status_code == 503
        desk.hold_exit()
        await core.shutdown()
        assert len(frames) == 1, "no installer handoff before stores are closed"
        await desk.prepare_exit()
        assert frames[-1]["type"] == "control.update_install"
        assert contract_errors("control/control#/$defs/ToShell", frames[-1]) == []
        assert desk.state.read()["phase"] == "installing"

    asyncio.run(scenario())


def test_update_is_blocked_during_mock_and_download(tmp_path: Path) -> None:
    async def scenario() -> None:
        core, desk, frames = desk_at(tmp_path / "data")
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        core.mock_active = lambda: True
        with pytest.raises(ApiError) as refused:
            desk.request_exit("restart-now")
        assert refused.value.details == {"reason": "mock_running"} and frames == []
        desk.hold_exit()
        core.mock_active = lambda: False
        await desk.prepare_exit()
        assert frames == [], "ending the mock during shutdown must not undo the latched install refusal"

    asyncio.run(scenario())


def test_failed_first_launch_quarantines_writes_and_can_roll_back(tmp_path: Path) -> None:
    async def scenario() -> None:
        core, desk, frames = desk_at(tmp_path / "data")
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        desk.state.prepare_install()
        desk.app_version = "1.1.0"
        desk.check_first_launch(HealthCheck(True, False, None))
        assert core.recovery_required and desk.status()["rollback_offered"] == "1.0.0"
        with pytest.raises(ApiError, match="request_conflict") as refused:
            core._guard()
        assert refused.value.details == {"reason": "update_recovery_required"}
        desk.request_exit("rollback")
        desk.hold_exit()
        await core.shutdown()
        await desk.prepare_exit()
        assert frames[-1]["action"] == "rollback" and frames[-1]["version"] == "1.0.0"

    asyncio.run(scenario())


def test_forged_update_changes_no_files(tmp_path: Path) -> None:
    async def scenario() -> None:
        core, desk, _ = desk_at(tmp_path / "data")
        before = tree_digest(desk.state.data_dir)
        forger, _ = foreign_trust()
        desk.stage(update_pack(tmp_path / "forged.janaupdate", "1.1.0", signer=forger))
        await desk.close()
        assert next(iter(core.jobs.values()))["state"] == "failed"
        assert tree_digest(desk.state.data_dir) == before

    asyncio.run(scenario())


def test_wal_snapshot_and_corruption_refusal(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, desk, _ = desk_at(tmp_path / "data")
        database = desk.state.data_dir / "device.db"
        conn = sqlite3.connect(database)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA wal_autocheckpoint=0")
        conn.execute("CREATE TABLE evidence (id INTEGER)")
        conn.executemany("INSERT INTO evidence VALUES (?)", [(i,) for i in range(25)])
        conn.commit()
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        desk.state.prepare_install()
        conn.close()
        held = desk.state.read()
        saved = desk.state.local_path(held["snapshot"]) / "device.db"
        with sqlite3.connect(saved) as snapshot:
            assert snapshot.execute("SELECT count(*) FROM evidence").fetchone()[0] == 25
        desk.state.first_launch("1.1.0", HealthCheck(False, False, None))
        saved.write_bytes(b"damaged snapshot")
        before = database.read_bytes()
        with pytest.raises(UpdateRefused, match="snapshot is missing or changed"):
            desk.state.rollback()
        assert database.read_bytes() == before

    asyncio.run(scenario())


def test_signed_current_installer_enables_rollback_without_replacing_staged_update(tmp_path: Path) -> None:
    async def scenario() -> None:
        _, desk, frames = desk_at(tmp_path / "data")
        held = desk.state.read()
        held["installed"].update(installer=None, sha256=None)
        desk.state._write(held)
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        assert desk.status()["apply_blocked"] == "rollback_unavailable"
        before = desk.state.read()["staged"]
        desk.stage(update_pack(tmp_path / "current.janaupdate", "1.0.0"))
        await desk.close()
        assert desk.state.read()["staged"] == before and desk.status()["apply_blocked"] is None
        assert desk.state.read()["installed"]["manifest"]["version"] == "1.0.0" and frames == []

    asyncio.run(scenario())


def test_usb_kit_preserves_a_verified_current_installer(tmp_path: Path) -> None:
    _, desk, frames = desk_at(tmp_path / "data")
    kit = tmp_path / "kit"
    kit.mkdir()
    update_pack(kit / "current.janaupdate", "1.0.0")
    sign_kit(kit, [("current.janaupdate", "app_update")])
    desk.cache_from_kit(kit)
    assert desk.state.read()["installed"]["manifest"]["version"] == "1.0.0"
    assert desk.state.read()["staged"] is None and frames == []


def test_file_selection_does_not_authorize_an_update_at_quit(tmp_path: Path) -> None:
    async def scenario() -> None:
        core, desk, frames = desk_at(tmp_path / "data")
        desk.stage(update_pack(tmp_path / "new.janaupdate", "1.1.0"))
        await desk.close()
        desk.hold_exit()
        await desk.prepare_exit()
        assert desk.state.read()["phase"] == "idle" and frames == []
        assert desk.status()["staged"]["accepted"] is False
        desk.request_exit("install-at-quit")
        assert not core.shutting_down and frames == []
        assert desk.status()["staged"]["accepted"] is True
        await core.shutdown()
        await desk.prepare_exit()
        assert frames[-1]["type"] == "control.update_install"

    asyncio.run(scenario())
