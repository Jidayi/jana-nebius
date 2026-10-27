# Historical deployment preparation records

These records describe a separate deployment configuration and its observations. They are not the configuration of the Nebius demo. Use [README.md](README.md) for the current gateway setup.

# M42 production and signing preparation

This folder contains templates, not an approved deployment. M42 stays off by default. Owner approval is already at `scripts/governance/m42-owner-approval.json`; it does not replace measured records or cryptographic signatures.

The current owner/custodian inputs, production decisions and Apple Silicon test steps are in [M42-RELEASE-HANDOFF.md](M42-RELEASE-HANDOFF.md). Current verification is selected by `latest_checks` in `scripts/governance/m42-release-verification.json`; older reports remain historical evidence. Corpus v3 retains every original source/question, documents one probability expectation correction, and adds four contrasting cases. Its amendment still requires independent content review; no old refusal was rescored as a pass. Corpus v4 additionally makes the speed definition explicit in six Unicode positives and adds three undefined-symbol contrasts. The subsequent unchanged-corpus staging run passed 117/117, with 8/8 targeted conditional-question/citation regressions, 12/12 Unicode stress and 6/6 upload/extraction checks. The previous 115/117 report remains historical evidence. The curriculum-lock suites now use `2026-10-19.2` with matching hashes; independent review and production/signing/device gates remain open.

`m42-release-candidate.json` binds the available real repository inputs and completed development report; all missing deployment/reviewer/device values remain explicit. Its saved preflight is blocked. It is not a production deployment.

Copy `m42-production.toml.example` and `m42-release-manifest.example.json` into the operator's deployment folder. Supply the real HTTPS gateway origin, hosting environment/region, immutable image digest, public entitlement keys, secret-manager mount and content-key/HSM reference. Keep all secret values outside the checkout. The host must match the signed device policy's production gateway; install distinct base64 SPKI SHA-256 primary and backup pins. The checked-in `.invalid` hosts and empty pins deliberately cannot qualify.

The Linux service template uses no swap, no core dumps and tmpfs scratch. Verify these controls on the actual host/cgroup, including all descendants, rather than treating the unit file as evidence. Build the gateway from lock-pinned dependencies, retain its SBOM and the corresponding PyAV/FFmpeg build/source and licence material, and run the real sandbox under this service account. Keep unprivileged user namespaces available for `bwrap`; do not weaken the sandbox when a host disables them. Restrict provider egress at the host/proxy and disable reverse-proxy/APM body logging. API upload buffers/results remain process-local and disappear on restart; persistent receipts may contain metadata only. Provider uncertainty requires reconciliation, not automatic resend.

The Gemini paid API's no-training terms alone do not prove zero retention: verify abuse-monitoring/ZDR eligibility and the actual project configuration. Record project and provider confirmation references, verifier and expiry. Do not enable Files API, Interactions storage, explicit caches, session resumption or tool/Maps grounding for Study. The existing adapter sends inline generateContent requests. Sources: [Google ZDR](https://ai.google.dev/gemini-api/docs/zdr), [usage policies](https://ai.google.dev/gemini-api/docs/usage-policies). A changed endpoint/project/model needs a new scoped record.

Measure extraction costs on the chosen deployment and bind the measurements to configured page/minute charges. Introductory Gemini 3.8 Flash token prices expire on 2026-12-31; bound the price record's expiry accordingly and requalify before 2027-01-01. Other gateway tutor-model placeholder prices still need their own qualification if those routes ship. Do not relabel the engineering `.0001` defaults as measured prices.

Each `evidence` entry in the release manifest is `{ "path": "relative-or-absolute-file", "sha256": "actual-file-digest" }`. Required JSON records and their exact fields are read by `scripts/jana_tools/release/m42.py`:

