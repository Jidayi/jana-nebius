"""S1 tests closed in M9 now that the harness and the S1 guard exist: answer oracles (EVL-02) and the non-goal refusals
(PRD-20). Items and dialogues are synthetic."""

from __future__ import annotations

import asyncio
import copy
import shutil
from pathlib import Path
from typing import Any

import pytest
from jana_tools import REPO_ROOT
from jana_tools.harness import run as harness
from jana_tools.scenarios import ScenarioResult, load_suite, run_scenario
from pack_builder import source as tree
from pack_builder.build import BuildError, build

PACK = REPO_ROOT / "content" / "curriculum" / "phy" / "o"


def evl02_every_item_has_oracle(tmp_path: Path) -> None:
    copy_dir = tmp_path / "src" / "phy" / "o"
    shutil.copytree(PACK, copy_dir)
    shutil.copytree(tree.ref_dir(PACK), tree.ref_dir(copy_dir))
    _, found = tree.read_pack(copy_dir)
    item = copy.deepcopy(next(i.record for i in found["items"] if i.record["id"] == "itm.phy.o.motion.0010"))
    del item["parts"][0]["answer"]
    tree.save_record(copy_dir, "items", item)
    with pytest.raises(BuildError) as failed:
        build(copy_dir, tmp_path / "out")
    assert any(p.startswith("itm.phy.o.motion.0010") for p in failed.value.problems), "the bank build fails"
    # And every item of the real bank has an oracle that verifies.
    cases = harness._oracle_cases()
    items = [
        p
        for pack in PACK.parent.parent.glob("*/*")
        if (pack / "pack.yaml").exists()
        for p in (pack / "items").glob("*.yaml")
    ]
    assert len(cases) == len(items) and all(c["status"] == "passed" for c in cases)


def evl02_untraced_number_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    suite = load_suite(REPO_ROOT / "evals" / "scenarios" / "s1_guided_solve.yaml")

    async def fake(scenario: dict[str, Any], *args: Any, **kwargs: Any) -> ScenarioResult:
        return ScenarioResult(scenario["id"], "passed", numbers_total=3, numbers_traced=2)

    monkeypatch.setattr("jana_tools.scenarios.run_scenario", fake)
    cases = asyncio.run(harness._scenario_cases("scenarios", REPO_ROOT / "evals" / "scenarios", "S1", "development",
                                                None, 2))  # fmt: skip
    assert len(cases) == len(suite["scenarios"])
    assert all(c["status"] == "failed" and "without a check id" in c["reason"] for c in cases), (
        "a run that shows an untraced number fails, even with every expectation met"
    )


def prd20_non_goal_requests_declined() -> None:
    suite = load_suite(REPO_ROOT / "evals" / "safety" / "scope-non-goals.yaml")
    assert {s["id"] for s in suite["scenarios"]} == {
        "non_goal_general_chat_declined",
        "non_goal_answer_machine_declined",
    }
    for scenario in suite["scenarios"]:
        assert scenario["critical"] and scenario["stage"] == "S1"
        result = asyncio.run(run_scenario(scenario, REPO_ROOT / "evals" / "safety", suite="scope_non_goals"))
        assert result.status == "passed", (scenario["id"], result.reason,
                                           [c.detail for c in result.checks if c.passed is False])  # fmt: skip
