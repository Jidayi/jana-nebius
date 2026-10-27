# M42 quality and acceptance corpus

`m42-quality.json` freezes the synthetic development corpus: every aid type across Biology, Chemistry, Maths, Physics, Accounting and a non-syllabus topic; Unicode; absent answers; conflicting material; source injection; and personal-data minimisation. The real-provider runner creates genuine SQLite source revisions, sends them through the authenticated gateway to its configured Study model, validates exact citations and committed cards/quiz keys, checks private student views, observes usage/cleanup and scans gateway files for source-body persistence. It does not replace independent content/safety review, native assistive technology or local model measurements. The run history below describes the candidates actually tested; those results do not qualify a different model. Current Nebius demo verification is recorded in [FEATURE_IMPORT.md](../../FEATURE_IMPORT.md).

Run the provider test with the existing owner-authorised developer secret source, never credentials in a command or test report:

```sh
JANA_M42_QUALITY_LIVE=1 JANA_M42_QUALITY_REPORT=/operator/m42-quality.json \
  .venv/bin/pytest -q -s services/cloud-gateway/tests/test_m42_quality_corpus.py
```

The runner allows at most two simultaneous synthetic requests and a USD 2 conservative spend ceiling, including uncertain holds. `JANA_M42_QUALITY_CASE=<id>` is a diagnostic subset and cannot qualify the complete corpus. `JANA_M42_QUALITY_TRACE=1` records synthetic provider replies for diagnosis; never use that mechanism for learner data. Results checkpoint after every case. Failures are retained and not automatically retried. The quality report includes the corpus SHA-256. A model, prompt, runtime, corpus or policy change needs new evidence; do not relabel a previous model's result.

The first full run produced **108/110** passing cases: probability chat and Unicode notes were safely withheld. Both passed single-case diagnostic reruns, which do not erase the original failures. One full diagnostic repeat captures synthetic replies to separate generation/support refusals from flawed evaluation checks. For example, an osmosis answer saying “does not require metabolic energy” is a correct answer to that question even if it omits the words “water” and “osmosis”; an overly narrow keyword check must be recorded as an oracle defect, not weakened support policy. Preserve original reports alongside any reviewed rescoring.

Separate deterministic/codec and protocol corpora:

- `services/agent-core/tests/test_m42_format_corpus.py`: real sandbox DOCX/ODT/PPTX/ODP/text/Unicode, slide speaker notes and linked-resource isolation; macro/entity/archive-bomb rejection; PDF page and text-unit boundaries.
- `services/agent-core/tests/test_m42_safety_corpus.py`: twelve real API requests for distress, harm, medical/legal, cheating, personal details and non-study browsing; exact templates, no job/model and no mastery change.
- `test_study_workspace.py`, `test_m42_extended.py`, `test_m42_archive.py`, `test_m42_checkout.py`: revisions, private grants, OCR raster/partial confirmation, marking, restart, consent, archive and erasure. Scripted OCR/model responses prove protocol behaviour, not OCR or model accuracy.
- `services/cloud-gateway/tests/test_m42_study.py`, `test_m42_recordings.py`, `test_m42_reconcile.py`: real document/media sandbox, timestamp uncertainty, custody, replay/holds/settlement and cleanup.
- `scripts/tests/test_m42_release_preparation.py`: assessment/contract compatibility, canonical signing handoff, returned-signature trust and production preflight tamper/expiry checks.
- `scripts/ci/browser-m42-gallery.mjs`: every Study state, light/dark, 320/800/1366 px, 100%/200% text; Axe, clipping, overlap and overflow. Use a fresh isolated benchmark build. Native NVDA/VoiceOver checks remain separate.

`m42-acceptance.json` maps **all 41 canonical M42 acceptance names** to concrete checks and remaining device/model/reviewer evidence. It deliberately does not declare a canonical acceptance passed merely because a narrower unit test passed. No requirement is removed.

For release, obtain the independently held-out corpus through the existing EVL-18 custodian/key procedure. Review exact source-to-claim entailment, arithmetic, question quality/unique keys, the guided-work distinction, unsafe operational transformations vs safe academic material, PII/injection and OCR/ASR uncertainty on every eligible local candidate and the cloud candidate. Keep reviewer identity, corpus/candidate/output digests and failures. A self-authored public development corpus cannot become independently held-out by changing its label. Production preflight requires that separate evidence and refuses a partial or failed development report.

The completed diagnostic repeat had 109/110 raw passes; its only failure was that osmosis keyword oracle.
The narrowly scoped `jana_tools.release.m42_quality` reassessment validates the unchanged sources/requests,
exact citation and independent support verdict, changes only that documented oracle, and yields 110/110.
The raw 109/110 report and first 108/110 run remain in the evidence folder. This is rescoring the same observed
responses, not claiming a new model run or independent review. The reassessment refuses to turn a model 422
refusal into a pass or accept any unrelated corpus change. Its boundary has regression coverage.
