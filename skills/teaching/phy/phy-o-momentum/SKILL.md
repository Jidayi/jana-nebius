---
name: phy-o-momentum
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach momentum with signs, its conservation, and impulse as force × time
description: "Momentum, collisions, explosions, recoil, impulse: choose a positive direction, find each object's mv with its sign, set the total before equal to the total after, and get force from the change in momentum over time. Not for: F = ma without momentum (phy-o-forces) or kinetic energy (phy-o-energy)."
subject: physics
levels: [O]
topics: [momentum, collisions, explosions, recoil, conservation of momentum, impulse, crumple zones]
kcs:
  - kc.phy.o.momentum.momentum_calculation
  - kc.phy.o.momentum.conservation_of_momentum
  - kc.phy.o.momentum.impulse
curriculum_refs: [PHY-O-01.06]
prerequisites:
  - kc.phy.o.measurement.scalars_and_vectors
  - kc.phy.o.forces.force_mass_acceleration
related: [phy-o-forces, phy-o-energy, phy-o-motion]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve, units_check_dimensions]
visuals: [knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: momentum
    unit: kg m/s
    min: -1000000
    max: 1000000
    context: balls, people, trolleys, cars and lorries moving either way along a line
  - quantity: velocity
    unit: m/s
    min: -1000
    max: 1000
    context: trolleys, vehicles, balls and bullets before and after a collision
  - quantity: mass
    unit: kg
    min: 0.001
    max: 100000
    context: bullets and balls up to lorries
  - quantity: force
    unit: N
    min: 0
    max: 1000000
    context: average forces during kicks, catches and crashes
  - quantity: time
    unit: s
    min: 0.0001
    max: 10
    context: contact times of impacts, from a bat on a ball to a crumple zone
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student calculates momentum as mass × velocity with a sign for its direction
  - The student applies conservation of momentum to a collision or an explosion along a line
  - The student finds an impulse as a change in momentum and an average force from it and the time
  - The student explains safety features by the longer time over which the momentum changes
---

# Momentum

## When to use

Use when a question asks for the momentum of a moving object, the velocity after a collision or an explosion, the
recoil of a gun or a skater, the impulse of a kick or a catch, or why airbags and crumple zones reduce injuries.

Not for: forces and acceleration with no collision (phy-o-forces), or the energy lost in a collision (phy-o-energy).

## What this skill does not do

- It does not treat collisions in two dimensions.
- It does not decide whether a collision is elastic; kinetic energy belongs to phy-o-energy.
- It does not read impulse from the area of a force-time graph.

## Objectives

1. The student calculates momentum as mass × velocity with a sign for its direction.
2. The student applies conservation of momentum to a collision or an explosion along a line.
3. The student finds an impulse as a change in momentum and an average force from it and the time.
4. The student explains safety features by the longer time over which the momentum changes.

## Prerequisite probe

- "Right is positive. What is the velocity of a ball moving at 3 m/s to the left?" Expected: −3 m/s.
- "Make v the subject of p = mv." Expected: v = p ÷ m.

If the first fails, revisit vectors (phy-o-measurement); if the second fails, practise rearranging, then return.

## Teaching sequence

1. Ask the student to choose a positive direction and mark it on a sketch. Done when the direction is on the board.
2. Ask for each object's mass in kilograms and velocity with its sign, before and after. Done when every velocity has a sign or is marked unknown.
3. Ask for each momentum as mass × velocity. Done when each value matches math_evaluate with its sign.
4. For a collision or an explosion, ask the student to write total momentum before = total momentum after, with every object in both totals. Done when the equation is on the board.
5. Ask the student to solve for the unknown; math_solve gives the reference value. Done when the student's value and its sign match the checked one.
6. For an impulse, ask for the change in momentum (final minus initial, keeping signs) and then force = change ÷ time in seconds. Done when the force matches the checked value.
7. Ask what the sign of the answer means for the direction. Done when the student states the direction in words.

## Hint ladder

1. Orient: "Which way is positive, and what is moving before and after?"
2. Concept: "The total momentum before equals the total momentum after, if no outside force acts."
3. First step: write the before and after totals with the student's values and leave the unknown as a symbol.
4. Worked step: show the equation with the numbers in and ask the student to solve it.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.momentum_sign_ignored`: adds momenta in opposite directions → "If the two trolleys move towards each other, can their momenta both be positive?"
- `mc.phy.o.momentum_as_kinetic_energy`: works out ½mv² for momentum → "Momentum is mass times velocity. Where did the half and the square come from?"
- `mc.phy.o.momentum_grams_not_converted`: uses 50 g as 50 in kg m/s → "What unit does the mass need to be in for kg m/s?"
- `mc.phy.o.stuck_mass_one_object`: divides by one trolley's mass when they move off together → "After they stick, how much mass is moving?"
- `mc.phy.o.explosion_creates_momentum`: says the total after an explosion is not zero → "What was the total momentum while everything was at rest?"
- `mc.phy.o.recoil_sign_dropped`: gives the recoil velocity as positive → "Does the gun move the same way as the bullet?"
- `mc.phy.o.collision_velocities_averaged`: averages the two velocities → "Would a lorry and a bicycle stuck together move off at the average of their speeds?"
- `mc.phy.o.impulse_change_as_force`: gives the change in momentum as the force → "The momentum changed over how long?"
- `mc.phy.o.rebound_change_subtracted`: takes 8 − 6 for a ball that bounces back → "The ball reversed. What is its velocity after, with its sign?"
- `mc.phy.o.impulse_ms_not_converted`: uses 20 ms as 20 s → "How many seconds is 20 milliseconds?"
- `mc.phy.o.cushioning_reduces_momentum_change`: says an airbag makes the change in momentum smaller → "The car still stops. Is the change in momentum smaller, or does it happen over a longer time?"

## Confidence and escalation

- Two sign errors: redraw the sketch with arrows and write every velocity with its sign before any arithmetic.
- Three failures on the conservation equation: detour to solving a linear equation, then return.
- A collision with an outside force that the question does not let you ignore: say momentum is not conserved and ask for help.

## Worked exchange

> Tutor: A 2.0 kg trolley moving at 3.0 m/s hits a stationary 1.0 kg trolley, and they move off together. What is their velocity afterwards? What is the total momentum before?
> Student: 2.0 × 3.0 = 6.0 kg m/s, and the still trolley has none.
> Tutor: Good. What mass moves off afterwards, and what is the total momentum then?
> Student: 3.0 kg together, and the momentum is still 6.0 kg m/s.
> Tutor: Right. So what is the velocity?
> Student: 6.0 ÷ 3.0 = 2.0 m/s, in the same direction as before.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- Every velocity carries a sign from the chosen positive direction.
- Both totals include every object, and the unknown matches math_solve.
- Masses are in kilograms and times in seconds, and the unit passes units_check_dimensions.
- A change in momentum is final minus initial, and the average force matches math_evaluate.
- The direction of the answer is stated in words.
