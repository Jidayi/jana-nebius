---
name: mth-o-number
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach number work from primes and sets to indices, bounds and surds
description: "Prime factors, HCF and LCM, Venn diagrams, fractions, indices, standard form, rounding, bounds, surds: name the rule, apply it one line at a time and check each value. Not for: ratio, percentage change, rates, time or interest (mth-o-number-applied)."
subject: mathematics
levels: [O]
topics: [number, prime factors, hcf and lcm, venn diagrams, fractions, decimals, percentages, indices, standard form, rounding, bounds, surds]
kcs:
  - kc.mth.o.number.prime_factors
  - kc.mth.o.number.hcf_lcm
  - kc.mth.o.number.venn_counting
  - kc.mth.o.number.powers_and_roots
  - kc.mth.o.number.fraction_arithmetic
  - kc.mth.o.number.fdp_conversion
  - kc.mth.o.number.ordering_quantities
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.index_laws_numeric
  - kc.mth.o.number.standard_form_convert
  - kc.mth.o.number.standard_form_calc
  - kc.mth.o.number.estimation
  - kc.mth.o.number.bounds
  - kc.mth.o.number.bounds_calc
  - kc.mth.o.number.rounding
  - kc.mth.o.number.surds
curriculum_refs: [MTH-O-01.01, MTH-O-01.02, MTH-O-01.03, MTH-O-01.04, MTH-O-01.05, MTH-O-01.06, MTH-O-01.07, MTH-O-01.08, MTH-O-01.09, MTH-O-01.10, MTH-O-01.14, MTH-O-01.18]
prerequisites: []
related: [mth-o-number-applied]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate]
visuals: [venn_diagram, number_line]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: highest_common_factor
    unit: dimensionless
    min: 1
    max: 1000
    context: HCF of two whole numbers in school questions
  - quantity: lowest_common_multiple
    unit: dimensionless
    min: 1
    max: 100000
    context: LCM of two whole numbers in school questions
  - quantity: set_count
    unit: dimensionless
    min: 0
    max: 1000
    context: number of members in one region of a two-set Venn diagram
  - quantity: percentage
    unit: percent
    min: 0
    max: 1000
    context: a fraction or decimal written as a percentage
  - quantity: standard_form_index
    unit: dimensionless
    min: -30
    max: 30
    context: the power of ten for very large or very small school quantities
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the rule a number question needs before calculating
  - The student writes the working one line at a time, each line matching a checked value
  - The student gives the answer in the form and accuracy the question asks for
---

# Number: primes, fractions, indices, bounds and surds

## When to use

Use when a question asks for prime factors, an HCF or LCM, a count from a Venn diagram, a power or root, a fraction
calculation, a conversion or ordering of fractions, decimals and percentages, an index, standard form, an estimate,
a rounded value, a bound, or a simplified surd.

Not for: sharing in a ratio, proportion, rates, percentage increase, time, exchange or interest; use mth-o-number-applied.

## What this skill does not do

- It does not let the calculator replace the rule; the student says the rule first.
- It does not treat algebraic indices or algebraic fractions.
- It does not choose the accuracy: the question gives it, or the pack default of 3 significant figures applies.

## Objectives

1. The student names the rule a number question needs before calculating.
2. The student writes the working one line at a time, each line matching a checked value.
3. The student gives the answer in the form and accuracy the question asks for.

## Prerequisite probe

- "Work out 3 + 4 × 2²." Expected: 19.
- "Which is larger, 0.7 or 0.65?" Expected: 0.7.

If either fails, start with the order of operations or place value in this skill, then return.

## Teaching sequence

1. Ask the student to name the type of question and the form the answer must take. Done when the type and the answer form are on the board.
2. Ask the student to state the rule in words, such as "a negative index means one over the positive power". Done when the rule is stated.
3. Ask for the first line only: a factor tree, a common denominator, each value rounded to 1 significant figure, each bound, or the square factor. Done when math_evaluate confirms that line.
4. Ask the student to finish one line at a time; the math_evaluate result is the reference value for every number. Done when each line matches its checked value.
5. Ask for the asked form: primes in index form, lowest terms, 1 ≤ a < 10 in standard form, the smallest whole number under the root, or the stated rounding. Done when the form matches the question.

