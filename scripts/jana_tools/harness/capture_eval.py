"""M21 development regression over owned worksheets and the complete production capture path.

Rates here describe assertions on rendered fixtures, not the EVL-12 ordinary-camera/photo accuracy gate.
The stacked-formula challenge stays a failure if the installed OCR fallback cannot transcribe it.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PIL import Image

from ..perception_fixtures import ROOT
from .capture_pipeline import CapturePipeline
from .perception import read_correctly
from .report import result


def corpus_errors(folder: Path = ROOT) -> list[str]:
    manifest = folder / "set.json"
    if not manifest.is_file() or manifest.stat().st_size > 1_000_000:
        return ["capture regression manifest is missing or oversized"]
    try:
        data = json.loads(manifest.read_text())
    except (ValueError, OSError):
        return ["capture regression manifest is unreadable"]
    if (
        not isinstance(data, dict)
        or data.get("format") != "jana.capture-regression.1"
        or data.get("release_evidence") is not False
    ):
        return ["capture regression must be explicitly labelled as development-only"]
    items = data.get("items")
    if not isinstance(items, list) or not 1 <= len(items) <= 1000:
        return ["capture regression needs between 1 and 1000 labelled fixtures"]
    errors, ids = [], set()
    for item in items:
        if not isinstance(item, dict):
            errors.append("fixture must be an object")
            continue
        name, ident = item.get("photo"), item.get("id")
        if not isinstance(ident, str) or not re.fullmatch(r"[a-z0-9-]{1,80}", ident) or ident in ids:
            errors.append("fixture ids must be unique slugs")
        ids.add(str(ident))
        if (item.get("source"), item.get("licence"), item.get("acquisition"), item.get("split")) != (
            "synthetic",
            "LicenseRef-Own",
            "rendered",
            "regression",
        ):
            errors.append(f"{ident}: unreviewed fixture provenance")
        if not isinstance(item.get("expected"), dict) or not item["expected"]:
            errors.append(f"{ident}: missing independent labels")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9-]+\.(png|jpg)", name):
            errors.append(f"{ident}: photo must be a local fixture basename")
            continue
        path = folder / name
        if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= 20 * 1024 * 1024:
            errors.append(f"{ident}: missing, linked or oversized photo")
            continue
        if hashlib.sha256(path.read_bytes()).hexdigest() != item.get("sha256"):
            errors.append(f"{ident}: fixture bytes changed")
    return errors


def _patch_masked(data: bytes, box: list[float]) -> bool:
    with Image.open(io.BytesIO(data)) as opened:
        image = opened.convert("RGB")
        left, top, right, bottom = box
        crop = image.crop((left * image.width, top * image.height, right * image.width, bottom * image.height))
        pixels = list(crop.getdata())
        return bool(pixels) and sum(min(pixel) >= 245 for pixel in pixels) / len(pixels) >= 0.98


async def evaluate(
    folder: Path = ROOT,
    router: Any = None,
    hardware_class: str = "mid",
    *,
    only: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    completed: Callable[[list[dict[str, Any]], dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    errors = corpus_errors(folder)
    if errors:
        return [
            {
                "suite": "perception",
                "case_id": "corpus::integrity",
                "status": "failed",
                "critical": True,
                "trace_ids": ["manifest:set.json"],
                "reason": "; ".join(errors)[:300],
            }
        ]
    items = json.loads((folder / "set.json").read_text())["items"]
    if only is not None:
        if not only or only - {item["id"] for item in items}:
            raise ValueError("select existing capture fixture ids")
        items = [item for item in items if item["id"] in only]
    cases = []
    async with CapturePipeline(hardware_class, router) as pipeline:
        for item in items:
            if progress is not None:
                progress(item["id"])
            expected = item["expected"]
            data = (folder / item["photo"]).read_bytes()
            # Recheck immediately before processing, too: never decode a changed or redirected fixture.
            if (folder / item["photo"]).is_symlink() or hashlib.sha256(data).hexdigest() != item["sha256"]:
                raise ValueError("capture fixture changed during the evaluation")
            try:
                observed = await pipeline.capture(
                    data,
                    purpose=expected.get("purpose", "question"),
                    override_quality=True,
                    rotation=expected.get("rotation", 0),
                    confirmed_text=expected.get("edited"),
                    selected_question=expected.get("selected_question"),
                )
            except Exception as error:
                observed = {"error": type(error).__name__}
            record = observed.get("record", {})
            text = record.get("text", "")
            traces = [f"fixture:{item['sha256']}"]
            if observed.get("capture_id"):
                traces.append(observed["capture_id"])

            def check(
                criterion: str,
                passed: bool,
                critical: bool = False,
                reason: str = "",
                *,
                fixture_id: str = item["id"],
                case_traces: list[str] = traces,
                capture_status: str = str(record.get("status", observed.get("error"))),
                reader_path: str = record.get("reader", {}).get("path", "none"),
            ) -> None:
                case = {
                    "suite": "perception",
                    "case_id": f"{fixture_id}::{criterion}",
                    "status": "passed" if passed else "failed",
                    "critical": critical,
                    "trace_ids": case_traces,
                    "reader_path": reader_path,
                }
                if not passed:
                    case["reason"] = (reason or f"capture status {capture_status}")[:300]
                cases.append(case)

            check("confirmation_gate", observed.get("unconfirmed_refused") is True, True)
            check(
                "app_event_contract",
                observed.get("app_event_errors") == [] and observed.get("app_progress_events", 0) >= 2,
                True,
            )
            check(
                "confidence_flags",
                all(not r.get("low_confidence_spans") or r["needs_confirmation"] for r in record.get("regions", [])),
                True,
            )
            check("local_only", record.get("egress", {}).get("left_device") is False, True)
            derivatives = observed.get("derivatives", [])
            bounded = True
            for derivative in derivatives:
                with Image.open(io.BytesIO(derivative)) as image:
                    bounded &= max(image.size) <= 1600 and not image.getexif() and len(derivative) <= 2_000_000
                bounded &= hashlib.sha256(derivative).hexdigest() != item["sha256"]
            check("derivative_bounds", bounded and bool(record), True)
            if "exact" in expected:
                check(
                    "exact_transcription",
                    record.get("status") == "awaiting_confirmation" and read_correctly(text, expected["exact"]),
                    reason=f"Transcription differs: {text[:200]!r}",
                )
            if "contains" in expected:
                check("given_values", all(value in text for value in expected["contains"]))
            if "private_absent" in expected:
                check(
                    "privacy_text", all(value not in json.dumps(record) for value in expected["private_absent"]), True
                )
            if "masked_patch" in expected:
                check(
                    "privacy_pixels",
                    bool(derivatives) and _patch_masked(derivatives[0], expected["masked_patch"]),
                    True,
                )
            if "blocking" in expected:
                check(
                    "quality_blocking",
                    record.get("status") == "quality_failed"
                    and any(
                        c["check"] == expected["blocking"] and c["outcome"] == "blocking"
                        for c in record.get("quality", {}).get("checks", [])
                    )
                    and observed.get("read_error") == "capture_not_ready",
                    True,
                )
            if "questions" in expected:
                check("question_groups", [q["label"] for q in record.get("questions", [])] == expected["questions"])
            if "edited" in expected:
                check("confirmed_edits", observed.get("turn_text") == expected["edited"], True)
            if expected.get("injection_removed"):
                check(
                    "injection_inert",
                    record.get("injection", {}).get("flagged") is True
                    and "[instruction-like text removed]" in text
                    and "Ignore all previous" not in text,
                    True,
                )
            if expected.get("upright"):
                check(
                    "orientation",
                    bool(derivatives) and record["attachments"][0]["width"] > record["attachments"][0]["height"],
                )
            if completed is not None:
                completed(
                    cases,
                    {
                        "fixture_id": item["id"],
                        "capture_id": observed.get("capture_id"),
                        "status": record.get("status", observed.get("error")),
                        "reader": record.get("reader", {}),
                        "preprocess_ms": observed.get("preprocess_ms"),
                        "reader_ms": observed.get("reader_ms"),
                        "total_ms": observed.get("total_ms"),
                    },
                )
    return cases


def suite_cases() -> list[dict[str, Any]]:
    return asyncio.run(evaluate())


def measures(cases: list[dict[str, Any]]) -> dict[str, Any]:
    criteria = sorted({case["case_id"].rsplit("::", 1)[-1] for case in cases})
    return {
        criterion: result(sum(case["status"] == "passed" for case in selected), len(selected))
        for criterion in criteria
        if (selected := [case for case in cases if case["case_id"].endswith(f"::{criterion}")])
    }


def run_model(
    server: Path,
    gguf: Path,
    projector: Path,
    model_id: str,
    hardware_class: str,
    *,
    only: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
    checkpoint: Path | None = None,
) -> dict[str, Any]:
    """Development evidence from an installed model/projector; never an ordinary-camera acceptance report."""
    from agent_core.config import Settings
    from agent_core.providers.gguf import read_header
    from agent_core.providers.llama import LlamaServerProvider

    from . import report as rep
    from .egress import offline_run
    from .lock import LOCK, lock_errors
    from .memfit import serving
    from .perception import model_router
    from .run import run

    if hardware_class not in ("low", "mid", "high"):
        raise ValueError("hardware class must be low, mid or high")
    errors = corpus_errors() + lock_errors()
    if errors:
        raise ValueError("invalid capture regression: " + "; ".join(errors[:5]))
    # A report for the selected suite only; no native run or model call is hidden in its base metadata.
    report = run(build_stage="S2", only=set())
    settings = Settings()
    context = {"low": settings.context_cap_low, "mid": settings.context_cap_mid, "high": settings.context_cap_high}[
        hardware_class
    ]
    # Optional model-header metadata must not destroy completed inference. Hybrid attention headers may contain
    # lists which the older memory-estimate reader cannot summarize yet; leave quantisation explicitly unknown.
    try:
        quantisation = f"gguf-type-{read_header(gguf).file_type}"
    except (TypeError, ValueError):
        quantisation = "unknown"
    report["models"] = [
        {"id": model_id, "quantisation": quantisation, "tier": "vision"},
        {"id": "tesseract-eng", "quantisation": "native", "tier": "ocr"},
    ]
    report["hardware"]["hardware_class"] = hardware_class
    version = json.loads(LOCK.read_text())["suites"]["perception"]
    base_valid, base_reasons = report["valid"], list(report.get("invalid_reasons", []))

    def assign(cases: list[dict[str, Any]]) -> None:
        criteria = measures(cases)
        critical = [case for case in cases if case["critical"]]
        criteria["critical"] = rep.result(sum(case["status"] == "passed" for case in critical), len(critical))
        report["suites"]["perception"] = {
            "version": version["version"],
            "lock_sha256": rep.lock_sha256(version),
            "split": "regression",
            "status": "ran",
            "result": rep.result(sum(c["status"] == "passed" for c in cases), len(cases)),
            "criteria": criteria,
        }
        report["cases"] = list(cases)

    def completed(cases: list[dict[str, Any]], observation: dict[str, Any]) -> None:
        if checkpoint is None:
            return
        assign(cases)
        report["valid"] = False
        report["invalid_reasons"] = [*base_reasons, "incomplete capture evaluation checkpoint"]
        checkpoint.parent.mkdir(parents=True, exist_ok=True)
        temporary = checkpoint.with_suffix(".tmp")
        temporary.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
        temporary.replace(checkpoint)
        with checkpoint.with_suffix(".observations.jsonl").open("a") as stream:
            stream.write(json.dumps(observation, sort_keys=True) + "\n")

    with offline_run() as network, serving(server, gguf, context, projector, alias=model_id) as served:

        async def go() -> list[dict[str, Any]]:
            provider = LlamaServerProvider(served.url, served.key)
            try:
                return await evaluate(
                    router=model_router(provider, model_id, hardware_class),
                    hardware_class=hardware_class,
                    only=only,
                    progress=progress,
                    completed=completed,
                )
            finally:
                await provider.close()

        cases = asyncio.run(go())
    assign(cases)
    report["valid"] = base_valid
    if base_reasons:
        report["invalid_reasons"] = base_reasons
    else:
        report.pop("invalid_reasons", None)
    report["network"]["egress_attempts"] = len(network.attempts)
    if network.attempts:
        report["valid"] = False
        report["invalid_reasons"] = [
            f"egress attempt during offline capture evaluation: {attempt}" for attempt in network.attempts
        ]
    return report
