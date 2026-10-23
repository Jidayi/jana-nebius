"""OBS-17, OBS-20, ARC-09, SEC-21: the core's real outbox delivers crash reports and telemetry to the ingest.

The device side is the core's own connectivity layer (policy, pinned TLS, egress ledger, outbox, crash-report
approval and the telemetry queue); the service side is the ingest served over TLS in-process. Data is synthetic."""

from __future__ import annotations

import asyncio
import json
import math
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.net import crash_reports
from agent_core.store import egress as egress_store
from agent_core.store.keystore import MemoryKeyStore
from agent_core.trace.crashes import CrashStore, device_key
from agent_core.trace.metrics import observe
from ingest import validation
from ingest.store import IngestStore
from ingest_harness import HOSTS, Clock, app, client, device_layer, enable, serve_tls, staff

STUDENT = "Kofi Synthetic-Learner"  # a made-up name, seeded to prove it never arrives
METADATA = {"app_version": "0.0.0", "channel": "dev", "hardware_class": "low", "os_family": "linux",
            "router_tier": "local"}  # fmt: skip


def _report(tmp: Path) -> dict[str, Any]:
    store = CrashStore(tmp / "crashes", device_key(MemoryKeyStore()), "1.0.0", Settings())
    record = store.record("core", "exception", [{"file": "agent_core/engine/turn.py", "line": 10, "function": "run"}],
                          error_type="RuntimeError", correlation={"session_id": "ses_SYNTH"},
                          log_tail=['{"event": "turn.start"}'], detail={"exit_code": None})  # fmt: skip
    return crash_reports.build_report(record, "low")


def test_obs17_obs20_outbox_delivers_to_ingest(tmp_path: Path):
    """An approved crash report and the day's telemetry report travel through the core's outbox over pinned TLS
    and are kept exactly once; a resend after a lost reply is answered "seen already" and counted as delivered."""
    application = app(tmp_path, Clock())
    report = _report(tmp_path)

    async def scenario() -> None:
        async with serve_tls(application, tmp_path) as (pki, port):
            online = device_layer(tmp_path, pki, port)
            try:
                enable(online, "crash_reports", "telemetry")
                online.connectivity.features_changed()
                assert await online.connectivity.check() == "online", "the probe reaches GET /v1/ping"
                crash_reports.approve(online, report, [STUDENT], 20, 10**15)
                metrics: dict[str, Any] = {}
                observe(metrics, "model_calls", 3)
                online.telemetry.add(metrics, **METADATA)
                online.telemetry.prepare()
                queued = online.device.execute("SELECT outbox_id, payload FROM outbox").fetchall()
                assert len(queued) == 2
                assert await online.drain_once(force=True) == 2
                assert egress_store.counts(online.device).get("crash_reports", 0) == 0
                # A restart interrupted the deliveries after the ingest kept them: the device still holds them as
                # pending and resends them with the same keys (ARC-09). The ingest keeps each once and answers "seen
                # already", which the outbox counts as delivered.
                for outbox_id, payload in queued:
                    online.device.execute("UPDATE outbox SET delivered_at = NULL, payload = ? WHERE outbox_id = ?",
                                          (payload, outbox_id))  # fmt: skip
                assert await online.drain_once(force=True) == 2
                assert not egress_store.pending(online.device)
            finally:
                await online.stop()

    asyncio.run(scenario())
    stored_reports = IngestStore(tmp_path / "ingest")  # the server's own handle closed with it
    crashes = stored_reports.reports("crash_report", "0000-00-00", "9999-99-99", 10)
    telemetry = stored_reports.reports("telemetry", "0000-00-00", "9999-99-99", 10)
    assert [row["report"] for row in crashes] == [report], "exactly the report the adult saw"
    assert len(telemetry) == 1 and validation.telemetry_problems(telemetry[0]["report"]) == []
    stored = (tmp_path / "ingest" / "ingest.sqlite3").read_bytes()
    assert STUDENT.encode() not in stored and b"ses_SYNTH" not in stored
    assert b"127.0.0.1" not in stored, "no client address is stored"


