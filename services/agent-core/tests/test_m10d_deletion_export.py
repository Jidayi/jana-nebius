"""M10.d: one-step profile deletion, exports and archive import (DAT-09, DAT-10, API-28, API-30, SEC-18). Synthetic
profiles and transcripts; no real student data."""

import asyncio
import base64
import hashlib
import io
import json
import socket
import sqlite3
import time
import zipfile
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.store.exports import ExportError, open_as_recipient, open_with_passphrase
from api_harness import STATEMENT, ask, cli, start_core, stop_core
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from test_m10a_profiles import Api, code, student

LOOP = asyncio.new_event_loop()
CANARY_GONE = "A cart qx7ama rolls 30 m in 6 s. How fast is it moving on average?"
CANARY_KEPT = "A cyclist zk4kofi rides 120 m in 20 s. What is the average speed?"


def run(coro):
    return LOOP.run_until_complete(coro)


async def _session_with_turn(api: Api, r, token: str, statement: str = STATEMENT) -> str:
    body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
            "origin": {"kind": "ask", "ref": None}}  # fmt: skip
    session_id = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
    turn = await api.call("POST", f"/v1/sessions/{session_id}/turns", ask(statement), profile=token)
    assert turn.status_code == 202, turn.text
    for _ in range(600):
        entry = r.core.sessions.get(session_id)
        if entry is not None and (entry.task is None or entry.task.done()):
            break
        await asyncio.sleep(0.05)
    return session_id


def _ids_in_databases(data_dir: Path, needles: tuple[str, ...]) -> dict[str, list[str]]:
    """Every table row of every SQLite file under the data directory that mentions one of the needles."""
    found: dict[str, list[str]] = {}
    for path in data_dir.rglob("*.db"):
        conn = sqlite3.connect(path)
        try:
            for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'"):
                for row in conn.execute(f'SELECT * FROM "{table}"'):  # noqa: S608 (table names from the file itself)
                    text = json.dumps(row, default=lambda b: b.hex() if isinstance(b, bytes) else str(b))
                    if any(n in text for n in needles):
                        found.setdefault(f"{path.name}:{table}", []).append(text[:120])
        finally:
            conn.close()
    return found


def _ids_in_files(data_dir: Path, needles: tuple[str, ...], skip: tuple[str, ...] = ("device.db",)) -> list[str]:
    hits = []
    for path in data_dir.rglob("*"):
        if any(n in str(path.relative_to(data_dir)) for n in needles):
            hits.append(f"path {path.relative_to(data_dir)}")
        elif path.is_file() and not path.name.startswith(skip):
            data = path.read_bytes()
            if any(n.encode() in data for n in needles):
                hits.append(f"bytes {path.relative_to(data_dir)}")
    return hits


# --- DAT-09 ----------------------------------------------------------------------------------------------------------


def dat09_delete_leaves_no_trace(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path)
        api = Api(r)
        try:
            gone, kept = await api.add(student("Ama")), await api.add(student("Kofi"))
            await _session_with_turn(api, r, (await api.unlock(gone)).json()["profile_token"], CANARY_GONE)
            await _session_with_turn(api, r, (await api.unlock(kept)).json()["profile_token"], CANARY_KEPT)
            r.runtime.traces.flush() if hasattr(r.runtime.traces, "flush") else None
            await asyncio.sleep(0.5)  # the trace writer is asynchronous
            needles = (gone, gone[4:])
            assert _ids_in_databases(tmp_path, needles), "the profile left records before deletion"
            # A pending deletion notice for a personal copy is one of the two things allowed to keep the id.
            r.runtime.stores.device.execute(
                "INSERT INTO outbox (outbox_id, idempotency_key, kind, profile_id, destination, payload, bytes,"
                " created_at, expires_at) VALUES ('obx_1', 'k1', 'tombstone', ?, 'personal_backup', x'00', 1, 0, 9e15)",
                (gone[4:],),
            )
            started = time.monotonic()
            token = (await api.unlock(gone)).json()["profile_token"]
            deleted = await api.call("DELETE", f"/v1/profiles/{gone}", profile=token)
            elapsed = time.monotonic() - started
            assert deleted.status_code == 200 and deleted.json()["deleted"] is True, deleted.text
            return needles, elapsed, kept
        finally:
            await stop_core(r)

    needles, elapsed, kept = run(scenario())
    # The deleted profile's conversation is nowhere; the kept profile's is only in its own learner database.
    assert _ids_in_files(tmp_path, ("qx7ama",), skip=()) == []
    holders = _ids_in_files(tmp_path, ("zk4kofi",), skip=())
    assert holders and all(h.startswith(f"bytes profiles/{kept[4:]}/") or "sessions/" in h for h in holders), holders
    left = _ids_in_databases(tmp_path, needles)
    assert set(left) == {"device.db:outbox", "device.db:device_audit"}, left
    audit = left["device.db:device_audit"]
    assert len(audit) == 1 and "profile.delete" in audit[0]
    assert _ids_in_files(tmp_path, needles) == []
    assert elapsed < Settings().profile_delete_budget_s
    assert (tmp_path / "profiles" / kept[4:] / "learner.db").is_file()  # the other profile is untouched


