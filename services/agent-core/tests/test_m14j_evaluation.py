"""M14.j: simulated students, the pedagogy rubric with two calibrated judges, and trajectory export and replay
(EVL-04, EVL-05, EVL-06, OBS-10).

The simulated-student gates read the newest committed live run (`evals/live-runs/*-simulated/report.json`); the judge
and replay mechanics are tested here with deterministic judges and scripted model replies. Every excerpt, label and
line is synthetic."""

from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from engine_harness import STATEMENT, checker_steps, close, solver_steps, tutor
from jana_tools import REPO_ROOT
from m14_harness import engine_for

LOOP = asyncio.new_event_loop()
RUBRIC = REPO_ROOT / "evals" / "rubrics" / "pedagogy.guided.v1.yaml"
LIVE = REPO_ROOT / "evals" / "live-runs"
JUDGES = ("local:qwen3-vl-8b@Q4_K_M", "cloud:gemini-2.5-pro")


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _latest_simulated() -> dict[str, Any] | None:
    reports = sorted(LIVE.glob("*-simulated/report.json"))
    return json.loads(reports[-1].read_text()) if reports else None


# --- EVL-04 -----------------------------------------------------------------------------------------------------------


def evl04_zero_detected_leaks() -> None:
    from jana_tools.harness.simulator import broke_character, load_personas

    config = load_personas()
    assert set(config["personas"]) == {"answer_seeker", "misconception_holder", "silent", "rapid_guesser", "off_topic",
                                       "anxious", "notation_mixer", "injector"}  # fmt: skip
    pinned = config["simulator"]
    assert pinned["seeds"] and pinned["model"] and "temperature" in pinned, "the simulator is pinned in the suite"
    from jana_tools.harness import lock

    assert "evals/personas/*.yaml" in lock.suites()["simulated_students"].files, "persona prompts are locked"
    assert broke_character("As an AI language model I cannot", "silent", [])
    assert broke_character("C", "misconception_holder", ["D"]) and not broke_character("D", "misconception_holder",
                                                                                         ["D"])  # fmt: skip
    report = _latest_simulated()
    if report is None:
        pytest.skip("no simulated-student run is committed yet (eval simulate on a local model)")
    assert report["scored"] > 0
    assert report["detected_leaks"] == 0, [r for r in report["rows"] if r["leaks"]][:3]
    gate = report["withheld_until_earned"]
    assert gate["passed"] / gate["total"] >= Settings().eval_simulated_withholding_rate


def evl04_misconception_named_rate() -> None:
    from jana_tools.harness.simulator import named

    misconception = yaml.safe_load((REPO_ROOT / "content/curriculum/phy/o/misconceptions/"
                                    "mc.phy.o.time_over_distance.yaml").read_text())  # fmt: skip
    assert named("Speed is how many metres you cover each second, so which goes on top, the metres or the seconds?",
                 misconception)  # fmt: skip
    assert not named("Let's look at the question again. What do you notice?", misconception)
    report = _latest_simulated()
    if report is None:
        pytest.skip("no simulated-student run is committed yet (eval simulate on a local model)")
    rate = report["misconception_named"]
    assert rate["total"] > 0
    assert rate["passed"] / rate["total"] >= Settings().eval_misconception_named_rate, rate


# --- EVL-05, EVL-06 ---------------------------------------------------------------------------------------------------


def _passing_calibration(tmp_path: Path, rubric: Any) -> Path:
    """Calibration records for both pinned judges from a synthetic teacher-labelled set the judges agree with."""
    from jana_tools.harness.rubric import calibrate

    folder = tmp_path / "calibration"
    labelled = [{"excerpt_id": f"ex{n:03d}", "excerpt": f"Tutor: what would you try first? ({n})",
                 "criterion": c["id"], "labels": ["pass", "pass", "fail"]}
                for n in range(Settings().eval_judge_calibration_excerpts) for c in rubric.criteria]  # fmt: skip
    for ref in JUDGES:
        record = calibrate(rubric, ref, lambda _c, _e: "pass", labelled, quantisation="Q4_K_M", folder=folder)
        assert record["passed"] and record["agreement"]["asks_for_attempt_first"] == 1.0
    return folder


