---
name: acc-o-clubs
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach the accounts of clubs and societies from receipts to surplus
description: "Clubs and societies, receipts and payments account, income and expenditure account, subscriptions, accumulated fund, surplus or deficit: adjust cash figures to the year. Not for: a trader's statements (acc-o-sole-trader-statements)."
subject: accounting
levels: [O]
topics: [clubs and societies, receipts and payments account, income and expenditure account, subscriptions, accumulated fund, surplus, deficit]
kcs:
  - kc.acc.o.clubs.club_statements
  - kc.acc.o.clubs.subscriptions
  - kc.acc.o.clubs.accumulated_fund
  - kc.acc.o.clubs.surplus_deficit
curriculum_refs: [ACC-O-13]
prerequisites:
  - kc.acc.o.double_entry.record_cash_transactions
  - kc.acc.o.accruals_prepayments.income_adjustments
  - kc.acc.o.accounting_equation.apply_equation
  - kc.acc.o.sole_trader_statements.profit_for_year
related: [acc-o-sole-trader-statements, acc-o-accruals-prepayments]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, acc_statements, math_evaluate]
visuals: [t_account, financial_statements]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student explains how a receipts and payments account differs from an income and expenditure account
  - The student works out subscriptions income and the accumulated fund that the tools confirm
  - The student finds the surplus or deficit for the year and names it correctly
---

# Accounts of clubs and societies

## When to use

Use when a question is about a club or society and asks how its receipts and payments account differs from its
income and expenditure account, or asks for subscriptions income, the accumulated fund, or the surplus or deficit
for the year.

Not for: a trader's income statement and statement of financial position (use acc-o-sole-trader-statements) or
accruals and prepayments on their own (use acc-o-accruals-prepayments).

## What this skill does not do

- It does not cover a club's trading activity such as a bar in detail; it uses the bar profit the question gives.
- It does not work out depreciation; it uses the figure given.
- It does not treat life membership or entrance fees beyond what the question states.

## Objectives

1. The student explains how a receipts and payments account differs from an income and expenditure account.
2. The student works out subscriptions income and the accumulated fund that the tools confirm.
3. The student finds the surplus or deficit for the year and names it correctly.

## Prerequisite probe

- "Rent receivable for the year is $1,200 and $100 of it is still owed at the year end. How much rent was received in cash?" Expected: $1,100.
- "Assets are $8,000 and liabilities are $1,500. What is the capital?" Expected: $6,500.

If either fails, detour to income adjustments or to the accounting equation, then return.

## Teaching sequence

1. Ask whether the figures come from a summary of cash (receipts and payments) or from the year's income and expenditure. Done when the student names which and why.
2. Ask for subscriptions income: cash received, less opening arrears, plus opening advances, plus closing arrears, less closing advances; the acc_statements result is the reference value. Done when the student's figure matches it.
3. Ask for the accumulated fund at the start: assets, including subscriptions owed, less liabilities, including subscriptions paid in advance; acc_double_entry checks the balance. Done when the fund matches.
4. Ask the student to list the year's income and expenditure, with depreciation and without the cost of new equipment; acc_statements gives the surplus or deficit as the reference. Done when the figure and its name match.
5. Check any side sum with math_evaluate. Done when every figure shown has a tool check.

## Hint ladder

1. Orient: "Is this figure the cash of the year, or the income that belongs to the year?"
2. Concept: subscriptions income is what members owe for this year, whenever they pay it.
3. First step: draw the subscriptions account with the opening and closing arrears and advances, and ask where the cash goes.
4. Worked step: show the cash with the opening items adjusted and ask for the closing adjustments.
5. Full step: show the checked figure; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.club_rp_shows_surplus`: reads a surplus off the receipts and payments account → "Does that account end with a profit figure, or with the cash left?"
- `mc.acc.o.club_rp_as_ie`: takes the cash figures as the year's income → "Does every amount paid this year belong to this year?"
- `mc.acc.o.club_receipts_only`: takes subscriptions received as the income → "Did some members pay for another year, or not pay yet?"
- `mc.acc.o.club_opening_items_ignored`: adjusts only for year-end arrears and advances → "Some cash this year paid off last year's arrears. Whose income was that?"
- `mc.acc.o.club_arrears_reversed`: subtracts arrears owed at the end → "Members still owe this for the year. Is it income of the year or not?"
- `mc.acc.o.club_fund_as_cash`: thinks the accumulated fund is cash → "Which assets and liabilities make up the fund, and is cash only one of them?"
- `mc.acc.o.club_advance_as_asset`: shows subscriptions in advance as an asset → "Does the club owe members a year of membership, or do they owe the club?"
- `mc.acc.o.club_fund_signs`: adds liabilities to assets → "Does what the club owes increase or reduce what belongs to the members?"
- `mc.acc.o.club_capital_items_in_ie`: charges new equipment in full as expenditure → "Will the equipment be used for more than this year?"
- `mc.acc.o.club_depreciation_omitted`: leaves out depreciation → "Did the club's equipment lose any value through use this year?"
- `mc.acc.o.club_surplus_deficit_reversed`: calls an excess of expenditure a surplus → "Was the income more than the expenditure, or less?"

## Confidence and escalation

- Two failures on subscriptions: switch to the subscriptions T-account and post each item.
- Three failures on the accumulated fund: detour to the accounting equation, then return.
- A local practice the tutor cannot settle, such as how a club treats life membership: save it for human help.

## Worked exchange

> Tutor: A club received $9,600 in subscriptions during the year. At the start, members owed $400 and had paid $300 in advance. At the end, members owed $500 and had paid $700 in advance. What is the subscriptions income for the year?
> Student: 9,600 + 500 − 700 = 9,400.
> Tutor: Part of the cash paid off the $400 owed from last year. Does that belong to this year?
> Student: No. And the $300 paid last year is for this year, so 9,600 − 400 + 300 + 500 − 700 = 9,300.
> Tutor: Right (checked with the statements tool). Where do the $500 and the $700 appear at the year end?
> Student: The 500 is a current asset and the 700 is a current liability.
> Tutor: Correct.

## Verification checklist

- Every figure came from the question or from an acc_statements, acc_double_entry or math_evaluate check.
- Subscriptions income is adjusted for opening and closing arrears and advances.
- New equipment is an asset, and depreciation is in the expenditure.
- The result is named a surplus when income is more than expenditure and a deficit when it is less.
