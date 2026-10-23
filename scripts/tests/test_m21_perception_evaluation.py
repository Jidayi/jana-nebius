"""M21's evaluation boundary: real capture integration, independent fixtures, honest scores and release provenance."""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from agent_core.engine.vision import reader_output
from agent_core.router.structured import decode_schema
from jana_tools.harness import capture_eval, perception
from jana_tools.harness.capture_pipeline import CapturePipeline
from jana_tools.harness.gate import gate_errors
from jana_tools.harness.report import errors as report_errors
from jana_tools.harness.run import run
from jana_tools.perception_fixtures import ROOT, build
from jsonschema import Draft202012Validator


def test_decoder_preserves_inline_definitions_and_nested_table_types() -> None:
    schema = {
        "type": "object",
        "$defs": {"value": {"type": "string"}},
        "properties": {"value": {"$ref": "#/$defs/value"}},
    }
    assert decode_schema(schema)["properties"]["value"] == {"type": "string"}
    decoded = decode_schema(reader_output()[1])
    Draft202012Validator.check_schema(decoded)
    properties = decoded["properties"]["regions"]["items"]["properties"]
    assert properties["table"]["anyOf"][1]["properties"]["rows"]["items"]["items"]["type"] == "string"
    assert "image_id" not in properties["bbox"]["anyOf"][1]["properties"]


def test_local_definitions_keep_caller_changes_instead_of_reloading_the_canonical_document() -> None:
    schema = {
        "$id": "https://jana.dev/contracts/input/captured-question",
        "$defs": {"region_id": {"const": "local"}},
        "type": "object",
        "properties": {"region": {"$ref": "#/$defs/region_id"}},
    }
    assert decode_schema(schema)["properties"]["region"] == {"const": "local"}
    external = decode_schema(
        {
            "type": "object",
            "properties": {"region": {"$ref": "https://jana.dev/contracts/input/captured-question#/$defs/region"}},
        }
    )
    assert external["properties"]["region"]["properties"]["region_id"]["type"] == "string"


def test_regression_images_and_labels_are_hash_locked_and_reproducible() -> None:
    assert capture_eval.corpus_errors() == []
    generated = build()
    for name, data in generated.items():
        assert hashlib.sha256((ROOT / name).read_bytes()).digest() == hashlib.sha256(data).digest(), name
    manifest = json.loads(generated["set.json"])
    assert not manifest["release_evidence"] and len(manifest["items"]) == 29
    assert {item["expected"].get("blocking") for item in manifest["items"]} >= {
        "darkness",
        "blur",
        "resolution",
        "no_text",
    }


def test_manifest_tampering_or_an_external_photo_fails_before_native_execution(tmp_path: Path) -> None:
    shutil.copytree(ROOT, tmp_path / "fixtures")
    folder = tmp_path / "fixtures"
    image = folder / "linear-plain.png"
    image.write_bytes(image.read_bytes() + b"changed")
    assert any("changed" in error for error in capture_eval.corpus_errors(folder))
    manifest = json.loads((folder / "set.json").read_text())
    manifest["items"][0]["photo"] = "../external.png"
    (folder / "set.json").write_text(json.dumps(manifest))
    assert any("basename" in error for error in capture_eval.corpus_errors(folder))


def _lab_record() -> dict[str, Any]:
    items = [{"photo": f"ordinary-{n}.jpg", "correct": True} for n in range(200)]
    return {
        "name": "synthetic unit evidence",
        "hardware_class": "high",
        "perception": {
            "hardware_class": "high",
            "evidence_kind": "ordinary_camera",
            "pipeline": "capture-v1",
            "set_sha256": "a" * 64,
            "printed": perception.score(items),
            "items": items,
        },
    }


@pytest.mark.parametrize(
    "field,value",
    [("evidence_kind", "rendered"), ("pipeline", "vision-only"), ("set_sha256", None), ("hardware_class", "low")],
)
def test_release_photo_gate_refuses_smoke_only_or_misattributed_evidence(field: str, value: Any) -> None:
    record = _lab_record()
    assert perception.gate_errors(record) == []
    record["perception"][field] = value
    assert perception.gate_errors(record)


def test_release_photo_gate_recomputes_scores_and_rejects_duplicate_or_missing_outcomes() -> None:
    record = _lab_record()
    record["perception"]["items"][0]["correct"] = False
    assert any("disagrees" in error for error in perception.gate_errors(record))
    record = _lab_record()
    record["perception"]["items"] = [record["perception"]["items"][0]] * 200
    assert any("duplicate" in error for error in perception.gate_errors(record))
    assert perception.gate_errors({"name": "missing", "perception": {"printed": {"rate": None}}})


def test_comparison_never_erases_currency_or_equates_chemical_symbols_with_digits() -> None:
    assert not perception.read_correctly("Dr Cash 100", "Dr Cash $100")
    assert not perception.read_correctly("H20", "H2O")
    assert perception.read_correctly(r"\(v^{2}=u^2+2as\)", "v^2 = u^2 + 2as")


def test_lab_rejects_rendered_set_before_starting_a_runtime(monkeypatch: pytest.MonkeyPatch) -> None:
    from jana_tools.harness import memfit

    def forbidden(*_: Any, **__: Any) -> Any:
        pytest.fail("a runtime must not start for an invalid acceptance set")

    monkeypatch.setattr(memfit, "serving", forbidden)
    items = json.loads((ROOT / "set.json").read_text())["items"]
    with pytest.raises(ValueError, match="invalid EVL-12"):
        perception.run_local(Path("unused"), Path("unused"), Path("unused"), "model", items, ROOT, "high")


