# Jana checkpoint and agent handoff — 2026-10-19

The owner requested that feature work stop and all current changes be preserved on
`main` for another agent. This is a workspace checkpoint, not release approval.
The app checkpoint includes the existing desktop, Studio, client, contracts,
renderer, curriculum, evaluation, gateway, Study worker, packaging and governance
changes, including work outside M42. Their inclusion does not claim fresh
verification of every component.

## Repositories and how to resume

- App: `/Users/ijidailassa/projects/jana`, branch `main`. This repository has no
  configured remote at handoff. The commit containing this file is the local
  checkpoint; use `git log -1` and `git status --short` to inspect it.
- Private specifications: `docs/` is a separate, ignored Git repository. Its
  `main` was fast-forwarded from `d50132c` to
  `51a06852eae73d493f2ac24f2fbd3d214ef600c8`, preserving all 15 commits from
  `codex/palette-accessibility`. This matches the app's `spec.lock`. Its remote is
  `https://github.com/Jidayi/jana-spec.git`; local `main` is 68 commits ahead of
  the last fetched `origin/main`. No push was performed for this handoff.
- Keep the private specification out of the app repository (ARC-16). Do not
  force-push, reset, or weaken release gates to obtain a green checkpoint.
- Read `AGENTS.md` before resuming. Read the installed Turbo documentation before
  changing or invoking its commands. No new feature or paid model work was run
  during the Git checkpoint task.

Checkpoint verification covered repository state, the private-spec pin, merge
markers and common credential patterns. Reported credential assignments were
synthetic test fixtures. The staged whitespace check reports existing raw
evidence formatting and two trailing spaces in `deploy/staging/egress.sh`;
these are preserved rather than rewriting historical evidence or its hashes.
No full test suite was rerun for this preservation task.

Another session delivered additional mastery evaluation evidence while this
checkpoint was being committed. That late evidence is preserved in a follow-up
commit; its arrival is not a new qualification claim by this task. Check both
repositories' status before resuming, since other sessions share this checkout.

## Final mastery-to-tutor verification

The completed software run is recorded in
`scripts/governance/evidence/mastery-real-model-flow-2026-10-19/summary.json`.
Across all four installed subjects, mastery checks covering 359 knowledge components
marked 1,077 answers and unlocked the tutor; 47 of those checks were then handed to
the real model. The real local Gemma 4 12B run covered all 53 new questions
plus a Physics representative: 54 exchanges, 126 tutor turns and 54 saved boards
reopened, with no tool errors or degraded fallback in the retained passing cases.
`combined-cases.json` indexes those cases; `verification-attempts.json` preserves
the failed attempts, fixes and exclusions. Live learner grades were unchanged.

Recorded passing regression results are 179 mastery/tutor/safety/role tests, 12
numerical and unit tests, and 4,964 isolated source-oracle checks. The engine
regression run (`engine-final-regressions.log`) did **not** pass: it stopped at its
first failure, `test_m25b_numbers_and_answers.py::prd05_zero_unchecked_numbers[suites]`
(a stale `answer_oracles` suite lock), so the tests after its 110 passes never ran.
A re-run on 2026-10-19 after the lock refresh still fails the same test, now on
`itm.mth.o.coordinate_geometry.0061` (`chk_build_mth_crd_0061_ans` fails in the
math tool). That item is not one of the new questions. The cause was an order-dependent
SymPy assumptions cache in the tool worker's as-written parse, not the item content; it is
fixed in b45743a0 (`scripts/governance/evidence/oracle-0061-2026-10-19/NOTE.md`). The engine
suite has to be re-run in full before anyone claims it passes.
The numerical suite preceded the final percentage-working and numeric-input changes; their
later focused, pack-build and real-model coverage is detailed in `summary.json`.

After this evidence was recorded, the numeric-answer shortcut moved from the
input-guard role into the engine (`turn.py` `numeric_only`, `_guard_model(answer=)`).
It now covers U+2212 minus signs, fractions and the open part's own unit, accepts
ASCII digits only, and applies only to answer and board submissions. Its focused
tests and the safety suites pass. The real-model run above predates that revision.
The source manifest covers 24 changed or directly verified files, not an attested
release tree. Installed development packs were Accounting 1.1.1, Chemistry 1.0.2,
Mathematics 1.0.3 and Physics 1.0.3.

After this run, three of the new Mathematics items (coordinate_geometry.9010, trigonometry.9045 and .9050)
had phrases reworded because 8-word runs matched sealed `answer_oracles` held-out content (EVL-24); their
maths and answers are unchanged, the items are 0.1.1 and the pack is 1.0.4 (built and verified). The real-model
evidence above used their 0.1.0 wording.

