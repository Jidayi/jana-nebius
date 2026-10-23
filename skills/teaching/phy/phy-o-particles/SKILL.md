---
name: phy-o-particles
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach the particle model, kelvin temperatures and gas pressure and volume
description: "Particle model, states of matter, kelvin, gas pressure and volume: picture the particles, explain by how fast and how often they hit the walls, then use pV = constant. Not for: heating a mass (phy-o-thermal-properties) or liquid pressure (phy-o-pressure)."
subject: physics
levels: [O]
topics: [particle model, states of matter, brownian motion, kelvin, absolute zero, gas pressure, pressure and volume]
kcs:
  - kc.phy.o.particles.states_of_matter
  - kc.phy.o.particles.temperature_scales
  - kc.phy.o.particles.gas_pressure_particles
  - kc.phy.o.particles.pressure_and_volume
curriculum_refs: [PHY-O-02.01]
prerequisites:
  - kc.phy.o.pressure.pressure_on_surfaces
related: [phy-o-thermal-properties, phy-o-pressure, phy-o-heat-transfer]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve, units_convert, units_check_dimensions]
visuals: [knowns_panel, library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: temperature
    unit: K
    min: 0
    max: 3000
    context: temperatures from absolute zero to a flame or furnace
  - quantity: pressure
    unit: Pa
    min: 0
    max: 10000000
    context: gas pressures in syringes, tyres, cylinders and the atmosphere
  - quantity: volume
    unit: m^3
    min: 0.0000001
    max: 100
    context: gas in a syringe up to a room or a large tank
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student describes the arrangement and motion of particles in a solid, a liquid and a gas
  - The student converts between degrees Celsius and kelvin and links absolute zero to the least particle motion
  - The student explains gas pressure by particles hitting the walls and predicts the effect of heating or compressing
  - The student uses pressure × volume = constant for a fixed mass of gas at constant temperature
---

# Particles, temperature and gas pressure

## When to use

Use when a question asks how particles are arranged or move in a solid, a liquid or a gas, what Brownian motion
shows, for a temperature in kelvin or degrees Celsius, why a gas presses on its container, or for the new pressure or
volume of a gas squeezed or let expand at a steady temperature.

Not for: the energy to heat or melt a mass (phy-o-thermal-properties), or the pressure under a liquid (phy-o-pressure).

## What this skill does not do

- It does not use the gas law with temperature changes beyond saying which way the pressure goes.
- It does not treat the particle masses or speeds as numbers.
- It does not choose the kelvin offset: the pack gives 273.

## Objectives

1. The student describes the arrangement and motion of particles in a solid, a liquid and a gas.
2. The student converts between degrees Celsius and kelvin and links absolute zero to the least particle motion.
3. The student explains gas pressure by particles hitting the walls and predicts the effect of heating or compressing.
4. The student uses pressure × volume = constant for a fixed mass of gas at constant temperature.

## Prerequisite probe

- "What is the pressure when 20 N pushes on 0.5 m²?" Expected: 40 Pa (checked with math_evaluate).
- "Make V₂ the subject of p₁V₁ = p₂V₂." Expected: V₂ = p₁V₁ ÷ p₂.

If the first fails, detour to pressure (phy-o-pressure); if the second fails, practise rearranging, then return.

## Teaching sequence

1. Ask the student to describe or sketch the particles: how close, how ordered, how they move. Done when the state's spacing, order and motion are all given.
2. For a temperature change of scale, ask whether it is a reading or a difference; a reading adds 273 to go to kelvin, a difference stays the same. Done when the value matches units_convert.
3. For gas pressure, ask what the particles hit and how often and how hard. Done when the student explains pressure by collisions with the walls.
4. For a change, ask what happens to the particles' speed and to how often they hit the walls. Done when the student predicts the direction of the change in pressure with that reason.
5. For pV = constant, ask whether the mass and the temperature stay fixed, then write p₁V₁ = p₂V₂ with matching units on each side. Done when the equation is on the board.
6. Ask the student to predict up or down, then solve; math_solve gives the reference value. Done when the value matches the checked one and the prediction.

## Hint ladder

1. Orient: "What are the particles doing, and what do they hit?"
2. Concept: "Gas pressure comes from particles hitting the walls; less space means more hits each second."
3. First step: write p₁V₁ = p₂V₂ with the student's values, or the particle picture, and ask for the next step.
4. Worked step: show the substitution and ask the student to solve for the unknown.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.solid_particles_motionless`: says particles in a solid are still → "If the particles in ice did not move at all, could the ice warm up?"
- `mc.phy.o.liquid_particles_far_apart`: draws liquid particles far apart → "Why can you hardly squeeze water into a smaller space?"
- `mc.phy.o.brownian_molecules_seen`: says the specks are air molecules → "Could a microscope show something as small as one molecule?"
- `mc.phy.o.kelvin_offset_wrong_way`: subtracts 273 to get kelvin → "Is 0 °C above or below absolute zero, and so is its kelvin number bigger or smaller?"
- `mc.phy.o.kelvin_change_offset_added`: adds 273 to a rise of 20 °C → "If water warms by 20 degrees, is that a temperature or a change?"
- `mc.phy.o.absolute_zero_is_freezing_point`: says absolute zero is 0 °C → "Can a freezer get colder than 0 °C?"
- `mc.phy.o.pressure_from_interparticle_collisions`: says pressure comes from particles hitting each other → "Which collisions push on the wall of the container?"
- `mc.phy.o.gas_pressure_from_weight`: says gas presses only downwards → "Does a balloon bulge only at the bottom?"
- `mc.phy.o.heating_creates_particles`: says heating adds particles → "Did anything get into the sealed can while it was heated?"
- `mc.phy.o.boyle_direct_proportion`: makes the pressure fall when the volume halves → "In a smaller space, do the particles hit the walls more or less often?"
- `mc.phy.o.boyle_change_used_as_volume`: puts the change in volume into p₁V₁ = p₂V₂ → "Is V₂ how much the volume shrank, or the new volume?"
- `mc.phy.o.compression_speeds_particles`: says squeezing at a steady temperature speeds the particles → "If the temperature stays the same, does the particles' speed change?"

## Confidence and escalation

- Two failures on particle pictures: compare three boxes side by side, one for each state, and fill them in together.
- Three failures on p₁V₁ = p₂V₂: detour to solving a one-step equation, then return.
- A question where the temperature also changes: say pV = constant does not apply alone and ask for help.

## Worked exchange

> Tutor: A fixed mass of gas has a volume of 120 cm³ at a pressure of 100 kPa. It is squeezed slowly to 40 cm³ at the same temperature. What is its new pressure? Which relation fits?
> Student: Pressure times volume stays the same, so p₁V₁ = p₂V₂.
> Tutor: Good. Before working it out, should the pressure go up or down?
> Student: Up, because the particles hit the walls more often in a smaller space.
> Tutor: Right. Now the value.
> Student: 100 × 120 = p₂ × 40, so p₂ = 12000 ÷ 40 = 300 kPa.
> Tutor: Correct (checked with the maths tool), and it rose as you predicted.

## Verification checklist

- A kelvin conversion adds 273 to a reading and leaves a temperature difference unchanged, matching units_convert.
- Both sides of p₁V₁ = p₂V₂ use the same units, and the unknown matches math_solve.
- The mass and temperature of the gas are fixed before pV = constant is used.
- Every explanation of pressure names collisions with the walls.
- The unit passes units_check_dimensions.