def evl05_rubric_gate(tmp_path: Path) -> None:
    from jana_tools.harness.rubric import gate_errors, grade, load_rubric

    rubric = load_rubric(RUBRIC)
    assert [c["id"] for c in rubric.criteria] == ["asks_for_attempt_first", "stays_kind_under_pressure",
                                                  "names_misconception", "asks_before_correcting",
                                                  "praises_method_not_person", "one_step_at_a_time",
                                                  "level_appropriate", "never_says_wrong"]  # fmt: skip
    assert rubric.data["scoring"]["criterion_pass_rate_gate"] == Settings().eval_rubric_criterion_gate
    folder = _passing_calibration(tmp_path, rubric)
    runs = [{"run_id": f"r{n}", "excerpt": f"Tutor: which quantity goes on top? ({n})"} for n in range(60)]

    def strict(criterion: dict[str, Any], excerpt: str) -> str:
        return "fail" if criterion["id"] == "level_appropriate" and excerpt.endswith("(3)") else "pass"

    def lenient(criterion: dict[str, Any], excerpt: str) -> str:
        return "pass"

    def broken(criterion: dict[str, Any], excerpt: str) -> str:
        raise TimeoutError

    report = grade(rubric, runs, {JUDGES[0]: strict, JUDGES[1]: lenient}, folder=folder)
    assert report["teacher_queue"] == [{"run_id": "r3", "criterion": "level_appropriate"}], "disagreement queued"
    assert report["per_criterion"]["level_appropriate"]["passed"] == 59, "unresolved counts as FAIL"
    assert report["judge_agreement"] < 1 and report["criterion_wilson_95"][0] < report["criterion_pass_rate"]
    assert gate_errors(report, rubric) == []
    erring = grade(rubric, runs[:50], {JUDGES[0]: broken, JUDGES[1]: lenient}, folder=folder)
    assert erring["criterion_pass_rate"] == 0 and gate_errors(erring, rubric), "a judge error is never a pass"
    critical = grade(rubric, runs, {JUDGES[0]: lambda c, e: "fail" if c["id"] == "names_misconception" else "pass",
                                    JUDGES[1]: lambda c, e: "fail" if c["id"] == "names_misconception" else "pass"},
                     folder=folder)  # fmt: skip
    assert critical["criterion_pass_rate"] > 0.85 and any("critical" in e for e in gate_errors(critical, rubric))
    releases = sorted((REPO_ROOT / "evals" / "rubrics" / "reports").glob("*.json"))
    if not releases:
        pytest.skip("no release sample is graded yet: the judges need teacher calibration labels, and the cloud "
                    "judge the owner's Gemini key")  # fmt: skip
    assert gate_errors(json.loads(releases[-1].read_text()), rubric) == []


def evl05_rubric_frozen(tmp_path: Path) -> None:
    from jana_tools.harness import lock

    root = tmp_path / "repo"
    (root / "evals" / "rubrics").mkdir(parents=True)
    shutil.copy(RUBRIC, root / "evals" / "rubrics" / RUBRIC.name)
    registry = tmp_path / "suites.toml"
    registry.write_text('[suites.pedagogy_rubric]\nowner = "Learning designer"\ncadence = "nightly"\nstage = "S2"\n'
                        'version = "2026-10-13.1"\nfiles = ["evals/rubrics/*.yaml"]\n')  # fmt: skip
    locked = tmp_path / "lock.json"
    lock.write_lock(registry, locked, root)
    assert lock.lock_errors(registry, locked, root) == []
    edited = root / "evals" / "rubrics" / RUBRIC.name
    edited.write_text(
        edited.read_text().replace(
            "PASS if the reply moves the work on by at most one step.",
            "PASS if the reply moves the work on by one or two steps.",
        )
    )
    errors = lock.lock_errors(registry, locked, root)
    assert errors and "changed without a version bump" in errors[0]
    # The repository's own lock covers the rubric, and the grading record carries the rubric's hash.
    suites = lock.suites()
    assert "evals/rubrics/*.yaml" in suites["pedagogy_rubric"].files
    assert lock.lock_errors() == [] or all("pedagogy_rubric" not in e for e in lock.lock_errors())


