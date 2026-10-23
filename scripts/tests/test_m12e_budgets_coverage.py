"""M12.e: performance budgets (VER-28) and the KC → checker coverage matrix (VER-36).

The VER-28 acceptance test reads the checker timings the low hardware class reference laptop produces and skips until
the device lab has them; the budget logic is tested here with synthetic timings. The VER-36 matrix runs on the
curriculum sources in the repository, and its rules on synthetic packs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from jana_tools import bench, kc_coverage
from jana_tools.harness import devlab

LAB = os.environ.get("JANA_DEVLAB_RESULTS")  # a directory of <laptop>.json measurement files from the lab
needs_lab = pytest.mark.skipif(LAB is None, reason="needs the reference laptops' measurements (device lab)")


# --- VER-28 ---------------------------------------------------------------------------------------------------------


@needs_lab
def ver28_latency_budgets() -> None:
    assert LAB is not None
    laptops = [json.loads(p.read_text()) for p in sorted(Path(LAB).glob("*.json"))]
    low = [lap for lap in laptops if lap["hardware_class"] == "low"]
    assert low, "the low hardware class reference laptop"
    assert [e for lap in low for e in devlab.tool_budget_errors(lap)] == []


def _timings(**overrides: Any) -> dict[str, Any]:
    """Synthetic timings that meet every budget: two slow warm-up calls, then twenty calls at half the budget."""
    settings = Settings()
    calls = {tool: [5000.0, 5000.0] + [getattr(settings, key) / 2] * 20 for tool, key in devlab.TOOL_BUDGETS.items()}
    tools = {"calls_ms": calls, "cpu_ms": {"math_solve": [12.0, 40.0]}, "ready_s": [1.1, 1.4, 0.9]}
    return {"name": "ref-low", "hardware_class": "low", "network": "disabled", "tools": tools | overrides}


def test_ver28_budget_logic() -> None:
    settings = Settings()
    assert devlab.tool_budget_errors(_timings()) == []
    # One slow call in twenty is above the 95th percentile; two reach it and break the budget.
    slow = _timings()
    slow["tools"]["calls_ms"]["chem_balance"][-1] = settings.ver_p95_chem_balance_ms + 1.0
    assert devlab.tool_budget_errors(slow) == []
    slow["tools"]["calls_ms"]["chem_balance"][-2] = settings.ver_p95_chem_balance_ms + 1.0
    [error] = devlab.tool_budget_errors(slow)
    assert "p95 chem_balance" in error and f"budget of {settings.ver_p95_chem_balance_ms} ms" in error
    short = _timings()
    short["tools"]["calls_ms"]["math_parse"] = [1.0] * 5
    assert any("math_parse has 3 timed calls" in e for e in devlab.tool_budget_errors(short))
    cpu = _timings(cpu_ms={"math_check_step": [10.0, settings.worker_call_cpu_ms + 1.0]})
    assert any("CPU" in e and "math_check_step" in e for e in devlab.tool_budget_errors(cpu))
    ready = _timings(ready_s=[1.0, settings.worker_warm_target_s + 0.5])
    assert any("to be ready" in e for e in devlab.tool_budget_errors(ready))
    assert "no checker timings" in devlab.tool_budget_errors({"name": "ref-low", "network": "disabled"})[0]
    online = _timings()
    online["network"] = "enabled"
    assert any("networking enabled" in e for e in devlab.tool_budget_errors(online))


def test_ver28_lab_output_feeds_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """`worker-bench --lab` writes exactly the `tools` object the gate reads."""
    settings = Settings()
    samples = {tool: [getattr(settings, key) / 4] * 22 for tool, key in devlab.TOOL_BUDGETS.items()}

    async def fake_samples(starts: int, rounds: int) -> tuple[dict[str, Any], str, list[float], dict[str, list[float]]]:
        return {"os": "test"}, "none", [1200.0] * starts, samples

    monkeypatch.setattr(bench, "_samples", fake_samples)
    monkeypatch.setattr(bench, "_cpu_ms", lambda: {"math_parse": [1.5]})
    out = bench.lab(starts=3)
    assert out["tools"]["ready_s"] == [1.2, 1.2, 1.2]
    laptop = {"name": "ref-low", "hardware_class": "low", "network": "disabled", "tools": out["tools"]}
    assert devlab.tool_budget_errors(laptop) == []


def test_ver28_budgets_are_keys() -> None:
    settings = Settings()
    budgets = {tool: getattr(settings, key) for tool, key in devlab.TOOL_BUDGETS.items()}
    assert budgets == {"math_parse": 20, "math_check_equivalence": 300, "math_check_step": 500, "chem_balance": 100,
                       "acc_statements": 300, "phys_circuit": 200}  # fmt: skip
    assert (settings.worker_call_cpu_ms, settings.worker_warm_target_s) == (2000, 3.0)
    assert devlab.scripts()["tool_latency"]["network"] == "disabled"


# --- VER-36 ---------------------------------------------------------------------------------------------------------


def ver36_kc_checker_mapping() -> None:
    found = kc_coverage.matrix("S2")
    assert found.errors == []
    launched = {(p.subject, p.level) for p in found.packs}
    assert ("phy", "o") in launched, "physics O level is the published pack"
    for pack in found.packs:
        assert pack.rows, f"{pack.subject} {pack.level} has knowledge components"
        for row in pack.rows:
            assert row.status != "unmapped"
            if row.kind == "procedural":
                assert row.named and set(row.named) <= set(pack.checkers)
    # Every launched pair is either checked here or listed with what its pack will have to satisfy.
    pending = {tuple(p.split(":")[0].split()) for p in found.pending}
    assert launched | pending == set(kc_coverage.launched("S2"))


def _kc(kc_id: str, kind: str, tools: list[str]) -> dict[str, Any]:
    return {"id": kc_id, "kind": kind, "tools": tools, "status": "active"}


def _item(item_id: str, kc_ids: list[str], tool: str) -> dict[str, Any]:
    return {"id": item_id, "kc_ids": kc_ids, "checks": {"chk_build_x": {"tool": tool, "args": {}}}}


def _pack(root: Path, subject: str, kcs: list[dict[str, Any]], items: list[dict[str, Any]]) -> None:
    (root / subject / "o" / "kcs").mkdir(parents=True)
    (root / subject / "o" / "items").mkdir()
    (root / subject / "o" / "kcs" / "topic.yaml").write_text(yaml.safe_dump(kcs))
    for item in items:
        (root / subject / "o" / "items" / f"{item['id']}.yaml").write_text(yaml.safe_dump(item))


def test_ver36_unmapped_and_wrong_checkers_fail(tmp_path: Path) -> None:
    kcs = [
        _kc("kc.chm.o.moles.balance", "procedural", ["chem_balance"]),
        _kc("kc.chm.o.moles.mass", "procedural", []),  # computational, names nothing
        _kc("kc.chm.o.moles.idea", "conceptual", []),  # content only
        _kc("kc.chm.o.moles.organic", "procedural", ["chem_organic"]),  # an S3 checker
        _kc("kc.chm.o.moles.ledger", "procedural", ["acc_ratios"]),  # another subject's checker
        _kc("kc.chm.o.moles.retired", "procedural", []) | {"status": "retired"},
    ]
    items = [_item("itm.chm.o.moles.0001", ["kc.chm.o.moles.mass"], "chem_molar_mass"),
             _item("itm.chm.o.moles.0002", ["kc.chm.o.moles.idea"], "math_evaluate"),
             _item("itm.chm.o.moles.0003", ["kc.chm.o.moles.balance"], "phys_circuit")]  # fmt: skip
    _pack(tmp_path, "chm", kcs, items)
    found = kc_coverage.pack_coverage("S2", "chm", "o", tmp_path)
    status = {r.kc_id: r.status for r in found.rows}
    assert status == {"kc.chm.o.moles.balance": "mapped", "kc.chm.o.moles.mass": "unmapped",
                      "kc.chm.o.moles.idea": "content_only", "kc.chm.o.moles.organic": "unmapped",
                      "kc.chm.o.moles.ledger": "unmapped"}  # fmt: skip
    errors = "\n".join(found.errors)
    assert "kc.chm.o.moles.mass: a procedural KC that names no checker" in errors and "chem_molar_mass" in errors
    assert "names chem_organic, a S3 checker" in errors
    assert "names acc_ratios, not a chemistry checker" in errors
    assert "runs phys_circuit, not a chemistry checker" in errors
    assert len(found.errors) == 6
    assert any("kc.chm.o.moles.idea: its items are checked by math_evaluate" in n for n in found.notes)
    # Mapped at S3, where the organic checker launches.
    assert "chem_organic" in kc_coverage.checkers("S3", "chm", "o")


def test_ver36_subject_needs_its_own_checker() -> None:
    # Biology launches at S3 with its own checkers; at S2 it has only the general ones.
    assert "bio_calc" in kc_coverage.checkers("S3", "bio", "o")
    assert "bio_calc" not in kc_coverage.checkers("S2", "bio", "o")
    assert ("bio", "o") not in kc_coverage.launched("S2")