def dat09_delete_offline(tmp_path: Path):
    attempts: list = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            attempts.append(host)
            raise OSError("network disabled for this test")
        return real_connect(self, address)

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            socket.socket.connect = guarded
            try:
                token = (await api.unlock(profile)).json()["profile_token"]
                return (await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)).status_code, profile
            finally:
                socket.socket.connect = real_connect
        finally:
            await stop_core(r)

    status, profile = run(scenario())
    assert status == 200 and attempts == []
    assert not (tmp_path / "profiles" / profile[4:]).exists()


# --- API-28 ----------------------------------------------------------------------------------------------------------


def api28_profile_delete_complete(tmp_path: Path):
    async def scenario():
        r = await start_core(tmp_path)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = (await api.unlock(profile)).json()["profile_token"]
            session_id = await _session_with_turn(api, r, token)
            assert code(await api.call("DELETE", f"/v1/profiles/{profile}")) == "profile_token_expired"
            deleted = await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)
            assert deleted.json()["files_removed"] >= 1
            listed = (await api.call("GET", "/v1/profiles")).json()["profiles"]
            gone_session = await api.call("GET", f"/v1/sessions/{session_id}/snapshot", profile=token)
            again = await api.unlock(profile)
            return listed, gone_session.status_code, again
        finally:
            await stop_core(r)

    listed, session_status, again = run(scenario())
    assert listed == [] and session_status == 404 and code(again) == "not_found"
    assert not (tmp_path / "sessions").exists() or not list((tmp_path / "sessions").glob("ses_*"))


# --- DAT-10, API-30, SEC-18: exports and import -----------------------------------------------------------------------

PASSPHRASE = "correct horse battery staple"  # noqa: S105 (a synthetic test passphrase)
SUPPORT = X25519PrivateKey.generate()
STUDY = X25519PrivateKey.generate()


def _public(key) -> str:
    raw = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return base64.b64encode(raw).decode()


def _settings() -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), export_support_public_key=_public(SUPPORT),
                    export_research_public_key=_public(STUDY))  # fmt: skip


async def _learner_with_history(api: Api, r, name: str = "Ama", canary: str = CANARY_GONE) -> tuple[str, str, str]:
    profile = await api.add(student(name))
    token = (await api.unlock(profile)).json()["profile_token"]
    session_id = await _session_with_turn(api, r, token, canary)
    await api.call("POST", f"/v1/sessions/{session_id}/turns", ask("s = 10 m", "answer"), profile=token)
    for _ in range(600):
        entry = r.core.sessions[session_id]
        if entry.task is None or entry.task.done():
            break
        await asyncio.sleep(0.05)
    return token, profile, session_id