- `provider_retention`: provider_endpoint, model, project_reference, paid_service, zero_data_retention_verified, request_logging_disabled, verified_by, provider_confirmation_reference, valid_until. Vertex additionally requires adapter=`vertex`, the exact project ID and location from the configured, validated Google publisher endpoint. A staging record cannot qualify production.
- `measured_costs`: configured `{page_usd, minute_usd, prices:{input,cached_input,output}}`, measurement_reference, reviewer, valid_until.
- `deployment_checks`: image_digest and measured true values for no_swap, core_dumps_disabled, temporary_memory_only, body_logs_disabled, sandbox_network_denied, secret_mount_outside_checkout, secret_mount_read_only, provider_egress_restricted, runtime_identity_least_privilege, linux_sandbox_smoke_passed.
- `native_distribution`: image_digest, sbom_sha256, source_build_offer_reference, licence_review_passed.
- `quality_corpus`: the exact versioned development corpus JSON.
- `quality`: complete full real-provider corpus report with exact corpus hash and all case observations. Vertex reports also bind provider_endpoint to the configured project/location. A partial rerun or a staging-project report cannot qualify production.
- `quality_review`: exact quality_sha256, reviewers, held_out_corpus_passed, local_reference_model_passed, content_review_passed, safety_review_passed, ocr_asr_review_passed. These are reviewer/measurement records, not flags to fill with true to make a tool pass.
- `devices`: completed report using `scripts/packaging/m42-device-report.example.json`; see the exact device actions in `M42-DEVICE-CHECKS.md` there.
- `gateway_config`, `network_policy`, `trust_anchors`, `dpia_list`: the actual files. Trust anchors contain public keys only; the signed list must explicitly name study_materials and verify under production release trust.

Run from the repository using its workspace Python environment (output files must not already exist):

```sh
PYTHONPATH=scripts .venv/bin/python -m jana_tools.release.m42 preflight \
  --manifest /operator/m42-release.json --report /operator/m42-preflight.json
```

A failed preflight lists missing/mismatched evidence and exits nonzero. It is an evidence consistency tool, not independent attestation. Inspect the report and all underlying records before enabling Study. Run the deployment smoke with a test entitlement after startup, then run the packaged client through that exact origin; an in-process staging test does not qualify deployed TLS, custody or hosting.

## Offline signing handoff

Use the approved assessment document and its actual `ops/governance-records#/$defs/dpia` record, including the responsible Safety lead's existing signing reference and document digest. Do not assign that role to the owner attestation or create an assessment from its approval text. M42's record gate is s3_launch and its feature is study_materials. The schema now accepts both; the device list contract is `ops/dpia-list`.

```sh
PYTHONPATH=scripts .venv/bin/python -m jana_tools.release.m42 prepare-signing \
  --records /operator/approved-dpia-records.json --documents /operator/assessments \
  --created-at ACTUAL-UTC-TIMESTAMP --out /operator/m42-signing-handoff
```

This validates records against the canonical contract and exact assessment bytes, then writes `dpia-list.unsigned.json`, the exact `dpia-list.canonical.json` bytes and `signing-request.json` with SHA-256 bindings. Existing output folders are refused. Transfer these reviewed files to the offline signing laptop under the existing `scripts/governance/evidence/KEY-CEREMONY.md` procedure. Use `signing_service.hierarchy.production_signer(content_certificate_id, hsm_command_argv, production_anchors(public_anchor_path)).sign("dpia_list", unsigned_payload)`; the HSM command reads canonical bytes on stdin and returns a base64 Ed25519 signature. Never copy a private key into the checkout, app or CI variables.

Verify the returned document before bundling:

```sh
PYTHONPATH=scripts .venv/bin/python -m jana_tools.release.m42 verify-return \
  --request /operator/m42-signing-handoff/signing-request.json \
  --unsigned /operator/m42-signing-handoff/dpia-list.unsigned.json \
  --signed /operator/dpia_list.json --anchors /operator/trust_anchors.json
```

The return check refuses changed payload bytes, wrong signing purpose, invalid/untrusted signatures and the development/test root in production. Bundle the verified list in `agent_core/net/dpia_list.json` and the actual release public anchors in `agent_core/config/trust_anchors.json`. Separately sign/notarise every packaged executable using the platform procedure; a DPIA content signature does not sign an installer. Bind final installer digests and the final configuration to the completed release report and re-run preflight.

