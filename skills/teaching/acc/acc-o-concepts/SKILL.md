---
name: acc-o-concepts
kind: teaching
version: "0.1"
status: draft
language: en
summary: Teach identifying and applying the accounting principles in a situation
description: "Accounting principles, concepts, business entity, prudence, realisation, accruals, consistency, materiality, historic cost, going concern: name the principle a situation shows and the treatment it requires. Not for: doing an adjustment (acc-o-accruals-prepayments)."
subject: accounting
levels: [O]
topics: [accounting principles, accounting concepts, business entity, prudence, realisation, accruals, consistency, materiality, historic cost, going concern, money measurement, duality]
kcs:
  - kc.acc.o.concepts.identify_concept
  - kc.acc.o.concepts.apply_concept
curriculum_refs: [ACC-O-17]
prerequisites:
  - kc.acc.o.accounting_equation.purpose_and_users
related: [acc-o-accruals-prepayments, acc-o-inventory]
pedagogy: [pedagogy-guided-solve]
audience: student
roles: [coach, diagnoser, solver, checker]
requires_tools: []
answer_policy:
  mode: withhold_until_earned
  min_attempts: 1
escalation:
  after_failed_attempts: 3
  action: switch_representation
owner: accounting-lead
last_reviewed_by: not-yet-reviewed
last_reviewed_at: "2026-10-13"
success_criteria:
  - The student names the principle that a described situation shows and says why it fits
  - The student chooses the treatment that a stated principle requires and rejects one that breaks it
---

# Accounting principles

## When to use

Use when a question describes a situation and asks which accounting principle applies, or names a principle and
asks how an item must be treated because of it.

Not for: working out an accrual, a prepayment or an inventory value (use acc-o-accruals-prepayments or
acc-o-inventory).

## What this skill does not do

- It does not compute amounts; the principle decides the treatment, and other skills do the arithmetic.
- It does not teach accounting standards by number.
- It does not accept a principle because it sounds careful; the meaning must fit the situation.

## Objectives

1. The student names the principle that a described situation shows and says why it fits.
2. The student chooses the treatment that a stated principle requires and rejects one that breaks it.

## Prerequisite probe

- "Name one group of people who use a business's financial statements, and say what they want to know." Expected: for example a bank lender, who wants to know whether a loan can be repaid.

If it fails, detour to the purpose and users of accounting, then return.

## Teaching sequence

1. Ask the student to say in plain words what the situation is about: whose item it is, when it belongs, how it is valued, or how big it is. Done when the student states the issue.
2. Ask which principle deals with that issue and for its meaning in one sentence. Done when the named principle and its meaning match the item's key.
3. Ask what treatment the principle requires for this item. Done when the treatment matches the item's key.
4. Ask for one treatment that would break the principle and why. Done when the student explains the break.
5. Give a second situation with a different principle that is easy to confuse with the first. Done when the student tells the two apart.

## Hint ladder

1. Orient: "Is this about whose item it is, when it belongs, what it is worth, or how big it is?"
2. Concept: give the meaning of the principle that matches the issue, without its name.
3. First step: offer two principle names and ask which meaning was just given.
4. Worked step: name the principle and ask what treatment it requires here.
5. Full step: give the principle and the treatment; it counts as not mastered and a similar item is scheduled.

## Misconceptions

- `mc.acc.o.con_names_confused`: names a principle whose meaning does not fit → "What does that principle say, and does it match what happened here?"
- `mc.acc.o.con_prudence_catch_all`: gives prudence for any careful treatment → "Is anything here being overstated, or is the issue something else?"
- `mc.acc.o.con_prudence_realisation_confused`: mixes up early losses with revenue on delivery → "Is this about when a sale is recorded, or about a possible loss?"
- `mc.acc.o.con_materiality_vs_entity`: explains a private item by its small size → "Would it belong to the business if it cost much more?"
- `mc.acc.o.con_cost_always`: keeps inventory at cost when it is worth less → "Can the business expect to get its cost back from these goods?"
- `mc.acc.o.con_cash_basis_principle`: records an expense when it is paid → "Which year used the service, whenever the bill was paid?"
- `mc.acc.o.con_consistency_ignored`: changes methods each year for the best result → "Could the profits of two years still be compared if the method kept changing?"
- `mc.acc.o.con_entity_ignored`: records the owner's private spending as an expense → "Whose spending is this, the owner's or the business's?"

## Confidence and escalation

- Two failures naming a principle: switch to a sorting task that matches four meanings to four names.
- Three failures in a row: detour to the users of accounts, then return with a simpler situation.
- A situation the key could fit to two principles: accept a reason that fits, and save it for human help.

## Worked exchange

> Tutor: A shop owner pays for a family holiday from the business bank account and records it as a business expense. Which principle does this break?
> Student: Prudence, because it is not careful.
> Tutor: Prudence stops a business overstating its profit or assets. Whose holiday was it, the owner's or the shop's?
> Student: The owner's. So it breaks the business entity principle, because the business is separate from its owner.
> Tutor: Right. How should the payment be recorded?
> Student: As drawings, not as an expense.
> Tutor: Correct.

## Verification checklist

- The named principle matches the item's key, and its meaning fits the situation.
- The treatment chosen is the one the principle requires, in the pack's terms.
- No amount is computed in this skill; any figure needed is passed to the skill that computes it.
