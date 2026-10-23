---
name: phy-o-thermal-properties
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach thermal expansion, heat capacity, latent heat and changes of state
description: "Thermal expansion, specific heat capacity, latent heat, heating curves: decide if the temperature or the state changes, use E = mcΔθ or E = mL in kilograms, read flat parts as a change of state. Not for: kelvin and gases (phy-o-particles) or conduction (phy-o-heat-transfer)."
subject: physics
levels: [O]
topics: [thermal expansion, specific heat capacity, latent heat, heating curves, cooling curves, evaporation, boiling, melting]
kcs:
  - kc.phy.o.thermal_properties.thermal_expansion
  - kc.phy.o.thermal_properties.specific_heat_capacity
  - kc.phy.o.thermal_properties.latent_heat
  - kc.phy.o.thermal_properties.changes_of_state
curriculum_refs: [PHY-O-02.02]
prerequisites:
  - kc.phy.o.particles.states_of_matter
  - kc.phy.o.particles.temperature_scales
  - kc.phy.o.energy.stores_and_transfers
related: [phy-o-particles, phy-o-heat-transfer, phy-o-energy]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_check_dimensions]
visuals: [knowns_panel, library_diagram]
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
    max: 1000000000
    context: heating, melting and boiling everyday amounts of water, metal and food
  - quantity: temperature
    unit: degC
    min: -273
    max: 3000
    context: temperatures from absolute zero to molten metal
  - quantity: specific_heat_capacity
    unit: J/(kg*K)
    min: 100
    max: 15000
    context: metals, water, oils and gases
  - quantity: specific_latent_heat
    unit: J/kg
    min: 10000
    max: 3000000
    context: melting and boiling of water, metals and common liquids
  - quantity: mass
    unit: kg
    min: 0.001
    max: 1000
    context: samples in a beaker up to a tank of water
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student explains thermal expansion of solids, liquids and gases by particle spacing and gives a use or a problem
  - The student uses E = mcΔθ to find the energy, the mass, the capacity or the temperature change
  - The student uses E = mL with the right latent heat for melting or boiling, adding stages when both happen
  - The student reads heating and cooling curves and tells evaporation from boiling
---

# Thermal properties and changes of state

## When to use

Use when a question asks why things expand when heated, how a bimetallic strip bends, how much energy warms, melts or
boils a mass, what the flat parts of a heating or cooling curve mean, or how evaporation differs from boiling.

Not for: kelvin conversions and gas pressure (phy-o-particles), or how energy moves by conduction, convection or
radiation (phy-o-heat-transfer).

## What this skill does not do

- It does not calculate the size of an expansion.
- It does not treat mixtures reaching a common temperature beyond energy lost = energy gained in words.
- It does not choose capacities or latent heats: the question or the pack gives them.

## Objectives

1. The student explains thermal expansion of solids, liquids and gases by particle spacing and gives a use or a problem.
2. The student uses E = mcΔθ to find the energy, the mass, the capacity or the temperature change.
3. The student uses E = mL with the right latent heat for melting or boiling, adding stages when both happen.
4. The student reads heating and cooling curves and tells evaporation from boiling.

## Prerequisite probe

- "A 50 W heater runs for 2 minutes. How much energy does it supply?" Expected: 6000 J (checked with math_evaluate).
- "Water warms from 20 °C to 35 °C. What is the rise in temperature?" Expected: 15 °C.

If the first fails, detour to power (phy-o-energy); if the second fails, revisit temperature differences, then return.

## Teaching sequence

1. Ask whether the substance changes temperature, changes state, or both. Done when the student names the stage or stages.
2. Ask for the givens: mass in kilograms, the temperature rise (final minus start), the capacity or latent heat, and any heater time in seconds. Done when every value has a unit and the rise is a difference.
3. For a temperature change, ask for E = mcΔθ; for a change of state, E = mL with fusion for melting and vaporisation for boiling. Done when the right relation is named for each stage.
4. Ask the student to substitute and add the stages if there are two; math_evaluate gives the reference. Done when the value matches the checked one.
5. For a curve, ask what the sloping and the flat parts show and where the energy goes on a flat part. Done when the student links flat parts to a change of state at a fixed temperature.
6. For expansion or evaporation, ask what the particles do: spread further apart, or the fastest ones escape the surface. Done when the explanation uses particle motion.

## Hint ladder

1. Orient: "Is the temperature changing here, the state, or both?"
2. Concept: "E = mcΔθ while the temperature changes; E = mL while the state changes at a fixed temperature."
3. First step: write the relation for each stage with the student's values and ask for the first value.
4. Worked step: show one stage's substitution and ask for its energy.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.bimetal_bends_towards_greater_expansion`: puts the brass on the inside of the curve → "Which metal gets longer, and which side of a bend is longer?"
- `mc.phy.o.expansion_order_reversed`: says solids expand more than gases → "Why does a balloon swell so much more than a metal rod when warmed?"
- `mc.phy.o.particles_grow_when_heated`: says the particles get bigger → "Do the particles grow, or do they move more and take more room?"
- `mc.phy.o.shc_final_temperature_used`: uses 70 °C as Δθ → "How many degrees did the water rise?"
- `mc.phy.o.thermal_grams_as_kg`: uses 500 g as 500 in E = mcΔθ → "The capacity is per kilogram. Is your mass in kilograms?"
- `mc.phy.o.heater_minutes_not_seconds`: uses minutes in E = Pt → "A watt is a joule each second. How many seconds did it run?"
- `mc.phy.o.shc_rearranged_wrongly`: works out E ÷ m × Δθ for c → "If c = E ÷ (mΔθ), where does Δθ go?"
- `mc.phy.o.latent_wrong_kind`: uses the latent heat of vaporisation for melting ice → "Is the ice turning into a liquid or a gas?"
- `mc.phy.o.latent_stage_omitted`: leaves out the melting when ice at 0 °C becomes warm water → "What must happen to the ice before the water can warm?"
- `mc.phy.o.temperature_rises_during_melting`: says the temperature rises while ice melts → "What does the flat part of the heating curve show?"
- `mc.phy.o.no_energy_when_temperature_constant`: says no energy goes in on a flat part → "The heater is still on. Where is that energy going?"
- `mc.phy.o.evaporation_only_at_boiling_point`: says puddles evaporate only at 100 °C → "How do puddles dry on a cool day?"
- `mc.phy.o.evaporation_removes_slow_particles`: says slow particles escape → "Which particles have enough energy to leave the surface?"

## Confidence and escalation

- Two failures on the stages: draw the heating curve with each stage labelled before calculating.
- Three failures on E = mcΔθ: detour to substituting into a product of three values, then return.
- A question with heat lost to the surroundings that it does not quantify: say the measured value will differ from the ideal one.

## Worked exchange

> Tutor: How much energy is needed to warm 0.50 kg of water from 20 °C to 70 °C? Water's specific heat capacity is 4200 J/(kg °C). First, what is the temperature rise?
> Student: 70 − 20 = 50 °C.
> Tutor: Good. Which relation links the energy, the mass and the rise?
> Student: E = mcΔθ, so 0.50 × 4200 × 50 = 105000 J.
> Tutor: Correct (checked with the maths tool), and that is 105 kJ.

## Verification checklist

- Masses are in kilograms and heater times in seconds.
- Δθ is a rise or fall, never a single reading.
- Each stage uses its own relation, and the stages are added.
- Every energy and unknown matches math_evaluate, and the unit passes units_check_dimensions.
- Explanations of expansion and evaporation use particle motion and spacing.