Independent curriculum approval remains pending for 59 items (53 new questions
and six corrected Physics solutions), listed in `pending-curriculum-approval.json`.
Hardware acceptance, broad/held-out model qualification, production signing and
independent release review remain separate. This software result does not close
the M42 failures or release requirements below. The local app was last available
at `http://localhost:5180/`; its model adapter and launcher under `/private/tmp/`
are temporary local services, not portable setup or qualification artifacts.

## M42 status and next engineering work

Start with `services/cloud-gateway/deploy/M42-RELEASE-HANDOFF.md`,
`scripts/governance/m42-release-verification.json`, the selected
`scripts/governance/m42-curriculum-lock-release-checks.json`, and
`scripts/governance/m42-release-inputs.json`. M42 remains disabled by default;
`release_ready` is false and production has not been provisioned by this task.

Latest recorded checks, rather than a fresh run during this checkpoint:

- Curriculum lock `2026-10-19.2`: 4,964/4,964 answer oracles and 4/4 pack builds.
- M42 core/gateway: 174 passed, 12 expected live skips; release preparation:
  27 passed; build verification: 35 passed.
- Retained qualification for the identical gateway bundle: 117/117 full live
  corpus, 8/8 targeted, 12/12 Unicode and 6/6 upload-format checks. These results
  are from the previous live run, not a new execution of the checkpoint tree.
- Broader evaluation harness: 11 passed, two failed. Reproduce
  `evl01_full_harness_run` for `itm.mth.o.coordinate_geometry.0061`; it failed in
  that harness despite passing in the dedicated content run. Diagnose the cause
  before changing the oracle or execution budget.
- `evl24_no_held_out_leakage` flags three development questions/four matching
  fingerprints: coordinate geometry `.9010`, trigonometry `.9045` and `.9050`.
  Consult the corpus custodian and the preserved `heldout-collisions.json`.
  Do not open encrypted benchmarks, remove protected hashes, or weaken the guard.
- The offline build checker now uses a bounded 3,000 ms symbolic slice; the
  learner slice remains 800 ms. Unknown/timeout results still fail verification.

Evidence is in `scripts/governance/evidence/m42-curriculum-lock-2026-10-19/`.
Earlier failures and raw observations are retained. Do not relabel development
evidence as independent, production, or signed-device qualification. Some
historical source manifests describe earlier working trees; this checkpoint
does not rewrite them or claim their hashes describe all checkpoint contents.

## Staging, spending and sensitive material

- Staging project: `jana-staging-512005`; production project:
  `jana-prod-512005`.
- Gateway: `https://staging-api.getjana.app` (`35.214.70.189`), VM
  `jana-staging-gateway`, zone `europe-west2-a`. Last recorded VM state is
  `TERMINATED`; it was not started for this checkpoint.
- Normal daily guard: $2, last verified 2026-10-18T23:15 UTC. Monthly Vertex cap:
  $20, last confirmed CONFIGURED on 2026-10-19. Do not assume a freshly inspected
  host or increase caps without authorization. Project budget alerts are not a
  hard spend cap.
- Preserve five uncertain receipts/reservations. Last recorded known charges
  plus holds total $9.12355125 under the temporary $10 qualification ceiling.
  Do not reconcile or repeat uncertain requests without independent usage data.
- Qualified gateway SHA-256:
  `1297f31090f1b9539fd3e339429b4461b554c117769dfe04ed004cb50606eeb4`.
  Use Gemini 3.8 Flash with the exact approved EU Vertex endpoint and attached
  service identity; do not export provider keys.
- Operator credentials and temporary helpers remain outside Git under
  `/private/tmp/`. They are not portable handoff artifacts and may expire. Never
  commit credentials or read local provider-key files to reconstruct access.

## Inputs still required for release

The exact requirements and ownership are in `m42-release-inputs.json` and the
M42 release handoff. They include the production hostname/region/spending
decision and provisioning authorization; project-specific Google retention
evidence; actual approved DPIA/Safety lead records; production content/installer
signing and notarization; independent content/safety/local-model/OCR/ASR reviews
and 60 prompt snapshot reviews; and final signed-device checks.

Owner approval already exists; do not ask for generic approval again. The owner
has an Apple Silicon Mac for D01–D08 with VoiceOver. Additional Windows x64/NVDA
(including non-AVX2) and Ubuntu/Debian device coverage is required. See
`scripts/packaging/M42-DEVICE-CHECKS.md`. Engineering still owns the harness
failure, production configuration/hardening, measured costs, immutable
SBOM/licence/source-offer evidence, production pins and exact-artifact checks.
