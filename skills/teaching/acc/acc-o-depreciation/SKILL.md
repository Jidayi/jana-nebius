---
name: acc-o-depreciation
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach capital spending, depreciation methods, net book value and disposals
description: "depreciation, straight line, reducing balance, net book value, disposal: sort capital from revenue spending, run each year under the full-year policy and compare proceeds with net book value. Not for: statement layout (acc-o-sole-trader-statements) or concepts (acc-o-concepts)."
subject: accounting
levels: [O]
topics: [depreciation, straight line, reducing balance, net book value, disposal, capital expenditure, revenue expenditure]
kcs:
  - kc.acc.o.depreciation.capital_revenue_expenditure
  - kc.acc.o.depreciation.depreciation_purpose
  - kc.acc.o.depreciation.straight_line
  - kc.acc.o.depreciation.reducing_balance
  - kc.acc.o.depreciation.net_book_value
  - kc.acc.o.depreciation.disposal
curriculum_refs: [ACC-O-07]
prerequisites:
  - kc.acc.o.accounting_equation.classify_elements
related: [acc-o-sole-trader-statements, acc-o-concepts]
pedagogy: [pedagogy-worked-example-fade]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_depreciation, math_evaluate]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: worked_example
plausibility:
  - quantity: depreciation_rate
    unit: percent
    min: 1
    max: 50
    context: straight-line or reducing-balance rates for buildings, machinery, vehicles and equipment
  - quantity: useful_life
    unit: year
    min: 1
    max: 50
    context: expected useful life of a non-current asset in a school question
  - quantity: time
    unit: year
    min: 0
    max: 30
    context: years an asset has been held at the date asked
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student sorts spending into capital and revenue expenditure by what it buys
  - The student explains why non-current assets are depreciated and why depreciation is not a cash payment
  - The student works out the yearly charge, accumulated depreciation and net book value by the method given
  - The student works out the profit or loss on disposal from the proceeds and the net book value
---

# Depreciation and disposals

## When to use

Use when a question asks whether spending is capital or revenue expenditure, why assets are depreciated, for a
yearly charge by the straight-line or reducing-balance method, for accumulated depreciation or net book value,
or for the profit or loss when a non-current asset is sold.

Not for: laying out the income statement or the statement of financial position (acc-o-sole-trader-statements)
or the accounting concepts behind depreciation (acc-o-concepts).

## What this skill does not do

- It does not use part-year charges: the pack charges a full year in the year of purchase and none in the year of disposal, unless the question says otherwise.
- It does not treat revaluation or the sum-of-digits method.
- It does not compute charges itself: the tools give every figure.

## Objectives

1. The student sorts spending into capital and revenue expenditure by what it buys.
2. The student explains why non-current assets are depreciated and why depreciation is not a cash payment.
3. The student works out the yearly charge, accumulated depreciation and net book value by the method given.
4. The student works out the profit or loss on disposal from the proceeds and the net book value.

## Prerequisite probe

- "Is a delivery van owned by the business an asset or an expense?" Expected: an asset.
- "What is 20% of 8,000?" Expected: 1,600 (checked with math_evaluate).

If the first fails, detour to classifying the elements; if the second fails, practise percentages first.

## Teaching sequence

1. Ask what each payment buys: a non-current asset or its cost to get it working, or upkeep and running costs. Done when each payment is labelled capital or revenue with a reason.
2. Ask for the method, the rate or the life and residual value, and the number of years held under the full-year policy. Done when all of these are on the board.
3. Ask for the yearly charge: (cost − residual value) ÷ life for straight line, or the rate × the opening net book value for reducing balance; the acc_depreciation result is the reference value. Done when the student's charge matches the checked value.
4. Ask for accumulated depreciation and net book value at the year end asked; acc_depreciation gives the reference schedule. Done when both figures match the checked schedule.
5. For a disposal, ask for the net book value at the date of sale, with no charge in the year of sale, then the gap between the proceeds and it; math_evaluate gives the reference value. Done when the student states the checked figure and labels it profit or loss.

## Hint ladder

1. Orient: "Which method does the question give, and how many years has the asset been held?"
2. Concept: depreciation spreads the cost of an asset over the years that use it; net book value is the cost not yet charged.
3. First step: write the first year's charge and the net book value after it, and ask for the next year.
4. Worked step: show the schedule up to the year before the one asked and ask for that year.
5. Full step: show the checked schedule or disposal figure; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.cre_big_amount_rule`: decides by the size of the bill → "Does the size of the bill tell you whether the item will last for years?"
- `mc.acc.o.cre_installation_as_revenue`: expenses the installation of a new machine → "Could the machine work at all without being delivered and installed?"
- `mc.acc.o.cre_repairs_as_capital`: treats a repair as capital → "After the repair, can the machine do more than when it was new?"
- `mc.acc.o.dep_cash_outflow`: thinks depreciation is paid in cash → "On which day does the business hand over cash for depreciation?"
- `mc.acc.o.dep_is_market_value`: reads net book value as resale value → "Is net book value what a buyer would pay, or the cost not yet charged?"
- `mc.acc.o.sl_residual_ignored`: divides the whole cost by the life → "How much of the cost comes back when the asset is sold at the end?"
- `mc.acc.o.sl_total_not_annual`: gives the lifetime total as the yearly charge → "Is that the charge for one year, or for the whole life?"
- `mc.acc.o.rb_on_cost`: applies the reducing-balance rate to cost every year → "In year 2, is the rate applied to the cost or to what was left after year 1?"
- `mc.acc.o.nbv_one_year_only`: takes off one year's charge after several years → "How many years of charges have been made since the purchase?"
- `mc.acc.o.disp_cost_not_nbv`: compares proceeds with cost → "After depreciation, what value did the books show for the asset when it was sold?"
- `mc.acc.o.disp_disposal_year_depreciated`: charges depreciation in the year of sale → "Under the pack's policy, how much is charged in the year of sale?"
- `mc.acc.o.disp_sign_reversed`: calls a loss a profit → "Did the business receive more or less than the net book value?"

## Confidence and escalation

- Two wrong charges in a row: build the year-by-year schedule as a table with cost, charge, accumulated depreciation and net book value.
- Three failures on a method: show a fully worked year, then fade to the student doing the next one.
- An asset type the pack does not cover, such as a leased or shared item: save it as a question for a teacher.

## Worked exchange

> Tutor: A machine costs 20,000 and is depreciated at 25% a year by the reducing-balance method, with a full year in the year of purchase and none in the year of sale. It is bought in year 1 and sold in year 3 for 10,500. What is the profit or loss on disposal?
> Student: 25% of 20,000 is 5,000 a year, so after two years the net book value is 10,000 and there is a profit of 500.
> Tutor: In year 2, is the 25% taken from the cost or from what was left after year 1?
> Student: From what was left, 15,000. So year 2 is 3,750 and the net book value is 11,250.
> Tutor: Right (checked with the depreciation tool). Is any depreciation charged in year 3?
> Student: No. 10,500 is less than 11,250, so a loss of 750.
> Tutor: Correct: a loss on disposal of 750 (checked with the maths tool).

## Verification checklist

- Every charge, accumulated depreciation and net book value came from acc_depreciation.
- The year count follows the full-year policy unless the question gives another one.
- Freehold land carries no depreciation.
- Profit or loss on disposal came from math_evaluate, is labelled, and is shown to 2 decimal places when it has cents.
