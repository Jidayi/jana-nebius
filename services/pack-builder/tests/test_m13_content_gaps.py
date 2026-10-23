"""The content pipeline gaps the S2 subject streams met (M13): mock papers in a pack (ASM-15, CUR-31), structured item
types in the build (ASM-03), accounting checker results in tool verification and `chem_balance` verdicts as build
checks (CUR-20, VER-19, VER-22, VER-25). Packs are copies of the S1 physics source with synthetic records added; every
paper, item, key and check here is invented test data."""

from __future__ import annotations

import copy
import shutil
from decimal import Decimal
from pathlib import Path
from typing import Any

import mock_contract
import pytest
import yaml
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.store import packs
from agent_core.store.packs import read_pack, verify_for_install
from pack_builder import mocks
from pack_builder import source as tree
from pack_builder.build import BuildError, build, load_source
from pack_builder.verify import Check, Verifier, run_check
from signing_service.keys import DEV_KEY_ID, dev_key

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "content" / "curriculum" / "phy" / "o"
TOPIC = "cur.phy.o.motion_forces_and_energy"
KC = "kc.phy.o.motion.average_speed"
PROVENANCE = {"origin": "original", "licence": "LicenseRef-Own", "drafted_with_ai": False, "sources": []}
PUBLISHED = {"status": "published", "reviewers": []}
HISTORY = {"drafted_by": "rev_author_test", "history": ["drafted", "verified", "in_eval_bank", "published"]}
SECOND = "itm.phy.o.motion.0020"  # a published two-mark numeric item of the topic (a published paper's are published)


def _copy(tmp_path: Path) -> Path:
    target = tmp_path / "src" / "phy" / "o"
    shutil.copytree(SOURCE, target)
    shutil.copytree(tree.ref_dir(SOURCE), tree.ref_dir(target))
    return target


def _item(item_id: str) -> dict[str, Any]:
    return dict(yaml.safe_load((SOURCE / "items" / f"{item_id}.yaml").read_text()))


def _question(qid: str, item_id: str) -> dict[str, Any]:
    item = _item(item_id)
    return {"question_id": qid, "item_id": item_id, "marks": mocks.item_marks(item), "kc_ids": item["kc_ids"]}


def paper(paper_id: str = "mck.phy.o.0001") -> dict[str, Any]:
    questions = [_question("1", "itm.phy.o.motion.0001"), _question("2", SECOND),
                 _question("3", "itm.phy.o.motion.0041")]  # fmt: skip
    marks = sum(q["marks"] for q in questions)
    return {"id": paper_id, "version": "0.1.0", "subject": "phy", "level": "o", "paper_kind": "section_mock",
            "title": "Motion: section mock", "duration_minutes": 30, "total_marks": marks, "calculator": True,
            "blueprint": {"topic_weights": {TOPIC: 1.0}},
            "sections": [{"section_id": "A", "title": "Calculations", "item_types": ["numeric"], "marks": marks,
                          "questions": questions}],
            "provenance": PROVENANCE, "review": PUBLISHED, "authoring": HISTORY}  # fmt: skip


def _write_paper(source: Path, record: dict[str, Any]) -> None:
    tree.save_record(source, "mock_papers", record)


def _problems(source: Path, tmp_path: Path) -> str:
    with pytest.raises(BuildError) as failed:
        build(source, tmp_path / "out")
    return "\n".join(failed.value.problems)


# --- mock papers (ASM-15, CUR-31) -----------------------------------------------------------------------------------


def test_mock_papers_wait_for_the_contract(tmp_path: Path) -> None:
    """Until the content-pack contract has the record, a source with mock papers is refused, never half-built."""
    if "mock_papers" in packs.TABLES:
        pytest.skip("the bundled contract has the mock-paper record")
    source = _copy(tmp_path)
    _write_paper(source, paper())
    assert "mock_papers need the MockPaper record of the content-pack contract" in _problems(source, tmp_path)


def test_mock_papers_built_into_the_pack(tmp_path: Path) -> None:
    with mock_contract.installed():
        source = _copy(tmp_path)
        # The test's own published papers only: the source's banked papers (a082509c) are another test's subject.
        for banked in (source / "mock-papers").glob("*.yaml"):
            banked.unlink()
        papers = [paper(f"mck.phy.o.000{n}") for n in (1, 2, 3)]
        for record in papers:
            _write_paper(source, record)
        loaded = load_source(source)
        assert [p["id"] for p in loaded.tables["mock_papers"]] == [p["id"] for p in papers]
        assert "authoring" not in loaded.tables["mock_papers"][0]  # source only
        built = build(source, tmp_path / "out", key=dev_key(), key_id=DEV_KEY_ID)
        manifest, tables = read_pack(built.pack_path)
        assert {t["name"]: t["rows"] for t in manifest["tables"]}["mock_papers"] == 3
        assert [p["id"] for p in tables["mock_papers"]] == [p["id"] for p in papers]
        # The device verifies the pack, mock papers included, against the contract before it loads (SEC-13).
        assert verify_for_install(built.pack_path, Environment.DEV)["pack_id"] == "pack.phy.o"
        # The canonical source form keeps the record's keys in contract order.
        text = (source / "mock-papers" / "mck.phy.o.0001.yaml").read_text()
        assert text.index("id:") < text.index("paper_kind:") < text.index("sections:") < text.index("authoring:")
    assert mock_contract.CONTRACT_ID  # the bundled contract is restored after the block


