---
name: acc-o-trial-balance
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach the trial balance, the errors it misses, corrections and suspense
description: "trial balance, suspense account, correction of errors, error of commission, error of principle: list balances on the right side, name the error type and journal the correction. Not for: ledger entries (acc-o-double-entry) or final accounts (acc-o-sole-trader-statements)."
subject: accounting
levels: [O]
topics: [trial balance, suspense account, correction of errors, error types, journal]
kcs:
  - kc.acc.o.trial_balance.classify_tb_balances
  - kc.acc.o.trial_balance.prepare_trial_balance
  - kc.acc.o.trial_balance.errors_not_revealed
  - kc.acc.o.trial_balance.correcting_entries
  - kc.acc.o.trial_balance.suspense_account
curriculum_refs: [ACC-O-04]
prerequisites:
  - kc.acc.o.double_entry.debit_credit_rules
  - kc.acc.o.double_entry.balance_account
  - kc.acc.o.double_entry.record_cash_transactions
related: [acc-o-double-entry, acc-o-sole-trader-statements]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, math_evaluate]
visuals: [trial_balance, journal_entry, t_account]
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
  - The student lists each ledger balance on the correct side of a trial balance and finds both totals
  - The student names the type of an error that leaves the totals in agreement
  - The student writes the journal entry that corrects an error
  - The student works out the suspense balance and the entries that clear it
---

# The trial balance and correcting errors

## When to use

Use when a question asks for a trial balance, which side a balance belongs on, why the totals differ, what type
of error leaves them agreeing, the journal entry that corrects an error, or the suspense account.

Not for: recording ordinary transactions (acc-o-double-entry) or redrafting final accounts after corrections
(acc-o-sole-trader-statements).

## What this skill does not do

- It does not redo the original transactions; it starts from the ledger balances or the error described.
- It does not restate profit after corrections; that belongs to the statements skill.
- It does not guess a missing balance: the tools give every total and difference.

## Objectives

1. The student lists each ledger balance on the correct side of a trial balance and finds both totals.
2. The student names the type of an error that leaves the totals in agreement.
3. The student writes the journal entry that corrects an error.
4. The student works out the suspense balance and the entries that clear it.

## Prerequisite probe

- "Is the balance on a purchases account usually a debit or a credit?" Expected: a debit.
- "A bank account has debits of 900 and credits of 650. What is the balance, and which kind?" Expected: 250, a debit balance (checked with math_evaluate).

If either fails, detour to the debit and credit rules or to balancing an account, then return.

## Teaching sequence

1. Ask the student to place each balance as a debit or a credit by its class; acc_double_entry gives the reference side. Done when every balance sits on the side the tool confirms.
2. Ask for both totals and any difference; math_evaluate gives the reference values. Done when the student's totals and difference match the checked values.
3. For an error, ask the student to write what was entered and what should have been entered, side by side. Done when both versions are on the board as entries.
4. Ask the student to name the error type from that comparison and say whether the totals still agree. Done when one error type is named and fits the comparison.
5. Ask for the correcting journal entry that takes out what is wrong and puts in what is right; acc_double_entry checks it. Done when the tool reports the correction balanced with every line ok.
6. When the totals differed, ask for the suspense balance on the side with the smaller total, then post each correction that touches it; math_evaluate gives the reference balance. Done when the suspense account is checked as nil after the corrections.

## Hint ladder

1. Orient: "What was entered, and what should have been entered?"
2. Concept: an error that keeps debits equal to credits cannot show in the totals; only one-sided errors need suspense.
3. First step: write the wrong entry and the right entry one under the other and ask what differs.
4. Worked step: show the debit of the correction and ask for its credit and amount.
5. Full step: show the checked correction and the suspense account; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.tb_capital_debit`: lists capital as a debit → "Does the business own its capital, or owe it to the owner?"
- `mc.acc.o.tb_drawings_credit`: lists drawings as a credit → "Drawings reduce capital. Which side records a fall in capital?"
- `mc.acc.o.tb_discount_confused`: treats discount allowed as income → "When the business allowed the customer a discount, did it gain or lose?"
- `mc.acc.o.err_thinks_tb_reveals`: thinks agreeing totals prove no errors → "If a sale is left out of the books entirely, would the totals still agree?"
- `mc.acc.o.err_commission_principle_confused`: mixes commission and principle → "Is the wrong account in the same class as the right one, or a different class?"
- `mc.acc.o.err_reversal_vs_original`: mixes complete reversal and original entry → "Is the amount wrong, or are the sides wrong?"
- `mc.acc.o.corr_direction_reversed`: writes the correction the wrong way round → "After your entry, what balance does the wrong account show?"
- `mc.acc.o.corr_full_amount`: corrects a wrong amount with the whole amount → "By how much was the amount too high or too low?"
- `mc.acc.o.corr_reversal_once`: corrects a reversal with the amount once → "Taking the entry out once brings the account to nil. How much more puts it right?"
- `mc.acc.o.corr_through_suspense`: puts a balanced error through suspense → "Did this error make the totals disagree in the first place?"
- `mc.acc.o.susp_includes_balanced_error`: counts an omission in the suspense balance → "Did that error change one side of the trial balance more than the other?"
- `mc.acc.o.susp_side_reversed`: opens suspense on the larger side → "Which side was short, and where must the suspense balance go to fill the gap?"

## Confidence and escalation

- Two wrong error types in a row: switch to a table with columns for accounts, sides and amount, wrong against right.
- Three failures on sides in the trial balance: detour to the debit and credit rules, then return.
- An error described in a way that fits two types: save it as a question for a teacher.

## Worked exchange

> Tutor: Rent of 450 paid by cheque was debited to the bank account and credited to the rent account. What type of error is this, and what corrects it?
> Student: A complete reversal. Debit rent 450 and credit bank 450.
> Tutor: After that entry, what balance does the rent account show?
> Student: Credit 450 then debit 450, so nil. It should be a debit of 450, so the entry needs 900: debit rent 900, credit bank 900.
> Tutor: Right (checked with the double-entry tool). Does it pass through the suspense account?
> Student: No. Debits equalled credits, so the totals agreed.
> Tutor: Correct.

## Verification checklist

- Every side in the trial balance matches acc_double_entry for that account class.
- Totals, differences and the suspense balance came from math_evaluate.
- Each correction passed acc_double_entry and leaves the wrong account at its right balance.
- Only errors that changed one side's total go through suspense, and suspense ends at nil.
