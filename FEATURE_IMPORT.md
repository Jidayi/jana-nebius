# Jana feature import — 25 October 2026

Imported feature source and tests from the local `../jana` working tree, whose HEAD was `41b57e01`, into this fork. This is a source integration, with three-way merges against the fork's initial snapshot; it does not replace the fork or copy another repository's Git directory.

| Capability | Entry point |
| --- | --- |
| Tutor pen and annotations, pointing back, diagram manipulation and replay | Tutor board and supported diagrams |
| Rough sketches and additional biology, chemistry, physics and maths visuals | Tutor visuals; development gallery at `/gallery.html` |
| Weekly parent summary and local PDF printing | Settings → Parent summary |
| Local parent alerts | Settings → Alerts |
| Retained conversations, boards and visuals, read-only | Progress → Session history |
| Item and skill analytics, diagrams and authoring reports | Authoring Studio → Analytics and reports |

The browser development adapter uses stage S3 to expose these imported screens. This is a development feature setting, not a production release acceptance claim. Sketches retain their checked/unchecked status and their measured token cost is recorded separately.

## Preserved fork behavior

The Nebius gateway, NVIDIA runtime, existing inference budget, consent checks and profile data remain in place. The daily plan, lesson, practice, assessment and Study journey work is preserved, including saved quiz answers, citations and returning from tutor help. Private specification files, provider credentials, model weights and application data are excluded from this import.

Integration fixes include exported contract paths, generated visual/worker bindings, parent-report print tokens, local Greek font coverage, and sketch-cost assertions using this fork's provider price table. Mock follow-up practice now keeps every weak idea in its set rather than opening a new journey for only the first idea.

## Validation

- Renderer suite: 55 passed; client suite: 359 passed; Studio suite: 34 passed; worker suite: 102 passed.
- UI suite: 632 passed initially; its remaining print-theme failure was fixed and all 6 parent-view tests pass, covering all 633 UI tests across those runs.
- Focused visual/parent/history/analytics backend suite: 75 passed initially; the remaining sketch-cost test was fixed. Sketch and research retests: 15 passed.
- Learning-journey, Study-journey, quiz-help and browser-host regressions: 37 passed.
- Pointing-demo and personal-calibration suite: 27 passed in the outer sandbox; its remaining real-worker demo passed separately with permission to start the worker's own macOS sandbox.
- Focused desktop regressions: 27 passed; the remaining glyph test passed after adding Greek font coverage and using `1/cm` in the infrared axis label.
- Desktop and Studio production builds and type checks passed. Code generation consistency, source ESLint, Python Ruff and whitespace checks passed.
- Live browser checks: Home retains its objective; Settings serves the parent summary and alerts; Progress opens session history; a science diagram advances its steps and hides its labels.

The broad desktop browser accessibility/input suite was not completed: the first run could not bind localhost inside the outer sandbox, and the permission-enabled rerun was stopped to keep the development app responsive. This note does not claim full browser accessibility certification or live model qualification of every visual type.

## Local checkpoints

The complete pre-import working tree was backed up under `/private/tmp/jana-feature-port-20261025` and checkpointed separately at `a69f50d7161a` on `codex/import-jana-features`. The feature import follows that checkpoint so its changes can be reviewed independently. No remote push is part of this operation.
