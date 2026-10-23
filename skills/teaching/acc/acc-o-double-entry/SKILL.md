---
name: acc-o-double-entry
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach recording cash, credit and owner transactions in ledger accounts
description: "double entry, debit, credit, ledger accounts, drawings, balancing accounts: find the two accounts, pick each side by its class and bring the balance down. Not for: the trial balance or errors (acc-o-trial-balance) or bank reconciliation (acc-o-bank-reconciliation)."
subject: accounting
levels: [O]
topics: [double entry, debit, credit, ledger, drawings, balancing accounts, returns]
kcs:
  - kc.acc.o.double_entry.debit_credit_rules
  - kc.acc.o.double_entry.record_cash_transactions
  - kc.acc.o.double_entry.record_credit_transactions
  - kc.acc.o.double_entry.record_owner_transactions
  - kc.acc.o.double_entry.balance_account
curriculum_refs: [ACC-O-03]
prerequisites:
  - kc.acc.o.accounting_equation.classify_elements
related: [acc-o-trial-balance, acc-o-bank-reconciliation]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
visuals: [t_account, journal_entry]
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
  - The student states the side that records a rise and a fall for each class of account
  - The student names the account debited and the account credited for a cash, credit or owner transaction
  - The student balances a ledger account and says on which side the balance is brought down
---

# Double entry and the ledger

## When to use

Use when a question asks which accounts a transaction touches, which is debited and which credited, how to record
cash or bank payments and receipts, credit sales and purchases, returns, capital paid in or drawings, or for the
balance on a ledger account.

Not for: the trial balance and correction of errors (acc-o-trial-balance) or reconciling the bank
(acc-o-bank-reconciliation).

## What this skill does not do

- It does not make year-end adjustments such as accruals or depreciation.
- It does not use the bank's point of view; every entry is in the business's own books.
- Amounts come from the question and totals come from the tools, never from memory.

## Objectives

1. The student states the side that records a rise and a fall for each class of account.
2. The student names the account debited and the account credited for a cash, credit or owner transaction.
3. The student balances a ledger account and says on which side the balance is brought down.

## Prerequisite probe

- "Name the class of each: rent paid, office equipment, a loan from the bank." Expected: expense, asset, liability.

If it fails, detour to classifying the elements of the accounting equation, then return.

## Teaching sequence

1. Ask the student to name every account the transaction touches, using chart of accounts names. Done when each account is named.
2. Ask for each account's class and whether it rises or falls. Done when each account has a class and a direction.
3. Ask for the side by the class rule: a rise in an asset, an expense or drawings is a debit; a rise in a liability, capital or income is a credit; a fall goes on the other side. Done when the student justifies each side with the rule.
4. Ask the student to write the debit and the credit with amounts; acc_double_entry checks the entry. Done when the tool reports the entry balanced with every line ok.
5. To balance an account, ask for the total of each side, counting any balance brought down at the start; math_evaluate gives the reference totals. Done when both totals match the checked values.
6. Ask for the difference, the side it is carried down on and the side it is brought down on. Done when the balance carried down is on the smaller side and the checked difference is brought down on the other side.

## Hint ladder

1. Orient: "What did the business get, and what did it give up or now owe?"
2. Concept: each class has one side for a rise; the opposite side records a fall.
3. First step: name the class of the first account and ask which side its change goes on.
4. Worked step: write the first account with its side and amount, and ask what completes the entry.
5. Full step: show the checked entry or balance; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.de_class_confused`: uses one class's rule for another → "Is wages an expense or income, and where does a rise in that class go?"
- `mc.acc.o.de_bank_view`: copies the bank statement's sides → "Who wrote the bank statement, and whose ledger are you writing in now?"
- `mc.acc.o.de_asset_as_purchases`: debits purchases for equipment → "Will this equipment be sold to customers, or kept to run the business?"
- `mc.acc.o.de_cash_bank_confused`: mixes the cash and bank accounts → "Was this paid from the till, or by cheque or transfer?"
- `mc.acc.o.de_goods_to_inventory`: debits inventory with goods bought for resale → "During the year, which account records goods bought to sell again?"
- `mc.acc.o.de_loan_as_income`: credits sales with a loan → "Did the business sell anything to get this money, or will it repay it?"
- `mc.acc.o.de_credit_as_cash`: records a credit sale as a cash sale → "Did any money move on the day, or does the customer now owe it?"
- `mc.acc.o.de_sale_credits_inventory`: credits inventory when goods are sold → "Which income account records the goods the business sells?"
- `mc.acc.o.de_drawings_credit_capital`: credits capital for drawings → "Did the owner put money in, or take it out?"
- `mc.acc.o.de_goods_drawings_as_sales`: credits sales when the owner takes goods → "Did any customer pay for those goods?"
- `mc.acc.o.de_opening_balance_omitted`: forgets the balance brought down → "What was already in the account before this month began?"
- `mc.acc.o.de_total_as_balance`: gives a side's total as the balance → "Is the balance the size of one side, or the gap between the two sides?"

## Confidence and escalation

- Two side errors in a row: draw the two T-accounts and mark which one gains and which one gives.
- Three failures on the class of an account: detour to classifying the elements, then return.
- When an entry balances but names the wrong account, return to step 2 and ask for the class again.

## Worked exchange

> Tutor: The bank account starts the month with a debit balance of 1,200. During the month 3,500 is paid in and 2,900 is paid out. Balance the account.
> Student: Debits are 3,500 and credits 2,900, so the balance is 600.
> Tutor: What was already in the account when the month began?
> Student: The 1,200 on the debit side. So debits are 4,700 and the balance is 1,800.
> Tutor: Right (checked with the maths tool). Where is it carried down, and where is it brought down?
> Student: Carried down on the credit side and brought down on the debit side.
> Tutor: Correct: a debit balance of 1,800, which is money the business has in the bank.

## Verification checklist

- Each entry passed acc_double_entry with debits equal to credits and every line ok.
- Account names match the chart of accounts; goods for resale go to purchases, never to inventory.
- Every side total and balance came from math_evaluate, including any opening balance.
- The balance brought down sits on the side opposite to where it was carried down.
