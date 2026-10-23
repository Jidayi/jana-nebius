"""The `pack.ref` chart of accounts in the build (CUR-07, CUR-18, CUR-28; G113): read from the accounting pack's ref
directory, checked against what the records name and send, and carried in the pack's `charts_of_accounts` table.
Charts and checks changed here are test data."""

from __future__ import annotations

import copy
import shutil
from pathlib import Path
from typing import Any

import pytest
from agent_core.contracts import validator
from agent_core.store import packs
from pack_builder import build as builder
from pack_builder import source as tree
from pack_builder.build import charts_of, load_source
from pack_builder.structure import chart_problems

REPO = Path(__file__).resolve().parents[3]
ACC = REPO / "content" / "curriculum" / "acc" / "o"
CHART = "coa.acc.o.standard.v1"


@pytest.fixture(scope="module")
def source() -> Any:
    return load_source(ACC)


def test_accounting_pack_holds_the_chart_its_records_name(source: Any) -> None:
    [chart] = charts_of(source)
    assert chart["id"] == CHART and len(chart["accounts"]) >= 40
    conventions = {c["key"]: c["value"] for c in source.tables["conventions"]}
    assert conventions["acc.chart_of_accounts"] == CHART
    assert chart_problems(charts_of(source), source.tables, source.checks) == []
    sent = [s for s in source.checks.values() if (s.get("args") or {}).get("chart", {}).get("id") == CHART]
    assert sent, "the accounting checks send the same chart"


def test_chart_carried_in_its_table(source: Any) -> None:
    assert "charts_of_accounts" in packs.TABLES  # the content-pack contract has the table (D90)
    assert [c["id"] for c in source.tables["charts_of_accounts"]] == [CHART]
    assert validator(f"{builder.CONTRACT}#/$defs/ChartOfAccounts").is_valid(source.tables["charts_of_accounts"][0])


def test_chart_problems_block(source: Any) -> None:
    [chart] = charts_of(source)
    # A check that sends the same chart with an account in another class.
    check_id, spec = next((c, s) for c, s in sorted(source.checks.items())
                          if (s.get("args") or {}).get("chart", {}).get("id") == CHART)  # fmt: skip
    drifted = copy.deepcopy(spec)
    for account in drifted["args"]["chart"]["accounts"]:
        if account["account_id"] == "drawings":
            account["class"] = "expense"
    found = chart_problems([chart], source.tables, {check_id: drifted})
    assert found == [f"{check_id}: its chart {CHART} differs from the pack's chart for drawings (CUR-07)"]
    # Fewer accounts, fewer names or an item's personal account are not a difference.
    fewer = copy.deepcopy(spec)
    fewer["args"]["chart"]["accounts"] = [{k: v for k, v in a.items() if k != "accepted_names"}
                                          for a in fewer["args"]["chart"]["accounts"][:3]]  # fmt: skip
    fewer["args"]["chart"]["accounts"].append({"account_id": "p_test_trader", "account_name": "T Trader",
                                               "class": "liability"})  # fmt: skip
    assert chart_problems([chart], source.tables, {check_id: fewer}) == []
    # A chart the conventions name that the ref does not hold; a malformed or doubled chart.
    assert any("names chart of accounts coa.acc.o.standard.v1, which the pack's ref does not hold" in p
               for p in chart_problems([], source.tables, {}))  # fmt: skip
    doubled = {**chart, "accounts": [*chart["accounts"], chart["accounts"][0]]}
    assert f"{CHART}: account cash is listed twice (CUR-07)" in chart_problems([doubled], {}, {})
    assert any("a chart needs an id" in p for p in chart_problems([{**chart, "id": "standard"}], {}, {}))
    assert any("is used twice" in p for p in chart_problems([chart, chart], {}, {}))


def test_chart_source_round_trip(tmp_path: Path) -> None:
    """The chart file sits beside the conventions and is read and written in canonical form (AUT-03)."""
    target = tmp_path / "acc" / "o"
    shutil.copytree(ACC, target)
    shutil.copytree(tree.ref_dir(ACC), tree.ref_dir(target))
    assert tree.format_tree(target) == []
    _, found = tree.read_pack(target)
    [located] = found["charts_of_accounts"]
    assert located.path == tree.ref_dir(target) / tree.CHART_FILE
    edited = {**located.record, "accounts": located.record["accounts"][:2]}
    tree.save_record(target, "charts_of_accounts", edited)
    assert [r.record for r in tree.read_pack(target)[1]["charts_of_accounts"]] == [edited]
