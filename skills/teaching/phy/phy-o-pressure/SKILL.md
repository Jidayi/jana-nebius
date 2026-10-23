---
name: phy-o-pressure
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach pressure as force over area, liquid pressure and barometer readings
description: "Pressure, force on an area, pressure in liquids, barometers and manometers: use p = F ÷ A with the area in m², p = ρgh with the depth in metres, then read a column height against atmospheric pressure. Not for: gas pressure and volume (phy-o-particles) or floating (phy-o-density)."
subject: physics
levels: [O]
topics: [pressure, force on an area, liquid pressure, depth, barometer, manometer, atmospheric pressure]
kcs:
  - kc.phy.o.pressure.pressure_on_surfaces
  - kc.phy.o.pressure.liquid_pressure
  - kc.phy.o.pressure.gas_and_atmospheric_pressure
curriculum_refs: [PHY-O-01.08]
prerequisites:
  - kc.phy.o.mass_weight.weight_from_mass
  - kc.phy.o.density.density_calculation
related: [phy-o-density, phy-o-particles, phy-o-mass-weight]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_convert, units_check_dimensions]
visuals: [knowns_panel, library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: pressure
    unit: Pa
    min: 0
    max: 200000000
    context: pressures under shoes and tyres, in pools and the deep sea, and of the air and gas supplies
  - quantity: force
    unit: N
    min: 0
    max: 10000000
    context: weights and pushes on floors, pistons and walls
  - quantity: area
    unit: m^2
    min: 0.00000001
    max: 1000
    context: from a needle point to a large floor or a dam wall
  - quantity: height
    unit: m
    min: 0
    max: 11000
    context: depths in pools, tanks and the sea, and liquid columns in barometers and manometers
  - quantity: density
    unit: kg/m^3
    min: 500
    max: 14000
    context: liquids from oils to mercury
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student calculates pressure as force ÷ area with the area in square metres
  - The student explains how a change of area changes the pressure for the same force
  - The student calculates the change in pressure in a liquid with ρgh, using the depth difference in metres
  - The student reads a barometer or a manometer and adds or takes away the column pressure from atmospheric pressure
---

# Pressure

## When to use

Use when a question asks for the pressure under an object, why sharp or wide objects behave as they do, the pressure
at a depth in a liquid, or the pressure of the air or a gas from a barometer or a manometer.

Not for: how the pressure of a gas changes with its volume (phy-o-particles), or whether an object floats
(phy-o-density).

## What this skill does not do

- It does not treat hydraulic machines beyond pressure = force ÷ area.
- It does not choose atmospheric pressure: the question or the pack gives it.
- It does not treat upthrust as a calculation.

## Objectives

1. The student calculates pressure as force ÷ area with the area in square metres.
2. The student explains how a change of area changes the pressure for the same force.
3. The student calculates the change in pressure in a liquid with ρgh, using the depth difference in metres.
4. The student reads a barometer or a manometer and adds or takes away the column pressure from atmospheric pressure.

## Prerequisite probe

- "What is the area of a face 0.20 m by 0.50 m?" Expected: 0.10 m² (checked with math_evaluate).
- "What is the weight of a 60 kg person where g = 9.8 N/kg?" Expected: 588 N.

If the first fails, revisit area; if the second fails, detour to weight (phy-o-mass-weight), then return.

## Teaching sequence

1. Ask what pushes and on what area: a solid on a surface, a liquid at a depth, or a gas in a tube. Done when the student names the situation.
2. For a solid, ask for the force in newtons (a weight is mg) and the area in m²; cm² to m² divides by 10 000. Done when both are in SI units, checked with units_convert.
3. Ask the student to substitute into p = F ÷ A, or its rearranged form. Done when the value matches math_evaluate.
4. For a liquid, ask for the depth difference in metres and the liquid's density, then Δp = ρgΔh. Done when the value matches math_evaluate.
5. Ask whether the question wants the pressure from the liquid alone or the total, which adds atmospheric pressure. Done when the student says which and why.
6. For a manometer, ask for the difference between the two levels and which side is pushed down; for a barometer, the vertical column height. Done when the gas or air pressure matches the checked value.
7. Ask for the unit and a sense check against everyday pressures. Done when the unit passes units_check_dimensions and the value is sensible.

## Hint ladder

1. Orient: "What is pushing, and over what area or through what depth?"
2. Concept: "Pressure is force on each square metre; in a liquid it grows with depth and density."
3. First step: write p = F ÷ A or Δp = ρgΔh with the student's values and ask for the units.
4. Worked step: show the substitution in SI units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.pressure_area_cm2_not_converted`: divides newtons by cm² and calls it pascals → "A pascal is a newton on each square what?"
- `mc.phy.o.pressure_area_factor_not_squared`: divides cm² by a hundred → "A square metre is 100 cm by 100 cm. How many square centimetres is that?"
- `mc.phy.o.larger_area_larger_pressure`: says a wider area gives more pressure → "Why do snowshoes stop you sinking into snow?"
- `mc.phy.o.pressure_mass_used_as_force`: divides kilograms by the area → "Pressure needs a force. What force does a mass of 60 kg exert?"
- `mc.phy.o.liquid_pressure_depends_on_volume`: says a wide tank has more pressure at the bottom → "In ρgh, where does the width of the tank appear?"
- `mc.phy.o.liquid_depth_cm_not_converted`: uses 30 cm as 30 in ρgh → "The density is in kg/m³. What unit must the depth be in?"
- `mc.phy.o.liquid_pressure_atmosphere_left_out`: gives ρgh as the total → "Is the air pressing on the water's surface too?"
- `mc.phy.o.liquid_pressure_only_downwards`: says water pushes only down → "Why does water spurt sideways from a hole in the side of a bottle?"
- `mc.phy.o.manometer_excess_as_gas_pressure`: gives the level difference as the gas pressure → "What is pressing on the open side of the tube?"
- `mc.phy.o.manometer_one_level_used`: reads one level off the scale → "Which two levels show how hard the gas pushes?"
- `mc.phy.o.barometer_space_holds_air`: says air fills the top of the tube → "If air filled the space, would the mercury column stay up?"
- `mc.phy.o.air_pressure_increases_with_height`: says the air pressure is higher on a mountain → "Is there more or less air above you on a mountain top?"

## Confidence and escalation

- Two failures on cm² to m²: draw a 1 m square split into 100 by 100 small squares.
- Three failures on ρgh: detour to density (phy-o-density), then return.
- A question that gives no atmospheric pressure but needs a total: ask for it; never assume a value.

## Worked exchange

> Tutor: A diver is 3.0 m below the surface of a pool. Water has a density of 1000 kg/m³, g is 9.8 N/kg and the air presses on the surface at 100 kPa. What is the total pressure on the diver? First, which relation gives the pressure from the water?
> Student: Pressure = ρgh.
> Tutor: Good. Put the values in, with the depth in metres.
> Student: 1000 × 9.8 × 3.0 = 29400 Pa, which is 29.4 kPa.
> Tutor: Right. Now the total?
> Student: 29.4 + 100 = 129.4 kPa, so about 129 kPa.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- Forces are in newtons, areas in m² and depths in metres before substituting.
- Every pressure matches math_evaluate, and conversions match units_convert.
- A liquid pressure uses the depth difference and says whether atmospheric pressure is included.
- A manometer reading uses the difference between the levels.
- The unit passes units_check_dimensions.
