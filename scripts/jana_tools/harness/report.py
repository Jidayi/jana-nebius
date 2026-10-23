"""Evaluation reports (EVL-23): one machine-readable report per run, validated before it is used, and a summary.

A report carries the suite versions and lock hashes, the build, the model ids and quantisations, the prompt and
skill fingerprints, the hardware, the network state and egress count, the seeds, per-suite and per-criterion results
with Wilson 95% intervals, every case with its trace ids, and the diff against the previous release report. A
held-out suite reports aggregates only: its cases carry no ids, no traces and no content.
"""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

INTERVAL = {"type": "array", "items": {"type": "number", "minimum": 0, "maximum": 1}, "minItems": 2, "maxItems": 2}
RESULT = {
    "type": "object",
    "additionalProperties": False,
    "required": ["passed", "total", "rate", "interval"],
    "properties": {"passed": {"type": "integer", "minimum": 0}, "total": {"type": "integer", "minimum": 0},
                   "rate": {"type": ["number", "null"]}, "interval": INTERVAL},
}  # fmt: skip
SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "Evaluation report (EVL-23)",
    "type": "object",
    "additionalProperties": False,
    "required": ["report_version", "run_id", "mode", "created_at", "build", "models", "fingerprints", "hardware",
                 "network", "seeds", "suites", "cases", "diff", "valid", "eval_only_paths"],
    "properties": {
        "report_version": {"const": 1},
        "run_id": {"type": "string", "minLength": 8},
        "mode": {"enum": ["development", "release"]},
        "created_at": {"type": "string", "format": "date-time"},
        "build": {"type": "object", "required": ["app_version", "commit", "stage"], "additionalProperties": False,
                  "properties": {"app_version": {"type": "string"}, "commit": {"type": "string"},
                                 "stage": {"enum": ["S1", "S2", "S3", "S4", "S5"]}}},
        "models": {"type": "array", "items": {"type": "object", "required": ["id", "quantisation", "tier"],
                   "additionalProperties": False, "properties": {"id": {"type": "string"},
                   "quantisation": {"type": "string"}, "tier": {"type": "string"}}}},
        "fingerprints": {"type": "object", "required": ["prompts", "skills"], "additionalProperties": False,
                         "properties": {"prompts": {"type": "object"}, "skills": {"type": "object"}}},
        "hardware": {"type": "object", "required": ["hardware_class", "os", "arch", "ram_gb"],
                     "additionalProperties": False, "properties": {
                         "hardware_class": {"enum": ["content_only", "low", "mid", "high", "cloud"]},
                         "os": {"type": "string"}, "arch": {"type": "string"},
                         "ram_gb": {"type": "number", "minimum": 0}, "machine": {"type": "string"}}},
        "network": {"type": "object", "required": ["state", "egress_attempts"], "additionalProperties": False,
                    "properties": {"state": {"enum": ["disabled", "enabled"]},
                                   "egress_attempts": {"type": "integer", "minimum": 0}}},
        "seeds": {"type": "array", "items": {"type": "integer"}, "minItems": 1},
        "suites": {"type": "object", "additionalProperties": {
            "type": "object", "required": ["version", "lock_sha256", "split", "status", "result", "criteria"],
            "additionalProperties": False, "properties": {
                "version": {"type": "string"}, "lock_sha256": {"type": "string", "pattern": "^[0-9a-f]{64}$"},
                "split": {"enum": ["development", "held_out", "regression"]},
                "status": {"enum": ["ran", "not_selected", "delegated", "not_run_stage", "not_run_needs_model",
                                    "not_run_device_lab"]},
                "result": RESULT, "criteria": {"type": "object", "additionalProperties": RESULT}}}},
        "cases": {"type": "array", "items": {
            "type": "object", "required": ["suite", "case_id", "status", "critical", "trace_ids"],
            "additionalProperties": False, "properties": {
                "suite": {"type": "string"}, "case_id": {"type": "string"},
                "status": {"enum": ["passed", "failed", "skipped"]}, "critical": {"type": "boolean"},
                "trace_ids": {"type": "array", "items": {"type": "string"}},
                "hardware_class": {"type": "string"}, "reason": {"type": "string"},
                "numbers_total": {"type": "integer", "minimum": 0}, "numbers_traced": {"type": "integer", "minimum": 0},
                "leaks": {"type": "integer", "minimum": 0}, "reader_path": {"type": "string"}}}},
        "diff": {"type": "object", "required": ["against"], "additionalProperties": False, "properties": {
            "against": {"type": ["string", "null"]},
            "rates": {"type": "object", "additionalProperties": {"type": ["number", "null"]}}}},
        "valid": {"type": "boolean", "description": "False when the run is not usable as a gate (egress, lock)."},
        "invalid_reasons": {"type": "array", "items": {"type": "string"}},
        "eval_only_paths": {"type": "array", "maxItems": 0, "description": "No product path branches on the harness."},
    },
}  # fmt: skip


