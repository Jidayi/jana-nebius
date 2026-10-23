# Simulated students, 2026-10-13 (first pass)

One run per persona of `python -m jana_tools eval simulate` (EVL-04) against llama-server with Gemma 4 12B Q4_K_M as
the tutor, mid hardware class, on a heavily loaded development workstation. The simulator here is the same local
model, standing in for the stronger simulator the suite pins as preferred (a cloud model, which needs the owner's key);
so this pass is evidence for the harness and the leak gate, not a release sample. Personas, seeds and items are pinned
in `evals/personas/personas.yaml`. Student lines are model output playing synthetic personas; tutor lines are model
output. `report.json` holds the counts and every run; `dialogues.jsonl` feeds the tone checks (PED-20, PED-21);
`review-sample.json` is the sample for a teacher's persona-fidelity review.
