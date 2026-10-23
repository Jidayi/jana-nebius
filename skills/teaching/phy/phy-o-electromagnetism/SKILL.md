---
name: phy-o-electromagnetism
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach fields of currents, the motor effect, induction and transformers
description: "Electromagnets, motor effect, electromagnetic induction, generators, transformers, power transmission: hand rules for directions, induction only while the field changes, turns ratio, P in = P out. Not for: bar magnets alone (phy-o-magnetism) or home power and fuses (phy-o-practical-electricity)."
subject: physics
levels: [O]
topics: [electromagnets, solenoids, motor effect, motors, electromagnetic induction, generators, transformers, turns ratio, power transmission]
kcs:
  - kc.phy.o.electromagnetism.fields_of_currents
  - kc.phy.o.electromagnetism.motor_effect
  - kc.phy.o.electromagnetism.electromagnetic_induction
  - kc.phy.o.electromagnetism.transformers
  - kc.phy.o.electromagnetism.power_transmission
curriculum_refs: [PHY-O-04.05]
prerequisites:
  - kc.phy.o.magnetism.magnetic_fields
  - kc.phy.o.electrical_quantities.current_and_charge
  - kc.phy.o.practical_electricity.electrical_power
related: [phy-o-magnetism, phy-o-practical-electricity, phy-o-electrical-quantities]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve]
visuals: [library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: voltage
    unit: V
    min: 0
    max: 1000000
    context: device chargers up to high-voltage transmission lines
  - quantity: current
    unit: A
    min: 0
    max: 10000
    context: currents in coils, appliances and transmission cables
  - quantity: power
    unit: W
    min: 0
    max: 5000000000
    context: chargers and motors up to power stations
  - quantity: turns
    unit: dimensionless
    min: 1
    max: 1000000
    context: turns on transformer and electromagnet coils
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student describes the field of a straight wire and a solenoid and how to make an electromagnet stronger
  - The student predicts the direction of the force on a current in a field and explains a d.c. motor
  - The student explains how a changing field induces an e.m.f. and names the factors that increase it
  - The student uses the turns ratio of a transformer to find an output voltage or a number of turns
  - The student uses input power = output power and explains why power is sent at a high voltage
---

# Electromagnetism

## When to use

Use when a question asks about the field round a wire or a coil, how to make an electromagnet stronger, which way a
wire or a motor coil is pushed, how a generator or a moving magnet makes a current, the output of a transformer, or
why power lines run at high voltage.

Not for: the poles and field of a bar magnet on its own (phy-o-magnetism), or power ratings and fuses at home
(phy-o-practical-electricity).

## What this skill does not do

- It does not calculate the size of a magnetic force or field.
- It does not treat transformer efficiency beyond input and output powers.
- It does not use the formula for induced e.m.f.; it names the factors that change it.

## Objectives

1. The student describes the field of a straight wire and a solenoid and how to make an electromagnet stronger.
2. The student predicts the direction of the force on a current in a field and explains a d.c. motor.
3. The student explains how a changing field induces an e.m.f. and names the factors that increase it.
4. The student uses the turns ratio of a transformer to find an output voltage or a number of turns.
5. The student uses input power = output power and explains why power is sent at a high voltage.

## Prerequisite probe

- "A 230 V supply gives a current of 2 A. What is the power?" Expected: 460 W (checked with math_evaluate).
- "Make Vs the subject of Vs ÷ Vp = Ns ÷ Np." Expected: Vs = Vp × Ns ÷ Np.

If the first fails, detour to power (phy-o-practical-electricity); if the second fails, practise rearranging.

## Teaching sequence

1. Ask what the question is about: a field, a force, an induced e.m.f., a transformer, or transmission. Done when the student names it.
2. For a field, ask for its shape (circles round a wire, bar-magnet pattern for a coil) and its direction by the right-hand grip rule. Done when the shape and the direction are both right.
3. For a force, ask for the field and current directions, then Fleming's left-hand rule. Done when the force is at right angles to both and its direction is right.
4. For induction, ask what is changing in the field through the coil and what would make the change faster. Done when the student says an emf is induced only while the field changes and names a factor.
5. For a transformer, ask whether it steps up or down from the turns, then use Vs ÷ Vp = Ns ÷ Np; math_solve gives the reference. Done when the value matches the checked one and the step direction.
6. For transmission, ask for the current from I = P ÷ V and the cable loss from I²R. Done when the student explains that a higher voltage gives a smaller current and a smaller loss, with checked values.

## Hint ladder

1. Orient: "What is moving or changing here: a current, a magnet, or the field through a coil?"
2. Concept: name the rule, such as "a current across a field feels a force at right angles to both".
3. First step: draw the directions or write the turns ratio with the student's values and ask for the next step.
4. Worked step: show the hand rule set-up or the substitution and ask for the result.
5. Full step: give the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.wire_field_along_wire`: draws the field along the wire → "Where do iron filings gather round a straight wire carrying a current?"
- `mc.phy.o.grip_rule_reversed`: gets the field the wrong way round → "With your right thumb along the current, which way do your fingers curl?"
- `mc.phy.o.electromagnet_factor_ignored`: says more turns makes no difference → "If one turn makes a weak field, what do a hundred turns do?"
- `mc.phy.o.force_along_field`: says the wire is pushed along the field → "In the left-hand rule, how are the thumb and the first finger set?"
- `mc.phy.o.reversing_both_reverses_force`: reverses the force when both are reversed → "If reversing one flips the force, what does reversing the other do next?"
- `mc.phy.o.commutator_role_confused`: says the commutator reverses the field → "What would happen to the coil after half a turn if the current did not change direction?"
- `mc.phy.o.stationary_magnet_induces`: says a still magnet in a coil induces an e.m.f. → "Is the field through the coil changing while the magnet rests there?"
- `mc.phy.o.reverse_motion_same_direction`: says pulling out gives the same current as pushing in → "What does the meter's needle do when the motion reverses?"
- `mc.phy.o.induction_factor_reversed`: says moving the magnet slower gives more e.m.f. → "Does a bicycle dynamo light glow brighter when you pedal faster or slower?"
- `mc.phy.o.transformer_works_on_dc`: says a battery can drive a transformer → "Does a steady current make a changing field in the core?"
- `mc.phy.o.turns_ratio_inverted`: gets about 4400 V from a step-down transformer → "With fewer turns on the secondary, should the voltage go up or down?"
- `mc.phy.o.step_up_down_confused`: calls more secondary turns step-down → "Which coil has more turns, and which voltage is bigger?"
- `mc.phy.o.higher_voltage_more_loss`: says high voltage wastes more → "For the same power, what happens to the current when the voltage rises?"
- `mc.phy.o.power_loss_not_squared`: works out the loss as I × R → "In the cable loss I²R, what happens to the current first?"

## Confidence and escalation

- Two failures on directions: switch to a labelled 3D diagram with the field, the current and the force drawn as arrows.
- Three failures on the turns ratio: detour to rearranging a proportion, then return.
- A device the pack does not describe: explain the physics it shares with a motor, generator or transformer.

## Worked exchange

> Tutor: A transformer has 1150 turns on its primary coil and 60 turns on its secondary. The primary is connected to a 230 V a.c. supply. What is the output voltage? First, is it a step-up or a step-down transformer?
> Student: Step-down, because the secondary has fewer turns.
> Tutor: Good. Which relation links the voltages to the turns?
> Student: Vs ÷ Vp = Ns ÷ Np, so Vs = 230 × 60 ÷ 1150 = 12 V.
> Tutor: Correct (checked with the maths tool). Would it work from a 230 V battery?
> Student: No, it needs a changing current to make a changing field in the core.
> Tutor: Right.

## Verification checklist

- Field and force directions come from the grip rule and the left-hand rule, stated with the rule used.
- An e.m.f. is induced only while the field through the coil changes.
- Turns ratios and output voltages match math_solve or math_evaluate, with the step direction stated.
- Transmission answers use I = P ÷ V and a loss of I²R, with values matching math_evaluate.
- Voltages, currents and powers are in volts, amperes and watts.
