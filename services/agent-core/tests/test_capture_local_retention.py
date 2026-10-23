"""INP-20: local-only routing and fixed on-disk expiry; synthetic OCR/model boundaries."""

from __future__ import annotations

from pathlib import Path

import pytest
from agent_core.api.errors import ApiError
from agent_core.store.retention import DAY_MS, run_retention
from engine_harness import close
from jana_tools.harness.egress import offline_run
from learner_harness import Clock, make_learner
from test_m10d_retention import device_db
from test_m11f_vision import images_in, reader_engine, run
from test_m21_capture_drafts import QUAD, create, setup


def inp20_photo_local_and_expires(tmp_path: Path) -> None:
    # The configured cloud reader is a trap. Profile policy disables it; preprocessing/OCR and provider
    # responses are synthetic, but CaptureDesk, routing, SQLite, image files and retention are production code.
    engine, local, cloud = reader_engine(tmp_path / "reader", cloud_on=False)

    async def check() -> None:
        core, boundary, desk, sid = setup(tmp_path)
        clock = Clock()
        core.clock_ms = clock
        boundary.read_photo = engine.read_photo
        learner = make_learner(core.store.conn, clock=clock)
        device = device_db()
        try:
            with offline_run() as network:
                cap = create(desk, sid)["capture_id"]
                await desk.crop(cap, {"corners": QUAD, "rotation": 0})
                desk.read(cap, {"send_to_cloud": True})  # even forged permission cannot enable the cloud tier
                await desk.tasks[cap]
                record = desk.get(cap)
                assert record["status"] == "awaiting_confirmation"
                assert record["egress"] == {"left_device": False, "destination": "none"}
                assert images_in(local) and not cloud.requests
                desk.confirm(cap, {"text": "Find x if x+5=15."})
                assert cap not in desk.raw
                expiry = core.store.conn.execute(
                    "SELECT expires_at FROM captures WHERE capture_id=?", (cap,)
                ).fetchone()[0]
                assert expiry == clock.now + core.settings.retention_attachment_days * DAY_MS
                files = list(desk.root().glob("*.jpg"))
                assert len(files) == 1
                for now in (expiry - 1, expiry):
                    clock.now = now
                    if now < expiry:
                        desk.put(desk.get(cap))  # viewing/updating a capture must not renew its TTL
                    run_retention(
                        core.store.conn,
                        device,
                        core.settings,
                        now_ms=now,
                        profile_dir=tmp_path,
                        log=learner.log,
                        fold=learner.projector.apply,
                    )
                    if now < expiry:
                        assert files[0].exists() and desk.get(cap)["status"] == "confirmed"
                    else:
                        assert not files[0].exists()
                        assert core.store.conn.execute("SELECT count(*) FROM attachments").fetchone()[0] == 0
                        assert core.store.conn.execute("SELECT count(*) FROM captures").fetchone()[0] == 0
                        with pytest.raises(ApiError, match="not_found"):
                            desk.get(cap)
                assert network.attempts == []
        finally:
            await desk.close()
            device.close()
            core.store.conn.close()

    try:
        run(check())
    finally:
        run(close(engine))
