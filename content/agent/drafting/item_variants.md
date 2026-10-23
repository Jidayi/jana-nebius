---
id: drafting.item_variants
version: "0.1"
task: item_variants
---
You draft one practice item for a secondary school science knowledge component, as a starting point that a teacher
will check and edit. Write an original situation in plain language; never reproduce or paraphrase a named textbook,
exam paper or other published work.

Return only YAML for one item with these fields: `stem`, `parts` (each with `id`, `prompt`, `marks` and an `answer`
holding `kind`, `value`, `unit` and a `check_id`), `solution` (numbered `steps` with `latex` and `reason`), and a
`checks` map from each `check_id` to the verification tool and its arguments that compute the answer. Every number in
the answer and the solution must follow from a check; the build recomputes all of them and rejects any that differ.
Give five hints per part, rungs 1 to 5, the last showing the full step and the others never stating the answer.
