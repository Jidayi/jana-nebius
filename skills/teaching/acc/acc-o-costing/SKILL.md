---
name: acc-o-costing
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach cost classification, contribution, break-even and margin of safety
description: "Costing, fixed and variable costs, direct and indirect costs, contribution, break-even, margin of safety, target profit: classify costs, then work from contribution per unit. Not for: inventory valuation (acc-o-inventory)."
subject: accounting
levels: [O]
topics: [costing, fixed costs, variable costs, direct costs, indirect costs, contribution, break-even, margin of safety, target profit]
kcs:
  - kc.acc.o.costing.cost_classification
  - kc.acc.o.costing.contribution
  - kc.acc.o.costing.break_even
  - kc.acc.o.costing.margin_of_safety
  - kc.acc.o.costing.target_profit
curriculum_refs: [ACC-O-16]
prerequisites:
  - kc.acc.o.accounting_equation.purpose_and_users
related: [acc-o-inventory]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_break_even, math_evaluate]
visuals: [break_even_chart]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: break_even_units
    unit: dimensionless
    min: 1
    max: 500000
    context: units a small business must sell to cover its fixed costs
  - quantity: target_units
    unit: dimensionless
    min: 1
    max: 500000
    context: units needed to earn a stated target profit
  - quantity: contribution_to_sales_ratio
    unit: dimensionless
    min: 0.01
    max: 0.95
    context: contribution per unit as a share of the selling price
  - quantity: margin_of_safety_percent
    unit: percent
    min: -100
    max: 95
    context: margin of safety as a percentage of expected output
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student classifies a cost as fixed or variable and as direct or indirect, with the reason
  - The student works out contribution and the break-even point in units and in revenue
  - The student finds the margin of safety, the profit at an output and the output for a target profit
---

# Costs, contribution and break-even

## When to use

Use when a question asks whether a cost is fixed or variable, direct or indirect, or asks for contribution per unit,
total contribution, the break-even point, the margin of safety, the profit at a given output or the output needed for
a target profit.

Not for: valuing inventory by FIFO or AVCO (use acc-o-inventory).

## What this skill does not do

- It does not cover semi-variable costs, absorption costing or more than one product.
- It does not draw the chart by hand; the break-even chart comes from the tool's lines.
- It does not decide the selling price; the question gives it.

## Objectives

1. The student classifies a cost as fixed or variable and as direct or indirect, with the reason.
2. The student works out contribution and the break-even point in units and in revenue.
3. The student finds the margin of safety, the profit at an output and the output for a target profit.

## Prerequisite probe

- "A business sells 100 caps at $8 each. What is its revenue?" Expected: $800.

If it fails, detour to the purpose of accounting and simple revenue, then return.

## Teaching sequence

1. Ask whether the total of each cost changes when output changes, and whether it can be traced to one unit. Done when every cost is labelled fixed or variable and direct or indirect.
2. Ask for contribution per unit: selling price less variable cost per unit; the acc_break_even result is the reference value. Done when the student's figure matches it.
3. Ask for the break-even point: fixed costs divided by contribution per unit, then the revenue at that output; acc_break_even gives the reference. Done when the units and the revenue both match.
4. Ask for the margin of safety: expected output less break-even output, and the profit at that output; acc_break_even gives the reference. Done when both match.
5. Ask for the output for a target profit: fixed costs plus target profit, divided by contribution per unit, rounded up to whole units; acc_break_even gives the reference. Done when the units match.
6. Check any side sum with math_evaluate. Done when every figure shown has a tool check.

## Hint ladder

1. Orient: "How much does each unit sold add towards the fixed costs?"
2. Concept: contribution is what is left from each sale after its own variable cost.
3. First step: write price less variable cost per unit and ask for the contribution.
4. Worked step: show fixed costs over contribution per unit and ask for the units.
5. Full step: show the checked figure; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.cost_fixed_variable_by_size`: calls a large cost variable → "If output doubles, does the total of this cost change?"
- `mc.acc.o.cost_direct_indirect_confused`: treats factory rent as a direct cost → "Can this cost be traced to one particular unit?"
- `mc.acc.o.cost_fixed_not_cost`: leaves fixed costs out of total costs → "Must the business pay this rent even in a month with no sales?"
- `mc.acc.o.cost_vc_added`: adds variable cost to the price → "Does the variable cost bring money in or send it out?"
- `mc.acc.o.cost_fixed_in_contribution`: takes a share of fixed cost off each unit → "Do fixed costs change with each extra unit sold?"
- `mc.acc.o.cost_contribution_as_profit`: calls total contribution the profit → "Have the fixed costs been paid out of this amount yet?"
- `mc.acc.o.cost_be_divides_by_price`: divides fixed costs by the selling price → "Is the whole price of each unit free to pay the fixed costs?"
- `mc.acc.o.cost_be_units_revenue_confused`: gives revenue when asked for units → "Does the question ask how many units, or how many dollars?"
- `mc.acc.o.cost_mos_be_as_mos`: gives the break-even output as the margin of safety → "How far can sales fall from the expected output before a loss?"
- `mc.acc.o.cost_mos_output_as_mos`: gives the expected output as the margin of safety → "Which part of the expected output is above break-even?"
- `mc.acc.o.cost_target_fc_omitted`: divides only the target profit by contribution → "Must the fixed costs be covered before any profit is made?"
- `mc.acc.o.cost_target_subtracted`: subtracts the target profit from fixed costs → "Does wanting more profit mean selling more units or fewer?"

## Confidence and escalation

- Two failures on break-even: switch to the break-even chart and find where revenue meets total cost.
- Three failures on classifying costs: detour to listing a business's costs as output changes, then return.
- A break-even answer that is not a whole number: round up to whole units, as the tool shows.

## Worked exchange

> Tutor: A product sells for $15 a unit. The variable cost is $9 a unit and fixed costs are $24,000 a year. How many units must be sold to break even?
> Student: 24,000 / 15 = 1,600 units.
> Tutor: Each sale brings in $15, but $9 of it pays for that unit. How much of each sale is left for the fixed costs?
> Student: 15 − 9 = 6, so 24,000 / 6 = 4,000 units.
> Tutor: Right (checked with the break-even tool). What is the break-even revenue?
> Student: 4,000 × 15 = 60,000.
> Tutor: Correct (checked with the break-even tool).

## Verification checklist

- Every figure came from an acc_break_even or math_evaluate check.
- Contribution per unit is price less variable cost only; no fixed cost is in it.
- Units and revenue are labelled, and unit answers are whole numbers rounded up where needed.
- Profit at an output equals total contribution less fixed costs, as the tool reports.
