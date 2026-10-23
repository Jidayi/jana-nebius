"""OPS-24, OBS-18, OBS-19, PRV-10, OPS-31: support bundles reach the ingest only by a deliberate upload with a ticket
reference, are re-scanned and stored encrypted, are opened only by the ticket's assignees with every opening logged,
and are deleted at ticket close, after the retention period, at a deletion request, or when an incident's hold ends.
The bundles are built with the core's own debug-bundle writer from synthetic inputs."""

from __future__ import annotations

import asyncio
import base64
import json
import zipfile
from pathlib import Path
from typing import Any

import httpx
from agent_core.config import Settings
from agent_core.store.exports import open_with_passphrase, seal_with_passphrase
from agent_core.trace.debug_bundle import BundleInputs, bundle_files, zip_bytes
from ingest import contracts
from ingest_harness import Clock, app, client, staff

RECEIPT, REFUSAL = "ops/support-upload#/$defs/SupportUploadReceipt", "ops/support-upload#/$defs/SupportUploadError"

NOW_MS = 1_790_000_000_000
FAST = Settings(passphrase_argon2_memory_kib=8192, passphrase_argon2_iterations=1)
PASSPHRASE = "a synthetic passphrase for tests"  # noqa: S105 (synthetic, test only)


def _files(note: str = "the hint skipped a step") -> dict[str, bytes]:
    inputs = BundleInputs(
        summary={"app": "1.0.0", "build": "dev", "hardware_class": "low"},
        config={"online_downloads": True, "launch_token": "synthetic-launch-secret", "worker_pool_size": 4},
        health={"core": "ok", "worker": "ok"}, log_dir=None,
        traces=[{"turn_id": f"trn_{i}", "duration_ms": 100 + i} for i in range(5)],
        crash_records=[], ledger=[{"feature": "downloads", "bytes": 10}], packs=["pack.phy.o"],
        models=["mp.synth.8b.q4_k_m.low"], now_ms=NOW_MS,
        problem_reports=[{"report_id": "01JREPORT00000000000000001", "session_id": "ses_1", "created_at": NOW_MS,
                          "content": json.dumps({"category": "confusing", "turn_id": "trn_1", "note": note,
                                                 "allow_support_export": True})}],
    )  # fmt: skip
    return bundle_files(inputs, Settings())


def _metadata(**changes: Any) -> str:
    value = {"device_id": "dev_synthetic01", "licence_id": None, "app_version": "1.0.0", "channel": "stable",
             "health": {"core": "ok"}, "error_codes": ["disk_full"], **changes}  # fmt: skip
    return base64.urlsafe_b64encode(json.dumps(value).encode()).decode().rstrip("=")


async def _ticket(http: httpx.AsyncClient, *assignees: str) -> str:
    reply = await http.post("/admin/v1/tickets", json={"assignees": list(assignees)}, headers=staff("ada"))
    assert reply.status_code == 201, reply.text
    return str(reply.json()["ticket_ref"])


async def _upload(http: httpx.AsyncClient, ticket: str, data: bytes, **headers: str) -> httpx.Response:
    return await http.put(f"/v1/support/tickets/{ticket}/bundle", content=data,
                          headers={"content-type": "application/octet-stream", **headers})  # fmt: skip


