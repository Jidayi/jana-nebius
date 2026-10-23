---
name: phy-o-magnetism
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach magnetic poles, magnetic materials and the field round a bar magnet
description: "Magnets, poles, magnetic materials, soft iron and steel, induced magnetism, magnetic field lines, compasses: apply like repels and unlike attracts, test with repulsion, and draw lines from north to south that never cross. Not for: fields of currents and motors (phy-o-electromagnetism)."
subject: physics
levels: [O]
topics: [magnets, poles, magnetic materials, soft iron, steel, induced magnetism, magnetic field lines, compass]
kcs:
  - kc.phy.o.magnetism.magnets_and_materials
  - kc.phy.o.magnetism.magnetic_fields
curriculum_refs: [PHY-O-04.01]
prerequisites: []
related: [phy-o-electromagnetism]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [math_evaluate]
visuals: [library_diagram]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: distance
    unit: m
    min: 0
    max: 2
    context: distances between magnets, compasses and objects on a lab bench
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student predicts attraction or repulsion between poles and explains why only repulsion proves a magnet
  - The student names the magnetic materials and tells soft magnetic materials from hard ones by their uses
  - The student explains induced magnetism in a piece of iron near a magnet
  - The student draws and reads the field round a bar magnet, its direction and where it is strongest
---

# Magnets and magnetic fields

## When to use

Use when a question asks whether two magnets attract or repel, which materials a magnet attracts, why iron is used in
electromagnets and steel in permanent magnets, how a magnet picks up a nail, or what the field round a bar magnet
looks like and which way a compass points in it.

Not for: the field round a wire or a coil, motors and generators (phy-o-electromagnetism).

## What this skill does not do

- It does not treat the Earth's magnetic field beyond a compass pointing north.
- It does not measure field strength as a number.
- It does not explain magnetism by domains in detail.

## Objectives

1. The student predicts attraction or repulsion between poles and explains why only repulsion proves a magnet.
2. The student names the magnetic materials and tells soft magnetic materials from hard ones by their uses.
3. The student explains induced magnetism in a piece of iron near a magnet.
4. The student draws and reads the field round a bar magnet, its direction and where it is strongest.

## Prerequisite probe

- "Name a metal that a magnet does not attract." Expected: any of copper, aluminium, brass or gold.
- "Which way does the north end of a compass needle point on its own?" Expected: towards the Earth's north.

If either fails, show the poles and a compass in a library diagram before starting.

## Teaching sequence

1. Ask which poles face each other. Done when the student names both poles.
2. Ask what like and unlike poles do. Done when the student predicts repel or attract with the rule.
3. For an unknown object, ask what test proves it is a magnet. Done when the student says repulsion, because a magnet attracts plain iron too.
4. For a material, ask whether it is magnetic and, if so, soft (easily magnetised and loses it) or hard (keeps it). Done when soft iron and steel are each matched to a use.
5. For induced magnetism, ask what pole forms in the near end of the iron. Done when the student says the opposite pole, so it is attracted.
6. For a field, ask the student to draw the lines from north to south, closest at the poles, never crossing. Done when the drawing has all three features.
7. Ask which way a compass points at a given place in the field. Done when the north end follows the field line's arrow.

## Hint ladder

1. Orient: "Which poles face each other, or where is the compass placed?"
2. Concept: "Like poles repel, unlike poles attract; field lines run from north to south outside the magnet."
3. First step: label the poles on a diagram and ask for the force or the line direction.
4. Worked step: draw one field line with its arrow and ask for the rest of the pattern.
5. Full step: give the full answer; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.like_poles_attract`: says two north poles attract → "If you bring two north poles together, do you feel a push or a pull?"
- `mc.phy.o.attraction_proves_magnet`: says attraction proves a magnet → "A plain nail is also pulled. What test would a nail fail?"
- `mc.phy.o.nonmagnetic_materials_attracted`: says magnets attract aluminium cans → "Why can recycling plants use a magnet to separate steel cans from aluminium ones?"
- `mc.phy.o.soft_iron_steel_swapped`: says soft iron makes the best permanent magnet → "Which material loses its magnetism as soon as the current stops?"
- `mc.phy.o.induced_pole_same_as_inducing`: says the near end of the nail becomes north near a north pole → "If it did, would the nail be pushed away or pulled in?"
- `mc.phy.o.nonmagnetic_blocks_magnetism`: says paper stops a magnet's pull → "How does a fridge magnet hold a sheet of paper to the door?"
- `mc.phy.o.field_lines_s_to_n`: draws the arrows from south to north → "Which way does a compass's north end point near the magnet's north pole?"
- `mc.phy.o.field_lines_can_cross`: lets two lines cross → "At a crossing, which way would a compass point?"
- `mc.phy.o.field_strongest_at_middle`: says the field is strongest beside the middle → "Where do iron filings gather most thickly?"
- `mc.phy.o.compass_points_at_like_pole`: says the compass's north end points at the magnet's north pole → "Do like poles attract or repel?"
- `mc.phy.o.field_lines_spacing_reversed`: says widely spaced lines show a strong field → "Where are the lines closest together, and where is the pull strongest?"

## Confidence and escalation

- Two failures on the pole rule: switch to a diagram with two magnets and arrows for the forces.
- Three failures on field lines: plot the field with a compass at several points together, then join them.
- A question about a material the pack does not list: say which group it would need to be in, and ask for help.

## Worked exchange

> Tutor: Two bar magnets lie end to end with a north pole facing a north pole. Then one magnet is turned round. What happens each time? First, what do like poles do?
> Student: They repel, so the magnets push apart.
> Tutor: Good. And after one is turned round?
> Student: Now a north pole faces a south pole, so they attract.
> Tutor: Right. A plain iron nail is also pulled towards either pole. Does that make the nail a magnet?
> Student: No. The magnet induces an opposite pole in the near end of the nail, so it is pulled either way. Only repulsion would prove it is a magnet.
> Tutor: Correct.

## Verification checklist

- Every prediction uses like poles repel and unlike poles attract.
- Only iron, steel, nickel and cobalt are named as magnetic.
- Soft iron is matched to temporary magnets and steel to permanent ones.
- Field lines run from north to south outside the magnet, never cross, and crowd at the poles.
- Any distance compared is taken from the question or checked with math_evaluate.