def test_mock_paper_problems(tmp_path: Path) -> None:
    source = load_source(SOURCE)
    items, nodes, kcs = source.tables["items"], source.tables["curriculum_nodes"], source.tables["kcs"]
    pack = source.pack
    tolerance = Settings().mock_blueprint_weight_tolerance

    def problems(change: Any) -> str:
        record = paper()
        change(record)
        return "\n".join(mocks.paper_problems([record], pack, items, nodes, kcs, tolerance))

    assert problems(lambda p: None) == ""
    questions = lambda p: p["sections"][0]["questions"]  # noqa: E731
    assert "is not in the pack" in problems(lambda p: questions(p)[0].update(item_id="itm.phy.o.motion.9999"))
    assert "the item carries 2" in problems(lambda p: questions(p)[0].update(marks=3))
    assert "a numeric item in a section of mcq" in problems(lambda p: p["sections"][0].update(item_types=["mcq"]))
    assert "are not the item's" in problems(lambda p: questions(p)[0].update(kc_ids=["kc.phy.o.motion.free_fall"]))
    assert "is on the paper twice" in problems(lambda p: questions(p)[1].update(item_id="itm.phy.o.motion.0001"))
    assert "question id repeats" in problems(lambda p: questions(p)[1].update(question_id="1"))
    assert "not the sum of its questions" in problems(lambda p: p["sections"][0].update(marks=9))
    assert "not the sum of its sections" in problems(lambda p: p.update(total_marks=9))
    assert "a phy.a paper" in problems(lambda p: p.update(level="a"))
    assert "are not topics of the map" in problems(
        lambda p: p["blueprint"].update(topic_weights={TOPIC: 0.5, "cur.phy.o.motion_forces_and_energy.motion": 0.5})
    )
    assert "sum to 0.500" in problems(lambda p: p["blueprint"].update(topic_weights={TOPIC: 0.5}))
    # Marks per topic must match the blueprint within one item (ASM-15).
    shifted = problems(lambda p: p["blueprint"].update(topic_weights={TOPIC: 0.4, "cur.phy.o.waves": 0.6}))
    assert "the blueprint plans 2.0" in shifted and "0 marks on cur.phy.o.waves" in shifted
    # With a choice of questions the marks sat are not fixed per topic, and a section's marks are N questions' worth.
    choice = problems(lambda p: p["sections"][0].update(choose=2))
    assert "every question carries" in choice
    # A published paper uses published items only.
    draft = copy.deepcopy(items)
    next(i for i in draft if i["id"] == SECOND)["review"] = {"status": "verified", "reviewers": []}
    record = paper()
    assert "which is not published" in "\n".join(mocks.paper_problems([record], pack, draft, nodes, kcs, tolerance))


def test_mock_paper_problems_fail_the_build(tmp_path: Path) -> None:
    with mock_contract.installed():
        source = _copy(tmp_path)
        record = paper()
        record["sections"][0]["questions"][0]["marks"] = 5
        record["paper_kind"] = "paper_9"
        _write_paper(source, record)
        found = _problems(source, tmp_path)
        assert "mck.phy.o.0001: $.paper_kind" in found  # the contract shape
        record["paper_kind"] = "section_mock"
        _write_paper(source, record)
        found = _problems(source, tmp_path)
        assert "mck.phy.o.0001 question 1: 5 marks, the item carries 2" in found


# --- structured item types and their keys (ASM-03, VER-19, VER-22, VER-23) ------------------------------------------


def _structured(item_id: str, answer: dict[str, Any], checks: dict[str, Any], marks: int = 2) -> dict[str, Any]:
    base = _item("itm.phy.o.motion.0041")
    hints = [{"rung": n, "name": h["name"], "text": {"en": "Work through it one line at a time."}}
             for n, h in enumerate(base["parts"][0]["hints"], 1)]  # fmt: skip
    record = {**base, "id": item_id, "type": answer["kind"], "stem": "Write the answer in full.",
              "parts": [{"id": "a", "prompt": "Write it.", "marks": marks, "answer": answer, "hints": hints}],
              "solution": {"steps": [{"n": 1, "latex": "\\text{see the key}", "reason": "The key",
                                      "check_id": answer["check_id"]}]},
              "exam_style": {**base["exam_style"], "total_marks": marks}, "checks": checks}  # fmt: skip
    record.pop("template_id", None)
    return record


