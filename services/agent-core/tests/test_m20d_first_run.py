"""M20.d: first run and recovery over the local API (PLT-17, UXS-10, UXS-47; D84, D86, D87).

First run is the one step of TABLE PLT-17a: students by name, then "Start learning", everything else a default of
TABLE PLT-17b. There is no PIN or recovery code anywhere, so nothing forgotten can lock a family out. The scripted
first run is the API sequence the app sends, with `/v1/setup` (a proposed contract addition, D72) recording where it
stands; the screens are tested in the desktop app (apps/desktop/test/first-run.test.tsx). Learners are synthetic.
Where a named test needs a client screen that is not built yet, it runs the core's whole path and then skips, naming
what is missing."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from pathlib import Path
from typing import Any

import pytest
from agent_core.contracts import errors as contract_errors
from agent_core.store.integrity import quick_check
from agent_core.store.keystore import INSTALL_MARKER
from api_harness import STATEMENT, start_core, stop_core
from jana_tools.harness.egress import offline_run
from licence_harness import SETTINGS
from test_m10a_profiles import Api, code
from test_m10d_deletion_export import PASSPHRASE, _export, _session_with_turn, _settings
from test_m20b_packs import _core, _kit


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def setup_errors(found: Any) -> list[str]:
    return contract_errors("api/commands#/$defs/SetupState", found)


async def done(api: Api) -> Any:
    return await api.call("PUT", "/v1/setup", {"step": "done"})


def by_name(name: str) -> dict[str, Any]:
    """What the app sends for a student added by name: the name and the defaults of TABLE PLT-17b for a computer with
    the physics O level pack (every installed subject at its level, a minor age band, no exam month)."""
    return {"display_name": name, "avatar": "avatar-1", "level": "O", "age_band": "13_15", "subjects": ["physics"]}


async def scripted_first_run(api: Api) -> list[str]:
    """First run as the app sends it; returns the step the core reports before and after "Start learning"."""
    seen = [(await api.call("GET", "/v1/setup")).json()["step"]]
    await api.add(by_name("Ama"))  # the one step: a name
    finished = await done(api)  # "Start learning"
    assert setup_errors(finished.json()) == []
    seen.append(finished.json()["step"])
    return seen


# --- PLT-17 ----------------------------------------------------------------------------------------------------------


def plt17_first_run_offline(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS)
        try:
            api = Api(r)
            with offline_run() as egress:
                steps = await scripted_first_run(api)
                features = (await api.call("GET", "/v1/connectivity")).json()["features"]
            assert steps == ["students", "done"]
            assert egress.attempts == []  # no non-loopback socket was opened
            assert features and not any(f["enabled"] for f in features.values())  # every online feature starts off
        finally:
            await stop_core(r)

    run(scenario())


def plt17_minimal_first_run(tmp_path: Path) -> None:
    """After one student name the core is set up: no PIN, recovery code, activation code, licence or account was
    asked for, and every other setting equals TABLE PLT-17b. This is the core's side; the screens' side, with the same
    name, runs in the desktop app (apps/desktop/test/first-run.test.tsx)."""

    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            assert await scripted_first_run(api) == ["students", "done"]
            assert (await api.call("GET", "/v1/licence")).json()["state"] == "none"  # the free product is all there
            (ama,) = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            assert set(ama) == {"profile_id", "display_name", "avatar"}  # no PIN anywhere (D86)
            token = await api.token(ama["profile_id"])
            settings = (await api.call("GET", f"/v1/profiles/{ama['profile_id']}/settings", profile=token)).json()
            assert "solution_policy" not in settings  # on request, not a setting (D26, D87)
            assert r.runtime.directory.age_band(ama["profile_id"]) == "13_15"  # a minor band
            features = (await api.call("GET", "/v1/connectivity")).json()["features"]
            assert not any(f["enabled"] for f in features.values())
            models = (await api.call("GET", "/v1/models")).json()
            assert models["assignment"]["strong"] == models["recommended"]["strong"]  # the recommended model
        finally:
            await stop_core(r)

    run(scenario())


def test_setup_resumes_and_moves_forward_only(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            assert (await api.call("GET", "/v1/setup")).json()["step"] == "students"
            assert code(await done(api)) == "validation_failed"  # a student first
            await api.add(by_name("Ama"))
        finally:
            await stop_core(r)
        again = await start_core(tmp_path, settings=SETTINGS, worker=False)  # quit mid-setup, start again
        try:
            api = Api(again)
            shown = (await api.call("GET", "/v1/setup")).json()
            assert (shown["step"], shown["profiles"], shown["completed_at"]) == ("students", 1, None)  # Ama is kept
            assert (await done(api)).json()["step"] == "done"
            assert (await done(api)).json()["step"] == "done"  # once done, it stays done
            for wrong in ("students", "adult"):
                assert code(await api.call("PUT", "/v1/setup", {"step": wrong})) == "validation_failed"
        finally:
            await stop_core(again)

    run(scenario())


def test_setup_step_schema_is_forward_only() -> None:
    from agent_core.contracts import document

    definitions = document("api/commands")["$defs"]
    assert definitions["SetupStep"]["properties"]["step"]["enum"] == ["done"]  # the step only moves forward
    assert definitions["SetupState"]["properties"]["step"]["enum"] == ["students", "done"]  # one step (D86)
    assert not [d for d in definitions if "Adult" in d or "Reset" in d]  # D86: no adult PIN to reset


# --- UXS-10 ----------------------------------------------------------------------------------------------------------


def uxs10_first_run_time(tmp_path: Path) -> None:
    """The scripted first run's own work, excluding copying model files, within the UXS-10 budget. This measures the
    core on the machine running the tests; the low-class reference laptop's figure comes from the device lab."""

    async def scenario() -> float:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            began = time.monotonic()
            assert await scripted_first_run(Api(r)) == ["students", "done"]
            return time.monotonic() - began
        finally:
            await stop_core(r)

    assert run(scenario()) < SETTINGS.first_run_budget_s


