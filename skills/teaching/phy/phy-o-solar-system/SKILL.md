---
name: phy-o-solar-system
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach day, year, seasons, Moon phases, orbital speed and the planets
description: "Solar System, day and night, seasons, phases of the Moon, orbital speed, planets and gravity: explain each cycle by a spin or an orbit, use v = 2πr ÷ T with the period in seconds, and link a planet's orbit to its distance from the Sun. Not for: stars, light-years and galaxies (phy-o-stars)."
subject: physics
levels: [O]
topics: [solar system, day and night, seasons, phases of the moon, orbital speed, orbits, planets, gravity]
kcs:
  - kc.phy.o.solar_system.earth_and_moon
  - kc.phy.o.solar_system.orbital_speed
  - kc.phy.o.solar_system.planets_and_gravity
curriculum_refs: [PHY-O-06.01]
prerequisites:
  - kc.phy.o.motion.average_speed
related: [phy-o-stars, phy-o-mass-weight, phy-o-forces]
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
  - quantity: speed
    unit: km/s
    min: 0.1
    max: 100
    context: orbital speeds of moons, satellites and planets
  - quantity: radius
    unit: m
    min: 1000000
    max: 10000000000000
    context: orbit radii from low satellites to the outer planets
  - quantity: period
    unit: s
    min: 3600
    max: 10000000000
    context: orbits from about an hour for a low satellite to the outer planets' years
  - quantity: field_strength
    unit: N/kg
    min: 0.1
    max: 30
    context: surface gravitational field strengths of moons and planets
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student explains day and night, the year and the seasons by the Earth's spin, orbit and tilt
  - The student explains the Moon's phases by the part of its sunlit half that faces the Earth
  - The student calculates an average orbital speed from the orbit radius and the period in matching units
  - The student compares the planets and explains how the Sun's gravity keeps them in orbit
---

# Earth, Moon and the Solar System

## When to use

Use when a question asks why we have day and night, years and seasons, why the Moon shows phases, for an orbital
speed, period or radius, how the planets differ, or what keeps planets and moons in their orbits.

Not for: light-years, the life of stars, galaxies and the expanding Universe (phy-o-stars).

## What this skill does not do

- It does not use the law of gravitation or Kepler's laws as formulas.
- It does not treat eclipses beyond the shadows they involve.
- It does not give planetary data from memory: the question or the pack gives it.

## Objectives

1. The student explains day and night, the year and the seasons by the Earth's spin, orbit and tilt.
2. The student explains the Moon's phases by the part of its sunlit half that faces the Earth.
3. The student calculates an average orbital speed from the orbit radius and the period in matching units.
4. The student compares the planets and explains how the Sun's gravity keeps them in orbit.

## Prerequisite probe

- "What is the circumference of a circle of radius 7 m?" Expected: 44.0 m (checked with math_evaluate).
- "How many seconds are in one day?" Expected: 86400 s.

If the first fails, revisit circles; if the second fails, practise time conversions (checked with units_convert).

## Teaching sequence

1. Ask which motion causes the cycle in the question: the Earth's spin, the Earth's orbit, or the Moon's orbit. Done when the student matches the cycle to one motion.
2. For seasons, ask how the tilt changes the Sun's height in the sky and the length of the day in each hemisphere. Done when the student explains with tilt, not distance.
3. For phases, ask which half of the Moon is lit and how much of it faces the Earth. Done when the student explains without the Earth's shadow.
4. For orbital speed, ask for the distance in one orbit as 2πr and the period in seconds. Done when both are in matching units, checked with units_convert.
5. Ask the student to substitute into v = 2πr ÷ T; math_evaluate gives the reference. Done when the value matches the checked one.
6. For orbits, ask which force acts on the planet, which way, and what it does to the motion. Done when gravity towards the Sun is named as the force that keeps changing the planet's direction.

## Hint ladder

1. Orient: "Which body is spinning or orbiting here, and how long does that take?"
2. Concept: "In one orbit a body travels the circumference, 2πr, in one period."
3. First step: write v = 2πr ÷ T with the student's values and ask for the units.
4. Worked step: show the substitution in matching units and ask for the value.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.sun_distance_causes_seasons`: says summer comes when the Earth is nearest the Sun → "If distance caused summer, why are the two hemispheres in opposite seasons?"
- `mc.phy.o.moon_phases_earth_shadow`: says the Earth's shadow makes the phases → "At full moon, where are the Earth, the Moon and the Sun?"
- `mc.phy.o.earth_spin_orbit_confused`: says a day is one orbit of the Sun → "Which takes a day: one spin, or one trip round the Sun?"
- `mc.phy.o.seasons_same_both_hemispheres`: says both hemispheres share a season → "When the north tilts towards the Sun, which way does the south tilt?"
- `mc.phy.o.orbit_speed_no_two_pi`: divides the radius by the period → "Does the planet travel the radius in one orbit, or all the way round?"
- `mc.phy.o.orbit_period_not_in_seconds`: divides by 365 for a speed in km/s → "A speed in km/s needs the time in what?"
- `mc.phy.o.orbit_radius_altitude_only`: uses a satellite's height as its orbit radius → "Is the orbit centred on the ground below or on the Earth's centre?"
- `mc.phy.o.outer_planets_orbit_faster`: says outer planets go round faster → "Does Neptune's year last longer or shorter than ours?"
- `mc.phy.o.orbit_needs_forward_force`: says a forward force keeps a planet moving → "In space, with nothing to slow it, does a moving planet need a push to keep going?"
- `mc.phy.o.no_gravity_in_space`: says there is no gravity in orbit → "If gravity stopped above the air, what would keep the Moon going round?"
- `mc.phy.o.planet_weight_uses_earth_g`: uses 9.8 N/kg on Mars → "Where is the object, and what is g there?"

## Confidence and escalation

- Two failures on a cycle: switch to a diagram of the Sun, the Earth and the Moon with the motion drawn.
- Three failures on v = 2πr ÷ T: detour to average speed (phy-o-motion), then return.
- A question needing planetary data the question does not give: ask for it; never recall values from memory.

## Worked exchange

> Tutor: The Earth orbits the Sun at an average radius of 1.5 × 10⁸ km and takes 365 days for one orbit. What is its average orbital speed in km/s? First, how far does it travel in one orbit?
> Student: The circumference, 2πr = 2 × π × 1.5 × 10⁸ = 9.42 × 10⁸ km.
> Tutor: Good. What must the time be in?
> Student: Seconds: 365 × 24 × 3600 = 3.15 × 10⁷ s.
> Tutor: Right. Now the speed.
> Student: (9.42 × 10⁸) ÷ (3.15 × 10⁷) = 29.9 km/s.
> Tutor: Correct (checked with the maths tool), about 30 km/s.

## Verification checklist

- Each cycle is explained by one spin or orbit, and seasons by the tilt.
- The distance in one orbit is 2πr from the centre of the body orbited.
- The period is in seconds for a speed in km/s or m/s, with conversions from units_convert.
- Every speed, period and radius matches math_evaluate.
- The force keeping a body in orbit is gravity towards the centre.
