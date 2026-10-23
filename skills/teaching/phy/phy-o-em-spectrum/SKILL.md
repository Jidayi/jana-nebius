---
name: phy-o-em-spectrum
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach the electromagnetic spectrum's order, shared properties, uses and hazards
description: "Electromagnetic spectrum, radio to gamma, speed of light, uses and hazards: put the regions in order of wavelength, use v = fλ with 3.0 × 10⁸ m/s, and match each region to a use and a danger. Not for: waves in general (phy-o-wave-properties) or radioactive decay (phy-o-radioactivity)."
subject: physics
levels: [O]
topics: [electromagnetic spectrum, radio waves, microwaves, infrared, ultraviolet, x-rays, gamma rays, speed of light, uses and hazards]
kcs:
  - kc.phy.o.em_spectrum.order_and_properties
  - kc.phy.o.em_spectrum.em_wave_calculations
  - kc.phy.o.em_spectrum.uses_and_hazards
curriculum_refs: [PHY-O-03.03]
prerequisites:
  - kc.phy.o.wave_properties.transverse_and_longitudinal
  - kc.phy.o.wave_properties.wave_equation
related: [phy-o-wave-properties, phy-o-light, phy-o-radioactivity]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, units_convert]
visuals: [library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: frequency
    unit: Hz
    min: 1000
    max: 1000000000000000000000
    context: long radio waves up to gamma rays
  - quantity: wavelength
    unit: m
    min: 0.0000000000001
    max: 100000
    context: gamma rays up to long radio waves
  - quantity: speed
    unit: m/s
    min: 100000000
    max: 300000000
    context: electromagnetic waves in a vacuum, air and transparent materials
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student lists the regions of the electromagnetic spectrum in order of wavelength or frequency
  - The student states the properties all electromagnetic waves share, including their speed in a vacuum
  - The student uses v = fλ with the speed of light to find a frequency or a wavelength in base units
  - The student matches each region to a use and a hazard and says which regions ionise
---

# The electromagnetic spectrum

## When to use

Use when a question asks for the order of the electromagnetic regions, what all electromagnetic waves have in common,
the wavelength or frequency of a radio, microwave or light wave, or what a region is used for and how it can harm.

Not for: general wave behaviour and the wave equation for water or sound (phy-o-wave-properties), or alpha, beta and
gamma from nuclei (phy-o-radioactivity).

## What this skill does not do

- It does not give exact boundaries between regions; it uses their order and typical sizes.
- It does not treat photons or energy per wave.
- It does not choose the speed of light: the pack gives 3.0 × 10⁸ m/s.

## Objectives

1. The student lists the regions of the electromagnetic spectrum in order of wavelength or frequency.
2. The student states the properties all electromagnetic waves share, including their speed in a vacuum.
3. The student uses v = fλ with the speed of light to find a frequency or a wavelength in base units.
4. The student matches each region to a use and a hazard and says which regions ionise.

## Prerequisite probe

- "Waves have a frequency of 4 Hz and a wavelength of 3 m. What is their speed?" Expected: 12 m/s.
- "Change 100 MHz into hertz." Expected: 1.0 × 10⁸ Hz (checked with units_convert).

If the first fails, detour to the wave equation (phy-o-wave-properties); if the second fails, to prefixes.

## Teaching sequence

1. Ask the student to list the regions from longest wavelength to shortest. Done when the order runs radio, microwave, infrared, visible, ultraviolet, X-ray, gamma.
2. Ask which way the frequency changes along that list. Done when the student says the frequency rises as the wavelength falls.
3. Ask what every region shares: transverse, no medium needed, the same speed in a vacuum. Done when all three are given.
4. For a calculation, ask for the frequency in hertz and the wavelength in metres, then v = fλ with 3.0 × 10⁸ m/s. Done when the value matches math_evaluate.
5. Ask whether the answer fits the region: radio waves metres to kilometres, light under a millionth of a metre. Done when the size fits the region named.
6. For uses and hazards, ask what the region does to matter and where it is used. Done when the use and the hazard match the region and ionising regions are named as ultraviolet, X-rays and gamma.

## Hint ladder

1. Orient: "Where does this wave sit in the spectrum, and what speed do all of them share?"
2. Concept: "Every electromagnetic wave travels at 3.0 × 10⁸ m/s in a vacuum, so v = fλ links its frequency and wavelength."
3. First step: write v = fλ with the student's values in base units and ask which one is unknown.
4. Worked step: show the rearranged form with numbers and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.em_order_reversed`: puts gamma rays at the long-wavelength end → "Which region has waves you could measure with a ruler?"
- `mc.phy.o.em_needs_medium`: says light needs air → "How does sunlight reach the Earth across empty space?"
- `mc.phy.o.infrared_ultraviolet_swapped`: puts ultraviolet next to red → "Which side of the visible band is violet light on?"
- `mc.phy.o.em_same_wavelength`: says equal speed means equal wavelength → "Radio and light travel equally fast. Do they have the same frequency?"
- `mc.phy.o.em_uses_sound_speed`: uses 340 m/s for radio → "Is a radio wave a sound wave or an electromagnetic wave?"
- `mc.phy.o.em_speed_differs`: says gamma rays travel faster than radio → "In a vacuum, which electromagnetic wave would win a race?"
- `mc.phy.o.wave_prefix_ignored`: uses 100 MHz as 100 → "How many hertz is one megahertz?"
- `mc.phy.o.xray_gamma_uses_swapped`: says gamma rays image broken bones → "Which one is made in a tube and used for pictures of bones?"
- `mc.phy.o.nonionising_called_ionising`: says microwaves damage DNA like X-rays → "Which regions carry enough energy to knock electrons off atoms?"
- `mc.phy.o.long_wave_uses_mixed`: says a TV remote uses microwaves → "Which region does a remote control's small bulb give out?"
- `mc.phy.o.hazard_increases_with_wavelength`: says radio waves are the most harmful → "As the wavelength gets shorter, does the danger rise or fall?"

## Confidence and escalation

- Two failures on the order: build the list from the two ends the student knows best, radio and gamma, and fill the middle.
- Three failures on v = fλ: detour to the wave equation (phy-o-wave-properties), then return.
- A health question beyond the pack's uses and hazards: give the pack's general hazard and suggest a trusted adult or doctor.

## Worked exchange

> Tutor: A radio station broadcasts at 100 MHz. What is the wavelength of its waves? First, how fast do radio waves travel?
> Student: At the speed of light, 3.0 × 10⁸ m/s, like every electromagnetic wave.
> Tutor: Good. What is 100 MHz in hertz?
> Student: 100 × 10⁶ Hz, which is 1.0 × 10⁸ Hz.
> Tutor: Right. Now the wavelength.
> Student: λ = v ÷ f = (3.0 × 10⁸) ÷ (1.0 × 10⁸) = 3.0 m.
> Tutor: Correct (checked with the maths tool), and a few metres is a sensible size for a radio wave.

## Verification checklist

- The order of regions runs from radio to gamma with the frequency rising.
- Frequencies are in hertz and wavelengths in metres before v = fλ, with conversions from units_convert.
- The speed of every electromagnetic wave in a vacuum is the pack's 3.0 × 10⁸ m/s.
- Every frequency and wavelength matches math_evaluate and fits its region.
- Ionising regions are ultraviolet, X-rays and gamma rays only.
