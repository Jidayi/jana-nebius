"""Offline release-operations CLI (OPS-06..38)."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.operations import atomic_json
from agent_core.config.support import HelpCatalogue
from pydantic import TypeAdapter

from . import incidents as inc
from . import operations as ops


@dataclass
class GateReference:
    path: str
    sha256: str
    reviewer: str


@dataclass
class Dossier:
    candidate: ops.Candidate
    gates: dict[str, GateReference]
    signoffs: ops.Signoffs
    freezes: list[tuple[datetime, datetime]]
    notes: ops.ReleaseNotes
    previous_notice: str
    previous_data_policy: dict[str, Any]
    data_policy: dict[str, Any]


def promotion_dossier_errors(data: dict[str, Any], root: Path, now: datetime) -> list[str]:
    dossier = TypeAdapter(Dossier).validate_json(json.dumps(data), strict=True)
    results = {}
    errors = []
    for name, reference in dossier.gates.items():
        try:
            path = (root / reference.path).resolve()
            body = path.read_bytes()
            if hashlib.sha256(body).hexdigest() != reference.sha256:
                raise ValueError("evidence digest mismatch")
            report = json.loads(body)
            if report.get("gate") != name:
                raise ValueError("evidence gate mismatch")
            results[name] = TypeAdapter(ops.GateResult).validate_json(
                json.dumps(
                    {
                        "candidate_sha256": report["candidate_sha256"],
                        "passed": report["passed"],
                        "report_sha256": reference.sha256,
                        "measured_at": report["measured_at"],
                        "reviewer": reference.reviewer,
                    }
                ),
                strict=True,
            )
        except (OSError, ValueError, KeyError):
            errors.append(f"OPS-06: invalid report for {name}")
    errors += ops.promotion_errors(dossier.candidate, results, dossier.signoffs, now)
    errors += ops.freeze_errors(dossier.candidate, now, dossier.freezes)
    errors += ops.notes_errors(
        dossier.notes,
        data_changed=dossier.previous_data_policy != dossier.data_policy,
        previous_notice=dossier.previous_notice,
    )
    return errors


def gateway_policy(cfg: Settings | None = None) -> dict[str, Any]:
    cfg = cfg or Settings()
    return {
        "probe_interval_s": cfg.ops_probe_interval_s,
        "window_s": cfg.ops_probe_window_s,
        "failure_share": cfg.ops_probe_failure_share,
        "latency_multiple": cfg.ops_probe_latency_multiple,
        "latency_objective_s": cfg.ops_first_words_p95_s,
        "healthy_s": cfg.ops_failback_healthy_s,
        "qualified_providers": [],
        "cost_history_days": cfg.ops_cost_history_days,
        "cost_multiple": cfg.ops_cost_multiple,
        "metadata_retention_days": cfg.ops_metadata_retention_days,
    }


def validate_record(kind: str, data: dict[str, Any], now: datetime) -> list[str]:
    if kind == "bandwidth":
        if "transfers" not in data:
            return ["OPS-16: verified reference transfer captures required"]
        transfers = TypeAdapter(list[ops.ReferenceTransfer]).validate_json(json.dumps(data["transfers"]), strict=True)
        amounts = ops.measure_bandwidth(transfers)
        return ops.budget_errors(
            amounts,
            data.get("exceptions", {}),
            model_selected=data.get("model_selected") is True,
            metered_authorised=data.get("metered_authorised") is True,
        )
    if kind == "lifecycle":
        return ops.lifecycle_errors(
            TypeAdapter(list[ops.LifecycleRun]).validate_python(data["runs"]),
            tuple(data["supported_apps"]),
            tuple(data["platforms"]),
        )
    if kind == "weekly":
        return inc.weekly_errors(TypeAdapter(inc.Weekly).validate_python(data["record"]), cloud_live=data["cloud_live"])
    if kind == "incident":
        calendar = TypeAdapter(inc.SchoolCalendar).validate_python(data["calendar"]) if "calendar" in data else None
        return inc.incident_errors(TypeAdapter(inc.Incident).validate_python(data["record"]), calendar=calendar)
    if kind == "drills":
        return inc.drill_errors(
            data["stage"],
            now,
            TypeAdapter(list[inc.Drill]).validate_python(data["records"]),
            term_start=datetime.fromisoformat(data["term_start"]),
            release_at=datetime.fromisoformat(data["release_at"]),
        )
    if kind == "slo":
        return list(ops.slo_report(TypeAdapter(list[ops.ServiceSample]).validate_python(data["samples"]))["errors"])
    if kind == "docs":
        return HelpCatalogue(data["app_version"]).docs_errors(data["manifest"])
    if kind == "page":
        return inc.page_errors(TypeAdapter(inc.Page).validate_python(data))
    if kind == "usb":
        return ops.usb_batch_errors(
            data["batch_size"], data["sha256"], TypeAdapter(list[ops.USBCheck]).validate_python(data["checks"])
        )
    raise ValueError("OPS-06: unknown record kind")


def run(args: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jana_tools release ops")
    parser.add_argument("command", choices=("validate", "promote", "gateway-config", "runbooks", "monitor"))
    parser.add_argument(
        "--kind", choices=("bandwidth", "lifecycle", "weekly", "incident", "drills", "slo", "docs", "page", "usb")
    )
    parser.add_argument("--state", type=Path)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--out", type=Path)
    options = parser.parse_args(args)
    now = datetime.now(UTC)
    try:
        if options.command == "monitor":
            from .monitor import ReleaseMonitor

            if options.input is None or options.state is None:
                raise ValueError("OPS-09: --input and --state required")
            output = asyncio.run(ReleaseMonitor(options.state).watch(options.input, once=options.once))
        elif options.command == "gateway-config":
            output = gateway_policy()
        elif options.command == "runbooks":
            output = {
                "required": inc.required_drills("S2"),
                "runbooks": json.loads(Path(__file__).with_name("runbooks.json").read_text()),
            }
        else:
            if options.input is None:
                raise ValueError("OPS-06: --input required")
            data = json.loads(options.input.read_text())
            if options.command == "promote":
                errors = promotion_dossier_errors(data, options.input.parent, now)
            else:
                errors = validate_record(options.kind or "", data, now)
            output = {
                "checked_at": now.isoformat(),
                "passed": not errors,
                "errors": errors,
                "input_sha256": hashlib.sha256(options.input.read_bytes()).hexdigest(),
            }
            if errors:
                print(json.dumps(output, sort_keys=True))
                return 1
        if options.out:
            if options.out.exists():
                raise ValueError("OPS-06: output record already exists")
            atomic_json(options.out, output)
        print(json.dumps(output, sort_keys=True))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(
            json.dumps({"passed": False, "errors": [f"OPS-06: invalid operations evidence ({type(error).__name__})"]})
        )
        return 1