def propane_item(item_id: str, coefficients: tuple[int, ...] = (1, 5, 3, 4), equation: str | None = None
                 ) -> dict[str, Any]:  # fmt: skip
    check = f"chk_build_test_{item_id[-4:]}"
    names = (("C3H8", "reactants"), ("O2", "reactants"), ("CO2", "products"), ("H2O", "products"))
    species = {side: [{"formula": f, "coefficient": c} for (f, s), c in zip(names, coefficients, strict=True)
                      if s == side] for side in ("reactants", "products")}  # fmt: skip
    answer = {"kind": "chemical_equation", **species, "state_symbols": "ignored", "non_lowest_multiple": "partial",
              "check_id": check}  # fmt: skip
    args = {"equation": equation or "C3H8 + O2 -> CO2 + H2O"}
    return _structured(item_id, answer, {check: {"tool": "chem_balance", "args": args}})


def journal_item(item_id: str, cash: str = "2500") -> dict[str, Any]:
    check = f"chk_build_test_{item_id[-4:]}"
    lines = [{"account_id": "equipment", "account_name": "Equipment", "accepted_names": ["Equipment"],
              "debit": "5000", "credit": "0"},
             {"account_id": "cash", "account_name": "Cash", "accepted_names": ["Cash"], "debit": "0", "credit": cash},
             {"account_id": "trade_payables", "account_name": "Trade payables", "accepted_names": ["Creditors"],
              "debit": "0", "credit": "2500"}]  # fmt: skip
    answer = {"kind": "journal_entry", "chart_of_accounts": "coa.acc.o.standard.v1", "currency": "USD",
              "lines": lines, "check_id": check}  # fmt: skip
    chart = {"id": "coa.acc.o.standard.v1", "accounts": [
        {"account_id": "equipment", "account_name": "Equipment", "class": "asset"},
        {"account_id": "cash", "account_name": "Cash", "class": "asset"},
        {"account_id": "trade_payables", "account_name": "Trade payables", "class": "liability"}]}  # fmt: skip
    args = {"entries_text": "Dr Equipment 5000; Cr Cash 2500; Cr Trade payables 2500", "dp": 2, "chart": chart}
    return _structured(item_id, answer, {check: {"tool": "acc_double_entry", "args": args}}, marks=3)


def table_item(item_id: str, gross: str = "20000.00") -> dict[str, Any]:
    check = f"chk_build_test_{item_id[-4:]}"
    rows = [{"label": "Revenue", "amount": "50000", "side": "add"},
            {"label": "Cost of sales", "amount": "30000", "side": "less"},
            {"label": "Gross profit", "amount": gross, "side": "total"}]  # fmt: skip
    answer = {"kind": "accounting_table", "table_kind": "income_statement", "chart_of_accounts":
              "coa.acc.o.standard.v1", "currency": "USD", "rows": rows, "check_id": check}  # fmt: skip
    args = {"trial_balance": [{"account": "Sales", "role": "revenue", "credit": "50000"},
                              {"account": "Purchases", "role": "purchases", "debit": "30000"},
                              {"account": "Capital", "role": "capital", "credit": "30000"},
                              {"account": "Bank", "role": "bank", "debit": "50000"}],
            "dp": 2, "layout": "capital_and_liabilities"}  # fmt: skip
    return _structured(item_id, answer, {check: {"tool": "acc_statements", "args": args}}, marks=3)


