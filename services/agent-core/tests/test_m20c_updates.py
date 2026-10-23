"""M20.c: app updates, safe application and rollback, channels, release signing and revocation (PLT-14, PLT-15,
PLT-16, SEC-15, SEC-16). Every pack, update and key here is synthetic and signed with the test hierarchy."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.config.revocation import RevocationStore
from agent_core.config.trust import Purpose
from agent_core.store.channels import channel_accepts
from agent_core.store.model_pack_store import CHANNEL, ModelPackError, ModelPackStore
from agent_core.store.pack_store import PackStore
from agent_core.store.packs import PackRejectedError
from agent_core.store.updates import (
    HealthCheck,
    Platform,
    UpdateRefused,
    UpdateState,
    adopt_revocations,
    can_install_now,
    read_update_pack,
)
from jana_tools.release import rollout
from m20_fixtures import (
    PLATFORM,
    content_pack,
    extra_intermediate,
    foreign_trust,
    model_pack,
    tree_digest,
    update_pack,
)
from signing_service.hierarchy import dev_trust
from signing_service.revocation import dev_revocation_list

DEV = Environment.DEV


def _read(path: Path, installed: str = "1.0.0", channel: str = "stable", **kw: object) -> object:
    return read_update_pack(path, installed_version=installed, device_channel=channel, platform=PLATFORM,
                            environment=DEV, trust=kw.get("trust", dev_trust()))  # type: ignore[arg-type]  # fmt: skip


# --- PLT-14 -------------------------------------------------------------------------------------------------------


def plt14_bad_update_signature_refused(tmp_path: Path) -> None:
    """An update pack whose signature does not verify (a forged key, or bytes changed after signing) is refused before
    any file is written; the data folder is byte-for-byte as it was."""
    data = tmp_path / "data"
    state = UpdateState(data)
    state.record_installed("1.0.0")
    before = tree_digest(data)

    forger, _ = foreign_trust()
    forged = update_pack(tmp_path / "forged.janaupdate", "1.1.0", signer=forger)
    with pytest.raises(UpdateRefused) as refused:
        _read(forged)
    assert refused.value.code == "signature"

    good = update_pack(tmp_path / "good.janaupdate", "1.1.0")
    tampered = tmp_path / "tampered.janaupdate"
    raw = bytearray(good.read_bytes())
    at = raw.find(b'"version": "1.1.0"')
    raw[at : at + len(b'"version": "1.1.0"')] = b'"version": "1.9.0"'  # same length: the zip still opens
    tampered.write_bytes(bytes(raw))
    with pytest.raises(UpdateRefused) as refused:
        _read(tampered)
    assert refused.value.code in ("signature", "damaged")
    assert tree_digest(data) == before, "a refused update changed no file"

    verified = _read(good)
    assert verified.summary()["size_bytes"] > 0 and verified.summary()["changes"], "size and changes are shown"


# --- PLT-15 -------------------------------------------------------------------------------------------------------


def _learner(data: Path) -> Path:
    path = data / "profiles" / "01JTESTPROFILE0000000000000" / "learner.db"
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE attempts (id TEXT PRIMARY KEY, outcome TEXT)")
    conn.executemany("INSERT INTO attempts VALUES (?, ?)", [(f"att_{i}", "correct") for i in range(25)])
    conn.commit()
    conn.close()
    return path


def plt15_failed_update_rolls_back(tmp_path: Path) -> None:
    """An update is not installed mid-turn, mock or learner download; at quit the learner store is snapshotted; an
    injected first-launch failure offers the rollback, which restores the previous version and every learner row."""
    data = tmp_path / "data"
    learner = _learner(data)
    old_installer = tmp_path / "jana-1.0.0-setup.exe"
    old_installer.write_bytes(b"synthetic installer 1.0.0")
    state = UpdateState(data)
    state.record_installed("1.0.0", old_installer)
    state.stage(_read(update_pack(tmp_path / "u.janaupdate", "1.1.0")))  # type: ignore[arg-type]

    assert not can_install_now(turn_running=True, mock_active=False, learner_download_active=False)
    assert not can_install_now(turn_running=False, mock_active=True, learner_download_active=False)
    assert not can_install_now(turn_running=False, mock_active=False, learner_download_active=True)
    assert can_install_now(turn_running=False, mock_active=False, learner_download_active=False)

    plan = state.prepare_install()
    assert plan["to_version"] == "1.1.0" and Path(plan["run_installer"]).is_file()
    # The new version migrates the learner store, then fails its first-launch health check (no worker hello).
    conn = sqlite3.connect(learner)
    conn.execute("ALTER TABLE attempts ADD COLUMN migrated INTEGER")
    conn.execute("DELETE FROM attempts WHERE id > 'att_1'")
    conn.commit()
    conn.close()
    outcome = state.first_launch("1.1.0", HealthCheck(core_ready=True, worker_hello=False, touch_generation=None))
    assert outcome == {"offer_rollback": True, "previous_version": "1.0.0"}

    back = state.rollback()
    assert back["version"] == "1.0.0" and Path(back["reinstall"]).read_bytes() == old_installer.read_bytes()
    assert state.read()["installed"]["version"] == "1.0.0"
    conn = sqlite3.connect(learner)
    rows = conn.execute("SELECT count(*) FROM attempts").fetchone()[0]
    columns = [r[1] for r in conn.execute("PRAGMA table_info(attempts)")]
    conn.close()
    assert rows == 25 and "migrated" not in columns, "no learner data was lost and the migration is undone"

    # A passing check commits the update; a content-only machine skips the touch generation.
    state.stage(_read(update_pack(tmp_path / "v.janaupdate", "1.1.1")))  # type: ignore[arg-type]
    state.prepare_install()
    assert state.first_launch("1.1.1", HealthCheck(True, True, None)) == {"offer_rollback": False}
    assert state.read()["installed"]["version"] == "1.1.1"
    with pytest.raises(UpdateRefused):
        state.rollback()


# --- PLT-16 -------------------------------------------------------------------------------------------------------


def test_rollback_after_a_successful_update(tmp_path: Path) -> None:
    data = tmp_path / "data"
    learner = _learner(data)
    old = tmp_path / "old.exe"
    old.write_bytes(b"synthetic original installer")
    state = UpdateState(data)
    state.record_installed("1.0.0", old)
    state.stage(_read(update_pack(tmp_path / "first.janaupdate", "1.1.0")))  # type: ignore[arg-type]
    first = state.prepare_install()
    expected_installer = Path(first["run_installer"]).read_bytes()
    state.first_launch("1.1.0", HealthCheck(True, True, None))
    state.record_installed("1.1.0")  # ordinary subsequent launches keep the rollback installer

    state.stage(_read(update_pack(tmp_path / "second.janaupdate", "1.2.0"), installed="1.1.0"))  # type: ignore[arg-type]
    state.prepare_install()
    with sqlite3.connect(learner) as conn:
        conn.execute("DELETE FROM attempts")
    assert state.first_launch("1.2.0", HealthCheck(True, False, None))["offer_rollback"]
    back = state.rollback()
    assert back["version"] == "1.1.0"
    assert Path(back["reinstall"]).read_bytes() == expected_installer
    with sqlite3.connect(learner) as conn:
        assert conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 25


def plt16_channel_acceptance(tmp_path: Path) -> None:
    """A stable device refuses dev and pilot artefacts (app updates, content packs, model packs); a pilot device
    accepts pilot and stable."""
    assert [channel_accepts("stable", c) for c in ("dev", "pilot", "stable")] == [False, False, True]
    assert [channel_accepts("pilot", c) for c in ("dev", "pilot", "stable")] == [False, True, True]
    assert [channel_accepts("dev", c) for c in ("dev", "pilot", "stable")] == [True, True, True]

    for channel, accepted_on_pilot in (("dev", False), ("pilot", True), ("stable", True)):
        update = update_pack(tmp_path / f"{channel}.janaupdate", "1.1.0", channel=channel)
        if channel != "stable":
            with pytest.raises(UpdateRefused) as refused:
                _read(update, channel="stable")
            assert refused.value.code == "channel"
        else:
            _read(update, channel="stable")
        if accepted_on_pilot:
            _read(update, channel="pilot")

        pack = tmp_path / f"{channel}.pack"
        content_pack(pack, channel=channel)
        stable_store = PackStore(tmp_path / f"stable-{channel}", DEV, channel="stable")
        pilot_store = PackStore(tmp_path / f"pilot-{channel}", DEV, channel="pilot")
        if channel == "stable":
            stable_store.install(pack)
        else:
            with pytest.raises(PackRejectedError):
                stable_store.install(pack)
            assert stable_store.installed("pack.phy.o") is None
        if accepted_on_pilot:
            pilot_store.install(pack)
        else:
            with pytest.raises(PackRejectedError):
                pilot_store.install(pack)

        model = tmp_path / f"mp-{channel}" / "mp.synth.8b.q4_k_m.low"
        model_pack(model, channel=channel)
        models = ModelPackStore(tmp_path / f"models-{channel}", DEV, "1.0.0", channel="stable")
        if channel == "stable":
            models.install(model)
        else:
            with pytest.raises(ModelPackError) as error:
                models.install(model)
            assert error.value.code == CHANNEL


def plt16_rollout_halts_on_crash_gate() -> None:
    """A step whose opt-in crash reports fall below the crash-free gate halts the rollout: the next step is not
    taken however long it waits, until a recorded decision resumes it."""
    settings = Settings()
    soak = rollout.soak_s(settings)
    healthy = rollout.CrashStats(sessions=10_000, crashed_sessions=10)
    failing = rollout.CrashStats(sessions=10_000, crashed_sessions=int(10_000 * (1 - settings.rollout_crash_free_gate))
                                 + 20)  # fmt: skip
    state = rollout.start("1.1.0", now_s=0.0)
    assert rollout.fraction(state, settings) == settings.rollout_steps[0]
    state = rollout.advance(state, soak / 2, healthy, settings)
    assert state.step == 0, "the soak has not passed"
    state = rollout.advance(state, soak, healthy, settings)
    assert state.step == 1 and rollout.fraction(state, settings) == settings.rollout_steps[1]

    halted = rollout.advance(state, soak * 1.5, failing, settings)
    assert halted.halted and halted.step == 1
    later = rollout.advance(halted, soak * 10, healthy, settings)
    assert later.step == 1 and later.halted, "a halted rollout does not take the next step"
    assert rollout.advance(state, soak * 2, rollout.CrashStats(0, 0), settings).step == 1, "no reports, no step"
    resumed = rollout.resume(halted, soak * 3, "fixed by 1.1.1 hotfix")
    assert rollout.advance(resumed, soak * 4, healthy, settings).step == 2
    assert rollout.offered(0.05, rollout.fraction(state, settings)) and not rollout.offered(0.95, 0.5)


def test_d84_free_offline_app_needs_no_licence(tmp_path: Path) -> None:
    """D84: with no licence anywhere on the device, a stable update pack verifies and stages, and stable content and
    model packs install from USB; the default device channel is stable."""
    from agent_core.store.channels import DEFAULT_CHANNEL

    data = tmp_path / "data"
    assert not list(tmp_path.rglob("*licen*")), "no licence file exists"
    state = UpdateState(data)
    state.record_installed("1.0.0")
    staged = state.stage(_read(update_pack(tmp_path / "u.janaupdate", "1.1.0"), channel=DEFAULT_CHANNEL))  # type: ignore[arg-type]
    assert staged.is_file()
    content_pack(tmp_path / "phy.pack")
    PackStore(tmp_path / "packs", DEV, channel=DEFAULT_CHANNEL).install(tmp_path / "phy.pack")
    model = tmp_path / "usb" / "mp.synth.8b.q4_k_m.low"
    model_pack(model)
    ModelPackStore(tmp_path / "models", DEV, "1.0.0", channel=DEFAULT_CHANNEL).install(model)


# --- SEC-15 -------------------------------------------------------------------------------------------------------


def sec15_downgrade_refused(tmp_path: Path) -> None:
    """An update signed with a valid updater key but a version lower than (or equal to) the installed one is refused;
    the rollback of PLT-15 is the only way back."""
    for version in ("1.0.9", "1.1.0"):
        update = update_pack(tmp_path / f"{version}.janaupdate", version)
        with pytest.raises(UpdateRefused) as refused:
            _read(update, installed="1.1.0")
        assert refused.value.code == "downgrade"
    _read(update_pack(tmp_path / "next.janaupdate", "1.1.1"), installed="1.1.0")
    wrong_os = update_pack(tmp_path / "mac.janaupdate", "1.2.0", platform=Platform("macos", "arm64"))
    with pytest.raises(UpdateRefused) as refused:
        _read(wrong_os, installed="1.1.0")
    assert refused.value.code == "platform"


# --- SEC-16 -------------------------------------------------------------------------------------------------------


def sec16_revocation_propagates_offline(tmp_path: Path) -> None:
    """A pack signed by an intermediate is refused once a revocation list naming that intermediate arrives inside an
    unrelated content pack update; an older or forged list changes nothing, and update packs carry lists too."""
    compromised, trust = extra_intermediate(Purpose.CONTENT, "key_dev_content_2", b"m20 compromised content key")
    revocations = RevocationStore(tmp_path / "device", DEV, base=trust)
    store = PackStore(tmp_path / "packs", DEV, revocations=revocations)
    content_pack(tmp_path / "mth.pack", "pack.mth.o", signer=compromised)
    content_pack(tmp_path / "phy-0.1.pack", "pack.phy.o")
    store.install(tmp_path / "mth.pack")
    store.install(tmp_path / "phy-0.1.pack")
    assert store.load_all()[1] == []

    listing = dev_revocation_list(2, [{"key_id": "key_dev_content_2", "revoked_at": "2026-10-13T00:00:00.000Z",
                                       "reason": "key_compromise"}])  # fmt: skip
    content_pack(tmp_path / "phy-0.2.pack", "pack.phy.o", "0.2.0", signed_files={"signed/revocation.json": listing})
    store.install(tmp_path / "phy-0.2.pack")  # the physics update, which says nothing about maths
    assert revocations.version() == 2

    loaded, refused = store.load_all()
    assert "pack.phy.o" in loaded and [pack for pack, _ in refused] == ["pack.mth.o"], "the maths pack is refused"
    assert "revoked" in refused[0][1]
    content_pack(tmp_path / "mth-again.pack", "pack.mth.o", "0.3.0", signer=compromised)
    with pytest.raises(PackRejectedError):
        store.install(tmp_path / "mth-again.pack")

    restarted = PackStore(tmp_path / "packs", DEV, revocations=RevocationStore(tmp_path / "device", DEV, base=trust))
    assert [p for p, _ in restarted.load_all()[1]] == ["pack.mth.o"], "the revocation survives a restart"

    assert not revocations.adopt(dev_revocation_list(1)), "an older list never shrinks what is revoked"
    forged = dict(listing, version=3, revoked=[])
    assert not revocations.adopt(forged) and revocations.version() == 2

    model_key = {"key_id": "key_dev_model", "revoked_at": "2026-10-13T00:00:00.000Z", "reason": "key_compromise"}
    newer = dev_revocation_list(3, [*listing["revoked"], model_key])
    update = _read(update_pack(tmp_path / "u.janaupdate", "1.1.0", revocation_list=newer))
    assert adopt_revocations(update, revocations) and revocations.version() == 3  # type: ignore[arg-type]
    model = tmp_path / "mp" / "mp.synth.8b.q4_k_m.low"
    model_pack(model)
    models = ModelPackStore(tmp_path / "models", DEV, "1.0.0", trust=revocations.trust())
    with pytest.raises(ModelPackError):
        models.install(model)