def test_ops24_bundle_upload_access_and_deletion(tmp_path: Path):
    clock = Clock()
    application = app(tmp_path, clock)
    ingest = application.state.ingest
    plain = zip_bytes(_files())
    sealed = seal_with_passphrase(plain, PASSPHRASE, FAST.passphrase_argon2_memory_kib,
                                  FAST.passphrase_argon2_iterations)  # fmt: skip

    async def scenario() -> dict[str, str]:
        async with client(application) as http:
            assert (await http.post("/admin/v1/tickets", json={"assignees": ["ada"]})).status_code == 401
            assert (await http.post("/admin/v1/tickets", json={"assignees": ["eve"]}, headers=staff("ada"))
                    ).status_code == 400  # fmt: skip
            ticket = await _ticket(http, "ada", "ben")

            # Only a real, open ticket takes an upload, and only the app's report files.
            unknown = await _upload(http, "JT-0000-0000-0000", plain)
            not_a_report = await _upload(http, ticket, b"%PDF-1.7 not a report")
            assert (unknown.status_code, not_a_report.status_code) == (404, 415)
            first = await _upload(http, ticket, plain, **{"jana-support-metadata": _metadata()})
            assert first.status_code == 201 and first.json()["scanned"] and not first.json()["sealed"]
            second = await _upload(http, ticket, sealed)
            assert second.status_code == 201 and second.json() == {**second.json(), "sealed": True, "scanned": False}
            plain_id, sealed_id = first.json()["bundle_id"], second.json()["bundle_id"]
            bad_metadata = await _upload(http, ticket, plain, **{"jana-support-metadata": _metadata(student="x")})
            assert bad_metadata.json()["error"]["code"] == "invalid_metadata"
            # Replies are the support-upload contract's (D99).
            assert all(contracts.errors(RECEIPT, reply.json()) == [] for reply in (first, second))
            assert all(contracts.errors(REFUSAL, reply.json()) == [] for reply in (unknown, not_a_report, bad_metadata))

            # Stored encrypted: neither the zip nor any of its text is readable on disk.
            on_disk = ingest.store.bundle_path(plain_id).read_bytes()
            assert not on_disk.startswith(b"PK") and b"pack.phy.o" not in on_disk

            # Assignees only; the sealed report needs L3 and a named defect. Every attempt is logged.
            assert (await http.get(f"/admin/v1/bundles/{plain_id}", headers=staff("cy"))).status_code == 403
            opened = await http.get(f"/admin/v1/bundles/{plain_id}", headers=staff("ben"))
            assert opened.status_code == 200 and opened.content == plain
            assert (await http.get(f"/admin/v1/bundles/{sealed_id}", headers=staff("ben"))).status_code == 403
            assert (await http.get(f"/admin/v1/bundles/{sealed_id}", headers=staff("ada"))).status_code == 403
            got = await http.get(f"/admin/v1/bundles/{sealed_id}?defect=DEF-1234", headers=staff("ada"))
            assert got.status_code == 200 and open_with_passphrase(got.content, PASSPHRASE) == plain
            meta = await http.get(f"/admin/v1/bundles/{plain_id}/metadata", headers=staff("ben"))
            assert meta.json()["metadata"]["device_id"] == "dev_synthetic01"

            # Ticket close deletes its bundles; they cannot be opened afterwards, and the log remains.
            closed = await http.post(f"/admin/v1/tickets/{ticket}/close", headers=staff("ben"))
            assert sorted(closed.json()["erased"]) == sorted([plain_id, sealed_id])
            assert not ingest.store.bundle_path(plain_id).exists()
            assert (await http.get(f"/admin/v1/bundles/{plain_id}", headers=staff("ben"))).status_code == 404
            assert (await _upload(http, ticket, plain)).status_code == 404, "a closed ticket takes no upload"
            log = (await http.get(f"/admin/v1/bundles/{sealed_id}/access-log", headers=staff("ada"))).json()["entries"]
            return {"plain": plain_id, "sealed": sealed_id, "log": json.dumps(log)}

    ids = asyncio.run(scenario())
    log = json.loads(ids["log"])
    assert [(e["actor"], e["action"], e["allowed"]) for e in log] == [
        ("uploader", "bundle.upload", True),
        ("ben", "bundle.open", False),
        ("ada", "bundle.open", False),
        ("ada", "bundle.open", True),
        ("system", "bundle.erase", True),
        ("ada", "bundle.access_log", True),  # reading the log is itself logged
    ]
    assert log[3]["reason"] == "DEF-1234"