async def _export(api: Api, token: str | None, folder: Path, **body):
    """Export through the profile's live token, opening the profile again when it has closed."""
    folder.mkdir(parents=True, exist_ok=True)
    request = {"destination": {"kind": "file", "path": str(folder)}, **body}
    profile_id = body["profile_ids"][0]
    if api.r.runtime.directory.profile_of(token) != profile_id:
        token = (await api.unlock(profile_id)).json()["profile_token"]
    reply = await api.call("POST", "/v1/exports", request, profile=token)
    if reply.status_code != 202:
        return reply, None
    job = (await api.call("GET", f"/v1/jobs/{reply.json()['job_id']}")).json()
    return reply, Path(job["result_ref"])


def _with_exports(tmp_path: Path, scenario):
    async def go():
        r = await start_core(tmp_path / "device", settings=_settings())
        try:
            return await scenario(Api(r), r)
        finally:
            await stop_core(r)

    return run(go())


def sec18_exports_encrypted(tmp_path: Path):
    async def scenario(api: Api, r):
        token, profile, _ = await _learner_with_history(api, r)
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE)  # fmt: skip
        _, bundle = await _export(api, token, tmp_path / "usb", kind="diagnostic_bundle", profile_ids=[profile])
        return archive.read_bytes(), bundle.read_bytes()

    archive, bundle = _with_exports(tmp_path, scenario)
    for sealed in (archive, bundle):
        assert not [w for w in (b"manifest.json", b"events.jsonl", b"physics", b"PK\x03\x04") if w in sealed]
    with pytest.raises(ExportError):
        open_with_passphrase(archive, "not the passphrase at all")
    assert json.loads(zipfile.ZipFile(io.BytesIO(open_with_passphrase(archive, PASSPHRASE))).read("manifest.json"))
    with pytest.raises(ExportError):
        open_as_recipient(bundle, STUDY)  # sealed for support, not for the study team
    assert "traces" in json.loads(open_as_recipient(bundle, SUPPORT))


