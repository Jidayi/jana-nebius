---
name: mth-o-geometry
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach angle facts, polygons, circle theorems, scales, bearings and similarity
description: "angles, polygons, circle theorems, bearings, similar shapes, symmetry, map scales: name the fact behind every angle or length, then check it. Not for: Pythagoras or trig (mth-o-trigonometry), area formulas (mth-o-mensuration), transformations (mth-o-transformations-and-vectors)."
subject: mathematics
levels: [O]
topics: [angles, polygons, circle theorems, bearings, similar shapes, symmetry, map scales, constructions]
kcs:
  - kc.mth.o.geometry.shape_properties
  - kc.mth.o.geometry.constructions
  - kc.mth.o.geometry.map_scales
  - kc.mth.o.geometry.bearings
  - kc.mth.o.geometry.similar_lengths
  - kc.mth.o.geometry.similar_area_volume
  - kc.mth.o.geometry.symmetry
  - kc.mth.o.geometry.angle_facts
  - kc.mth.o.geometry.parallel_line_angles
  - kc.mth.o.geometry.triangle_angles
  - kc.mth.o.geometry.polygon_angles
  - kc.mth.o.geometry.circle_theorems_basic
  - kc.mth.o.geometry.circle_theorems_cyclic
curriculum_refs: [MTH-O-04.01, MTH-O-04.02, MTH-O-04.03, MTH-O-04.04, MTH-O-04.05, MTH-O-04.06, MTH-O-04.07, MTH-O-04.08]
prerequisites:
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.direct_proportion
  - kc.mth.o.number.ratio_share
  - kc.mth.o.number.powers_and_roots
