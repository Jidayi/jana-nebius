---
name: mth-o-calculus
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach differentiating powers, tangents, stationary points and definite integrals
description: "Differentiation, gradient of a curve, tangents, normals, stationary points, definite integrals, area under a curve: use the power rule term by term and check with the tool. Not for: gradients of straight lines (mth-o-coordinate-geometry) or travel graphs (mth-o-algebra-and-graphs)."
subject: mathematics
levels: [O]
topics: [calculus, differentiation, derivative, gradient of a curve, tangents, normals, stationary points, integration, definite integrals, area under a curve]
kcs:
  - kc.mth.o.calculus.differentiate_powers
  - kc.mth.o.calculus.tangents_normals
  - kc.mth.o.calculus.stationary_points
  - kc.mth.o.calculus.definite_integrals
curriculum_refs: [MTH-O-10.01, MTH-O-10.02]
prerequisites:
  - kc.mth.o.algebra_and_graphs.index_laws_algebra
  - kc.mth.o.algebra_and_graphs.quadratic_equations
  - kc.mth.o.coordinate_geometry.perpendicular_lines
related: [mth-o-coordinate-geometry, mth-o-algebra-and-graphs]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_differentiate, math_integrate, math_evaluate, math_solve]
visuals: [function_graph]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: gradient
    unit: dimensionless
    min: -1000
    max: 1000
    context: gradient of a polynomial curve at a point in school questions
  - quantity: coordinate
    unit: dimensionless
    min: -1000
    max: 1000
    context: coordinates of stationary points and points of contact
  - quantity: definite_integral
    unit: dimensionless
    min: -10000
    max: 10000
    context: value of a definite integral of a polynomial over a short interval
  - quantity: area_under_curve
    unit: dimensionless
    min: 0
    max: 10000
    context: area between a polynomial curve and the x-axis, in square units
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student differentiates or integrates a sum of powers of x term by term
  - The student substitutes into the derivative, not the curve, to find a gradient
  - The student finds and classifies stationary points, or evaluates a definite integral as F(upper) − F(lower)
---

# Calculus: derivatives and definite integrals

## When to use

Use when a question asks for dy/dx of a sum of powers of x, the gradient of a curve at a point, the equation of a
tangent or a normal, the stationary points of a curve and their nature, a definite integral, or the area between a
curve and the x-axis.

Not for: gradients of straight lines from two points (mth-o-coordinate-geometry), or speeds and distances from travel
graphs (mth-o-algebra-and-graphs).

## What this skill does not do

- It does not treat the chain, product or quotient rules.
- It does not differentiate from first principles.
- It does not integrate anything other than powers of x.

## Objectives

1. The student differentiates or integrates a sum of powers of x term by term.
2. The student substitutes into the derivative, not the curve, to find a gradient.
3. The student finds and classifies stationary points, or evaluates a definite integral as F(upper) − F(lower).

## Prerequisite probe

- "Write 1/x² as a power of x." Expected: x⁻².
- "Solve x² − 4 = 0." Expected: x = 2 or x = −2.

If either fails, detour to index laws or quadratic equations in mth-o-algebra-and-graphs, then return.

## Teaching sequence

1. Ask the student to write each term as a number times a power of x. Done when every term is in that form.
2. Ask for the derivative term by term: bring the power down as a multiplier, then lower the power by one; a constant gives 0. Done when the derivative matches math_differentiate.
3. For a gradient, tangent or normal, ask the student to substitute x into dy/dx; the normal's gradient is −1 over the tangent's. Done when the gradient matches math_evaluate and the line passes through the point.
4. For stationary points, ask the student to solve dy/dx = 0, then find y from the curve; math_solve gives the reference x-values. Done when each point matches.
5. Ask the student to classify each point: a positive second derivative means a minimum, a negative one a maximum. Done when each point is named and the second derivative matches math_differentiate.
6. For an integral, ask for each term raised by one power and divided by the new power, then F(upper) − F(lower). Done when the value matches math_integrate.

## Hint ladder

1. Orient: "Does the question want a gradient, a stationary point or an area?"
2. Concept: name the rule, such as "multiply by the power, then take one off the power".
3. First step: ask for the derivative of the first term only.
4. Worked step: show the full derivative and ask what to do with it.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.derivative_power_not_brought_down`: differentiates 4x³ as 4x² → "What happens to the power when it comes down?"
- `mc.mth.o.derivative_constant_kept`: keeps the +5 in the derivative → "What is the gradient of the flat line y = 5?"
- `mc.mth.o.gradient_from_y`: puts x into the curve to find a gradient → "Which expression tells you the gradient, y or dy/dx?"
- `mc.mth.o.normal_gradient_as_tangent`: uses the tangent's gradient for the normal → "The normal is at right angles to the tangent. What do their gradients multiply to?"
- `mc.mth.o.stationary_from_y_zero`: solves y = 0 for stationary points → "At a stationary point, what is zero: the height or the gradient?"
- `mc.mth.o.max_min_confused`: calls a point with a positive second derivative a maximum → "Does y = x² have a maximum or a minimum at the origin, and what is its second derivative?"
- `mc.mth.o.integral_power_not_divided`: integrates x² as x³ → "If you differentiate x³, do you get back x²?"
- `mc.mth.o.integral_limits_reversed`: works out F(lower) − F(upper) → "Which limit comes first in F(upper) − F(lower)?"

## Confidence and escalation

- Two failures choosing between y and dy/dx: show the function_graph with the tangent at the point, then ask again.
- Three failures on the power rule: detour to index laws in mth-o-algebra-and-graphs.
- An area with part of the curve below the x-axis: ask the student to split the interval at the root before integrating.
- A method the student says the local syllabus requires, such as a sign table: save the question for human help.

## Worked exchange

> Tutor: Find the stationary points of y = x³ − 3x² + 4. What is dy/dx?
> Student: 3x² − 6x.
> Tutor: Good. Where are the stationary points?
> Student: Where y = 0, so solve x³ − 3x² + 4 = 0.
> Tutor: A stationary point is where the gradient is zero. Which expression gives the gradient?
> Student: dy/dx, so 3x² − 6x = 0 gives x = 0 or x = 2, and y = 4 or y = 0.
> Tutor: That's right (checked with the maths tool): (0, 4) is a maximum and (2, 0) is a minimum.

## Verification checklist

- The derivative matches math_differentiate and the integral value matches math_integrate.
- Gradients come from dy/dx at the given x, not from the curve.
- Each stationary point satisfies dy/dx = 0 and lies on the curve; its nature matches the second derivative.
- An area is positive; a region below the x-axis was handled separately.
