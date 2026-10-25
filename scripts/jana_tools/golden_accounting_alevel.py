"""Golden sets for the A level accounting checkers (VER-34; VER-29), built by construction like `golden_accounting.py`
and with their own seed, so the S2 sets are unchanged.

Expected answers never come from the checkers under test. Each case is built backwards from the answer chosen first:
partnership profits from a chosen residual and appropriations; changes in equity from chosen movements; manufacturing
purchases from a chosen cost of raw materials consumed; incomplete records from a chosen profit, credit sales and
purchases, cost of sales and inventory lost; cash flows from chosen flows, with the purchases, tax paid and disposal
proceeds turned into the balances the question would print; control accounts from a chosen closing balance, the
receipts or payments being the balancing figure; investment appraisal from chosen flows by the definitions (payback
in years and months, ARR on the stated basis, NPV with three-place table factors, IRR by interpolation). Every case is
synthetic; each set says `review: pending` until two subject teachers have authored and reviewed it."""

from __future__ import annotations

import random
from fractions import Fraction
from math import ceil
from typing import Any

from .golden_accounting import _case, _errors_last, _money

Case = dict[str, Any]
SEED = 20261023


# --- acc_statements: the A level forms --------------------------------------------------------------------------------


def _partnership(rng: random.Random, i: int) -> Case:
    count = rng.choice([2, 2, 3])
    ratio = [rng.randint(1, 5) for _ in range(count)]
    residual = rng.randint(-20, 200) * 300 * sum(ratio)  # shares come out in whole currency units
    rate = rng.choice([0, 5, 6, 10])
    partners, appropriated, back = [], Fraction(0), Fraction(0)
    expected: dict[str, Any] = {}
    for p in range(count):
        pid = "abc"[p]
        capital = rng.randint(10, 100) * 1000
        salary = rng.choice([0, 0, rng.randint(5, 20) * 1000])
        drawings = rng.randint(5, 40) * 1000
        iod = rng.choice([0, rng.randint(1, 10) * 50])
        opening = rng.randint(-30, 60) * 100
        interest = Fraction(capital * rate, 100)
        share = Fraction(residual * ratio[p], sum(ratio))
        appropriated += salary + interest
        back += iod
        partners.append({"id": pid, "name": f"Partner {pid.upper()}", "capital": capital, "salary": salary,
                         "drawings": drawings, "interest_on_drawings": iod, "profit_share": ratio[p],
                         "current_account_opening": opening})  # fmt: skip
        closing = opening + salary + interest + share - drawings - iod
        expected[pid] = (share, closing)
    profit = residual + appropriated - back
    args = {
        "form": "partnership",
        "partnership": {"profit_for_the_year": int(profit), "interest_on_capital_percent": rate, "partners": partners},
    }
    expect = {"residual_profit": _money(residual), "shares": {pid: _money(s) for pid, (s, _) in expected.items()},
              "current_accounts": {pid: {"amount": _money(abs(c)), "side": "credit" if c >= 0 else "debit"}
                                   for pid, (_, c) in expected.items()}}  # fmt: skip
    return _case(f"partnership_{i:03d}", args, expect)


