---
name: phy-o-practical-electricity
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach electrical power, kilowatt-hours, the cost of electricity and fuses
description: "Electrical power, kilowatt-hours, cost of electricity, fuses, live, neutral and earth wires: pick the power formula, use kW and hours for kWh, fit the fuse just above the working current. Not for: circuit rules (phy-o-circuits) or transformers (phy-o-electromagnetism)."
subject: physics
levels: [O]
topics: [electrical power, kilowatt-hours, cost of electricity, fuses, circuit breakers, live wire, neutral wire, earth wire, double insulation]
kcs:
  - kc.phy.o.practical_electricity.electrical_power
  - kc.phy.o.practical_electricity.energy_cost
  - kc.phy.o.practical_electricity.fuses_and_safety
curriculum_refs: [PHY-O-04.04]
prerequisites:
  - kc.phy.o.electrical_quantities.resistance
  - kc.phy.o.energy.power
related: [phy-o-electrical-quantities, phy-o-circuits, phy-o-energy, phy-o-electromagnetism]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, phys_circuit, units_convert, units_check_dimensions]
visuals: [circuit, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: power
    unit: W
    min: 0
    max: 15000
    context: household appliances from a phone charger to an electric shower
  - quantity: current
    unit: A
    min: 0
    max: 100
    context: currents drawn by household appliances and lab components
  - quantity: voltage
    unit: V
    min: 0
    max: 1000
    context: cells, lab supplies and mains supplies
  - quantity: energy
    unit: kWh
    min: 0
    max: 100000
    context: electricity used by appliances and homes over days to a year
  - quantity: fuse_rating
    unit: A
    min: 1
    max: 60
    context: plug fuses and circuit breakers in homes
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student calculates electrical power with P = IV and P = I²R, and the current from a power rating
  - The student calculates electrical energy in joules and in kilowatt-hours with the right units of power and time
  - The student calculates the cost of using an appliance over a stated time
  - The student selects a fuse rating just above the working current and explains the roles of the live, neutral and earth wires
---

# Electricity at home

## When to use

Use when a question asks for an appliance's power or current, the energy it uses in joules or kilowatt-hours, what it
costs to run, which fuse to fit, or what the live, neutral and earth wires, fuses, circuit breakers and double
insulation do.

Not for: sharing current and p.d. in circuits (phy-o-circuits), or transformers and power lines
(phy-o-electromagnetism).

## What this skill does not do

- It does not treat alternating current beyond the mains values the question gives.
- It does not set prices: the cost per kilowatt-hour comes from the question.
- It does not give wiring instructions for real installations; safety is explained, not practised.

## Objectives

1. The student calculates electrical power with P = IV and P = I²R, and the current from a power rating.
2. The student calculates electrical energy in joules and in kilowatt-hours with the right units of power and time.
3. The student calculates the cost of using an appliance over a stated time.
4. The student selects a fuse rating just above the working current and explains the roles of the live, neutral and earth wires.

## Prerequisite probe

- "Change 1500 W into kilowatts." Expected: 1.5 kW (checked with units_convert).
- "A 6 V lamp takes 2 A. What is its power?" Expected: 12 W.

If the first fails, practise prefixes (phy-o-measurement); if the second fails, detour to power (phy-o-energy).

## Teaching sequence

1. Ask which quantities are given: power, current, p.d., resistance, time, price. Done when each has a unit.
2. For power, ask which formula fits the givens: P = IV, P = I²R, or I = P ÷ V for a current. Done when the value matches math_evaluate or phys_circuit.
3. For energy in joules, ask for watts and seconds; for kilowatt-hours, kilowatts and hours. Done when the units are a matching pair, checked with units_convert.
4. Ask for E = Pt, then the total over every day of use. Done when the energy matches math_evaluate.
5. For cost, ask for energy in kWh × price per kWh. Done when the cost matches the checked value with its currency unit.
6. For a fuse, ask for the working current and the fuse ratings on offer, then the smallest rating above the current. Done when the chosen fuse is above the working current and the next one up is not chosen.
7. For safety, ask what each wire, the fuse and the earth connection do in a fault. Done when the student says the fuse protects the wiring and the earth keeps a metal case safe.

## Hint ladder

1. Orient: "Is the question about the rate (power), the amount (energy), the money, or safety?"
2. Concept: "Energy = power × time; in kWh the power is in kilowatts and the time in hours."
3. First step: write the formula with the student's values and ask whether the units match.
4. Worked step: show the substitution with units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.electric_power_current_not_squared`: uses P = IR → "In P = I²R, what happens to the current before you multiply?"
- `mc.phy.o.electric_power_current_inverted`: works out I = V ÷ P → "Should a more powerful kettle at the same p.d. draw more current or less?"
- `mc.phy.o.electric_power_kw_not_converted`: puts 2 kW into I = P ÷ V as 2 → "How many watts is 2 kW?"
- `mc.phy.o.kwh_time_left_in_minutes`: multiplies kilowatts by minutes → "The kWh uses which unit of time?"
- `mc.phy.o.kwh_power_left_in_watts`: multiplies watts by hours and calls it kWh → "Is your power in watts or kilowatts?"
- `mc.phy.o.kwh_divided_by_3600_only`: divides joules by 3600 for kWh → "That gives watt-hours. How many watt-hours make a kilowatt-hour?"
- `mc.phy.o.energy_cost_days_left_out`: gives the cost for one day → "How many days does the question cover?"
- `mc.phy.o.fuse_rating_below_current`: picks a 3 A fuse for 8.7 A → "What happens to a 3 A fuse when 8.7 A flows through it?"
- `mc.phy.o.fuse_largest_always_safest`: picks the biggest fuse → "If a fault made 12 A flow, would a 30 A fuse melt?"
- `mc.phy.o.fuse_in_neutral_wire`: puts the fuse in the neutral → "If the fuse in the neutral melts, is the appliance still joined to the live wire?"
- `mc.phy.o.earth_wire_carries_working_current`: says the earth carries the normal current → "In normal use, does the metal case carry any current?"
- `mc.phy.o.fuse_protects_person_from_shock`: says the fuse stops shocks → "A shock needs only a small current. What does the fuse protect instead?"

## Confidence and escalation

- Two failures on kWh: make a two-column table, power in kW and time in h, before multiplying.
- Three failures on the power formulas: detour to R = V ÷ I (phy-o-electrical-quantities), then return.
- A question about a real wiring fault at home: explain the physics and say a qualified electrician must do any repair.

## Worked exchange

> Tutor: A 2.0 kW kettle is used for 15 minutes each day for 30 days. Electricity costs 20 cents per kWh. What does this cost? First, what must the time be in for kilowatt-hours?
> Student: Hours: 15 minutes is 0.25 h.
> Tutor: Good. How much energy does it use each day?
> Student: E = Pt = 2.0 × 0.25 = 0.50 kWh.
> Tutor: Right. And over the 30 days?
> Student: 0.50 × 30 = 15 kWh, so the cost is 15 × 20 = 300 cents.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- Power and time are a matching pair: watts and seconds for joules, kilowatts and hours for kWh.
- Every power, current, energy and cost matches math_evaluate, with conversions from units_convert.
- A chosen fuse rating is above the working current and the smallest such rating offered.
- Safety answers name the fuse in the live wire and the earth wire on a metal case.
- The unit passes units_check_dimensions.
