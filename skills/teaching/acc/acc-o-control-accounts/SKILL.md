---
name: acc-o-control-accounts
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach sales and purchases ledger control accounts and their sources
description: "control accounts, sales ledger control, purchases ledger control, contra: name each figure's source and side, leave out cash items and find the closing balance. Not for: day books (acc-o-source-documents) or writing off debts (acc-o-irrecoverable-debts)."
subject: accounting
levels: [O]
topics: [control accounts, sales ledger control, purchases ledger control, contra, set-off]
kcs:
  - kc.acc.o.control_accounts.control_purpose
  - kc.acc.o.control_accounts.control_sources
  - kc.acc.o.control_accounts.sales_ledger_control
  - kc.acc.o.control_accounts.purchases_ledger_control
curriculum_refs: [ACC-O-06]
prerequisites:
  - kc.acc.o.source_documents.post_day_book_totals
  - kc.acc.o.double_entry.balance_account
related: [acc-o-source-documents, acc-o-irrecoverable-debts]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
visuals: [t_account]
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
  - The student explains what a control account checks and what it cannot prove
  - The student names the source and the side of each figure in a control account
  - The student works out the closing balance of a sales or purchases ledger control account
---

# Control accounts

## When to use

Use when a question asks why a business keeps control accounts, where a figure in one comes from, which side it
goes on, or for the closing balance of a sales ledger control account or a purchases ledger control account.

Not for: writing up the day books themselves (acc-o-source-documents) or deciding which debts to write off
(acc-o-irrecoverable-debts).

## What this skill does not do

- It does not post to individual customers' or suppliers' accounts; it works with totals.
- It does not treat credit balances on both sides of one control account.
- It does not add up the figures itself: the tools give every total.

## Objectives

1. The student explains what a control account checks and what it cannot prove.
2. The student names the source and the side of each figure in a control account.
3. The student works out the closing balance of a sales or purchases ledger control account.

## Prerequisite probe

- "Which book of prime entry first records credit sales?" Expected: the sales journal.
- "An account has debits of 7,300 and credits of 6,100. What is the balance?" Expected: 1,200 debit (checked with math_evaluate).

If either fails, detour to posting day book totals or to balancing an account, then return.

## Teaching sequence

1. Ask what the control account checks: the total of all the personal accounts in one ledger. Done when the student says which ledger it checks and one error it would miss.
2. For each item, ask whether it concerns customers or suppliers, and strike out cash sales and cash purchases. Done when only credit items remain, each under its control account.
3. For each remaining figure, ask for its book of prime entry and its side; acc_double_entry confirms the side. Done when every figure has a source and a side the tool confirms.
4. Ask for the total of each side; math_evaluate gives the reference totals. Done when both totals match the checked values.
5. Ask for the closing balance and the side it is brought down on. Done when the checked balance sits on the debit side for customers or the credit side for suppliers.

## Hint ladder

1. Orient: "Does this item change what customers owe the business, or what the business owes suppliers?"
2. Concept: a control account is one big personal account for a whole ledger; it rises and falls on the same sides as one customer's or one supplier's account.
3. First step: write the opening balance on its side and ask where credit sales or credit purchases go.
4. Worked step: show one side complete and ask for the other side's items.
5. Full step: show the checked account and balance; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.ca_control_finds_all_errors`: thinks agreement proves every personal account right → "If a receipt is posted to the wrong customer, would the control total change?"
- `mc.acc.o.ca_control_replaces_ledger`: thinks personal accounts are no longer needed → "Without the personal accounts, how would the business know which customer owes what?"
- `mc.acc.o.ca_side_reversed`: debits receipts in the sales ledger control account → "When a customer pays, does the amount owed to the business rise or fall?"
- `mc.acc.o.ca_source_confused`: names the sales journal as the source of receipts → "Which book first records money received?"
- `mc.acc.o.ca_wrong_control_account`: puts a customer item with the suppliers → "Does this person buy from the business, or sell to it?"
- `mc.acc.o.ca_cash_sales_included`: includes cash sales → "Did this sale leave any customer owing money?"
- `mc.acc.o.ca_discount_side_reversed`: adds discount allowed to what customers owe → "Does a discount make the customer owe more or less?"
- `mc.acc.o.ca_irrecoverable_omitted`: leaves out irrecoverable debts → "The debt was written off. Does the business still expect to collect it?"
- `mc.acc.o.ca_cash_purchases_included`: includes cash purchases → "After paying cash, does the business owe that supplier anything?"
- `mc.acc.o.ca_contra_omitted`: leaves out a set-off → "The supplier also owes the business. Once the two debts are set off, what happens to what the business owes?"

## Confidence and escalation

- Two side errors in a row: switch to one customer's personal account, then scale it up to the control account.
- Three failures on balancing: detour to balancing an account, then return.
- A local trade practice the pack does not cover, such as credit given through an agent: save it as a question for a teacher.

## Worked exchange

> Tutor: The sales ledger control account opens with 4,200 owed by customers. In the month: credit sales 15,600, cash sales 2,000, receipts from customers 13,900, discount allowed 300, sales returns 500 and irrecoverable debts 250. What is the closing balance?
> Student: Debits are 4,200 + 15,600 + 2,000 = 21,800.
> Tutor: Did the cash sales leave any customer owing money?
> Student: No, so debits are 19,800. Credits are 13,900 + 300 + 500 + 250 = 14,950, so the balance is 4,850.
> Tutor: Right (checked with the maths tool). On which side is it brought down?
> Student: The debit side, because customers owe it to the business.
> Tutor: Correct.

## Verification checklist

- Cash sales and cash purchases are absent from both control accounts.
- Every figure's side matches acc_double_entry for the control account named.
- Side totals and the closing balance came from math_evaluate.
- Set-offs appear in both control accounts, on the credit side for customers and the debit side for suppliers.
