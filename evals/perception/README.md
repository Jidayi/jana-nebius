# M21 capture evaluation

`regression/` contains 29 owned, rendered worksheets and independent labels. It covers typed questions across subjects,
rotation/EXIF, perspective and tilt, printed working, a diagram and stacked fraction, multiple questions, privacy masking,
instruction-like text, blocking quality checks and confirmation edits. No learner photos are included. The manifest identifies
the fixtures as synthetic, rendered, regression-only and **not release evidence**. The pictures are not the 200 ordinary-camera
photos required by EVL-12 and do not establish detector accuracy or confidence calibration.

The suite uses the production `CaptureDesk`, assembled `Engine`, strict event validation, sandboxed preprocessing and selected
reader. It does not mock OCR, quality decisions or confirmation. The store is temporary and deleted after the run. Cases record
the reader path, capture id and fixture digest; image bytes are not copied into reports. Individual transcription failures remain
failures. Reports separate exact transcription from the other assertions, so a successful privacy check cannot inflate accuracy.

Run the installed OCR fallback:

```sh
.venv/bin/python -m jana_tools eval run --stage S2 --only perception --out /tmp/jana-photo-ocr
```

A missing sandbox, reviewed OCR asset or runtime fails the evaluated cases rather than producing an empty passing suite.
Tesseract is not a validated printed-formula reader: the baseline includes deliberately scored challenges it cannot yet read.
A nonzero command exit is a failed evaluation, even when the evaluator's own unit tests pass.

Run an installed local vision model and its projector:

```sh
.venv/bin/python -m jana_tools lab capture-regression LLAMA_SERVER GGUF MMPROJ MODEL_ID high --out /tmp/jana-photo-vision
```

`--only chemistry-plain,printed-working` selects a focused development run. The provider and every inherited tier are pinned to
`MODEL_ID`; the report shows `vision_model` or `ocr_pipeline` for each case, so fallback is visible. This command always creates
a development report with a regression split. It cannot certify a release, an untested hardware class or a reference-device budget.
Every completed fixture writes `capture-checkpoint.json` atomically, plus bounded timing/reader metadata in
`capture-checkpoint.observations.jsonl`. Checkpoints remain explicitly invalid/incomplete; only the final run report can be gated.
Model metadata is collected before generation, and an unsupported optional quantisation summary is labelled unknown rather than
throwing away completed results. The hybrid Gemma GGUF header reader now retains per-layer KV-head counts for launch planning.

The model/runtime and OCR assets must already be installed; evaluation does not download models or switch on cloud reading.

Regenerate owned pictures with `.venv/bin/python -m jana_tools.perception_fixtures`. For a changed fixture or label, bump the
version in both that generator and `evals/suites.toml`, inspect the pictures and originals, then run
`.venv/bin/python -m jana_tools eval lock --write`. The fixture test verifies byte reproducibility and all hashes. The existing
held-out key and encrypted banks are not used for this development corpus.

## Ordinary-camera acceptance

The separate `printed/set.json` is supplied by the device lab. Each item needs a unique local photo basename and SHA-256,
`source` (`synthetic` or `licensed`, describing the question sheet), an approved `licence`, `acquisition: camera`, and an independent
`original` (at most 8,000 characters). The default minimum remains 200 photos; thresholds are unchanged. Links, traversal,
duplicate files, changed bytes, unbounded input and rendered smoke fixtures are refused before a model runtime starts.

```sh
.venv/bin/python -m jana_tools lab perception LLAMA_SERVER GGUF MMPROJ MODEL_ID high CAMERA_SET
```

This runner now uses the same complete capture path as the app, including privacy and quality checks and local OCR fallback.
The reader's decoder accepts the 0–1000 coordinate convention described in
[Google's image understanding documentation](https://ai.google.dev/gemma/docs/capabilities/vision/image), then converts it to
canonical 0–1 capture geometry. This conversion is deterministic; it does not certify that the model localized a region correctly.

Its results bind the manifest digest, hardware class and pipeline version to per-photo outcomes. The gate recomputes aggregates
and rejects duplicated outcomes or mismatched evidence. Camera data and the held-out release run must be collected and reviewed
on each reference class. For S2 and later, the release harness refuses regression-only perception evidence and requires the
`camera:low`, `camera:mid` and `camera:high` criteria from verified held-out camera results. A rendered corpus is never relabelled
as held-out evidence. Real device-lab capture results, release packaging/signing, ordinary-photo accuracy and latency remain open.
