"""Golden sets for the M12.d accounting checkers (VER-22, VER-23, VER-24, VER-25; VER-29), built by construction like
the other sets in `golden.py`.

Expected answers never come from the checkers under test. Ledgers come from transactions chosen first, so each
account's balance is the sum of its signed postings; marking cases from a key with one deliberate, labelled mutation;
corrections from a chosen error type; reconciliations from a chosen updated cash book balance with the statement
balance derived through the chosen reconciling items; statements from chosen figures with capital as the balancing
figure; depreciation from charges chosen to be exact; FIFO closing inventory from the latest receipts that remain;
AVCO from the weighted-average definition on chosen quantities; ratios and break-even from their definitions on chosen
figures. Every case is synthetic; each set says `review: pending` until two subject teachers have authored and
reviewed it."""

from __future__ import annotations

import random
from fractions import Fraction
from math import ceil
from typing import Any

Case = dict[str, Any]
SEED = 20261014

# A synthetic chart of accounts for the generated cases (not any board's chart).
CHART = {
    "id": "coa.acc.o.golden.v1",
    "accounts": [
        {"account_id": "equipment", "account_name": "Equipment", "class": "asset",
         "accepted_names": ["Office equipment", "Fixtures and equipment"]},
        {"account_id": "motor_vehicles", "account_name": "Motor vehicles", "class": "asset"},
        {"account_id": "bank", "account_name": "Bank", "class": "asset", "accepted_names": ["Cash at bank"]},
        {"account_id": "cash", "account_name": "Cash", "class": "asset", "accepted_names": ["Cash in hand"]},
        {"account_id": "inventory", "account_name": "Inventory", "class": "asset"},
        {"account_id": "trade_receivables", "account_name": "Trade receivables", "class": "asset",
         "accepted_names": ["Debtors", "Receivables"]},
        {"account_id": "trade_payables", "account_name": "Trade payables", "class": "liability",
         "accepted_names": ["Creditors", "Payables"]},
        {"account_id": "loan", "account_name": "Bank loan", "class": "liability", "accepted_names": ["Loan"]},
        {"account_id": "capital", "account_name": "Capital", "class": "capital"},
        {"account_id": "drawings", "account_name": "Drawings", "class": "drawings"},
        {"account_id": "sales", "account_name": "Sales", "class": "income", "accepted_names": ["Revenue"]},
        {"account_id": "rent_received", "account_name": "Rent received", "class": "income"},
        {"account_id": "purchases", "account_name": "Purchases", "class": "expense"},
        {"account_id": "wages", "account_name": "Wages", "class": "expense", "accepted_names": ["Salaries"]},
        {"account_id": "rent", "account_name": "Rent", "class": "expense", "accepted_names": ["Rent paid"]},
        {"account_id": "electricity", "account_name": "Electricity", "class": "expense"},
        {"account_id": "accumulated_depreciation", "account_name": "Accumulated depreciation", "class": "contra",
         "normal_side": "credit"},
    ],
}  # fmt: skip
CLASS = {a["account_name"]: a["class"] for a in CHART["accounts"]}
NAMES = [a["account_name"] for a in CHART["accounts"] if a["class"] != "contra"]


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> Case:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _money(value: Fraction | int, dp: int = 2) -> str:
    """Half away from zero at `dp` places, by integer arithmetic on the exact value."""
    value = Fraction(value)
    whole = int(abs(value) * 10**dp + Fraction(1, 2))
    sign = "-" if value < 0 and whole else ""
    units, part = divmod(whole, 10**dp)
    return f"{sign}{units}.{part:0{dp}d}" if dp else f"{sign}{units}"


def _arg(value: Fraction | int) -> int | str:
    value = Fraction(value)
    return int(value) if value.denominator == 1 else _money(value)


def _errors_last(cases: list[Case]) -> list[Case]:
    return [c for c in cases if "error" not in c["expect"]] + [c for c in cases if "error" in c["expect"]]


# --- acc_double_entry -------------------------------------------------------------------------------------------------

DOC_TEXT = "Dr Equipment 5000; Cr Cash 2500; Cr Payables 2500"


def _text(lines: list[tuple[str, str, int]]) -> str:
    return "; ".join(f"{'Dr' if side == 'debit' else 'Cr'} {account} {amount}" for account, side, amount in lines)


def _key_line(account: str, side: str, amount: int) -> dict[str, Any]:
    return {"account_name": account, "debit": amount if side == "debit" else 0,
            "credit": amount if side == "credit" else 0}  # fmt: skip