def evl06_uncalibrated_judge_refused(tmp_path: Path) -> None:
    from jana_tools.harness.rubric import UncalibratedJudge, calibrate, grade, load_rubric

    rubric = load_rubric(RUBRIC)
    runs = [{"run_id": "r1", "excerpt": "Tutor: what would you try first?"}]
    judges = {ref: (lambda c, e: "pass") for ref in JUDGES}
    with pytest.raises(UncalibratedJudge, match="no calibration record"):
        grade(rubric, runs, judges, folder=tmp_path / "none")
    folder = _passing_calibration(tmp_path, rubric)
    assert grade(rubric, runs, judges, folder=folder)["runs"] == 1
    # A judge below the agreement bar on a critical criterion is refused.
    labelled = [
        {
            "excerpt_id": f"ex{n:03d}",
            "excerpt": "x",
            "criterion": "asks_for_attempt_first",
            "labels": ["fail", "fail", "pass"],
        }
        for n in range(Settings().eval_judge_calibration_excerpts)
    ]
    weak = calibrate(rubric, JUDGES[0], lambda c, e: "pass", labelled, quantisation="Q4_K_M", folder=folder)
    assert not weak["passed"]
    with pytest.raises(UncalibratedJudge, match="did not pass calibration"):
        grade(rubric, runs, judges, folder=folder)
    folder = _passing_calibration(tmp_path / "again", rubric)
    # A record for another rubric version, or another judge prompt, does not count.
    newer = tmp_path / "pedagogy.guided.v1.yaml"
    newer.write_text(RUBRIC.read_text().replace("version: 1.0.0", "version: 1.1.0"))
    with pytest.raises(UncalibratedJudge, match="another version"):
        grade(load_rubric(newer), runs, judges, folder=folder)
    prompt = tmp_path / "judge-prompt.md"
    prompt.write_text((REPO_ROOT / "evals" / "rubrics" / "judge-prompt.md").read_text() + "Be strict.\n")
    with pytest.raises(UncalibratedJudge, match="judge prompt changed"):
        grade(rubric, runs, judges, folder=folder, prompt=prompt)
    # The model under test never judges its own outputs.
    with pytest.raises(UncalibratedJudge, match="model under test"):
        grade(rubric, runs, judges, folder=folder, under_test=["qwen3-vl-8b"])
    assert "gemma-4-12b" in rubric.data["judging"]["excluded_from_judge_pool"]


# --- OBS-10 -----------------------------------------------------------------------------------------------------------


def obs10_replay_reproduces_trace(tmp_path: Path) -> None:
    from jana_tools.harness.trajectory import (
        ExportRefused,
        Recording,
        capture_inputs,
        compare,
        export,
        load,
        replay,
        signature,
    )

    leak = tutor("The ball rises 10 m.")  # the failure: the first reply gives the answer away, the gate fires
    script = {"solver": solver_steps(), "checker": checker_steps(),
              "coach": [tutor("What do you know at the top?"), leak, tutor("Which equation links u, v, a and s?"),
                        tutor("Good. Now put the numbers in.")]}  # fmt: skip
    engine, provider = run(engine_for(tmp_path, script))
    recording = Recording()
    recording.attach(provider)
    inputs = capture_inputs(engine)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("v = 0 at the top"))
    run(engine.student_turn("v^2 = u^2 + 2as"))
    run(close(engine))
    fired = [g for t in engine.traces for g in t["gates"] if g["gate"] == "no_answer_leak" and g["fired"]]
    assert fired, "the recorded session is a failing one: the leak gate fired"
    header = {"subject": "physics", "level": "O", "mode": "guided", "hardware_class": "mid",
              "session_date": "2026-10-09"}  # fmt: skip
    path = export(tmp_path / "trajectory.jsonl", header, inputs, recording, engine.traces)
    lines = [json.loads(line) for line in path.read_text().splitlines()]
    assert {line["type"] for line in lines} == {"session", "input", "model", "trace"}
    trajectory = load(path)
    replayed = run(replay(trajectory))
    assert compare(trajectory["traces"], replayed) == []
    assert [signature(t)["tools"] for t in replayed] == [signature(t)["tools"] for t in engine.traces]
    assert [signature(t)["gates"] for t in replayed] == [signature(t)["gates"] for t in engine.traces]
    # A release build exports payloads only inside a debug bundle the adult consented to.
    with pytest.raises(ExportRefused):
        export(tmp_path / "release.jsonl", header, inputs, recording, engine.traces, channel="release")
    bundle = export(tmp_path / "debug.jsonl", header, inputs, recording, engine.traces, channel="release",
                    debug_bundle_consent=True)  # fmt: skip
    assert json.loads(bundle.read_text().splitlines()[0])["debug_bundle"] is True
    hashes = export(tmp_path / "hashes.jsonl", header, inputs, recording, engine.traces, capture="hashes")
    assert {json.loads(line)["type"] for line in hashes.read_text().splitlines()} == {"session", "trace"}
