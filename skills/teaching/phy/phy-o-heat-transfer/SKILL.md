---
name: phy-o-heat-transfer
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach conduction, convection and infrared radiation with particle reasons
description: "Conduction, convection, radiation, insulation: say which way energy flows, name the process and its medium, explain it with particles, density or the surface, then judge a design. Not for: heating a mass (phy-o-thermal-properties) or the spectrum (phy-o-em-spectrum)."
subject: physics
levels: [O]
topics: [conduction, convection, radiation, infrared, insulation, vacuum flask, sea breeze]
kcs:
  - kc.phy.o.heat_transfer.conduction
  - kc.phy.o.heat_transfer.convection
  - kc.phy.o.heat_transfer.radiation
curriculum_refs: [PHY-O-02.03]
prerequisites:
  - kc.phy.o.particles.states_of_matter
  - kc.phy.o.density.floating_and_sinking
related: [phy-o-thermal-properties, phy-o-particles, phy-o-em-spectrum]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate]
visuals: [library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: temperature
    unit: degC
    min: -100
    max: 1500
    context: everyday hot and cold objects, rooms, the sea, ovens and fires
  - quantity: time
    unit: s
    min: 1
    max: 100000
    context: cooling and heating experiments from seconds to a day
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student explains conduction by particle vibrations and, in metals, free electrons, and ranks conductors
  - The student explains a convection current by warm fluid becoming less dense and rising
  - The student relates infrared emission and absorption to a surface's colour, texture and temperature
  - The student explains how a design such as a vacuum flask reduces each kind of transfer
---

# Conduction, convection and radiation

## When to use

Use when a question asks how energy moves through a solid, why a fluid circulates when heated, which surface emits or
absorbs infrared best, why a metal feels colder than wood, how sea breezes form, or how a vacuum flask or a house
reduces energy loss.

Not for: how much energy heats or melts a mass (phy-o-thermal-properties), or the wider electromagnetic spectrum
(phy-o-em-spectrum).

## What this skill does not do

- It does not calculate rates of energy transfer.
- It does not treat the greenhouse effect beyond infrared emission and absorption.
- It does not rank materials beyond good and poor conductors and the surfaces in the question.

## Objectives

1. The student explains conduction by particle vibrations and, in metals, free electrons, and ranks conductors.
2. The student explains a convection current by warm fluid becoming less dense and rising.
3. The student relates infrared emission and absorption to a surface's colour, texture and temperature.
4. The student explains how a design such as a vacuum flask reduces each kind of transfer.

## Prerequisite probe

- "Which can flow: the particles of a solid, a liquid or a gas?" Expected: those of liquids and gases.
- "Warm air and cool air: which is less dense?" Expected: warm air.

If the first fails, detour to the particle model (phy-o-particles); if the second fails, to floating (phy-o-density).

## Teaching sequence

1. Ask which way the energy flows. Done when the student says from the hotter place to the colder place.
2. Ask what is between them: a solid, a fluid, or empty space. Done when the medium is named.
3. Name the process that fits: conduction through solids, convection in fluids, radiation through anything and through a vacuum. Done when the student names the process with its medium.
4. For conduction, ask how vibrations pass along, and what extra carriers a metal has. Done when the student mentions vibrating particles and, for metals, free electrons.
5. For convection, ask what happens to the warm fluid's density and where the cooler fluid goes. Done when the student describes the full loop of the current.
6. For radiation, ask how the surface's colour, texture and temperature change emission and absorption. Done when dull black is named the best emitter and absorber and shiny silver the poorest.
7. For a design, ask which part stops or slows each process. Done when every process has a part that reduces it.

## Hint ladder

1. Orient: "Where is it hotter, and what lies between the hot place and the cold one?"
2. Concept: "Conduction needs touching particles, convection needs a fluid that can flow, radiation needs neither."
3. First step: name the process and ask the student what the particles, the fluid or the surface does.
4. Worked step: give the first half of the explanation and ask the student to finish it.
5. Full step: give the full explanation; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.metal_conduction_vibration_only`: explains metal conduction by vibrations alone → "What do metals have that wood does not, which can move through the whole piece?"
- `mc.phy.o.metal_feels_colder_because_colder`: says the metal is at a lower temperature → "Both have been in the room all night. Which one takes energy from your hand faster?"
- `mc.phy.o.insulator_produces_heat`: says a blanket makes heat → "Would a blanket wrapped round an ice cube warm it up?"
- `mc.phy.o.cold_transferred_as_substance`: says cold flows into the drink → "Which way does energy flow between ice and warm juice?"
- `mc.phy.o.heated_fluid_denser`: says warm water sinks → "When a fluid expands, what happens to the mass in each cubic centimetre?"
- `mc.phy.o.heat_itself_rises`: says heat rises on its own → "What pushes the warm air up?"
- `mc.phy.o.convection_in_solids`: puts convection in a metal bar → "Can the particles of a solid flow from one place to another?"
- `mc.phy.o.sea_warms_faster_than_land`: gets the day breeze backwards → "On a sunny day, which warms up faster, the sand or the sea?"
- `mc.phy.o.shiny_surfaces_better_radiators`: says shiny surfaces emit more → "Why are kettles shiny and radiators often dark?"
- `mc.phy.o.good_absorber_poor_emitter`: says a black surface absorbs well but emits badly → "Which can cooled faster in the experiment, the black one or the silver one?"
- `mc.phy.o.cold_objects_do_not_radiate`: says cool objects give out no infrared → "How does a thermal camera see a person in the dark?"
- `mc.phy.o.radiation_needs_medium`: says infrared needs air → "How does energy from the Sun reach the Earth?"
- `mc.phy.o.vacuum_stops_radiation`: says the vacuum stops radiation → "If light crosses space, can the vacuum stop infrared? What do the silvered walls do?"

## Confidence and escalation

- Two failures on naming the process: switch to a diagram with the hot place, the cold place and the medium drawn.
- Three failures on convection: draw the loop step by step with density labels, then ask again.
- A design question about materials not in the question: ask which properties are known before judging.

## Worked exchange

> Tutor: Two identical cans each hold 200 cm³ of water at 80 °C. One is painted dull black and the other is shiny silver. After 10 minutes, which is cooler, and why? First, how does each can lose energy to the room?
> Student: By conduction and convection in the air, and by giving out infrared radiation.
> Tutor: Good. Which surface is the better emitter of infrared?
> Student: The dull black one, so that can cools faster.
> Tutor: Right. Does the shiny can give out no infrared at all?
> Student: It still emits some, just less, because every warm object radiates.
> Tutor: Correct: after 10 minutes the black can is the cooler one.

## Verification checklist

- The energy flows from hotter to colder in every explanation.
- Each process is matched to its medium: solids, fluids, or any medium and a vacuum.
- Convection explanations say the warm fluid is less dense and rises, and the cooler fluid sinks to replace it.
- Radiation explanations rank dull black above shiny silver for both emitting and absorbing.
- Any temperature or time compared is taken from the question or checked with math_evaluate.
