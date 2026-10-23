"""The ingest checks crash reports and telemetry against the outbox contract the core sends them by, and answers with
the contract's receipt and refusals (cloud/outbox, D98, D99). Data is synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import errors as core_errors
from agent_core.net import crash_reports
from agent_core.store.keystore import MemoryKeyStore
from agent_core.trace.crashes import CrashStore, device_key
from ingest import contracts, support, validation
from ingest_harness import Clock, app, client

CRASH = "cloud/outbox#/$defs/CrashReport"


def _report(tmp: Path) -> dict[str, Any]:
    store = CrashStore(tmp / "crashes", device_key(MemoryKeyStore()), "1.0.0", Settings())
    record = store.record("worker", "worker_limit", [], detail={"tool": "math_solve", "limit": "cpu_ms"})
    return crash_reports.build_report(record, "mid")


def test_obs17_ingest_and_core_check_one_contract():
    """The ingest validates with the same contract the core's outbox validates with before it queues a report, and
    the core sends exactly the contract's fields."""
    assert validation.CONTRACT["crash_report"] == crash_reports.CONTRACT == CRASH
    shape = contracts.document("cloud/outbox")["$defs"]["CrashReport"]
    assert set(crash_reports.ALLOWED) == set(shape["required"]) == set(shape["properties"])
    assert set(crash_reports.STACK_FIELDS) == set(shape["properties"]["stack"]["items"]["properties"])
    assert set(crash_reports.DETAIL_FIELDS) == set(shape["properties"]["detail"]["properties"])


def _variants(report: dict[str, Any]) -> list[dict[str, Any]]:
    frame = {"file": "~/x.py", "line": 3, "function": "f"}
    return [
        report,
        {**report, "stack": [frame, {"module": "core.dll", "offset": "0x1f"}]},
        {**report, "stack": [frame, {"module": "core.dll", "offset": 31}]},
        {**report, "stack": [{**frame, "line": None}]},
        {**report, "stack": [{**frame, "locals": "x"}]},
        {**report, "stack": [{**frame, "line": -1}]},
        {**report, "stack": [frame] * 201},
        {**report, "detail": {"exit_code": 3}},
        {**report, "detail": {"exit_code": -11}},
        {**report, "detail": {"model": "m"}},
        {**report, "process": "browser"},
        {**report, "kind": "oops"},
        {**report, "hardware_class": None},
        {**report, "hardware_class": "huge"},
        {**report, "error_type": "x" * 81},
        {**report, "version": "1" * 41},
        {**report, "log_tail": ["x" * 301]},
        {**report, "day": report["day"] + 1000},
        {**report, "day": -86_400_000},
        {**report, "crash_id": "has space"},
        {**report, "extra": 1},
        {k: v for k, v in report.items() if k != "log_tail"},
    ]


def test_obs17_ingest_agrees_with_core_contract(tmp_path: Path):
    """On a set of near-miss reports, the ingest accepts exactly what the core's copy of the contract accepts, so a
    report the core queued is never refused for its shape, and a whole UTC day is required (OBS-19a)."""
    report = _report(tmp_path)
    assert report["day"] % 86_400_000 == 0
    verdicts = []
    for variant in _variants(report):
        ours = validation.crash_report_problems(variant) == []
        assert ours == (core_errors(CRASH, variant) == []), variant
        verdicts.append(ours)
    assert verdicts[:5] == [True, True, True, True, False] and verdicts.count(True) >= 7


def test_obs17_replies_match_contract(tmp_path: Path):
    """201 is an `OutboxReceipt`; 409 seen already and every refusal an `OutboxError`, whose message never quotes the
    body (OBS-19)."""
    application = app(tmp_path, Clock())
    report = _report(tmp_path)

    async def scenario() -> None:
        async with client(application) as http:
            headers = {"idempotency-key": f"crash-{report['crash_id']}"}
            first = await http.post("/v1/outbox/crash_report", content=json.dumps(report), headers=headers)
            again = await http.post("/v1/outbox/crash_report", content=json.dumps(report), headers=headers)
            bad = await http.post("/v1/outbox/crash_report", content=b"{}", headers=headers)
            secret = {**report, "crash_id": "zz_" + report["crash_id"][:20], "version": "the student wrote x" * 3}
            quoted = await http.post("/v1/outbox/crash_report", content=json.dumps(secret),
                                     headers={"idempotency-key": f"crash-{secret['crash_id']}"})  # fmt: skip
            assert (first.status_code, again.status_code, bad.status_code) == (201, 409, 422)
            assert contracts.errors("cloud/outbox#/$defs/OutboxReceipt", first.json()) == []
            for reply in (again, bad, quoted):
                assert contracts.errors("cloud/outbox#/$defs/OutboxError", reply.json()) == [], reply.json()
            assert quoted.status_code == 422 and "student" not in quoted.text

    asyncio.run(scenario())


def test_ops24_ticket_reference_is_the_contracts():
    """The support upload's ticket reference pattern is the contract's (ops/support-upload)."""
    pattern = contracts.document("ops/support-upload")["$defs"]["TicketRef"]["pattern"]
    assert support.TICKET_PATTERN.pattern == pattern
