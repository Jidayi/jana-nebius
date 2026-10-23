# M23 implementation and integration handoff

Branch: `codex/m23-safety`, based on main at `a83d5bc2`. All work is in the isolated M23 worktree.
No private specification changes, main-checkout commits, merges, pushes, downloads, paid model calls or real
student records were made. The private `docs` checkout is linked for reading only.

## Coverage

The initial `coverage M23` run found **26 requirements and 33 named tests, all 33 missing**. This differs from the
24-of-27 estimate in the task. The implementation covers **32 passing named tests and one missing UI test**,
`uxs44_report_on_every_reply`. Synthetic regressions also exercise failures and boundaries outside the named tests.
This is implementation coverage, not permission to start a pilot or publish a release.

## Requirement status

“Done” below means the code and synthetic acceptance check are implemented. Evidence supplied by a person is
listed separately; the code never substitutes its fixtures for that evidence.

| Requirement | Code and acceptance check | Work left / owner |
| --- | --- | --- |
| OBS-13 | Done: `obs13_metrics_match_reference`; runtime-shaped traces, local log observations, dimensional summaries and tool quantiles | Reference-device measurements: Evaluation lead |
| OBS-20 | Done: `obs20_telemetry_schema_allow_list`, `obs20_offline_backlog_bounded`; durable daily aggregates, withdrawal purge, bounded merge, schema endpoint and final egress validation | Display the schema in Settings: UI builder |
| OBS-21 | Done: technical JSON dashboard with evaluation fingerprints, model hashes and version report shares; regression tests in `test_m23_programme.py` | Optional visual presentation: UI builder; version shares count reports, not identified devices |
| PRD-18 | Done: `prd18_north_star_with_guardrails`; candidate-bound report and release check | Set `product_bottom_out_share_max` from an approved policy and collect real evidence: Product and Evaluation leads. Missing policy blocks release |
| PRD-19 | Done: `prd19_telemetry_schema_no_pii`, `prd19_small_cohort_suppressed` | None in this core slice |
| PRV-09 | Done: `prv09_telemetry_allowlist`, `prv09_crash_redaction`; existing opt-in crash flow retained | Notice/schema presentation: UI builder |
| BIZ-12 | Done: `biz12_metrics_report_complete`; all catalogue entries have windows, sources, sample sizes and explicit missing/suppressed states | Supply billing, finance, support and study aggregates: Product/Finance leads |
| MEM-26 | Done: `mem26_no_memory_in_analytics`; exports project structured evidence and omit memory events/content | None in this core slice |
| PRV-07 | Done: `prv07_counsel_review_recorded`; checked country-specific counsel record and blocking gate | Actual findings, counsel review and D13 resolution: Safety lead/counsel |
| PRV-21 | Done: `prv21_tabletop_recorded`, `prv21_safety_config_disables_feature`; signed USB restrictions are adopted monotonically and enforced at turn boundaries | Real exercise: Safety lead. This slice enforces `online_feature`; the other OPS-11 targets, their installed-version feed and other propagation channels belong to M24/Operations |
| PRV-22 | Done: `prv22_report_local_only`; selected reports leave only through an explicit authorized diagnostic export | None in the API slice |
| PRV-23 | Done: `prv23_redteam_before_gate`; dated candidate/stage evidence, offered-language coverage and regression references checked | Run the red team/privacy audit and provide review evidence: Safety lead |
| SEC-25 | Done: `sec25_release_blocked_on_security_tests`; test inventory, per-target fuzz effort, OS coverage and open findings checked | Actual security jobs and external assessment: Security lead. M24 must consume the same release check before signing/distribution |
| SEC-26 | Done: `sec26_security_release_reaches_offline_channels`; local offline-pack copy and notification manifest | Publish the real security contact/policy, validate/sign the supplied update pack and dispatch notices/USB media: Security and Operations leads. No notification is sent by this code |
| UXS-44 | API done: `uxs44_report_stays_local`; authorization checked when reports are exported | `uxs44_report_on_every_reply` is deliberately missing: report menus, keyboard access and sheet are UI-builder work in protected paths |
| EVL-22 | Done: `evl22_protocol_registered`, `evl22_dataset_deidentified`; chronology and frozen script hash checked; a signed pilot receipt is required for pilot profiles | Real protocol, power calculation, registration and study operation: Evaluation/Product leads |
| BIZ-13 | Done: `biz13_wtp_evidence_linked`; segment sizes, methods, comparisons and D10 evidence link checked | Conduct research and decide D10: Product lead |
| BIZ-14 | Done: `biz14_experiments_registered`; adult-only pricing register, identical learning build, currency and renewal rules checked | Fill and operate the real register: Product lead |
| BIZ-15 | Done: `biz15_pilot_protocol_complete`; protocol fields and pre-baseline registration checked | Choose schools, support arrangements and commercial criteria: Product lead |
| BIZ-16 | Done: `biz16_non_consented_excluded`; opt-in cohort projection plus API assent/study-host checks; export approval receipt is audited | Operate the study's secure storage and end-of-analysis deletion under the declared retention policy: study custodian/Product lead |
| PRD-08 | Done in the register/API slice: separate parent and school-owner research segments, student assent and supported-country protocol | Recruit representative participants and buyers: Product lead |
| TRN-01 | Done: `trn01_run_requires_approved_record`, `trn01_margins_frozen_after_first_run`; authorization produces a hashed run receipt and frozen margins | Real justification and three approvals: Engine/Evaluation/Safety leads. Actual training/model-card integration remains M40; no training is launched here |
| TRN-02 | Done: `trn02_ladder_evidence_complete`; consecutive candidate evidence and each attempted/accepted-skipped rung checked | Genuine release-report/revision evidence: Engine/Evaluation leads |
| TRN-07 | Done: `trn07_source_allowlist`; explicit development inputs, licences and source-specific conditions checked | Record genuine provenance and licence reviews: Curriculum lead |
| TRN-08 | Done: `trn08_builder_refuses_student_artefacts`, `trn08_canary_absent_from_shards`, `trn08_no_training_egress_path` | None in the S2 default-data gate; existing later-stage consent definitions are not exposed as shipped S2 scopes |
| PRD-22 | Done: `prd22_pilot_checklist_gate`; pilot API requires a content-signed complete country record and registered-protocol clearance | Actual country configuration, locale/resources/legal/support evidence and signing: Product/Curriculum/Safety leads. The pilot shell/build must supply `control.config.pilot_country_file` (adopted, D92): Platform lead |

