"""M11: the acceptance tests that need the device lab's reference laptops (EVL-14) or the pilot device survey.

Each test first runs everything that can run on any machine (the measuring tool or the gate over synthetic records),
then reads the lab's measurement files (`JANA_DEVLAB_RESULTS`, one `<laptop>.json` each) or the pilot survey
(`JANA_DEVICE_SURVEY`, a CSV in the survey template's columns) and skips, saying what is missing, until they exist.
The measurement fields each laptop file adds for M11: `cpu_features`, `runtime_variant` and `runtime_crashes`
(PLT-04), `model` and `model_params_b` (PLT-29), `class_runs` (PLT-08; `lab classbench`), `memory_fit` (MDL-17;
`lab memfit`), `perception` (EVL-12; `lab perception`), `overhead` (OBS-24; `lab overhead`). Every record below that
is not read from those files is synthetic."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.router.probe import Probe
from jana_tools import REPO_ROOT
from jana_tools.harness import devlab, memfit, overhead, perception, survey

LAB = os.environ.get("JANA_DEVLAB_RESULTS")
SURVEY = os.environ.get("JANA_DEVICE_SURVEY")
SETTINGS = Settings()
PROBES = REPO_ROOT / "services" / "agent-core" / "tests" / "fixtures" / "probe"


def _laptops() -> list[dict[str, Any]]:
    if LAB is None:
        pytest.skip("needs the reference laptops' measurements (device lab: JANA_DEVLAB_RESULTS)")
    return [json.loads(p.read_text()) for p in sorted(Path(LAB).glob("*.json"))]


def _reference(hw: str) -> dict[str, Any]:
    found = [lap for lap in _laptops() if lap.get("hardware_class") == hw and lap.get("reference", True)]
    if not found:
        pytest.skip(f"the device lab has no {hw}-class reference laptop yet")
    return found[0]


# --- PLT-04: the selection and fallback run in the shell's own tests (apps/desktop/src-tauri/tests/runtime.rs) ----


def plt04_no_avx2_selects_baseline() -> None:
    """On a lab machine without AVX2: the baseline build ran, nothing crashed, and its guided steps were timed in full
    within the class's budget (the build choice itself: the shell's test of the same name)."""
    without = [lap for lap in _laptops() if "avx2" not in set(lap.get("cpu_features", ["avx2"]))]
    if not without:
        pytest.skip("the device lab has no laptop without AVX2 yet")
    for lap in without:
        assert lap.get("runtime_variant") == "cpu-baseline", lap["name"]
        assert lap.get("runtime_crashes", 0) == 0, f"{lap['name']}: the runtime crashed"
        assert [e for e in devlab.lab_errors(lap) if "step_s" in e] == []


# --- PLT-29 --------------------------------------------------------------------------------------------------------


def plt29_minimum_laptop_runs_8b_model() -> None:
    """On the low reference laptop, offline: the 8B-class model (7B or more, D58) loads within MDL-17's memory budget
    (the estimate within tolerance, peak memory the headroom below installed) and the guided step meets the low
    class's budget (AGT-28)."""
    low = _reference("low")
    assert low.get("network") == "disabled", "measured offline"
    assert 7 <= float(low.get("model_params_b", 0)) < 13, f"{low['name']}: {low.get('model')} is not 8B-class"
    assert memfit.errors(low) == []
    assert devlab.lab_errors(low) == []


def _fixture_probe(name: str) -> Probe:
    return Probe.from_json(json.loads((PROBES / f"{name}.json").read_text())["probe"])


def plt29_device_survey_reports_exclusion(tmp_path: Path) -> None:
    """The template records memory, CPU year and architecture, free disk and the class per machine, and the report
    states the share below the minimum laptop and what those machines lack. Then the M7 pilot survey itself."""
    with survey.TEMPLATE.open() as handle:
        header = handle.readline().strip().split(",")
    assert survey.errors([], header) == []
    for column in ("ram_gb", "cpu_year", "arch", "free_disk_gb", "hardware_class", "below_minimum"):
        assert column in header
    rows = [survey.row(_fixture_probe(n), f"synthetic-{n}", "2026-10-13") for n in ("low", "mid", "high",
                                                                                   "below_minimum")]  # fmt: skip
    assert survey.errors(rows) == []
    found = survey.report(rows)
    assert found["machines"] == 4 and found["below_minimum"]["passed"] == 1 and found["below_minimum"]["rate"] == 0.25
    assert found["lacking"] == {"ram": 1}
    assert found["classes"] == {"low": 1, "mid": 1, "high": 1, "content_only": 1}
    this = survey.append_this_machine(tmp_path / "survey.csv", "this-machine")
    assert survey.read(tmp_path / "survey.csv") == [this] and survey.errors([this]) == []
    if SURVEY is None:
        pytest.skip("the M7 pilot device survey has not been run yet (JANA_DEVICE_SURVEY)")
    pilot = survey.read(Path(SURVEY))
    with Path(SURVEY).open() as handle:
        assert survey.errors(pilot, handle.readline().strip().split(",")) == []
    stated = survey.report(pilot)
    assert stated["machines"] > 0 and stated["below_minimum"]["rate"] is not None