def test_sec21_outbox_refuses_credentials_and_bad_bodies(tmp_path: Path):
    """Anonymous uploads only; each body must be one strict JSON object that satisfies its contract and matches
    its idempotency key; a refused body is stored nowhere."""
    application = app(tmp_path, Clock())
    report = _report(tmp_path)
    key = f"crash-{report['crash_id']}"

    async def post(kind: str, body: Any, idem: str | None, **headers: str) -> tuple[int, str]:
        raw = body if isinstance(body, bytes) else json.dumps(body).encode()
        sent = {"content-type": "application/octet-stream", **({"idempotency-key": idem} if idem else {}), **headers}
        async with client(application) as http:
            reply = await http.post(f"/v1/outbox/{kind}", content=raw, headers=sent)
        return reply.status_code, reply.json()["error"]["code"] if reply.status_code >= 400 else ""

    async def scenario() -> None:
        assert await post("crash_report", report, key, authorization="Bearer abc") == (400, "credential_not_accepted")
        assert await post("crash_report", report, key, cookie="a=b") == (400, "credential_not_accepted")
        assert await post("crash_report", report, None) == (400, "idempotency_key_required")
        assert await post("backup_snapshot", report, key) == (404, "unknown_kind")
        assert await post("crash_report", report, "crash-someone-else") == (422, "contract_violation")
        assert await post("crash_report", {**report, "correlation": {"turn_id": "t"}}, key) == (
            422, "contract_violation")  # fmt: skip
        frame = {"file": "x.py", "line": 1, "function": "f", "locals": "x=1"}
        assert await post("crash_report", {**report, "stack": [frame]}, key) == (422, "contract_violation")
        assert await post("crash_report", {**report, "detail": {"student": STUDENT}}, key) == (
            422, "contract_violation")  # fmt: skip
        assert await post("crash_report", {**report, "day": report["day"] + 1}, key) == (422, "contract_violation")
        for leak in ("write to someone@example.com", "path /Users/kofi/Documents/x", "Bearer abcdef0123456789xyz"):
            assert await post("crash_report", {**report, "log_tail": [leak]}, key) == (422, "redaction_blocked"), leak
        duplicated = b'{"crash_id": "a", "crash_id": "b"}'
        assert await post("crash_report", duplicated, key) == (400, "invalid_json")
        assert await post("crash_report", b"[1, 2]", key) == (400, "invalid_json")
        assert await post("crash_report", b"\xff\xfe", key) == (400, "invalid_json")
        big = {**report, "log_tail": ["x" * 300] * 3000}
        assert (await post("crash_report", big, key))[0] == 413

        payload = json.loads(_telemetry())
        rid = payload["report_id"]
        assert await post("telemetry", payload, "not-the-report-id") == (422, "contract_violation")
        assert await post("telemetry", {**payload, "note": "free text"}, rid) == (422, "contract_violation")
        assert await post("telemetry", {**payload, "channel": "nightly"}, rid) == (422, "contract_violation")
        nan = json.dumps(payload).replace('"days": 1', '"days": NaN').encode()
        assert await post("telemetry", nan, rid) == (400, "invalid_json")
        assert await post("telemetry", payload, rid) == (201, "")
        assert await post("telemetry", payload, rid) == (409, "seen_already")
        assert await post("crash_report", report, key) == (201, "")

    asyncio.run(scenario())
    store = application.state.ingest.store
    assert len(store.reports("crash_report", "0000", "9999", 10)) == 1
    assert len(store.reports("telemetry", "0000", "9999", 10)) == 1


def _telemetry() -> bytes:
    from agent_core.config.telemetry_schema import report

    metrics: dict[str, Any] = {}
    observe(metrics, "model_calls", 2)
    return json.dumps(report(metrics, days=1, **METADATA)).encode()


def test_obs17_obs20_retention_and_deletion(tmp_path: Path):
    """Reports are purged after their retention; a deletion request naming a crash report removes it at once and
    is logged; a dashboard read is logged too."""
    clock = Clock()
    application = app(tmp_path, clock)
    ingest = application.state.ingest
    retention = ingest.config.retention
    report = _report(tmp_path)

    async def scenario() -> None:
        async with client(application) as http:

            async def send(kind: str, body: bytes, key: str) -> int:
                reply = await http.post(f"/v1/outbox/{kind}", content=body, headers={"idempotency-key": key})
                return reply.status_code

            crash, crash_key = json.dumps(report).encode(), f"crash-{report['crash_id']}"
            assert await send("crash_report", crash, crash_key) == 201
            body = _telemetry()
            assert await send("telemetry", body, json.loads(body)["report_id"]) == 201
            listing = await http.get("/admin/v1/reports/crash_report", headers={"authorization": "Bearer nope"})
            assert listing.status_code == 401
            everything = "?from=0000-00-00&to=9999-99-99"
            listing = await http.get(f"/admin/v1/reports/crash_report{everything}", headers=staff("ben"))
            assert [r["report"] for r in listing.json()["reports"]] == [report]

            clock.now += (retention.crash_report_days + 1) * 86_400
            assert ingest.purge()["reports"] == 1, "the crash report is past its retention"
            assert ingest.store.reports("telemetry", "0000", "9999", 10), "telemetry is kept longer"
            clock.now += (retention.telemetry_days + 1) * 86_400
            assert ingest.purge()["reports"] == 1
            # A resend of a purged report is new to the service: it is kept again (and purged again in time).
            assert await send("crash_report", crash, crash_key) == 201
            erased = await http.post(f"/admin/v1/reports/crash_report/{report['crash_id']}/erase", headers=staff("cy"))
            assert erased.json() == {"erased": True}
            assert not ingest.store.reports("crash_report", "0000", "9999", 10)

    asyncio.run(scenario())
    log = ingest.store.access_log(f"crash_report:{report['crash_id']}")
    assert [(e["actor"], e["action"], e["allowed"]) for e in log] == [("cy", "report.erase", True)]


def test_ingest_page_and_probe(tmp_path: Path):
    application = app(tmp_path, Clock())

    async def scenario() -> None:
        async with client(application) as http:
            assert (await http.get("/v1/ping")).status_code == 204
            assert (await http.get("/v1/status")).json() == {"status": "ok"}
            page = await http.get("/support")
            assert page.status_code == 200 and "default-src 'none'" in page.headers["content-security-policy"]
            days = application.state.ingest.config.retention.bundle_days
            assert f"after {days} days" in page.text and "{{" not in page.text
            assert (await http.get("/support/upload.js")).headers["content-type"].startswith("text/javascript")
            assert all(h.endswith(".invalid") for h in (HOSTS["crash"], HOSTS["telemetry"])), "placeholders"

    asyncio.run(scenario())


@pytest.mark.parametrize("value", [math.inf, -math.inf])
def test_ingest_non_finite_measurements_refused(value: float):
    payload = json.loads(_telemetry())
    payload["metrics"]["model_calls"]["sum"] = value
    assert "non-finite measurement" in validation.telemetry_problems(payload)
