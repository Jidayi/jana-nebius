# Jana Studio

Internal offline authoring app. Open a curriculum checkout, choose an author, edit contract forms or JSON and preview
with the production lesson, board and visual renderers. The app runs the same validation, verification, lint, maths QA
and injection scan as `aut`. Local deterministic editing needs no learner database, tutor model or online service.

Valid JSON autosaves after five seconds. Navigation and native close flush first. Incomplete JSON, disk conflicts and
failed saves retain the draft and block leaving. Skill and diagram editors share that revision-aware draft behavior;
conflicts offer a copy. Bulk imports and authored variant recipes have explicit discard controls.

## Authoring workflows

- Misconception benches compute wrong answers with the production matcher and worker, flag collisions and link
  probes/distractors. Conditional step/structural signatures state the required working evidence and use the sandbox.
- Typed template sampling covers up to 50 combinations including range boundaries, constraints, local-context word
  lists, key distribution and unmarkable keys. Authors can record source-bound sampled parameter ranges. Worked
  examples have a draggable, keyboard-operable fading order restricted to existing steps, and a template variant
  action accepting an authored parameterised JSON recipe. Every key/check is recomputed; new variants remain drafts.
- Skill editors expose the canonical front matter, section skeleton, rule/line findings, injection checks, case counts,
  role index budget and slices. Submission requires current, real local-model evidence as well as deterministic gates.
- Diagram management includes safe SVG tagging, sanitisation reports, part keyboard controls, licence gates, sequences,
  production previews and new identities when part meanings change. Source approvals remain separate.
- Diffs use the last committed published source, with semantic marking/version flags, board/diagram overlays and
  section-aware skill changes. Anchored comments support threads and block publication until resolved.
- Version plans enforce semantic minimum bumps and correction notes. Retirement checks references and reserves IDs.
  KC migrations check all references and replay a fictional event log through the production projector and an
  independently expanded reference. Multi-file changes use a durable recovery journal.
- YAML/CSV imports require a matching clean dry run, complete licensed provenance and external references. Re-imports
  are idempotent; all attributions and declared AI assistance are retained. Learner-data column formats are refused.
- Verification, evaluation-bank placement and publication use the existing authoring gates. Publication requires
  current green evidence, committed sources and no blocking comments. Signing is queued to the existing service;
  no publisher private keys are held in Studio.

## Development and checks

Use the existing workspace dependencies and `pnpm --filter @jana/studio dev` at `http://127.0.0.1:5191`.
`JANA_STUDIO_WORKSPACE` selects the local checkout; `JANA_STUDIO_PYTHON` selects its trusted interpreter. The browser
cannot choose a filesystem root. The development bridge checks loopback host/origin, per-launch token and input bounds.
Production uses fixed native commands and bounded JSON-lines stdio; the native folder picker selects the root.

Run Studio tests, typecheck and build with its package scripts; run the backend's `test_m22_studio.py` and M8 tests.
`node scripts/ci/studio-browser.mjs --out=<directory>` runs fictional-workspace browser journeys and axe/layout audits.
`cargo check --offline -p jana-studio` checks the native launcher. The shared launch screen paints before the editor
and its separate maths/validator chunks load.

## Local model evaluations

Configure trusted `JANA_STUDIO_EVAL_URL` (loopback HTTP only), `JANA_STUDIO_EVAL_MODEL` and, when needed,
`JANA_STUDIO_EVAL_KEY` before launching. `JANA_STUDIO_SIMULATOR_MODEL` optionally selects the simulated student model.
Jobs use the real S2 harness, selected workspace content and development cases. Without this runtime they stay queued.
Results bind source/runtime fingerprints and attach to authoring records; stale results cannot satisfy publication.
Simulation transcripts report leaks/checks and explicitly require a calibrated judge for rubric conclusions.
Unit tests using fixture providers prove orchestration, not real-model quality or candidate acceptance.

## Internal packaging and external acceptance

`scripts/packaging/build-studio.sh` builds/stages the backend and tool worker separately from learner resources.
Install hash-pinned `requirements-build.txt` into an isolated build environment, set `JANA_STUDIO_BUILD_PYTHON`,
`JANA_STUDIO_NODE` and `JANA_STUDIO_NODE_LICENSE` to reviewed platform inputs, then run the script. It bundles authoring
contracts, evaluator assets, Node/KaTeX and notices and exercises the frozen backend from a separate cwd without a
project Node on PATH. `tauri.package.conf.json` supplies the native resource overlay; signing follows staging.
The trusted `JANA_STUDIO_BACKEND` native override can select an internal packaged backend.

The local macOS backend smoke is not signed-installer acceptance. Windows/Linux builds, native webview/screen-reader
and physical-device checks, signing/notarisation, offline WebView2 provisioning on Windows, visual baseline approval,
actual local-model runs and calibrated-judge observations remain external evidence requirements. The release Tauri
CLI pin, signing identities and benchmarked runtime inputs remain release-owner work. No specialist content approval
or milestone acceptance is inferred from these software checks.
