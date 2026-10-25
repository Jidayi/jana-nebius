---
name: phy-o-kinematics-suvat
kind: teaching
version: "1.2"
status: draft
language: en
summary: Teach constant-acceleration problems with the suvat equations and units
description: "suvat, constant acceleration, motion equations: select knowns, check units and direction. Not for: variable acceleration."
subject: physics
levels: [O]
topics: [constant acceleration]
kcs:
  - kc.phy.o.kinematics.suvat_select
  - kc.phy.o.kinematics.suvat_solve
prerequisites: []
curriculum_refs: [PHY-O-01.02]
pedagogy: [pedagogy-socratic-drill]
audience: student
roles: [coach, solver, checker, diagnoser]
requires_tools: [math_solve, math_evaluate]
visuals: [free_body]
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: prerequisite_detour
plausibility:
  - quantity: height
    unit: m
    min: 0
    max: 100
    context: small thrown objects
owner: synthetic-author
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-01-01"
success_criteria:
  - The student lists the knowns and the unknown with units before choosing an equation
---

# Synthetic constant-acceleration teaching fixture

## When to use

Use for a constant-acceleration problem with known quantities.

## What this skill does not do

- It does not introduce calculus.

## Objectives

1. The student lists the knowns and the unknown with units before choosing an equation.

## Prerequisite probe

Ask which quantity changes and which direction is positive.

## Teaching sequence

1. Name the positive direction. Done when the direction is on the board.
2. Ask for knowns with units. Done when each given quantity has a symbol and unit.
3. Choose a relation and check it. Done when the substituted result has a tool check.

## Plausible ranges

Use the height range in the metadata to ask about units when a result is implausible.

## Hint ladder

1. Ask which quantity is unknown.
2. Point to the known quantities.
3. Name the relation connecting those quantities.
4. Substitute the knowns and ask the student to finish.
5. Full step: show the checked answer; this counts as not mastered and a similar problem is scheduled.

## Misconceptions

- `mc.phy.o.kmh_not_converted` → speed units differ → Which units does the equation need?

## Confidence and escalation

Ask for a missing given rather than guessing it.

## Worked exchange

> Student: I used a starting speed of 20 m/s. Is my equation right?
> Tutor: That's right (checked with the maths tool), and 20 m is the rounded result.

## Verification checklist

- Every confirmed value has a check.
- The student named the knowns before selecting an equation.