def test_build_accepts_structured_items(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    # The accounting answers name the pack.ref chart of accounts, which the pack's ref must then hold (CUR-07).
    for chart in yaml.safe_load((tree.ref_dir(REPO / "content/curriculum/acc/o") / tree.CHART_FILE).read_text()):
        tree.save_record(source, "charts_of_accounts", chart)
    for record in (propane_item("itm.phy.o.motion.9001"), journal_item("itm.phy.o.motion.9002"),
                   table_item("itm.phy.o.motion.9003")):  # fmt: skip
        tree.save_record(source, "items", record)
    built = build(source, tmp_path / "out")
    _, tables = read_pack(built.pack_path)
    types = {i["id"]: i["type"] for i in tables["items"]}
    assert [types[f"itm.phy.o.motion.900{n}"] for n in (1, 2, 3)] == [
        "chemical_equation", "journal_entry", "accounting_table"]  # fmt: skip


def test_structured_keys_checked_by_their_tools(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    tree.save_record(source, "items", propane_item("itm.phy.o.motion.9001", coefficients=(2, 10, 6, 8)))
    tree.save_record(source, "items", journal_item("itm.phy.o.motion.9002", cash="2000"))
    tree.save_record(source, "items", table_item("itm.phy.o.motion.9003", gross="21000"))
    found = _problems(source, tmp_path)
    assert "itm.phy.o.motion.9001 part a: key coefficients 2 10 6 8 are not chem_balance's 1 5 3 4" in found
    assert "itm.phy.o.motion.9002 part a: the key does not balance (debits 5000, credits 4500)" in found
    assert "key amount 2000 (cash) is not a figure of chk_build_test_9002" in found
    assert "key line 'Gross profit' amount 21000 is not a figure of acc_statements" in found


def test_chem_balance_verdicts_fail_the_build(tmp_path: Path) -> None:
    def problems(args: dict[str, Any]) -> list[str]:
        verifier = Verifier({"chk_build_test_eq": {"tool": "chem_balance", "args": args}}, [])
        verifier.check("itm.chm.o.reactions.9001", "chk_build_test_eq")
        return verifier.problems

    assert problems({"equation": "C3H8 + 5O2 -> 3CO2 + 4H2O"}) == []
    assert problems({"equation": "C3H8 + O2 -> CO2 + H2O"}) == []  # no coefficients stated: only the balance
    assert "finds not balanced (H, O)" in problems({"equation": "C3H8 + 5O2 -> 3CO2 + 3H2O"})[0]
    assert "balanced but not in lowest terms (1 5 3 4)" in problems({"equation": "2C3H8 + 10O2 -> 6CO2 + 8H2O"})[0]
    assert "finds not balanced" in problems({"equation": "C3H8 + O2 -> CO2 + H2O", "coefficients": [1, 5, 3, 3]})[0]
    assert "cannot balance the equation" in problems({"equation": "H2 + O2 + O3 -> H2O"})[0]
    # In a pack, the item that names such a check is refused.
    source = _copy(tmp_path)
    tree.save_record(source, "items", propane_item("itm.phy.o.motion.9001", equation="C3H8 + 5O2 -> 3CO2 + 3H2O"))
    assert (
        "itm.phy.o.motion.9001: chk_build_test_9001 states coefficients 1 5 3 3, which chem_balance finds not "
        "balanced (H, O)" in _problems(source, tmp_path)
    )


# --- accounting results in tool verification (CUR-20, VER-25) -------------------------------------------------------


def _ratio_item(key: str) -> dict[str, Any]:
    answer = {"kind": "numeric", "value": key, "unit": "%", "unit_policy": "none",
              "tolerance": {"mode": "absolute", "value": 0.005}, "check_id": "chk_build_test_markup"}  # fmt: skip
    hints = [{"rung": n, "text": {"en": "Use gross profit over cost of sales."}} for n in range(1, 6)]
    return {"id": "itm.acc.o.ratios.9001", "stem": "Revenue is $37,200 and cost of sales is $27,000.",
            "parts": [{"id": "a", "prompt": "What is the mark-up?", "answer": answer, "hints": hints}],
            "solution": {"steps": [{"n": 1, "latex": "\\text{mark-up} = 37.78\\%",
                                    "check_id": "chk_build_test_markup"}]}}  # fmt: skip


RATIO_CHECK = {"tool": "acc_ratios", "args": {"revenue": "37200", "cost_of_sales": "27000", "ratios": ["mark_up"],
                                              "dp": 2}}  # fmt: skip


def test_verify_reads_accounting_results() -> None:
    result = run_check("chk_build_test_markup", RATIO_CHECK)
    assert {round(n, 2) for n in result.numbers()} >= {Decimal("37.78"), Decimal("10200.00")}
    assert result.shown() != ""
    # The key is reproduced by acc_ratios alone: no maths check stands beside it.
    verifier = Verifier({"chk_build_test_markup": RATIO_CHECK}, [])
    verifier.item(_ratio_item("37.78"))
    assert verifier.problems == []
    wrong = Verifier({"chk_build_test_markup": RATIO_CHECK}, [])
    wrong.item(_ratio_item("27.42"))
    assert any("key 27.42 does not match acc_ratios result" in p for p in wrong.problems)
    # Labels, references and verdicts are not figures.
    named = Check("c", "acc_double_entry", 1, "", "", {"ref": "2024", "amount": "12.50", "account": "7"})
    assert named.numbers() == {Decimal("12.50")}
    assert Check("c", "acc_inventory", 1, "", "", {"exact": "200/3", "value": "66.67"}).shown() == "66.67"
