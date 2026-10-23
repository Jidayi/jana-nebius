---
name: acc-o-sole-trader-statements
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach a sole trader's income statement and statement of financial position
description: "Income statement, cost of sales, gross profit, profit for the year, statement of financial position, working capital, closing capital: build each figure in layout order. Not for: partnerships (acc-o-partnerships) or clubs (acc-o-clubs)."
subject: accounting
levels: [O]
topics: [income statement, cost of sales, gross profit, profit for the year, statement of financial position, working capital, closing capital, sole trader]
kcs:
  - kc.acc.o.sole_trader_statements.cost_of_sales
  - kc.acc.o.sole_trader_statements.gross_profit
  - kc.acc.o.sole_trader_statements.profit_for_year
  - kc.acc.o.sole_trader_statements.sofp_sections
  - kc.acc.o.sole_trader_statements.working_capital
  - kc.acc.o.sole_trader_statements.closing_capital
curriculum_refs: [ACC-O-11]
prerequisites:
  - kc.acc.o.double_entry.record_credit_transactions
  - kc.acc.o.accruals_prepayments.accrued_expense
  - kc.acc.o.accounting_equation.classify_elements
  - kc.acc.o.double_entry.record_owner_transactions
related: [acc-o-partnerships, acc-o-clubs, acc-o-accruals-prepayments, acc-o-depreciation]
pedagogy: [pedagogy-worked-example-fade]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_statements, math_evaluate]
visuals: [financial_statements]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: worked_example
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student works out cost of sales, gross profit and profit for the year in the income statement order
  - The student places each item in the correct section of the statement of financial position
  - The student finds net current assets and closing capital that the statements tool confirms
---

# Financial statements of a sole trader

## When to use

Use when a question gives a trial balance or a list of balances for a sole trader and asks for cost of sales, gross
profit, profit for the year, the sections of the statement of financial position, net current assets or closing
capital.

Not for: sharing profit between partners (use acc-o-partnerships), club accounts (use acc-o-clubs), or working out
an accrual, a prepayment or depreciation itself (use acc-o-accruals-prepayments or acc-o-depreciation).

## What this skill does not do

- It does not work out depreciation, accruals or the allowance; it uses the figures those skills give.
- It does not prepare statements for partnerships, clubs or companies.
- It does not choose a layout: the pack's statement of financial position shows assets, then capital and liabilities.

## Objectives

1. The student works out cost of sales, gross profit and profit for the year in the income statement order.
2. The student places each item in the correct section of the statement of financial position.
3. The student finds net current assets and closing capital that the statements tool confirms.

## Prerequisite probe

- "Is a bank loan repayable in five years an asset, a liability or capital?" Expected: a liability (non-current).
- "Rent of $200 is owed at the year end. Does the rent expense go up or down?" Expected: up, by $200.

If either fails, detour to classifying elements or to accrued expenses, then return.

## Teaching sequence

1. Ask for net revenue: revenue less sales returns. Done when the student states the figure.
2. Ask for cost of sales: opening inventory, plus purchases less purchases returns, plus carriage inwards, less closing inventory; the acc_statements result is the reference value. Done when the student's figure matches it.
3. Ask for gross profit, then add other income and take off expenses for profit for the year; acc_statements gives the reference. Done when both figures match.
4. Ask the student to sort each balance into non-current assets, current assets, capital, non-current liabilities or current liabilities. Done when every item has one section.
5. Ask for total current assets, total current liabilities and net current assets; acc_statements gives the reference. Done when all three match.
6. Ask for closing capital: opening capital plus capital introduced plus profit, less drawings; acc_statements gives the reference. Done when the statement balances in the tool.

## Hint ladder

1. Orient: "Which line of the statement are we on, and what comes just before it?"
2. Concept: cost of sales is the cost of the goods sold in the year, not of everything bought.
3. First step: write the cost of sales lines in order and ask for the first subtotal.
4. Worked step: show the goods available for sale and ask what happens to the closing inventory.
5. Full step: show the checked line; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.cos_closing_added`: adds closing inventory to cost of sales → "Were the goods still on the shelves at the year end sold this year?"
- `mc.acc.o.cos_carriage_inwards_omitted`: puts carriage inwards with the expenses → "Is this the cost of getting goods in, or of sending them to customers?"
- `mc.acc.o.cos_returns_added`: adds purchases returns to purchases → "If goods go back to the supplier, has the business bought more or less?"
- `mc.acc.o.gp_sales_returns_ignored`: uses revenue before sales returns → "Did the business keep the money for the goods customers sent back?"
- `mc.acc.o.gp_expenses_deducted`: takes wages off before gross profit → "Is gross profit before or after the running expenses?"
- `mc.acc.o.pfy_drawings_deducted`: treats drawings as an expense → "Did the business spend this money to earn its revenue, or did the owner take it?"
- `mc.acc.o.pfy_other_income_omitted`: leaves out rent or discount received → "Is there any income that did not come from selling goods?"
- `mc.acc.o.pfy_capital_spending_deducted`: charges a new vehicle in full as an expense → "Will the vehicle still be used next year, and how is that use charged?"
- `mc.acc.o.sofp_overdraft_as_asset`: adds an overdraft to current assets → "Does the business have this money, or does it owe it to the bank?"
- `mc.acc.o.sofp_term_confused`: puts every loan under non-current liabilities → "When must this loan be repaid: within the next year, or later?"
- `mc.acc.o.wc_non_current_included`: counts equipment in current assets → "Will the equipment turn into cash within the next year in normal trading?"
- `mc.acc.o.cc_drawings_added`: adds drawings to capital → "Does the owner's stake grow or shrink when the owner takes money out?"

## Confidence and escalation

- Two failures on cost of sales: switch to a worked example with smaller numbers, then fade it.
- Three failures on sorting items: detour to classifying elements, then return.
- A statement that does not balance: check closing capital before any other line.

## Worked exchange

> Tutor: Revenue $48,000; sales returns $1,000; opening inventory $5,000; purchases $30,000; purchases returns $800; carriage inwards $600; closing inventory $6,200. What is the cost of sales?
> Student: 5,000 + 30,000 − 800 + 600 + 6,200 = 41,000.
> Tutor: The $6,200 of goods were still on the shelves at the year end. Were they sold this year?
> Student: No, so they come off: 5,000 + 30,000 − 800 + 600 − 6,200 = 28,600.
> Tutor: Right (checked with the statements tool). Now the gross profit?
> Student: Net revenue is 47,000, so gross profit is 47,000 − 28,600 = 18,400.
> Tutor: Correct (checked with the statements tool).

## Verification checklist

- Every figure came from the question or from an acc_statements or math_evaluate check.
- Carriage outwards and wages are expenses, not part of cost of sales.
- Drawings reduce capital and never appear as an expense or a liability.
- The statement of financial position balances in the tool, in the pack's layout and terms.
