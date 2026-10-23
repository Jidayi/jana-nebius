"""JRN-02: the journeys are executable test scripts. The S2 journey suite is complete (a script per journey whose
steps and failure branches are the specification's, a runner case per journey and branch, its acceptance tests
defined), the journey core is built the way the app builds it, and the runner refuses a journey played out of order,
a device-lab step played on the harness, or any egress."""

from __future__ import annotations

import asyncio
import importlib
import re
import socket
from pathlib import Path

import pytest
from jana_tools import REPO_ROOT
from jana_tools.coverage import acceptance_tests, defined_tests
from jana_tools.journeys import runner
from jana_tools.journeys.scripts import executable, script, script_errors, scripts

# The journey test modules, each exporting CASES: {(journey, part): probe factory}.
MODULES = (
    "test_m25a_first_run_and_lab",
    "test_m25a_snap_and_working",
    "test_m25a_practice_and_plan",
    "test_m25a_exam_and_answers",
    "test_m25a_safety",
)
# Journeys whose end-to-end suite is another milestone's: the studio's (M22.a) runs in its own client suite.
ELSEWHERE = {"JRN-16": "M22.a, the studio's own end-to-end suite"}


def registered_cases() -> dict[tuple[str, str], object]:
    found: dict[tuple[str, str], object] = {}
    for name in MODULES:
        module = importlib.import_module(name)
        for key, factory in getattr(module, "CASES", {}).items():
            assert key not in found, f"{key} is bound twice"
            found[key] = factory
    return found


def jrn02_journey_suite_complete() -> None:
    """Every active journey of S2 and earlier has a script matching the specification and an end-to-end case per
    journey and failure branch (named e2e_jrnNN_*), and the coverage report finds its acceptance tests."""
    assert script_errors("S2") == [], script_errors("S2")
    defined = defined_tests()
    cases = registered_cases()
    pending = []
    for journey in executable("S2"):
        s = script(journey)
        tests = acceptance_tests(journey)
        missing = [t for t in tests if t not in defined]
        if journey in ELSEWHERE:
            if missing:
                pending.append(f"{journey} ({ELSEWHERE[journey]}): {missing}")
            continue
        assert not missing, f"{journey}: acceptance tests not defined: {missing}"
        for part in ("main", *(b.id for b in s.branches)):
            assert (journey, part) in cases, f"{journey} {part}: no runner case"
            assert re.fullmatch(r"e2e_jrn\d{2}_(main|f\d+)", runner.case_id(journey, part))
    unknown = [k for k in cases if k[0] not in executable("S2")]
    assert not unknown, f"cases for journeys outside S2: {unknown}"
    if pending:
        pytest.skip("every M25 journey is complete; still pending elsewhere: " + "; ".join(pending))


def test_journey_core_wires_what_the_app_wires() -> None:
    """The journey core adds to `start_core` exactly what the app's start wires on the core and `start_core` does
    not, so no journey runs on a core the app would not build."""
    import journey_harness

    app = (REPO_ROOT / "services/agent-core/agent_core/api/__main__.py").read_text()
    harness = (REPO_ROOT / "services/agent-core/tests/api_harness.py").read_text()
    # A tuple assignment (`core.online, core.release = ...`) starts its statement; a read inside a call does not.
    wired = set(re.findall(r"\bcore\.([a-z_]+) = ", app)) | set(re.findall(r"^\s*core\.([a-z_]+), core\.", app, re.M))
    base = set(re.findall(r"\bcore\.([a-z_]+) = ", harness))
    # Device services a journey core does not start (the shell's downloads and update installer, crash capture,
    # the background Reflector, correction re-marking, readiness reported to the shell); journeys that need one
    # attach it themselves.
    shell_side = {"pack_desk", "update_desk", "crashes", "reflector", "corrections_due", "readiness"}
    assert wired - base - shell_side == set(journey_harness.WIRED)


def _probe_steps(*plays: tuple[str, int]):
    async def probe(run: runner.Run) -> None:
        for kind, n in plays:
            if kind == "step":
                with run.step(n):
                    pass
            else:
                run.device_lab(n, "synthetic reason")

    return probe


def test_runner_requires_every_step_in_order() -> None:
    s = script("JRN-10")
    passed = asyncio.run(runner.run_case(s, "main", _probe_steps(("step", 1), ("step", 2), ("step", 3))))
    assert passed.status == "passed" and passed.case_id == "e2e_jrn10_main" and passed.reached == (1, 2, 3)
    short = asyncio.run(runner.run_case(s, "main", _probe_steps(("step", 1), ("step", 2))))
    assert short.status == "failed" and "steps not played: [3]" in short.reason
    skipped = asyncio.run(runner.run_case(s, "main", _probe_steps(("step", 1), ("step", 3))))
    assert skipped.status == "failed" and "step 3 played, step 2 expected" in skipped.reason
    with pytest.raises(runner.JourneyError):
        asyncio.run(runner.run_case(s, "F9", _probe_steps()))


def test_runner_keeps_device_lab_steps_for_the_device_lab() -> None:
    s = script("JRN-03")
    rest = [("step", n) for n in range(2, len(s.steps) + 1)]
    played = asyncio.run(runner.run_case(s, "main", _probe_steps(("lab", 1), *rest)))
    assert played.status == "passed" and played.delegated == {1: "synthetic reason"}
    cheated = asyncio.run(runner.run_case(s, "main", _probe_steps(("step", 1), *rest)))
    assert cheated.status == "failed" and "runs on the device lab" in cheated.reason
    dodged = asyncio.run(runner.run_case(s, "main", _probe_steps(("lab", 1), ("lab", 2))))
    assert dodged.status == "failed" and "harness step and must be played" in dodged.reason


def test_runner_fails_a_case_that_reaches_the_network() -> None:
    async def probe(run: runner.Run) -> None:
        try:
            socket.create_connection(("192.0.2.1", 443), timeout=0.1)  # a documentation address (RFC 5737)
        except OSError:
            pass

    found = asyncio.run(runner.run_case(script("JRN-10"), "F1", probe))
    assert found.status == "failed" and found.egress and "egress during an offline journey" in found.reason


def test_journey_scripts_name_only_requirement_ids(tmp_path: Path) -> None:
    """A script is identifiers and our own short title only; a script for a journey the specification does not have,
    or with a branch it does not have, fails the suite check."""
    for path in sorted((REPO_ROOT / "evals/journeys").glob("jrn*.yaml")):
        text = path.read_text()
        assert set(re.findall(r"^\s*([a-z_]+):", text, re.MULTILINE)) <= {
            "journey", "title", "persona", "stage", "steps", "n", "requirements", "runs_on", "branches", "id",
            "online",
        }, path  # fmt: skip
    copy = tmp_path / "journeys"
    copy.mkdir()
    for path in (REPO_ROOT / "evals/journeys").glob("jrn*.yaml"):
        (copy / path.name).write_text(path.read_text())
    (copy / "jrn04.yaml").write_text((copy / "jrn04.yaml").read_text().replace("- id: F5", "- id: F6"))
    assert any("JRN-04: script branches" in e for e in script_errors("S2", copy))
    (copy / "jrn12.yaml").write_text((copy / "jrn10.yaml").read_text().replace("JRN-10", "JRN-12"))
    assert any("JRN-12" in e for e in script_errors("S2", copy))
    assert len(scripts()) >= 10