def uxs10_offline_first_run(tmp_path: Path) -> None:
    """With networking disabled, first run completes with the tutor model from the USB kit (the bundle goes through
    the same install), and nothing on the way offers a download: the model's download answers `feature_disabled`
    while downloads are off, as they are on a fresh install. The screens' side, with the same name, runs in the
    desktop app. The background install's trigger is not wired yet, so the test then skips."""

    async def scenario() -> None:
        r, desk = await _core(tmp_path, downloads=False)
        try:
            api = Api(r)
            kit = _kit(tmp_path)
            with offline_run() as egress:
                assert (await api.call("GET", "/v1/setup")).json()["step"] == "students"
                await api.add(by_name("Ama"))
                reply = await api.call("POST", "/v1/packs/install", {"source": {"kind": "usb", "path": str(kit)}})
                assert reply.status_code == 202 and reply.json()["queued_until_online"] is False, reply.text
                assert (await done(api)).json()["step"] == "done"  # "Start learning" never waits for the copy
                for _ in range(500):
                    job = (await api.call("GET", f"/v1/jobs/{reply.json()['job_id']}")).json()
                    if job["state"] in ("done", "failed"):
                        break
                    await asyncio.sleep(0.02)
                assert job["state"] == "done", job
                (model,) = desk.models.installed()
                download = await api.call("POST", f"/v1/models/{model['model_pack_id']}/download")
                features = (await api.call("GET", "/v1/connectivity")).json()["features"]
            assert model["state"] == "installed"
            assert code(download) == "feature_disabled"  # no download-only path while downloads are off
            assert not features["downloads"]["enabled"]
            assert egress.attempts == []
        finally:
            await stop_core(r)

    run(scenario())
    # The core installs from the kit offline and first run finishes. Not built: nothing starts that install by itself
    # at "Start learning" (UXS-10: the recommended model is installed in the background, without asking), because the
    # core is not told where the bundled models or the kit are (a launch or control-channel field the contract lacks),
    # and the client does not record "Start learning" with `PUT /v1/setup`.
    pytest.skip(
        "the background install of the recommended model from the bundle or USB kit at 'Start learning' is not "
        "wired: the kit's location is not passed to the core, and the client does not call PUT /v1/setup"
    )


# --- UXS-47 ----------------------------------------------------------------------------------------------------------


def _damage(path: Path) -> None:
    """Scribble over the database's first page after the header, as a failing disk would."""
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    data = bytearray(path.read_bytes())
    data[100:4096] = b"\xa5" * (4096 - 100)
    path.write_bytes(bytes(data))