def dat10_bundle_encrypted_and_signed(tmp_path: Path):
    async def scenario(api: Api, r):
        token, profile, _ = await _learner_with_history(api, r)
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE)  # fmt: skip
        damaged = tmp_path / "damaged.janaprofile"
        data = bytearray(archive.read_bytes())
        data[len(data) // 2] ^= 0x01
        damaged.write_bytes(bytes(data))
        wrong = await api.call(
            "POST",
            "/v1/profiles/import",
            {"source": {"kind": "file", "path": str(archive)}, "passphrase": "the wrong passphrase"},
        )
        changed = await api.call(
            "POST",
            "/v1/profiles/import",
            {"source": {"kind": "usb", "path": str(damaged)}, "passphrase": PASSPHRASE},
        )
        return wrong, changed, len((await api.call("GET", "/v1/profiles")).json()["profiles"])

    wrong, changed, count = _with_exports(tmp_path, scenario)
    assert code(wrong) == "archive_invalid" and code(changed) == "archive_invalid" and count == 1


def dat10_archive_student_authorization(tmp_path: Path):
    async def scenario(api: Api, r):
        token, profile, first = await _learner_with_history(api, r)
        token = (await api.unlock(profile)).json()["profile_token"]
        second = await _session_with_turn(api, r, token, CANARY_KEPT)
        _, plain = await _export(api, token, tmp_path / "a", kind="profile_archive", profile_ids=[profile],
                                 passphrase=PASSPHRASE)  # fmt: skip
        # Nobody mints the grant without the student's own token, and transcripts without one are refused.
        assert code(
            await api.call(
                "POST",
                f"/v1/profiles/{profile}/archive-authorizations",
                {"session_ids": [first], "include_attachments": False, "confirmed": True},
            )
        ) in ("profile_token_expired", "not_found")
        refused, _ = await _export(api, token, tmp_path / "b", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE, include_transcripts=True)  # fmt: skip
        grant = (await api.call("POST", f"/v1/profiles/{profile}/archive-authorizations",
                                {"session_ids": [first], "include_attachments": False, "confirmed": True},
                                profile=token)).json()["authorization_id"]  # fmt: skip
        _, granted = await _export(
            api,
            token,
            tmp_path / "c",
            kind="profile_archive",
            profile_ids=[profile],
            passphrase=PASSPHRASE,
            include_transcripts=True,
            archive_authorization_id=grant,
        )
        replay, _ = await _export(
            api,
            token,
            tmp_path / "d",
            kind="profile_archive",
            profile_ids=[profile],
            passphrase=PASSPHRASE,
            include_transcripts=True,
            archive_authorization_id=grant,
        )
        late = (await api.call("POST", f"/v1/profiles/{profile}/archive-authorizations",
                               {"session_ids": [first], "include_attachments": False, "confirmed": True},
                               profile=token)).json()["authorization_id"]  # fmt: skip
        await api.call("POST", f"/v1/profiles/{profile}/close", profile=token)
        locked, _ = await _export(
            api,
            token,
            tmp_path / "e",
            kind="profile_archive",
            profile_ids=[profile],
            passphrase=PASSPHRASE,
            include_transcripts=True,
            archive_authorization_id=late,
        )
        assert second != first
        return plain, granted, refused, replay, locked, first

    plain, granted, refused, replay, locked, first = _with_exports(tmp_path, scenario)
    assert code(refused) == "validation_failed" and code(replay) == "validation_failed"
    assert code(locked) == "validation_failed"
    without_grant = open_with_passphrase(plain.read_bytes(), PASSPHRASE)
    assert b"qx7ama" not in without_grant and b"zk4kofi" not in without_grant
    with_grant = zipfile.ZipFile(io.BytesIO(open_with_passphrase(granted.read_bytes(), PASSPHRASE)))
    assert sorted(n for n in with_grant.namelist() if n.startswith("sessions/")) == [f"sessions/{first[4:]}.json"]
    assert b"zk4kofi" not in open_with_passphrase(granted.read_bytes(), PASSPHRASE)
    assert not [n for n in with_grant.namelist() if n.startswith("attachments/")]


def dat10_archive_roundtrip(tmp_path: Path):
    async def export(api: Api, r):
        token, profile, _ = await _learner_with_history(api, r)
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE)  # fmt: skip
        return archive, _checksum(r, profile)

    archive, original = _with_exports(tmp_path, export)

    async def restore():  # a second device
        r = await start_core(tmp_path / "second", settings=_settings())
        api = Api(r)
        try:
            reply = await api.call(
                "POST",
                "/v1/profiles/import",
                {"source": {"kind": "usb", "path": str(archive)}, "passphrase": PASSPHRASE},
            )
            job = (await api.call("GET", f"/v1/jobs/{reply.json()['job_id']}")).json()
            return _checksum(r, job["result_ref"])
        finally:
            await stop_core(r)

    assert run(restore()) == original


def _checksum(r, profile_id: str) -> str:
    from agent_core.learner.mastery import MasteryParams
    from agent_core.learner.service import Learner

    with r.runtime.directory.open_learner(profile_id) as conn:
        learner = Learner.open(conn, profile_id=profile_id[4:], device_id=r.runtime.directory.device_id,
                               wall_ms=lambda: int(time.time() * 1000), max_skew_ms=10**13,
                               params=MasteryParams.from_settings(Settings()))  # fmt: skip
        events = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        assert events > 0
        return learner.projector.checksum()


