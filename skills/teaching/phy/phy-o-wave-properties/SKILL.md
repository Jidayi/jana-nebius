---
name: phy-o-wave-properties
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach amplitude, wavelength, frequency, v = fλ and how waves reflect and bend
description: "Waves, amplitude, wavelength, frequency, period, wave speed, transverse and longitudinal, reflection, refraction, diffraction: read one full cycle, use v = fλ in base units, keep the frequency fixed at a boundary. Not for: light and lenses (phy-o-light) or sound and echoes (phy-o-sound)."
subject: physics
levels: [O]
topics: [waves, amplitude, wavelength, frequency, period, wave speed, transverse, longitudinal, reflection, refraction, diffraction]
kcs:
  - kc.phy.o.wave_properties.describing_waves
  - kc.phy.o.wave_properties.wave_equation
  - kc.phy.o.wave_properties.transverse_and_longitudinal
  - kc.phy.o.wave_properties.wave_behaviour
curriculum_refs: [PHY-O-03.01]
prerequisites:
  - kc.phy.o.measurement.si_prefixes
  - kc.phy.o.motion.average_speed
related: [phy-o-light, phy-o-sound, phy-o-em-spectrum, phy-o-oscilloscope]
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
    min: 0.01
    max: 1000000000000000
    context: water waves, sound, radio and light
  - quantity: wavelength
    unit: m
    min: 0.000000001
    max: 10000
    context: from light to long radio waves and ocean swells
  - quantity: speed
    unit: m/s
    min: 0.01
    max: 300000000
    context: ripples in a tank, sound in air and solids, and light
  - quantity: period
    unit: s
    min: 0.000000000000001
    max: 1000
    context: one cycle of light, sound, mains or water waves
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student identifies amplitude, wavelength, frequency and period on a diagram or graph and finds T = 1/f
  - The student uses wave speed = frequency × wavelength to find any one of the three in base units
  - The student tells transverse from longitudinal waves by the direction of vibration and gives examples
  - The student describes reflection, refraction and diffraction and what happens to speed, wavelength and frequency
---

# Properties of waves

## When to use

Use when a question asks for the amplitude, wavelength, frequency or period of a wave, uses wave speed = frequency ×
wavelength, asks whether a wave is transverse or longitudinal, or what happens when waves reflect, change depth or
pass through a gap.

Not for: angles and lenses for light (phy-o-light), or echoes and hearing (phy-o-sound).

## What this skill does not do

- It does not treat interference or standing waves.
- It does not use refractive index; that belongs to phy-o-light.
- It does not read values from an oscilloscope's settings; that belongs to phy-o-oscilloscope.

## Objectives

1. The student identifies amplitude, wavelength, frequency and period on a diagram or graph and finds T = 1/f.
2. The student uses wave speed = frequency × wavelength to find any one of the three in base units.
3. The student tells transverse from longitudinal waves by the direction of vibration and gives examples.
4. The student describes reflection, refraction and diffraction and what happens to speed, wavelength and frequency.

## Prerequisite probe

- "A car travels 100 m in 4 s. What is its speed?" Expected: 25 m/s.
- "Change 2.5 kHz into hertz." Expected: 2500 Hz (checked with units_convert).

If the first fails, detour to average speed (phy-o-motion); if the second fails, to prefixes (phy-o-measurement).

## Teaching sequence

1. Ask the student to mark one complete cycle on the diagram or graph. Done when the cycle runs crest to crest or compression to compression.
2. Ask for the amplitude from the middle line to a crest, and for the wavelength or period as one full cycle. Done when each value is read from one full cycle.
3. Ask for the frequency as cycles each second, or T = 1/f. Done when the value matches math_evaluate.
4. For v = fλ, ask for every value in hertz, metres and metres per second first, then rearrange. Done when the value matches math_evaluate in base units.
5. Ask which way the medium vibrates compared with the way the wave travels. Done when the student classifies the wave with that reason.
6. At a boundary or a gap, ask which of speed, wavelength and frequency change; the frequency is set by the source. Done when the student says the frequency stays the same and names the effect correctly.
7. Ask for the unit and a sense check. Done when the unit passes units_check_dimensions.

## Hint ladder

1. Orient: "Where does one full wave start and end on this picture?"
2. Concept: "Speed is how far one wavelength moves each period: v = fλ."
3. First step: write v = fλ with the student's values in base units and ask which one is unknown.
4. Worked step: show the rearranged form with numbers and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.amplitude_peak_to_trough`: measures the amplitude crest to trough → "Where is the middle line the wave vibrates about?"
- `mc.phy.o.wavelength_crest_to_trough`: takes crest to trough as a wavelength → "After a crest and a trough, where does the pattern start again?"
- `mc.phy.o.period_frequency_confused`: gives 50 as the period of a 50 Hz wave → "If 50 waves pass each second, how long does one take?"
- `mc.phy.o.whole_time_as_period`: takes the whole graph as one period → "How many complete cycles fit across the graph?"
- `mc.phy.o.wave_equation_inverted`: writes λ = f ÷ v → "If the waves move faster at the same frequency, should each one be longer or shorter?"
- `mc.phy.o.wave_speed_divided`: divides frequency by wavelength for speed → "How far does the wave move in one second if 5 waves of 0.4 m pass?"
- `mc.phy.o.wave_prefix_ignored`: uses 2.5 kHz as 2.5 → "How many hertz is one kilohertz?"
- `mc.phy.o.vibration_direction_swapped`: says longitudinal waves vibrate across the direction of travel → "In a slinky pushed back and forth, which way do the coils move?"
- `mc.phy.o.ripples_called_longitudinal`: calls ripples longitudinal → "Does a floating cork bob up and down or move along with the ripple?"
- `mc.phy.o.wave_carries_medium`: says the wave carries the water forward → "Does the cork end up at the shore?"
- `mc.phy.o.frequency_changes_on_refraction`: says the frequency changes in shallow water → "Does the dipper make waves any faster when they reach shallow water?"
- `mc.phy.o.depth_speed_reversed`: says waves speed up in shallow water → "When the wavelength gets shorter at the same frequency, what has the speed done?"
- `mc.phy.o.diffraction_wider_gap_more`: says a wider gap spreads waves more → "Which spreads more after it: a gap as wide as one wavelength, or ten?"
- `mc.phy.o.reflection_angle_from_surface`: measures the angle from the barrier → "Which line do angles of reflection start from?"

## Confidence and escalation

- Two failures on reading a cycle: draw a wave on the board and shade one full cycle together.
- Three failures on v = fλ: detour to rearranging a product, then return.
- A diagram with no scale or labelled axes: ask for the scale before reading any value.

## Worked exchange

> Tutor: Ripples in a tank have a frequency of 5.0 Hz and a wavelength of 0.40 m. They move into shallower water where their speed is 1.5 m/s. What is their wavelength there? First, what is their speed in the deep water?
> Student: v = fλ = 5.0 × 0.40 = 2.0 m/s.
> Tutor: Good. In the shallow water, which of the three stays the same?
> Student: The frequency, because the source still makes 5.0 waves each second.
> Tutor: Right. So what is the new wavelength?
> Student: λ = v ÷ f = 1.5 ÷ 5.0 = 0.30 m.
> Tutor: Correct (checked with the maths tool): the waves slow down and their wavelength gets shorter.

## Verification checklist

- Every wavelength, amplitude and period is read from one full cycle and the middle line.
- Values are in hertz, metres and seconds before v = fλ, with conversions from units_convert.
- Every speed, frequency, wavelength and period matches math_evaluate.
- The frequency stays the same at a boundary and through a gap.
- The unit passes units_check_dimensions.
