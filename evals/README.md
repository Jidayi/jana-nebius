# Evaluation suites and fixtures

Suites, fixtures, contract corpora, scenario YAML, gallery fixtures and reports (ARC-16). Every scenario is
synthetic (`synthetic: true`); none describes a real student or a real result. Scenario files validate against
the evaluation scenario contract in the specification. The harness in `scripts/jana_tools/harness` runs them
through the same engine, router and tool worker the app ships (EVL-01).

| Path | Holds |
| --- | --- |
| `suites.toml` | Every suite of TABLE EVL-01a: owner, cadence, first stage, frozen version and the files it locks |
| `lock.json` | The sha256 of every locked file per suite version and the split policy (EVL-18) |
| `scenarios/`, `safety/` | Scenario suites; `<file>.meta.yaml` beside each holds item metadata (EVL-24); scripted replies for the per-commit run are in `scripts/` |
| `held-out/` | Held-out items, encrypted; only a release run with the release key reads them (EVL-18) |
| `devlab/` | The device lab's fixed timing scripts and laptop register (EVL-14); `survey/template.csv`, the pilot device survey's columns (PLT-29) |
| `perception/printed/` | The printed-photo set of EVL-12 (`set.json` beside the photos of synthetic or licensed question sheets); not assembled yet |
| `bakeoff/` | Recorded bake-off reports (EVL-15), one `<run id>.json` each; the release check requires one behind every model's class (MDL-27) |
| `revisions.jsonl` | The tuning revision log, one tuning unit per revision (EVL-19); created by the first revision |
| `prompt-snapshots/`, `contracts/`, `cassettes/`, `recordings/`, `live-runs/` | Prompt snapshots, contract corpora, model cassettes and recorded sessions |

Commands (from the repository root):

```bash
uv run python -m jana_tools eval run
```

runs every suite this build can run and writes a report and summary to `evals/reports/` (ignored by git). Other
commands: `eval lock [--write]` (check or refresh the lock after a version bump), `eval gate <report> [--release]`,
`eval commit-checks <range>` (EVL-19 and EVL-20 on a range of commits), `eval seal <suite> <items.yaml>` (with the
release key in `JANA_HELD_OUT_KEY`) and `eval revision <entry.json>`. Device-lab measurements for a laptop's file:
`lab classbench`, `lab memfit`, `lab perception`, `lab overhead` and `lab survey` (`python -m jana_tools lab` lists
them); `release models` is the MDL-27 and MDL-28 check.

Changing a locked file means bumping that suite's version in `suites.toml` and running `eval lock --write`; a gate run
refuses a changed suite whose version did not move. A commit that fixes an incident (`INC-n`) or a user report
(`RPT-n`) adds a `regression` split item whose metadata names it in `regression_of`.
