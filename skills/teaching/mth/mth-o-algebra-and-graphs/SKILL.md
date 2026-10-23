---
name: mth-o-algebra-and-graphs
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach algebra from substitution to equations, graphs and functions
description: "Algebra, expressions, factorising, equations, inequalities, sequences, graphs, functions: one legal step per line, each checked before the next. Not for: gradients and straight-line equations (mth-o-coordinate-geometry) or differentiation (mth-o-calculus)."
subject: mathematics
levels: [O]
topics: [algebra, expressions, expanding brackets, factorising, equations, simultaneous equations, quadratic equations, inequalities, sequences, variation, graphs, functions]
kcs:
  - kc.mth.o.algebra_and_graphs.substitution
  - kc.mth.o.algebra_and_graphs.expand_brackets
  - kc.mth.o.algebra_and_graphs.factorise_common
  - kc.mth.o.algebra_and_graphs.factorise_quadratic
  - kc.mth.o.algebra_and_graphs.change_subject
  - kc.mth.o.algebra_and_graphs.algebraic_fractions
  - kc.mth.o.algebra_and_graphs.index_laws_algebra
  - kc.mth.o.algebra_and_graphs.linear_equations
  - kc.mth.o.algebra_and_graphs.simultaneous_equations
  - kc.mth.o.algebra_and_graphs.quadratic_equations
  - kc.mth.o.algebra_and_graphs.forming_equations
  - kc.mth.o.algebra_and_graphs.linear_inequalities
  - kc.mth.o.algebra_and_graphs.linear_sequences
  - kc.mth.o.algebra_and_graphs.quadratic_sequences
  - kc.mth.o.algebra_and_graphs.variation
  - kc.mth.o.algebra_and_graphs.travel_graphs
  - kc.mth.o.algebra_and_graphs.tables_of_values
  - kc.mth.o.algebra_and_graphs.graphical_solutions
  - kc.mth.o.algebra_and_graphs.quadratic_features
  - kc.mth.o.algebra_and_graphs.function_notation
curriculum_refs: [MTH-O-02.01, MTH-O-02.02, MTH-O-02.03, MTH-O-02.04, MTH-O-02.05, MTH-O-02.06, MTH-O-02.07, MTH-O-02.08, MTH-O-02.09, MTH-O-02.10, MTH-O-02.11, MTH-O-02.12]
prerequisites:
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.fraction_arithmetic
  - kc.mth.o.number.index_laws_numeric
  - kc.mth.o.number.direct_proportion
  - kc.mth.o.number.rates
  - kc.mth.o.coordinate_geometry.gradient
related: [mth-o-coordinate-geometry, mth-o-calculus, mth-o-number]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_check_equivalence, math_solve]
visuals: [function_graph, number_line]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: solution
    unit: dimensionless
    min: -1000
    max: 1000
    context: values of x or y that solve school equations and inequalities
  - quantity: speed
    unit: m/s
    min: 0
    max: 300
    context: speeds read from travel graphs, from walkers to aircraft
  - quantity: acceleration
    unit: m/s^2
    min: -50
    max: 50
    context: gradients of speed-time graphs for vehicles and runners
  - quantity: distance
    unit: km
    min: 0
    max: 5000
    context: distances on travel graphs, from short walks to long journeys
  - quantity: time
    unit: hour
    min: 0
    max: 48
    context: journey times on travel graphs
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student writes one legal step per line, each equivalent to the line before
  - The student checks a solution by substituting it into the original equation
  - The student reads a graph by naming the point, gradient or area the question needs
---

# Algebra and graphs

## When to use

Use when a question asks to substitute into a formula, expand, factorise, simplify, change the subject, solve a
linear, simultaneous or quadratic equation or an inequality, find an nth term, use variation, read a travel graph,
complete a table of values, solve with graphs, find a turning point, or work with f(x), fg(x) or f⁻¹(x).

Not for: gradients, lengths and equations of straight lines (mth-o-coordinate-geometry), or derivatives and
integrals (mth-o-calculus).

## What this skill does not do

- It does not skip lines: each line is one step the student can name.
- It does not plot graphs for the student; values come from the student's table, checked by the tool.
- It does not teach completing the square beyond finding a turning point.

## Objectives

1. The student writes one legal step per line, each equivalent to the line before.
2. The student checks a solution by substituting it into the original equation.
3. The student reads a graph by naming the point, gradient or area the question needs.

