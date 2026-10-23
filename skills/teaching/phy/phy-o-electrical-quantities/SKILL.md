---
name: phy-o-electrical-quantities
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach charge, current, potential difference and resistance with their graphs
description: "Electric charge, current, potential difference, resistance, wires, I-V graphs: move electrons when charging, use Q = It, W = QV and R = V ÷ I in base units, read I-V graphs. Not for: series and parallel circuits (phy-o-circuits) or power and cost (phy-o-practical-electricity)."
subject: physics
levels: [O]
topics: [electric charge, current, potential difference, emf, resistance, ohm's law, resistance of wires, i-v graphs]
kcs:
  - kc.phy.o.electrical_quantities.electric_charge
  - kc.phy.o.electrical_quantities.current_and_charge
  - kc.phy.o.electrical_quantities.potential_difference
  - kc.phy.o.electrical_quantities.resistance
  - kc.phy.o.electrical_quantities.resistance_of_wires
  - kc.phy.o.electrical_quantities.current_voltage_graphs
curriculum_refs: [PHY-O-04.02]
prerequisites:
  - kc.phy.o.energy.stores_and_transfers
related: [phy-o-circuits, phy-o-practical-electricity, phy-o-electromagnetism]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, phys_circuit, units_check_dimensions]
visuals: [circuit, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: current
    unit: A
    min: 0
    max: 100
    context: currents in lab circuits and household appliances
  - quantity: voltage
    unit: V
    min: 0
    max: 1000
    context: cells, batteries, lab supplies and the mains
  - quantity: resistance
    unit: ohm
    min: 0.001
    max: 10000000
    context: wires, lamps, resistors, sensors and diodes the wrong way round
  - quantity: charge
    unit: C
    min: 0
    max: 1000000
    context: charge passed in seconds to hours in lab circuits and appliances
  - quantity: energy
    unit: J
    min: 0
    max: 100000000
    context: energy transferred by charge in lab circuits and appliances
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student explains charging by friction as a transfer of electrons and predicts forces between charges
  - The student uses Q = It and W = QV with currents in amperes and times in seconds
  - The student calculates resistance, current or p.d. with R = V ÷ I
  - The student predicts how a wire's resistance changes with its length and cross-sectional area
  - The student reads I-V graphs for a fixed resistor, a filament lamp and a diode
---

# Charge, current, voltage and resistance

## When to use

Use when a question asks why a rubbed object is charged and what it attracts, for a charge, current or time with
Q = It, for an energy or a p.d. with W = QV, for a resistance with R = V ÷ I, how a wire's length or thickness
changes its resistance, or what an I-V graph says about a resistor, a lamp or a diode.

Not for: sharing current and p.d. in series and parallel circuits (phy-o-circuits), or power, kilowatt-hours and fuses
(phy-o-practical-electricity).

## What this skill does not do

- It does not use resistivity as a number.
- It does not treat internal resistance.
- It does not choose the charge on an electron: the pack gives 1.6 × 10⁻¹⁹ C.

## Objectives

1. The student explains charging by friction as a transfer of electrons and predicts forces between charges.
2. The student uses Q = It and W = QV with currents in amperes and times in seconds.
3. The student calculates resistance, current or p.d. with R = V ÷ I.
4. The student predicts how a wire's resistance changes with its length and cross-sectional area.
5. The student reads I-V graphs for a fixed resistor, a filament lamp and a diode.

## Prerequisite probe

- "Change 250 mA into amperes." Expected: 0.25 A.
- "Rearrange V = IR to give the current." Expected: current = V ÷ R.

If the first fails, practise prefixes (phy-o-measurement); if the second fails, practise rearranging, then return.

## Teaching sequence

1. For charging, ask which object gains electrons and which loses them. Done when the student gives each object's sign from the electrons it gained or lost.
2. Ask the student to list the givens with base units: amperes, seconds, volts, ohms, coulombs and joules. Done when every value is in base units.
3. Ask which relation links them: Q = It, W = QV or R = V ÷ I. Done when one relation is chosen with a reason.
4. Ask the student to rearrange and substitute; math_evaluate or phys_circuit gives the reference. Done when the value matches the checked one.
5. For a wire, ask what happens to the resistance if the length or the cross-sectional area changes, and by what factor. Done when the student scales with the length and inversely with the area.
6. For an I-V graph, ask for the shape, then R = V ÷ I at a point on the line. Done when the student names the component and says how its resistance changes.
7. Ask for the unit and a sense check. Done when the unit passes units_check_dimensions.

## Hint ladder

1. Orient: "Which quantities does the question give, and which does it want?"
2. Concept: name the relation in words, such as "current is the charge passing each second".
3. First step: write the relation with symbols and ask the student to put the numbers in, in base units.
4. Worked step: show the substitution and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.electron_gain_sign_reversed`: says the rod that gained electrons is positive → "Electrons are negative. What does gaining some do to the rod's charge?"
- `mc.phy.o.protons_move_in_charging`: says protons move onto the cloth → "Which particles are free to leave the surface of an atom?"
- `mc.phy.o.minutes_used_as_seconds`: puts 2 minutes into Q = It as 2 → "One coulomb is one ampere for how long?"
- `mc.phy.o.q_it_upside_down`: writes I = t ÷ Q → "Current is charge each second. Which goes on top?"
- `mc.phy.o.pd_flows_through_component`: says the p.d. flows through the lamp → "Where do the voltmeter's two leads go, through the lamp or either side of it?"
- `mc.phy.o.charge_used_up_in_lamp`: says less charge leaves the lamp → "Does the ammeter after the lamp read less than the one before it?"
- `mc.phy.o.w_qv_upside_down`: writes V = Q ÷ W → "A volt is a joule for each what?"
- `mc.phy.o.ohm_law_upside_down`: writes R = I ÷ V → "If a bigger p.d. is needed for the same current, is the resistance bigger or smaller?"
- `mc.phy.o.ohm_law_multiplied`: works out R = V × I → "Would a 12 V lamp taking 2 A really have 24 ohms?"
- `mc.phy.o.thicker_wire_more_resistance`: says a thicker wire resists more → "Is it easier to pour water through a wide pipe or a narrow one?"
- `mc.phy.o.diameter_used_as_area`: halves the resistance when the diameter doubles → "If the diameter doubles, what happens to the area of the circle?"
- `mc.phy.o.lamp_resistance_falls_when_hot`: says a hot filament resists less → "Why does the lamp's current-voltage graph bend towards the voltage axis?"
- `mc.phy.o.iv_gradient_is_resistance`: takes the I-V gradient as the resistance → "On a current-voltage graph, is the gradient voltage over current, or current over voltage?"
- `mc.phy.o.diode_conducts_both_ways`: says a diode conducts in reverse → "What does the diode's graph show for negative voltages?"

## Confidence and escalation

- Two failures on units: build the base units on the board (ampere, second, coulomb, volt, joule, ohm) and convert first.
- Three failures on rearranging: detour to rearranging a product or quotient, then return.
- A graph with no values at the point asked for: ask for the reading; never estimate without saying so.

## Worked exchange

> Tutor: A lamp takes a current of 0.50 A when the p.d. across it is 12 V. What is its resistance, and how much charge passes through it in 2 minutes? Start with the resistance.
> Student: R = V ÷ I = 12 ÷ 0.50 = 24 Ω.
> Tutor: Good. For the charge, what must the time be in?
> Student: Seconds: 2 × 60 = 120 s, so Q = It = 0.50 × 120 = 60 C.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- Currents are in amperes, times in seconds and energies in joules before substituting.
- Every charge, energy, p.d., current and resistance matches math_evaluate or phys_circuit.
- Charging explanations move electrons only.
- Wire resistance scales with length and inversely with cross-sectional area.
- The unit passes units_check_dimensions.