## Unicode generation and remaining handoffs

Draft citations use request-local passage IDs. The gateway partitions each frozen source chunk into contiguous passages of at most 500 Unicode code points, resolves selected IDs to exact source/revision/ranges/quotes, then validates the unchanged canonical response and independently checks support and safety. The provider receives literal Unicode in JSON, avoiding copied escape sequences. Neither source text nor citation quotes are normalised. Invented or mixed reference fields are withheld; legacy canonical citations still require exact revision-bound text and unambiguous offset repair. Choice and non-choice quiz items use disjoint generation shapes, avoiding invented empty units fields. Generation preserves the source's scope, conditions, units and negation; a source-specific example cannot become a universal claim. The support pass checks entailment, including direct deductions without missing premises, and still rejects contradictions, outside facts and invented quantities. Verifier explanations stay in memory; only fixed validation-stage labels and the actual refusal HTTP status enter metadata. This is internal provider translation; it does not change client contracts or permit an unsupported claim. A fully observed, explicitly repairable drafting rejection can receive one source-grounded revision and a fresh full verification. Missing evidence, contradictions, unsafe material and unknown outcomes never trigger correction. The four-call upper bound is reserved before sending, combined actual usage settles once, and all calls share a 180-second deadline.

The production example now prepares the known `jana-prod-512005` project with the EU Vertex endpoint and attached identity. It remains deliberately incomplete: the production hostname, public entitlement hierarchy, provider retention confirmation, measured extraction charges and signing evidence must be supplied. No production resources are changed by editing it. Both global and EU introductory price records expire by 2026-12-31.

To finish release qualification, supply the approved assessment document plus its canonical Safety lead record, the production public trust hierarchy/content-key signing interface, and platform signing access. The local Mac identity inventory on 2026-10-18 reports zero valid code-signing identities. Run the existing offline signing handoff after those actual inputs are available; the owner's approval remains recorded and does not need repeating. Provider confirmation must cover abuse-monitoring retention for the exact production project, not just no-training terms or the staging cache setting.

On the owner's Apple Silicon Mac, execute D01-D08 from `scripts/packaging/M42-DEVICE-CHECKS.md` on the final signed package, including native VoiceOver, offline import/generation, OCR correction, recording boundaries, cancellation/consent, deletion/archive recovery and audio. Windows 10/11 x64 (including non-AVX2) with NVDA, Ubuntu 22.04+ and Debian 12 x64 require their own testers. Independently reviewed held-out content/safety and local-model/OCR/ASR measurements remain separate from this synthetic engineering corpus.

## Jana staging (2026-10-18)

The actual staging inventory, budgets, controls and live observations are bound in `scripts/governance/m42-staging-deployment.json`. Production is separate. Staging uses `jana-staging-512005`, a London `e2-medium` VM with an attached prediction-only identity, Secret Manager and an isolated VPC. The runtime cannot access the synthetic licence issuer or backup TLS key. Gemini 3.8 Flash runs through the EU multi-region Vertex endpoint; the optional project cache is disabled. This does not certify abuse-monitoring retention for learner data: qualification uses synthetic content only.

`staging/` contains the measured host configuration and operator helpers. Ubuntu's user-namespace restriction stays enabled; the scoped AppArmor profile permits bwrap's setup, and bwrap's required `--disable-userns` option denies nested user namespaces in its child. `AF_NETLINK` is necessary for bwrap's private loopback setup. Scratch tmpfs mounts must specify `mode=1777`; do not combine them with `PrivateTmp`, which was measured to replace them with disk-backed bind mounts. The unit disables swap and core dumps, keeps code read-only and mounts the admin credential read-only outside the checkout. Provider egress permits only the resolved EU Google endpoint and metadata credential service. Multi-region endpoints do not support the Private Google Access VIP; production should qualify Private Service Connect rather than copy a VIP override.

