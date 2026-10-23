#!/usr/bin/env bash
# Security and licence scans (SEC-22, SEC-23). Needs the network (advisory databases).
# Fails on a known high or critical vulnerability without a recorded exception, on a disallowed
# licence in a shipped artefact, and on stale lockfiles, SBOM-derived notices or reviews.
set -euo pipefail
cd "$(dirname "$0")/../.."
out="${RUNNER_TEMP:-/tmp}/security"
mkdir -p "$out"

echo "--- supply chain: lockfiles, pinned actions, dependency reviews"
uv run --frozen python -m jana_tools lockfiles action-pins dependency-reviews

echo "--- SBOM per release artefact, licence policy and attributions"
uv run --frozen python -m jana_tools sbom "$out/sbom"
uv run --frozen python -m jana_tools licences notices

ignored=$(uv run --frozen python - <<'PY'
import tomllib
data = tomllib.load(open("scripts/governance/vulnerability-exceptions.toml", "rb"))
print(" ".join(e["id"] for e in data.get("exception", [])))
PY
)

echo "--- Python vulnerabilities (pip-audit)"
uv export --frozen --all-packages --format requirements-txt --no-emit-workspace > "$out/requirements.txt"
pip_ignores=(); for id in $ignored; do pip_ignores+=(--ignore-vuln "$id"); done
uvx --from pip-audit==2.10.1 pip-audit --strict --require-hashes --disable-pip -r "$out/requirements.txt" ${pip_ignores[@]+"${pip_ignores[@]}"}

echo "--- JavaScript vulnerabilities (pnpm audit, high and critical)"
corepack pnpm audit --audit-level high

echo "--- Rust vulnerabilities, licences, bans and sources (cargo-audit, cargo-deny)"
audit_ignores=(); for id in $ignored; do audit_ignores+=(--ignore "$id"); done
cargo audit --deny warnings ${audit_ignores[@]+"${audit_ignores[@]}"}
cargo deny --locked check advisories licenses bans sources
