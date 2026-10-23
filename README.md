# Jana

An offline-first secondary school sciences tutor for Mathematics, Physics, Chemistry, Biology and Accounting.
This monorepo contains the local tutor, checking worker, desktop shell, curriculum tooling and S2 implementations.
Desktop installation controls and typed input are being integrated. This fork preserves the original implementation; passing development tests does not constitute release acceptance.

## Layout

| Path | Holds |
| --- | --- |
| `apps/desktop/` | Desktop app: `src-tauri/` (Rust shell) and `src/` (React entry) |
| `apps/prototype-s0/` | The S0 prototype, frozen and excluded from releases |
| `packages/` | `ui`, `client-core`, `renderers`, `contracts-ts` (generated), `i18n` |
| `services/` | `agent-core`, `tool-worker`, `perception-worker`, `pack-builder` and, later, online services |
| `content/`, `skills/` | Authored agent content, curriculum sources and skills |
| `evals/` | Evaluation suites, fixtures and contract corpora |
| `scripts/` | Repository tooling (`jana_tools`), git hooks and CI scripts |
| `docs/` | Private specification; deliberately absent from this hackathon copy |

An unknown directory fails the layout check. Every package declares its layer in its manifest
(`jana` in `package.json`, `[tool.jana]` in `pyproject.toml`, `[package.metadata.jana]` in `Cargo.toml`).

## Hackathon copy

This is a fresh source copy of Jana for the Nebius × NVIDIA Global AI Hackathon. The original desktop app,
shared UI, themes, navigation, feature implementations and authored curriculum are preserved. The separate
custom browser demo from the previous attempt is not part of this checkout. No upstream Git history, remote,
secrets, private specification or internal deployment evidence was copied.

The cloud provider now routes Coach and Diagnoser to NVIDIA Nemotron Super and Solver and Checker to
Nemotron Ultra through Nebius Token Factory. The gateway alone reads `NEBIUS_API_KEY`; the UI does not receive it.
Original local models and feature implementations remain available.

The approved budget is **$25 total for ten days**: $15 inference and $10 reserved for hosting. The gateway's
persistent ledger at `/tmp/jana-nebius-gateway` is retained across this reset. The supplied configuration limits
inference to $1.50 per UTC day and $15 total, ending November 2, 2026 at 00:46:01 UTC. It reserves in-flight costs
and retains failed or unresolved reservations. Do not delete or reset that ledger. Cloud voice and paid web search
remain disabled in this budgeted configuration; their existing implementations are preserved.

Start the gateway in the Terminal where the key is already exported:

```bash
uv run --offline python -m cloud_gateway --config services/cloud-gateway/deploy/nebius-dev.toml --port 8081
```

The full original app is in `apps/desktop`, including its browser development entry:

```bash
pnpm --filter @jana/desktop dev
```

The original development sidecar uses scripted tutor replies by default for UI development. That mode is not
live Nemotron inference and must not be presented as the hackathon demo. Connecting the full app's online
session to the budgeted gateway, public hosting and the submission video are separate remaining integration work.

## The specification

The original private specification is excluded from this fork, together with its pin and internal run evidence.
Checks that require that private specification are unavailable here. Never copy it into this repository.
The existing guard hooks can still prevent accidental inclusion:

```bash
git config core.hooksPath scripts/git-hooks
```

## Checks

```bash
uv run pytest services/cloud-gateway/tests/test_nebius.py services/cloud-gateway/tests/test_inference_budget.py -q
pnpm --filter @jana/desktop typecheck
pnpm --filter @jana/desktop build
```

Acceptance tests are named after the specification's test names, for example `arc16_repository_layout_check`.
