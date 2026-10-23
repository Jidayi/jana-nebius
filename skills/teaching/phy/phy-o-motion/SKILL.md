---
name: phy-o-motion
kind: teaching
version: "0.3"
status: draft
language: en
summary: Teach straight-line motion from speed to the equations of motion
description: "speed, velocity, acceleration, motion graphs, equations of uniform acceleration, free fall: name the knowns, choose the relation, substitute with units, check the sign. Not for: projectiles at an angle, circular motion or forces (separate skills)."
subject: physics
levels: [O]
topics: [motion, speed, acceleration, motion graphs, free fall]
kcs:
  - kc.phy.o.motion.distance_or_displacement
  - kc.phy.o.motion.average_speed
  - kc.phy.o.motion.speed_unit_conversion
  - kc.phy.o.motion.acceleration_from_change
  - kc.phy.o.motion.distance_time_gradient
  - kc.phy.o.motion.velocity_time_gradient
  - kc.phy.o.motion.velocity_time_area
  - kc.phy.o.motion.choose_equation
  - kc.phy.o.motion.solve_with_equation
  - kc.phy.o.motion.free_fall
curriculum_refs: [PHY-O-01.02]
prerequisites: []
related: [phy-o-forces, phy-o-measurement, phy-o-energy]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_solve, math_evaluate, units_convert, units_check_dimensions]
visuals: [motion_graph]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: speed
    unit: m/s
    min: 0
    max: 120
    context: people, animals, bicycles, cars, trains and thrown objects
  - quantity: acceleration
    unit: m/s^2
    min: -30
    max: 30
    context: vehicles speeding up or braking, objects under gravity
  - quantity: height
    unit: m
    min: 0.1
    max: 100
    context: objects thrown or dropped by hand
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-10"
success_criteria:
  - The student writes the knowns and the unknown with units before choosing a relation
  - The student chooses a relation that contains the knowns and the unknown and nothing else unknown
  - The student reaches a checked answer with a correct unit and a sign that fits the chosen direction
---

# Motion in a straight line

## When to use

Use when a problem asks for a speed, a velocity, an acceleration, a distance, a displacement or a time for motion
along a straight line, from numbers or from a distance-time or velocity-time graph, including objects moving up or
down under gravity.

Not for: projectiles launched at an angle, circular motion, or questions about the forces that cause the motion.

## What this skill does not do

- It does not introduce calculus; gradients and areas come from the graph's straight lines and simple shapes.
- It does not treat air resistance.
- It does not choose the value of g: the question or the pack convention gives it.

## Objectives

1. The student writes the knowns and the unknown with units before choosing a relation.
2. The student chooses a relation that contains the knowns and the unknown and nothing else unknown.
3. The student reaches a checked answer with a correct unit and a sign that fits the chosen direction.

## Prerequisite probe

- "A car travels 300 m in 20 s. What is its average speed?" Expected: 15 m/s (checked with math_evaluate).
- "Make a the subject of v = u + at." Expected: a = (v − u)/t.

If either fails, step back to average speed or to rearranging, then return to this problem.

## Teaching sequence

1. Ask the student to say which way is positive for the motion. Done when the direction is on the board.
   Keep the given gravitational magnitude g positive. With upwards positive the signed acceleration is a = -g;
   do not relabel it as a negative g or ask for the sign again after a correct signed substitution.
2. Ask the student to list the quantities the question gives, each with its unit, and to mark the one it asks for. Done when every given quantity is listed with a unit.
3. Ask which relation links the givens to the unknown: average speed, the definition of acceleration, a graph's gradient or area, or one equation of uniform acceleration. Done when the student names one relation.
4. Ask the student to substitute the values with their signs and units. Done when the substitution line is on the board and checked.
5. Ask the student to solve for the unknown; the tool result is the reference value. Done when the student's value matches the checked value.
6. Ask for the unit and a quick sense check against everyday values. Done when the unit passes units_check_dimensions and the value is sensible.

## Hint ladder

1. Orient: "What does the question give you, and what does it ask for?"
2. Concept: name the relation in words, such as "acceleration is the change in velocity divided by the time taken".
3. First step: write the relation with the symbols and ask the student to put the numbers in.
4. Worked step: show the substitution and ask the student for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.distance_for_displacement`: adds both parts of a there-and-back walk for the displacement → "Where did the walk end compared with where it started?"
- `mc.phy.o.time_over_distance`: divides the time by the distance → "Speed is how far you go each second. Which quantity goes on top?"
- `mc.phy.o.kmh_divide_by_36`: divides a speed in km/h by 36 instead of by 3.6 → "How many metres are in a kilometre, and how many seconds in an hour?"
- `mc.phy.o.final_velocity_over_time`: uses the final velocity instead of the change in velocity → "What was the velocity at the start, and how much did it change?"
- `mc.phy.o.gradient_from_one_point`: divides one point's distance by its time on a sloping line → "Which two points does the gradient need, and what changed between them?"
- `mc.phy.o.vt_gradient_read_as_velocity`: reads a velocity off the graph as the acceleration → "Is the acceleration the height of the line, or how steep it is?"
- `mc.phy.o.triangle_area_without_half`: takes the area under a speeding-up line as velocity × time → "Is the shape under the line a rectangle or a triangle?"
- `mc.phy.o.equation_with_unknown_time`: picks an equation with the time in it when the time is not given → "Which quantity in that equation do you not know and not want?"
- `mc.phy.o.squares_dropped`: uses v = u + 2as → "Which equation has v² and u² in it, and where did the squares go?"
- `mc.phy.o.gravity_sign_flipped`: gives the acceleration the same sign as the upward motion when up is positive → "Which way does gravity pull, and which way did you call positive?"

## Confidence and escalation

- Two failures on choosing a relation: list the quantities again and ask which one is missing from each relation.
- Three failures on rearranging: detour to rearranging a formula, then return.
- A correct size with the wrong sign: treat it as mc.phy.o.gravity_sign_flipped, not as an arithmetic slip.

## Worked exchange

> Tutor: A trolley speeds up steadily from 2.0 m/s to 8.0 m/s in 3.0 s. What is its acceleration? What does the question give you?
> Student: u is 2.0 m/s, v is 8.0 m/s and t is 3.0 s.
> Tutor: Good. Which relation links a change in velocity to a time?
> Student: Acceleration is the change in velocity over the time, so (8.0 − 2.0) / 3.0.
> Tutor: Work it out and give the unit.
> Student: 2.0 m/s².
> Tutor: That's right (checked with the maths tool), and 2.0 m/s² is a sensible value for a trolley.

## Verification checklist

- Every number shown comes from the question or has a check from math_evaluate, math_solve or units_convert.
- The final unit passed units_check_dimensions.
- The sign of the acceleration matches the chosen positive direction.
- A graph value is read from a point the question gives, never estimated without saying so.

## Reference relations

For straight-line motion with constant acceleration, u is initial velocity, v final velocity, a signed
acceleration, s displacement and t elapsed time. These authored relations let the worker check a student's
symbolic formula even when the hidden solution plan starts with substitution.

- `v = u + a*t`
- `s = u*t + (1/2)*a*t^2`
- `v^2 = u^2 + 2*a*s`
