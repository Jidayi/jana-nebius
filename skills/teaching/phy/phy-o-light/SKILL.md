---
name: phy-o-light
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach reflection, refraction, critical angle and images in a converging lens
description: "Reflection, refraction, refractive index, critical angle, total internal reflection, converging lens: measure angles from the normal, use n = sin i ÷ sin r and sin C = 1/n, then place the image with rays or 1/u + 1/v = 1/f. Not for: wave speed and diffraction (phy-o-wave-properties)."
subject: physics
levels: [O]
topics: [reflection, plane mirror, refraction, refractive index, critical angle, total internal reflection, converging lens, ray diagram]
kcs:
  - kc.phy.o.light.plane_mirrors
  - kc.phy.o.light.refraction
  - kc.phy.o.light.speed_in_medium
  - kc.phy.o.light.total_internal_reflection
  - kc.phy.o.light.converging_lens
curriculum_refs: [PHY-O-03.02]
prerequisites:
  - kc.phy.o.wave_properties.wave_behaviour
related: [phy-o-wave-properties, phy-o-em-spectrum]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, phys_optics, units_check_dimensions]
visuals: [ray_diagram, knowns_panel]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: refractive_index
    unit: dimensionless
    min: 1
    max: 3
    context: water, glass, plastics and diamond
  - quantity: angle
    unit: degree
    min: 0
    max: 90
    context: angles of incidence, reflection, refraction and critical angles from the normal
  - quantity: speed
    unit: m/s
    min: 100000000
    max: 300000000
    context: the speed of light in a vacuum, air and transparent materials
  - quantity: focal_length
    unit: m
    min: 0.001
    max: 10
    context: lenses in cameras, magnifying glasses, projectors and the eye
  - quantity: image_distance
    unit: m
    min: 0.001
    max: 100
    context: distances of images from a lens or a mirror in a lab
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student applies the law of reflection with angles from the normal and describes a plane-mirror image
  - The student calculates a refractive index or an angle with n = sin i ÷ sin r
  - The student relates the refractive index to the speed of light in the material
  - The student finds the critical angle from sin C = 1/n and predicts total internal reflection
  - The student finds the position, size and nature of the image formed by a converging lens
---

# Light: reflection, refraction and lenses

## When to use

Use when a question asks for an angle of reflection or refraction, a refractive index, the speed of light in glass or
water, a critical angle, whether total internal reflection happens, or where a converging lens forms an image and what
it is like.

Not for: wave speed, frequency and diffraction in general (phy-o-wave-properties).

## What this skill does not do

- It does not treat diverging lenses or curved mirrors.
- It does not treat dispersion beyond naming it.
- It does not choose the sign convention: the pack gives real-is-positive.

## Objectives

1. The student applies the law of reflection with angles from the normal and describes a plane-mirror image.
2. The student calculates a refractive index or an angle with n = sin i ÷ sin r.
3. The student relates the refractive index to the speed of light in the material.
4. The student finds the critical angle from sin C = 1/n and predicts total internal reflection.
5. The student finds the position, size and nature of the image formed by a converging lens.

## Prerequisite probe

- "A ray meets a mirror at 40° to its surface. What is its angle to the normal?" Expected: 50°.
- "What is sin 30°?" Expected: 0.5 (checked with math_evaluate in degrees).

If the first fails, draw the normal together; if the second fails, revisit sines of angles, then return.

## Teaching sequence

1. Ask the student to draw the normal where the ray meets the surface. Done when every angle is marked from the normal.
2. For a mirror, ask for the angle of reflection and where the image is. Done when the angles are equal and the image is as far behind the mirror as the object is in front.
3. For refraction, ask which way the ray bends going into the denser material, then write n = sin i ÷ sin r. Done when the student predicts the bending and the equation is on the board.
4. Ask the student to solve, taking the inverse sine at the end for an angle; phys_optics gives the reference. Done when the value matches the checked one.
5. For speed, ask for n = speed in vacuum ÷ speed in the material. Done when the speed is below the speed in a vacuum and matches math_evaluate.
6. For total internal reflection, ask for sin C = 1/n and whether the ray goes from dense to less dense with an angle above C. Done when the critical angle matches phys_optics and the prediction gives both conditions.
7. For a lens, ask for a ray diagram or 1/u + 1/v = 1/f, then the image's distance, size and nature. Done when all three match phys_optics.