# --- MDL-17 --------------------------------------------------------------------------------------------------------


def _synthetic_record(off: float) -> dict[str, Any]:
    """A memory-fit record whose measured memory differs from the estimate by `off` (synthetic header and figures)."""
    from agent_core.providers.gguf import GgufInfo

    header = asdict(GgufInfo("qwen3", 40960, 36, 4096, 32, 8, 128, 128, 15, 5 * 1024**3))
    record = {"model": "synthetic", "header": header, "context": 6144, "projector_bytes": 0, "extras_bytes": 0}
    record["measured_bytes"] = int(memfit.estimate({**record, "measured_bytes": 1}) / (1 + off))
    return record


def mdl17_estimate_accuracy() -> None:
    """The check over records (synthetic here), then each reference laptop's measured records for every candidate."""
    tolerance = SETTINGS.memory_estimate_tolerance
    assert memfit.errors({"name": "synthetic", "memory_fit": [_synthetic_record(tolerance / 2)]}) == []
    assert memfit.errors({"name": "synthetic", "memory_fit": [_synthetic_record(tolerance * 2)]})
    assert memfit.errors({"name": "synthetic"}) == ["synthetic: no memory-fit measurements (python -m jana_tools lab "
                                                    "memfit)"]  # fmt: skip
    for hw in ("low", "mid", "high"):
        assert memfit.errors(_reference(hw)) == []


# --- EVL-12 --------------------------------------------------------------------------------------------------------


def evl12_photo_transcription_gate() -> None:
    """The comparison and the gate (synthetic results here), then the printed set and each class's lab results."""
    assert perception.read_correctly(r"\(v^{2} = u^2 + 2as\)", "v^2 = u^2 + 2as")
    assert perception.read_correctly(r"\dfrac{1}{2} \cdot m v^2", r"\frac{1}{2}\times mv^2")
    assert not perception.read_correctly("A stone falls 45 m.", "A stone falls 54 m.")
    assert not perception.read_correctly(None, "anything")
    size, gate = SETTINGS.evl12_printed_set_size, SETTINGS.evl12_printed_gate
    passing = int(size * gate) + 1
    items = [{"photo": f"synthetic-{n}.png", "correct": n < passing} for n in range(size)]
    good = {
        "name": "synthetic",
        "perception": {
            "printed": perception.score(items),
            "items": items,
            "evidence_kind": "ordinary_camera",
            "pipeline": "capture-v1",
            "set_sha256": "a" * 64,
            "hardware_class": "mid",
        },
    }
    assert perception.gate_errors(good) == []
    poor_items = [{"photo": f"synthetic-{n}.png", "correct": n < passing - 2} for n in range(size)]
    poor = {**good, "perception": {**good["perception"], "printed": perception.score(poor_items), "items": poor_items}}
    assert any("under the gate" in e for e in perception.gate_errors(poor))
    problems = perception.set_errors()
    if problems:
        pytest.skip(f"the printed photo set is not assembled yet: {problems[0]}")
    for hw in ("low", "mid", "high"):
        assert perception.gate_errors(_reference(hw)) == []


# --- OBS-24 --------------------------------------------------------------------------------------------------------


def obs24_overhead_within_budget() -> None:
    """The benchmark itself runs here (against the development script, which says nothing about the budget); the
    budget is judged on the low-class reference laptop's run against the real runtime."""
    record = overhead.measure(turns=3, warmup=1)
    assert record["on"]["turns"] == 3 and record["off"]["turns"] == 3
    assert record["on"]["median_turn_ms"] > 0 and record["off"]["peak_rss_bytes"] > 0
    assert overhead.gate_errors({"name": "here", "overhead": record})[0].endswith("without the real runtime")
    assert overhead.gate_errors({"name": "here", "overhead": {**record, "runtime": "real", "turn_share": 0.01,
                                                              "rss_mb": 5.0}}) == []  # fmt: skip
    assert overhead.gate_errors(_reference("low")) == []