def api28_archive_import_new_profile(tmp_path: Path):
    async def scenario(api: Api, r):
        token, profile, _ = await _learner_with_history(api, r)
        await api.call("PATCH", f"/v1/profiles/{profile}/settings", {"memory_saving": False},
                       profile=(await api.unlock(profile)).json()["profile_token"])  # fmt: skip
        with r.runtime.directory.open_learner(profile) as conn:
            conn.execute("INSERT INTO consents (consent_id, scope, granted_by_role, granted_by_label, notice_version,"
                         " dpia_ref, method, granted_at) VALUES ('c1', 'research_use', 'guardian', 'Parent', 'v1',"
                         " 'test-dpia', 'in_app_guardian', 1)")  # fmt: skip
        before = (await api.call("GET", "/v1/profiles")).json()["profiles"]
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE)  # fmt: skip
        reply = await api.call(
            "POST",
            "/v1/profiles/import",
            {"source": {"kind": "file", "path": str(archive)}, "passphrase": PASSPHRASE},
        )
        assert reply.status_code == 202, reply.text
        new = (await api.call("GET", f"/v1/jobs/{reply.json()['job_id']}")).json()["result_ref"]
        after = (await api.call("GET", "/v1/profiles")).json()["profiles"]
        with r.runtime.directory.open_learner(new) as conn:
            consents = conn.execute("SELECT withdrawn_at FROM consents").fetchall()
        token = (await api.unlock(new)).json()["profile_token"]
        settings = (await api.call("GET", f"/v1/profiles/{new}/settings", profile=token)).json()
        return profile, new, before, after, consents, settings, _checksum(r, profile), _checksum(r, new)

    profile, new, before, after, consents, settings, old_sum, new_sum = _with_exports(tmp_path, scenario)
    assert new != profile and before[0] in after and len(after) == 2
    added = next(p for p in after if p["profile_id"] == new)
    assert "has_pin" not in added and added["display_name"] == "Ama (2)"
    assert consents and all(c[0] is not None for c in consents)  # archived consents come back withdrawn
    assert settings["memory_saving"] is False and old_sum == new_sum


def api30_export_scoped_and_audited(tmp_path: Path):
    async def scenario(api: Api, r):
        token, ama, _ = await _learner_with_history(api, r)
        _, kofi, _ = await _learner_with_history(api, r, "Kofi", CANARY_KEPT)
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[ama],
                                   passphrase=PASSPHRASE)  # fmt: skip
        with r.runtime.directory.open_learner(ama) as conn:
            exports = conn.execute("SELECT kind, destination, sha256 FROM exports").fetchall()
            audit = conn.execute("SELECT actor_role, action FROM audit_log").fetchall()
        with r.runtime.directory.open_learner(kofi) as conn:
            other = conn.execute("SELECT count(*) FROM exports").fetchone()[0]
        return archive, exports, audit, other, kofi

    archive, exports, audit, other, kofi = _with_exports(tmp_path, scenario)
    sealed = archive.read_bytes()
    assert exports == [("profile_archive", "file", hashlib.sha256(sealed).hexdigest())]
    assert ("student", "export.profile_archive") in audit and other == 0
    content = open_with_passphrase(sealed, PASSPHRASE)
    assert b"Kofi" not in content and kofi[4:].encode() not in content


def api30_kinds_match_dat10(tmp_path: Path):
    from agent_core.contracts.api.commands import CreateExport
    from agent_core.store.generated.schema import DATABASES

    ids = {"parent_report", "profile_archive", "research_export", "diagnostic_bundle"}
    check = DATABASES["learner"].split("CREATE TABLE exports", 1)[1].split("destination", 1)[0]
    kinds = set(json.loads(json.dumps(CreateExport.model_json_schema()["properties"]["kind"]["enum"])))
    assert ids == kinds == {k for k in kinds if f"'{k}'" in check} and len(ids) == 4

    async def scenario(api: Api, r):
        _token, profile, _ = await _learner_with_history(api, r)
        folder = {"kind": "file", "path": str(tmp_path)}
        base = {"profile_ids": [profile], "destination": folder}
        wrong = [{**base, "kind": "diagnostic_bundle", "recipient_public_key": "untrusted"},
                 {**base, "kind": "profile_archive", "passphrase": PASSPHRASE, "include_session_ids": ["ses_x"]},
                 {**base, "kind": "research_export", "include_transcripts": True}]  # fmt: skip
        token = (await api.unlock(profile)).json()["profile_token"]
        return [(await api.call("POST", "/v1/exports", body, profile=token)) for body in wrong]

    for reply in _with_exports(tmp_path, scenario):
        assert reply.status_code == 422 and code(reply) == "validation_failed"


