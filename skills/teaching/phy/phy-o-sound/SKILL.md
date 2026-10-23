---
name: phy-o-sound
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach sound as a longitudinal wave, echoes, pitch, loudness and ultrasound
description: "Sound waves, echoes, speed of sound, pitch, loudness, hearing range, ultrasound: describe compressions in a medium, halve the there-and-back time of an echo, link pitch to frequency and loudness to amplitude. Not for: waves in general (phy-o-wave-properties) or light (phy-o-light)."
subject: physics
levels: [O]
topics: [sound waves, echoes, speed of sound, compressions, pitch, loudness, hearing range, ultrasound]
kcs:
  - kc.phy.o.sound.sound_waves
  - kc.phy.o.sound.speed_and_echoes
  - kc.phy.o.sound.pitch_and_loudness
  - kc.phy.o.sound.ultrasound
curriculum_refs: [PHY-O-03.04]
prerequisites:
  - kc.phy.o.wave_properties.transverse_and_longitudinal
  - kc.phy.o.wave_properties.describing_waves
  - kc.phy.o.motion.average_speed
related: [phy-o-wave-properties, phy-o-oscilloscope, phy-o-motion]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, math_solve, units_convert, units_check_dimensions]
visuals: [wave_diagram, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: speed
    unit: m/s
    min: 100
    max: 6000
    context: sound in gases, liquids, body tissue and solids
  - quantity: frequency
    unit: Hz
    min: 1
    max: 10000000
    context: infrasound, audible sound and ultrasound used in scanning and sonar
  - quantity: distance
    unit: m
    min: 0.001
    max: 10000
    context: from tissue depths in a scan to cliffs, buildings and the sea bed
  - quantity: time
    unit: s
    min: 0.000001
    max: 60
    context: echo times in a body scan up to echoes from far cliffs
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student describes sound as a longitudinal wave of compressions and rarefactions that needs a medium
  - The student calculates a speed or a distance from an echo by halving the there-and-back distance
  - The student links pitch to frequency and loudness to amplitude and recalls the human hearing range
  - The student explains uses of ultrasound and finds depths from ultrasound echoes with the right speed
---

# Sound

## When to use

Use when a question asks how sound travels, why it cannot cross a vacuum, how fast it moves in a material, how far
away a cliff or the sea bed is from an echo, what makes a sound higher or louder, what we can hear, or how ultrasound
is used in scans, sonar and cleaning.

Not for: waves in general and v = fλ without sound (phy-o-wave-properties), or light (phy-o-light).

## What this skill does not do

- It does not treat the Doppler effect or resonance.
- It does not measure loudness in decibels.
- It does not choose the speed of sound: the question gives it for each material.

## Objectives

1. The student describes sound as a longitudinal wave of compressions and rarefactions that needs a medium.
2. The student calculates a speed or a distance from an echo by halving the there-and-back distance.
3. The student links pitch to frequency and loudness to amplitude and recalls the human hearing range.
4. The student explains uses of ultrasound and finds depths from ultrasound echoes with the right speed.

## Prerequisite probe

- "A car travels 680 m in 2 s. What is its speed?" Expected: 340 m/s.
- "What is the period of a wave with a frequency of 50 Hz?" Expected: 0.02 s (checked with math_evaluate).

If the first fails, detour to average speed (phy-o-motion); if the second fails, to periods (phy-o-wave-properties).

## Teaching sequence

1. Ask how the particles of the medium move as the sound passes. Done when the student says they vibrate back and forth along the direction of travel.
2. Ask where the compressions and rarefactions are and what a vacuum would do. Done when the student says sound needs particles to pass on.
3. For an echo, ask whether the sound travels one way or there and back. Done when the student states the path with its factor of two or none.
4. Ask for distance = speed × time with the right speed for the material, then halve for an echo; math_evaluate gives the reference. Done when the value matches the checked one.
5. For pitch and loudness, ask which feature of the wave changes. Done when pitch is linked to frequency and loudness to amplitude.
6. For ultrasound, ask what makes it ultrasound and what reflects it in a scan or sonar. Done when the student says a frequency above 20 kHz reflected at boundaries between materials.
7. Ask for the unit and a sense check. Done when the unit passes units_check_dimensions and the size fits the situation.

## Hint ladder

1. Orient: "Where does the sound start, where does it go, and does it come back?"
2. Concept: "An echo's time covers the trip there and back, so the distance to the reflector is half the total."
3. First step: write distance = speed × time with the student's values and ask whether to halve.
4. Worked step: show the total distance and ask for the distance to the reflector.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.sound_called_transverse`: draws sound with particles moving across its path → "When a loudspeaker cone pushes the air, which way do the air particles move?"
- `mc.phy.o.sound_travels_in_vacuum`: says sound crosses space → "What is there in space to carry the vibrations?"
- `mc.phy.o.sound_speed_media_order`: says sound is fastest in air → "In which state are the particles closest and most tightly linked?"
- `mc.phy.o.rarefaction_is_empty`: says a rarefaction has no particles → "Are the particles gone, or just spread out?"
- `mc.phy.o.echo_not_halved`: gives the there-and-back distance → "How far did the sound go before it bounced?"
- `mc.phy.o.direct_sound_factor_two`: halves for thunder → "Does the sound of thunder bounce back to its start?"
- `mc.phy.o.speed_as_distance_times_time`: multiplies distance by time for speed → "Speed is metres each second. Which goes on top?"
- `mc.phy.o.pitch_from_amplitude`: says a bigger amplitude raises the pitch → "If you strum a guitar string harder, does the note get higher or louder?"
- `mc.phy.o.loudness_from_frequency`: says higher frequency is louder → "Can a high note be played quietly?"
- `mc.phy.o.hearing_limit_wrong`: gives the top of hearing as 2 kHz → "Can people hear a 10 kHz whistle?"
- `mc.phy.o.ultrasound_air_speed_used`: uses 340 m/s inside the body → "Is the scanner's sound travelling through air or through tissue?"
- `mc.phy.o.ultrasound_means_loud`: says ultrasound means very loud → "Is ultrasound beyond our hearing because it is loud, or because of its frequency?"
- `mc.phy.o.ultrasound_shadow_image`: says the scan is a shadow picture → "Does the scanner detect sound that passes through, or sound that comes back?"

## Confidence and escalation

- Two failures on the echo factor: draw the path out and back as two arrows and label each with the distance.
- Three failures on distance = speed × time: detour to average speed (phy-o-motion), then return.
- A question with no speed for the material: ask for it; never assume the speed in air for water or tissue.

## Worked exchange

> Tutor: You clap in front of a cliff and hear the echo 1.2 s later. Sound travels at 340 m/s in air. How far away is the cliff? First, how far does the sound travel in 1.2 s?
> Student: 340 × 1.2 = 408 m.
> Tutor: Good. Is that the distance to the cliff?
> Student: No, the sound went there and back, so the cliff is 408 ÷ 2 = 204 m away.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- Every echo distance is half the there-and-back distance; direct sounds are not halved.
- The speed used is the one for the material the sound travels through.
- Every speed, distance and time matches math_evaluate, with conversions from units_convert.
- Pitch is linked to frequency and loudness to amplitude, with the hearing range 20 Hz to 20 kHz.
- The unit passes units_check_dimensions.