## Hint ladder

1. Orient: "Where is the normal, and which material is the ray in first?"
2. Concept: name the rule, such as "light slows and bends towards the normal entering a denser material".
3. First step: write the relation with the student's angles or distances and ask for the next line.
4. Worked step: show the substitution and ask for the value, or for the inverse sine.
5. Full step: show the checked result; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.mirror_angle_from_surface`: measures angles from the mirror → "Which line do we draw at right angles to the mirror?"
- `mc.phy.o.mirror_image_real`: says a screen behind the mirror shows the image → "Does any light go behind the mirror?"
- `mc.phy.o.refraction_bends_wrong_way`: bends the ray away from the normal into glass → "Light slows down in glass. Does it bend towards the normal or away?"
- `mc.phy.o.snell_inverse_sine_missed`: gives 0.43 as the angle → "Is that number the angle, or its sine?"
- `mc.phy.o.snell_ratio_inverted`: gets a refractive index below 1 → "Can light go faster in glass than in air?"
- `mc.phy.o.light_speed_times_index`: multiplies 3.0 × 10⁸ by n → "Is light faster or slower inside the glass?"
- `mc.phy.o.light_speed_same_in_material`: uses 3.0 × 10⁸ m/s inside water → "If the speed did not change, would the ray bend at all?"
- `mc.phy.o.tir_angle_below_critical`: expects total internal reflection below the critical angle → "Above or below the critical angle, which way does all the light go back?"
- `mc.phy.o.tir_from_air_into_glass`: expects total internal reflection going into glass → "In which direction does the ray bend away from the normal?"
- `mc.phy.o.critical_sine_not_inverted`: uses sin C = n → "Can a sine be bigger than 1?"
- `mc.phy.o.lens_centre_ray_bends`: bends the ray through the centre → "At the middle of a thin lens, are the two faces parallel?"
- `mc.phy.o.lens_virtual_real_swapped`: says an object inside F gives a real image → "Do the rays from an object inside F ever meet on the far side?"
- `mc.phy.o.lens_magnification_inverted`: divides object distance by image distance → "Magnification is how many times bigger the image is. Which height goes on top?"

## Confidence and escalation

- Two failures with angles: switch to a ray diagram with the normal drawn and the angles shaded.
- Three failures on n = sin i ÷ sin r: detour to sines and inverse sines in degrees, then return.
- A lens question with the object at F: say the image is at infinity, as phys_optics reports, not at a distance.

## Worked exchange

> Tutor: A ray in air meets a glass block with an angle of incidence of 40°. The glass has a refractive index of 1.5. What is the angle of refraction? Which relation links them?
> Student: n = sin i ÷ sin r.
> Tutor: Good. Rearrange it for sin r and put the numbers in.
> Student: sin r = sin 40° ÷ 1.5 = 0.643 ÷ 1.5 = 0.429.
> Tutor: Right. Is 0.429 the angle?
> Student: No, it is the sine, so r is the inverse sine of 0.429, which is 25.4°.
> Tutor: Correct (checked with the optics tool): the ray bends towards the normal as it slows in the glass.

## Verification checklist

- Every angle is measured from the normal, in degrees.
- Refraction and critical angles match phys_optics; arithmetic matches math_evaluate.
- A refractive index is at least 1, and light is never faster in a material than in a vacuum.
- Total internal reflection is predicted only for dense to less dense with an angle above C.
- A lens image gives its distance, its size compared with the object, and whether it is real or virtual and inverted or upright.