The VM stops four hours after each start. The $2 UTC-day Study limit accounts for all devices and unresolved reservations. The $20 monthly Vertex service cap is enforced by Cloud Billing with reporting latency; the $60 project budget sends alerts at 50%, 80% and 100% and is not a project-wide hard cap. Persistent disk, reserved IPv4 and secrets continue to cost money while the VM is stopped. The attached IPv4 currently costs $0.005/hour (about $3.65 for 730 hours); review the current price before keeping an idle staging environment indefinitely.

The reserved staging address is `35.214.70.189`. The owner added its A record in Squarespace, and `https://staging-api.getjana.app` now serves a publicly trusted certificate. The activation helper requires DNS to resolve exclusively to this address and successful ACME verification. `staging/activate-public.py` must run after active test requests finish, because it changes the authentication audience and restarts the gateway. Publish a new hash-addressed bundle/config and record the final audience, certificate SPKI, origin checks and bundle manifest after activation. Keep the existing website DNS records intact. The private tunnel certificate and the synthetic entitlement are not public/release trust anchors. `staging/device-policy.json` contains the measured public gateway SPKI and a separate backup pin for staging-only client builds; it leaves all release approval gates in place. The public certificate renews through Certbot; the VM must be running for its renewal timer to execute.

For private operator checks, start an IAP SSH forward (always specify the project and account):

```sh
gcloud compute ssh jana-staging-gateway --project=jana-staging-512005 \
  --zone=europe-west2-a --account=ijidai@ruhu.ai --tunnel-through-iap \
  -- -N -L 18443:127.0.0.1:8443 -o ExitOnForwardFailure=yes
```

Use `test_m42_deployed.py` only with explicit `JANA_M42_DEPLOYED=1`, `JANA_STAGING_ORIGIN`, `JANA_STAGING_AUDIENCE`, `JANA_STAGING_CA` (the exact private certificate for tunnel checks) and `JANA_STAGING_ENTITLEMENT` (a fresh short-lived synthetic entitlement). Keep operator files outside Git with mode 0600. Set a new, non-existent `JANA_M42_QUALITY_REPORT` for a corpus run or `JANA_M42_UPLOAD_REPORT` for `-k uploads`. Never overwrite a previous live observation, silently resend an uncertain request, relax TLS verification or substitute the test/release licence hierarchy. Public-origin checks must use the system CA store and the public authentication audience. The current corpus remains a development corpus, not an independently reviewed held-out set.

References: [Vertex endpoints](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/locations), [Vertex retention/cache controls](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention), [Cloud Billing service spend caps](https://docs.cloud.google.com/billing/docs/how-to/budgets-spend-caps), [IPv4 pricing](https://cloud.google.com/vpc/network-pricing), [Ubuntu AppArmor](https://documentation.ubuntu.com/security/security-features/privilege-restriction/apparmor/).

The final public configuration uses the documented **non-global EU** introductory Vertex prices: $0.825 input, $0.0825 cached input and $4.125 output per million tokens through 2026-12-31. Earlier synthetic run receipts were corrected once by `staging/reprice-synthetic.py`, with the raw reports retained. Do not reuse this staging-only amendment on production or rerun it under a different revision. The authorised qualification runs used a timed daily override of at most $10 while retaining uncertain reservations; the normal $2 cap must be restored and measured afterward. The owner-approved monthly Vertex service cap is now $20; it does not cap infrastructure charges.

To produce a reviewable source bundle, export the cloud-gateway dependency closure from `uv.lock` with hashes and no workspace/editable entries, then run `staging/build-bundle.py` using the workspace Python, the public-only staging TOML, public certificate and that requirements file. Its allowlist excludes environment, Git, operator and credential files. Two identical inputs yield the same tarball SHA-256. Upload under `gateway/<sha256>.tar.gz` in the private deployment bucket, update only this staging VM's `jana-bundle-sha256` metadata and run `staging/apply-bundle.py` over IAP after active requests finish. Collect `staging/host-checks.py` and rerun the deployed checks. Never replace a previous observation with a later result.
