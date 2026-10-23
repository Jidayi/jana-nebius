---
name: acc-o-accruals-prepayments
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach accrued and prepaid expenses and income for the year's statements
description: "accruals, prepayments, accrued expenses, prepaid expenses, income in advance: turn cash paid or received into the amount for the year and place each balance in the statement of financial position. Not for: irrecoverable debts (acc-o-irrecoverable-debts) or club accounts (acc-o-clubs)."
subject: accounting
levels: [O]
topics: [accruals, prepayments, accrued expenses, prepaid expenses, other payables, other receivables]
kcs:
  - kc.acc.o.accruals_prepayments.accrued_expense
  - kc.acc.o.accruals_prepayments.prepaid_expense
  - kc.acc.o.accruals_prepayments.income_adjustments
  - kc.acc.o.accruals_prepayments.accrual_presentation
curriculum_refs: [ACC-O-09]
prerequisites:
  - kc.acc.o.double_entry.debit_credit_rules
related: [acc-o-irrecoverable-debts, acc-o-clubs]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_statements, acc_double_entry, math_evaluate]
visuals: [financial_statements, t_account]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: time
    unit: month
    min: 0
    max: 24
    context: months of an expense or income owing or paid in advance at a year end
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student works out an expense for the year from the cash paid and the amounts owing or prepaid at each end
  - The student works out income for the year from the cash received and the amounts owing or received in advance
  - The student places each closing accrual or prepayment as a current asset or a current liability
---

# Accruals and prepayments

## When to use

Use when a question gives the cash paid for an expense or received as income and asks for the amount for the
year, when part is still owing or covers the next year, or where an accrual or prepayment appears in the
statement of financial position.

Not for: writing off or allowing for debts (acc-o-irrecoverable-debts) or subscriptions in club accounts
(acc-o-clubs).

## What this skill does not do

- It does not prepare the full income statement; it gives the adjusted figure that goes into it.
- It does not apportion by days; the question gives the amounts or whole months.
- It does not work out the figures itself: the tools give every amount.

## Objectives

1. The student works out an expense for the year from the cash paid and the amounts owing or prepaid at each end.
2. The student works out income for the year from the cash received and the amounts owing or received in advance.
3. The student places each closing accrual or prepayment as a current asset or a current liability.

## Prerequisite probe

- "An expense account rises. Is the entry a debit or a credit?" Expected: a debit.

If it fails, detour to the debit and credit rules, then return.

## Teaching sequence

1. Ask the student to draw the year as a line and mark what was paid, what belongs to last year and what belongs to next year. Done when every amount sits on the line.
2. For an expense, ask the student to start from the cash paid, take off last year's accrual, add this year's accrual, add last year's prepayment and take off this year's prepayment; acc_statements gives the reference figure. Done when the student's expense matches the checked value.
3. For income, ask the same with income owing to the business added and income received in advance taken off; acc_statements gives the reference figure. Done when the student's income matches the checked value.
4. Ask for the year-end entry in the expense or income account; acc_double_entry checks it. Done when the tool reports the entry balanced with every line ok.
5. Ask where each closing balance goes: amounts the business owes are other payables under current liabilities; amounts paid ahead or owed to it are other receivables under current assets. Done when every balance sits on the line acc_statements confirms.

## Hint ladder

1. Orient: "Which part of this payment was used in this year?"
2. Concept: the income statement shows the cost of what was used, and the income earned, in the year, whatever the cash did.
3. First step: write the cash figure and ask whether each adjustment adds to it or takes from it.
4. Worked step: show the first adjustment applied and ask for the second.
5. Full step: show the checked figure and its place in the statement of financial position; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.acc_cash_basis`: uses the cash paid as the expense → "Is the cash paid this year the same as the cost of what was used this year?"
- `mc.acc.o.acc_accrual_subtracted`: takes an amount owing off the cash paid → "The service was used but not yet paid for. Is the true cost more or less than the cash?"
- `mc.acc.o.acc_opening_accrual_added`: adds last year's accrual → "The amount owing at the start was used last year. Which year's cost is it?"
- `mc.acc.o.acc_prepayment_added`: adds a payment for next year → "Part of this payment covers next year. Should this year carry it?"
- `mc.acc.o.acc_opening_ignored`: leaves out last year's prepayment → "Some of this year's service was paid for last year. Has it been counted?"
- `mc.acc.o.acc_adjustment_as_total`: gives only the amount owing as the income → "Is the amount owing the whole income for the year, or only the part not yet received?"
- `mc.acc.o.acc_income_adjustment_reversed`: subtracts rent owed to the business → "Rent owed to the business was earned this year. Does it add to the income or take from it?"
- `mc.acc.o.acc_accrual_as_asset`: shows wages owing as an asset → "Wages owing are a debt of the business. Is a debt an asset?"
- `mc.acc.o.acc_prepayment_as_liability`: shows a prepayment as a liability → "The business paid in advance. Who now owes a service to whom?"
- `mc.acc.o.acc_adjustment_in_is_only`: leaves the year-end balance out of the statement of financial position → "If the wages are still owed at the year end, where does that debt appear?"
- `mc.acc.o.acc_prepayment_as_non_current`: lists prepaid insurance as non-current → "Will the prepaid insurance be used up within a year?"

## Confidence and escalation

- Two wrong signs in a row: switch to a T-account for the expense with opening and closing balances shown.
- Three failures on sides: detour to the debit and credit rules, then return.
- An arrangement the pack does not cover, such as rent paid in goods: save it as a question for a teacher.

## Worked exchange

> Tutor: Rent paid during the year was 5,400. At the start of the year 300 was owing for last year, and at the end 450 is owing. What is the rent expense for the year, and where does the 450 appear?
> Student: 5,400 + 300 + 450 = 6,150.
> Tutor: The 300 owing at the start was for last year's rent. Which year's cost is it?
> Student: Last year's. So it comes off what was paid: 5,400 − 300 + 450 = 5,550.
> Tutor: Right (checked with the statements tool). Where does the 450 go in the statement of financial position?
> Student: Under current liabilities as other payables, because the business still owes it.
> Tutor: Correct.

## Verification checklist

- Every adjusted expense and income figure came from acc_statements.
- Each year-end entry passed acc_double_entry.
- Closing accruals of expenses and income in advance are other payables; prepaid expenses and income owing are other receivables.
- Figures are shown to 2 decimal places when they have cents, rounded half away from zero.
