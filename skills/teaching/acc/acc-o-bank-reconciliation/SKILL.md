---
name: acc-o-bank-reconciliation
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach updating the cash book and reconciling it with the bank statement
description: "bank reconciliation, cash book, bank statement, unpresented cheques, overdraft: update the cash book first, then reconcile from the statement balance to the updated cash book balance. Not for: ledger rules (acc-o-double-entry) or control accounts (acc-o-control-accounts)."
subject: accounting
levels: [O]
topics: [bank reconciliation, cash book, bank statement, unpresented cheques, outstanding lodgements, overdraft]
kcs:
  - kc.acc.o.bank_reconciliation.timing_differences
  - kc.acc.o.bank_reconciliation.update_cash_book
  - kc.acc.o.bank_reconciliation.reconciliation_statement
  - kc.acc.o.bank_reconciliation.overdraft_sides
curriculum_refs: [ACC-O-05]
prerequisites:
  - kc.acc.o.double_entry.record_cash_transactions
  - kc.acc.o.double_entry.balance_account
  - kc.acc.o.double_entry.debit_credit_rules
related: [acc-o-double-entry, acc-o-control-accounts]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
visuals: [bank_reconciliation, t_account]
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
  - The student sorts each difference into an item for the cash book or a timing difference for the statement
  - The student works out the updated cash book balance from items first seen on the bank statement
  - The student completes a reconciliation from the bank statement balance to the updated cash book balance
  - The student reads a debit or credit balance correctly in the cash book and on the bank statement
---

# Bank reconciliation

## When to use

Use when a question gives a cash book and a bank statement that disagree and asks for the updated cash book
balance, a bank reconciliation statement, the balance the statement should show, or what an overdraft looks
like in each record.

Not for: the debit and credit rules on their own (acc-o-double-entry) or control accounts
(acc-o-control-accounts).

## What this skill does not do

- It does not treat a difference as a bank error unless the question says so.
- It does not use any layout other than the pack's: start from the bank statement balance, end at the updated cash book balance.
- It does not work out balances itself: the tools give every figure.

## Objectives

1. The student sorts each difference into an item for the cash book or a timing difference for the statement.
2. The student works out the updated cash book balance from items first seen on the bank statement.
3. The student completes a reconciliation from the bank statement balance to the updated cash book balance.
4. The student reads a debit or credit balance correctly in the cash book and on the bank statement.

## Prerequisite probe

- "In the business's cash book, which side records money paid into the bank?" Expected: the debit side.
- "A cash book bank column has debits of 5,000 and credits of 3,800. What is the balance?" Expected: 1,200 debit (checked with math_evaluate).

If either fails, detour to recording cash transactions or balancing an account, then return.

## Teaching sequence

1. Ask the student to tick each item that appears in both the cash book and the bank statement. Done when every unticked item is listed.
2. Ask which unticked items the business could not have known about (charges, standing orders, credit transfers, dishonoured cheques) and which are timing differences. Done when each unticked item is in one of the two lists.
3. Ask for the updated cash book balance: add receipts first seen on the statement and take off payments first seen there; math_evaluate gives the reference value. Done when the student's balance and its side match the checked value.
4. Ask the student to set out the statement: the bank statement balance, add outstanding lodgements, take off unpresented cheques. Done when each timing difference sits on its line with the right sign.
5. Ask for the closing figure, or solve the same layout backwards when the statement balance is the unknown; math_evaluate gives the reference value. Done when the checked layout ends at the updated cash book balance.
6. For an overdraft, ask which side shows it in the cash book and which on the statement; acc_double_entry confirms the cash book side. Done when the student says a credit cash book balance and a debit statement balance both mean an overdraft.

## Hint ladder

1. Orient: "Did the business know about this item when it wrote up its cash book?"
2. Concept: items the business did not know go into the cash book; items the bank has not yet processed go into the statement.
3. First step: list the statement-only items and ask whether each one adds to or takes away from the business's money.
4. Worked step: show the updated cash book balance and ask for the first line of the reconciliation.
5. Full step: show the checked reconciliation; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.br_bank_error_assumed`: calls every difference a bank error → "Could the bank simply not have received this cheque yet?"
- `mc.acc.o.br_unpresented_vs_lodgement`: swaps unpresented cheques and lodgements → "Was this money paid out by the business, or paid in?"
- `mc.acc.o.br_update_vs_timing`: puts a timing difference in the cash book → "Did the business already know about this item when it wrote up its cash book?"
- `mc.acc.o.br_credit_transfer_omitted`: forgets receipts seen only on the statement → "Is there money on the statement that came in without passing through the cash book?"
- `mc.acc.o.br_includes_timing`: takes an unpresented cheque off the cash book again → "That cheque is already in the cash book. Why take it off a second time?"
- `mc.acc.o.br_update_signs_reversed`: adds bank charges → "Did the bank charge leave the business with more money or less?"
- `mc.acc.o.br_rec_signs_reversed`: adds unpresented cheques to the statement balance → "When that cheque clears, will the statement balance go up or down?"
- `mc.acc.o.br_rec_uses_unadjusted_cb`: reconciles to the old cash book balance → "Has the cash book been brought up to date before the comparison?"
- `mc.acc.o.br_credit_means_money`: reads a credit cash book balance as money in the bank → "In the business's cash book, which side records money paid in?"
- `mc.acc.o.br_statement_view_reversed`: reads the statement from the business's view → "Whose point of view is the bank statement written from?"

## Confidence and escalation

- Two sign errors in a row: switch to a number line that starts at the statement balance and moves as each item clears.
- Three failures on cash book sides: detour to recording cash transactions, then return.
- A bank charge or item with a local name the pack does not cover: save it as a question for a teacher.

## Worked exchange

> Tutor: The cash book shows a debit balance of 2,400. The statement shows bank charges of 60 and a credit transfer of 500 not in the cash book. A cheque for 700 is unpresented and a deposit of 300 is not yet on the statement. What is the updated cash book balance, and what should the statement show?
> Student: 2,400 − 60 + 500 − 700 = 2,140.
> Tutor: The 700 cheque is already in the cash book. Did the business know about it?
> Student: Yes, so it stays out. The updated balance is 2,400 − 60 + 500 = 2,840.
> Tutor: Right (checked with the maths tool). Start from the statement balance, add the 300 and take off the 700 to reach 2,840. What must the statement show?
> Student: 2,840 + 700 − 300, so 3,240.
> Tutor: Correct: 3,240 + 300 − 700 = 2,840 (checked with the maths tool).

## Verification checklist

- The updated cash book balance and every reconciliation line came from math_evaluate.
- Only statement-only items changed the cash book; timing differences appear only in the reconciliation.
- The reconciliation starts at the bank statement balance and ends at the updated cash book balance.
- An overdraft is shown as a negative or labelled figure, never as money in the bank.
