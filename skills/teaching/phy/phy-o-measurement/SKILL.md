---
name: phy-o-measurement
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach unit prefixes, scalars and vectors, resultants and careful measurement
description: "Prefixes, scalars and vectors, resultant of two vectors, micrometer and repeat timing: find the factor, decide if direction matters, add along a line or use Pythagoras at right angles, read the scale then correct it. Not for: motion graphs (phy-o-motion) or forces in balance (phy-o-forces)."
subject: physics
levels: [O]
topics: [prefixes, scalars, vectors, resultant, micrometer, zero error, repeat timing]
kcs:
  - kc.phy.o.measurement.si_prefixes
  - kc.phy.o.measurement.scalars_and_vectors
  - kc.phy.o.measurement.resultant_vectors
  - kc.phy.o.measurement.measuring_techniques
curriculum_refs: [PHY-O-01.01]
prerequisites: []
related: [phy-o-motion, phy-o-forces, phy-o-density]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_convert, units_check_dimensions]
visuals: [knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: length
    unit: m
    min: 0.000001
    max: 10000
    context: lengths measured in a school lab, from a wire's diameter to a running track
  - quantity: time
    unit: s
    min: 0.01
    max: 10000
    context: timings by stopwatch or light gate, single swings to a long experiment
  - quantity: speed
    unit: m/s
    min: 0
    max: 300
    context: resultant velocities of boats, aircraft and people in wind or current
  - quantity: force
    unit: N
    min: 0
    max: 100000
    context: resultants of everyday pushes, pulls and weights
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student converts a quantity between prefixed units with the right factor and direction
  - The student classifies a quantity as scalar or vector by asking whether direction is part of it
  - The student finds the size and direction of the resultant of two vectors along a line or at right angles
  - The student reads a micrometer or a repeated timing, corrects for zero error and divides by the count
---

# Units, vectors and measuring

## When to use

Use when a question asks to change a unit with a prefix, to say whether a quantity is a scalar or a vector, to
combine two forces or velocities, or to read a micrometer, a ruler or a stopwatch accurately.

Not for: speed and acceleration from graphs (phy-o-motion), or what a resultant force does to motion (phy-o-forces).

## What this skill does not do

- It does not resolve a vector into components at angles other than a right angle.
- It does not use scale drawing; resultants at right angles come from Pythagoras and tan.
- It does not treat vernier calipers beyond reading a main scale and a second scale the same way.

## Objectives

1. The student converts a quantity between prefixed units with the right factor and direction.
2. The student classifies a quantity as scalar or vector by asking whether direction is part of it.
3. The student finds the size and direction of the resultant of two vectors along a line or at right angles.
4. The student reads a micrometer or a repeated timing, corrects for zero error and divides by the count.

## Prerequisite probe

- "How many millimetres are in 2.5 m?" Expected: 2500 mm (checked with units_convert).
- "A right-angled triangle has shorter sides 6 cm and 8 cm. How long is the longest side?" Expected: 10 cm.

If the first fails, practise powers of ten first; if the second fails, revisit Pythagoras' theorem, then return.

## Teaching sequence

1. Ask what kind of question it is: a unit change, scalar or vector, combining vectors, or reading an instrument. Done when the student names the kind.
2. For a prefix, ask for its factor (milli 10⁻³, micro 10⁻⁶, kilo 10³, mega 10⁶) and whether the number should grow or shrink; for an area or a volume the factor is squared or cubed. Done when the value matches units_convert.
3. For scalar or vector, ask whether the quantity still makes sense without a direction. Done when the student classifies it with that reason.
4. For two vectors along one line, ask the student to choose a positive direction, then add with signs. Done when the size and the direction are both stated.
5. For two vectors at right angles, ask for the size by Pythagoras and the angle by tan from a named line; math_evaluate gives the reference. Done when both match the checked values.
6. For an instrument, ask for the main-scale reading plus the second scale (a micrometer thimble counts hundredths of a millimetre), minus any zero error; for repeats, divide the total by how many there were. Done when the corrected reading matches the checked value.
7. Ask for the unit and a sense check. Done when the unit passes units_check_dimensions and the size is sensible.

## Hint ladder

1. Orient: "What does the question give you, and does direction matter here?"
2. Concept: name the rule, such as "vectors at right angles combine by Pythagoras, never by adding".
3. First step: write the factor, the sign convention or the right-angled triangle and ask for the next line.
4. Worked step: show the substitution and ask the student for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.prefix_multiply_divide_swapped`: multiplies by 1000 to turn millimetres into metres → "Is a metre made of many millimetres or a few, so should the number grow or shrink?"
- `mc.phy.o.prefix_power_wrong`: uses a hundred for milli → "How many millimetres make one metre?"
- `mc.phy.o.area_volume_factor_not_raised`: divides cm³ by a hundred for m³ → "A 1 m cube is 100 cm along each edge. How many 1 cm cubes fill it?"
- `mc.phy.o.speed_as_vector`: calls speed a vector → "Does a speedometer tell you which way the car is going?"
- `mc.phy.o.mass_as_vector`: calls mass a vector → "Which way does a kilogram of sugar point?"
- `mc.phy.o.resultant_adds_sizes`: adds 3 N and 4 N at right angles to get 7 N → "Could a pull to the east help a pull to the north fully?"
- `mc.phy.o.opposite_vectors_added`: adds opposing forces → "If two people push a box from opposite sides, does the box feel both pushes the same way?"
- `mc.phy.o.pythagoras_for_a_line`: uses Pythagoras for forces along one line → "Is there a right angle anywhere between these two forces?"
- `mc.phy.o.resultant_angle_inverted`: takes tan as the wrong ratio → "Which side is opposite the angle you want, and which is next to it?"
- `mc.phy.o.thimble_read_as_tenths`: reads thimble divisions as tenths → "One full turn moves the spindle half a millimetre over fifty divisions. What is one division worth?"
- `mc.phy.o.zero_error_wrong_way`: adds a positive zero error → "If the jaws already read 0.02 mm when closed, is every reading too big or too small?"
- `mc.phy.o.repeat_not_divided`: gives the time for twenty swings as the period → "How many swings did the stopwatch time?"

## Confidence and escalation

- Two failures on a prefix: build the factor from 1 m = 1000 mm on the board, then convert again.
- Three failures on a resultant at right angles: detour to Pythagoras and tan in a plain triangle, then return.
- A reading from an instrument the student describes but the question does not show: ask for the readings; never guess them.

## Worked exchange

> Tutor: A boat is steered north at 4.0 m/s across a river that flows east at 3.0 m/s. What is the boat's resultant velocity? Do the two velocities act along one line?
> Student: No, they are at right angles.
> Tutor: Good. So how do you combine their sizes?
> Student: Pythagoras: the square root of 4.0² + 3.0² is the square root of 25, so 5.0 m/s.
> Tutor: Right. A velocity also needs a direction. Which angle can you find with tan, and from which line?
> Student: tan θ = 3.0 ÷ 4.0, so θ is 36.9° east of north.
> Tutor: Correct (checked with the maths tool): 5.0 m/s at 36.9° east of north.

## Verification checklist

- Every converted value matches units_convert, including squared and cubed factors.
- A vector answer states a size and a direction from a named line.
- Resultant sizes and angles match math_evaluate with angles in degrees.
- Instrument readings subtract a positive zero error and add back a negative one.
- Repeated timings and stacks are divided by the count, and the unit passes units_check_dimensions.
