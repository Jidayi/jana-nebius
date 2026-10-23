---
name: acc-o-ratios
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach calculating and interpreting accounting ratios
description: "Ratios, gross margin, mark-up, current ratio, acid-test, inventory turnover, collection periods, return on capital employed: use the pack's definitions, then interpret. Not for: missing figures from a margin (acc-o-incomplete-records)."
subject: accounting
levels: [O]
topics: [ratios, gross margin, profit margin, mark-up, current ratio, acid-test ratio, inventory turnover, collection period, return on capital employed, interpretation]
kcs:
  - kc.acc.o.ratios.margins
  - kc.acc.o.ratios.mark_up
  - kc.acc.o.ratios.liquidity
  - kc.acc.o.ratios.inventory_turnover
  - kc.acc.o.ratios.collection_periods
  - kc.acc.o.ratios.roce
  - kc.acc.o.ratios.interpret_ratios
curriculum_refs: [ACC-O-15]
prerequisites:
  - kc.acc.o.sole_trader_statements.gross_profit
  - kc.acc.o.sole_trader_statements.working_capital
  - kc.acc.o.sole_trader_statements.cost_of_sales
  - kc.acc.o.sole_trader_statements.profit_for_year
related: [acc-o-incomplete-records, acc-o-sole-trader-statements]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_ratios, math_evaluate]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: gross_margin
    unit: percent
    min: 0
    max: 90
    context: gross profit as a percentage of revenue for a trading business
  - quantity: net_margin
    unit: percent
    min: -50
    max: 60
    context: profit for the year as a percentage of revenue
  - quantity: mark_up
    unit: percent
    min: 0
    max: 300
    context: gross profit as a percentage of cost of sales
  - quantity: roce
    unit: percent
    min: -50
    max: 100
    context: profit for the year over closing capital plus non-current liabilities
  - quantity: current_ratio
    unit: dimensionless
    min: 0.1
    max: 10
    context: current assets to current liabilities, as x to 1
  - quantity: acid_test
    unit: dimensionless
    min: 0.05
    max: 8
    context: current assets less inventory to current liabilities, as x to 1
  - quantity: inventory_turnover_times
    unit: dimensionless
    min: 0.5
    max: 60
    context: cost of sales over average inventory for a year
  - quantity: inventory_turnover_days
    unit: day
    min: 3
    max: 365
    context: average inventory held, in days of a 365-day year
  - quantity: receivable_days
    unit: day
    min: 1
    max: 180
    context: trade receivables collection period on credit sales
  - quantity: payable_days
    unit: day
    min: 1
    max: 180
    context: trade payables payment period on credit purchases
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student chooses the figures each ratio needs under the pack's definitions
  - The student calculates the ratio with the correct base, unit and 2 decimal places, as the ratios tool confirms
  - The student explains a change in a ratio with a cause that fits the kind of ratio
---

# Analysing and interpreting accounts

## When to use

Use when a question asks for a gross or profit margin, a mark-up, the current or acid-test ratio, inventory
turnover, a collection or payment period, or the return on capital employed, or asks what a change in one of them
shows.

Not for: finding a missing revenue or cost of sales from a stated margin or mark-up (use acc-o-incomplete-records),
or preparing the statements the figures come from (use acc-o-sole-trader-statements).

## What this skill does not do

- It does not pick a definition: the pack fixes them (365 days, average inventory, credit sales and purchases, closing capital plus non-current liabilities, profit for the year).
- It does not prepare the statements; the question gives the figures.
- It does not cover gearing or company ratios.

## Objectives

1. The student chooses the figures each ratio needs under the pack's definitions.
2. The student calculates the ratio with the correct base, unit and 2 decimal places, as the ratios tool confirms.
3. The student explains a change in a ratio with a cause that fits the kind of ratio.

## Prerequisite probe

- "Revenue is $30,000 and cost of sales is $18,000. What is the gross profit?" Expected: $12,000.

