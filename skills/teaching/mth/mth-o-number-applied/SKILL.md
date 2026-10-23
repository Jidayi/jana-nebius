---
name: mth-o-number-applied
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach ratio, proportion, rates, percentage change, time and interest problems
description: "Ratio, proportion, rates, percentage change, reverse percentages, time intervals, exchange rates, interest: find one part or the multiplier first, then scale and check. Not for: converting fractions and percentages, rounding or bounds (mth-o-number)."
subject: mathematics
levels: [O]
topics: [ratio, proportion, rates, speed, percentage change, reverse percentage, time intervals, exchange rates, simple interest, compound interest, growth and decay]
kcs:
  - kc.mth.o.number.ratio_share
  - kc.mth.o.number.direct_proportion
  - kc.mth.o.number.rates
  - kc.mth.o.number.percentage_change
  - kc.mth.o.number.reverse_percentage
  - kc.mth.o.number.time_intervals
  - kc.mth.o.number.currency_conversion
  - kc.mth.o.number.simple_interest
  - kc.mth.o.number.compound_growth
curriculum_refs: [MTH-O-01.11, MTH-O-01.12, MTH-O-01.13, MTH-O-01.15, MTH-O-01.16, MTH-O-01.17]
prerequisites:
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.fraction_arithmetic
  - kc.mth.o.number.fdp_conversion
  - kc.mth.o.number.index_laws_numeric
related: [mth-o-number]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: percentage_change
    unit: percent
    min: -100
    max: 500
    context: rises and falls in prices, wages, populations and marks
  - quantity: interest_rate
    unit: percent
    min: 0
    max: 30
    context: yearly simple or compound interest rates in school questions
  - quantity: multiplier
    unit: dimensionless
    min: 0.01
    max: 10
    context: one-step or compound multipliers such as 1.15 or 0.92 to a power
  - quantity: speed
    unit: km/h
    min: 0
    max: 1000
    context: walkers, cyclists, cars, buses, trains and aircraft
  - quantity: density
    unit: g/cm^3
    min: 0.01
    max: 25
    context: common solids and liquids
  - quantity: time
    unit: min
    min: 0
    max: 2880
    context: journey times and intervals read from clocks and timetables
  - quantity: exchange_rate
    unit: dimensionless
    min: 0.0001
    max: 20000
    context: units of one currency for one unit of another
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds the value of one part, one unit or the multiplier before scaling
  - The student chooses to multiply or divide by deciding whether the answer should be larger or smaller
  - The student gives a checked answer with its unit, rounded only at the last step
---

# Number in use: ratio, rates, percentages, time and money

## When to use

Use when a question shares an amount in a ratio, scales a quantity in direct or inverse proportion, asks for a
speed, density or unit price, a percentage increase or decrease, an original amount before a change, a time
interval, a currency conversion, or simple or compound interest, growth or decay.

Not for: converting or ordering fractions, decimals and percentages, rounding or bounds; use mth-o-number.

## What this skill does not do

- It does not give financial advice; amounts and rates are fictional and come from the question.
- It does not use formulas the student cannot explain; every step comes from one part, one unit or a multiplier.
- It does not set the exchange rate or the interest rate; the question gives them.

## Objectives

1. The student finds the value of one part, one unit or the multiplier before scaling.
2. The student chooses to multiply or divide by deciding whether the answer should be larger or smaller.
3. The student gives a checked answer with its unit, rounded only at the last step.

## Prerequisite probe

- "Write 15% as a decimal." Expected: 0.15.
- "Work out 3/5 of 40." Expected: 24.

If either fails, detour to fractions, decimals and percentages in mth-o-number, then return.

## Teaching sequence

1. Ask the student to list the givens with their units and to mark the quantity asked for. Done when every given has a unit or a label.
2. Ask for the key number: one part of the ratio, the amount for one unit, the rate, or the multiplier such as 1.15 for a 15% rise. Done when the key number matches math_evaluate.
3. Ask whether the answer should be larger or smaller than the starting amount, then whether to multiply or divide. Done when the operation is stated with that reason.
4. For a time, ask the student to count hours and minutes separately, and to divide minutes by 60 when a rate is per hour. Done when the time is in the unit the rate uses.
5. Ask the student to finish with full calculator values; the math_evaluate result is the reference value. Done when the unrounded value matches the checked value.
6. Ask for the final answer rounded as asked, money to 2 decimal places, with its unit. Done when the rounded answer and unit match the key.

## Hint ladder

1. Orient: "What are you given, and what does the question want?"
2. Concept: name the idea, such as "a 15% rise means the new amount is 115% of the old".
3. First step: ask for one part, one unit or the multiplier only.
4. Worked step: show the key number and ask for the scaled answer.
5. Full step: show the checked answer; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.ratio_one_part`: stops at the value of one part → "How many parts does this person get?"
- `mc.mth.o.proportion_additive`: adds the difference instead of scaling → "If 4 cost 10, should 8 cost 14 or 20?"
- `mc.mth.o.rate_inverted`: divides volume by mass for a density → "Density is grams in each cubic centimetre. Which goes on top?"
- `mc.mth.o.minutes_as_hours`: uses 45 minutes as 45 hours in a km/h speed → "What fraction of an hour is 45 minutes?"
- `mc.mth.o.percent_change_new_base`: divides the change by the new value → "What amount did the change start from?"
- `mc.mth.o.reverse_percent_of_new`: takes 20% off a price that had 20% added → "Is 20% of the new price the same as 20% of the old one?"
- `mc.mth.o.time_as_decimal`: subtracts times as if an hour had 100 minutes → "How many minutes make one hour?"
- `mc.mth.o.exchange_wrong_operation`: multiplies by the rate when converting back → "Should the number of units get bigger or smaller this way?"
- `mc.mth.o.percent_not_divided`: uses 4% as 4 in a formula → "What is 4% written as a decimal?"
- `mc.mth.o.compound_times_years`: uses 1.05 × 3 for three years of growth → "What does multiplying by 1.05 three times in a row give?"

## Confidence and escalation

- Two wrong choices of multiply or divide: switch to a bar model or a two-row table of matching amounts, then ask again.
- Three failures on percentages: detour to fractions, decimals and percentages in mth-o-number.
- A time across midnight or a 12-hour clock with no am or pm: ask the student which day each time is on before going on.
- A tax, bank or currency rule the student says applies locally: save the question for human help.

## Worked exchange

> Tutor: $2,000 is saved at 5% per year compound interest. What is the amount after 3 years? What multiplier gives one year of growth?
> Student: 1.05.
> Tutor: Good. How do you apply it for 3 years?
> Student: Multiply by 1.05 three times, so 2,000 × 1.05³.
> Tutor: Work it out and keep the cents.
> Student: $2,315.25.
> Tutor: That's right (checked with the maths tool). The interest alone is $315.25 (checked), so read which one the question asks for.

## Verification checklist

- Every number shown comes from the question or matches a math_evaluate result.
- Ratio shares add up to the total; a percentage change is divided by the original amount.
- A reverse percentage divides by the multiplier, and the result times the multiplier gives the new amount.
- Times are in the unit the rate uses; money is given to 2 decimal places.
- No value was rounded before the last step.
