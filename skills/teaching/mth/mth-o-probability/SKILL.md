---
name: mth-o-probability
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach single, combined and dependent probabilities and expected frequency
description: "probability, expected frequency, relative frequency, tree diagrams, combined events, without replacement: count outcomes, multiply along branches, add across them. Not for: averages, charts or data tables (mth-o-statistics)."
subject: mathematics
levels: [O]
topics: [probability, expected frequency, relative frequency, tree diagrams, combined events, without replacement]
kcs:
  - kc.mth.o.probability.single_event
  - kc.mth.o.probability.expected_frequency
  - kc.mth.o.probability.independent_events
  - kc.mth.o.probability.dependent_events
curriculum_refs: [MTH-O-08.01, MTH-O-08.02, MTH-O-08.03]
prerequisites:
  - kc.mth.o.number.fdp_conversion
  - kc.mth.o.number.fraction_arithmetic
related: [mth-o-statistics]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: [stats_compute, math_evaluate]
visuals: [probability_tree, matrix_table]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
plausibility:
  - quantity: probability
    unit: dimensionless
    min: 0
    max: 1
    context: probabilities of single, combined and dependent events
  - quantity: relative_frequency
    unit: dimensionless
    min: 0
    max: 1
    context: successes divided by trials in an experiment
  - quantity: expected_frequency
    unit: dimensionless
    min: 0
    max: 100000
    context: expected number of times an event happens in a set number of trials
owner: mathematics-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student writes a probability as favourable outcomes over all equally likely outcomes, as a fraction or decimal from 0 to 1
  - The student multiplies along the branches for "and" and adds the separate routes for "or"
  - The student changes the second probability when an item is not replaced
---

# Probability: single and combined events

## When to use

Use when a problem asks for the probability of an event or of it not happening, a relative frequency, an expected
number of results, or the probability of two events from a table or a tree diagram, with or without replacement.

Not for: means, medians, charts or reading data tables (use mth-o-statistics).

## What this skill does not do

- It does not use formal set notation or conditional probability symbols.
- It does not accept a probability written as odds or as a ratio.
- It does not run simulations; it reasons from counts and given probabilities.

## Objectives

1. The student writes a probability as favourable outcomes over all equally likely outcomes, as a fraction or decimal from 0 to 1.
2. The student multiplies along the branches for "and" and adds the separate routes for "or".
3. The student changes the second probability when an item is not replaced.

## Prerequisite probe

- "Write 3/8 as a decimal." Expected: 0.375.
- "Work out 2/3 × 3/5." Expected: 2/5.

If either fails, step back to fraction and decimal conversion or to multiplying fractions, then return.

## Teaching sequence

1. Ask the student to list the outcomes or the counts of each kind, and the total. Done when the total is on the board.
2. Ask whether the question is about one event, "and", "or", "not" or "at least one". Done when the student names the type.
3. For two picks, ask whether the first item goes back before the second pick. Done when the student says how the second total changes.
4. Ask the student to draw the table or tree with a probability on every branch. Done when each pair of branches adds to 1.
5. Ask the student to multiply or add as the type needs; the math_evaluate or stats_compute result is the reference value. Done when the student's value matches the checked value.
6. For expected frequency, ask for the number of trials times the probability. Done when the student's count matches the checked value.

## Hint ladder

1. Orient: "How many outcomes are there in total, and how many are the ones you want?"
2. Concept: name the rule, such as "for this and then that, multiply the probabilities".
3. First step: draw the first set of branches and ask the student to label them.
4. Worked step: show the route on the tree and ask the student for the product.
5. Full step: show the checked probability; the step counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.mth.o.probability_as_odds`: divides favourable by unfavourable → "Out of how many beads altogether are you choosing?"
- `mc.mth.o.probability_equal_categories`: gives 1 over the number of colours → "Are there as many red beads as blue beads?"
- `mc.mth.o.complement_not_taken`: gives P(event) when P(not) is asked → "Is the question about it happening or about it not happening?"
- `mc.mth.o.expected_divides`: divides trials by the probability → "Should you expect more results than the number of trials?"
- `mc.mth.o.relative_frequency_inverted`: divides trials by successes → "Can a relative frequency be bigger than 1?"
- `mc.mth.o.and_as_add`: adds for "both" → "Is it more likely or less likely that both things happen than just one?"
- `mc.mth.o.complement_of_both`: works out 1 − P(both) for at least one → "Which result is the only one with no success at all?"
- `mc.mth.o.without_replacement_ignored`: keeps the same second probability → "After one bead is taken out, how many are left in the bag?"
- `mc.mth.o.denominator_not_reduced`: changes the top but not the total → "The bag lost one bead; what is the new total?"

## Confidence and escalation

- Two failures combining events: switch representation from a calculation to a tree diagram or a sample space table.
- Three failures multiplying fractions: detour to fraction arithmetic, then return.
- A context the student does not understand, such as a game or a local custom: save a local question for human help.

## Worked exchange

> Tutor: A bag has 3 red and 5 blue beads. Two beads are taken without replacement. What is the probability both are red? What is P(red) first?
> Student: 3 out of 8, so 3/8.
> Tutor: Good. How many beads are left, and how many are red?
> Student: 7 left and 2 red, so 2/7.
> Tutor: Both red means red and then red. What do you do with the two probabilities?
> Student: Multiply: 3/8 × 2/7 = 6/56 = 3/28.
> Tutor: Right (checked with the maths tool), and 3/28 is small, which fits two reds from mostly blue beads.

## Verification checklist

- Every number shown comes from the question or from a math_evaluate or stats_compute check.
- Every probability lies from 0 to 1, and each set of branches adds to 1.
- Without replacement, both the count and the total drop for the second pick.
- Fractions are in lowest terms; inexact decimals are given to 3 significant figures.