def api30_student_confirmation_required(tmp_path: Path):
    """The authorization is the student's own confirmation for exactly the chosen sessions: unconfirmed, for another
    profile or after it lapses it gives nothing, and it is single-use (API-30, D86)."""

    async def scenario(api: Api, r):
        now = [1_800_000_000_000]
        r.runtime.directory.clock_ms = lambda: now[0]
        r.core.clock_ms = lambda: now[0]
        token, profile, session_id = await _learner_with_history(api, r)
        body = {"session_ids": [session_id], "include_attachments": False, "confirmed": True}
        unconfirmed = await api.call("POST", f"/v1/profiles/{profile}/archive-authorizations",
                                     {**body, "confirmed": False}, profile=token)  # fmt: skip
        other = await api.call("POST", "/v1/profiles/prf_01M4NOTTHISPROFILE00000000/archive-authorizations", body,
                               profile=token)  # fmt: skip
        granted = await api.call("POST", f"/v1/profiles/{profile}/archive-authorizations", body, profile=token)
        now[0] += int(Settings().retention_archive_authorization_s * 1000) + 1
        expired, _ = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE, include_transcripts=True,
                                   archive_authorization_id=granted.json()["authorization_id"])  # fmt: skip
        token = (await api.unlock(profile)).json()["profile_token"]
        fresh = (await api.call("POST", f"/v1/profiles/{profile}/archive-authorizations", body,
                                profile=token)).json()["authorization_id"]  # fmt: skip
        _, archive = await _export(api, token, tmp_path / "usb", kind="profile_archive", profile_ids=[profile],
                                   passphrase=PASSPHRASE, include_transcripts=True,
                                   archive_authorization_id=fresh)  # fmt: skip
        replay, _ = await _export(api, token, tmp_path / "again", kind="profile_archive", profile_ids=[profile],
                                  passphrase=PASSPHRASE, include_transcripts=True,
                                  archive_authorization_id=fresh)  # fmt: skip
        return unconfirmed, other, granted, expired, archive, replay, session_id

    unconfirmed, other, granted, expired, archive, replay, session_id = _with_exports(tmp_path, scenario)
    assert code(unconfirmed) == "validation_failed" and other.status_code == 404
    assert granted.status_code == 200 and granted.json()["expires_in_s"] == 300
    assert code(expired) == "validation_failed" and code(replay) == "validation_failed"
    names = zipfile.ZipFile(io.BytesIO(open_with_passphrase(archive.read_bytes(), PASSPHRASE))).namelist()
    assert [n for n in names if n.startswith("sessions/")] == [f"sessions/{session_id[4:]}.json"]


def dat10_diagnostic_redacted(tmp_path: Path):
    async def scenario(api: Api, r):
        token, profile, _ = await _learner_with_history(api, r)
        r.runtime.traces.flush()
        _, bundle = await _export(api, token, tmp_path / "usb", kind="diagnostic_bundle", profile_ids=[profile])
        return bundle

    bundle = _with_exports(tmp_path, scenario)
    opened = open_as_recipient(bundle.read_bytes(), SUPPORT)
    traces = json.loads(opened)["traces"]
    assert traces and b"qx7ama" not in opened and b"s = 10 m" not in opened


def test_retention_pass_covers_every_profile(tmp_path: Path):
    """The runtime's DAT-08 pass reaches each profile's own learner database (not only the open one)."""

    async def scenario():
        r = await start_core(tmp_path)
        api = Api(r)
        try:
            first = await api.add(student("Ama"))
            await _session_with_turn(api, r, (await api.unlock(first)).json()["profile_token"], CANARY_GONE)
            await api.unlock(await api.add(student("Kofi")))  # the first profile's database is now closed
            with r.runtime.directory.open_learner(first) as conn:
                conn.execute("UPDATE sessions SET ended_at = 1")
            r.runtime.retention_pass(now_ms=10**13)
            with r.runtime.directory.open_learner(first) as conn:
                return (conn.execute("SELECT count(*) FROM turns").fetchone()[0],
                        conn.execute("SELECT transcript_purged_at FROM sessions").fetchone()[0])  # fmt: skip
        finally:
            await stop_core(r)

    turns, purged = run(scenario())
    assert turns == 0 and purged is not None


