---
name: phy-o-stars
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach light-years, the life cycle of stars and the expanding Universe
description: "Stars, light-years, life cycle of a star, redshift, Hubble constant, Big Bang: light-years to metres with the seconds in a year, order a star's stages by its mass, and use v = H₀d. Not for: the Solar System and orbits (phy-o-solar-system)."
subject: physics
levels: [O]
topics: [stars, light-years, life cycle of a star, nebula, red giant, supernova, white dwarf, black hole, redshift, hubble constant, big bang, galaxies]
kcs:
  - kc.phy.o.stars.light_years
  - kc.phy.o.stars.life_cycle_of_stars
  - kc.phy.o.stars.expanding_universe
curriculum_refs: [PHY-O-06.02]
prerequisites:
  - kc.phy.o.measurement.si_prefixes
  - kc.phy.o.solar_system.planets_and_gravity
related: [phy-o-solar-system, phy-o-em-spectrum]
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
  - quantity: distance
    unit: m
    min: 100000000
    max: 1000000000000000000000000000
    context: from the Moon to the most distant galaxies
  - quantity: speed
    unit: km/s
    min: 0
    max: 300000
    context: recession speeds of galaxies, always below the speed of light
  - quantity: time
    unit: s
    min: 1
    max: 1000000000000000000
    context: light travel times from the Moon up to the age of the Universe
  - quantity: hubble_constant
    unit: 1/s
    min: 0.000000000000000001
    max: 0.00000000000000001
    context: the Hubble constant expressed per second
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student converts distances between light-years and metres with the speed of light and the seconds in a year
  - The student describes the life cycle of a star from a nebula and how its end depends on its mass
  - The student explains redshift as a shift to longer wavelengths from galaxies moving away
  - The student uses recession speed = Hubble constant × distance and links it to the Big Bang
---

# Stars and the Universe

## When to use

Use when a question asks for a distance in light-years or metres, how long light takes to reach us from a star, the
stages in the life of a star, why heavy elements exist, what redshift shows, or how fast a galaxy recedes at a given
distance.

Not for: the Earth, the Moon, the planets and orbital speeds (phy-o-solar-system).

## What this skill does not do

- It does not treat the Hertzsprung-Russell diagram.
- It does not calculate redshift from wavelengths beyond the direction of the shift.
- It does not choose the Hubble constant: the question or the pack gives it.

## Objectives

1. The student converts distances between light-years and metres with the speed of light and the seconds in a year.
2. The student describes the life cycle of a star from a nebula and how its end depends on its mass.
3. The student explains redshift as a shift to longer wavelengths from galaxies moving away.
4. The student uses recession speed = Hubble constant × distance and links it to the Big Bang.

## Prerequisite probe

- "How many seconds are in a year of 365 days?" Expected: 3.1536 × 10⁷ s (checked with math_evaluate).
- "Change 4000 m into kilometres." Expected: 4 km.

If the first fails, practise time conversions (checked with units_convert); if the second, practise prefixes.

## Teaching sequence

1. Ask what a light-year measures. Done when the student says the distance light travels in one year.
2. For a conversion, ask for the seconds in a year, then distance = speed of light × time. Done when the value matches math_evaluate in metres.
3. For a light travel time, ask for the distance in metres and divide by the speed of light. Done when the time matches the checked value in the unit asked for.
4. For a star's life, ask the student to put the stages in order and say where the star's mass makes the path split. Done when the order is right and the split is placed after the red giant or supergiant.
5. For redshift, ask which way the wavelengths shift and what that says about the galaxy's motion. Done when the student says longer wavelengths and moving away.
6. For the Hubble relation, ask for the distance in the units that match the constant, then v = H₀d. Done when the speed matches math_evaluate and is below the speed of light.
7. Ask what galaxies moving apart suggest about the past. Done when the student links it to the Universe expanding from a hot, dense start.

## Hint ladder

1. Orient: "Is the question about a distance, the life of a star, or galaxies moving apart?"
2. Concept: "A light-year is the distance light travels in a year: speed of light × seconds in a year."
3. First step: write the relation with the student's values and ask for the units.
4. Worked step: show the substitution in standard form and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.light_year_is_time`: says a light-year is a time → "If a star is 4 light-years away, is that how long ago or how far?"
- `mc.phy.o.year_seconds_factor_missed`: works out a year as 365 × 24 × 60 → "That gives minutes. How many seconds are in each minute?"
- `mc.phy.o.light_year_conversion_inverted`: multiplies metres by a light-year to get light-years → "Should the number in light-years be much bigger or much smaller than in metres?"
- `mc.phy.o.distant_light_seen_now`: says we see a star as it is today → "If its light took 400 years to arrive, when did it leave the star?"
- `mc.phy.o.stars_shine_by_burning`: says stars burn like a fire → "Is there oxygen in space for burning, and what joins in a star's core?"
- `mc.phy.o.every_star_ends_white_dwarf`: says every star ends as a white dwarf → "What happens to a star many times the Sun's mass after its red supergiant stage?"
- `mc.phy.o.massive_stars_live_longer`: says bigger stars live longer → "A big star burns its fuel much faster. Does it last longer or shorter?"
- `mc.phy.o.life_cycle_order_muddled`: puts the red giant before the main sequence → "Which stage does the Sun spend most of its life in, and is it there now?"
- `mc.phy.o.redshift_means_galaxy_red`: says redshift means the galaxy looks red → "Shifted towards red means the wavelengths got longer or shorter?"
- `mc.phy.o.nearer_galaxies_recede_faster`: says nearer galaxies recede faster → "In v = H₀d, what happens to v when d is bigger?"
- `mc.phy.o.big_bang_centre_in_space`: says the Big Bang happened at one point in space → "If space itself stretches, which galaxy is at the centre?"
- `mc.phy.o.hubble_relation_inverted`: divides the distance by the Hubble constant for the speed → "Speed is the constant times the distance. Which operation is that?"

## Confidence and escalation

- Two failures on standard form: practise multiplying numbers in standard form before converting.
- Three failures on the light-year: detour to distance = speed × time (phy-o-motion), then return.
- A question about current research beyond the pack: give the pack's model and say scientists still study it.

## Worked exchange

> Tutor: Light travels at 3.0 × 10⁸ m/s. How many metres are in one light-year? First, how many seconds are in a year of 365 days?
> Student: 365 × 24 × 3600 = 3.1536 × 10⁷ s.
> Tutor: Good. So how far does light go in that time?
> Student: 3.0 × 10⁸ × 3.1536 × 10⁷ = 9.46 × 10¹⁵ m.
> Tutor: Correct (checked with the maths tool). A star is 4.2 light-years away. How far is that in metres?
> Student: 4.2 × 9.46 × 10¹⁵ = 3.97 × 10¹⁶ m.
> Tutor: Correct (checked with the maths tool).

## Verification checklist

- A light-year is a distance, built from the speed of light and the seconds in a year.
- Every distance, time and speed matches math_evaluate, with conversions from units_convert.
- A star's stages are in order, and its end depends on its mass.
- Redshift is a shift to longer wavelengths from galaxies moving away.
- Recession speeds use matching units for the Hubble constant and the distance, and stay below the speed of light.
