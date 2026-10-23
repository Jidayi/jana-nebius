"""M23 metrics and privacy checks use synthetic records only."""

from __future__ import annotations

import asyncio
import copy
import json
from datetime import date

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors


def technical():
    from agent_core.trace.metrics import from_traces

    return from_traces(
        [
            {
                "duration_ms": 100,
                "status": "complete",
                "compaction": None,
                "model_calls": [
                    {"role": "coach", "tier": "local", "latency": {"ttft_ms": 20}, "fallback": False, "cache_hit": True}
                ],
                "tool_calls": [{"name": "math_eval", "status": "ok", "duration_ms": 12}],
                "gates": [],
                "guards": [],
                "profile_ref": "PRIVATE-CANARY",
                "text": "PRIVATE-CANARY",
            }
        ]
    )


def payload():
    from agent_core.config.telemetry_schema import report

    return report(
        technical(),
        app_version="0.1.0",
        channel="pilot",
        hardware_class="low",
        os_family="linux",
        router_tier="local",
        days=1,
    )


def obs13_metrics_match_reference():
    result = technical()
    assert result["turn_duration_ms"]["sum"] == 100
    assert result["ttft_ms"]["sum"] == 20
    assert result["tool_duration_ms"]["sum"] == 12
    assert result["turn_complete"]["sum"] == 1
    assert result["model_calls"]["sum"] == 1
    assert result["model_cache_hits"]["sum"] == 1
    from agent_core.trace.metrics import from_traces

    merged = from_traces([{"duration_ms": n, "status": "error"} for n in (10, 30, 50)])
    assert merged["turn_duration_ms"]["count"] == 3
    assert merged["turn_duration_ms"]["sum"] == 90
    assert sum(merged["turn_duration_ms"]["buckets"]) == 3


def obs20_telemetry_schema_allow_list():
    from agent_core.config.telemetry_schema import problems

    value = payload()
    assert not problems(value)
    assert contract_errors("trace/telemetry", value) == []
    assert payload()["report_id"] != value["report_id"]
    for mutation in (
        {**value, "note": "PRIVATE-CANARY"},
        {**value, "os_family": "my personal computer"},
        {**value, "app_version": "PRIVATE-CANARY"},
        {**value, "metrics": {"PRIVATE-CANARY": value["metrics"]["model_calls"]}},
    ):
        assert problems(mutation)


def prv09_telemetry_allowlist():
    from agent_core.config.telemetry_schema import problems

    value = payload()
    for name in ("profile_id", "device_id", "school_id", "turns", "kc_mastery", "notes", "image", "audio"):
        assert problems({**value, name: "PRIVATE-CANARY"})
    value["metrics"]["model_calls"]["student_text"] = "PRIVATE-CANARY"
    assert problems(value)


def prd19_telemetry_schema_no_pii():
    from agent_core.config.telemetry_schema import problems

    value = payload()
    assert "PRIVATE-CANARY" not in json.dumps(value)
    for name in ("count", "sum"):
        bad = copy.deepcopy(value)
        bad["metrics"]["model_calls"][name] = "PRIVATE-CANARY"
        assert problems(bad)
    bad = copy.deepcopy(value)
    bad["metrics"]["model_calls"]["sum"] = float("nan")
    assert problems(bad)
    bad = copy.deepcopy(value)
    bad["metrics"]["model_calls"]["count"] = True
    assert problems(bad)


