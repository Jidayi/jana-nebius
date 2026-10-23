---
name: acc-o-accounting-equation
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach the accounting equation, its elements and how transactions change it
description: "accounting equation, assets, liabilities, capital, users of accounts: sort each item into its class, find a missing figure and trace how a transaction moves both sides. Not for: debit and credit entries (acc-o-double-entry) or accounting concepts (acc-o-concepts)."
subject: accounting
levels: [O]
topics: [accounting equation, assets, liabilities, capital, users of accounts, classification]
kcs:
  - kc.acc.o.accounting_equation.purpose_and_users
  - kc.acc.o.accounting_equation.classify_elements
  - kc.acc.o.accounting_equation.apply_equation
  - kc.acc.o.accounting_equation.effect_of_transactions
curriculum_refs: [ACC-O-01]
prerequisites: []
related: [acc-o-double-entry, acc-o-concepts]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student states what accounting records and what one named user group wants from the accounts
  - The student classifies each item as an asset, a liability, capital, income or an expense
  - The student finds a missing figure from assets = capital + liabilities
  - The student shows which items a transaction changes, in which direction, and that the equation still balances
---

# The accounting equation

## When to use

Use when a question asks why businesses keep accounts, who reads them, whether an item is an asset, a liability,
capital, income or an expense, for a missing total in assets = capital + liabilities, or for the effect of one
transaction on the equation.

Not for: writing debit and credit entries (acc-o-double-entry) or the accounting concepts (acc-o-concepts).

## What this skill does not do

- It does not post anything to ledger accounts; it works with totals only.
- It does not prepare an income statement or a statement of financial position.
- It does not invent figures: the question gives every amount and the tools give every total.

## Objectives

1. The student states what accounting records and what one named user group wants from the accounts.
2. The student classifies each item as an asset, a liability, capital, income or an expense.
3. The student finds a missing figure from assets = capital + liabilities.
4. The student shows which items a transaction changes, in which direction, and that the equation still balances.

## Prerequisite probe

- "Which of these does a business own: a delivery van or a bank loan?" Expected: the delivery van.
- "What is 12,000 − 4,500?" Expected: 7,500 (checked with math_evaluate).

If either fails, sort a few everyday items into "owned" and "owed" with the student, then return.

## Teaching sequence

1. Ask what the accounts are for and what one named user, such as a lender or the owner, most wants to know. Done when the student names that user's main interest.
2. Ask the student to label each item as owned by the business, owed to outsiders, or owed to the owner. Done when every item in the question has a label.
3. Ask for the class of each item; the class acc_double_entry gives for the account is the reference. Done when each item has one class that matches the tool.
4. Ask the student to write assets = capital + liabilities and rearrange it for the unknown. Done when the rearranged equation is on the board.
5. Ask for the totals and the missing figure; the math_evaluate result is the reference value. Done when the student's figure matches the checked value.
6. For a transaction, ask which two items change, by how much and in which direction. Done when each change has an item, an amount and a direction.
7. Ask for the new totals on both sides; math_evaluate gives the reference totals. Done when the checked assets equal the checked capital plus liabilities.

## Hint ladder

1. Orient: "Which items does the business own, and which does it owe?"
2. Concept: the owner's claim is what is left of the assets after every outside debt is paid.
3. First step: write assets = capital + liabilities and ask which term is unknown.
4. Worked step: show the rearranged equation with the numbers in place and ask for the result.
5. Full step: show the checked figure and the balanced equation; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.ae_purpose_cash_only`: thinks the accounts record only cash → "If the business owes a supplier but has paid nothing yet, should the accounts show the debt?"
- `mc.acc.o.ae_users_interest_confused`: gives one user another user's interest → "A bank lending money worries most about one thing. Will the loan be repaid?"
- `mc.acc.o.ae_expense_as_asset`: calls rent paid an asset → "Once the month is over, does the rent paid leave the business owning anything?"
- `mc.acc.o.ae_liability_as_asset`: calls a loan received an asset → "Cash came in with the loan, but to whom does the business now owe that money?"
- `mc.acc.o.ae_loan_as_income`: calls a loan income → "Did the business sell anything to get this money, or must it hand it back later?"
- `mc.acc.o.ae_capital_as_owner_money`: treats capital as a debt to outsiders → "Is capital owed to a lender, or to the owner of the business?"
- `mc.acc.o.ae_equation_signs_wrong`: adds liabilities to assets to get capital → "If the business owns 10,000 and owes 3,000, how much of it belongs to the owner?"
- `mc.acc.o.ae_liability_omitted`: subtracts only the trade payables → "Have you taken off every amount owed, including the loan?"
- `mc.acc.o.ae_asset_swap_confused`: thinks buying a machine for cash changes total assets → "One asset went down and another went up by the same amount. Did the total change?"
- `mc.acc.o.ae_credit_purchase_capital`: says buying goods on credit changes capital → "Buying on credit creates a debt to whom, the owner or the supplier?"
- `mc.acc.o.ae_drawings_as_liability_change`: says drawings cut liabilities → "When the owner takes cash out, does the business owe outsiders less, or does the owner's claim fall?"
- `mc.acc.o.ae_effect_signs`: reverses the direction of a change → "Did that item go up or down, and which did you write?"

## Confidence and escalation

- Two wrong classes in a row: switch to three columns headed owned, owed to outsiders and owed to the owner.
- Three failures on the missing figure: give a version with a single liability, then add the second one back.
- An item the pack does not cover, such as a local savings group payment: save it as a question for a teacher.

## Worked exchange

> Tutor: A business has assets of 18,000, trade payables of 2,500 and a bank loan of 5,000. What is its capital? Then the owner takes 1,000 cash for personal use: what changes?
> Student: Capital is 18,000 + 2,500 + 5,000, so 25,500.
> Tutor: The payables and the loan are owed to outsiders. Do they belong to the owner?
> Student: No. So capital is 18,000 − 2,500 − 5,000 = 10,500.
> Tutor: Right (checked with the maths tool). Now the drawings of 1,000: which items change?
> Student: Cash falls by 1,000 and capital falls by 1,000, so assets are 17,000 and capital is 9,500.
> Tutor: Correct: 17,000 = 9,500 + 2,500 + 5,000, so the equation still balances (checked with the maths tool).

## Verification checklist

- Each class matches the class acc_double_entry gives for that account in the chart of accounts.
- Every total and missing figure came from math_evaluate.
- Assets equal capital plus liabilities before and after each transaction.
- Directions of change are stated as rise or fall for each item, never left implied.