def _company(rng: random.Random, i: int) -> Case:
    operations = rng.randint(50, 500) * 1000
    finance = rng.randint(0, 40) * 500
    tax = rng.randint(0, 60) * 500
    profit = operations - finance - tax
    capital, premium, retained = rng.randint(100, 500) * 1000, rng.randint(0, 100) * 1000, rng.randint(0, 200) * 1000
    shares, price = rng.randint(1, 100) * 1000, rng.choice(["1.00", "1.20", "1.50", "2.00"])
    bonus = rng.randint(0, premium // 1000) * 1000 if rng.random() < 0.5 else 0
    dividends = rng.randint(0, (retained + profit) // 2000) * 1000
    transfer = rng.choice([0, 0, rng.randint(1, 20) * 1000])
    issue_premium = shares * (Fraction(price) - 1)
    issues = [{"kind": "issue", "shares": shares, "nominal_value": 1, "price": price}]
    if bonus:
        issues.append({"kind": "bonus", "shares": bonus, "nominal_value": 1, "from_reserve": "share_premium"})
    args = {"form": "limited_company", "company": {
        "profit_from_operations": operations, "finance_costs": finance, "tax": tax,
        "equity": {"share_capital": capital, "share_premium": premium, "retained_earnings": retained},
        "share_issues": issues, "dividends_paid": dividends, "transfer_to_general_reserve": transfer}}  # fmt: skip
    closing: dict[str, Fraction | int] = {
        "share_capital": capital + shares + bonus,
        "share_premium": premium + issue_premium - bonus,
        "retained_earnings": retained + profit - dividends - transfer,
    }
    if transfer:
        closing["general_reserve"] = transfer
    expect = {"profit_for_the_year": _money(profit), "total_equity": _money(sum(closing.values())),
              "closing": {k: _money(v) for k, v in closing.items()}}  # fmt: skip
    return _case(f"company_{i:03d}", args, expect)


def _manufacturing(rng: random.Random, i: int) -> Case:
    consumed = rng.randint(20, 200) * 1000
    opening, closing = rng.randint(1, 30) * 500, rng.randint(1, 30) * 500
    carriage = rng.choice([0, rng.randint(1, 10) * 100])
    purchases = consumed + closing - opening - carriage
    labour, overheads = rng.randint(10, 150) * 1000, [rng.randint(1, 30) * 500 for _ in range(rng.randint(1, 4))]
    wip_open, wip_close = rng.randint(0, 20) * 500, rng.randint(0, 20) * 500
    markup = rng.choice([0, 10, 20, 25])
    units = rng.choice([0, 1000, 2500, 4000])
    prime = consumed + labour
    cost = prime + sum(overheads) + wip_open - wip_close
    raw = {"opening_inventory": opening, "purchases": purchases, "closing_inventory": closing}
    if carriage:
        raw["carriage_inwards"] = carriage
    data: dict[str, Any] = {"raw_materials": raw, "direct_labour": labour,
                            "factory_overheads": [{"name": f"Overhead {k + 1}", "amount": v}
                                                  for k, v in enumerate(overheads)],
                            "work_in_progress": {"opening": wip_open, "closing": wip_close}}  # fmt: skip
    expect: dict[str, Any] = {"prime_cost": _money(prime), "cost_of_production": _money(cost)}
    if markup:
        data["factory_profit_percent"] = markup
        expect["transfer_price"] = _money(Fraction(cost * (100 + markup), 100))
    if units:
        data["units_produced"] = units
        expect["unit_cost"] = {"value": _money(Fraction(cost, units))}
    return _case(f"manufacturing_{i:03d}", {"form": "manufacturing", "manufacturing": data}, expect)


def _incomplete(rng: random.Random, i: int) -> Case:
    profit = rng.randint(-10, 80) * 500
    drawings, introduced = rng.randint(0, 30) * 500, rng.choice([0, rng.randint(1, 20) * 500])
    opening_assets, opening_liabilities = rng.randint(40, 200) * 500, rng.randint(0, 40) * 500
    closing_net = opening_assets - opening_liabilities + profit + introduced - drawings
    closing_liabilities = rng.randint(0, 40) * 500
    basis, percent = rng.choice([("mark_up", 25), ("mark_up", 50), ("margin", 20), ("margin", 40)])
    cost_of_sales = rng.randint(40, 200) * 300  # chosen first, so revenue is whole at every margin here
    sales = cost_of_sales * (100 + percent) // 100 if basis == "mark_up" else cost_of_sales * 100 // (100 - percent)
    cash_sales = rng.choice([0, rng.randint(0, sales // 1000) * 500])
    credit_sales = sales - cash_sales
    open_rec, close_rec, discounts = rng.randint(5, 40) * 100, rng.randint(5, 40) * 100, rng.randint(0, 10) * 50
    receipts = open_rec + credit_sales - discounts - close_rec
    purchases_total = rng.randint(30, 150) * 400
    open_pay, close_pay = rng.randint(5, 40) * 100, rng.randint(5, 40) * 100
    payments = open_pay + purchases_total - close_pay
    opening_inventory = rng.randint(0, 20) * 1000 + max(0, cost_of_sales - purchases_total)
    expected_closing = opening_inventory + purchases_total - cost_of_sales
    lost = Fraction(rng.randint(0, min(40, int(expected_closing) // 100)) * 100)
    sales_data: dict[str, Any] = {"opening_receivables": open_rec, "closing_receivables": close_rec,
                                  "receipts": receipts, "discounts_allowed": discounts}  # fmt: skip
    if cash_sales:
        sales_data["cash_sales"] = cash_sales
    data = {
        "affairs": {"opening": {"assets": opening_assets, "liabilities": opening_liabilities},
                    "closing": {"assets": closing_net + closing_liabilities, "liabilities": closing_liabilities},
                    "drawings": drawings, "capital_introduced": introduced},
        "sales": sales_data,
        "purchases": {"opening_payables": open_pay, "closing_payables": close_pay, "payments": payments},
        "margin": {"percent": percent, "basis": basis, "opening_inventory": opening_inventory,
                   "closing_inventory": _money(expected_closing - lost)},
    }  # fmt: skip
    expect = {"profit_for_the_year": _money(profit), "total_purchases": _money(purchases_total),
              "cost_of_sales": _money(cost_of_sales), "expected_closing_inventory": _money(expected_closing),
              "inventory_lost": _money(lost)}  # fmt: skip
    expect["total_sales"] = _money(sales)
    return _case(f"incomplete_{i:03d}", {"form": "incomplete_records", "incomplete_records": data}, expect)


def a_level_statement_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("partnership_doc", {"form": "partnership", "partnership": {
            "profit_for_the_year": 50000, "interest_on_capital_percent": 5, "partners": [
                {"id": "a", "name": "Ali", "capital": 40000, "drawings": 20000, "interest_on_drawings": 500,
                 "profit_share": 3, "current_account_opening": 2000},
                {"id": "b", "name": "Bola", "capital": 20000, "salary": 8000, "drawings": 30000,
                 "interest_on_drawings": 300, "profit_share": 2, "current_account_opening": "(1,000)"}]}},
              {"residual_profit": "39800.00", "shares": {"a": "23880.00", "b": "15920.00"},
               "current_accounts": {"a": {"amount": "7380.00", "side": "credit"},
                                    "b": {"amount": "6380.00", "side": "debit"}}}, "hand"),
        _case("company_doc", {"form": "limited_company", "company": {
            "profit_from_operations": 90000, "finance_costs": 5000, "tax": 17000,
            "equity": {"share_capital": 200000, "share_premium": 30000, "retained_earnings": 45000},
            "share_issues": [{"kind": "issue", "shares": 50000, "nominal_value": 1, "price": "1.50"},
                             {"kind": "bonus", "shares": 25000, "nominal_value": 1}],
            "dividends_paid": 20000, "transfer_to_general_reserve": 10000}},
              {"profit_for_the_year": "68000.00", "total_equity": "398000.00",
               "closing": {"share_capital": "275000.00", "share_premium": "30000.00", "general_reserve": "10000.00",
                           "retained_earnings": "83000.00"}}, "hand"),
        _case("company_bonus_exceeds_premium", {"form": "limited_company", "company": {
            "profit_for_the_year": 1000, "equity": {"share_capital": 10000, "share_premium": 2000},
            "share_issues": [{"kind": "bonus", "shares": 5000, "nominal_value": 1}]}}, {"error": 4}, "hand"),
        _case("company_issue_at_discount", {"form": "limited_company", "company": {
            "profit_for_the_year": 1000, "share_issues": [{"kind": "issue", "shares": 100, "nominal_value": 1,
                                                           "price": "0.80"}]}}, {"error": 4}, "hand"),
        _case("manufacturing_doc", {"form": "manufacturing", "manufacturing": {
            "raw_materials": {"opening_inventory": 8000, "purchases": 60000, "carriage_inwards": 1000,
                              "closing_inventory": 9000},
            "direct_labour": 40000, "factory_overheads": [{"name": "Factory rent", "amount": 12000},
                                                          {"name": "Depreciation of machinery", "amount": 6000}],
            "work_in_progress": {"opening": 5000, "closing": 7000}, "factory_profit_percent": 10,
            "units_produced": 10000}},
              {"prime_cost": "100000.00", "cost_of_production": "116000.00", "transfer_price": "127600.00",
               "unit_cost": {"exact": "58/5", "value": "11.60"}}, "hand"),
        _case("incomplete_margin_revenue", {"form": "incomplete_records", "incomplete_records": {"margin": {
            "percent": 20, "basis": "margin", "opening_inventory": 5000, "purchases": 40000,
            "closing_inventory": 7000}}}, {"revenue": "47500.00", "cost_of_sales": "38000.00"}, "hand"),
        _case("incomplete_inventory_surplus", {"form": "incomplete_records", "incomplete_records": {"margin": {
            "percent": 25, "basis": "mark_up", "revenue": 50000, "purchases": 40000, "opening_inventory": 0,
            "closing_inventory": 1000}}}, {"error": 4}, "hand"),
        _case("form_without_its_data", {"form": "partnership"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(30):
        cases.append(_partnership(rng, i))
    for i in range(25):
        cases.append(_company(rng, i))
    for i in range(25):
        cases.append(_manufacturing(rng, i))
    for i in range(25):
        cases.append(_incomplete(rng, i))
    return _errors_last(cases)


# --- acc_cash_flow ----------------------------------------------------------------------------------------------------


def cash_flow_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("cash_flow_doc", {
            "profit_from_operations": 40000, "non_cash": [{"kind": "depreciation", "amount": 8000}],
            "disposal": {"cost": 10000, "accumulated_depreciation": 6000, "proceeds": 3000},
            "non_current_asset_balances": {"opening_cost": 100000, "closing_cost": 120000},
            "working_capital": [{"item": "inventory", "opening": 10000, "closing": 12000},
                                {"item": "trade_receivables", "opening": 8000, "closing": 7000},
                                {"item": "trade_payables", "opening": 5000, "closing": 6500}],
            "interest_paid": 2000,
            "tax_balances": {"opening_liability": 6000, "charge": 9000, "closing_liability": 7000},
            "financing": [{"kind": "share_issue", "amount": 20000}, {"kind": "dividends_paid", "amount": 10000}],
            "opening_cash": 5000},
              {"net_cash_from_operating_activities": "39500.00", "net_cash_from_investing_activities": "-27000.00",
               "net_cash_from_financing_activities": "10000.00", "net_change_in_cash": "22500.00",
               "closing_cash": "27500.00"}, "hand"),
        _case("cash_flow_missing_flow", {"profit_from_operations": 1000, "opening_cash": 0, "closing_cash": 1500},
              {"status": "unknown", "reason": "does_not_reconcile", "difference": "500.00"}, "hand"),
        _case("cash_flow_both_profits", {"profit_from_operations": 1, "profit_before_tax": 1, "opening_cash": 0},
              {"error": 4}, "hand"),
        _case("cash_flow_given_and_derived_differ", {"profit_from_operations": 1, "opening_cash": 0,
                                                     "tax_paid": 100, "tax_balances": {"opening_liability": 50,
                                                     "charge": 80, "closing_liability": 40}}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(100):
        pbt_basis = i % 3 == 0
        profit = rng.randint(-20, 200) * 500
        depreciation = rng.randint(0, 40) * 250
        carrying, gain = rng.randint(0, 40) * 250, rng.randint(-20, 20) * 100
        gain = max(gain, -carrying)
        cost = carrying + rng.randint(1, 40) * 250
        proceeds = carrying + gain
        purchases = rng.randint(0, 100) * 500
        opening_cost = cost + rng.randint(0, 200) * 500
        closing_cost = opening_cost + purchases - cost
        tax_paid, tax_open, charge = rng.randint(0, 30) * 200, rng.randint(0, 30) * 200, rng.randint(0, 30) * 200
        tax_paid = min(tax_paid, tax_open + charge)
        interest = rng.randint(0, 20) * 100
        changes = {}
        working = []
        for item, sign in (("inventory", 1), ("trade_receivables", 1), ("trade_payables", -1)):
            opening = rng.randint(0, 60) * 100
            closing = max(0, opening + rng.randint(-20, 20) * 100)
            working.append({"item": item, "opening": opening, "closing": closing})
            changes[item] = -sign * (closing - opening)
        flows = {"share_issue": rng.choice([0, rng.randint(1, 50) * 1000]),
                 "loans_repaid": rng.choice([0, rng.randint(1, 20) * 500]),
                 "dividends_paid": rng.choice([0, rng.randint(1, 20) * 500])}  # fmt: skip
        financing = flows["share_issue"] - flows["loans_repaid"] - flows["dividends_paid"]
        operating_start = profit + (interest if pbt_basis else 0)
        generated = operating_start + depreciation - gain + sum(changes.values())
        operating = generated - interest - tax_paid
        investing = proceeds - purchases
        opening_cash = rng.randint(-20, 40) * 500
        change = operating + investing + financing
        args: dict[str, Any] = {
            "non_cash": [{"kind": "depreciation", "amount": depreciation}],
            "disposal": {"cost": cost, "accumulated_depreciation": cost - carrying, "proceeds": proceeds},
            "non_current_asset_balances": {"opening_cost": opening_cost, "closing_cost": closing_cost},
            "working_capital": working, "interest_paid": interest,
            "tax_balances": {"opening_liability": tax_open, "charge": charge,
                             "closing_liability": tax_open + charge - tax_paid},
            "financing": [{"kind": k, "amount": v} for k, v in flows.items() if v],
            "opening_cash": opening_cash,
        }  # fmt: skip
        if pbt_basis:
            args |= {"profit_before_tax": profit, "finance_costs": interest}
        else:
            args["profit_from_operations"] = profit
        if i % 4 == 0:
            args["closing_cash"] = opening_cash + change
        expect = {"net_cash_from_operating_activities": _money(operating),
                  "net_cash_from_investing_activities": _money(investing),
                  "net_cash_from_financing_activities": _money(financing), "net_change_in_cash": _money(change),
                  "closing_cash": _money(opening_cash + change)}  # fmt: skip
        cases.append(_case(f"cash_flow_{i:03d}", args, expect))
    return _errors_last(cases)


# --- acc_double_entry: control accounts -------------------------------------------------------------------------------


def control_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("control_doc", {"control_account": {
            "kind": "sales_ledger", "opening_debit": 12000, "opening_credit": 300, "ledger_total": 15000,
            "entries": [{"item": "credit_sales", "amount": 80000}, {"item": "receipts", "amount": 75000},
                        {"item": "discounts_allowed", "amount": 1200}, {"item": "irrecoverable_debts", "amount": 500},
                        {"item": "contra", "amount": 400}, {"item": "dishonoured_cheques", "amount": 600}]}},
              {"balance_bd": {"side": "debit", "amount": "15200.00"},
               "reconciliation": {"agrees": False, "difference": "200.00"}}, "hand"),
        _case("control_wrong_item", {"control_account": {"kind": "purchases_ledger", "entries": [
            {"item": "credit_sales", "amount": 1}]}}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(100):
        sales = i % 2 == 0
        kind = "sales_ledger" if sales else "purchases_ledger"
        closing = rng.randint(10, 300) * 50
        opening = rng.randint(10, 300) * 50
        main = rng.randint(100, 2000) * 50
        others = {k: rng.choice([0, rng.randint(1, 40) * 25]) for k in (
            ("discounts_allowed", "irrecoverable_debts", "returns", "contra") if sales else
            ("discounts_received", "returns", "contra"))}  # fmt: skip
        cash = opening + main - sum(others.values()) - closing
        if cash < 0:
            main -= cash
            cash = 0
        entries = [{"item": "credit_sales" if sales else "credit_purchases", "amount": main},
                   {"item": "receipts" if sales else "payments", "amount": cash}]  # fmt: skip
        entries += [{"item": k, "amount": v} for k, v in others.items() if v]
        rng.shuffle(entries)
        error = rng.choice([0, 0, rng.randint(1, 20) * 10])
        account: dict[str, Any] = {"kind": kind, f"opening_{'debit' if sales else 'credit'}": opening,
                                   "entries": entries, "ledger_total": closing - error}  # fmt: skip
        normal = "debit" if sales else "credit"
        expect = {"balance_bd": {"side": normal, "amount": _money(closing)},
                  "reconciliation": {"agrees": not error, "difference": _money(error)}}  # fmt: skip
        cases.append(_case(f"control_{i:03d}", {"control_account": account}, expect))
    return _errors_last(cases)


# --- acc_appraisal ----------------------------------------------------------------------------------------------------


def _factor(rate: int, year: int) -> Fraction:
    """A discount table's factor: 1 / (1 + r)^t printed to three places (half up)."""
    exact = 1 / (1 + Fraction(rate, 100)) ** year
    return Fraction(int(exact * 1000 + Fraction(1, 2)), 1000)


def _exact_npv(receipts: list[int], outlay: int, rate: int) -> Fraction:
    """NPV with the exact factors 1 / (1 + r)^t, as the IRR interpolation uses them."""
    present = (Fraction(f) / (1 + Fraction(rate, 100)) ** t for t, f in enumerate(receipts, 1))
    return sum(present, Fraction(-outlay))


def appraisal_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("appraisal_doc", {"initial_investment": "50,000", "cash_flows": [15000, 20000, 25000, 10000],
                                "discount_rate_percent": 10, "discount_factors": ["0.909", "0.826", "0.751", "0.683"],
                                "arr_basis": "average_investment", "irr_rates": [10, 20]},
              {"payback": {"exact": "2.6", "years": 2, "months": 8},
               "arr": {"percent": {"exact": "20"}, "average_annual_profit": "5000.00", "investment": "25000.00"},
               "npv": {"value": "5760.00", "factors_source": "table"},
               "irr": {"percent": {"value": "15.72"}}}, "hand"),
        _case("appraisal_no_basis", {"initial_investment": 100, "cash_flows": [60, 60], "methods": ["arr"]},
              {"arr": {"status": "unknown", "reason": "convention_missing"}}, "hand"),
        _case("appraisal_not_recovered", {"initial_investment": 100, "cash_flows": [10, 10], "methods": ["payback"]},
              {"payback": {"status": "unknown", "reason": "not_recovered"}}, "hand"),
        _case("appraisal_not_bracketed", {"initial_investment": 100, "cash_flows": [80, 80], "methods": ["irr"],
                                          "irr_rates": [5, 10]},
              {"irr": {"status": "unknown", "reason": "not_bracketed"}}, "hand"),
        _case("appraisal_npv_without_rate", {"initial_investment": 100, "cash_flows": [80], "methods": ["npv"]},
              {"error": 4}, "hand"),
        _case("appraisal_wrong_table_length", {"initial_investment": 100, "cash_flows": [80, 80], "methods": ["npv"],
                                               "discount_rate_percent": 10, "discount_factors": ["0.909"]},
              {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(100):
        years = rng.randint(3, 6)
        flows = [rng.randint(5, 60) * 1000 for _ in range(years)]
        outlay = rng.randint(max(1, sum(flows) // 2000), sum(flows) // 1000) * 1000
        residual = rng.choice([0, 0, rng.randint(1, 10) * 500])
        rate = rng.choice([5, 8, 10, 12, 15])
        low, high = rate, rate + rng.choice([5, 10, 15])
        table = [_factor(rate, t) for t in range(1, years + 1)]
        receipts = [*flows[:-1], flows[-1] + residual]
        basis = rng.choice(["average_investment", "initial_investment"])
        args = {"initial_investment": outlay, "cash_flows": flows, "residual_value": residual,
                "discount_rate_percent": rate,
                "discount_factors": [f"{f.numerator / f.denominator:.3f}" for f in table],
                "irr_rates": [low, high], "arr_basis": basis}  # fmt: skip
        expect: dict[str, Any] = {}
        # Payback: whole years while the cumulative flow stays short, then the fraction of the next year.
        remaining, year = Fraction(outlay), 0
        while year < years and receipts[year] < remaining:
            remaining -= receipts[year]
            year += 1
        if year == years:
            expect["payback"] = {"status": "unknown", "reason": "not_recovered"}
        else:
            exact = year + remaining / receipts[year]
            months = ceil((exact - int(exact)) * 12)
            whole = int(exact) + (months == 12)
            expect["payback"] = {"value": _money(exact), "years": whole, "months": 0 if months == 12 else months}
        profit = Fraction(sum(flows) - (outlay - residual), years)
        invested = Fraction(outlay + residual, 2) if basis == "average_investment" else Fraction(outlay)
        expect["arr"] = {"percent": {"value": _money(profit / invested * 100)}, "basis": basis}
        npv = sum((f * k for f, k in zip(receipts, table, strict=True)), Fraction(0)) - outlay
        expect["npv"] = {"value": _money(npv), "factors_source": "table"}
        n1, n2 = _exact_npv(receipts, outlay, low), _exact_npv(receipts, outlay, high)
        if n1 * n2 > 0 or n1 == n2:
            expect["irr"] = {"status": "unknown", "reason": "not_bracketed"}
        else:
            expect["irr"] = {"percent": {"value": _money(low + n1 / (n1 - n2) * (high - low))}}
        cases.append(_case(f"appraisal_{i:03d}", args, expect))
    return _errors_last(cases)


SETS = ("acc_statements.a_level", "acc_cash_flow", "acc_double_entry.control", "acc_appraisal")


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The VER-34 sets by name (stage S3)."""
    return {
        "acc_statements.a_level": a_level_statement_cases(rng),
        "acc_cash_flow": cash_flow_cases(rng),
        "acc_double_entry.control": control_cases(rng),
        "acc_appraisal": appraisal_cases(rng),
    }