If it fails, detour to gross profit, then return.

## Teaching sequence

1. Ask which group the ratio belongs to: profitability, liquidity or efficiency. Done when the student names the group.
2. Ask the student to write the formula in words with its base, and to read the pack's definition where one applies. Done when the formula is on the board.
3. Ask the student to pick the figures from the statements, such as average inventory or credit sales only. Done when every figure is listed with its source line.
4. Ask for the value with its unit: percent, x to 1, times or days; the acc_ratios result is the reference value. Done when the student's value matches it to 2 decimal places.
5. Ask whether the change since last year is better or worse for this ratio, and for one cause of the right kind. Done when the cause fits the ratio's group.
6. Check any side sum with math_evaluate. Done when every figure shown has a tool check.

## Hint ladder

1. Orient: "Which two figures does this ratio compare, and which one is the base?"
2. Concept: a margin compares profit with revenue; a mark-up compares profit with cost.
3. First step: write the formula with the two figures in place and ask for the division.
4. Worked step: show the fraction and ask for the value and its unit.
5. Full step: show the checked ratio; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.rat_margin_markup_confused`: divides by cost for a margin → "Is a margin measured against the selling price or against the cost?"
- `mc.acc.o.rat_revenue_for_profit`: puts revenue on top for a mark-up → "Can the profit on goods be more than the whole price paid for them?"
- `mc.acc.o.rat_gross_net_confused`: uses gross profit for return on capital → "Which profit is left for the owner after every expense?"
- `mc.acc.o.rat_ratio_inverted`: divides current liabilities by current assets → "Which figure comes first in the name of the ratio?"
- `mc.acc.o.rat_acid_includes_inventory`: keeps inventory in the acid-test → "Can inventory be turned into cash at once to pay a debt due tomorrow?"
- `mc.acc.o.rat_quick_assets_too_narrow`: uses only trade receivables as quick assets → "Is money already in the bank available to pay debts?"
- `mc.acc.o.rat_closing_inventory_used`: uses closing inventory → "Which inventory figure does the pack's definition ask for?"
- `mc.acc.o.rat_revenue_for_cos`: divides revenue by inventory → "Is inventory valued at cost or at selling price?"
- `mc.acc.o.rat_total_sales_used`: uses all sales for the collection period → "Do cash customers ever owe the business anything?"
- `mc.acc.o.rat_capital_employed_wrong`: leaves the long-term loan out of capital employed → "Which long-term funds does the business use besides the owner's capital?"
- `mc.acc.o.rat_interpret_volume_margin`: says selling more raises the gross margin → "If each item earns the same profit, does selling more change the profit per dollar of revenue?"
- `mc.acc.o.rat_interpret_liquidity_profit`: explains a fall in the current ratio by lower profit → "Does this ratio use any profit figure at all?"

## Confidence and escalation

- Two failures on the base: switch to a two-column table of profit and base for margin and mark-up.
- Three failures on picking figures: detour to the statement the figure comes from, then return.
- A board in the student's region that uses a different definition: follow the pack and save the question for human help.

## Worked exchange

> Tutor: Revenue is $50,000 and cost of sales is $40,000. What are the gross margin and the mark-up?
> Student: Gross profit is 10,000. The margin is 10,000 / 40,000 × 100 = 25%.
> Tutor: A margin compares the profit with the selling price. Which figure is the selling price?
> Student: Revenue, so the margin is 10,000 / 50,000 × 100 = 20%.
> Tutor: Right (checked with the ratios tool). And the mark-up?
> Student: Mark-up is on cost: 10,000 / 40,000 × 100 = 25%.
> Tutor: Correct (checked with the ratios tool).

## Verification checklist

- Every value came from an acc_ratios or math_evaluate check, with the pack's definitions recorded.
- Percentages say percent, liquidity ratios are written as x to 1, and periods are in days.
- Values are rounded to 2 decimal places, half away from zero.
- An interpretation names a cause of the same kind as the ratio.