def test_ops24_retention_incident_hold_and_deletion_request(tmp_path: Path):
    clock = Clock()
    application = app(tmp_path, clock)
    ingest = application.state.ingest
    days = ingest.config.retention.bundle_days
    plain = zip_bytes(_files())

    async def scenario() -> None:
        async with client(application) as http:
            kept, held = await _ticket(http, "ada"), await _ticket(http, "ada")
            expiring = (await _upload(http, kept, plain)).json()["bundle_id"]
            evidence = (await _upload(http, held, plain)).json()["bundle_id"]
            assert (await http.post(f"/admin/v1/tickets/{held}/hold", json={"incident_id": "INC-77"},
                                    headers=staff("ada"))).status_code == 200  # fmt: skip
            clock.now += (days - 1) * 86_400
            assert ingest.purge()["bundles"] == 0, "not before the retention period"
            clock.now += 86_400
            assert ingest.purge()["bundles"] == 1 and not ingest.store.bundle_path(expiring).exists()
            clock.now += 400 * 86_400
            assert ingest.purge()["bundles"] == 0, "an incident hold keeps evidence past retention"
            assert (await http.post(f"/admin/v1/tickets/{held}/close", headers=staff("ada"))).json()["erased"] == []
            released = await http.post("/admin/v1/incidents/INC-77/close", headers=staff("ada"))
            assert released.json()["erased"] == [evidence]

            # A deletion request (PRV-10) deletes a held bundle at once.
            again = await _ticket(http, "ada")
            requested = (await _upload(http, again, plain)).json()["bundle_id"]
            await http.post(f"/admin/v1/tickets/{again}/hold", json={"incident_id": "INC-78"}, headers=staff("ada"))
            assert (await http.post(f"/admin/v1/bundles/{requested}/erase", headers=staff("cy"))).json() == {
                "erased": True}  # fmt: skip
            assert not ingest.store.bundle_path(requested).exists()
            assert (await http.post(f"/admin/v1/bundles/{requested}/erase", headers=staff("cy"))).status_code == 404

    asyncio.run(scenario())


def test_obs19_bundle_rescan_refuses_personal_details(tmp_path: Path):
    """The re-scan refuses a plain report holding a contact detail, a secret or a named home folder, and one whose
    manifest does not match its files; nothing of a refused upload is kept, and the refusal names only the kind."""
    application = app(tmp_path, Clock())
    ingest = application.state.ingest

    def tampered() -> bytes:
        files = _files()
        files["health.json"] = b'{"core": "error"}\n'
        return zip_bytes(files)

    def bomb() -> bytes:
        files = _files()
        files["logs/core.jsonl"] = b"x" * (ingest.config.limits.max_bundle_unzipped_bytes + 1)
        return zip_bytes(files)

    async def scenario() -> None:
        async with client(application) as http:
            ticket = await _ticket(http, "ada")
            for note, kind in (("call me on +233 24 123 4567", "phone"), ("write to kid@example.com", "email"),
                               ("see C:\\Users\\Kwame\\Desktop", "home_path")):  # fmt: skip
                reply = await _upload(http, ticket, zip_bytes(_files(note)))
                assert reply.status_code == 422 and reply.json()["error"]["code"] == "redaction_blocked"
                assert kind in reply.json()["error"]["message"] and note not in reply.text
            reply = await _upload(http, ticket, tampered())
            assert reply.json()["error"]["code"] == "bundle_invalid"
            reply = await _upload(http, ticket, bomb())
            assert reply.status_code in (413, 422)
        assert ingest.store.bundles(ticket) == []
        assert not list((tmp_path / "ingest" / "bundles").iterdir())

    asyncio.run(scenario())


def test_ops24_default_bundle_passes_rescan(tmp_path: Path):
    """A default report from the core's writer is clean by construction (OBS-18) and passes the re-scan as is; its
    secrets were removed before saving."""
    from ingest.support import bundle_problems

    files = _files()
    data = zip_bytes(files)
    assert bundle_problems(data, 500, 10_000_000) == []
    with zipfile.ZipFile(__import__("io").BytesIO(data)) as archive:
        assert b"synthetic-launch-secret" not in b"".join(archive.read(n) for n in archive.namelist())
