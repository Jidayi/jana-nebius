---
name: phy-o-density
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach density from mass and volume, displacement and floating
description: "Density, mass and volume, displacement, floating and sinking: get the mass and the volume in matching units, divide mass by volume, find an odd shape's volume from the rise in water, then compare densities. Not for: pressure in liquids (phy-o-pressure) or convection (phy-o-heat-transfer)."
subject: physics
levels: [O]
topics: [density, mass and volume, displacement, measuring cylinder, floating and sinking]
kcs:
  - kc.phy.o.density.density_calculation
  - kc.phy.o.density.measuring_density
  - kc.phy.o.density.floating_and_sinking
curriculum_refs: [PHY-O-01.04]
prerequisites:
  - kc.phy.o.measurement.si_prefixes
  - kc.phy.o.measurement.measuring_techniques
related: [phy-o-measurement, phy-o-pressure, phy-o-heat-transfer]
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
  - quantity: density
    unit: kg/m^3
    min: 0.1
    max: 25000
    context: gases, liquids and solids from air to the densest metals
  - quantity: mass
    unit: kg
    min: 0.0001
    max: 10000
    context: samples weighed in a lab up to large blocks and tanks of liquid
  - quantity: volume
    unit: m^3
    min: 0.0000001
    max: 100
    context: objects measured in a cylinder up to a room or a tank
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student calculates density, mass or volume from the other two with consistent units
  - The student converts a density between g/cm³ and kg/m³ in the right direction
  - The student finds the volume of an irregular solid from the rise in water level or the overflow
  - The student predicts floating or sinking by comparing the object's density with the liquid's
---

# Density

## When to use

Use when a question asks for a density, a mass or a volume from the other two, how to measure the density of an
irregular solid or a liquid, or whether an object floats or sinks in a liquid.

Not for: the pressure under a liquid (phy-o-pressure), or why warm fluids rise (phy-o-heat-transfer).

## What this skill does not do

- It does not treat upthrust as a force calculation; floating is decided by comparing densities.
- It does not cover mixtures or alloys made from given proportions.
- It does not choose the density of water: the question or the pack gives it.

## Objectives

1. The student calculates density, mass or volume from the other two with consistent units.
2. The student converts a density between g/cm³ and kg/m³ in the right direction.
3. The student finds the volume of an irregular solid from the rise in water level or the overflow.
4. The student predicts floating or sinking by comparing the object's density with the liquid's.

## Prerequisite probe

- "Change 0.5 kg into grams." Expected: 500 g (checked with units_convert).
- "What is the volume of a block 2 cm by 3 cm by 5 cm?" Expected: 30 cm³.

If the first fails, practise prefixes (phy-o-measurement); if the second fails, revisit volume as length × width × height.

## Teaching sequence

1. Ask the student to list the mass and the volume with units, or the readings that will give them. Done when every given value has a unit.
2. For an irregular solid, ask for the volume as the rise in the cylinder level, or the volume that overflows from a full can. Done when the volume is a difference or an overflow, not a single reading.
3. For a liquid, ask for its mass as the full container minus the empty one. Done when the container's mass is taken off.
4. Ask the student to write density = mass ÷ volume, or its rearranged form, and substitute. Done when the value matches math_evaluate.
5. Ask whether the units match the answer wanted; to go from g/cm³ to kg/m³ multiply by 1000. Done when the converted value matches units_convert.
6. For floating, ask for the object's density beside the liquid's and which is larger. Done when the student says less dense floats and denser sinks, with both values.

## Hint ladder

1. Orient: "What do you know about the object's mass and its volume?"
2. Concept: "Density is the mass of each unit of volume: mass divided by volume."
3. First step: write density = mass ÷ volume with the student's values and ask for the result.
4. Worked step: show the substitution with units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.density_volume_over_mass`: divides volume by mass → "Density tells you how many grams each cubic centimetre holds. Which goes on top?"
- `mc.phy.o.density_units_not_converted`: gives 2.7 from g and cm³ as kg/m³ → "Is aluminium really less dense than air, at 2.7 kg/m³?"
- `mc.phy.o.density_conversion_direction_swapped`: divides by 1000 for kg/m³ → "A cubic metre holds a million cubic centimetres. Should the number in kg/m³ be bigger or smaller?"
- `mc.phy.o.block_volume_two_sides`: multiplies two sides of a block → "How many measurements does a box need to fix its volume?"
- `mc.phy.o.density_rearranged_wrongly`: divides density by volume to find the mass → "If each cubic centimetre has 8 g, how much do 10 of them have?"
- `mc.phy.o.displacement_final_reading_as_volume`: takes 65 cm³ as the stone's volume → "How much water was in the cylinder before the stone went in?"
- `mc.phy.o.displacement_can_not_filled`: starts with the can below its spout → "Will the first water pushed up come out of the spout or just fill the can?"
- `mc.phy.o.container_mass_not_subtracted`: uses the beaker and liquid together → "Which part of that reading is the beaker?"
- `mc.phy.o.cylinder_read_wrongly`: reads the top of the curved surface → "Where should your eye be, and which part of the curve do you read?"
- `mc.phy.o.density_float_rule_reversed`: says denser objects float → "Does a stone, denser than water, float?"
- `mc.phy.o.mass_decides_floating`: says heavy objects sink → "A large log is heavier than a small pebble. Which one floats?"
- `mc.phy.o.hollow_object_density_of_material`: says a steel ship must sink → "What fills most of the space inside the hull?"

## Confidence and escalation

- Two wrong conversions between g/cm³ and kg/m³: use water, 1 g/cm³ and 1000 kg/m³, as the anchor.
- Three failures on the formula: detour to rearranging a quotient, then return.
- A floating question with no density for the liquid: ask for it or use the value the question gives.

## Worked exchange

> Tutor: A stone of mass 75 g is lowered into a measuring cylinder, and the water level rises from 40 cm³ to 65 cm³. What is the stone's density? First, what is its volume?
> Student: The rise: 65 − 40 = 25 cm³.
> Tutor: Good. Now the density?
> Student: Mass over volume: 75 ÷ 25 = 3.0 g/cm³.
> Tutor: Right. What is that in kg/m³?
> Student: Multiply by 1000, so 3000 kg/m³.
> Tutor: Correct (checked with the units tool), and as it is denser than water, the stone sinks.

## Verification checklist

- The volume of an irregular solid is a rise in level or an overflow, never one reading.
- Mass and volume are in matching units before dividing, and the unit passes units_check_dimensions.
- Every density, mass and volume matches math_evaluate; conversions match units_convert.
- A floating prediction names both densities.