## Record formats and contracts

The specification adopted this milestone's contract proposals as D92: `trace/telemetry` (served by
`GET /v1/telemetry/schema`), `ops/governance-records` (proposed as `ops/m23-records`), `ops/pilot-country`,
`ops/safety-configuration` (one contract with M24's entry rules), `CreateExport.research_approval` with its
conditional, and `control.config.pilot_country_file`. The code validates against the bundled contracts; there are no
local schema copies. Governance records are selected by `$defs` name (`release`, `counsel`, `tabletop`, `redteam`,
`security`, `protocol`, `wtp`, `experiment`, `justification`).

Country configurations and safety updates use the existing Content-key hierarchy. Development signatures are
accepted only by environments that already trust the test root. No release private keys were generated or used.
The pilot clearance must be inside the signed country configuration; its analysis hash and registration dates are
checked. An owner approval reference is still required before that configuration can be signed.

## Local commands

The owner's fill-in templates, per-record checks and drill checklists for this evidence are in
[../evidence/README.md](../evidence/README.md) (`uv run python -m jana_tools evidence ...`).

All commands below are local tooling; no command sends a support report, notifies a person, starts a study or
launches a training process.

```sh
uv run python -m jana_tools m23 release-check --evidence release.json --candidate COMMIT --stage S2 --gate pilot_start
uv run python -m jana_tools m23 pilot-start-check --evidence programme.json --candidate COMMIT --stage S2
uv run python -m jana_tools m23 metrics-catalogue --input local-observations.json
uv run python -m jana_tools m23 dashboard --input technical-reports.json
uv run python -m jana_tools m23 product-report --input weekly.json --policy product-policy.json
uv run python -m jana_tools m23 business-report --input monthly.json
uv run python -m jana_tools m23 training-authorize --input run.json --records justifications.json --out run-receipts --date UTC_TIMESTAMP
uv run python -m jana_tools m23 dataset-build --input authored-development.jsonl --out new-dataset-directory
uv run python -m jana_tools m23 security-release --update-pack signed-update.janaupdate --version VERSION --contacts registered-contact-refs.json --out new-runbook-directory
```

`programme.json` contains `country`, `protocol`, `wtp`, `experiments` and `release`. `pilot-start-check` validates
cross-record country consistency and the release evidence, then emits protocol-clearance fields. The Product lead
adds the approval reference and has the country configuration signed through the existing signing service.

The existing `release stage S2` command additionally requires `--m23-evidence`, `--product-metrics` and
`--product-policy`; it blocks absent, stale or candidate-mismatched evidence and breached product guardrails.
The UI needs to collect `research_approval` (`student_assent`, `school_approval_ref`, `protocol_ref`) for research
exports. The core accepts the proposed field before contract adoption and also handles its adopted schema.

## Release acceptance still left

The lead must reconcile the pre-existing spec checkout/pin mismatch: the observed private spec HEAD was
`fd79220c8d5018f9f50a3adcc6d93f3c312474aa`, while this branch pins
`bdc48140afa029266bb7811e1a74d80f1d5c31fe` in `spec.lock`. Neither was changed. The normal repository check therefore
cannot pass until the lead reconciles the intended spec revision. A signed M23 acceptance record in the private
specification also remains the lead's responsibility.

Pilot deployment: a shell-supplied `control.config.pilot_country_file` selects the pilot environment, its signing roots,
network policy and profile gate. The field is part of the control contract (1.3, D92); other unknown control fields
remain rejected. The desktop UI and shell producer are not changed in this slice.

## Validation results

- New M23 checks and affected regressions: **192 passed** (`/private/tmp/jana-m23-complete.xml`).
- Real sidecar/control-channel startup smoke checks: **2 passed** (`/private/tmp/jana-m23-sidecar.xml`).
- `uv run ruff check`: passed; `uv run ruff format --check`: passed.
- `uv run mypy`: passed (427 source files). Additional core/tooling mypy run: passed (335 source files).
- `uv run lint-imports`: 31 contracts kept, none broken.
- `uv run python -m jana_tools`: only `spec-lock` failed with the pre-existing mismatch recorded above; every
  other check passed. The pinned Node path and offline frozen pnpm installation were used.
- Coverage details: [coverage.md](coverage.md). Baseline: 33 missing. Final: 32 pass, one UI test missing.

The failing-first runs are preserved outside the repository under `/private/tmp/jana-m23-*.txt`; their fixtures
and real assertions are committed with this branch. No acceptance signature or real study/security outcome is claimed.
