# S2 evaluation and prompt evidence

`python -m jana_tools release stage S2 --report report.json --s2-evidence dossier.json` computes the S2 column of
TABLE EVL-17a, including inherited S1 rows. Every missing, malformed, stale, undersized or failing measurement
blocks release. The candidate must be the checkout's HEAD. S3-S5 also retain an explicit unimplemented-gates block;
these changes do not claim later-stage acceptance. Existing PRD-11 acceptance/decision checks remain in force.

The S2 rows of TABLE PRD-17a are computed too: the three release-gate rows (final answer, guided withholding,
critical safety) per reference class from the same dossier's reports, and the five pilot rows from
`--pilot-evidence pilot.json` (the `pilot_exit` governance record: aggregates only). `--pilot` tags a closed pilot
(PRD-11): the pilot rows are reported as pending instead of blocking, every decision blocking `pilot_start` must
be decided as well, and the tag must say `pilot`.

`release gate <gate> --evidence gate.json [--field-evidence index.json]` checks any other gate of the decisions
register (`pilot_start`, `cloud_tier`, `paid_launch`, `voice_launch`, `web_launch`, `mobile_launch`, `fine_tune`):
its undecided decisions and the evidence the specification names for it (the `gate_evidence` record; see
`release/gates.py`). `release dpia-list --records DIR --created-at T --out F` writes the unsigned PRV-08 DPIA list
from the Safety lead's signed `dpia` records, for the offline signing laptop to sign with the content key.
`release pins --release` also lists the `.invalid` hosts and empty pins of `agent_core/net/policy.json`, the empty
content safety reviewer list and the safety-resources placeholders.

The dossier is a version-1 JSON object with:

- `candidate`: full evaluated commit ID; `reports`: EVL-23 release reports for low, mid, high and content-only.
  Every run needs a unique ID, the current frozen suite version/hash, held-out evidence, disabled networking,
  zero egress and no eval-only product paths. Existing schema fields and Wilson intervals remain on each result.
- `minimums`: positive sample-size policy keyed by `suite.criterion`, registered in
  `minimums_registered_at` before any run. No sample-size decision is invented by this code. The ordinary-camera
  floor remains at least the configured 200 photos; device runs retain configured warm-up and timed sample counts.
- `judges`: two distinct IDs for each of `pedagogy_rubric` and `teacher_review`. Their criteria are reported
  separately as `<criterion>:<judge>`. A passing pooled score cannot hide a failing judge or hardware class.
- `devices`: raw EVL-14 device runs (`hardware_class`, `candidate`, `network`, `egress_attempts`,
  `all_gates_enabled`, and `runs` arrays for `first_text_s`, `restatement_s`, `step_s`). Medians are recomputed.
