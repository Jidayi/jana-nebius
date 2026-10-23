---
name: mth-o-coordinate-geometry
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach straight lines on a grid with gradient, length, midpoint and equations
description: "Coordinate geometry, gradient, intercepts, midpoint, length of a line segment, parallel and perpendicular lines: label the points, subtract in one order, substitute and check. Not for: curves and graphical solutions (mth-o-algebra-and-graphs) or tangents to curves (mth-o-calculus)."
subject: mathematics
levels: [O]
topics: [coordinate geometry, straight lines, gradient, intercepts, midpoint, length of a line segment, equation of a line, parallel lines, perpendicular lines]
kcs:
  - kc.mth.o.coordinate_geometry.points_on_lines
  - kc.mth.o.coordinate_geometry.axis_intercepts
  - kc.mth.o.coordinate_geometry.gradient
  - kc.mth.o.coordinate_geometry.segment_length
  - kc.mth.o.coordinate_geometry.midpoint
  - kc.mth.o.coordinate_geometry.line_equation
  - kc.mth.o.coordinate_geometry.parallel_lines
  - kc.mth.o.coordinate_geometry.perpendicular_lines
curriculum_refs: [MTH-O-03.01, MTH-O-03.02, MTH-O-03.03, MTH-O-03.04, MTH-O-03.05, MTH-O-03.06, MTH-O-03.07]
prerequisites:
  - kc.mth.o.algebra_and_graphs.substitution
  - kc.mth.o.algebra_and_graphs.linear_equations
  - kc.mth.o.trigonometry.pythagoras
related: [mth-o-algebra-and-graphs, mth-o-calculus, mth-o-trigonometry]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve]
visuals: [function_graph]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: gradient
    unit: dimensionless
    min: -100
    max: 100
    context: gradients of straight lines through grid points in school questions
  - quantity: segment_length
    unit: dimensionless
    min: 0
    max: 500
    context: distance between two grid points, in grid units
  - quantity: coordinate
    unit: dimensionless
    min: -1000
    max: 1000
    context: intercepts, midpoints and missing coordinates on a school grid
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student labels the two points as (x₁, y₁) and (x₂, y₂) before using any formula
  - The student finds a gradient as the change in y over the change in x, subtracting in the same order
  - The student writes the line as y = mx + c and checks it with a given point
---

# Coordinate geometry of straight lines

## When to use

Use when a question gives points or a straight line on a grid and asks whether a point lies on the line, where the
line crosses the axes, its gradient, the length or midpoint of a segment, its equation, or a parallel or
perpendicular line.

Not for: plotting curves or solving equations with graphs (mth-o-algebra-and-graphs), or tangents and normals to
curves (mth-o-calculus).

## What this skill does not do

- It does not read values off a sketch unless the question marks them.
- It does not use the distance formula as a rule to memorise; length comes from Pythagoras on the two changes.
- It does not treat circles or curves.

## Objectives

1. The student labels the two points as (x₁, y₁) and (x₂, y₂) before using any formula.
2. The student finds a gradient as the change in y over the change in x, subtracting in the same order.
3. The student writes the line as y = mx + c and checks it with a given point.

## Prerequisite probe

- "Substitute x = −2 into y = 3x + 5." Expected: y = −1.
- "Solve 2x + 6 = 0." Expected: x = −3.

If either fails, detour to substitution or linear equations in mth-o-algebra-and-graphs; for lengths, to Pythagoras in mth-o-trigonometry.

## Teaching sequence

1. Ask the student to label the given points (x₁, y₁) and (x₂, y₂). Done when both points are labelled.
2. Ask for the change in x and the change in y, subtracting in the same order. Done when both changes match math_evaluate.
3. Ask for the quantity: gradient = change in y ÷ change in x, length = √(change in x² + change in y²), midpoint = half the sum of each coordinate; math_evaluate gives the reference value. Done when the value matches.
4. For an equation, ask for m first (the same m for a parallel line, −1/m for a perpendicular one), then substitute a point to find c; math_solve gives c. Done when y = mx + c has a checked m and c.
5. For intercepts, ask the student to put x = 0 for the y-intercept and y = 0 for the x-intercept; math_solve gives each value. Done when both intercepts match.
6. Ask the student to substitute a given point into the final equation. Done when both sides agree.

## Hint ladder

1. Orient: "Which two points do you have, and what does the question want?"
2. Concept: name the idea, such as "gradient is how far up for each one across".
3. First step: ask for the change in y and the change in x only.
4. Worked step: show the gradient worked and ask for c.
5. Full step: show the checked equation; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.coordinates_swapped`: puts the y-coordinate in place of x → "In (2, 7), which number goes with x?"
- `mc.mth.o.intercepts_swapped`: sets x = 0 to find the x-intercept → "On the x-axis, what is y always equal to?"
- `mc.mth.o.gradient_order_mixed`: subtracts in one order on top and the other below → "Did you start from the same point on the top and on the bottom?"
- `mc.mth.o.pythag_no_root`: gives the sum of the squares as the length → "Is that the length, or the length squared?"
- `mc.mth.o.midpoint_subtracted`: halves the difference of the coordinates → "Is the middle of 2 and 8 equal to 3?"
- `mc.mth.o.c_as_y_coordinate`: takes the point's y-coordinate as c → "Is the given point on the y-axis?"
- `mc.mth.o.parallel_same_intercept`: copies c from the given line → "Does the new line pass through the same point on the y-axis?"
- `mc.mth.o.perpendicular_reciprocal_only`: gives 1/m for a perpendicular gradient → "If one line goes up to the right, which way must the other go?"

## Confidence and escalation

- Two failures with gradients: switch to the function_graph and count squares up and across between the points.
- Three failures on the length: detour to Pythagoras in mth-o-trigonometry.
- A sign error that repeats: ask the student to write each coordinate in brackets before subtracting.
- A line form the student says the local syllabus prefers, such as ax + by = c: save the question for human help.

## Worked exchange

> Tutor: A line passes through A(1, 3) and B(4, 9). Find its equation. What is its gradient?
> Student: 9 − 3 over 4 − 1, which is 6 over 3, so 2.
> Tutor: Good. Now find c using point A.
> Student: c is 3, because the line goes through (1, 3).
> Tutor: Point A is at x = 1, so it is not on the y-axis. Put x = 1 and y = 3 into y = 2x + c.
> Student: 3 = 2 + c, so c = 1 and the line is y = 2x + 1.
> Tutor: That's right (checked with the maths tool), and B fits too: 2 × 4 + 1 = 9.

## Verification checklist

- The gradient, length and midpoint match math_evaluate; m and c match math_solve.
- The same point was subtracted first on the top and on the bottom of the gradient.
- Perpendicular gradients multiply to −1; parallel gradients are equal.
- The final equation is satisfied by every given point.
