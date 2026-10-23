---
id: solver-tool-discipline
version: "0.1"
kind: technique
applies_to: [solver, checker]
models: ["*"]
requires_tools: [math_solve]
priority: 70
max_chars: 700
owner: Engine lead
status: draft
---
Batch independent tool calls in one round.
Solve equations with `math_solve`; never rearrange in your head.
Compare two forms with `math_check_equivalence` instead of judging by eye.
Never repeat an unchanged failing call: read the error and fix the arguments.
