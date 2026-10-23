"""M12.d: accounting checkers (VER-22 double entry and bank reconciliation, VER-23 statements, VER-24 depreciation
and inventory, VER-25 ratios and break-even)."""

import io
import json
from typing import Any

from agent_core.contracts import errors as contract_errors
from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000002"
UPSTREAM = "chk_01JZ0000000000000000000009"


def call(name: str, args: dict[str, Any], conventions: dict[str, Any] | None = None) -> dict[str, Any]:
    """One call through the real server code, in process: the reply frame as a dict."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000, "conventions": conventions or {}}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    reply: dict[str, Any] = next(r for r in replies if r.get("id") == "1")
    if "result" in reply:
        assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", reply["result"]) == []
        assert reply["result"]["check"]["result_sha256"] == golden.result_sha256(reply["result"]["value"])
    return reply


def _golden_failures(tool: str) -> list[str]:
    data = golden.load()[tool]
    assert data["stage"] == "S2" and len(data["cases"]) >= 100
    return [c["id"] for c in data["cases"] if not golden.matches(golden.run(c, tool), c["expect"])]


# --- VER-22 -----------------------------------------------------------------------------------------------------


def ver22_double_entry_golden():
    # The example entry, written as text for the small profile, balances and posts to a trial balance that agrees.
    example = "Dr Equipment 5000; Cr Cash 2500; Cr Payables 2500"
    result = call("acc_double_entry", {"entries_text": example})["result"]
    value = result["value"]
    assert value["entries"][0]["balanced"] and value["all_balanced"] and result["check"]["method"] == "exact"
    assert [a["account"] for a in value["ledger"]] == ["Equipment", "Cash", "Payables"]
    equipment = value["ledger"][0]
    assert equipment["debit"] == [{"ref": "e1", "details": ["Cash", "Payables"], "amount": "5000.00"}]
    assert equipment["balance_cd"] == {"side": "credit", "amount": "5000.00"}
    assert equipment["balance_bd"] == {"side": "debit", "amount": "5000.00"}
    assert value["trial_balance"]["agrees"] and value["trial_balance"]["total_debit"] == "5000.00"
    # With no chart of accounts nothing is classified, and the result says why.
    assert [w["code"] for w in result["warnings"]] == ["convention_missing"]

    # Reversing debit and credit is wrong_side on every line; on a two-line entry, on both lines.
    reversed_entry = "Cr Equipment 5000; Dr Cash 2500; Dr Payables 2500"
    marking = call("acc_double_entry", {"entries_text": reversed_entry, "key_text": example})["result"]["value"]
    assert [ln["verdict"] for ln in marking["marking"]["entries"][0]["lines"]] == ["wrong_side"] * 3
    pair = call("acc_double_entry", {"entries_text": "Dr Cash 800; Cr Rent 800",
                                     "key_text": "Dr Rent 800; Cr Cash 800"})["result"]["value"]  # fmt: skip
    assert [ln["verdict"] for ln in pair["marking"]["entries"][0]["lines"]] == ["wrong_side", "wrong_side"]
    assert pair["marking"]["correct"] is False

    # The pack's chart classifies accounts through its synonyms; a key line accepts its listed names.
    chart = {"id": "coa.acc.o.test.v1", "accounts": [
        {"account_id": "equipment", "account_name": "Equipment", "class": "asset",
         "accepted_names": ["Shop equipment"]},
        {"account_id": "bank", "account_name": "Bank", "class": "asset"},
        {"account_id": "trade_payables", "account_name": "Trade payables", "class": "liability",
         "accepted_names": ["Creditors"]}]}  # fmt: skip
    key = [{"lines": [
        {"account_id": "equipment", "account_name": "Equipment", "debit": "25000", "credit": "0"},
        {"account_id": "bank", "account_name": "Bank", "debit": "0", "credit": "10000"},
        {"account_id": "trade_payables", "account_name": "Trade payables", "debit": "0",
         "credit": "15000"}]}]  # fmt: skip
    student = "Dr Shop equipment 25000; Cr Bank 10000; Cr Creditors 15000"
    marked = call("acc_double_entry", {"entries_text": student, "key": key, "chart": chart})["result"]
    assert marked["value"]["marking"]["correct"] and "warnings" not in marked
    assert [ln["class"] for ln in marked["value"]["entries"][0]["lines"]] == ["asset", "asset", "liability"]

    # Errors the trial balance does not reveal are named, with the correcting entry; a one-sided error goes through
    # suspense.
    right = [{"lines": [{"account": "Equipment", "side": "debit", "amount": 600},
                        {"account": "Bank", "side": "credit", "amount": 600}]}]  # fmt: skip
    for written, kind in (([("Trade payables", "debit", 600), ("Bank", "credit", 600)], "principle"),
                          ([("Bank", "debit", 600), ("Equipment", "credit", 600)], "complete_reversal"),
                          ([("Equipment", "debit", 600)], "revealed_by_trial_balance")):  # fmt: skip
        recorded = [{"lines": [{"account": a, "side": s, "amount": v} for a, s, v in written]}]
        corrected = call("acc_double_entry", {"task": "correct", "recorded": recorded, "entries": right,
                                              "chart": chart})["result"]["value"]  # fmt: skip
        assert corrected["corrections"][0]["error"] == kind
    assert corrected["corrections"][0]["correction"][-1] == {"account": "Suspense", "side": "debit", "amount": "600.00"}
    assert corrected["suspense"]["opening"] == {"side": "credit", "amount": "600.00"}

    # Places shown come from the pack's convention when the call gives none.
    in_whole = call("acc_double_entry", {"entries_text": example}, {"acc.dp": {"value": 0, "source": "pack"}})
    assert in_whole["result"]["value"]["trial_balance"]["total_debit"] == "5000"
    assert _golden_failures("acc_double_entry") == []


def ver22_bank_reconciliation_golden():
    seeded = {
        "cash_book": {"balance": 2300, "entries": [
            {"ref": "201", "direction": "out", "amount": 400}, {"ref": "202", "direction": "out", "amount": 250},
            {"details": "takings", "direction": "in", "amount": 900}]},
        "bank_statement": {"balance": 1715, "entries": [
            {"ref": "201", "direction": "out", "amount": 400}, {"details": "charges", "direction": "out", "amount": 35},
            {"details": "credit transfer", "direction": "in", "amount": 100}]},
    }  # fmt: skip
    result = call("acc_double_entry", seeded)["result"]
    value = result["value"]
    # The cash book is updated for the items first seen on the statement, then reconciled to the statement balance.
    assert [(u["label"], u["direction"], u["amount"]) for u in value["cash_book"]["updates"]] == [
        ("charges", "out", "35.00"), ("credit transfer", "in", "100.00")]  # fmt: skip
    assert value["cash_book"]["updated_balance"] == "2365.00" and value["reconciled"]
    lines = value["statement"]["lines"]
    assert [(ln["id"], ln["op"], ln["amount"]) for ln in lines] == [
        ("bank_statement_balance", "start", "1715.00"), ("lodgement:3", "add", "900.00"),
        ("unpresented:2", "less", "250.00"), ("cash_book_balance", "total", "2365.00")]  # fmt: skip
    # The layout's starting point is a convention: the tool default is visible, the pack's is used when sent.
    assert [w["code"] for w in result["warnings"]] == ["convention_default_used"]
    from_cash = call("acc_double_entry", seeded, {"acc.reconciliation_start": {"value": "cash_book", "source": "pack"}})
    assert from_cash["result"]["value"]["statement"]["start_from"] == {"value": "cash_book", "source": "pack"}
    assert from_cash["result"]["value"]["reconciled"] and "warnings" not in from_cash["result"]

    # A student statement that leaves out the unpresented cheque: that is the first divergent line.
    omitted = call("acc_double_entry", {**seeded, "student": [{"amount": 1715}, {"amount": 900}, {"amount": 2365}]})
    checked = omitted["result"]["value"]["student"]
    assert checked["correct"] is False
    assert checked["first_divergent"] == {"index": 2, "id": "unpresented:2", "verdict": "missing_line",
                                          "expected": "250.00", "label": "unpresented cheque 202"}  # fmt: skip
    assert [m["verdict"] for m in checked["lines"]] == ["ok", "ok", "missing_line", "ok"]
    # A wrong amount is the first divergent line too; a complete statement is correct.
    student = [{"amount": v} for v in (1715, 900, 205, 2365)]
    wrong = call("acc_double_entry", {**seeded, "student": student})["result"]["value"]["student"]
    assert wrong["first_divergent"]["verdict"] == "wrong_amount" and wrong["first_divergent"]["student"] == "205.00"
    full = [{"amount": v} for v in (1715, 900, 250, 2365)]
    assert call("acc_double_entry", {**seeded, "student": full})["result"]["value"]["student"]["correct"]
    # An error in the reconciling items leaves an unexplained difference rather than a false reconciliation.
    off = {**seeded, "bank_statement": {**seeded["bank_statement"], "balance": 1700}}
    unreconciled = call("acc_double_entry", off)["result"]["value"]
    assert unreconciled["reconciled"] is False and unreconciled["difference"] == "-15.00"


# --- VER-23 -----------------------------------------------------------------------------------------------------

TRIAL_BALANCE = [
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
]


def ver23_first_divergent_line():
    adjustments = [
        {"kind": "closing_inventory", "amount": 5000, "check_id": UPSTREAM},  # valued by acc_inventory
        {"kind": "accrued_expense", "account": "Wages", "amount": 500},
        {"kind": "prepaid_expense", "account": "Rent", "amount": 600},
        {"kind": "depreciation", "account": "Equipment", "method": "straight_line", "rate_percent": 10},
    ]
    # The student's income statement with closing inventory seeded wrong (4,000 for 5,000) and the rest carried on.
    written = [("Sales", 60000), ("Opening inventory", 4000), ("Purchases", 35000),
               ("Cost of goods available for sale", 39000), ("Closing inventory", 4000), ("Cost of sales", 35000),
               ("Gross profit", 25000), ("Wages", 9500), ("Rent", 2400), ("Depreciation: Equipment", 2000),
               ("Total expenses", 13900), ("Profit for the year", 11100)]  # fmt: skip
    args = {"trial_balance": TRIAL_BALANCE, "adjustments": adjustments, "terms": {"revenue": ["Revenue", "Sales"]},
            "student": {"statement": "income_statement",
                        "lines": [{"label": label, "amount": amount} for label, amount in written]}}  # fmt: skip
    result = call("acc_statements", args)["result"]
    value = result["value"]
    checked = value["student"]
    assert checked["first_divergent"] == {"id": "closing_inventory", "label": "Closing inventory",
                                          "expected": "5000.00", "student": "4000.00", "verdict": "wrong"}  # fmt: skip
    verdicts = {m["id"]: m["verdict"] for m in checked["lines"]}
    assert [verdicts[k] for k in ("cost_of_sales", "gross_profit", "profit_for_the_year")] == ["own_figure"] * 3
    assert verdicts["revenue"] == verdicts["expense:wages"] == verdicts["total_expenses"] == "ok"
    assert checked["correct"] is False and checked["unrecognised"] == []

    # The statements themselves: every figure traced, every subtotal with its formula; the position balances.
    lines = {ln["id"]: ln for ln in value["income_statement"]["lines"]}
    assert lines["revenue"]["label"] == "Revenue" and lines["revenue"]["trace"] == {"trial_balance": ["Sales"]}
    assert lines["expense:wages"]["amount"] == "9500.00"
    assert lines["expense:wages"]["trace"] == {"trial_balance": ["Wages"], "adjustments": [1]}
    assert lines["gross_profit"] == {"id": "gross_profit", "label": "Gross profit", "op": "total",
                                     "formula": ["+revenue", "-cost_of_sales"], "amount": "26000.00"}  # fmt: skip
    assert value["profit_for_the_year"] == "12100.00" and value["result"] == "profit" and value["balanced"]
    position = {ln["id"]: ln["amount"] for ln in value["financial_position"]["lines"]}
    assert position["asset:equipment:net_book_value"] == "14000.00" and position["other_payables"] == "500.00"
    assert position["total_assets"] == position["total_capital_and_liabilities"] == "28100.00"
    # The closing inventory came from an upstream check, cited in the record (VER-02).
    assert result["check"]["inputs_from"] == [UPSTREAM]

    # Term synonyms and the layout come from the pack: "balance sheet" as the title, the net assets layout.
    pack = {"acc.sofp_layout": {"value": "net_assets", "source": "pack"}}
    terms = {"financial_position": ["Balance sheet", "Statement of financial position"]}
    sheet = call("acc_statements", {"trial_balance": TRIAL_BALANCE, "adjustments": adjustments, "terms": terms}, pack)
    sheet_value = sheet["result"]["value"]
    assert sheet_value["financial_position"]["title"] == "Balance sheet" and sheet_value["balanced"]
    assert sheet_value["financial_position"]["layout"] == {"value": "net_assets", "source": "pack"}
    assert _golden_failures("acc_statements") == []


# --- VER-24 -----------------------------------------------------------------------------------------------------


def ver24_straight_line():
    result = call("acc_depreciation", {"method": "straight_line", "cost": 12000, "residual": 2000, "life_years": 5})
    value = result["result"]["value"]
    assert value["annual_charge"] == {"exact": "2000", "value": "2000.00"}
    assert [r["charge"] for r in value["schedule"]] == ["2000.00"] * 5
    assert value["schedule"][-1]["closing_nbv"] == "2000.00"  # never below the residual value
    # The part-year policy is stated or visibly defaulted; time-apportioned charges follow the months held.
    assert [w["code"] for w in result["result"]["warnings"]] == ["convention_default_used"]
    months = call("acc_depreciation", {"method": "straight_line", "cost": 12000, "residual": 2000, "life_years": 5,
                                       "part_year_policy": "time_apportioned", "first_year_months": 3})  # fmt: skip
    assert [r["charge"] for r in months["result"]["value"]["schedule"]] == ["500.00"] + ["2000.00"] * 4 + ["1500.00"]
    # Reducing balance rounds each year's charge (2 d.p. by default) before carrying the net book value.
    reducing = call("acc_depreciation", {"method": "reducing_balance", "cost": 1000, "rate_percent": 15, "years": 3})
    assert [r["charge"] for r in reducing["result"]["value"]["schedule"]] == ["150.00", "127.50", "108.38"]
    # A disposal: the net book value, the gain or loss and the disposal account.
    sold = call("acc_depreciation", {"method": "straight_line", "cost": 8000, "life_years": 4,
                                     "part_year_policy": "full_year",
                                     "disposal": {"year": 3, "proceeds": 4600}})  # fmt: skip
    disposal = sold["result"]["value"]["disposal"]
    assert (disposal["net_book_value"], disposal["result"], disposal["amount"]) == ("4000.00", "gain", "600.00")
    assert disposal["disposal_account"][-1] == {"side": "debit", "details": "gain", "amount": "600.00"}
    assert _golden_failures("acc_depreciation") == []


def ver24_fifo_avco_golden():
    movements = [{"kind": "opening", "quantity": 100, "unit_cost": 10},
                 {"kind": "receipt", "quantity": 200, "unit_cost": 11},
                 {"kind": "issue", "quantity": 150},
                 {"kind": "receipt", "quantity": 100, "unit_cost": 12},
                 {"kind": "issue", "quantity": 120}]  # fmt: skip
    fifo = call("acc_inventory", {"method": "fifo", "movements": movements})["result"]["value"]
    assert (fifo["cost_of_sales"], fifo["closing_inventory"]["value"]) == ("2870.00", "1530.00")
    first_issue = fifo["stores_ledger"][2]["issue"]
    assert [(lay["quantity"], lay["unit_cost"]["exact"]) for lay in first_issue["layers"]] == [(100, "10"), (50, "11")]
    assert [(lay["quantity"], lay["value"]) for lay in fifo["stores_ledger"][-1]["balance"]["layers"]] == [
        (30, "330.00"), (100, "1200.00")]  # fmt: skip
    avco = call("acc_inventory", {"method": "avco", "movements": movements})["result"]
    value = avco["value"]
    assert (value["cost_of_sales"], value["closing_inventory"]["value"]) == ("2944.00", "1456.00")
    assert value["stores_ledger"][1]["balance"]["unit_cost"] == {"exact": "32/3", "value": "10.67"}  # kept exact
    assert [w["code"] for w in avco["warnings"]] == ["convention_default_used"]
    # The pack may round the AVCO unit cost at each receipt; the periodic average is an option.
    rounded = call("acc_inventory", {"method": "avco", "movements": movements},
                   {"acc.avco_unit_cost": {"value": "rounded", "source": "pack"}})["result"]["value"]  # fmt: skip
    assert rounded["unit_cost_rounded"] and rounded["stores_ledger"][2]["issue"]["value"] == "1600.50"
    periodic = call("acc_inventory", {"method": "avco", "avco_basis": "periodic", "movements": movements})
    assert periodic["result"]["value"]["closing_inventory"]["value"] == "1430.00"
    # Lower of cost and net realisable value.
    nrv = call("acc_inventory", {"method": "fifo", "movements": movements, "nrv": {"total": 1500}})
    assert nrv["result"]["value"]["closing_inventory"] == {"quantity": 130, "cost": "1530.00", "nrv": "1500.00",
                                                           "basis": "nrv", "value": "1500.00"}  # fmt: skip
    over = call("acc_inventory", {"method": "fifo", "movements": [*movements, {"kind": "issue", "quantity": 131}]})
    assert over["error"]["code"] == 4
    assert _golden_failures("acc_inventory") == []


# --- VER-25 -----------------------------------------------------------------------------------------------------


def ver25_ratio_golden():
    figures = {"revenue": 50000, "credit_sales": 40000, "cost_of_sales": 30000, "profit_for_the_year": 8000,
               "opening_inventory": 3000, "closing_inventory": 4000, "current_assets": 12000,
               "current_liabilities": 6000, "trade_receivables": 5000, "trade_payables": 2700,
               "credit_purchases": 27000, "closing_capital": 40000, "non_current_liabilities": 10000}  # fmt: skip
    pack = {f"acc.definition_set.{k}": {"value": v, "source": "pack"} for k, v in {
        "year_days": 365, "capital_employed": "capital_and_non_current_liabilities", "capital_basis": "closing",
        "roce_profit": "profit_for_the_year", "inventory_basis": "average", "receivables_sales": "credit_sales",
        "payables_purchases": "credit_purchases", "quick_assets": "less_inventory",
        "gearing": "debt_to_capital_employed"}.items()}  # fmt: skip
    result = call("acc_ratios", figures, pack)["result"]
    ratios = result["value"]["ratios"]
    expected = {"gross_margin": "40.00", "net_margin": "16.00", "mark_up": "66.67", "roce": "16.00",
                "current_ratio": "2.00", "acid_test": "1.33", "inventory_turnover_times": "8.57",
                "inventory_turnover_days": "42.58", "receivable_days": "45.63", "payable_days": "36.50",
                "gearing": "20.00"}  # fmt: skip
    assert {k: r["value"]["value"] for k, r in ratios.items()} == expected
    assert all(r["formula"] and r["status"] == "ok" for r in ratios.values())
    assert ratios["mark_up"]["value"]["exact"] == "200/3"
    assert ratios["receivable_days"]["formula"] == "trade receivables / credit sales × 365"
    assert ratios["receivable_days"]["definitions"]["year_days"] == {"value": 365, "source": "pack"}
    assert "warnings" not in result
    # A board defining the year as 360 days, stated by the item, is recorded with its source.
    item = call("acc_ratios", {**figures, "ratios": ["receivable_days"],
                               "definitions": {"year_days": 360}}, pack)["result"]["value"]["ratios"]  # fmt: skip
    assert item["receivable_days"]["value"]["value"] == "45.00"
    assert item["receivable_days"]["definitions"]["year_days"] == {"value": 360, "source": "item"}
    # No definition set at all: the ratios that need one are unknown, never a guessed board rule.
    bare = call("acc_ratios", figures)["result"]
    assert bare["value"]["ratios"]["receivable_days"] == {"status": "unknown", "reason": "convention_missing",
                                                          "definition": "receivables_sales"}  # fmt: skip
    assert bare["value"]["ratios"]["gross_margin"]["value"]["value"] == "40.00"
    assert {w["code"] for w in bare["warnings"]} == {"convention_missing"}
    assert _golden_failures("acc_ratios") == []


def ver25_break_even_golden():
    value = call("acc_break_even", {"fixed_costs": 10000, "variable_cost_per_unit": 6, "selling_price": 10,
                                    "output_units": 3000, "target_profit": 2000})["result"]["value"]  # fmt: skip
    assert value["contribution_per_unit"] == "4.00"
    assert value["break_even_units"] == {"exact": {"exact": "2500", "value": "2500.00"}, "whole_units": 2500}
    assert value["break_even_revenue"]["value"] == "25000.00"
    assert value["margin_of_safety"]["units"]["value"] == "500.00"
    assert value["margin_of_safety"]["percent"] == {"exact": "50/3", "value": "16.67"}
    assert value["target_profit"]["whole_units"] == 3000
    chart = value["chart"]
    assert chart["fixed_cost"] == [[0, "10000.00"], [5000, "10000.00"]]
    assert chart["total_cost"][1] == [5000, "40000.00"] and chart["revenue"][1] == [5000, "50000.00"]
    # A fractional break-even point is rounded up to whole units.
    fraction = call("acc_break_even", {"fixed_costs": 1000, "variable_cost_per_unit": 4, "selling_price": 7})
    assert fraction["result"]["value"]["break_even_units"]["whole_units"] == 334
    no_contribution = call("acc_break_even", {"fixed_costs": 1, "variable_cost_per_unit": 7, "selling_price": 7})
    assert no_contribution["error"]["code"] == 4
    assert _golden_failures("acc_break_even") == []
