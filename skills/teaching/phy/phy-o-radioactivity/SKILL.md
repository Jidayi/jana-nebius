---
name: phy-o-radioactivity
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach alpha, beta and gamma, decay equations, half-life, background and uses
description: "Radioactivity, alpha, beta and gamma, decay equations, half-life, background radiation, uses and safety: balance the numbers, take off the background, halve once per half-life. Not for: nuclide notation alone (phy-o-atom) or X-rays and the spectrum (phy-o-em-spectrum)."
subject: physics
levels: [O]
topics: [radioactivity, alpha, beta, gamma, decay equations, half-life, background radiation, count rate, tracers, radiation safety]
kcs:
  - kc.phy.o.radioactivity.types_of_radiation
  - kc.phy.o.radioactivity.decay_equations
  - kc.phy.o.radioactivity.half_life
  - kc.phy.o.radioactivity.background_radiation
  - kc.phy.o.radioactivity.uses_and_safety
curriculum_refs: [PHY-O-05.02]
prerequisites:
  - kc.phy.o.atom.atomic_structure
  - kc.phy.o.atom.isotopes
related: [phy-o-atom, phy-o-em-spectrum]
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
  action: prerequisite_detour
plausibility:
  - quantity: count_rate
    unit: count/min
    min: 0
    max: 1000000
    context: counts from a school detector, from background to a strong source close by
  - quantity: activity
    unit: Bq
    min: 0
    max: 1000000000000
    context: school sources up to medical and industrial sources
  - quantity: half_life
    unit: s
    min: 0.000001
    max: 200000000000000000
    context: half-lives from fractions of a second to billions of years
  - quantity: time
    unit: s
    min: 0
    max: 200000000000000000
    context: decay times from seconds to the age of the Earth
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student compares alpha, beta and gamma by nature, penetration, ionising effect and deflection
  - The student finds the new proton and nucleon numbers after alpha or beta decay
  - The student uses half-life to find the activity left, the fraction remaining or the time taken
  - The student corrects a count rate for background radiation and names its main sources
  - The student selects a source for a use from its radiation and half-life and describes safe handling
---

# Radioactivity

## When to use

Use when a question asks what alpha, beta and gamma radiation are and what stops them, for the nucleus left after a
decay, how much of a source remains after some time, for a count rate corrected for background, or which source suits
a smoke alarm, a thickness gauge or a medical tracer, and how to handle sources safely.

Not for: reading nuclide symbols and isotopes alone (phy-o-atom), or X-rays and the rest of the spectrum
(phy-o-em-spectrum).

## What this skill does not do

- It does not treat fission or fusion beyond naming them.
- It does not use exponential formulas; half-lives come in whole numbers or from a graph.
- It does not give dose limits or medical advice.

## Objectives

1. The student compares alpha, beta and gamma by nature, penetration, ionising effect and deflection.
2. The student finds the new proton and nucleon numbers after alpha or beta decay.
3. The student uses half-life to find the activity left, the fraction remaining or the time taken.
4. The student corrects a count rate for background radiation and names its main sources.
5. The student selects a source for a use from its radiation and half-life and describes safe handling.

## Prerequisite probe

- "What is 80 halved three times?" Expected: 10 (checked with math_evaluate).
- "A nucleus has nucleon number 4 and proton number 2. How many neutrons does it have?" Expected: 2.

If the first fails, practise repeated halving; if the second fails, detour to nuclide notation (phy-o-atom).

## Teaching sequence

1. For a radiation, ask what it is, what stops it, how strongly it ionises and which way a field deflects it. Done when all four are given for the radiation asked about.
2. For a decay, ask for the particle's own numbers (alpha 4 and 2, beta 0 and −1), then balance the top and bottom totals. Done when both totals match on each side, checked with math_evaluate.
3. For a count rate, ask for the background and take it off before any halving. Done when the corrected rate matches the checked value.
4. For half-life, ask the student to halve once per half-life in a table of time and amount. Done when the number of halvings and the result match math_evaluate.
5. For a time, ask how many halvings reach the target, then multiply by the half-life; math_solve gives the reference for a non-whole number. Done when the time matches the checked value.
6. For a use, ask which radiation reaches where it must and which half-life lasts long enough without lingering. Done when the choice gives both reasons.
7. For safety, ask how distance, time, shielding and handling tools reduce the dose. Done when the student names at least two with reasons.

