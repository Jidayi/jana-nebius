"""Markers for structured answers (ASM-03, ASM-07, CUR-15): chemical equations by `chem_balance`, journal entries and
accounting tables by `acc_double_entry` and the key's lines. The worker's checkers run in-process; every item, key and
student answer here is synthetic test data."""

from __future__ import annotations

import asyncio
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import validate
from agent_core.engine.marking import MARKERS, Converted, RunTool, Verdict, mark, settle

SETTINGS = Settings()
CALLS: list[str] = []


async def run_tool(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The worker's checker, in-process: the result value and a check id, or nothing when it refuses."""
    from tool_worker.functions import FUNCTIONS
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    check_id = f"chk_test_{name}_{len(CALLS)}"
    CALLS.append(name)
    try:
        value, _ = FUNCTIONS[name].implementation(args, CallContext("t", check_id, {}, {}, lambda: False, settings={}))
    except WorkerError:
        return None, None
    return value, check_id


async def no_convert(quantity: str, to: str) -> Converted | None:
    raise AssertionError("structured answers convert no units")


def marked(item: dict[str, Any], response: Any, run: RunTool | None = run_tool) -> Verdict:
    verdict = asyncio.run(mark(item, "a", response, no_convert, SETTINGS, run))
    if verdict.outcome != "unverifiable":  # every verdict names the checker it came from (ASM-02)
        assert verdict.provenance and verdict.check_ids
    payload = verdict.payload(verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                              closes_opportunity=True)  # fmt: skip
    validate("learning/learning-event#/$defs/payload_verdict", payload)
    return verdict


def item(kind: str, answer: dict[str, Any], marks: int = 2) -> dict[str, Any]:
    return {"id": "itm.chm.o.reactions.9001", "type": kind,
            "parts": [{"id": "a", "prompt": "Answer.", "marks": marks, "answer": {"kind": kind, **answer},
                       "hints": []}]}  # fmt: skip


def propane(states: str = "ignored", multiple: str = "partial") -> dict[str, Any]:
    species = {"reactants": [{"formula": "C3H8", "coefficient": 1, "state": "g"},
                             {"formula": "O2", "coefficient": 5, "state": "g"}],
               "products": [{"formula": "CO2", "coefficient": 3, "state": "g"},
                            {"formula": "H2O", "coefficient": 4, "state": "l"}]}  # fmt: skip
    return item("chemical_equation", {**species, "state_symbols": states, "non_lowest_multiple": multiple,
                                      "check_id": "chk_build_test_propane"})  # fmt: skip


def test_structured_types_have_markers() -> None:
    assert {"chemical_equation", "journal_entry", "accounting_table"} <= set(MARKERS)


def test_chemical_equation_marker() -> None:
    key = propane()
    assert marked(key, [1, 5, 3, 4]).outcome == "correct"
    assert marked(key, "C3H8 + 5O2 -> 3CO2 + 4H2O").outcome == "correct"
    assert marked(key, "5 O2 + C3H8 → 4 H2O + 3 CO2").outcome == "correct"  # species in any order
    # Balanced but not in lowest terms: partial credit when the item allows it, else wrong (CUR-15).
    multiple = marked(key, ["2", "10", "6", "8"])
    assert (multiple.outcome, multiple.marks_awarded, multiple.error_category) == ("partial", 1.0, "form")
    assert [c["result"] for c in multiple.criteria] == ["pass", "pass", "fail"]
    strict = marked(propane(multiple="wrong"), "2C3H8 + 10O2 -> 6CO2 + 8H2O")
    assert (strict.outcome, strict.marks_awarded, strict.error_category) == ("incorrect", 0.0, "form")
    # Not balanced; wrong species (even balanceable ones); unreadable answers.
    assert (marked(key, [1, 5, 3, 3]).outcome, marked(key, [1, 5, 3, 3]).error_category) == ("incorrect", "unbalanced")
    wrong_species = marked(key, "2C3H8 + 7O2 -> 6CO + 8H2O")
    assert (wrong_species.outcome, wrong_species.error_category) == ("incorrect", "value")
    assert marked(key, "propane burns in oxygen").error_category == "value"
    assert marked(key, [1, 5, 3]).error_category == "unreadable"
    assert marked(key, [1, 0, 3, 4]).error_category == "unreadable"
    # State symbols marked only when the item requires them.
    required = propane(states="required")
    assert marked(required, "C3H8(g) + 5O2(g) -> 3CO2(g) + 4H2O(l)").outcome == "correct"
    assert marked(required, {"coefficients": [1, 5, 3, 4], "states": ["g", "g", "g", "l"]}).outcome == "correct"
    lost = marked(required, "C3H8(g) + 5O2(g) -> 3CO2(g) + 4H2O(g)")
    assert (lost.outcome, lost.marks_awarded, lost.criteria[-1]["result"]) == ("partial", 1.0, "fail")
    assert marked(required, [1, 5, 3, 4]).outcome == "partial"
    assert marked(key, "C3H8(g) + 5O2(g) -> 3CO2(g) + 4H2O(g)").outcome == "correct"  # ignored here
    # No checker, no verdict: never a guess.
    assert marked(key, [1, 5, 3, 4], run=None).outcome == "unverifiable"
    # A model's differing outcome is discarded (ASM-02).
    assert settle("correct", marked(key, [1, 5, 3, 3])).outcome == "incorrect"


def journal() -> dict[str, Any]:
    lines = [{"account_id": "equipment", "account_name": "Equipment", "accepted_names": ["Equipment", "Machinery"],
              "debit": "5000", "credit": "0"},
             {"account_id": "cash", "account_name": "Cash", "accepted_names": ["Cash", "Cash at bank"],
              "debit": "0", "credit": "2500"},
             {"account_id": "trade_payables", "account_name": "Trade payables",
              "accepted_names": ["Trade payables", "Creditors", "Payables"], "debit": "0",
              "credit": "2500"}]  # fmt: skip
    return item("journal_entry", {"chart_of_accounts": "coa.acc.o.standard.v1", "currency": "USD", "lines": lines,
                                  "check_id": "chk_build_test_journal"}, marks=3)  # fmt: skip


def line(account: str, side: str, amount: str) -> dict[str, str]:
    return {"account": account, "side": side, "amount": amount}


def asm07_accounting_errors() -> None:
    key = journal()
    right = [line("Creditors", "credit", "$2,500"), line("Equipment", "debit", "5000"), line("Cash", "credit", "2500")]
    assert marked(key, right).outcome == "correct"  # line order, aliases and the currency symbol do not matter
    assert marked(key, "Dr Equipment 5000; Cr Cash 2500; Cr Payables 2500").outcome == "correct"
    columns = [{"account": "Machinery", "debit": "5000", "credit": ""}, {"account": "Cash", "debit": "", "credit":
               "2500"}, {"account": "Payables", "debit": "0", "credit": "2500"}]  # fmt: skip
    assert marked(key, columns).outcome == "correct"
    seeded = {
        "wrong_side": [line("Equipment", "credit", "5000"), line("Cash", "debit", "2500"),
                       line("Payables", "debit", "2500")],
        "wrong_account": [line("Furniture", "debit", "5000"), line("Cash", "credit", "2500"),
                          line("Payables", "credit", "2500")],
        "unbalanced": [line("Equipment", "debit", "5000"), line("Cash", "credit", "2000"),
                       line("Payables", "credit", "2500")],
        "missing_line": [line("Equipment", "debit", "5000"), line("Cash", "credit", "2500")],
    }  # fmt: skip
    for category, lines in seeded.items():
        verdict = marked(key, lines)
        assert verdict.outcome in ("incorrect", "partial") and verdict.error_category == category, (category, verdict)
        assert verdict.first_error_step is not None and verdict.marks_awarded < 3
    # The line verdicts give the marks: two of three lines right is two marks.
    unbalanced = marked(key, seeded["unbalanced"])
    assert (unbalanced.outcome, unbalanced.marks_awarded, unbalanced.first_error_step) == ("partial", 2.0, 2)
    assert [c["result"] for c in unbalanced.criteria] == ["pass", "fail", "pass"]
    extra = marked(key, [*right, line("Drawings", "debit", "100")])
    assert (extra.outcome, extra.error_category) == ("partial", "unbalanced")
    assert marked(key, [{"account": "Cash"}]).error_category == "unreadable"
    assert marked(key, right, run=None).outcome == "unverifiable"


def test_accounting_table_marker() -> None:
    rows = [{"label": "Equipment", "account_id": "equipment", "amount": "5000", "side": "debit"},
            {"label": "Cash", "account_id": "cash", "amount": "1000", "side": "debit"},
            {"label": "Capital", "account_id": "capital", "amount": "6000", "side": "credit"},
            {"label": "Totals", "amount": "6000", "side": "total"}]  # fmt: skip
    trial = item("accounting_table", {"table_kind": "trial_balance", "chart_of_accounts": "coa.acc.o.standard.v1",
                                      "currency": "USD", "rows": rows, "check_id": "chk_build_test_tb"},
                 marks=4)  # fmt: skip
    answer = [{"label": "Capital", "side": "credit", "amount": "6,000"}, {"label": "Equipment", "side": "debit",
              "amount": "5000"}, {"label": "Cash", "side": "debit", "amount": "1000"}, {"label": "totals",
              "amount": "6000"}]  # fmt: skip
    assert marked(trial, answer).outcome == "correct"
    wrong = [dict(r) for r in answer]
    wrong[2]["amount"] = "1200"
    verdict = marked(trial, wrong)
    assert (verdict.outcome, verdict.error_category, verdict.first_error_step) == ("partial", "unbalanced", 2)
    assert verdict.marks_awarded == 3.0
    flipped = [dict(r) for r in answer]
    flipped[1]["side"] = "credit"
    assert marked(trial, flipped).error_category == "wrong_side"

    statement = [{"label": "Revenue", "amount": "50000", "side": "add", "marks": 1},
                 {"label": "Cost of sales", "amount": "30000", "side": "less", "marks": 1},
                 {"label": "Gross profit", "amount": "20000", "side": "total", "marks": 2},
                 {"label": "Expenses", "amount": "8000", "side": "less", "marks": 1},
                 {"label": "Profit for the year", "amount": "12000", "side": "total", "marks": 2}]  # fmt: skip
    income = item("accounting_table", {"table_kind": "income_statement", "chart_of_accounts": "coa.acc.o.standard.v1",
                                       "currency": "USD", "rows": statement, "check_id": "chk_build_test_is"},
                  marks=7)  # fmt: skip
    written = [{"label": r["label"], "amount": r["amount"]} for r in statement]
    assert marked(income, written).outcome == "correct"
    written[1]["amount"] = "31000"
    written[2]["amount"] = "19000"
    diverged = marked(income, written)
    assert (diverged.outcome, diverged.first_error_step, diverged.error_category) == ("partial", 2, "value")
    assert diverged.marks_awarded == 4.0  # revenue, expenses and profit: 1 + 1 + 2 of 7
    missing = marked(income, written[:3])
    assert missing.error_category == "missing_line"
    assert marked(income, "Revenue 50000").error_category == "unreadable"
