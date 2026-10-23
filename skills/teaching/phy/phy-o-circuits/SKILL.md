---
name: phy-o-circuits
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach series, parallel and mixed circuits, potential dividers and sensors
description: "Series and parallel circuits, combined resistance, potential dividers, thermistors, LDRs, diodes: same current in series, same p.d. in parallel, combine groups step by step. Not for: one component or I-V graphs (phy-o-electrical-quantities) or mains safety (phy-o-practical-electricity)."
subject: physics
levels: [O]
topics: [series circuits, parallel circuits, combined resistance, mixed circuits, potential divider, thermistor, light-dependent resistor, diode, circuit symbols]
kcs:
  - kc.phy.o.circuits.series_circuits
  - kc.phy.o.circuits.parallel_circuits
  - kc.phy.o.circuits.mixed_circuits
  - kc.phy.o.circuits.potential_dividers
  - kc.phy.o.circuits.circuit_components
curriculum_refs: [PHY-O-04.03]
prerequisites:
  - kc.phy.o.electrical_quantities.resistance
  - kc.phy.o.electrical_quantities.current_voltage_graphs
related: [phy-o-electrical-quantities, phy-o-practical-electricity]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve, phys_circuit, units_check_dimensions]
visuals: [circuit, circuit_sim, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: current
    unit: A
    min: 0
    max: 50
    context: currents in lab circuits with cells, lamps and resistors
  - quantity: voltage
    unit: V
    min: 0
    max: 1000
    context: supply and component p.d.s in lab and household circuits
  - quantity: resistance
    unit: ohm
    min: 0.01
    max: 10000000
    context: resistors, lamps, thermistors and light-dependent resistors
  - quantity: power
    unit: W
    min: 0
    max: 10000
    context: power in components of lab and household circuits
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds the current, the p.d.s and the total resistance in a series circuit
  - The student finds branch currents and the combined resistance of resistors in parallel
  - The student solves a circuit with resistors in series and in parallel by combining groups step by step
  - The student calculates a potential divider's output and predicts the effect of a thermistor or an LDR
  - The student identifies circuit symbols and describes how thermistors, LDRs and diodes behave
---

# Series and parallel circuits

## When to use

Use when a question gives a circuit diagram or a description and asks for a current, a p.d., a total resistance, the
output of a potential divider, how a sensor circuit responds to heat or light, or what a diode does.

Not for: Q = It, R = V ÷ I for one component and I-V graphs (phy-o-electrical-quantities), or power ratings, fuses and
mains wiring (phy-o-practical-electricity).

## What this skill does not do

- It does not use Kirchhoff's laws beyond the series and parallel rules.
- It does not treat internal resistance.
- It does not treat logic gates or transistors.

## Objectives

1. The student finds the current, the p.d.s and the total resistance in a series circuit.
2. The student finds branch currents and the combined resistance of resistors in parallel.
3. The student solves a circuit with resistors in series and in parallel by combining groups step by step.
4. The student calculates a potential divider's output and predicts the effect of a thermistor or an LDR.
5. The student identifies circuit symbols and describes how thermistors, LDRs and diodes behave.

## Prerequisite probe

- "A 6 V supply is across a 3 Ω resistor. What is the current?" Expected: 2 A (checked with math_evaluate).
- "What is 1/6 + 1/3 as one fraction?" Expected: 1/2.

If the first fails, detour to R = V ÷ I (phy-o-electrical-quantities); if the second fails, practise adding fractions.

## Teaching sequence

1. Ask the student to redraw or describe the circuit and mark which parts are in series and which in parallel. Done when each group is labelled.
2. For series, ask what is the same everywhere (the current) and what adds (the p.d.s and the resistances). Done when the student states both rules.
3. For parallel, ask what is the same across each branch (the p.d.) and what adds (the branch currents); the combined resistance comes from adding reciprocals. Done when the student states both rules.
4. For a mixed circuit, ask the student to replace each parallel group by its combined resistance, then add the series parts. Done when the total matches phys_circuit.
5. Ask for the supply current, then share the p.d.s and the branch currents. Done when every value matches phys_circuit.
6. For a potential divider, ask for the output as supply × R₂ ÷ (R₁ + R₂) and what happens when a sensor's resistance changes. Done when the value matches the checked one and the direction of change is right.
7. For a component, ask what its resistance depends on, or which way a diode conducts. Done when the student gives the behaviour with its condition.

## Hint ladder

1. Orient: "Which components are in series with each other, and which are side by side in parallel?"
2. Concept: "Series: one current, p.d.s add. Parallel: one p.d., currents add."
3. First step: combine the innermost group and ask for the next step.
4. Worked step: show the total resistance and ask for the supply current.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.series_current_used_up`: says the current is smaller after each lamp → "Where could the charge go between the two ammeters?"
- `mc.phy.o.series_pd_shared_equally`: splits 12 V equally between 2 Ω and 4 Ω → "Which resistor needs more energy from each coulomb to push the same current through?"
- `mc.phy.o.series_resistance_averaged`: averages resistors in series → "Does adding a second resistor in a line make it harder or easier for the current?"
- `mc.phy.o.parallel_reciprocal_not_inverted`: gives 1/2 as the resistance → "Is 1/2 the resistance, or one over the resistance?"
- `mc.phy.o.parallel_resistances_added`: adds 6 Ω and 3 Ω in parallel → "Should the pair be harder to pass than the 3 Ω alone, when it offers two paths?"
- `mc.phy.o.parallel_current_split_equally`: splits the current equally between 6 Ω and 3 Ω → "Which branch is easier for the current to take?"
- `mc.phy.o.parallel_adding_branch_raises_resistance`: says another branch raises the total → "With an extra path, does more current or less flow from the supply?"
- `mc.phy.o.mixed_branch_gets_full_supply`: puts 12 V across the parallel pair → "The series resistor takes some of the p.d. How much is left for the pair?"
- `mc.phy.o.mixed_series_resistor_left_out`: forgets the series resistor in the total → "Is the 4 Ω part of the path from the supply and back?"
- `mc.phy.o.divider_ratio_of_resistors`: uses R₂ ÷ R₁ → "What share of the whole resistance is R₂?"
- `mc.phy.o.ldr_resistance_rises_with_light`: says an LDR resists more in light → "Why does a street light controlled by an LDR switch on at dusk?"
- `mc.phy.o.thermistor_resistance_rises_with_heat`: says a thermistor resists more when hot → "As this thermistor warms, does it let more current through or less?"
- `mc.phy.o.diode_direction_reversed`: reads the diode symbol backwards → "Which way does the triangle in the symbol point the current?"
- `mc.phy.o.thermistor_ldr_confused`: says a thermistor responds to light → "What does the 'thermo' part of thermistor tell you it senses?"

## Confidence and escalation

- Two failures on the series and parallel rules: switch to the circuit simulation and watch the meters as a branch is added.
- Three failures on combining groups: detour to adding reciprocals, then return.
- A circuit the student cannot reduce to series and parallel groups: solve it with phys_circuit and ask for help to explain it.

## Worked exchange

> Tutor: A 12 V supply is connected to a 4 Ω resistor in series with a parallel pair of 6 Ω and 3 Ω. What is the current from the supply? First, combine the parallel pair.
> Student: 1/R = 1/6 + 1/3 = 1/2, so R = 2 Ω.
> Tutor: Good. What is the total resistance?
> Student: 2 + 4 = 6 Ω.
> Tutor: Right. Now the current.
> Student: I = V ÷ R = 12 ÷ 6 = 2 A.
> Tutor: Correct (checked with the circuit tool). How is the 12 V shared?
> Student: The 4 Ω takes 2 × 4 = 8 V, so the parallel pair has 12 − 8 = 4 V.
> Tutor: Correct (checked with the circuit tool).

## Verification checklist

- Each group is labelled series or parallel before any calculation.
- Combined resistances, currents and p.d.s match phys_circuit.
- P.d.s round any loop add up to the supply, and branch currents add up to the supply current.
- Divider outputs and sensor predictions name the direction of change.
- The unit passes units_check_dimensions.
