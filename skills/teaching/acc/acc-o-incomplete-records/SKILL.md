---
name: acc-o-incomplete-records
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach finding capital, profit and missing figures from incomplete records
description: "Incomplete records, statement of affairs, profit from change in capital, missing credit sales or purchases, margin and mark-up: rebuild the missing figure. Not for: control accounts (acc-o-control-accounts) or ratio analysis (acc-o-ratios)."
subject: accounting
levels: [O]
topics: [incomplete records, statement of affairs, change in capital, missing figures, credit sales, credit purchases, margin, mark-up]
kcs:
  - kc.acc.o.incomplete_records.statement_of_affairs
  - kc.acc.o.incomplete_records.profit_from_capital
  - kc.acc.o.incomplete_records.missing_credit_figures
  - kc.acc.o.incomplete_records.margin_markup_use
curriculum_refs: [ACC-O-14]
prerequisites:
  - kc.acc.o.accounting_equation.apply_equation
  - kc.acc.o.sole_trader_statements.closing_capital
  - kc.acc.o.control_accounts.sales_ledger_control
  - kc.acc.o.double_entry.balance_account
  - kc.acc.o.ratios.mark_up
related: [acc-o-control-accounts, acc-o-ratios, acc-o-sole-trader-statements]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, acc_statements, acc_ratios, math_evaluate]
visuals: [t_account, financial_statements]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: mark_up
    unit: percent
    min: 5
    max: 200
    context: mark-up on cost stated for a trader's goods
  - quantity: gross_margin
    unit: percent
    min: 5
    max: 80
    context: gross margin on revenue stated for a trader's goods
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds capital from a statement of affairs as assets less liabilities
  - The student finds profit from the change in capital, adjusted for drawings and capital introduced
  - The student rebuilds credit sales, credit purchases or a missing trading figure that the tools confirm
---

# Incomplete records

## When to use

Use when a trader has not kept full double-entry records and a question asks for capital from a statement of
affairs, profit from the change in capital, credit sales or credit purchases from cash and balances, or a missing
revenue or cost of sales from a stated margin or mark-up.

Not for: preparing control accounts as such (use acc-o-control-accounts) or working out and judging ratios (use
acc-o-ratios).

## What this skill does not do

- It does not invent missing figures; every figure is rebuilt from what the question gives.
- It does not judge whether the trader's records are honest or complete.
- It does not teach the margin and mark-up formulas from scratch; it uses them.

## Objectives

1. The student finds capital from a statement of affairs as assets less liabilities.
2. The student finds profit from the change in capital, adjusted for drawings and capital introduced.
3. The student rebuilds credit sales, credit purchases or a missing trading figure that the tools confirm.

## Prerequisite probe

- "Assets are $15,000 and liabilities are $4,000. What is the capital?" Expected: $11,000.
- "Goods cost $200 and are sold at a mark-up of 25%. What is the selling price?" Expected: $250.

If either fails, detour to the accounting equation or to mark-up, then return.

## Teaching sequence

1. Ask the student to list the assets and the liabilities separately, then take liabilities from assets; acc_double_entry checks the balance. Done when the capital matches.
2. Ask for profit: closing capital less opening capital, plus drawings, less capital introduced; the acc_statements result is the reference value. Done when the student's profit matches it.
3. Ask for credit sales from a receivables account: receipts from credit customers plus closing balance less opening balance; acc_double_entry checks the account. Done when the balancing figure matches.
4. Ask the student to name the base of the percentage, cost for a mark-up and revenue for a margin, then find the missing figure; acc_ratios gives the reference. Done when the figure and its base match.
5. Check any side sum with math_evaluate. Done when every figure shown has a tool check.

## Hint ladder

1. Orient: "Which figure is missing, and which account or statement would show it?"
2. Concept: capital rises with profit and capital paid in, and falls with drawings.
3. First step: write closing capital less opening capital and ask what else changed capital this year.
4. Worked step: show the increase with drawings added back and ask about capital introduced.
5. Full step: show the checked figure; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.ir_soa_assets_only`: gives total assets as the capital → "Does the trader own all of these assets outright, or are some owed for?"
- `mc.acc.o.ir_soa_item_misclassified`: lists a loan among the assets → "Does the business have this loan, or owe it?"
- `mc.acc.o.ir_change_only`: takes the increase in capital as the profit → "Did anything other than profit change the capital this year?"
- `mc.acc.o.ir_drawings_subtracted`: subtracts drawings from the increase → "Without the drawings, would capital have ended higher or lower?"
- `mc.acc.o.ir_capital_introduced_added`: adds capital paid in to the profit → "Did the money the owner paid in come from trading?"
- `mc.acc.o.ir_receipts_only`: takes cash from customers as the credit sales → "Do all credit sales of the year turn into cash within the year?"
- `mc.acc.o.ir_opening_closing_swapped`: subtracts the closing balance → "Is the amount still owed at the end a sale of this year that is not yet paid?"
- `mc.acc.o.ir_cash_sales_included`: adds cash sales to credit sales → "Which sales pass through the receivables account?"
- `mc.acc.o.ir_markup_subtracted`: takes the mark-up off the cost → "Is the selling price above or below the cost?"
- `mc.acc.o.ir_percent_of_wrong_base`: gives the gross profit as the revenue → "Is this figure the whole selling price, or only the profit part of it?"

## Confidence and escalation

- Two failures on profit from capital: switch to a capital T-account and post each change.
- Three failures on credit sales: detour to the sales ledger control account, then return.
- A margin given where a mark-up is needed: ask for the base before any arithmetic.

## Worked exchange

> Tutor: A trader's capital was $20,000 at the start of the year and $26,500 at the end. Drawings were $7,200, and the trader paid in $3,000 of extra capital. What was the profit for the year?
> Student: Capital went up by 6,500, so the profit is 6,500.
> Tutor: The owner took out $7,200 during the year. Without the drawings, would capital have ended higher or lower?
> Student: Higher, so I add them back: 6,500 + 7,200 = 13,700.
> Tutor: Good. Did all of that increase come from trading?
> Student: No, 3,000 was paid in, so the profit is 13,700 − 3,000 = 10,700.
> Tutor: Right (checked with the statements tool).

## Verification checklist

- Every figure came from the question or from an acc_double_entry, acc_statements, acc_ratios or math_evaluate check.
- Drawings are added back and capital introduced is taken out when finding profit.
- Credit sales use credit customers' receipts and balances only, never cash sales.
- A mark-up is on cost and a margin is on revenue, as the tool's formula states.
