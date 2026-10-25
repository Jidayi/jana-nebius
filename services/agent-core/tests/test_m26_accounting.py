"""M26.a: A level accounting (VER-34): partnership, company, manufacturing and incomplete records in `acc_statements`,
cash flow statements (`acc_cash_flow`), control accounts in `acc_double_entry` and investment appraisal
(`acc_appraisal`), through the real worker boundary and against the S3 golden sets."""

from jana_tools import golden
from test_m12d_accounting import call

SETS = ("acc_statements.a_level", "acc_cash_flow", "acc_double_entry.control", "acc_appraisal")
CASH_FLOW = {
    "profit_from_operations": 40000, "non_cash": [{"kind": "depreciation", "amount": 8000}],
    "disposal": {"cost": 10000, "accumulated_depreciation": 6000, "proceeds": 3000},
    "non_current_asset_balances": {"opening_cost": 100000, "closing_cost": 120000},
    "working_capital": [{"item": "inventory", "opening": 10000, "closing": 12000},
                        {"item": "trade_receivables", "opening": 8000, "closing": 7000},
                        {"item": "trade_payables", "opening": 5000, "closing": 6500}],
    "interest_paid": 2000, "tax_balances": {"opening_liability": 6000, "charge": 9000, "closing_liability": 7000},
    "financing": [{"kind": "share_issue", "amount": 20000}, {"kind": "dividends_paid", "amount": 10000}],
    "opening_cash": 5000,
}  # fmt: skip


