---
name: phy-o-energy
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach energy stores, kinetic and potential energy, work, power and efficiency
description: "Energy stores, kinetic and potential energy, work, power, efficiency, resources: name the stores, keep the total fixed, pick the formula, use SI units. Not for: electrical energy and cost (phy-o-practical-electricity) or heating a mass (phy-o-thermal-properties)."
subject: physics
levels: [O]
topics: [energy stores, kinetic energy, potential energy, conservation of energy, work, power, efficiency, energy resources]
kcs:
  - kc.phy.o.energy.stores_and_transfers
  - kc.phy.o.energy.kinetic_energy
  - kc.phy.o.energy.potential_energy
  - kc.phy.o.energy.energy_conversion
  - kc.phy.o.energy.work_done
  - kc.phy.o.energy.power
  - kc.phy.o.energy.efficiency
  - kc.phy.o.energy.energy_resources
curriculum_refs: [PHY-O-01.07]
prerequisites:
  - kc.phy.o.motion.average_speed
  - kc.phy.o.mass_weight.weight_from_mass
  - kc.phy.o.forces.resultant_force
related: [phy-o-forces, phy-o-momentum, phy-o-practical-electricity, phy-o-thermal-properties]
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
  - quantity: energy
    unit: J
    min: 0
    max: 1000000000000
    context: energy in stores from a dropped coin to a day of a power station's output
  - quantity: work
    unit: J
    min: 0
    max: 1000000000
    context: lifting, pushing and pulling by people, machines and cranes
  - quantity: power
    unit: W
    min: 0
    max: 5000000000
    context: people, motors, vehicles and power stations
  - quantity: speed
    unit: m/s
    min: 0
    max: 120
    context: falling, swinging, sliding and moving objects and vehicles
  - quantity: height
    unit: m
    min: 0
    max: 1000
    context: heights objects are lifted or fall through, up to a tall hill or dam
  - quantity: efficiency
    unit: percent
    min: 0
    max: 100
    context: useful output as a share of total input for any device
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the stores that empty and fill in a change and keeps the total energy the same
  - The student calculates kinetic energy and changes in gravitational potential energy in SI units
  - The student uses conservation of energy to link height and speed for falling, swinging and sliding objects
  - The student calculates work, power and efficiency with the force along the distance and the time in seconds
  - The student compares energy resources by renewability, reliability, cost and effect on the environment
---

# Energy, work and power

## When to use

Use when a question asks which energy stores change, for a kinetic or gravitational potential energy, the speed at
the bottom of a fall or a swing, the work done by a force, a power, an efficiency, or how energy resources compare.

Not for: electrical energy, kilowatt-hours and cost (phy-o-practical-electricity), or heating a mass with E = mcΔθ
(phy-o-thermal-properties).

## What this skill does not do

- It does not treat elastic potential energy calculations.
- It does not let energy be lost: wasted energy goes to another store, usually the thermal store of the surroundings.
- It does not rank energy resources by a single score; each comparison names the factor used.

## Objectives

1. The student names the stores that empty and fill in a change and keeps the total energy the same.
2. The student calculates kinetic energy and changes in gravitational potential energy in SI units.
3. The student uses conservation of energy to link height and speed for falling, swinging and sliding objects.
4. The student calculates work, power and efficiency with the force along the distance and the time in seconds.
5. The student compares energy resources by renewability, reliability, cost and effect on the environment.

## Prerequisite probe

- "What is the weight of a 5.0 kg mass where g = 9.8 N/kg?" Expected: 49 N (checked with math_evaluate).
- "Change 2 minutes into seconds." Expected: 120 s.

If the first fails, detour to weight (phy-o-mass-weight); if the second fails, practise time units, then return.

## Teaching sequence

