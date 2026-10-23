---
name: mth-o-mensuration
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach perimeter, area, volume and surface area of flat shapes and solids
description: "area, perimeter, circles, arcs, sectors, volume, surface area, metric units: choose the formula, substitute with units, check the size. Not for: missing sides by Pythagoras or trig (mth-o-trigonometry), or scaling similar shapes (mth-o-geometry)."
subject: mathematics
levels: [O]
topics: [area, perimeter, circles, arcs and sectors, volume, surface area, metric units, compound shapes]
kcs:
  - kc.mth.o.mensuration.metric_units
  - kc.mth.o.mensuration.area_perimeter
  - kc.mth.o.mensuration.circle_measures
  - kc.mth.o.mensuration.arcs_sectors
  - kc.mth.o.mensuration.prism_volume
  - kc.mth.o.mensuration.pyramid_cone_sphere
  - kc.mth.o.mensuration.compound_shapes
curriculum_refs: [MTH-O-05.01, MTH-O-05.02, MTH-O-05.03, MTH-O-05.04, MTH-O-05.05]
prerequisites:
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.number.standard_form_convert
  - kc.mth.o.algebra_and_graphs.substitution
related: [mth-o-trigonometry, mth-o-geometry]
pedagogy: [pedagogy-worked-example-fade]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [units_convert, math_evaluate, geom_figure]
visuals: [geometry_figure, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: worked_example
plausibility:
  - quantity: length
    unit: m
    min: 0.001
    max: 10000
    context: sides, radii, heights, perimeters and arc lengths of school shapes, rooms, fields and tanks
  - quantity: area
    unit: m^2
    min: 0.00001
    max: 1000000
    context: areas and surface areas from small cards to farm fields
  - quantity: volume
    unit: m^3
    min: 0.000001
    max: 100000
    context: volumes of boxes, cans, cones, balls, tanks and swimming pools
  - quantity: angle
    unit: degree
    min: 0
    max: 360
    context: angles at the centre of sectors
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the shape or the parts of a compound shape and the formula for each before substituting
  - The student puts lengths in one unit, using the radius where a formula needs it
  - The student reaches a checked answer with a unit of the right power for a length, an area or a volume
---

# Mensuration: perimeter, area and volume

## When to use

Use when a problem asks for a perimeter, an area, an arc length, a sector area, a volume or a surface area of a flat
shape, a solid or a compound shape, or asks to change a length, area, volume or capacity from one metric unit to another.

Not for: finding a missing side with Pythagoras or trigonometry first (use mth-o-trigonometry), or scaling areas and
volumes of similar shapes (use mth-o-geometry).

## What this skill does not do

- It does not choose the value of π: the calculator value is used unless the question gives one.
- It does not find slant heights or perpendicular heights by Pythagoras; that belongs to the trigonometry skill.
- It does not expect formulas for cones and spheres to be recalled when the question supplies them.

## Objectives

1. The student names the shape or the parts of a compound shape and the formula for each before substituting.
2. The student puts lengths in one unit, using the radius where a formula needs it.
3. The student reaches a checked answer with a unit of the right power for a length, an area or a volume.

## Prerequisite probe

- "Find A = ½(a + b)h when a = 4, b = 6 and h = 5." Expected: 25.
- "How many centimetres are in 3.5 m?" Expected: 350.

If either fails, step back to substitution or to metric units, then return.

## Teaching sequence

1. Ask the student to sketch the shape and split a compound shape into simple parts. Done when each part is named.
2. Ask whether the question wants a length, an area or a volume. Done when the student names the kind and its unit power.
3. Ask the student to bring every length to one unit; the units_convert result is the reference value. Done when all lengths share a unit.
4. Ask for the formula for each part, with r as the radius and h as the perpendicular height. Done when each formula is written.
5. Ask the student to substitute and work it out; the math_evaluate result is the reference value. Done when the student's value matches the checked value.
6. Ask for the unit and a size check against the sketch. Done when the unit has the right power and the size is sensible.

## Hint ladder

1. Orient: "Is the question asking for a length, an area or a volume?"
2. Concept: name the formula in words, such as "a prism's volume is its cross-section area times its length".
3. First step: write the formula and ask the student to put the numbers in.
4. Worked step: show the substitution and ask the student for the value.
5. Full step: show the checked result with its unit; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.area_units_linear`: multiplies by 100 to change m² to cm² → "A 1 m square is how many centimetres along each side, and how many 1 cm squares fill it?"
- `mc.mth.o.unit_conversion_direction`: divides when going to a smaller unit → "Smaller units mean more of them; should the number grow or shrink?"
- `mc.mth.o.perimeter_area_confused`: adds sides for an area → "Are you measuring the fence around the field or the grass inside it?"
- `mc.mth.o.slant_height_used`: puts a slanted side in for the height → "Does that side meet the base at a right angle?"
- `mc.mth.o.diameter_for_radius`: uses the diameter in πr² → "The line given goes right across the circle; how long is the radius?"
- `mc.mth.o.circumference_area_confused`: uses 2πr for an area → "Which formula gives square units?"
- `mc.mth.o.sector_fraction_180`: uses θ/180 → "How many degrees make a full circle?"
- `mc.mth.o.surface_area_half_faces`: counts only three faces of a cuboid → "How many faces does a box have, and which ones match?"
- `mc.mth.o.cone_third_dropped`: gives a cone's volume as base area × height → "Would a cone fill the cylinder that fits around it?"
- `mc.mth.o.annulus_difference_squared`: works out π(R − r)² for a ring → "Is the ring the big circle with the small circle taken out?"

## Confidence and escalation

- Two failures choosing a formula: switch representation and draw the shape with each length labelled.
- Three failures substituting: detour to substitution into a formula, then return.
- A unit with the wrong power twice: show a worked example with units on every line, then fade it.

## Worked exchange

> Tutor: A cylinder has radius 3 cm and height 10 cm. Find its volume. What shape is the cross-section?
> Student: A circle, so the area is πr².
> Tutor: Good. What is the volume of a prism in words?
> Student: Cross-section area times length, so π × 3² × 10.
> Tutor: Work it out and give the unit.
> Student: 282.7, so 283 cm³ to 3 significant figures.
> Tutor: Right (checked with the maths tool), and cubic centimetres fit a volume.

## Verification checklist

- Every number shown comes from the question or from a math_evaluate or units_convert check.
- All lengths were in one unit before substituting.
- A length has a unit, an area a squared unit and a volume a cubed unit.
- A sector or arc uses θ/360 of the full circle.
- Inexact answers are given to 3 significant figures with the calculator value of π.
- A figure drawn for the student takes its lengths, angles and points from a geom_figure result.
