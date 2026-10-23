---
name: mth-o-trigonometry
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach Pythagoras, right-angled trigonometry and the sine and cosine rules
description: "pythagoras, sine, cosine, tangent, sine rule, cosine rule, elevation and depression, 3D: label the sides, pick the relation, check the size. Not for: angle facts or circle theorems (mth-o-geometry), or vector lengths (mth-o-transformations-and-vectors)."
subject: mathematics
levels: [O]
topics: [pythagoras, sine, cosine, tangent, sine rule, cosine rule, elevation and depression, triangle area, 3d trigonometry]
kcs:
  - kc.mth.o.trigonometry.pythagoras
  - kc.mth.o.trigonometry.trig_side
  - kc.mth.o.trigonometry.trig_angle
  - kc.mth.o.trigonometry.elevation_depression
  - kc.mth.o.trigonometry.sine_rule
  - kc.mth.o.trigonometry.cosine_rule
  - kc.mth.o.trigonometry.triangle_area_sine
  - kc.mth.o.trigonometry.three_d
curriculum_refs: [MTH-O-06.01, MTH-O-06.02, MTH-O-06.03, MTH-O-06.04]
prerequisites:
  - kc.mth.o.number.powers_and_roots
  - kc.mth.o.algebra_and_graphs.change_subject
  - kc.mth.o.mensuration.area_perimeter
related: [mth-o-geometry, mth-o-transformations-and-vectors]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, geom_figure]
visuals: [geometry_figure, unit_circle]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: length
    unit: m
    min: 0.001
    max: 10000
    context: sides of triangles, heights of trees and buildings, distances across land and inside solids
  - quantity: angle
    unit: degree
    min: 0
    max: 180
    context: angles in triangles, including angles of elevation and depression
  - quantity: area
    unit: m^2
    min: 0.000001
    max: 10000000
    context: areas of triangles from small drawings to fields
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student labels the sides from the given angle or marks the right angle before choosing a relation
  - The student chooses Pythagoras, a ratio, the sine rule or the cosine rule to fit the givens and the unknown
  - The student reaches a checked answer in degrees mode, with a length shorter than the hypotenuse where there is one
---

# Trigonometry: right-angled and other triangles

## When to use

Use when a problem asks for a missing side or angle of a triangle, a height from an angle of elevation or depression,
the area of a triangle from two sides and the included angle, or a length or angle inside a cuboid or pyramid.

Not for: angle facts, polygons or circle theorems (use mth-o-geometry), or the length of a column vector (use
mth-o-transformations-and-vectors).

## What this skill does not do

- It does not use radians; every angle is in degrees.
- It does not treat the ambiguous case of the sine rule.
- It does not draw the triangle for the student in a 3D problem; it asks the student to pick out the flat triangle.

## Objectives

1. The student labels the sides from the given angle or marks the right angle before choosing a relation.
2. The student chooses Pythagoras, a ratio, the sine rule or the cosine rule to fit the givens and the unknown.
3. The student reaches a checked answer in degrees mode, with a length shorter than the hypotenuse where there is one.

## Prerequisite probe

- "What is the square root of 169?" Expected: 13.
- "Make x the subject of 0.5 = x/8 and find x." Expected: x = 8 × 0.5 = 4.

If either fails, step back to roots or to changing the subject, then return.

## Teaching sequence

1. Ask the student to sketch the triangle and mark the right angle, or say there is none. Done when the sketch shows it.
2. Ask the student to label the sides from the marked angle: hypotenuse, opposite, adjacent, or a, b, c opposite A, B, C. Done when each side has a label.
3. Ask which relation uses the givens and the unknown and nothing else unknown. Done when the student names one relation.
4. Ask the student to substitute and rearrange before any calculating. Done when the unknown is the subject.
5. Ask the student to work it out in degrees; the math_evaluate result is the reference value. Done when the student's value matches the checked value.
6. Ask for a size check: the hypotenuse is the longest side and the largest angle faces the longest side. Done when the student states the check.

## Hint ladder

1. Orient: "Is there a right angle, and which side or angle is asked for?"
2. Concept: name the relation, such as "the sine of an angle is the opposite side over the hypotenuse".
3. First step: write the relation with the labels and ask the student to put the numbers in.
4. Worked step: show the rearranged line and ask the student for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.pythag_add_for_leg`: adds the squares when the hypotenuse is given → "Should the missing side be longer or shorter than the hypotenuse?"
- `mc.mth.o.pythag_no_root`: stops at the sum of the squares → "Is that number the side, or the side squared?"
- `mc.mth.o.calculator_radians`: gets wrong ratios from radians mode → "What does your calculator give for sin 30°?"
- `mc.mth.o.trig_ratio_wrong`: labels the sides from the wrong angle → "Which side is across from the angle you are using?"
- `mc.mth.o.trig_rearrange_wrong`: multiplies when the unknown is on the bottom → "If 0.5 = 6/x, is x bigger or smaller than 6?"
- `mc.mth.o.trig_ratio_inverted`: uses adjacent over opposite in tan⁻¹ → "Which side goes on top in tangent?"
- `mc.mth.o.depression_from_vertical`: measures depression from the vertical → "From which line does the observer look down?"
- `mc.mth.o.eye_height_ignored`: leaves out the observer's eye height → "Does your triangle start at the ground or at the eye?"
- `mc.mth.o.sine_rule_inverted`: pairs a side with an angle that is not opposite it → "Which angle faces this side?"
- `mc.mth.o.cosine_rule_sign`: adds 2bc cos A → "When A is 90°, what must the cosine rule turn into?"
- `mc.mth.o.three_d_two_dimensions`: gives the base diagonal as the space diagonal → "Does that line go up through the solid or stay on the floor?"

## Confidence and escalation

- Two failures choosing a ratio: switch representation and recolour the opposite, adjacent and hypotenuse sides.
- Three failures rearranging: detour to changing the subject of a formula, then return.
- A 3D figure the student cannot picture: save a local question for human help.

## Worked exchange

> Tutor: In a right-angled triangle the hypotenuse is 12 cm and one angle is 35°. Find the side opposite the 35° angle. Which sides do you have?
> Student: The hypotenuse, and I want the opposite.
> Tutor: Good. Which ratio links the opposite and the hypotenuse?
> Student: Sine, so sin 35° = x/12 and x = 12 × sin 35°.
> Tutor: Work it out in degrees mode.
> Student: 6.88 cm.
> Tutor: Right (checked with the maths tool), and it is shorter than the hypotenuse, as it must be.

## Verification checklist

- Every number shown comes from the question or from a math_evaluate check in degrees.
- A missing side of a right-angled triangle is shorter than its hypotenuse.
- The largest angle is opposite the longest side.
- An angle of elevation or depression is measured from the horizontal.
- Lengths are given to 3 significant figures and inexact angles to 1 decimal place.
- A figure drawn for the student takes its lengths, angles and points from a geom_figure result.
