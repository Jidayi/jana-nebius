Acceptance-test coverage for M23

| Work package | Requirement | Priority | Tests |
| --- | --- | --- | --- |
| M23.a | OBS-13 | must | `obs13_metrics_match_reference` → pass |
| M23.a | OBS-20 | must | `obs20_telemetry_schema_allow_list` → pass<br>`obs20_offline_backlog_bounded` → pass |
| M23.a | OBS-21 | should |  |
| M23.a | PRD-18 | must | `prd18_north_star_with_guardrails` → pass |
| M23.a | PRD-19 | must | `prd19_telemetry_schema_no_pii` → pass<br>`prd19_small_cohort_suppressed` → pass |
| M23.a | PRV-09 | must | `prv09_telemetry_allowlist` → pass<br>`prv09_crash_redaction` → pass |
| M23.a | BIZ-12 | must | `biz12_metrics_report_complete` → pass |
| M23.a | MEM-26 | must | `mem26_no_memory_in_analytics` → pass |
| M23.b | PRV-07 | must | `prv07_counsel_review_recorded` → pass |
| M23.b | PRV-21 | must | `prv21_tabletop_recorded` → pass<br>`prv21_safety_config_disables_feature` → pass |
| M23.b | PRV-22 | must | `prv22_report_local_only` → pass |
| M23.b | PRV-23 | must | `prv23_redteam_before_gate` → pass |
| M23.b | SEC-25 | must | `sec25_release_blocked_on_security_tests` → pass |
| M23.b | SEC-26 | must | `sec26_security_release_reaches_offline_channels` → pass |
| M23.b | UXS-44 | must | `uxs44_report_on_every_reply` → missing<br>`uxs44_report_stays_local` → pass |
| M23.c | EVL-22 | must | `evl22_protocol_registered` → pass<br>`evl22_dataset_deidentified` → pass |
| M23.c | BIZ-13 | must | `biz13_wtp_evidence_linked` → pass |
| M23.c | BIZ-14 | must | `biz14_experiments_registered` → pass |
| M23.c | BIZ-15 | must | `biz15_pilot_protocol_complete` → pass |
| M23.c | BIZ-16 | must | `biz16_non_consented_excluded` → pass |
| M23.c | PRD-08 | should |  |
| M23.d | TRN-01 | must | `trn01_run_requires_approved_record` → pass<br>`trn01_margins_frozen_after_first_run` → pass |
| M23.d | TRN-02 | must | `trn02_ladder_evidence_complete` → pass |
| M23.d | TRN-07 | must | `trn07_source_allowlist` → pass |
| M23.d | TRN-08 | must | `trn08_builder_refuses_student_artefacts` → pass<br>`trn08_canary_absent_from_shards` → pass<br>`trn08_no_training_egress_path` → pass |
| M23.e | PRD-22 | must | `prd22_pilot_checklist_gate` → pass |

26 requirements, 33 named tests: 1 missing, 32 pass