def _personal_copy_deletion(tmp_path: Path, ack_status: int = 204):
    """Already-owed personal-copy erasures stay visible until their destination acknowledges them.

    The S4 account services/holder registration are not shipped in S2. Test their declared transport rows on local
    TLS stand-ins only; do not switch on future features in the actual application or claim deployed copy erasure.
    """
    from dataclasses import replace

    from agent_core.contracts.cloud.outbox import Tombstone
    from agent_core.net.policy import load_policy
    from agent_core.store import egress
    from agent_core.store.events import iso_ms
    from net_harness import FakeServices, enable, layer

    async def scenario():
        async with FakeServices(tmp_path) as server:
            r = await start_core(tmp_path / "core", worker=False)
            online = None
            try:
                api = Api(r)
                profile = await api.add(student("Synthetic learner"))
                token = (await api.unlock(profile)).json()["profile_token"]
                policy = load_policy()
                personal = ("cloud_backup", "multi_device")
                policy = replace(
                    policy,
                    features={**policy.features, **{f: replace(policy.features[f], stage="S2") for f in personal}},
                )
                online = layer(tmp_path, server, device=r.runtime.stores.device, policy=policy)
                enable(online, *personal)
                await online.connectivity.check()
                now = online.clock_ms()
                payload = Tombstone(erases="profile", deleted_at=iso_ms(now)).model_dump_json().encode()
                for feature in personal:
                    online.outbox.put(
                        "tombstone",
                        feature,
                        payload,
                        expires_ms=now + 86_400_000,
                        idempotency_key=f"erase:{profile}:{feature}",
                        profile_id=profile[4:],
                    )
                # A failed destination cannot be confused with an acknowledged one.
                relay_host = online.host_for("multi_device")
                server.handlers["/v1/outbox/tombstone"] = lambda seen: (
                    (503, {"pending": True}) if seen.headers["host"].split(":")[0] == relay_host else (ack_status, None)
                )
                deleted = await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)
                assert deleted.status_code == 200 and deleted.json()["deleted"]
                assert set(online.outbox.counts()) == set(personal)
                online.connectivity.state = "offline"
                sent_before = len(server.requests)
                assert await online.outbox.drain(force=True) == 0
                assert len(server.requests) == sent_before
                assert online.outbox.counts() == {f: 1 for f in personal}
                await online.connectivity.check()
                assert await online.outbox.drain(force=True) == 1
                view = online.state_view(extended=True)
                assert view["features"]["cloud_backup"]["queued_items"] == 0
                assert view["features"]["multi_device"]["queued_items"] == 1
                assert view["features"]["multi_device"]["state"] == "queued"
                pending = egress.pending(online.device)
                assert len(pending) == 1 and pending[0].idempotency_key == f"erase:{profile}:multi_device"
                key = pending[0].idempotency_key
                # The same durable request survives a new connection; no new identity is issued on retry.
                await online.stop()
                online = layer(tmp_path, server, device=r.runtime.stores.device, policy=policy)
                await online.connectivity.check()
                server.handlers["/v1/outbox/tombstone"] = lambda seen: (ack_status, None)
                assert await online.outbox.drain(force=True) == 1
                assert not egress.pending(online.device)
                sends = [
                    s
                    for s in server.requests
                    if s.path == "/v1/outbox/tombstone" and s.headers.get("idempotency-key") == key
                ]
                assert len(sends) == 2
                assert (
                    online.device.execute(
                        "SELECT delivered_at,payload FROM outbox WHERE idempotency_key=?", (key,)
                    ).fetchone()[1]
                    == b""
                )
            finally:
                if online is not None:
                    await online.stop()
                await stop_core(r)

    run(scenario())


def dat09_personal_copy_deletion(tmp_path: Path):
    _personal_copy_deletion(tmp_path)


@pytest.mark.parametrize("ack_status", [200, 204, 409])
def prv10_cloud_requests(tmp_path: Path, ack_status: int):
    """Track each owed personal erasure through offline, rejection, retry and acknowledgement.

    Successful and already-applied responses end tracking; the independent destination remains pending after 503.
    Local TLS transport qualification only: deployed S4 account rights propagation is separately required.
    """
    _personal_copy_deletion(tmp_path, ack_status)
