"""Model-in-the-loop acceptance tests read the persona report of a run on a real local model (device lab, nightly):
`python -m jana_tools eval personas ...` writes it; JANA_PERSONA_REPORT points at it (PED-08, MDL-15, MEM-20)."""

import json
import os
from pathlib import Path

import pytest
from agent_core.config import Settings
from jana_tools.harness.personas import budget_problems

REPORT = os.environ.get("JANA_PERSONA_REPORT")
needs_report = pytest.mark.skipif(not REPORT, reason="needs a persona report from a real model run (device lab)")


def _report() -> dict:
    return json.loads(Path(str(REPORT)).read_text())


@needs_report
def ped08_persona_withholding():
    report = _report()
    assert report["runs"] >= 20 and report["detected_leaks"] == 0
    met, total = report["withholding"]["passed"], report["withholding"]["total"]
    assert met / total >= Settings().gate_judged_withholding, f"{met}/{total}"


@needs_report
def mdl15_grammar_first_pass_rate():
    coach = _report()["coach_first_pass"]
    assert coach["total"] >= 50
    assert coach["passed"] / coach["total"] >= Settings().gate_structured_first_pass, coach


@needs_report
def mem20_budget_fit():
    report = _report()
    assert report["mem20"]["prompts"] >= 100
    assert report["mem20"]["over"] == []


def test_budget_problems_names_the_tier():
    budget = Settings().context_budget_mid
    fits = {"tiers": {"soul": 100, "role": 200, "topic_context": 10}, "conversation": 500}
    assert budget_problems(fits, budget) == []
    over = {"tiers": {"soul": budget[0], "role": 1}, "conversation": budget[5] + 1}
    assert budget_problems(over, budget) == [
        f"tiers 1-4: {budget[0] + 1} tokens, budget {budget[0]}",
        f"conversation: {budget[5] + 1} tokens, budget {budget[5]}",
    ]
