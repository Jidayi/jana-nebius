---
name: phy-o-atom
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach atomic structure, nuclide notation, isotopes and the nuclear model
description: "Atoms, protons, neutrons, electrons, nuclide notation, isotopes, alpha scattering, nuclear model: read the proton number from the bottom and the nucleon number from the top, subtract for neutrons, and match each scattering result to its conclusion. Not for: radioactive decay (phy-o-radioactivity)."
subject: physics
levels: [O]
topics: [atoms, protons, neutrons, electrons, nuclide notation, proton number, nucleon number, isotopes, alpha scattering, nuclear model]
kcs:
  - kc.phy.o.atom.atomic_structure
  - kc.phy.o.atom.isotopes
  - kc.phy.o.atom.nuclear_model_evidence
curriculum_refs: [PHY-O-05.01]
prerequisites: []
related: [phy-o-radioactivity]
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
  action: switch_representation
plausibility:
  - quantity: proton_number
    unit: dimensionless
    min: 1
    max: 118
    context: proton numbers of the elements
  - quantity: nucleon_number
    unit: dimensionless
    min: 1
    max: 300
    context: nucleon numbers of known nuclides
  - quantity: radius
    unit: m
    min: 0.000000000000001
    max: 0.000000001
    context: sizes from a nucleus to an atom
owner: physics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student finds the numbers of protons, neutrons and electrons from nuclide notation
  - The student finds the electrons in an ion from its charge
  - The student identifies isotopes as nuclides with the same proton number but different nucleon numbers
  - The student explains how the alpha-scattering results showed a small, dense, positive nucleus
---

# Inside the atom

## When to use

Use when a question gives a nuclide symbol and asks for the numbers of protons, neutrons or electrons, asks which
nuclides are isotopes of one element, or asks what the alpha-particle scattering experiment showed about the atom.

Not for: what happens to the nucleus in alpha or beta decay, half-life or radiation (phy-o-radioactivity).

## What this skill does not do

- It does not treat electron shells beyond counting electrons.
- It does not give atomic masses or relative atomic mass.
- It does not treat the strong force or binding energy.

## Objectives

1. The student finds the numbers of protons, neutrons and electrons from nuclide notation.
2. The student finds the electrons in an ion from its charge.
3. The student identifies isotopes as nuclides with the same proton number but different nucleon numbers.
4. The student explains how the alpha-scattering results showed a small, dense, positive nucleus.

## Prerequisite probe

- "What charge does a proton, a neutron and an electron each carry?" Expected: positive, none, negative.
- "What is 238 − 92?" Expected: 146 (checked with math_evaluate).

If the first fails, show the three particles in a library diagram; if the second fails, practise subtraction, then return.

## Teaching sequence

1. Ask the student to read the two numbers on the symbol: the bottom is the proton number, the top the nucleon number. Done when each number is named correctly.
2. Ask for the protons from the proton number and the neutrons as nucleon number minus proton number. Done when both match math_evaluate.
3. Ask for the electrons in the neutral atom, then in an ion: a positive ion has lost electrons, a negative one gained them. Done when the electron count matches the charge.
4. For isotopes, ask what must be the same and what must differ. Done when the student says the same proton number and different nucleon numbers.
5. For scattering, ask what most alpha particles did, what a few did, and what each result shows. Done when each result is matched to its conclusion.
6. For sizes, ask how the nucleus compares with the whole atom. Done when the student says the nucleus is about a hundred thousand times smaller across and holds nearly all the mass.

## Hint ladder

1. Orient: "Which number on the symbol is on top, and which is at the bottom?"
2. Concept: "The bottom number counts protons; the top number counts protons and neutrons together."
3. First step: write protons = bottom number and ask for the neutrons.
4. Worked step: show the subtraction for the neutrons and ask for the electrons.
5. Full step: give the full answer; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.phy.o.neutrons_equal_nucleon_number`: gives 23 neutrons for sodium-23 → "Does the top number count only neutrons, or protons too?"
- `mc.phy.o.nucleon_proton_numbers_swapped`: takes the top number as the protons → "Which number on the symbol is smaller, and which particles does it count?"
- `mc.phy.o.electrons_equal_neutrons`: matches electrons to neutrons → "Which particles' charge do the electrons cancel?"
- `mc.phy.o.ion_charge_sign_reversed`: says a +1 ion gained an electron → "If an atom gains a negative electron, does it become more positive or more negative?"
- `mc.phy.o.isotopes_differ_in_protons`: says isotopes have different proton numbers → "If the proton number changed, would it still be the same element?"
- `mc.phy.o.isotope_means_radioactive`: says carbon-12 is not an isotope → "Is carbon-12 a version of carbon with its own number of neutrons?"
- `mc.phy.o.isotopes_differ_chemically`: says isotopes react differently → "Reactions depend on electrons. Do isotopes of one element have different numbers of electrons?"
- `mc.phy.o.ion_as_isotope`: calls an ion a new isotope → "Did the nucleus change when the atom lost an electron?"
- `mc.phy.o.scattering_most_bounced_back`: says most alpha particles bounced back → "If most went straight through, what is most of the atom?"
- `mc.phy.o.deflection_by_electrons`: blames electrons for the big deflections → "Could something as light as an electron turn back a heavy alpha particle?"
- `mc.phy.o.plum_pudding_fits_results`: says spread-out charge explains the rebounds → "Could a thin spread of positive charge push hard enough to turn an alpha particle back?"
- `mc.phy.o.nucleus_fills_atom`: draws the nucleus filling much of the atom → "If the nucleus were that big, would most alpha particles pass straight through?"

## Confidence and escalation

- Two failures on nuclide notation: switch to a labelled symbol with arrows to each number.
- Three failures on scattering: compare the two models in a library diagram, result by result.
- A nuclide not in the pack: read its numbers from the symbol the question gives; never recall them from memory.

## Worked exchange

> Tutor: A sodium nuclide has a nucleon number of 23 and a proton number of 11. How many protons, neutrons and electrons does a neutral sodium atom have? Start with the protons.
> Student: 11 protons, from the bottom number.
> Tutor: Good. And the neutrons?
> Student: The top number counts protons and neutrons, so 23 − 11 = 12 neutrons.
> Tutor: Right. And the electrons in the neutral atom?
> Student: 11, the same as the protons, so the charges cancel.
> Tutor: Correct (checked with the maths tool). How many would a sodium ion with a charge of +1 have?
> Student: It has lost one electron, so 10.
> Tutor: Right.

## Verification checklist

- Protons come from the proton number and neutrons from nucleon number minus proton number, checked with math_evaluate.
- Electrons equal protons in a neutral atom and follow the charge in an ion.
- Isotopes share a proton number and differ in nucleon number.
- Each scattering result is matched to its own conclusion.
- Any size compared is converted with units_convert.