def _learner_files(data_dir: Path) -> set[str]:
    return {p.relative_to(data_dir).as_posix() for p in (data_dir / "profiles").rglob("*") if p.is_file()}


def test_damaged_profile_store_never_stops_the_core(tmp_path: Path) -> None:
    """A `device.db` that fails its integrity check is set aside, never deleted, and the core starts: the students are
    listed again from their own files, their profile rows are unchanged, every online feature is off and the health
    says the store was repaired (DAT-13, UXS-47, D84). Before this, the core did not start at all."""

    async def first() -> tuple[list[str], list[Any]]:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            students = [await api.add(by_name(name)) for name in ("Ama", "Kofi")]
            with r.runtime.directory.open_learner(students[0]) as conn:
                return students, conn.execute("SELECT * FROM profile").fetchall()
        finally:
            await stop_core(r)

    students, profile = run(first())
    files = _learner_files(tmp_path)
    _damage(tmp_path / "device.db")

    async def after() -> None:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            listed = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            assert [p["profile_id"] for p in listed] == students
            assert [p["display_name"] for p in listed] == ["Ama", "Kofi"]
            with r.runtime.directory.open_learner(students[0]) as conn:
                assert conn.execute("SELECT * FROM profile").fetchall() == profile
            assert (await api.unlock(students[0])).status_code == 200
            assert (await api.call("GET", "/v1/health")).json()["components"]["learner_store"] == "degraded"
            features = (await api.call("GET", "/v1/connectivity")).json()["features"]
            assert not any(f["enabled"] for f in features.values())
        finally:
            await stop_core(r)

    run(after())
    kept = [p for p in tmp_path.glob("device.db.damaged-*") if not p.name.endswith(("-wal", "-shm"))]
    assert len(kept) == 1 and kept[0].stat().st_size > 0  # never deleted without a confirmed action
    assert files <= _learner_files(tmp_path)


def test_a_locked_store_is_not_called_damaged(tmp_path: Path) -> None:
    """A database another process holds locked passes the open check, so a healthy store is never set aside; a damaged
    one still fails it."""
    path = tmp_path / "device.db"
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("CREATE TABLE t (x)")
    holder.execute("BEGIN EXCLUSIVE")
    try:
        assert quick_check(path)
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    _damage(path)
    assert not quick_check(path)


def test_profile_damaged_at_its_schema_page_still_opens(tmp_path: Path) -> None:
    """A learner database damaged where its schema version is kept opens through the DAT-13 recovery; the check for a
    newer app's file no longer fails the open with an internal error (UXS-47)."""

    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            ama = await api.add(by_name("Ama"))
            await stop_core(r)
            _damage(tmp_path / "profiles" / ama[4:] / "learner.db")
            r = await start_core(tmp_path, settings=SETTINGS, worker=False)
            api = Api(r)
            assert (await api.unlock(ama)).status_code == 200
            assert list((tmp_path / "profiles" / ama[4:]).glob("learner.db.damaged-*"))
        finally:
            await stop_core(r)

    run(scenario())


def uxs47_no_secret_locks_data(tmp_path: Path) -> None:
    """With no PIN or code known (there is none, D86, D87), every profile opens with its learning data byte-identical,
    and no learner file is readable only with a PIN or code."""

    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS)
        try:
            api = Api(r)
            directory = r.runtime.directory
            students = [await api.add(by_name(name)) for name in ("Ama", "Kofi")]
            for profile in students:
                token = await api.token(profile)
                await _session_with_turn(api, r, token, STATEMENT)
                await api.call("POST", f"/v1/profiles/{profile}/close", profile=token)

            def learning(profile: str) -> Any:
                with directory.open_learner(profile) as conn:
                    return (conn.execute("SELECT * FROM events ORDER BY rowid").fetchall(),
                            conn.execute("SELECT * FROM attempts").fetchall())  # fmt: skip

            before = {p: learning(p) for p in students}
            for profile in students:
                assert (await api.unlock(profile)).status_code == 200  # a tap, nothing else
            assert {p: learning(p) for p in students} == before  # learning data unchanged
            # Each learner file opens with plain SQLite, and the key store holds no profile key (D68, SEC-17).
            readable = 0
            for path in sorted(r.data_dir.glob("profiles/*/learner.db")):
                plain = sqlite3.connect(path)
                try:
                    readable += plain.execute("SELECT count(*) FROM events").fetchone()[0]
                finally:
                    plain.close()
            assert readable >= sum(len(events) for events, _ in before.values())
            held = getattr(directory.keys, "secrets", None)
            if held is not None:
                assert set(held) <= {INSTALL_MARKER}
        finally:
            await stop_core(r)

    run(scenario())