1. Ask which store empties and which fills, and by what transfer. Done when both stores and the transfer are named.
2. Ask the student to list the givens in SI units: kilograms, metres, seconds, newtons and joules. Done when every value is in SI units or converted with units_convert.
3. Ask for the formula that links the givens: ½mv², mgΔh, W = Fd, P = E ÷ t, or useful ÷ total input. Done when one formula is chosen with a reason.
4. For a fall or a swing, ask the student to set the energy lost from one store equal to the energy gained by the other. Done when the energy equation is on the board.
5. Ask the student to substitute and solve; math_evaluate gives the reference. Done when the value matches the checked one.
6. Ask for a sense check: an efficiency never above 100%, a speed that fits the situation. Done when the value is in its band and the unit passes units_check_dimensions.
7. For a resource, ask which factor the question compares and how the resource scores on it. Done when the factor and the score are both given.

## Hint ladder

1. Orient: "Which store empties, and which one fills?"
2. Concept: "Energy is not made or destroyed; the energy one store loses, others gain."
3. First step: write the energy equation or formula with symbols and ask for the substitution.
4. Worked step: show the substitution in SI units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.energy_used_up`: says the energy is used up when the car stops → "Where did the energy from the kinetic store go?"
- `mc.phy.o.transfer_named_as_store`: calls heating a store → "Is heating somewhere energy sits, or a way it moves?"
- `mc.phy.o.ke_half_omitted`: works out mv² → "What number sits in front of mv² in the kinetic energy formula?"
- `mc.phy.o.ke_proportional_to_speed`: says doubling the speed doubles the energy → "The speed is squared. What happens to 2 when you square it?"
- `mc.phy.o.gpe_height_not_change`: uses the starting height for a drop to a table → "How far did the object go down?"
- `mc.phy.o.conversion_two_dropped`: gets v² = gh from mgh = ½mv² → "When you multiply both sides by 2, where does the 2 go?"
- `mc.phy.o.ke_speed_not_rooted`: gives v² as the speed → "Is 98 the speed, or the speed squared?"
- `mc.phy.o.work_done_without_movement`: says holding a box still does work on it → "How far did the box move in the direction of the force?"
- `mc.phy.o.power_is_energy`: gives the energy as the power → "Power is how fast energy is transferred. What time did it take?"
- `mc.phy.o.power_minutes_not_converted`: divides by minutes → "A watt is a joule each what?"
- `mc.phy.o.efficiency_inverted`: gets an efficiency above 100% → "Can a device give out more useful energy than it takes in?"
- `mc.phy.o.efficiency_useful_over_wasted`: divides useful by wasted → "Which energy did the device take in altogether?"
- `mc.phy.o.renewability_confused_with_reliability`: calls wind non-renewable because it stops → "Will the wind run out, or just drop for a while?"
- `mc.phy.o.nuclear_is_renewable`: calls uranium renewable → "Is more uranium being made as fast as it is mined?"

## Confidence and escalation

- Two failures on naming stores: list the stores (kinetic, gravitational, elastic, chemical, thermal, nuclear) and choose from them.
- Three failures on rearranging ½mv² or mgΔh: detour to rearranging with squares and roots, then return.
- Friction or air resistance that the question does not let you ignore: say the speed will be less than the ideal value.

## Worked exchange

> Tutor: A 0.50 kg ball is dropped from a height of 5.0 m. Ignoring air resistance, how fast is it moving just before it lands? Take g as 9.8 N/kg. Which store empties as it falls?
> Student: The gravitational store: mgh = 0.50 × 9.8 × 5.0 = 24.5 J.
> Tutor: Good. Which store fills?
> Student: The kinetic store, so ½ × 0.50 × v² = 24.5.
> Tutor: Right. Solve for v.
> Student: v² = 24.5 × 2 ÷ 0.50 = 98, so v = 9.9 m/s.
> Tutor: Correct (checked with the maths tool). The mass cancels, so v² = 2gh for any falling mass.

## Verification checklist

- Masses are in kilograms, heights in metres and times in seconds before substituting.
- The force in W = Fd acts along the distance moved.
- Every energy, speed, power and efficiency matches math_evaluate, and the unit passes units_check_dimensions.
- An efficiency is at most 100% and uses total input on the bottom.
- Wasted energy is named as going to a store, never as destroyed.
