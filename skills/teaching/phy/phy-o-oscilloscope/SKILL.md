---
name: phy-o-oscilloscope
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach reading period, frequency and peak voltage from an oscilloscope trace
description: "Oscilloscope traces, time-base, Y-gain: count divisions for one full wave, times the time-base, in seconds for f = 1/T; height above the centre line times the Y-gain for the peak voltage. Not for: waves in general (phy-o-wave-properties) or sound (phy-o-sound)."
subject: physics
levels: [O]
topics: [oscilloscope, time-base, y-gain, period, frequency, peak voltage, trace]
kcs:
  - kc.phy.o.oscilloscope.time_base
  - kc.phy.o.oscilloscope.y_gain
curriculum_refs: [PHY-O-04.06]
prerequisites:
  - kc.phy.o.wave_properties.describing_waves
  - kc.phy.o.electrical_quantities.potential_difference
related: [phy-o-wave-properties, phy-o-sound, phy-o-electrical-quantities]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_convert, units_check_dimensions]
visuals: [wave_diagram, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: frequency
    unit: Hz
    min: 0.1
    max: 1000000
    context: signals from slow a.c. supplies to sound and ultrasound
  - quantity: period
    unit: s
    min: 0.000001
    max: 10
    context: one cycle of a signal shown on a school oscilloscope
  - quantity: voltage
    unit: V
    min: 0
    max: 1000
    context: peak voltages of signals from microphones, signal generators and supplies
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds the period from the divisions for one complete wave and the time-base setting
  - The student calculates the frequency as one over the period in seconds
  - The student finds the peak voltage from the height above the centre line and the Y-gain setting
  - The student says which control changes the spacing of the waves and which changes their height
---

# Reading an oscilloscope

## When to use

Use when a question shows an oscilloscope trace, or describes one, with a time-base or a Y-gain setting and asks for
the period, the frequency, the peak voltage or the peak-to-peak voltage, or what changing a control does to the trace.

Not for: wave properties without an oscilloscope (phy-o-wave-properties), or how sound travels (phy-o-sound).

## What this skill does not do

- It does not treat root-mean-square values.
- It does not read traces with no settings given.
- It does not treat two traces on one screen or phase differences.

## Objectives

1. The student finds the period from the divisions for one complete wave and the time-base setting.
2. The student calculates the frequency as one over the period in seconds.
3. The student finds the peak voltage from the height above the centre line and the Y-gain setting.
4. The student says which control changes the spacing of the waves and which changes their height.

## Prerequisite probe

- "Change 5 ms into seconds." Expected: 0.005 s (checked with units_convert).
- "What is the frequency of a wave with a period of 0.004 s?" Expected: 250 Hz.

If the first fails, practise prefixes (phy-o-measurement); if the second fails, detour to periods (phy-o-wave-properties).

## Teaching sequence

1. Ask the student to mark one complete wave, crest to the next crest. Done when the marked length is one full cycle.
2. Ask for its length in divisions; if several waves are marked, divide by how many. Done when the divisions for one wave are stated.
3. Ask for the period as divisions × time-base, then in seconds. Done when the period matches units_convert in seconds.
4. Ask for the frequency as 1 ÷ period. Done when the value matches math_evaluate in hertz.
5. Ask for the height of a crest above the centre line in divisions, then × Y-gain for the peak voltage. Done when the value matches math_evaluate in volts.
6. Ask what a change of time-base or Y-gain would do to the trace. Done when the time-base is linked to spacing and the Y-gain to height.

## Hint ladder

1. Orient: "Where does one complete wave start and end on the screen?"
2. Concept: "Time-base turns divisions across into time; Y-gain turns divisions up into volts."
3. First step: count the divisions and ask for the multiplication by the setting.
4. Worked step: show divisions × setting and ask for the value in base units.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.osc_divisions_as_time`: gives 4 divisions as the period → "Each division is worth how much time?"
- `mc.phy.o.osc_waves_not_divided`: gives the time for three waves as the period → "How many complete waves did you measure across?"
- `mc.phy.o.osc_ms_read_as_s`: works out 1 ÷ 20 for a 20 ms period → "Is 20 ms twenty seconds?"
- `mc.phy.o.osc_half_wave_as_period`: measures crest to trough → "After a crest and a trough, has the wave finished one full cycle?"
- `mc.phy.o.osc_frequency_period_confused`: gives the period when asked for frequency → "Which one is measured in hertz?"
- `mc.phy.o.osc_divisions_as_volts`: gives 3 divisions as the voltage → "Each division up is worth how many volts?"
- `mc.phy.o.osc_peak_and_peak_to_peak_confused`: measures crest to trough for the peak → "Where is the zero line, in the middle or at the trough?"
- `mc.phy.o.osc_ygain_mv_as_v`: reads 50 mV per division as 50 V → "Is the Y-gain in volts or millivolts per division?"
- `mc.phy.o.osc_ygain_timebase_confused`: uses the Y-gain to spread the waves out → "Which control works across the screen, and which up and down?"

## Confidence and escalation

- Two failures on the period: draw a single wave on a grid and count divisions together.
- Three failures on f = 1/T: detour to periods and frequency (phy-o-wave-properties), then return.
- A trace whose settings are missing or unreadable: ask for the settings; never guess them.

## Worked exchange

> Tutor: On an oscilloscope, one complete wave spans 4 divisions across, with the time-base at 5 ms per division. The crests are 3 divisions above the centre line, with the Y-gain at 2 V per division. Find the frequency and the peak voltage. First, what is the period?
> Student: 4 × 5 = 20 ms.
> Tutor: Good. What is that in seconds, and so the frequency?
> Student: 20 ms is 0.020 s, so f = 1 ÷ 0.020 = 50 Hz.
> Tutor: Right. Now the peak voltage.
> Student: 3 × 2 = 6 V.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- The period covers one complete wave, crest to crest.
- The period is in seconds before f = 1/T, with conversions from units_convert.
- The peak voltage is measured from the centre line, not from crest to trough, unless peak-to-peak is asked for.
- Every period, frequency and voltage matches math_evaluate.
- The unit passes units_check_dimensions.