related: [mth-o-trigonometry, mth-o-mensuration, mth-o-transformations-and-vectors]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, geom_figure]
visuals: [geometry_figure, bearing_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: angle
    unit: degree
    min: 0
    max: 360
    context: angles at points, on lines, in triangles, polygons and circles
  - quantity: angle_sum
    unit: degree
    min: 180
    max: 3600
    context: interior angle sums of polygons with 3 to 22 sides
  - quantity: bearing
    unit: degree
    min: 0
    max: 360
    context: three-figure bearings and back bearings
  - quantity: distance
    unit: km
    min: 0.01
    max: 2000
    context: real distances found from map scales
  - quantity: length
    unit: cm
    min: 0.01
    max: 100000
    context: sides of similar shapes and lengths on scale drawings
  - quantity: scale_factor
    unit: dimensionless
    min: 0.01
    max: 100
    context: length scale factors between similar shapes
  - quantity: area
    unit: cm^2
    min: 0.01
    max: 10000000
    context: areas of similar shapes
  - quantity: volume
    unit: cm^3
    min: 0.01
    max: 10000000
    context: volumes of similar solids
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the geometric fact that justifies each angle or length before calculating it
  - The student uses the correct total, scale factor or power of the scale factor for the situation
  - The student reaches a checked answer with a unit or a three-figure bearing that fits the figure
---

# Geometry: angles, circles, scales and similar shapes

## When to use

Use when a problem asks for a missing angle at a point, on a line, at parallel lines, in a triangle, a polygon or a
circle; a bearing or back bearing; a real length from a map scale; a missing length, area or volume of similar shapes;
lines or order of symmetry; the name of a shape from its properties; or the steps of a ruler-and-compasses construction.

Not for: Pythagoras or trigonometry (use mth-o-trigonometry), area and volume formulas (use mth-o-mensuration),
or moving shapes on a grid (use mth-o-transformations-and-vectors).

## What this skill does not do

- It does not write formal proofs; a short reason after each angle is enough.
- It does not measure from the figure; diagrams are not drawn to scale unless the question says so.
- It does not draw constructions; it checks the order of the steps in words.

## Objectives

1. The student names the geometric fact that justifies each angle or length before calculating it.
2. The student uses the correct total, scale factor or power of the scale factor for the situation.
3. The student reaches a checked answer with a unit or a three-figure bearing that fits the figure.

## Prerequisite probe

- "Share 30 in the ratio 2 : 3." Expected: 12 and 18.
- "Work out 360 − 3 × 75." Expected: 135.

If either fails, step back to ratio or to the order of operations, then return.

## Teaching sequence

1. Ask the student to mark every given angle or length on the figure and the one asked for. Done when the unknown is marked.
2. Ask which fact links the givens to the unknown: a total (180°, 360°), equal angles, a circle theorem, a scale or a scale factor. Done when the student names one fact in words.
3. Ask the student to write the calculation with the fact as its reason. Done when the line and its reason are on the board.
4. Ask the student to work it out; the math_evaluate result is the reference value. Done when the student's value matches the checked value.
5. For similar shapes, ask whether the quantity is a length, an area or a volume before using k, k² or k³. Done when the power matches the quantity.
6. Ask for a sense check: an acute angle looks acute, a bearing has three figures and lies from 000° to 360°. Done when the student states the check.

## Hint ladder

1. Orient: "Which angles or lengths do you know, and which one is asked for?"
2. Concept: name the fact, such as "angles in a triangle add up to 180°".
3. First step: write the fact as an equation and ask the student to fill in the known values.
4. Worked step: show the equation with values and ask the student for the result.
5. Full step: show the checked result and the reason; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.square_not_rectangle`: says a square cannot also be a rectangle → "Does a square have four right angles and opposite sides equal, as every rectangle must?"
- `mc.mth.o.construction_radius_changed`: changes the compass width between the two arcs → "If the arcs come from different widths, where will they cross?"
- `mc.mth.o.scale_wrong_direction`: divides the map length by the scale → "Is the real road longer or shorter than the line on the map?"
- `mc.mth.o.back_bearing_from_360`: takes the bearing from 360° for the way back → "Facing back the other way, how many degrees have you turned?"
- `mc.mth.o.similar_additive`: adds the difference between sides → "If one side doubles, what happens to every other side?"
- `mc.mth.o.similar_length_factor_for_area`: uses k for an area → "A square with sides twice as long holds how many of the small squares?"
- `mc.mth.o.rotation_order_zero`: gives order 0 to a shape with no turn symmetry → "After one full turn, does the shape look the same again?"
- `mc.mth.o.line_angles_360`: uses 360° on a straight line → "How many degrees is a half turn?"
- `mc.mth.o.cointerior_equal`: makes co-interior angles equal → "One angle is acute and the other obtuse; can they be equal?"
- `mc.mth.o.isosceles_not_halved`: gives 180° minus the top angle as one base angle → "That remainder is shared between how many angles?"
- `mc.mth.o.polygon_sum_n_180`: uses n × 180° → "How many triangles fit inside the polygon from one corner?"
- `mc.mth.o.centre_angle_halved`: halves the angle at the circumference for the centre → "Which angle is bigger, the one at the centre or the one at the edge?"
- `mc.mth.o.cyclic_opposite_equal`: makes opposite angles of a cyclic quadrilateral equal → "What do opposite angles of a cyclic quadrilateral add up to?"

## Confidence and escalation

- Two failures naming a fact: switch representation and redraw the figure with only the angles that matter.
- Three failures on a total such as 180° or 360°: detour to angles at a point and on a line, then return.
- A figure the student cannot describe in words: save a local question for human help.

## Worked exchange

> Tutor: In triangle PQR, PQ = PR and angle QPR is 40°. Find angle PQR. Which angles are equal?
> Student: The angles at Q and R, because PQ and PR are the equal sides.
> Tutor: Good. What do the three angles add up to, and what is left after 40°?
> Student: 180 − 40, so 140°.
> Tutor: Is 140° one angle or two angles together?
> Student: Two, so angle PQR is 140 ÷ 2 = 70°.
> Tutor: Right (checked with the maths tool), and 70° is acute, as the figure shows.

## Verification checklist

- Every number shown comes from the question or from a math_evaluate check.
- Each angle carries a reason that names the fact used.
- A bearing has three figures and lies from 000° to 360°.
- Similar shapes use k for lengths, k² for areas and k³ for volumes.
- Inexact angles are given to 1 decimal place and other values to 3 significant figures.
- A figure drawn for the student takes its lengths, angles and points from a geom_figure result.