def obs20_offline_backlog_bounded(tmp_path):
    from agent_core.net.telemetry import TelemetryQueue
    from agent_core.store import egress
    from net_harness import enable, layer

    online = layer(tmp_path)
    enable(online, "telemetry")
    start = date(2026, 1, 1)
    clock = [
        int(
            __import__("datetime")
            .datetime.combine(start, __import__("datetime").time(), __import__("datetime").UTC)
            .timestamp()
            * 1000
        )
    ]
    online.clock_ms = lambda: clock[0]
    queue = TelemetryQueue(online)
    for _day in range(20):
        clock[0] += 86_400_000
        queue.add(
            technical(),
            app_version="0.1.0",
            channel="pilot",
            hardware_class="low",
            os_family="linux",
            router_tier="local",
        )
    queue = TelemetryQueue(online)
    assert len(queue.days()) == Settings().retention_telemetry_days
    online.connectivity.state = "online"
    assert queue.prepare() is not None
    queued = [p for p in egress.pending(online.device, "telemetry") if p.kind == "telemetry"]
    assert len(queued) == 1
    sent = json.loads(queued[0].payload)
    assert sent["days"] == Settings().retention_telemetry_days
    assert sent["metrics"]["model_calls"]["sum"] == Settings().retention_telemetry_days
    assert queue.prepare() is None
    enable_off = getattr(online, "switch", None)
    assert enable_off is None or callable(enable_off)
    asyncio.run(online.stop())


def prv09_crash_redaction():
    from agent_core.net.crash_reports import build_report, report_problems

    seeded = {
        "crash_id": "synthetic",
        "process": "core",
        "kind": "exception",
        "version": "0.1.0",
        "transcript": "PRIVATE-CANARY",
        "notes": "PRIVATE-CANARY",
        "log_tail": [],
        "stack": [],
    }
    value = build_report(seeded, "low")
    assert "PRIVATE-CANARY" not in json.dumps(value)
    assert not report_problems(value, ["PRIVATE-CANARY"])
    value["log_tail"] = ["PRIVATE-CANARY"]
    assert report_problems(value, ["PRIVATE-CANARY"])


def prd19_small_cohort_suppressed():
    from agent_core.trace.research import statistic

    assert statistic(9, 18)["value"] is None
    assert statistic(10, 18)["value"] == 1.8
    assert statistic(9, 18)["review_required"] is True


def mem26_no_memory_in_analytics():
    from agent_core.trace.research import project

    rows = {
        "events": [
            {"type": "note_written", "payload": {"text": "PRIVATE-CANARY"}},
            {
                "type": "attempt",
                "occurred_at": "2026-01-01T00:00:00Z",
                "payload": {"text": "PRIVATE-CANARY", "active_ms": 12, "correct": True},
            },
        ],
        "notes": [{"text": "PRIVATE-CANARY"}],
        "transcripts": ["PRIVATE-CANARY"],
        "kc_mastery": [],
    }
    result = project(rows)
    assert "PRIVATE-CANARY" not in json.dumps(result)
    assert result["events"] == [{"type": "attempt", "day": "2026-01-01", "active_ms": 12, "correct": True}]


def test_telemetry_keeps_version_and_tier_breakdowns(tmp_path):
    from agent_core.net.telemetry import TelemetryQueue
    from agent_core.store import egress
    from net_harness import enable, layer

    online = layer(tmp_path)
    enable(online, "telemetry")
    queue = TelemetryQueue(online)
    for version, tier in (("0.1.0", "local"), ("0.2.0", "cloud")):
        queue.add(
            technical(), app_version=version, channel="pilot", hardware_class="low", os_family="linux", router_tier=tier
        )
    online.connectivity.state = "online"
    queue.prepare()
    value = json.loads(egress.pending(online.device, "telemetry")[0].payload)
    assert {(row["app_version"], row["router_tier"]) for row in value["series"]} == {
        ("0.1.0", "local"),
        ("0.2.0", "cloud"),
    }
    asyncio.run(online.stop())


