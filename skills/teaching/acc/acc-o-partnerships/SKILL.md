---
name: acc-o-partnerships
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach sharing partnership profit and keeping the partners' accounts
description: "Partnership, appropriation account, interest on capital, partners' salaries, current accounts: apply the agreement, share the residual profit and keep the partners' accounts. Not for: a sole trader's statements (acc-o-sole-trader-statements)."
subject: accounting
levels: [O]
topics: [partnership, appropriation account, interest on capital, interest on drawings, partners' salaries, current accounts, capital accounts]
kcs:
  - kc.acc.o.partnerships.partnership_agreement
  - kc.acc.o.partnerships.interest_and_salary
  - kc.acc.o.partnerships.appropriation
  - kc.acc.o.partnerships.current_accounts
  - kc.acc.o.partnerships.capital_vs_current
curriculum_refs: [ACC-O-12]
prerequisites:
  - kc.acc.o.double_entry.record_owner_transactions
  - kc.acc.o.sole_trader_statements.profit_for_year
  - kc.acc.o.double_entry.balance_account
related: [acc-o-sole-trader-statements]
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
plausibility:
  - quantity: interest_rate
    unit: percent
    min: 1
    max: 20
    context: interest on partners' capital or drawings
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student states what the agreement settles and the rules that apply when there is none
  - The student shares the residual profit after interest and salaries in the agreed ratio
  - The student records each item in the correct capital or current account and balances the current account
---

# Partnership accounts

## When to use

Use when two or more partners share a profit and a question asks for interest on capital or drawings, salaries,
each partner's share of the residual profit, or the balance of a partner's current account, or asks what belongs in
the capital account and what in the current account.

Not for: a sole trader's income statement and statement of financial position (use acc-o-sole-trader-statements).

## What this skill does not do

- It does not cover admitting or retiring a partner, goodwill or revaluation.
- It does not invent agreement terms; the question gives them, or the default rules apply.
- It does not work out profit for the year itself; the question gives it.

## Objectives

1. The student states what the agreement settles and the rules that apply when there is none.
2. The student shares the residual profit after interest and salaries in the agreed ratio.
3. The student records each item in the correct capital or current account and balances the current account.

## Prerequisite probe

- "An owner takes $500 from the business bank account for private use. Which account is debited?" Expected: drawings.

If it fails, detour to recording owner transactions, then return.

## Teaching sequence

1. Ask what the agreement says about the profit-sharing ratio, interest, salaries and interest on drawings; with no agreement, profit is shared equally with no interest or salaries. Done when every term is listed.
2. Ask for each partner's interest on capital, interest on drawings and salary, using that partner's own figures; math_evaluate gives the reference value. Done when each amount matches.
3. Ask for the residual profit: profit for the year plus interest on drawings, less interest on capital and salaries; math_evaluate gives the reference. Done when the figure matches.
4. Ask for each partner's share of the residual in the ratio; math_evaluate gives the reference. Done when the shares add up to the residual.
5. Ask the student to post the items to each current account and balance it; acc_double_entry checks the postings. Done when the tool confirms the closing balance and its side.
6. Ask which items go to the capital account instead. Done when only permanent capital changes are placed there.

## Hint ladder

1. Orient: "What does the agreement give each partner before the rest is shared?"
2. Concept: interest and salaries are shares of the profit, taken out before the residual is split.
3. First step: list each partner's interest and salary, and ask for their total.
4. Worked step: show profit plus interest on drawings less that total, and ask for the residual.
5. Full step: show the checked shares; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.pa_capital_ratio_default`: shares profit in the capital ratio with no agreement → "If the partners agreed nothing, what rule shares the profit?"
- `mc.acc.o.pa_salary_default`: gives a salary with no agreement → "Where would a partner's right to a salary come from?"
- `mc.acc.o.pa_rate_on_wrong_base`: works interest on the total of all capitals → "Whose capital earns this partner's interest?"
- `mc.acc.o.pa_salary_omitted`: leaves out an agreed salary → "Has every amount the agreement promises been taken out before sharing?"
- `mc.acc.o.pa_iod_subtracted`: takes interest on drawings off the profit to share → "The partner pays this interest. Does that leave more or less profit to share?"
- `mc.acc.o.pa_share_before_appropriations`: splits the whole profit in the ratio first → "What must be paid to the partners before the rest is split?"
- `mc.acc.o.pa_ratio_reversed`: gives one partner the other's fraction → "Which partner has the larger part of the ratio?"
- `mc.acc.o.pa_appropriation_as_expense`: puts salaries in the income statement → "Is a partner's salary a cost of running the business, or a share of its profit?"
- `mc.acc.o.pa_drawings_added_current`: credits drawings to the current account → "Do drawings increase or decrease what the business owes the partner?"
- `mc.acc.o.pa_opening_side_reversed`: treats an opening debit balance as a credit → "Does a debit balance mean the partner owes the business, or the business owes the partner?"
- `mc.acc.o.pa_profit_to_capital`: credits the profit share to a fixed capital account → "If capitals are fixed, which account takes the yearly changes?"

## Confidence and escalation

- Two failures on the residual: switch to a table with one column per partner and one row per item.
- Three failures on the current account: detour to balancing an account, then return.
- A share that is right in size but given to the wrong partner: treat it as mc.acc.o.pa_ratio_reversed.

## Worked exchange

> Tutor: Ama and Kofi share profits 3:2. Profit for the year is $40,000. Capitals are Ama $50,000 and Kofi $30,000, with interest on capital at 6%. Kofi's salary is $8,000. Interest on drawings is Ama $300 and Kofi $200. What residual profit is shared?
> Student: 40,000 − 3,000 − 1,800 − 8,000 = 27,200.
> Tutor: The partners pay interest on their drawings. Does that make the profit to share bigger or smaller?
> Student: Bigger: 40,000 + 300 + 200 − 3,000 − 1,800 − 8,000 = 27,700.
> Tutor: Right (checked with the maths tool). What is each partner's share?
> Student: Ama gets 3/5 of 27,700, which is 16,620, and Kofi gets 11,080.
> Tutor: Correct (checked with the maths tool); the two shares add up to 27,700.

## Verification checklist

- Every figure came from the question or from a math_evaluate check.
- Interest on capital uses each partner's own capital, and interest on drawings is added back.
- The shares add up to the residual profit exactly.
- Current account postings passed acc_double_entry, and the closing balance has its side stated.