def test_native_capture_publishes_valid_app_progress_and_keeps_the_confirmation_gate() -> None:
    async def check() -> None:
        async with CapturePipeline() as pipeline:
            observed = await pipeline.capture(
                (ROOT / "linear-plain.png").read_bytes(), override_quality=True, confirmed_text="Find x if 2x+5=17."
            )
            if observed.get("error") == "photo_reading_unavailable":
                pytest.skip("native perception sandbox/runtime unavailable on this platform")
            assert observed["app_event_errors"] == [] and observed["app_progress_events"] >= 4
            assert observed["unconfirmed_refused"]
            if observed["record"]["status"] == "refused":
                pytest.skip("reviewed English OCR asset is not installed")
            assert observed["turn_text"] == "Find x if 2x+5=17."
            assert observed["confirmed"]["confirmation"]["method"] == "edited"
            assert pipeline.desk.raw == {} and pipeline.desk.prepared == {}

    asyncio.run(check())


def test_perception_suite_reports_real_failures_with_separate_accuracy_metrics(monkeypatch: pytest.MonkeyPatch) -> None:
    cases = [
        {
            "suite": "perception",
            "case_id": "synthetic::exact_transcription",
            "status": "failed",
            "critical": False,
            "trace_ids": ["fixture:synthetic"],
            "reader_path": "ocr_pipeline",
        },
        {
            "suite": "perception",
            "case_id": "synthetic::confirmation_gate",
            "status": "passed",
            "critical": True,
            "trace_ids": ["fixture:synthetic"],
            "reader_path": "ocr_pipeline",
        },
    ]
    monkeypatch.setattr(capture_eval, "suite_cases", lambda: copy.deepcopy(cases))
    report = run(build_stage="S2", only={"perception"})
    assert report_errors(report) == [] and gate_errors(report) == []
    suite = report["suites"]["perception"]
    assert suite["status"] == "ran" and suite["result"]["total"] == 2
    assert suite["criteria"]["exact_transcription"]["passed"] == 0
    assert report["cases"][0]["status"] == "failed"


def test_s2_release_cannot_promote_rendered_regressions_to_camera_acceptance() -> None:
    from jana_tools.harness.gate import release_errors
    from jana_tools.harness.report import result

    report = run(only=set())
    report["mode"] = "release"
    report["build"]["stage"] = "S2"
    report["suites"]["safety"].update(status="ran", criteria={"held_out": result(3, 3)})
    report["cases"] = [
        {
            "suite": "safety",
            "case_id": "held_out",
            "status": "passed",
            "critical": True,
            "trace_ids": [],
            "hardware_class": hardware,
        }
        for hardware in ("low", "mid", "high")
    ]
    perception_row = report["suites"]["perception"]
    perception_row.update(
        status="ran",
        split="regression",
        criteria={f"camera:{hardware}": result(200, 200) for hardware in ("low", "mid", "high")},
    )
    assert any("development only" in error for error in release_errors(report))
    # Unit evidence only: the gate accepts the aggregate shape for genuine held-out camera results on all classes.
    perception_row["split"] = "held_out"
    assert release_errors(report) == []
    del perception_row["criteria"]["camera:low"]
    assert any("low class" in error for error in release_errors(report))


@pytest.mark.parametrize("interrupted", [False, True])
def test_hybrid_metadata_does_not_lose_inference_and_partial_reports_cannot_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupted: bool
) -> None:
    from contextlib import contextmanager

    from agent_core.providers import gguf
    from jana_tools.harness import memfit

    @contextmanager
    def local_server(*_: Any, **__: Any) -> Any:
        yield memfit.Served("http://127.0.0.1:1", "synthetic-unit-key", 0)

    def hybrid_header(*_: Any) -> Any:
        raise TypeError("hybrid attention heads are a list")

    async def inference(**kwargs: Any) -> list[dict[str, Any]]:
        cases = [
            {
                "suite": "perception",
                "case_id": "linear-plain::exact_transcription",
                "status": "passed",
                "critical": False,
                "trace_ids": ["fixture:synthetic"],
                "reader_path": "vision_model",
            }
        ]
        kwargs["completed"](cases, {"fixture_id": "linear-plain", "total_ms": 1})
        if interrupted:
            raise RuntimeError("synthetic interruption after a completed fixture")
        return cases

    monkeypatch.setattr(memfit, "serving", local_server)
    monkeypatch.setattr(gguf, "read_header", hybrid_header)
    monkeypatch.setattr(capture_eval, "evaluate", inference)
    checkpoint = tmp_path / "capture.json"
    if interrupted:
        with pytest.raises(RuntimeError, match="synthetic interruption"):
            capture_eval.run_model(
                Path("unused"), Path("unused"), Path("unused"), "synthetic-model", "high", checkpoint=checkpoint
            )
    else:
        report = capture_eval.run_model(
            Path("unused"), Path("unused"), Path("unused"), "synthetic-model", "high", checkpoint=checkpoint
        )
        assert report["models"][0]["quantisation"] == "unknown"
        assert report_errors(report) == [] and report["valid"]
    partial = json.loads(checkpoint.read_text())
    assert report_errors(partial) == [] and gate_errors(partial)
    assert partial["cases"][0]["case_id"] == "linear-plain::exact_transcription"
    assert "incomplete" in partial["invalid_reasons"][0]
    assert checkpoint.with_suffix(".observations.jsonl").is_file()