def test_metrics_use_runtime_trace_fields():
    from agent_core.trace.metrics import from_traces

    values = from_traces(
        [
            {
                "status": "complete",
                "duration_ms": 100,
                "model_calls": [
                    {
                        "role": "solver",
                        "tier": "local",
                        "fallback_from": "base",
                        "schema_valid": False,
                        "error_class": "empty",
                        "tokens": {"input": 100, "output": 10, "cache_read": 40},
                        "latency": {"prompt_eval_ms": 50, "generation_ms": 100, "ttft_ms": 20},
                        "cost_usd": 0.1,
                    }
                ],
                "gates": [{"gate": "verification", "fired": True, "outcome": "exhausted_canned"}],
            }
        ]
    )
    assert values["model_fallbacks"]["sum"] == 1
    assert values["model_invalid"]["sum"] == 1
    assert values["model_empty"]["sum"] == 1
    assert values["model_cache_hits"]["sum"] == 1
    assert values["gate_exhausted"]["sum"] == 1
    assert values["prompt_tokens_per_s"]["sum"] == 2000
    assert values["generation_tokens_per_s"]["sum"] == 100


def test_catalogue_groups_traces_and_logs_without_content():
    from agent_core.trace.metrics import catalogue

    metadata = {"app_version": "0.1.0", "channel": "pilot", "hardware_class": "low", "os_family": "linux"}
    trace = {
        "build": metadata,
        "duration_ms": 100,
        "status": "complete",
        "mode": "guided",
        "tool_calls": [{"name": "math_evaluate", "status": "ok", "duration_ms": 12}],
        "model_calls": [{"role": "coach", "tier": "local", "latency": {"ttft_ms": 20}}],
        "notes": "PRIVATE-CANARY",
    }
    logs = [
        {**metadata, "router_tier": "local", "metric": "ready_ms", "value": 123, "message": "PRIVATE-CANARY"},
        {**metadata, "router_tier": "local", "metric": "peak_memory_mb", "value": 64},
    ]
    result = catalogue([trace], logs)
    assert "PRIVATE-CANARY" not in json.dumps(result)
    assert any(row["labels"].get("tool") == "math_evaluate" for row in result["series"])
    assert result["tools"]["math_evaluate"]["p50_ms"] == 12
    assert result["tools"]["math_evaluate"]["p95_ms"] == 12
    assert any(row["metrics"].get("ready_ms", {}).get("sum") == 123 for row in result["series"])


def test_telemetry_queue_and_day_marker_are_atomic(tmp_path, monkeypatch):
    import pytest
    from agent_core.net.telemetry import TelemetryQueue
    from agent_core.store import egress
    from net_harness import enable, layer

    online = layer(tmp_path)
    enable(online, "telemetry")
    queue = TelemetryQueue(online)
    queue.add(
        technical(), app_version="0.1.0", channel="pilot", hardware_class="low", os_family="linux", router_tier="local"
    )
    online.connectivity.state = "online"

    def fail(_):
        raise RuntimeError("synthetic power failure")

    monkeypatch.setattr(queue, "_write", fail)
    with pytest.raises(RuntimeError):
        queue.prepare()
    assert egress.pending(online.device, "telemetry") == []
    asyncio.run(online.stop())


def test_obs20_invalid_report_never_queued(tmp_path, monkeypatch):
    """PRV-09, OBS-20: a report its schema refuses is not queued, by a check that holds under `python -O` (no assert);
    the day's counts stay for the next attempt."""
    from agent_core.net import telemetry
    from agent_core.store import egress
    from net_harness import enable, layer

    online = layer(tmp_path)
    enable(online, "telemetry")
    queue = telemetry.TelemetryQueue(online)
    queue.add(
        technical(), app_version="0.1.0", channel="pilot", hardware_class="low", os_family="linux", router_tier="local"
    )
    online.connectivity.state = "online"
    real = telemetry.report
    monkeypatch.setattr(telemetry, "report", lambda *a, **k: {**real(*a, **k), "student_name": "x"})
    assert queue.prepare() is None
    assert egress.pending(online.device, "telemetry") == []
    monkeypatch.setattr(telemetry, "report", real)
    assert queue.prepare() is not None, "the kept days go out once the report is valid"
    asyncio.run(online.stop())