## Hint ladder

1. Orient: "Is the question about the radiation, the nucleus, the amount left, or a use?"
2. Concept: name the rule, such as "each half-life halves what is left, so three half-lives leave an eighth".
3. First step: write the first row of the halving table or the decay equation and ask for the next.
4. Worked step: fill in all but the last row or number and ask for it.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.penetration_order_wrong`: says alpha passes through paper → "Which radiation is a big, slow, doubly charged particle?"
- `mc.phy.o.alpha_deflected_more`: says alpha bends more than beta → "Alpha is thousands of times heavier than beta. Which is easier to turn?"
- `mc.phy.o.ionising_follows_penetration`: says gamma ionises most → "If gamma ionised strongly, would it lose its energy quickly or travel far?"
- `mc.phy.o.beta_lowers_proton_number`: lowers the proton number in beta decay → "A neutron turns into a proton. Does the proton number go up or down?"
- `mc.phy.o.alpha_numbers_swapped`: takes 4 off the proton number → "An alpha particle has 2 protons and 2 neutrons. Which number counts all 4?"
- `mc.phy.o.gamma_changes_numbers`: changes the numbers for gamma → "Does a gamma ray carry any protons or neutrons away?"
- `mc.phy.o.half_life_linear`: divides by 6 after three half-lives → "Halve 80, then halve again, then again. What is left?"
- `mc.phy.o.half_lives_equal_ratio`: takes a fall from 640 to 80 as eight half-lives → "How many times did you halve, not divide?"
- `mc.phy.o.background_halved_too`: halves the background with the source → "Does the background come from the source in front of you?"
- `mc.phy.o.background_ignored`: halves the counter's reading without correcting it → "Would the counter read zero with the source taken away?"
- `mc.phy.o.background_zero_without_source`: says the counter reads zero with no source → "What do rocks, the air and space send us all the time?"
- `mc.phy.o.tracer_alpha_emitter`: picks an alpha emitter as a medical tracer → "Can alpha particles get out of the body to reach the detector?"
- `mc.phy.o.short_half_life_for_long_use`: picks a half-life of hours for a smoke alarm → "The alarm must work for years. What would be left after a week?"
- `mc.phy.o.irradiated_becomes_radioactive`: says gamma-sterilised food is radioactive → "Did any radioactive material get into the food?"

## Confidence and escalation

- Two failures on halving: build a table of time against amount with one row per half-life.
- Three failures on decay equations: detour to nuclide notation (phy-o-atom), then return.
- A question about a real exposure or a health worry: give the physics and suggest a trusted adult or doctor.

## Worked exchange

> Tutor: A counter near a source reads 660 counts per minute, and the background is 20 counts per minute. The source has a half-life of 6 hours. After how long will the source's own count rate be 80 counts per minute? First, what is its own count rate now?
> Student: 660 − 20 = 640 counts per minute.
> Tutor: Good. How many halvings take 640 down to 80?
> Student: 640 to 320, to 160, to 80, so three halvings.
> Tutor: Right. So how long is that?
> Student: 3 × 6 = 18 hours.
> Tutor: Correct (checked with the maths tool). What would the counter read then?
> Student: 80 + 20 = 100 counts per minute, because the background is still there.
> Tutor: Right.

## Verification checklist

- The background is taken off before halving and added back for a counter reading.
- The number of half-lives counts halvings, and every amount and time matches math_evaluate or math_solve.
- Decay equations balance the top numbers and the bottom numbers.
- A source choice gives both its radiation and its half-life as reasons.
- Safety answers name distance, time, shielding or handling tools.
