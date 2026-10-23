# M21 capture development evidence — 2026-10-15

These runs use the owned, hash-locked **rendered regression** corpus, not ordinary-camera or held-out photographs.
No learner images or personal information are included. The model and projector were already installed locally;
weights are not copied into this repository. Reports retain their actual run timestamps.

| Run | Fixture assertions | Critical assertions | Exact transcription |
| --- | --- | --- | --- |
| [Native OCR baseline](ocr-baseline.md) | 172/180 | 154/154 | 15/22 |
| [Vision integration before final reader instructions](vision-integration.md) | 176/180 | 154/154 | 18/22 |
| [Final full vision run](vision-final.md) | 178/180 | 154/154 | 20/22 |

The 29 fixtures contain 22 exact-transcription cases and seven fixtures for other behavior. The aggregate assertion
rate is **not** transcription accuracy. Focused [corrections](vision-corrections.md) and [reader tightening](reader-tightening.md)
reuse corpus images; they are not independent evidence. Every genuine failed assertion remains in its JSON report.
Both final failures are an extra `x` on the name/contact-masked worksheets. Unknown or invented characters were not
silently removed to improve the score. Native fallback also fails several chemistry, geometry and fraction cases.

The pipeline invokes the actual CoreService, strict app events, sandboxed native privacy/quality processing, structured
vision reader and explicit confirmation gate. Reader paths and per-fixture timings are retained in observations files.
Interrupted checkpoints cannot pass the release gate. Camera evaluation validates rights, camera acquisition, unique
hashes and labels before inference; release mode cannot relabel these regressions as held-out evidence.

[inputs-deterministic.json](inputs-deterministic.json) binds the final reader code, fixture/eval locks, local runtime and
whole model/projector hashes. [inputs.json](inputs.json) records the earlier reader. Both record the specification pin
used during inference; the later specification progress-only commit does not change the capture contract. The local
Ollama model is development evidence without publisher release provenance. The M4 Max 128 GB host is not a reference
laptop; configured hardware-class labels do not establish class budgets. Runtime logs showed an image-token budget
reduction from 1120 to 512 with the current default batch setting. Batch/memory settings were not changed without
memory and latency measurements.

The broader core evaluation passed safety 306/306, prompt regression 60/60, memory 69/69 and scenarios 2/2, while seven
of 3,858 marking cases timed out during concurrent model load. Their isolated recheck is recorded separately in
[golden-timeout-recheck.json](golden-timeout-recheck.json); the original failed evaluation is not rewritten.

Open acceptance evidence: at least 200 appropriately licensed ordinary-camera photos on each required class, confidence
and crop geometry calibration, reference-device latency/memory/typing, Windows sandbox and supported webview cameras,
actual signed perception packs within the 60 MB budget and native source/licence review. D41 and M21 acceptance remain open.

After inference, a formatting-only signature wrap and the retryable working-checker API error mapping/test were added.
Those changes do not alter image reading. Isolated commit-source verification uses a separate locked offline environment,
so unrelated editable packages cannot mask a missing committed dependency. The original inference fingerprints are retained.

Final isolated M21/router/vision batch: **80 passed, one device-lab test skipped**. The additional checker-unavailable
regression is included. This verifies the proposed committed tree with cached locked dependencies and real workers.

Typing evidence: the working checkout passes the normal fresh strict mypy run (391 sources). The isolated commit passes
strict checks on the explicitly selected sources with `mypy --follow-imports=silent` (384 sources). A default isolated
run also reports existing errors in imported repository tooling outside that selected scope; those unrelated files
were not swept into this M21 commit. Functional test results above use the isolated environment without that overlay.
