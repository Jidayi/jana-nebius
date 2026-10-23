---
id: numbers-from-checks
version: "0.1"
kind: technique
applies_to: [coach, solver]
models: ["*"]
essential: true
priority: 95
max_chars: 500
owner: Engine lead
status: draft
---
Use only numbers that come from a tool check, the question or the student's own line.
List the source of each number in `numbers_from`; a number with no source is removed before the student sees it.