def uxs47_no_dead_ends(tmp_path: Path) -> None:
    """From the profile-store-unreadable state and from a single unreadable profile, with networking disabled, the
    core's path reaches a usable profile ("Try again" after the DAT-13 repair), and no learner file is deleted on the
    way. The screens that offer these steps are not built yet, so the test then skips."""

    async def first() -> list[str]:
        r = await start_core(tmp_path, settings=SETTINGS)
        try:
            api = Api(r)
            students = [await api.add(by_name(name)) for name in ("Ama", "Kofi")]
            token = await api.token(students[0])
            await _session_with_turn(api, r, token, STATEMENT)
            await api.call("POST", f"/v1/profiles/{students[0]}/close", profile=token)
            return students
        finally:
            await stop_core(r)

    students = run(first())
    files = _learner_files(tmp_path)

    async def recovering() -> None:
        r = await start_core(tmp_path, settings=SETTINGS)
        try:
            api = Api(r)
            with offline_run() as egress:
                listed = [p["profile_id"] for p in (await api.call("GET", "/v1/profiles")).json()["profiles"]]
                assert listed == students  # every tile is there
                for profile in listed:  # every profile opens and teaches: no dead end
                    await _session_with_turn(api, r, await api.token(profile), STATEMENT)
                with r.runtime.directory.open_learner(students[0]) as conn:
                    assert conn.execute("SELECT count(*) FROM events").fetchone()[0] > 0  # Ama's learning is kept
            assert egress.attempts == []
        finally:
            await stop_core(r)

    _damage(tmp_path / "device.db")  # the profile store is unreadable
    run(recovering())
    assert list(tmp_path.glob("device.db.damaged-*"))
    _damage(tmp_path / "profiles" / students[1][4:] / "learner.db")  # one profile's own file is unreadable
    run(recovering())
    assert list((tmp_path / "profiles" / students[1][4:]).glob("learner.db.damaged-*"))
    assert files <= _learner_files(tmp_path)  # every learner file is still there
    pytest.skip(
        "the client's recovery screens are not built (UXS-47: 'Let's get your profiles back' from 'Show "
        "recovery options', and the unreadable-profile tile); the core's path above passes"
    )


def uxs47_restore_reachable(tmp_path: Path) -> None:
    """ "Restore from a profile archive" is `POST /v1/profiles/import` with the archive from a file or USB stick: with
    networking disabled it ends with a new profile in the list that opens, beside the one of the same name. The
    client's button and its states are not built yet, so the test then skips."""

    async def scenario() -> None:
        r = await start_core(tmp_path / "device", settings=_settings())
        try:
            api = Api(r)
            ama = await api.add(by_name("Ama"))
            token = await api.token(ama)
            await _session_with_turn(api, r, token, STATEMENT)
            _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[ama],
                                       passphrase=PASSPHRASE)  # fmt: skip
            assert archive is not None
            before = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            with offline_run() as egress:
                restore = {"source": {"kind": "usb", "path": str(archive)}, "passphrase": PASSPHRASE}
                reply = await api.call("POST", "/v1/profiles/import", restore)
                assert reply.status_code == 202, reply.text
                job = (await api.call("GET", f"/v1/jobs/{reply.json()['job_id']}")).json()
                after = (await api.call("GET", "/v1/profiles")).json()["profiles"]
                assert (await api.unlock(job["result_ref"])).status_code == 200
            assert egress.attempts == []
            assert job["state"] == "done" and len(after) == len(before) + 1
            (tile,) = [p for p in after if p["profile_id"] == job["result_ref"]]
            assert tile["display_name"] == "Ama (2)"  # a new tile beside the existing one
        finally:
            await stop_core(r)

    run(scenario())
    pytest.skip(
        "the client's 'Restore from a profile archive' action and its states are not built (UXS-47); the "
        "core's path above passes"
    )
