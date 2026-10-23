---
name: phy-o-forces
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach resultant force, F = ma, drag, springs, circular motion and moments
description: "Resultant force, F = ma, friction, terminal velocity, springs, circular motion, moments, stability: draw the forces, find the resultant, then use F = ma, F = kx or the principle of moments. Not for: momentum and impulse (phy-o-momentum) or pressure (phy-o-pressure)."
subject: physics
levels: [O]
topics: [resultant force, acceleration from force, friction, terminal velocity, springs, circular motion, moments, centre of gravity, stability]
kcs:
  - kc.phy.o.forces.resultant_force
  - kc.phy.o.forces.force_mass_acceleration
  - kc.phy.o.forces.friction_and_terminal_velocity
  - kc.phy.o.forces.springs
  - kc.phy.o.forces.circular_motion
  - kc.phy.o.forces.moments
  - kc.phy.o.forces.centre_of_gravity
curriculum_refs: [PHY-O-01.05]
prerequisites:
  - kc.phy.o.measurement.scalars_and_vectors
  - kc.phy.o.measurement.resultant_vectors
  - kc.phy.o.motion.acceleration_from_change
  - kc.phy.o.mass_weight.weight_from_mass
related: [phy-o-motion, phy-o-mass-weight, phy-o-momentum]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_check_dimensions]
visuals: [free_body, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: force
    unit: N
    min: 0
    max: 1000000
    context: pushes, pulls, drag and weights from a pencil to a lorry
  - quantity: mass
    unit: kg
    min: 0.001
    max: 100000
    context: trolleys, people, cars and lorries
  - quantity: acceleration
    unit: m/s^2
    min: -50
    max: 50
    context: vehicles, runners and falling objects
  - quantity: extension
    unit: m
    min: 0
    max: 2
    context: stretched springs and rubber bands in a school lab
  - quantity: spring_constant
    unit: N/m
    min: 1
    max: 100000
    context: lab springs up to vehicle suspension springs
  - quantity: moment
    unit: N m
    min: 0
    max: 100000
    context: levers, see-saws, spanners, doors and cranes
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds the resultant of forces along a line and says whether the motion changes
  - The student uses resultant force = mass × acceleration to find the force, the mass or the acceleration
  - The student explains friction, drag and terminal velocity with forces that balance or do not
  - The student uses F = kx with the extension, and a centre-pointing force for motion in a circle
  - The student applies the principle of moments and links stability to the centre of gravity and the base
---

# Forces and their effects

## When to use

Use when a question gives the forces on an object and asks for the resultant, an acceleration, a spring's extension or
constant, a force or a distance on a balanced beam, why an object falls at a steady speed, why something moves in a
circle, or why one object is more stable than another.

Not for: collisions, momentum and impulse (phy-o-momentum), or force per unit area (phy-o-pressure).

## What this skill does not do

- It does not resolve forces at angles other than along a line; perpendicular resultants belong to phy-o-measurement.
- It does not calculate the size of a centripetal force; it reasons about its direction and what makes it bigger.
- It does not treat elastic potential energy.

## Objectives

1. The student finds the resultant of forces along a line and says whether the motion changes.
2. The student uses resultant force = mass × acceleration to find the force, the mass or the acceleration.
3. The student explains friction, drag and terminal velocity with forces that balance or do not.
4. The student uses F = kx with the extension, and a centre-pointing force for motion in a circle.
5. The student applies the principle of moments and links stability to the centre of gravity and the base.

## Prerequisite probe

- "A cart speeds up from 4 m/s to 10 m/s in 3 s. What is its acceleration?" Expected: 2 m/s².
- "What is the weight of a 2.0 kg mass where g = 9.8 N/kg?" Expected: 19.6 N (checked with math_evaluate).

If the first fails, detour to acceleration (phy-o-motion); if the second, to weight (phy-o-mass-weight).

## Teaching sequence

1. Ask the student to sketch the object with every force as a labelled arrow. Done when each force has a size, a direction and a cause.
2. Ask for the resultant along the line of motion, with one direction chosen as positive. Done when the resultant matches math_evaluate with its sign.
3. Ask what the resultant does: zero means a steady velocity or rest, non-zero means acceleration in its direction. Done when the student links the resultant to the change in motion.
4. For F = ma, ask for the resultant force (never the driving force alone) and the mass in kilograms, then substitute. Done when the value matches the checked one.
5. For a spring, ask for the extension (new length minus original length) in metres, then use F = kx. Done when the value matches the checked one.
6. For a circle, ask which way the resultant force points and what supplies it. Done when the student says towards the centre and names the force.
7. For a beam, ask for each moment as force × perpendicular distance from the pivot, then set clockwise equal to anticlockwise; for stability, ask where the vertical line through the centre of gravity falls. Done when the unknown matches the checked value or the toppling reason is given.

## Hint ladder

1. Orient: "What forces act on the object, and which way does each one point?"
2. Concept: name the rule, such as "only the resultant force changes the motion" or "clockwise moments equal anticlockwise moments".
3. First step: write the resultant or the moments equation with the student's arrows and ask for the next line.
4. Worked step: show the substitution with units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.balanced_means_at_rest`: says a car at a steady speed has an unbalanced force → "If the forces balance, what changes about the motion: nothing, or the speed?"
- `mc.phy.o.resultant_one_force_left_out`: takes only friction from the driving force → "Have you counted every arrow on your sketch?"
- `mc.phy.o.fma_applied_force_not_resultant`: puts the driving force into F = ma → "Which force is left over once the drag pushes back?"
- `mc.phy.o.fma_ratio_inverted`: works out mass ÷ force for the acceleration → "Should a bigger force give a bigger or a smaller acceleration?"
- `mc.phy.o.terminal_velocity_no_forces`: says no forces act at terminal velocity → "Is gravity still pulling on the skydiver?"
- `mc.phy.o.drag_independent_of_speed`: says drag stays the same as speed rises → "Does the wind push harder on your hand at walking pace or from a fast car window?"
- `mc.phy.o.spring_length_for_extension`: uses the stretched length in F = kx → "How much longer did the spring get?"
- `mc.phy.o.spring_proportional_beyond_limit`: extends the straight line forever → "What happens to the graph after the limit of proportionality?"
- `mc.phy.o.circular_force_outwards`: points the force away from the centre → "If you let go of the string, where would the ball go, and which way was the string pulling?"
- `mc.phy.o.moment_distance_from_end`: measures distances from the end of the beam → "About which point does the beam turn?"
- `mc.phy.o.balance_equal_forces`: says the beam balances only with equal forces → "Can a small child balance a big adult on a see-saw, and where must each sit?"
- `mc.phy.o.topples_whenever_tilted`: says any tilt topples it → "Where does the line straight down from the centre of gravity fall now?"
- `mc.phy.o.base_width_irrelevant`: ignores the width of the base → "Is a wide-based lamp or a narrow one harder to knock over?"

## Confidence and escalation

- Two failures on the resultant: redraw the forces as arrows of matching length and add them along the line.
- Three failures on F = ma or the moments equation: detour to rearranging a product, then return.
- A force the student adds that the question does not give: ask where it comes from before using it.

## Worked exchange

> Tutor: A car of mass 1200 kg has a driving force of 3000 N and resistive forces of 600 N against it. What is its acceleration? First, what is the resultant force?
> Student: 3000 − 600 = 2400 N forwards.
> Tutor: Good. Which relation links that to the acceleration?
> Student: F = ma, so a = 2400 ÷ 1200 = 2.0 m/s².
> Tutor: Correct (checked with the maths tool). What happens to the acceleration as the resistive forces grow with speed?
> Student: The resultant gets smaller, so the acceleration falls until the forces balance and the speed stays steady.
> Tutor: Right: balanced forces mean a steady velocity, not rest.

## Verification checklist

- The force in F = ma is the resultant, with every force on the sketch counted.
- Masses are in kilograms, extensions and distances in metres, and units pass units_check_dimensions.
- Every resultant, acceleration, extension and moment matches math_evaluate.
- Moments use perpendicular distances from the pivot, and both sides are summed.
- A circular-motion answer points the resultant towards the centre.