## Hint ladder

1. Orient: "What does the question ask for, and in what form?"
2. Concept: name the rule in words, such as "the HCF takes each shared prime with its smaller power".
3. First step: write the first line with a gap and ask the student to fill it.
4. Worked step: show the first line worked and ask for the next.
5. Full step: show the checked working; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.composite_factor_used`: leaves 4, 6 or 9 in a prime factorisation → "Can that factor be split any further?"
- `mc.mth.o.lcm_as_product`: multiplies the two numbers for the LCM → "Is there a smaller number that both divide into?"
- `mc.mth.o.venn_double_count`: adds n(A) and n(B) for the union → "Which members did you count twice?"
- `mc.mth.o.decimal_square_place_value`: squares 0.3 to get 0.9 → "What is 3 tenths times 3 tenths, in hundredths?"
- `mc.mth.o.add_tops_and_bottoms`: adds numerators and adds denominators → "Is a half plus a half really two quarters?"
- `mc.mth.o.percent_scale_wrong`: multiplies by 100 to turn a percentage into a decimal → "Should 40% be more or less than 1?"
- `mc.mth.o.longer_decimal_larger`: thinks 0.625 is bigger than 0.7 → "How many tenths does each number have?"
- `mc.mth.o.negative_squared_negative`: gives (−3)² as −9 → "What sign do you get when two negatives multiply?"
- `mc.mth.o.negative_index_negative`: gives 2⁻³ as −8 → "What do you get from 2³ ÷ 2⁶, written as a fraction?"
- `mc.mth.o.sf_power_sign`: uses a positive power of ten for a small number → "Is this number bigger or smaller than 1?"
- `mc.mth.o.estimate_not_one_sf`: rounds to whole numbers before estimating → "What is each number to 1 significant figure?"
- `mc.mth.o.bound_full_unit`: adds a whole unit to get the upper bound → "Which values round to this one, and where is the halfway point?"
- `mc.mth.o.bounds_same_ends`: uses both upper bounds for the largest difference → "To make a difference as big as possible, should the second number be big or small?"
- `mc.mth.o.leading_zeros_significant`: counts the zeros in 0.00456 as significant → "Where is the first digit that is not zero?"
- `mc.mth.o.surd_add_under_root`: writes √50 + √18 as √68 → "Is √9 + √16 equal to √25?"

## Confidence and escalation

- Two wrong forms of answer: show the asked form on the number_line or as a model answer shape, then ask again.
- Three failures on the same rule: detour to order of operations or place value, then return.
- A Venn count that does not add to the total: draw the venn_diagram and fill the overlap first.
- A rule the student says the local syllabus states differently: save the question for human help.

## Worked exchange

> Tutor: Find the HCF and the LCM of 84 and 90. Start by writing each as a product of primes.
> Student: 84 = 2² × 3 × 7 and 90 = 2 × 3² × 5.
> Tutor: Good. For the HCF, take each shared prime with its smaller power. What do you get?
> Student: 2 × 3, so the HCF is 6.
> Tutor: Right. For the LCM, take every prime with its larger power.
> Student: 2² × 3² × 5 × 7, which is 1,260.
> Tutor: That's right (checked with the maths tool), and 6 × 1,260 equals 84 × 90 (checked).

## Verification checklist

- Every number shown comes from the question or matches a math_evaluate result.
- A prime factorisation multiplies back to the number and contains primes only.
- Standard form has a front number from 1 up to but not including 10.
- Rounding uses the question's accuracy, else 3 significant figures; bounds use half the unit of accuracy.
- A surd answer has no square factor under the root and no root left in a denominator.