def wilson(passed: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    """The Wilson 95% score interval for a proportion (0, 0 for an empty sample)."""
    if total == 0:
        return (0.0, 0.0)
    p = passed / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    half = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return (0.0 if passed == 0 else max(0.0, centre - half), 1.0 if passed == total else min(1.0, centre + half))


def result(passed: int, total: int) -> dict[str, Any]:
    low, high = wilson(passed, total)
    return {"passed": passed, "total": total, "rate": (passed / total) if total else None,
            "interval": [round(low, 6), round(high, 6)]}  # fmt: skip


def lock_sha256(lock_entry: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(lock_entry, sort_keys=True).encode()).hexdigest()


def errors(report: dict[str, Any]) -> list[str]:
    validator = Draft202012Validator(SCHEMA)
    return [f"{'/'.join(str(p) for p in e.absolute_path) or '$'}: {e.message}" for e in validator.iter_errors(report)]


def diff(report: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    if previous is None:
        return {"against": None}
    rates = {}
    for name, suite in report["suites"].items():
        before = previous.get("suites", {}).get(name, {}).get("result", {}).get("rate")
        now = suite["result"]["rate"]
        rates[name] = None if before is None or now is None else round(now - before, 6)
    return {"against": previous["run_id"], "rates": rates}


def summary(report: dict[str, Any]) -> str:
    lines = [f"# Evaluation run {report['run_id']} ({report['mode']})", "",
             f"Build {report['build']['app_version']} at {report['build']['commit']} · "
             f"{report['hardware']['hardware_class']} class on {report['hardware']['os']} · network "
             f"{report['network']['state']}, {report['network']['egress_attempts']} egress attempts · "
             f"{'valid' if report['valid'] else 'INVALID: ' + '; '.join(report.get('invalid_reasons', []))}", "",
             "| Suite | Version | Status | Passed | Rate (95% interval) |",
             "| --- | --- | --- | --- | --- |"]  # fmt: skip
    for name, suite in report["suites"].items():
        r = suite["result"]
        rate = "-" if r["rate"] is None else f"{r['rate']:.1%} ({r['interval'][0]:.1%} to {r['interval'][1]:.1%})"
        label = (
            "perception (fixture assertions)" if name == "perception" and suite.get("split") == "regression" else name
        )
        lines.append(f"| {label} | {suite['version']} | {suite['status']} | {r['passed']}/{r['total']} | {rate} |")
    perception = report["suites"].get("perception", {})
    if perception.get("status") == "ran" and perception.get("split") == "regression":
        exact = perception.get("criteria", {}).get("exact_transcription", result(0, 0))
        lines += [
            "",
            f"Printed exact transcription: {exact['passed']}/{exact['total']} fixture photos.",
            "Rendered development fixtures are not ordinary-camera EVL-12 or reference-device acceptance evidence.",
        ]
    failed = [c for c in report["cases"] if c["status"] == "failed"]
    if failed:
        lines += ["", "Failed cases:", *[f"- {c['suite']}/{c['case_id']}: {c.get('reason', '')}" for c in failed]]
    return "\n".join(lines) + "\n"
