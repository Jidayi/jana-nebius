# scripts

Repository tooling. Not shipped.

| Path | Holds |
| --- | --- |
| `jana_tools/` | Checks run by CI: `uv run python -m jana_tools` runs every lint-stage check; subcommands below |
| `tests/` | Tests of the repository rules, named after the acceptance tests they implement |
| `ci/` | CI stage scripts: offline harness and self-test, full test run, codegen check, security scans |
| `governance/` | Boundary owners (generates `.github/CODEOWNERS`), scope trace, review paths, vulnerability exceptions |
| `git-hooks/` | The no-spec guard (pre-commit, pre-push); enable with `git config core.hooksPath scripts/git-hooks` |
| `content/mock_papers/` | Generator of the O level mock papers (ASM-15, CUR-31); `--check` fails when the tree differs. The Physics and Mathematics drafting generators were retired on 2026-10-15: the records under `content/curriculum/` are the source of truth (AUT-03; see its README) |

Subcommands: `importlinter --write`, `codeowners --write`, `notices --write` (regenerate derived files);
`sbom <dir>`; `coverage <milestone> [--junit results.xml]` (acceptance-test coverage report);
`stages-needs`, `boundary-review`, `feature-review` (used by CI jobs).
