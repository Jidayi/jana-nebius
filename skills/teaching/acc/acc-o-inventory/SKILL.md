---
name: acc-o-inventory
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach FIFO and AVCO valuation, net realisable value and profit effects
description: "inventory valuation, FIFO, AVCO, net realisable value, closing inventory: track receipts and issues, value what is left at the lower of cost and net realisable value, and trace an error into profit. Not for: the income statement (acc-o-sole-trader-statements) or ratios (acc-o-ratios)."
subject: accounting
levels: [O]
topics: [inventory valuation, fifo, avco, net realisable value, closing inventory, cost of sales]
kcs:
  - kc.acc.o.inventory.fifo
  - kc.acc.o.inventory.avco
  - kc.acc.o.inventory.lower_cost_nrv
  - kc.acc.o.inventory.inventory_profit_effect
curriculum_refs: [ACC-O-08]
prerequisites:
  - kc.acc.o.double_entry.record_credit_transactions
  - kc.acc.o.sole_trader_statements.cost_of_sales
related: [acc-o-sole-trader-statements, acc-o-ratios]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [acc_inventory, math_evaluate]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: inventory_units
    unit: dimensionless
    min: 0
    max: 100000
    context: units held in store at any point in a school inventory record
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student values closing inventory and cost of sales by FIFO from a record of receipts and issues
  - The student values closing inventory by AVCO with a new average unit cost after each receipt
  - The student values each item at the lower of cost and net realisable value
  - The student predicts the effect of an inventory error on gross profit and profit for the year
---

# Valuing inventory

## When to use

Use when a question gives receipts and issues of goods and asks for closing inventory or cost of sales by FIFO
or AVCO, when goods are damaged or slow to sell and need the lower of cost and net realisable value, or when it
asks how an inventory error changes profit.

Not for: preparing the income statement itself (acc-o-sole-trader-statements) or inventory ratios
(acc-o-ratios).

## What this skill does not do

- It does not use LIFO or a periodic AVCO: the pack works out a new average after each receipt.
- It does not round the average unit cost; only the inventory value is rounded to 2 decimal places.
- It does not count or value goods itself: the tools give every figure.

## Objectives

1. The student values closing inventory and cost of sales by FIFO from a record of receipts and issues.
2. The student values closing inventory by AVCO with a new average unit cost after each receipt.
3. The student values each item at the lower of cost and net realisable value.
4. The student predicts the effect of an inventory error on gross profit and profit for the year.

## Prerequisite probe

- "How is cost of sales found from opening inventory, purchases and closing inventory?" Expected: opening inventory + purchases − closing inventory.

If it fails, detour to cost of sales in the income statement, then return.

## Teaching sequence

1. Ask the student to list receipts and issues in date order with quantities and unit costs. Done when the record runs in order and the units left agree with the question.
2. For FIFO, ask which batches leave first and which remain; acc_inventory gives the reference closing inventory and cost of sales. Done when both figures match the checked values.
3. For AVCO, ask for the new average unit cost after each receipt, kept exact, and the cost of each issue at that average; acc_inventory gives the reference values. Done when the closing value, rounded to 2 decimal places, matches the checked value.
4. For damaged or slow goods, ask for net realisable value (selling price less costs to finish and sell) and compare it with cost item by item; math_evaluate gives the reference values. Done when each item carries the lower checked figure.
5. For an error, ask how closing inventory enters cost of sales and which way gross profit and profit for the year move, then what happens next year when it becomes opening inventory. Done when the student states the direction for both years.

## Hint ladder

1. Orient: "Which goods have left the store, and which are still there?"
2. Concept: FIFO issues the oldest goods first; AVCO prices every unit at the running average; inventory is never valued above what it will fetch.
3. First step: set up the record with columns for in, out and balance, and ask for the first issue.
4. Worked step: show the balance after the first issue and ask for the next line.
5. Full step: show the checked record and closing value; this counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.inv_fifo_reversed`: values FIFO closing inventory at the oldest prices → "Under FIFO, which goods leave the store first, the oldest or the newest?"
- `mc.acc.o.inv_avco_for_fifo`: uses an average for FIFO → "Does FIFO ever mix prices into an average?"
- `mc.acc.o.inv_cos_for_closing`: gives cost of sales as closing inventory → "Is that the cost of what was sold, or of what is still on the shelves?"
- `mc.acc.o.inv_simple_average`: averages the unit prices without weights → "Did the business buy the same number of units at each price?"
- `mc.acc.o.inv_fifo_for_avco`: uses the latest price for AVCO → "Under AVCO, do the goods left carry the latest price or the running average?"
- `mc.acc.o.inv_selling_price_used`: values inventory at selling price → "Has the business earned a profit on goods it has not sold yet?"
- `mc.acc.o.inv_nrv_ignored`: keeps cost when the goods will sell for less → "If the item will sell for less than it cost, can it be worth its cost?"
- `mc.acc.o.inv_nrv_costs_added`: adds repair costs to the selling price → "Do repair costs add to what the business will receive, or reduce it?"
- `mc.acc.o.inv_effect_reversed`: says overstated inventory lowers profit → "If closing inventory is too high, is cost of sales too high or too low?"
- `mc.acc.o.inv_no_profit_effect`: thinks an inventory error leaves profit alone → "Closing inventory is taken off in cost of sales. Can it change without profit changing?"
- `mc.acc.o.inv_opening_closing_confused`: gives opening and closing errors the same effect → "Opening inventory is added in cost of sales and closing inventory is taken off. Do their errors push profit the same way?"

## Confidence and escalation

- Two wrong balances in a row: switch to a table with one row per batch, crossing out units as they leave.
- Three failures on the profit effect: detour to cost of sales, then return.
- Goods the pack does not cover, such as items held for a customer: save it as a question for a teacher.

## Worked exchange

> Tutor: There is no opening inventory. The business receives 100 units at 4.00 each, then 150 units at 5.00 each, and then issues 180 units. Value closing inventory and cost of sales by FIFO.
> Student: 70 units are left, at 4.00 each, so 280.
> Tutor: Under FIFO, which batch leaves the store first?
> Student: The one at 4.00. So all 100 of those go, plus 80 at 5.00, leaving 70 at 5.00, which is 350.
> Tutor: Right (checked with the inventory tool). What is the cost of sales?
> Student: 100 × 4.00 plus 80 × 5.00, which is 800.
> Tutor: Correct: 350 left and 800 sold add up to the 1,150 bought (checked with the maths tool).

## Verification checklist

- Closing inventory and cost of sales came from acc_inventory with the method the question names.
- Closing inventory plus cost of sales equals opening inventory plus purchases (checked with math_evaluate).
- The AVCO unit cost is exact and only the value is rounded to 2 decimal places, half away from zero.
- Each item is at the lower of cost and net realisable value, compared item by item.