def double_entry_cases(rng: random.Random) -> list[Case]:
    flip = {"debit": "credit", "credit": "debit"}
    cases = [
        _case("de_doc_example_balances", {"entries_text": DOC_TEXT},
              {"all_balanced": True, "entries": [{"balanced": True, "total_debit": "5000.00"}],
               "trial_balance": {"agrees": True, "total_debit": "5000.00", "total_credit": "5000.00"}}, "hand"),
        _case("de_doc_reversal_wrong_side", {"entries_text": "Cr Equipment 5000; Dr Cash 2500; Dr Payables 2500",
                                             "key_text": DOC_TEXT},
              {"marking": {"correct": False, "entries": [{"verdict": "incorrect", "lines": [
                  {"verdict": "wrong_side"}, {"verdict": "wrong_side"}, {"verdict": "wrong_side"}]}]}}, "hand"),
        _case("de_two_line_reversal",
              {"entries_text": "Dr Cash 800; Cr Rent 800", "key_text": "Dr Rent 800; Cr Cash 800"},
              {"marking": {"entries": [{"lines": [{"verdict": "wrong_side"}, {"verdict": "wrong_side"}]}]}}, "hand"),
        _case("de_doc_correct", {"entries_text": DOC_TEXT, "key_text": DOC_TEXT},
              {"marking": {"correct": True, "entries": [{"verdict": "correct"}]}}, "hand"),
        _case("de_missing_line_unbalanced", {"entries_text": "Dr Equipment 5000; Cr Cash 2500", "key_text": DOC_TEXT},
              {"all_balanced": False, "marking": {"entries": [{"verdict": "unbalanced", "balanced": False, "lines": [
                  {"verdict": "ok"}, {"verdict": "ok"}, {"verdict": "missing_entry"}]}]}}, "hand"),
        _case("de_classified_by_chart", {"entries_text": "Dr Office equipment 5000; Cr Cash at bank 5000",
                                         "chart": CHART},
              {"entries": [{"lines": [{"account_id": "equipment", "class": "asset"},
                                      {"account_id": "bank", "class": "asset"}]}],
               "ledger": [{"account": "Equipment", "class": "asset", "balance_bd": {"side": "debit"}},
                          {"account": "Bank", "class": "asset", "balance_bd": {"side": "credit"},
                           "unusual_balance": True}]}, "hand"),
        _case("de_key_synonym_accepted", {
            "entries": [{"lines": [{"account": "Shop equipment", "side": "debit", "amount": "25,000"},
                                   {"account": "Bank", "side": "credit", "amount": 10000},
                                   {"account": "Creditors", "side": "credit", "amount": 15000}]}],
            "key": [{"lines": [
                {"account_id": "equipment", "account_name": "Equipment",
                 "accepted_names": ["Equipment", "Shop equipment"], "debit": "25000", "credit": "0"},
                {"account_id": "bank", "account_name": "Bank", "accepted_names": ["Bank"], "debit": "0",
                 "credit": "10000"},
                {"account_id": "trade_payables:joseph", "account_name": "Joseph Supplies",
                 "accepted_names": ["Joseph Supplies", "Trade payables", "Creditors"], "debit": "0",
                 "credit": "15000"}]}]},
              {"marking": {"correct": True}}, "hand"),
        _case("de_balance_off_two_sides", {"entries_text": "Dr Bank 900; Cr Sales 900\nDr Wages 300; Cr Bank 300",
                                           "opening_balances": [{"account": "Bank", "side": "debit", "amount": 100}]},
              {"ledger": [{"account": "Bank", "total": "1000.00", "balance_cd": {"side": "credit", "amount": "700.00"},
                           "balance_bd": {"side": "debit", "amount": "700.00"}}, {"account": "Sales"},
                          {"account": "Wages"}],
               "trial_balance": {"agrees": False, "difference": "100.00"}}, "hand"),
        _case("de_closed_account", {"entries_text": "Dr Bank 400; Cr Sales 400\nDr Rent 400; Cr Bank 400"},
              {"ledger": [{"account": "Bank", "balance_cd": None, "total": "400.00", "balance_bd": None},
                          {"account": "Sales"}, {"account": "Rent"}]}, "hand"),
        _case("de_text_not_understood", {"entries_text": "Equipment 5000 debit"}, {"error": 3}, "hand"),
        _case("de_nothing_given", {"task": "post"}, {"error": 4}, "hand"),
    ]  # fmt: skip

    # Corrections: one case per error type, and two errors that compensate.
    right = [{"lines": [{"account": "Equipment", "side": "debit", "amount": 600},
                        {"account": "Bank", "side": "credit", "amount": 600}]}]  # fmt: skip
    errors = {
        "omission": ([], "omission"),
        "reversal": ([("Bank", "debit", 600), ("Equipment", "credit", 600)], "complete_reversal"),
        "commission": ([("Motor vehicles", "debit", 600), ("Bank", "credit", 600)], "commission"),
        "principle": ([("Wages", "debit", 600), ("Bank", "credit", 600)], "principle"),
        "original_entry": ([("Equipment", "debit", 60), ("Bank", "credit", 60)], "original_entry"),
        "single_sided": ([("Equipment", "debit", 600)], "revealed_by_trial_balance"),
    }
    for label, (written, kind) in errors.items():
        recorded = [{"lines": [{"account": a, "side": s, "amount": v} for a, s, v in written]}]
        expect: dict[str, Any] = {"corrections": [{"error": kind}]}
        if kind == "revealed_by_trial_balance":
            expect["corrections"][0]["correction"] = [
                {"account": "Bank", "side": "credit", "amount": "600.00"},
                {"account": "Suspense", "side": "debit", "amount": "600.00"},
            ]
        if kind == "complete_reversal":
            expect["corrections"][0]["correction"] = [
                {"account": "Equipment", "side": "debit", "amount": "1200.00"},
                {"account": "Bank", "side": "credit", "amount": "1200.00"},
            ]
        cases.append(_case(f"de_correct_{label}", {"task": "correct", "recorded": recorded, "entries": right,
                                                   "chart": CHART}, expect, "hand"))  # fmt: skip
    compensating = {
        "task": "correct",
        "recorded": [{"lines": [{"account": "Sales", "side": "credit", "amount": 1100},
                                {"account": "Bank", "side": "debit", "amount": 1000}]},
                     {"lines": [{"account": "Wages", "side": "debit", "amount": 400},
                                {"account": "Bank", "side": "credit", "amount": 300}]}],
        "entries": [{"lines": [{"account": "Sales", "side": "credit", "amount": 1000},
                               {"account": "Bank", "side": "debit", "amount": 1000}]},
                    {"lines": [{"account": "Wages", "side": "debit", "amount": 300},
                               {"account": "Bank", "side": "credit", "amount": 300}]}],
        "chart": CHART,
    }  # fmt: skip
    cases.append(_case("de_correct_compensating", compensating,
                       {"corrections": [{"error": "compensating", "revealed_by_trial_balance": False},
                                        {"error": "compensating"}],
                        "suspense": {"opening": None}}, "hand"))  # fmt: skip

    # Reconciliations (VER-22 acceptance: an omitted unpresented cheque is the first divergent line).
    doc = {
        "cash_book": {"balance": 2300, "entries": [
            {"ref": "201", "direction": "out", "amount": 400}, {"ref": "202", "direction": "out", "amount": 250},
            {"details": "takings", "direction": "in", "amount": 900}]},
        "bank_statement": {"balance": 1715, "entries": [
            {"ref": "201", "direction": "out", "amount": 400}, {"details": "charges", "direction": "out", "amount": 35},
            {"details": "credit transfer", "direction": "in", "amount": 100}]},
        "start_from": "bank_statement",
    }  # fmt: skip
    cases.append(_case("de_reconcile_doc", doc, {
        "reconciled": True, "cash_book": {"updated_balance": "2365.00"},
        "statement": {"lines": [{"id": "bank_statement_balance", "amount": "1715.00"},
                                {"id": "lodgement:3", "op": "add", "amount": "900.00"},
                                {"id": "unpresented:2", "op": "less", "amount": "250.00"},
                                {"id": "cash_book_balance", "amount": "2365.00"}]}}, "hand"))  # fmt: skip
    omitted = {**doc, "student": [{"amount": 1715}, {"amount": 900}, {"amount": 2365}]}
    cases.append(_case("de_reconcile_omitted_cheque", omitted, {"student": {"correct": False, "first_divergent": {
        "id": "unpresented:2", "verdict": "missing_line", "expected": "250.00"}}}, "hand"))  # fmt: skip
    cases.append(_case("de_reconcile_student_correct", {**doc, "student": [{"amount": 1715}, {"amount": 900},
                                                                           {"amount": 250}, {"amount": 2365}]},
                       {"student": {"correct": True, "first_divergent": None}}, "hand"))  # fmt: skip
    cases.append(_case("de_reconcile_from_cash_book", {**doc, "start_from": "cash_book"}, {
        "reconciled": True, "statement": {"lines": [{"id": "cash_book_balance"}, {"op": "less"}, {"op": "add"},
                                                    {"id": "bank_statement_balance", "amount": "1715.00"}]}},
                       "hand"))  # fmt: skip
    overdrawn = {"cash_book": {"balance": 300, "overdrawn": True, "entries": [
        {"ref": "301", "direction": "out", "amount": 200}]},
        "bank_statement": {"balance": 100, "overdrawn": True, "entries": []}}  # fmt: skip
    cases.append(_case("de_reconcile_overdrawn", overdrawn, {"reconciled": True, "cash_book": {
        "updated_balance": "-300.00", "overdrawn": True}}, "hand"))  # fmt: skip
    cases.append(_case("de_reconcile_needs_statement", {"task": "reconcile", "cash_book": {"balance": 1}},
                       {"error": 4}, "hand"))  # fmt: skip

    # Generated: postings and the trial balance from chosen transactions.
    for i in range(34):
        net: dict[str, int] = {}
        order: list[str] = []
        lines_text = []
        for _ in range(rng.randint(1, 5)):
            debit, credit = rng.sample(NAMES, 2)
            value = rng.randint(1, 400) * 25
            for account, signed in ((debit, value), (credit, -value)):
                if account not in net:
                    order.append(account)
                net[account] = net.get(account, 0) + signed
            lines_text.append(f"Dr {debit} {value}; Cr {credit} {value}")
        debits = sum(v for v in net.values() if v > 0)
        rows = [{"account": a, "side": "debit" if net[a] > 0 else "credit", "amount": _money(abs(net[a]))}
                for a in order if net[a]]  # fmt: skip
        expect = {
            "all_balanced": True,
            "trial_balance": {
                "rows": rows,
                "total_debit": _money(debits),
                "total_credit": _money(debits),
                "agrees": True,
            },
        }
        args: dict[str, Any] = {"entries_text": "\n".join(lines_text)}
        if i % 2:
            args["chart"] = CHART
        cases.append(_case(f"de_trial_balance_{i:03d}", args, expect))

    # Generated: one labelled mutation of a key entry.
    mutations = ("none", "wrong_side", "wrong_amount", "wrong_account", "missing_entry", "extra_entry")
    for i in range(36):
        accounts = rng.sample(NAMES, 3)
        total = rng.randint(4, 200) * 50
        part = rng.randint(1, total // 50 - 1) * 50
        key = [(accounts[0], "debit", total), (accounts[1], "credit", part), (accounts[2], "credit", total - part)]
        mutation = mutations[i % len(mutations)]
        student: list[list[Any]] = [list(line) for line in key]
        verdicts = ["ok", "ok", "ok"]
        if mutation == "wrong_side":
            student[1][1] = flip[student[1][1]]
            verdicts[1] = "wrong_side"
        elif mutation == "wrong_amount":
            student[2][2] += 50
            verdicts[2] = "wrong_amount"
        elif mutation == "wrong_account":
            student[0][0] = next(n for n in NAMES if n not in accounts)
            verdicts[0] = "wrong_account"
        elif mutation == "missing_entry":
            student.pop(1)
            verdicts = ["ok", "ok", "missing_entry"]
        elif mutation == "extra_entry":
            extra = next(n for n in NAMES if n not in accounts)
            student.append([extra, "debit", 50])
            verdicts.append("extra_entry")
        balanced = sum(v if s == "debit" else -v for _, s, v in student) == 0
        verdict = "correct" if mutation == "none" else ("unbalanced" if not balanced else "incorrect")
        args = {"entries_text": _text([(a, s, v) for a, s, v in student]), "key_text": _text(key)}
        if i % 3 == 0:  # the structured key form of a content pack
            args.pop("key_text")
            args["key"] = [{"lines": [_key_line(*line) for line in key]}]
        expect = {
            "marking": {
                "correct": mutation == "none",
                "entries": [{"verdict": verdict, "balanced": balanced, "lines": [{"verdict": v} for v in verdicts]}],
            }
        }
        cases.append(_case(f"de_mark_{mutation}_{i:03d}", args, expect))

    # Generated: reconciliations built from the updated cash book balance.
    for i in range(24):
        cash_balance = rng.randint(-20, 400) * 25
        unpresented = [rng.randint(1, 60) * 10 for _ in range(rng.randint(0, 3))]
        lodgements = [rng.randint(1, 60) * 10 + 5 for _ in range(rng.randint(0, 2))]  # never a statement amount
        charges = [rng.randint(1, 9) * 5 for _ in range(rng.randint(0, 2))]
        receipts = [rng.randint(1, 40) * 10 for _ in range(rng.randint(0, 2))]
        updated = cash_balance + sum(receipts) - sum(charges)
        bank_balance = updated - sum(lodgements) + sum(unpresented)
        cleared = [rng.randint(1, 60) * 10 for _ in range(2)]
        cash_entries = ([{"ref": f"c{k}", "direction": "out", "amount": v} for k, v in enumerate(cleared)]
                        + [{"ref": f"u{k}", "direction": "out", "amount": v} for k, v in enumerate(unpresented)]
                        + [{"details": f"lodgement {k}", "direction": "in", "amount": v}
                           for k, v in enumerate(lodgements)])  # fmt: skip
        bank_entries = ([{"ref": f"c{k}", "direction": "out", "amount": v} for k, v in enumerate(cleared)]
                        + [{"ref": f"bc{k}", "details": "charges", "direction": "out", "amount": v}
                           for k, v in enumerate(charges)]
                        + [{"ref": f"ct{k}", "details": "credit transfer", "direction": "in", "amount": v}
                           for k, v in enumerate(receipts)])  # fmt: skip
        args = {"cash_book": {"balance": abs(cash_balance), "overdrawn": cash_balance < 0, "entries": cash_entries},
                "bank_statement": {"balance": abs(bank_balance), "overdrawn": bank_balance < 0,
                                   "entries": bank_entries},
                "start_from": "bank_statement" if i % 2 else "cash_book"}  # fmt: skip
        lines = 2 + len(unpresented) + len(lodgements)
        cases.append(_case(f"de_reconcile_{i:03d}", args, {
            "reconciled": True, "difference": "0.00",
            "cash_book": {"updated_balance": _money(updated), "overdrawn": updated < 0},
            "statement": {"lines": [{} for _ in range(lines)]}}))  # fmt: skip
    return _errors_last(cases)


# --- acc_statements ---------------------------------------------------------------------------------------------------


def _statement_case(rng: random.Random, i: int) -> tuple[dict[str, Any], dict[str, Fraction], list[tuple[str, int]]]:
    """A trial balance from chosen figures, capital the balancing figure; returns args, figures and the expected
    income statement lines (id, value) in order."""
    revenue = rng.randint(400, 900) * 100
    purchases = rng.randint(150, 350) * 100
    opening = rng.randint(10, 60) * 100
    closing = rng.randint(10, 60) * 100
    wages = rng.randint(50, 150) * 100
    rent = rng.randint(12, 60) * 100
    equipment = rng.randint(100, 300) * 100
    old_depreciation = rng.randint(0, 40) * 100
    receivables = rng.randint(20, 90) * 100
    bank = rng.randint(5, 80) * 100
    payables = rng.randint(10, 60) * 100
    drawings = rng.randint(20, 90) * 100
    accrual = rng.randint(0, 10) * 50
    prepaid = rng.randint(0, 10) * 50
    rate = rng.choice([10, 20, 25])
    debits = purchases + opening + wages + rent + equipment + receivables + bank + drawings
    credits = revenue + old_depreciation + payables
    capital = debits - credits
    if capital <= 0:
        revenue += capital - 1000
        capital = 1000
    tb = [
        {"account": "Sales", "role": "revenue", "credit": revenue},
        {"account": "Purchases", "role": "purchases", "debit": purchases},
        {"account": "Inventory at start", "role": "opening_inventory", "debit": opening},
        {"account": "Wages", "role": "expense", "debit": wages},
        {"account": "Rent", "role": "expense", "debit": rent},
        {"account": "Equipment", "role": "non_current_asset", "debit": equipment},
        {"account": "Accumulated depreciation on equipment", "role": "accumulated_depreciation",
         "credit": old_depreciation},
        {"account": "Trade receivables", "role": "trade_receivables", "debit": receivables},
        {"account": "Bank", "role": "bank", "debit": bank},
        {"account": "Trade payables", "role": "trade_payables", "credit": payables},
        {"account": "Capital", "role": "capital", "credit": capital},
        {"account": "Drawings", "role": "drawings", "debit": drawings},
    ]  # fmt: skip
    adjustments: list[dict[str, Any]] = [{"kind": "closing_inventory", "amount": closing}]
    if accrual:
        adjustments.append({"kind": "accrued_expense", "account": "Wages", "amount": accrual})
    if prepaid:
        adjustments.append({"kind": "prepaid_expense", "account": "Rent", "amount": prepaid})
    reducing = i % 2 == 1
    base = equipment - old_depreciation if reducing else equipment
    depreciation = Fraction(base * rate, 100)
    adjustments.append(
        {
            "kind": "depreciation",
            "account": "Equipment",
            "method": "reducing_balance" if reducing else "straight_line",
            "rate_percent": rate,
        }
    )
    available = opening + purchases
    cost_of_sales = available - closing
    gross = revenue - cost_of_sales
    expenses = wages + accrual + rent - prepaid + depreciation
    profit = gross - expenses
    closing_capital = capital + profit - drawings
    total_assets = equipment - old_depreciation - depreciation + closing + receivables + prepaid + bank
    figures = {"profit": profit, "closing_capital": closing_capital, "total_assets": total_assets}
    lines = [("revenue", revenue), ("opening_inventory", opening), ("purchases", purchases),
             ("cost_of_goods_available", available), ("closing_inventory", closing), ("cost_of_sales", cost_of_sales),
             ("gross_profit", gross), ("expense:wages", wages + accrual), ("expense:rent", rent - prepaid),
             ("depreciation:equipment", depreciation), ("total_expenses", expenses),
             ("profit_for_the_year", profit)]  # fmt: skip
    return {"trial_balance": tb, "adjustments": adjustments, "layout": "capital_and_liabilities"}, figures, lines


# Seeded errors: (line, the later lines that follow from it by the own figure rule).
SEEDED = {
    "closing_inventory": ("cost_of_sales", "gross_profit", "profit_for_the_year"),
    "purchases": ("cost_of_goods_available", "cost_of_sales", "gross_profit", "profit_for_the_year"),
    "expense:wages": ("total_expenses", "profit_for_the_year"),
    "revenue": ("gross_profit", "profit_for_the_year"),
}
FORMULAS = {
    "cost_of_goods_available": [(1, "opening_inventory"), (1, "purchases")],
    "cost_of_sales": [(1, "cost_of_goods_available"), (-1, "closing_inventory")],
    "gross_profit": [(1, "revenue"), (-1, "cost_of_sales")],
    "total_expenses": [(1, "expense:wages"), (1, "expense:rent"), (1, "depreciation:equipment")],
    "profit_for_the_year": [(1, "gross_profit"), (-1, "total_expenses")],
}


def statement_cases(rng: random.Random) -> list[Case]:
    cases = []
    # VER-23 acceptance, by hand: closing inventory written as 4,000 instead of 5,000.
    doc_tb = [
        {"account": "Sales", "role": "revenue", "credit": 60000},
        {"account": "Purchases", "role": "purchases", "debit": 35000},
        {"account": "Inventory 1 January", "role": "opening_inventory", "debit": 4000},
        {"account": "Wages", "role": "expense", "debit": 9000},
        {"account": "Rent", "role": "expense", "debit": 3000},
        {"account": "Equipment", "role": "non_current_asset", "debit": 20000},
        {"account": "Provision for depreciation of equipment", "role": "accumulated_depreciation", "credit": 4000},
        {"account": "Trade receivables", "role": "trade_receivables", "debit": 6000},
        {"account": "Bank", "role": "bank", "debit": 2500},
        {"account": "Trade payables", "role": "trade_payables", "credit": 3500},
        {"account": "Capital", "role": "capital", "credit": 20000},
        {"account": "Drawings", "role": "drawings", "debit": 8000},
    ]  # fmt: skip
    doc_adjustments = [{"kind": "closing_inventory", "amount": 5000},
                       {"kind": "accrued_expense", "account": "Wages", "amount": 500},
                       {"kind": "prepaid_expense", "account": "Rent", "amount": 600},
                       {"kind": "depreciation", "account": "Equipment", "amount": 2000}]  # fmt: skip
    written = [("Sales", 60000), ("Opening inventory", 4000), ("Purchases", 35000),
               ("Cost of goods available for sale", 39000), ("Closing inventory", 4000), ("Cost of sales", 35000),
               ("Gross profit", 25000), ("Wages", 9500), ("Rent", 2400), ("Depreciation: Equipment", 2000),
               ("Total expenses", 13900), ("Profit for the year", 11100)]  # fmt: skip
    doc = {"trial_balance": doc_tb, "adjustments": doc_adjustments, "terms": {"revenue": ["Revenue", "Sales"]},
           "student": {"statement": "income_statement",
                       "lines": [{"label": label, "amount": value} for label, value in written]}}  # fmt: skip
    later = {"cost_of_sales": "own_figure", "gross_profit": "own_figure", "profit_for_the_year": "own_figure"}
    cases.append(_case("st_doc_first_divergent_line", doc, {
        "profit_for_the_year": "12100.00", "balanced": True,
        "student": {"correct": False, "first_divergent": {"id": "closing_inventory", "verdict": "wrong",
                                                          "expected": "5000.00", "student": "4000.00"},
                    "lines": [{"verdict": later.get(line_id, "wrong" if line_id == "closing_inventory" else "ok")}
                              for line_id in ("revenue", "opening_inventory", "purchases", "cost_of_goods_available",
                                              "closing_inventory", "cost_of_sales", "gross_profit", "expense:wages",
                                              "expense:rent", "depreciation:equipment", "total_expenses",
                                              "profit_for_the_year")]}}, "hand"))  # fmt: skip
    titles = {"financial_position": ["Balance sheet", "Statement of financial position"]}
    cases.append(_case("st_doc_terms_from_pack", {"trial_balance": doc_tb, "adjustments": doc_adjustments,
                                                  "terms": titles, "layout": "net_assets"},
                       {"financial_position": {"title": "Balance sheet", "layout": {"value": "net_assets"}},
                        "balanced": True}, "hand"))  # fmt: skip
    more = [*doc_adjustments, {"kind": "irrecoverable_debt", "amount": 200}, {"kind": "allowance", "percent": 5},
            {"kind": "goods_for_own_use", "amount": 300}, {"kind": "accrued_income", "account": "Commission",
                                                           "amount": 150}]  # fmt: skip
    # profit 12,100 - 200 irrecoverable - 290 allowance (5% of 5,800) + 300 own use + 150 commission = 12,060
    cases.append(
        _case(
            "st_doc_all_adjustments",
            {"trial_balance": doc_tb, "adjustments": more},
            {"profit_for_the_year": "12060.00", "balanced": True},
            "hand",
        )
    )
    unbalanced = [dict(row) for row in doc_tb]
    unbalanced[0]["credit"] = 60001
    cases.append(_case("st_trial_balance_disagrees", {"trial_balance": unbalanced}, {"error": 4}, "hand"))
    cases.append(_case("st_depreciation_unknown_asset", {"trial_balance": doc_tb, "adjustments": [
        {"kind": "depreciation", "account": "Motor van", "amount": 100}]}, {"error": 4}, "hand"))  # fmt: skip

    for i in range(100):
        args, figures, lines = _statement_case(rng, i)
        expect: dict[str, Any] = {"profit_for_the_year": _money(figures["profit"]), "balanced": True}
        if i % 2 == 0:  # a student statement with one seeded error, or none
            seeded = [*SEEDED, None][(i // 2) % (len(SEEDED) + 1)]
            values = dict(lines)
            student = dict(values)
            if seeded is not None:
                student[seeded] += 100
                for line_id in SEEDED[seeded]:
                    student[line_id] = sum((sign * student[p] for sign, p in FORMULAS[line_id]), Fraction(0))
            args["student"] = {
                "statement": "income_statement",
                "lines": [{"line": line_id, "amount": _arg(student[line_id])} for line_id, _ in lines],
            }
            verdicts = [{"verdict": "ok"} if student[k] == values[k] else
                        {"verdict": "wrong" if k == seeded else "own_figure"} for k, _ in lines]  # fmt: skip
            first = None if seeded is None else {"id": seeded, "verdict": "wrong"}
            expect["student"] = {"correct": seeded is None, "first_divergent": first, "lines": verdicts}
        cases.append(_case(f"st_statement_{i:03d}", args, expect))
    return _errors_last(cases)


# --- acc_depreciation -------------------------------------------------------------------------------------------------


def depreciation_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("dep_doc_straight_line", {"method": "straight_line", "cost": 12000, "residual": 2000, "life_years": 5},
              {"annual_charge": {"value": "2000.00"}, "schedule": [
                  {"year": y, "charge": "2000.00", "closing_nbv": _money(12000 - 2000 * y)} for y in range(1, 6)]},
              "hand"),
        _case("dep_reducing_balance", {"method": "reducing_balance", "cost": 10000, "rate_percent": "20%",
                                       "years": 3},
              {"schedule": [{"charge": "2000.00", "closing_nbv": "8000.00"},
                            {"charge": "1600.00", "closing_nbv": "6400.00"},
                            {"charge": "1280.00", "closing_nbv": "5120.00"}]}, "hand"),
        _case("dep_rounding_per_year", {"method": "reducing_balance", "cost": 1000, "rate_percent": 15, "years": 3},
              {"schedule": [{"charge": "150.00"}, {"charge": "127.50"}, {"charge": "108.38", "closing_nbv": "614.12"}]},
              "hand"),
        _case("dep_time_apportioned", {"method": "straight_line", "cost": 6000, "life_years": 4,
                                       "part_year_policy": "time_apportioned", "first_year_months": 4},
              {"schedule": [{"charge": "500.00"}, {"charge": "1500.00"}, {"charge": "1500.00"}, {"charge": "1500.00"},
                            {"charge": "1000.00", "closing_nbv": "0.00"}]}, "hand"),
        _case("dep_disposal_loss_full_year", {"method": "straight_line", "cost": 8000, "residual": 0, "life_years": 4,
                                              "part_year_policy": "full_year",
                                              "disposal": {"year": 3, "proceeds": 3500}},
              {"schedule": [{"charge": "2000.00"}, {"charge": "2000.00"}, {"charge": "0.00"}],
               "disposal": {"net_book_value": "4000.00", "result": "loss", "amount": "500.00"}}, "hand"),
        _case("dep_percent_of_cost", {"method": "straight_line", "cost": 5000, "rate_percent": 10, "years": 2},
              {"annual_charge": {"value": "500.00"}, "schedule": [{"charge": "500.00"}, {"charge": "500.00"}]},
              "hand"),
        _case("dep_residual_above_cost", {"method": "straight_line", "cost": 100, "residual": 200, "life_years": 2},
              {"error": 4}, "hand"),
        _case("dep_reducing_needs_rate", {"method": "reducing_balance", "cost": 100, "years": 2}, {"error": 4},
              "hand"),
        _case("dep_straight_needs_life", {"method": "straight_line", "cost": 100}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(40):  # straight line with an exact annual charge
        life = rng.randint(2, 10)
        annual = rng.randint(1, 400) * 25
        residual = rng.randint(0, 40) * 50
        cost = annual * life + residual
        schedule = [{"year": y, "charge": _money(annual), "accumulated": _money(annual * y),
                     "closing_nbv": _money(cost - annual * y)} for y in range(1, life + 1)]  # fmt: skip
        cases.append(_case(f"dep_straight_line_{i:03d}", {"method": "straight_line", "cost": cost,
                                                          "residual": residual, "life_years": life},
                           {"annual_charge": {"value": _money(annual)}, "schedule": schedule}))  # fmt: skip
    for i in range(30):  # reducing balance, each charge exact to the cent by the choice of cost
        rate = rng.choice([10, 20, 25, 40, 50])
        years = rng.randint(1, 4)
        cost = rng.randint(1, 50) * 10**4
        nbv = Fraction(cost)
        schedule = []
        for y in range(1, years + 1):
            charge = Fraction(_money(nbv * rate / 100))  # each year's charge is rounded before it is carried
            nbv -= charge
            schedule.append({"year": y, "charge": _money(charge), "closing_nbv": _money(nbv)})
        cases.append(_case(f"dep_reducing_balance_{i:03d}", {"method": "reducing_balance", "cost": cost,
                                                             "rate_percent": rate, "years": years},
                           {"schedule": schedule}))  # fmt: skip
    for i in range(30):  # disposals: the net book value after the full-year charges, then the gain or loss
        life = rng.randint(3, 8)
        annual = rng.randint(1, 200) * 50
        cost = annual * life
        year = rng.randint(2, life)
        nbv = cost - annual * (year - 1)  # full year in the year of purchase, none in the year of disposal
        proceeds = max(nbv + rng.randint(-20, 20) * 50, 0)
        result = "gain" if proceeds > nbv else ("loss" if proceeds < nbv else "none")
        cases.append(_case(f"dep_disposal_{i:03d}", {
            "method": "straight_line", "cost": cost, "life_years": life, "part_year_policy": "full_year",
            "disposal": {"year": year, "proceeds": proceeds}},
            {"disposal": {"year": year, "net_book_value": _money(nbv), "result": result,
                          "amount": _money(abs(proceeds - nbv))}}))  # fmt: skip
    return _errors_last(cases)


# --- acc_inventory ----------------------------------------------------------------------------------------------------


def inventory_cases(rng: random.Random) -> list[Case]:
    doc = [{"kind": "opening", "quantity": 100, "unit_cost": 10}, {"kind": "receipt", "quantity": 200, "unit_cost": 11},
           {"kind": "issue", "quantity": 150}, {"kind": "receipt", "quantity": 100, "unit_cost": 12},
           {"kind": "issue", "quantity": 120}]  # fmt: skip
    # FIFO: the 130 left are the last 100 at 12 and 30 of the 200 at 11 = 1,530; cost of sales 4,400 - 1,530.
    # AVCO: 3,200 / 300 = 32/3 after the first receipt; 150 issued at 1,600 leaves 1,600; + 1,200 = 2,800 / 250 = 11.20;
    # 120 issued at 1,344 leaves 130 at 11.20 = 1,456.
    cases = [
        _case("inv_doc_fifo", {"method": "fifo", "movements": doc},
              {"cost_of_sales": "2870.00", "closing_inventory": {"quantity": 130, "value": "1530.00"}}, "hand"),
        _case("inv_doc_avco", {"method": "avco", "movements": doc},
              {"cost_of_sales": "2944.00", "closing_inventory": {"quantity": 130, "value": "1456.00"}}, "hand"),
        _case("inv_doc_avco_periodic", {"method": "avco", "avco_basis": "periodic", "movements": doc},
              {"periodic_unit_cost": {"exact": "11"}, "cost_of_sales": "2970.00",
               "closing_inventory": {"value": "1430.00"}}, "hand"),
        _case("inv_doc_fifo_nrv", {"method": "fifo", "movements": doc, "nrv": {"per_unit": "11.50"}},
              {"closing_inventory": {"cost": "1530.00", "nrv": "1495.00", "basis": "nrv", "value": "1495.00"}},
              "hand"),
        _case("inv_avco_rounded_unit_cost", {"method": "avco", "round_unit_cost": True, "movements": doc[:3]},
              {"stores_ledger": [{}, {"balance": {"unit_cost": {"exact": "10.67"}}},
                                 {"issue": {"value": "1600.50"}, "balance": {"value": "1600.50"}}]}, "hand"),
        _case("inv_issue_too_many", {"method": "fifo", "movements": [
            {"kind": "opening", "quantity": 5, "unit_cost": 2}, {"kind": "issue", "quantity": 6}]}, {"error": 4},
              "hand"),
        _case("inv_receipt_needs_cost", {"method": "avco", "movements": [{"kind": "receipt", "quantity": 5}]},
              {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(50):  # FIFO: closing inventory is what remains of the latest receipts
        layers = [(rng.randint(1, 40) * 10, rng.randint(100, 2000)) for _ in range(rng.randint(2, 4))]
        cents = [Fraction(c, 100) for _, c in layers]
        bought = sum(q * c for (q, _), c in zip(layers, cents, strict=True))
        held = sum(q for q, _ in layers)
        last_quantity = layers[-1][0]
        closing_quantity = rng.randint(0, last_quantity)
        issued = held - closing_quantity
        closing_value = closing_quantity * cents[-1]
        movements: list[dict[str, Any]] = [{"kind": "opening" if k == 0 else "receipt", "quantity": q,
                                            "unit_cost": _money(c)} for k, (q, c) in enumerate(zip(
                                                [q for q, _ in layers], cents, strict=True))]  # fmt: skip
        if issued:
            movements.append({"kind": "issue", "quantity": issued})
        cases.append(_case(f"inv_fifo_{i:03d}", {"method": "fifo", "movements": movements}, {
            "cost_of_sales": _money(bought - closing_value),
            "closing_inventory": {"quantity": closing_quantity, "value": _money(closing_value)}}))  # fmt: skip
    for i in range(50):  # AVCO perpetual: receipt, issue, receipt, issue, by the weighted-average definition
        q0, c0 = rng.randint(1, 30) * 10, Fraction(rng.randint(100, 900), 100)
        q1, c1 = rng.randint(1, 30) * 10, Fraction(rng.randint(100, 900), 100)
        avg1 = (q0 * c0 + q1 * c1) / (q0 + q1)
        k1 = rng.randint(1, q0 + q1)
        q2, c2 = rng.randint(1, 30) * 10, Fraction(rng.randint(100, 900), 100)
        held = q0 + q1 - k1
        avg2 = (held * avg1 + q2 * c2) / (held + q2)
        k2 = rng.randint(0, held + q2)
        closing_quantity = held + q2 - k2
        movements = [{"kind": "opening", "quantity": q0, "unit_cost": _money(c0)},
                     {"kind": "receipt", "quantity": q1, "unit_cost": _money(c1)},
                     {"kind": "issue", "quantity": k1},
                     {"kind": "receipt", "quantity": q2, "unit_cost": _money(c2)}]  # fmt: skip
        if k2:
            movements.append({"kind": "issue", "quantity": k2})
        cases.append(_case(f"inv_avco_{i:03d}", {"method": "avco", "round_unit_cost": False, "movements": movements},
                           {"cost_of_sales": _money(k1 * avg1 + k2 * avg2),
                            "closing_inventory": {"quantity": closing_quantity,
                                                  "value": _money(closing_quantity * avg2)}}))  # fmt: skip
    return _errors_last(cases)


# --- acc_ratios -------------------------------------------------------------------------------------------------------

DEFINITIONS = {"year_days": 365, "capital_employed": "capital_and_non_current_liabilities", "capital_basis": "closing",
               "roce_profit": "profit_for_the_year", "inventory_basis": "average", "receivables_sales": "credit_sales",
               "payables_purchases": "credit_purchases", "quick_assets": "less_inventory",
               "gearing": "debt_to_capital_employed"}  # fmt: skip


def ratio_cases(rng: random.Random) -> list[Case]:
    doc_figures = {"revenue": 50000, "credit_sales": 40000, "cost_of_sales": 30000, "profit_for_the_year": 8000,
                   "opening_inventory": 3000, "closing_inventory": 4000, "current_assets": 12000,
                   "current_liabilities": 6000, "trade_receivables": 5000, "trade_payables": 2700,
                   "credit_purchases": 27000, "closing_capital": 40000, "non_current_liabilities": 10000}  # fmt: skip
    cases = [
        _case("ratio_doc_golden", {**doc_figures, "definitions": DEFINITIONS}, {"ratios": {
            "gross_margin": {"value": {"value": "40.00"}, "formula": "gross profit / revenue \u00d7 100"},
            "net_margin": {"value": {"value": "16.00"}}, "mark_up": {"value": {"value": "66.67"}},
            "roce": {"value": {"value": "16.00"}}, "current_ratio": {"value": {"value": "2.00"}},
            "acid_test": {"value": {"value": "1.33"}}, "inventory_turnover_times": {"value": {"value": "8.57"}},
            "inventory_turnover_days": {"value": {"value": "42.58"}},
            "receivable_days": {"value": {"value": "45.63"}}, "payable_days": {"value": {"value": "36.50"}},
            "gearing": {"value": {"value": "20.00"}}}}, "hand"),
        _case("ratio_definition_missing", {**doc_figures, "ratios": ["receivable_days"]},
              {"ratios": {"receivable_days": {"status": "unknown", "reason": "convention_missing"}}}, "hand"),
        _case("ratio_360_days", {**doc_figures, "ratios": ["receivable_days"],
                                 "definitions": {"year_days": 360, "receivables_sales": "revenue"}},
              {"ratios": {"receivable_days": {"value": {"exact": "36"}, "definitions": {
                  "year_days": {"value": 360, "source": "item"}}}}}, "hand"),
        _case("ratio_figure_missing", {"revenue": 100, "ratios": ["net_margin"]},
              {"ratios": {"net_margin": {"status": "missing_figures", "missing": "profit_for_the_year"}}}, "hand"),
        _case("ratio_zero_denominator", {"revenue": 0, "gross_profit": 0, "ratios": ["gross_margin"]},
              {"ratios": {"gross_margin": {"status": "undefined"}}}, "hand"),
        _case("ratio_float_refused", {"revenue": 10.5}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(100):
        revenue = rng.randint(200, 2000) * 100
        cost = rng.randint(50, 90) * revenue // 100
        profit = rng.randint(1, 30) * revenue // 100
        opening, closing = rng.randint(5, 80) * 100, rng.randint(5, 80) * 100
        current_assets = closing + rng.randint(10, 200) * 100
        current_liabilities = rng.randint(10, 200) * 100
        receivables, payables = rng.randint(5, 100) * 100, rng.randint(5, 100) * 100
        credit_sales, credit_purchases = revenue * rng.randint(5, 10) // 10, rng.randint(50, 500) * 100
        capital, debt = rng.randint(100, 900) * 100, rng.randint(0, 300) * 100
        figures = {"revenue": revenue, "cost_of_sales": cost, "profit_for_the_year": profit,
                   "opening_inventory": opening, "closing_inventory": closing, "current_assets": current_assets,
                   "current_liabilities": current_liabilities, "trade_receivables": receivables,
                   "trade_payables": payables, "credit_sales": credit_sales, "credit_purchases": credit_purchases,
                   "closing_capital": capital, "non_current_liabilities": debt}  # fmt: skip
        days = 365 if i % 2 else 360
        average = Fraction(opening + closing, 2)
        gross = revenue - cost
        expected = {
            "gross_margin": Fraction(gross * 100, revenue),
            "net_margin": Fraction(profit * 100, revenue),
            "mark_up": Fraction(gross * 100, cost),
            "roce": Fraction(profit * 100, capital + debt),
            "current_ratio": Fraction(current_assets, current_liabilities),
            "acid_test": Fraction(current_assets - closing, current_liabilities),
            "inventory_turnover_times": cost / average,
            "inventory_turnover_days": average * days / cost,
            "receivable_days": Fraction(receivables * days, credit_sales),
            "payable_days": Fraction(payables * days, credit_purchases),
            "gearing": Fraction(debt * 100, capital + debt),
        }
        definitions = {**DEFINITIONS, "year_days": days}
        cases.append(_case(f"ratio_{i:03d}", {**figures, "definitions": definitions},
                           {"ratios": {k: {"status": "ok", "value": {"value": _money(v)}}
                                       for k, v in expected.items()}}))  # fmt: skip
    return _errors_last(cases)


# --- acc_break_even ---------------------------------------------------------------------------------------------------


def break_even_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("be_doc_golden", {"fixed_costs": 10000, "variable_cost_per_unit": 6, "selling_price": 10},
              {"contribution_per_unit": "4.00", "break_even_units": {"exact": {"exact": "2500"}, "whole_units": 2500},
               "break_even_revenue": {"value": "25000.00"}}, "hand"),
        _case("be_doc_margin_and_target", {"fixed_costs": 10000, "variable_cost_per_unit": 6, "selling_price": 10,
                                           "output_units": 3000, "target_profit": 2000},
              {"margin_of_safety": {"units": {"exact": "500"}, "percent": {"value": "16.67"}},
               "target_profit": {"whole_units": 3000}, "profit_at_output": "2000.00",
               "chart": {"max_units": 5000, "total_cost": [[0, "10000.00"], [5000, "40000.00"]]}}, "hand"),
        _case("be_round_up", {"fixed_costs": 1000, "variable_cost_per_unit": 4, "selling_price": 7},
              {"break_even_units": {"exact": {"exact": "1000/3"}, "whole_units": 334}}, "hand"),
        _case("be_no_contribution", {"fixed_costs": 1000, "variable_cost_per_unit": 7, "selling_price": 7},
              {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(100):
        price = Fraction(rng.randint(100, 5000), 100)
        variable = price * rng.randint(10, 90) / 100
        variable = Fraction(int(variable * 100), 100)
        contribution = price - variable
        fixed = rng.randint(10, 2000) * 100
        units = fixed / contribution
        output = rng.randint(0, 3) * ceil(units) // 2 + rng.randint(1, 500)
        target = rng.randint(0, 100) * 100
        args = {"fixed_costs": fixed, "variable_cost_per_unit": _money(variable), "selling_price": _money(price),
                "output_units": output, "target_profit": target}  # fmt: skip
        safety = output - units
        expect = {
            "contribution_per_unit": _money(contribution),
            "break_even_units": {"whole_units": ceil(units), "exact": {"value": _money(units)}},
            "break_even_revenue": {"value": _money(units * price)},
            "margin_of_safety": {"units": {"value": _money(safety)},
                                 "percent": {"value": _money(safety / output * 100)}},
            "target_profit": {"whole_units": ceil((fixed + target) / contribution)},
        }  # fmt: skip
        cases.append(_case(f"be_{i:03d}", args, expect))
    return _errors_last(cases)


STAGES = {name: "S2" for name in ("acc_double_entry", "acc_statements", "acc_depreciation", "acc_inventory",
                                  "acc_ratios", "acc_break_even")}  # fmt: skip


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The M12.d sets by tool name (stage S2)."""
    return {
        "acc_double_entry": double_entry_cases(rng),
        "acc_statements": statement_cases(rng),
        "acc_depreciation": depreciation_cases(rng),
        "acc_inventory": inventory_cases(rng),
        "acc_ratios": ratio_cases(rng),
        "acc_break_even": break_even_cases(rng),
    }