## Prerequisite probe

- "Work out 2 × 3² − 4." Expected: 14.
- "Work out −5 + 8, then −5 × −2." Expected: 3, then 10.

If either fails, detour to order of operations and negative numbers in mth-o-number, then return.

## Teaching sequence

1. Ask the student to name the task: substitute, expand, factorise, rearrange, solve, find a term, or read a graph. Done when the task is named.
2. For an expression, ask for one step per line; math_check_equivalence confirms each line equals the one before. Done when every line is confirmed.
3. For an equation or inequality, ask for one inverse operation per line on both sides; the math_solve result is the reference solution. Done when the student's solution matches math_solve.
4. For a term, a constant k, a table value or a function value, ask for the substitution line; math_evaluate gives the reference value. Done when each value matches.
5. For a graph, ask which feature the question needs: a meeting point, a crossing point, a turning point, a gradient or an area. Done when the feature is named and its value matches math_solve or math_evaluate.
6. Ask the student to substitute the answer back into the original equation. Done when both sides agree.

## Hint ladder

1. Orient: "What is the task here: simplify, solve or read?"
2. Concept: name the rule, such as "do the same to both sides" or "the constant term is the product of the two numbers".
3. First step: write the first line with a gap for the student to fill.
4. Worked step: show the first line worked and ask for the next one.
5. Full step: show the checked working; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.negative_squared_negative`: substitutes x = −3 into x² and gets −9 → "What is −3 times −3?"
- `mc.mth.o.expand_missing_middle`: writes (x + 2)(x + 5) as x² + 10 → "Check with x = 1: do both sides give the same number?"
- `mc.mth.o.dots_not_rooted`: writes x² − 49 as (x − 49)(x + 49) → "What number squared gives 49?"
- `mc.mth.o.rearrange_wrong_order`: divides before subtracting when making x the subject of y = 3x + 4 → "Which was done to x last, so must be undone first?"
- `mc.mth.o.cancel_terms_not_factors`: cancels x² terms across a sum → "Is (x² + 2)/(x² + 5) the same as 2/5 when x = 1?"
- `mc.mth.o.coefficient_not_raised`: writes (2x³)⁴ with 8 in front → "What is 2 × 2 × 2 × 2?"
- `mc.mth.o.simultaneous_other_unknown`: gives y when x was asked for → "Which letter does the question ask about?"
- `mc.mth.o.root_sign_from_factor`: reads x = 3 from (x + 3) = 0 → "What value of x makes x + 3 equal zero?"
- `mc.mth.o.inequality_no_flip`: keeps the sign after dividing by −2 → "Is 2 < 6 still true after dividing both sides by −2?"
- `mc.mth.o.nth_term_first_as_coefficient`: puts the first term in front of n → "By how much does each term go up?"
- `mc.mth.o.second_difference_not_halved`: uses the second difference as the n² coefficient → "What second difference does n² give on its own?"
- `mc.mth.o.variation_power_ignored`: uses y = kx when y varies as x² → "What does the question say y varies as?"
- `mc.mth.o.gradient_for_area`: finds the gradient of a speed-time graph for a distance → "Is the question asking for a rate or a total?"
- `mc.mth.o.composite_order_reversed`: applies f first for fg(x) → "Which function touches x first in fg(x)?"

## Confidence and escalation

- Two failures on the same algebra move: test both lines with a small number such as x = 2, then ask again.
- Three failures on solving: detour to linear equations or to negative numbers.
- A graph question where the reading is unclear: show the function_graph and ask for the point first.
- An answer method the student says the local syllabus requires: save the question for human help.

## Worked exchange

> Tutor: Solve x² − x − 12 = 0 by factorising. Which two numbers multiply to −12 and add to −1?
> Student: −4 and 3, so (x − 4)(x + 3) = 0.
> Tutor: Good. What are the solutions?
> Student: x = −4 and x = 3.
> Tutor: Put x = −4 into the bracket x − 4. Does it give zero?
> Student: No, it gives −8. So x = 4 or x = −3.
> Tutor: That's right (checked with the maths tool): 16 − 4 − 12 = 0 and 9 + 3 − 12 = 0.

## Verification checklist

- Every simplified line passed math_check_equivalence against the line before.
- Every solution came from math_solve and satisfies the original equation.
- An inequality sign was reversed exactly when both sides were multiplied or divided by a negative.
- Graph readings name the axis, the unit and the point used.
