# signing-service

The internal content signing service (D34, AUT-33). For each queued publish request it exports the named commit
into a clean directory, rebuilds the pack, re-runs every gate (verification, licence, held-out exclusion, coverage for
pilot and stable, and the requester), checks the version bump and KC migrations against the previous release (CUR-09,
CUR-10), moves the banked records to `published`, signs, and writes the signed pack, a signed row-level diff from the
previous release and a release record with the pack and diff sizes against their budgets (CUR-34).

```bash
uv run python -m signing_service process
uv run python -m signing_service anchors --write   # regenerate the public trust anchors the app bundles (SEC-12)
```

## Keys (SEC-12)

Every signature is Ed25519, from an intermediate key with one purpose (content, model, agent bundle, updater, licence)
certified by a root key. The app bundles only public data: the root public keys and the intermediate certificates
(`services/agent-core/agent_core/config/trust_anchors.json`), and verifies each artefact type against the matching
intermediate only.

- **Test hierarchy** (`signing_service/keys.py`): the test root and its intermediates are derived from published
  phrases. They are not secrets and give no authority: development builds trust them, pilot and production builds
  refuse them (OPS-35).
- **Production hierarchy**: no private key is ever in this repository, on a developer machine or in a CI variable.
  The release root is created offline with two-of-three custodians and issues the intermediate certificates
  (`hierarchy.issue_certificate`, which refuses a validity longer than the configured rotation); the intermediates
  live in HSMs. The service signs through the HSM's signing command by reference (`hierarchy.production_signer`)
  and checks every returned signature against the intermediate's certificate. The resulting root public key and
  certificates are added to the trust anchors (public data) before a release build.
- **The key ceremony** (`python -m signing_service.ceremony issue|adopt|dry-run`): issues the root's public record,
  the five certificates and the root's first revocation list through the root HSM's signing command, then adopts them
  into the trust anchors. `dry-run` rehearses every step with throwaway keys and changes nothing here. The owner's
  guide is `scripts/governance/evidence/KEY-CEREMONY.md`.
- **App updates, signed offline** (`signing_service.updater`; owner ruling 2026-10-17): Tauri's updater key is never
  in CI. The release job writes the unsigned update bundles with a request (`updater request`); the ceremony laptop
  signs exactly those files through Tauri's signer and verifies each signature against the app's updater public key
  (`ceremony sign-updates`); publishing checks the signed result (`updater verify`, `jana_tools release publish
  --kind app_update --signatures ...`).
