---
name: mth-o-transformations-and-vectors
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach transformations of points and shapes, and column vector work
description: "Transformations, translation, reflection, rotation, enlargement, column vectors, magnitude: state every detail of the move, apply it one point at a time and check the image. Not for: similarity and congruence (mth-o-geometry) or Pythagoras in triangles (mth-o-trigonometry)."
subject: mathematics
levels: [O]
topics: [transformations, translation, reflection, rotation, enlargement, scale factor, column vectors, vectors, magnitude]
kcs:
  - kc.mth.o.transformations_and_vectors.transform_points
  - kc.mth.o.transformations_and_vectors.enlargement
  - kc.mth.o.transformations_and_vectors.vector_arithmetic
  - kc.mth.o.transformations_and_vectors.vector_magnitude
curriculum_refs: [MTH-O-07.01, MTH-O-07.02, MTH-O-07.03]
prerequisites:
  - kc.mth.o.coordinate_geometry.points_on_lines
  - kc.mth.o.geometry.symmetry
  - kc.mth.o.geometry.similar_lengths
  - kc.mth.o.number.order_of_operations
  - kc.mth.o.trigonometry.pythagoras
related: [mth-o-geometry, mth-o-trigonometry, mth-o-coordinate-geometry]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate, geom_figure]
visuals: [transformation_grid]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: coordinate
    unit: dimensionless
    min: -100
    max: 100
    context: coordinates of images of points on a school grid
  - quantity: scale_factor
    unit: dimensionless
    min: -10
    max: 10
    context: scale factors of enlargements, including fractions and negatives
  - quantity: length
    unit: cm
    min: 0
    max: 1000
    context: side lengths of shapes before and after an enlargement
  - quantity: area
    unit: cm^2
    min: 0
    max: 100000
    context: areas of shapes before and after an enlargement
  - quantity: magnitude
    unit: dimensionless
    min: 0
    max: 1000
    context: length of a column vector with whole-number components
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student states a transformation fully, with its type and every detail it needs
  - The student finds the image of a point by applying the transformation to its coordinates
  - The student calculates vector sums, multiples and magnitudes one component at a time
---

# Transformations and column vectors

## When to use

Use when a question asks for the image of a point or shape after a translation, reflection, rotation or enlargement,
for the description of a transformation, for lengths, areas or scale factors in an enlargement, or for sums,
differences, multiples and magnitudes of column vectors.

Not for: proving shapes similar or congruent (mth-o-geometry), or Pythagoras and trigonometry in triangles
(mth-o-trigonometry).

## What this skill does not do

- It does not combine transformations into one matrix.
- It does not treat vector geometry proofs with position vectors.
- It does not accept a description with a detail missing, such as a rotation with no centre.

## Objectives

1. The student states a transformation fully, with its type and every detail it needs.
2. The student finds the image of a point by applying the transformation to its coordinates.
3. The student calculates vector sums, multiples and magnitudes one component at a time.

## Prerequisite probe

- "From the origin, how far across and how far up is the point (−2, 3)?" Expected: 2 to the left and 3 up.
- "Work out √(3² + 4²)." Expected: 5.

If either fails, detour to coordinates in mth-o-coordinate-geometry or to Pythagoras in mth-o-trigonometry.

## Teaching sequence

1. Ask the student to name the transformation and its details: a vector; a mirror line; a centre, angle and direction; or a centre and scale factor. Done when every detail is stated.
2. Ask the student to transform one point first, measuring from the mirror line or the centre; math_evaluate gives the reference image. Done when that image matches.
3. Ask the student to repeat for the other vertices. Done when every vertex matches its checked image.
4. For an enlargement, ask for new length = scale factor × old length and new area = scale factor² × old area. Done when both match math_evaluate.
5. For vectors, ask the student to work the top components, then the bottom ones, applying any number in front to both. Done when each component matches math_evaluate.
6. For a magnitude, ask for the square root of top² + bottom². Done when the length matches math_evaluate.

## Hint ladder

1. Orient: "What kind of move is this, and what details does it need?"
2. Concept: name the idea, such as "an image is as far beyond the mirror as the point is in front".
3. First step: ask for the distance or the vector from the mirror line or the centre to one point.
4. Worked step: show the image of one point and ask for the next.
5. Full step: show the checked image; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.reflection_not_doubled`: puts the image on the mirror line → "Is the image as far behind the mirror as the point is in front?"
- `mc.mth.o.rotation_half_turn`: changes (x, y) to (−x, −y) for a quarter turn → "Is a 90° turn the same as a half turn?"
- `mc.mth.o.translation_components_swapped`: adds the bottom component to x → "Which component moves the point across?"
- `mc.mth.o.enlargement_centre_ignored`: multiplies coordinates when the centre is not the origin → "Where do you measure the distances from?"
- `mc.mth.o.enlargement_added`: adds the scale factor to each length → "If a 4 cm side is enlarged by scale factor 3, is it 7 cm or 12 cm?"
- `mc.mth.o.vector_scalar_dropped`: multiplies only the top component by the number in front → "Does doubling a move double the across part, the up part, or both?"
- `mc.mth.o.vector_subtract_sign`: adds a negative component that should be subtracted → "What is 2 − (−5)?"
- `mc.mth.o.magnitude_signed_sum`: adds the components to get the length → "A vector moves 3 across and 3 down. Is its length really zero?"

## Confidence and escalation

- Two failures on the same transformation: switch to the transformation_grid and count squares from the centre or mirror line.
- Three failures on a magnitude: detour to Pythagoras in mth-o-trigonometry.
- A wrong image every time for one rotation direction: ask the student to turn the page or tracing paper and watch.
- A notation the student says the local syllabus uses differently: save the question for human help.

## Worked exchange

> Tutor: Enlarge P(3, 2) by scale factor 2 with centre C(1, 1). Where is the image?
> Student: At (6, 4).
> Tutor: That works only for a centre at the origin. What is the move from C to P?
> Student: 3 − 1 = 2 across and 2 − 1 = 1 up.
> Tutor: Good. Multiply that move by 2 and add it to C.
> Student: 4 across and 2 up from (1, 1), so (5, 3).
> Tutor: That's right (checked with the maths tool): the image is twice as far from C as P is.

## Verification checklist

- Each image point matches math_evaluate, and one distance from the centre or mirror line was checked.
- A rotation has a centre, an angle and a direction; an enlargement has a centre and a scale factor.
- Lengths scale by the scale factor and areas by its square.
- A vector magnitude is positive and matches math_evaluate.
- A figure drawn for the student takes its lengths, angles and points from a geom_figure result.