- `network_cuts`: separate online EVL-23 reports, with `scenarios.network_cut` counts for each reference class.
- `mastery`: candidate-bound per-subject held-out synthetic-log measurements (`ece`, `ready_to_check` counts,
  `model` (the model the subject's pack runs: `pfa_elo`, D25), `parameter_replay_no_worse`, `held_out`, `log_kind`).
  D25 must also be decided. The BKT comparison of LRN-11 is a post-pilot study and gates no release.
- `bakeoff_record`: the candidate-bound, reproducible record described in `evals/bakeoff/README.md`; D6 must be
  decided. Schema parse rates are supplied for every role under `bakeoff.structured_first_pass:<role>`.
- `previous`: previous EVL-23 release report when one exists, for the existing held-out regression rule.

The rate/count criteria are listed in `evaluation.MEASURES`. Perception uses `camera_exact` and
`accepted_regions_exact`. These are ordinary-camera release measurements, not the rendered capture regression.
Additional external suites (including teacher review, content-only and bake-off) must be frozen and their report
producers must emit the documented criteria before their rows can pass. This implementation does not fabricate
those reports or silently relabel development fixtures as device evidence.

`release bakeoff-record` wraps the existing EVL-15 ranking computation with its raw input hash, frozen lock, prompt
files and candidate; validation recomputes the report from those inputs. No bake-off outcome or model decision is
recorded by the implementation tests.

`release prompt-record --candidate <commit> --run-id <id> --date <UTC timestamp> --report <EVL-23 report> ...`
appends a PRM-23 version-2 record to `evals/prompt-runs.jsonl` (override with `--out`). It verifies that the commit
contains the exact prompt bytes, including nested auxiliary role manifests, and requires actual passing behaviour,
leak and persona measurements. Release revalidates that evidence and refuses unchanged file versions or multiple
prompt-file changes in a tuning revision. The older `record_run` outcome-only helper is retained for local tuning
history; its records cannot authorize a production release.

Real model bake-offs, teacher reviews, camera/device measurements and the unresolved minimum sample-size policy
remain release evidence to collect, not results established by the synthetic regression tests.

## M24 operations

Checklists that write the `JANA_M24_EVIDENCE` records, with a refused dry-run mode, are in
`scripts/governance/evidence/README.md` (`uv run python -m jana_tools evidence drill <drill>`).

`python -m jana_tools release ops` adds offline policy and record checks. It does not publish, dispatch kits,
contact schools or claim that an exercise occurred. Numeric policies are named `ops_*` settings in
`agent_core/config/keys.py`.

- `validate --kind <kind> --input record.json` checks bandwidth, lifecycle, weekly, incident, drills, SLO, docs,
  page or USB records. Bandwidth inputs contain hash-verified transfer files and transmission counts; missing
  reference flows need an explicit exception. The CLI does not derive successful measurements from policy limits.
- `promote --input dossier.json` requires a candidate, freeze calendar, release notes, data-policy comparison,
  signoffs and gate references. Each gate reference has a path, SHA-256 and reviewer. The referenced JSON contains
  its gate name, candidate SHA-256, strict boolean result and measurement timestamp. Missing evidence blocks it.
- `monitor --state state.json --input health.json --once` persists the ring and offers together. Without `--once`
  it polls the health source. Stale or failed health halts offers and kit production; resumption requires an
  explicit reason through the monitor API. Deployment must connect the health producer and publication consumer.
- `gateway-config` exports gateway policy from the central configuration. Deployment supplies qualified provider
  choices and synthetic probes; merely exporting the policy does not establish qualification.
- `runbooks` prints the offline drill catalogue and required drill names. A runbook is not an execution record.

Device policy accepts independently signed matrix and safety files through pack/update imports or the local
catalogue API. Incoming files use current trust and revocations. Previously accepted, restrictive safety records
continue to apply after signing-key revocation; dropping them could re-enable a disabled capability. Future
incoming records signed by that key remain refused. Restriction application occurs at a turn boundary, and the
Help API exposes active and pending sequence numbers. Permanent retired item IDs are shared across channels.

`OperationsPublisher` requires a deployment-owned gate callback before signing. `build_kit` verifies staged files
and requires an injected signer. Neither permits a caller's unsigned assertion to replace the release process.
`HotfixStore.execute_remark` requires the existing marker/replay adapter; it does not mutate protected learner
stores. `BundleVault` encrypts metadata bundles and audits ticket-scoped access; support deployment owns key
custody and authentication. Conversation export remains in the existing explicit-consent flow.

The specification adopted this milestone's contract proposals as D92: `ops/safety-configuration`, `ops/support-bundle`,
`ops/field-evidence`, `ops/probe-record`, `ops/cloud-switch`, the update manifest's embedded matrix and safety
configuration, and `HelpReply`, `SettingsSections`, `CatalogueImport` and `CatalogueImportReply` with their
endpoints in `api/commands` (proposed as a separate `api/operations` file). The code validates against the bundled
contracts and uses their generated bindings. The OPS-06 red-team row reads PRV-23's `redteam_max_age_days`.

Nineteen exact acceptance names need field evidence. With no `JANA_M24_EVIDENCE`, they skip visibly. To run them,
set that variable to an evidence index matching the proposed `ops/field-evidence` contract. Bind it to the checkout
HEAD and `spec.lock`, declare synthetic data only, and include a reviewer and the correct source per test. The
first proof is a `ops/probe-record` JSON document; supplemental proofs contain the raw observations. Paths must
stay inside the evidence directory and every SHA-256 is checked. The reader checks report identity, timing and
required observations. It cannot authenticate that a human actually performed an exercise: release reviewers
must inspect and approve the raw evidence. Parser unit fixtures never count as field acceptance.

See `M24-STATUS.json` for each requirement, remaining owners and validation. UI rendering, physical installs,
protected learner replay, deployment probes and staff exercises remain explicit acceptance work.
