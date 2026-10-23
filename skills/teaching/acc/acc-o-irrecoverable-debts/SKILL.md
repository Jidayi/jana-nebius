---
name: acc-o-irrecoverable-debts
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach writing off irrecoverable debts and adjusting the allowance for them
description: "Irrecoverable debts, bad debts, allowance for irrecoverable debts, debt recovered: write off, set the allowance, charge only the change and show net receivables. Not for: control accounts (acc-o-control-accounts) or the full statements (acc-o-sole-trader-statements)."
subject: accounting
levels: [O]
topics: [irrecoverable debts, bad debts, allowance for irrecoverable debts, debt recovered, trade receivables]
kcs:
  - kc.acc.o.irrecoverable_debts.write_off
  - kc.acc.o.irrecoverable_debts.allowance_amount
  - kc.acc.o.irrecoverable_debts.allowance_change
  - kc.acc.o.irrecoverable_debts.net_receivables
curriculum_refs: [ACC-O-10]
prerequisites:
  - kc.acc.o.double_entry.record_credit_transactions
related: [acc-o-control-accounts, acc-o-sole-trader-statements]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_double_entry, acc_statements, math_evaluate]
visuals: [journal_entry, t_account, financial_statements]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: allowance_rate
    unit: percent
    min: 0.5
    max: 20
    context: allowance for irrecoverable debts as a percentage of trade receivables
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student records a write-off and a recovery with entries that the double-entry tool confirms
  - The student works out the new allowance on the receivables left after any write-off
  - The student charges only the change in the allowance and shows net trade receivables correctly
---

# Irrecoverable debts and the allowance for them

## When to use

Use when a customer will not pay and the debt must be written off, when a debt written off earlier is paid after
all, or when a question asks for the allowance for irrecoverable debts, the change charged to profit, or the net
trade receivables at the year end.

Not for: sales ledger control accounts (use acc-o-control-accounts) or a complete income statement and statement of
financial position (use acc-o-sole-trader-statements).

## What this skill does not do

- It does not decide which customers will not pay; the question says so.
- It does not choose the allowance percentage; the question gives it.
- It does not prepare the full year-end statements; it supplies their irrecoverable debt lines.

## Objectives

1. The student records a write-off and a recovery with entries that the double-entry tool confirms.
2. The student works out the new allowance on the receivables left after any write-off.
3. The student charges only the change in the allowance and shows net trade receivables correctly.

## Prerequisite probe

- "Goods are sold on credit to a customer for $300. Which account is debited and which is credited?" Expected: debit the customer's account (trade receivables), credit sales.

If it fails, detour to recording credit transactions, then return.

## Teaching sequence

1. Ask whether the question is about a known debt that will not be paid, a debt paid after being written off, or an estimate for the future. Done when the student names the case.
2. For a write-off or a recovery, ask for the journal entries; acc_double_entry checks them against the key. Done when the tool reports the entries balanced and matching.
3. Ask the student to take any written-off debt out of trade receivables first, then apply the percentage; the acc_statements result is the reference value. Done when the student's allowance matches it.
4. Ask for the change: new allowance less old allowance, and whether it is an expense or income; acc_statements gives the reference. Done when the amount and the direction both match.
5. Ask for net trade receivables: receivables after write-offs less the new allowance; acc_statements gives the reference. Done when the figure matches.
6. Check any side sum with math_evaluate. Done when every figure shown has a tool check.

## Hint ladder

1. Orient: "Is this debt certain to be lost, or is the business only estimating a loss?"
2. Concept: a write-off removes a known debt; the allowance is an estimate on the debts that are left.
3. First step: write trade receivables less the debt written off, and ask for the percentage of that figure.
4. Worked step: show the new allowance next to the old one and ask for the difference and its direction.
5. Full step: show the checked figures; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.id_writeoff_to_allowance`: debits the allowance for a known bad debt → "Is this debt an estimate, or is it already certain that the customer will not pay?"
- `mc.acc.o.id_writeoff_as_sales_return`: treats the write-off like returned goods → "Did the goods come back to the business, or did the customer keep them?"
- `mc.acc.o.id_recovery_skips_reinstatement`: records the cash without putting the debt back first → "Where would the customer's account show that this debt was ever paid?"
- `mc.acc.o.id_recovery_as_sale`: credits sales when an old debt is paid → "Were any new goods sold when this money came in?"
- `mc.acc.o.id_allowance_before_writeoff`: applies the percentage before removing a written-off debt → "Does the business still expect to collect anything from the debt it has written off?"
- `mc.acc.o.id_net_as_allowance`: gives the receivables left as the allowance → "Is the allowance the part expected to be collected, or the part that may be lost?"
- `mc.acc.o.id_full_allowance_charged`: charges the whole new allowance to profit → "How much of this allowance was already charged against last year's profit?"
- `mc.acc.o.id_change_direction_reversed`: treats a rise in the allowance as income → "If the estimated loss grows, does profit go up or down?"
- `mc.acc.o.id_writeoff_not_deducted`: leaves a written-off debt in trade receivables → "Can a debt that has been written off still be counted as owed to the business?"
- `mc.acc.o.id_old_allowance_used`: deducts last year's allowance in this year's statement → "Which year's estimate describes the debts owed at this year end?"

## Confidence and escalation

- Two failures on the entries: switch to T-accounts and trace the customer's account line by line.
- Three failures on the allowance: detour to recording credit transactions, then return.
- A correct allowance but a wrong charge: treat it as mc.acc.o.id_full_allowance_charged before anything else.

## Worked exchange

> Tutor: Trade receivables are $12,400 at the year end, and a debt of $400 must still be written off. The allowance is to be 5% of trade receivables; last year it was $500. What is the new allowance?
> Student: 5% of 12,400 is 620.
> Tutor: Will the business still collect the $400 debt that is being written off?
> Student: No. So it is 5% of 12,000, which is 600.
> Tutor: Right (checked with the statements tool). How much goes to the income statement?
> Student: Only the increase, 600 − 500 = 100, as an expense.
> Tutor: Correct, and net trade receivables are 11,400 (checked with the statements tool).

## Verification checklist

- Every entry passed acc_double_entry, with the debt written off credited to the customer's account.
- Every figure came from the question or from an acc_statements or math_evaluate check.
- The allowance is worked on receivables after write-offs, and only the change reaches the income statement.
- Amounts are shown to 2 decimal places where pence or cents appear, using the pack's terms.