def ver34_a_level_accounting_golden() -> None:
    # Investment appraisal: payback in years and months (rounded up), ARR on the stated basis, NPV from the printed
    # three-place table, IRR by interpolation between two rates.
    appraisal = call("acc_appraisal", {"initial_investment": "50,000", "cash_flows": [15000, 20000, 25000, 10000],
                                       "discount_rate_percent": 10, "irr_rates": [10, 20],
                                       "discount_factors": ["0.909", "0.826", "0.751", "0.683"]},
                     {"acc.arr_basis": {"value": "average_investment", "source": "pack"}})["result"]  # fmt: skip
    value = appraisal["value"]
    assert value["payback"] == {"exact": "2.6", "value": "2.60", "years": 2, "months": 8}
    assert value["arr"]["percent"]["value"] == "20.00" and value["arr"]["basis_source"] == "pack"
    assert value["npv"]["value"] == "5760.00" and value["npv"]["factors_source"] == "table"
    assert value["irr"]["percent"]["value"] == "15.72" and value["irr"]["npvs"] == ["5778.29", "-4320.99"]
    # Without a stated ARR basis the figure is unknown rather than one board's rule.
    bare = call("acc_appraisal", {"initial_investment": 100, "cash_flows": [60, 60], "methods": ["arr"]})["result"]
    assert bare["value"]["arr"]["reason"] == "convention_missing" and bare["check"]["confidence"] == "undecided"

    # Partnership: interest on drawings added, salary and interest on capital appropriated, the residual shared 3:2;
    # a partner who drew more than their appropriations ends with a debit current account, flagged.
    partners = [{"id": "a", "name": "Ali", "capital": 40000, "drawings": 20000, "interest_on_drawings": 500,
                 "profit_share": 3, "current_account_opening": 2000},
                {"id": "b", "name": "Bola", "capital": 20000, "salary": 8000, "drawings": 30000,
                 "interest_on_drawings": 300, "profit_share": 2, "current_account_opening": "(1,000)"}]  # fmt: skip
    partnership = call("acc_statements", {"form": "partnership", "partnership": {
        "profit_for_the_year": 50000, "interest_on_capital_percent": 5, "partners": partners},
        "student": {"statement": "appropriation_account", "lines": [
            {"line": "residual_profit", "amount": 39800}, {"line": "a:share", "amount": 23880},
            {"line": "b:share", "amount": 15920}]}})["result"]  # fmt: skip
    value = partnership["value"]
    assert value["residual_profit"] == "39800.00" and value["shares"] == {"a": "23880.00", "b": "15920.00"}
    assert value["current_accounts"] == {"a": {"amount": "7380.00", "side": "credit"},
                                         "b": {"amount": "6380.00", "side": "debit"}}  # fmt: skip
    assert [w["code"] for w in partnership["warnings"]] == ["implausible"]
    marks = {m["id"]: m["verdict"] for m in value["student"]["lines"]}
    assert marks["residual_profit"] == marks["a:share"] == marks["b:share"] == "ok"

    # Cash flows: purchases, tax paid and the disposal's loss derived from the balances, each in the working; a
    # student's later subtotal that follows from their own wrong depreciation figure is own_figure, not wrong.
    student = [{"line": "depreciation", "amount": 9000}, {"line": "cash_generated_from_operations", "amount": 50500}]
    cash = call("acc_cash_flow", {**CASH_FLOW, "student": {"lines": student}})["result"]
    value = cash["value"]
    assert value["net_cash_from_operating_activities"] == "39500.00" and value["closing_cash"] == "27500.00"
    lines = {line["id"]: line["amount"] for line in value["lines"]}
    assert lines["purchase_of_non_current_assets"] == "-30000.00" and lines["tax_paid"] == "-8000.00"
    assert lines["loss_on_disposal"] == "1000.00" and lines["change_in_inventory"] == "-2000.00"
    assert [w["label"] for w in cash["working"]] == ["disposal", "purchases", "tax paid"]
    verdicts = {m["id"]: m["verdict"] for m in value["student"]["lines"]}
    assert verdicts["depreciation"] == "wrong" and verdicts["cash_generated_from_operations"] == "own_figure"
    assert value["student"]["first_divergent"]["id"] == "profit_from_operations"  # not written: missing
    # A stated closing balance the flows do not reach is unknown with the difference: no flow is invented.
    short = call("acc_cash_flow", {**CASH_FLOW, "closing_cash": 28000})["result"]["value"]
    assert short == {"status": "unknown", "reason": "does_not_reconcile", "computed_closing": "27500.00",
                     "stated_closing": "28000.00", "difference": "500.00"}  # fmt: skip

    # Control accounts: the balance from the period's totals, reconciled with the list of ledger balances.
    control = call("acc_double_entry", {"control_account": {
        "kind": "sales_ledger", "opening_debit": 12000, "opening_credit": 300, "ledger_total": 15000,
        "entries": [{"item": "credit_sales", "amount": 80000}, {"item": "receipts", "amount": 75000},
                    {"item": "discounts_allowed", "amount": 1200}, {"item": "irrecoverable_debts", "amount": 500},
                    {"item": "contra", "amount": 400}, {"item": "dishonoured_cheques", "amount": 600}]}})  # fmt: skip
    value = control["result"]["value"]
    assert value["balance_bd"] == {"side": "debit", "amount": "15200.00"} and value["total"] == "92600.00"
    assert value["reconciliation"] == {"ledger_total": "15000.00", "agrees": False, "difference": "200.00"}
    wrong_side = call("acc_double_entry", {"control_account": {"kind": "purchases_ledger", "entries": [
        {"item": "credit_sales", "amount": 1}]}})  # fmt: skip
    assert wrong_side["error"]["code"] == 4

    # A sole trader's statements are unchanged by the new forms (VER-23), and a form without its data is refused.
    sole = call("acc_statements", {"trial_balance": [{"account": "Sales", "role": "revenue", "credit": 10},
                                                     {"account": "Cash", "role": "cash", "debit": 10}]})  # fmt: skip
    assert sole["result"]["value"]["profit_for_the_year"] == "10.00"
    assert "manufacturing" in call("acc_statements", {"form": "manufacturing"})["error"]["message"]

    # The A level golden sets (stage S3) pass at 100%.
    data = golden.load()
    for name in SETS:
        assert data[name]["stage"] == "S3" and len(data[name]["cases"]) >= 100, name
        failures = [c["id"] for c in data[name]["cases"]
                    if not golden.matches(golden.run(c, data[name]["tool"]), c["expect"])]  # fmt: skip
        assert failures == [], (name, failures)
