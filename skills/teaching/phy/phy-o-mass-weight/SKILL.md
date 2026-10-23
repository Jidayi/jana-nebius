---
name: phy-o-mass-weight
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach weight as mass times g and how mass and weight differ elsewhere
description: "Mass and weight, gravitational field strength, weight on other planets: separate the amount of matter from the pull on it, use W = mg in kilograms, and change g, never the mass, for another world. Not for: falling under gravity (phy-o-motion) or orbits (phy-o-solar-system)."
subject: physics
levels: [O]
topics: [mass, weight, gravitational field strength, weight on other planets, newton meter, beam balance]
kcs:
  - kc.phy.o.mass_weight.weight_from_mass
  - kc.phy.o.mass_weight.mass_or_weight
curriculum_refs: [PHY-O-01.03]
prerequisites:
  - kc.phy.o.measurement.si_prefixes
related: [phy-o-forces, phy-o-solar-system, phy-o-measurement]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_check_dimensions]
visuals: [knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: mass
    unit: kg
    min: 0.001
    max: 100000
    context: objects from a coin to a loaded lorry
  - quantity: weight
    unit: N
    min: 0.001
    max: 1000000
    context: weights of everyday objects, people and vehicles on the Earth, the Moon or a planet
  - quantity: field_strength
    unit: N/kg
    min: 0.1
    max: 30
    context: gravitational field strength at the surface of moons and planets in the Solar System
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student calculates weight from mass with W = mg, with the mass in kilograms
  - The student finds a mass from a weight by dividing by the field strength of the place where it was measured
  - The student explains that mass stays the same everywhere while weight changes with g
  - The student matches a beam balance to mass and a newton meter to weight
---

# Mass and weight

## When to use

Use when a question asks for a weight from a mass or a mass from a weight, compares an object on the Earth with the
same object on the Moon or a planet, or asks which instrument measures mass and which measures weight.

Not for: the motion of a falling object (phy-o-motion), or how gravity keeps planets in orbit (phy-o-solar-system).

## What this skill does not do

- It does not use the law of gravitation; field strengths come from the question.
- It does not choose g for the Earth: the question or the pack convention gives it.
- It does not treat apparent weight in lifts or in orbit.

## Objectives

1. The student calculates weight from mass with W = mg, with the mass in kilograms.
2. The student finds a mass from a weight by dividing by the field strength of the place where it was measured.
3. The student explains that mass stays the same everywhere while weight changes with g.
4. The student matches a beam balance to mass and a newton meter to weight.

## Prerequisite probe

- "Change 250 g into kilograms." Expected: 0.25 kg.
- "Make m the subject of W = mg." Expected: m = W ÷ g.

If the first fails, practise prefixes (phy-o-measurement); if the second fails, practise rearranging, then return.

## Teaching sequence

1. Ask the student to say in words what mass is and what weight is, with the unit of each. Done when mass is in kilograms and weight is a force in newtons.
2. Ask where the object is and which value of g belongs to that place. Done when the g used matches the place in the question.
3. Ask for the mass in kilograms before any calculation. Done when every mass is in kilograms.
4. Ask the student to write W = mg, or m = W ÷ g, and substitute; math_evaluate gives the reference value. Done when the student's value matches the checked one.
5. For a move to another world, ask what happens to the mass first, then work out the new weight from the new g. Done when the mass is unchanged and the new weight matches the checked value.
6. Ask which instrument would read differently on the Moon. Done when the newton meter is named for weight and the beam balance for mass.

## Hint ladder

1. Orient: "Is the question about the amount of matter or about the pull of gravity on it?"
2. Concept: "Weight is the force of gravity on a mass: W = mg, with g for the place the object is."
3. First step: write W = mg with the g of the right place and ask for the substitution.
4. Worked step: show the substitution and ask for the value with its unit.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.weight_given_as_mass_number`: gives 5 kg as the weight → "Weight is a force. What unit does a force have?"
- `mc.phy.o.weight_grams_not_converted`: multiplies 500 g by g → "g is in newtons per kilogram. Is your mass in kilograms yet?"
- `mc.phy.o.weight_mass_divided_by_g`: divides the mass by g for the weight → "Should a 10 kg bag weigh more or less than 10 N on the Earth?"
- `mc.phy.o.planet_g_mismatched`: uses the Earth's g for an object on Mars → "Where is the object standing, and what is g there?"
- `mc.phy.o.mass_changes_with_g`: says the mass is smaller on the Moon → "Does any of the astronaut's matter get left behind on the Earth?"
- `mc.phy.o.no_mass_in_space`: says a floating astronaut has no mass → "Would a floating astronaut still be hard to push into motion?"
- `mc.phy.o.mass_weight_units_swapped`: writes a weight in kilograms → "Which of the two is a force, and what is a force measured in?"
- `mc.phy.o.balance_types_confused`: thinks a beam balance reads less on the Moon → "If gravity weakens on both pans equally, does the balance tip?"
- `mc.phy.o.planet_g_ratio_inverted`: multiplies by the stronger g over the weaker → "On a world with weaker gravity, should the weight go up or down?"

## Confidence and escalation

- Two failures on the unit of weight: compare a kilogram bag on a balance with the same bag on a newton meter, then try again.
- Three failures on the arithmetic: detour to rearranging W = mg, then return.
- A question that gives no g for a place: ask for it or use the value the question supplies; never invent one.

## Worked exchange

> Tutor: An astronaut has a mass of 70 kg. On the Moon, g is 1.6 N/kg. What are her mass and her weight on the Moon?
> Student: Her mass is still 70 kg, because the amount of matter does not change.
> Tutor: Good. How do you get the weight?
> Student: W = mg, so 70 × 1.6 = 112 N.
> Tutor: Correct (checked with the maths tool). How does that compare with her weight on the Earth, where g is 9.8 N/kg?
> Student: 70 × 9.8 = 686 N, so she weighs much less on the Moon but has the same mass.
> Tutor: Right (checked): the weight changes with g, and the mass does not.

## Verification checklist

- Every mass is in kilograms before W = mg.
- The g used belongs to the place the object is, or where the weight was measured.
- Weights are in newtons and masses in kilograms, and the unit passes units_check_dimensions.
- Every weight and mass matches math_evaluate.
- A mass is never changed by moving the object to another world.
