---
id: drafting.worked_example
version: "0.1"
task: worked_example
---
You draft a worked example for a knowledge component: an original problem and its solution as board steps, each with
`latex`, a one-line `reason`, and a `check_id` for every step that produces a number. Return only YAML with `problem`,
`steps` and a `checks` map from each `check_id` to the verification tool and its arguments.
