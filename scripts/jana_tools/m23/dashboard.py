"""OBS-21: developer summaries from technical reports only."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from agent_core.config.telemetry_schema import problems
from agent_core.trace.metrics import merge

SOURCES = {"telemetry", "evaluation", "device_lab"}


def dashboard(records: list[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[str, Any] = {}
    changes = []
    adoption: dict[str, int] = {}
    for record in records:
        if set(record) - {"source", "payload", "commit", "model", "fingerprints", "previous_fingerprints"}:
            raise ValueError("OBS-21: content is not a dashboard input")
        if record.get("source") not in SOURCES or problems(record.get("payload")):
            raise ValueError("OBS-21: only validated technical reports are accepted")
        commit = record.get("commit")
        if commit is not None and not re.fullmatch(r"[a-f0-9]{40}", commit):
            raise ValueError("OBS-21: invalid evaluation commit")
        if record["source"] == "telemetry" and set(record) != {"source", "payload"}:
            raise ValueError("OBS-21: telemetry has no per-model or commit identifiers")
        for key in ("fingerprints", "previous_fingerprints"):
            if set(record.get(key, {})) - {"prompts", "skills", "model", "content"}:
                raise ValueError("OBS-21: unsupported fingerprint class")
            if any(not re.fullmatch(r"[a-f0-9]{64}", str(value)) for value in record.get(key, {}).values()):
                raise ValueError("OBS-21: fingerprint must be a hash")
        report = record["payload"]
        model_ref = hashlib.sha256(str(record.get("model", "")).encode()).hexdigest() if record.get("model") else None
        if record["source"] != "telemetry":
            current, previous = record.get("fingerprints", {}), record.get("previous_fingerprints", {})
            changes.append(
                {
                    "commit": commit,
                    "model_ref": model_ref,
                    "fingerprints_changed": sorted(
                        k for k in set(current) | set(previous) if current.get(k) != previous.get(k)
                    ),
                }
            )
        version_key = f"{report['channel']}:{report['app_version']}"
        adoption[version_key] = adoption.get(version_key, 0) + 1
        key = f"{report['app_version']}:{report['hardware_class']}:{report['router_tier']}:{report['channel']}"
        key += f":{commit}:{model_ref}"
        old = groups.get(key, {}).get("metrics", {})
        groups[key] = {
            "app_version": report["app_version"],
            "hardware_class": report["hardware_class"],
            "router_tier": report["router_tier"],
            "channel": report["channel"],
            "commit": commit,
            "model_ref": model_ref,
            "metrics": merge([old, report["metrics"]]),
        }
    return {
        "reports": len(records),
        "groups": list(groups.values()),
        "changes": changes,
        "version_report_share": {key: value / len(records) for key, value in adoption.items()},
    }
