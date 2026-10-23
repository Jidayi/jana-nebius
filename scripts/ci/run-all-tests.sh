#!/usr/bin/env bash
# The full test suite across the three toolchains, with no network access needed.
# Dependencies must already be installed (uv sync, pnpm install, cargo fetch).
# Every toolchain runs even if an earlier one fails; the script fails if any did.
set -uo pipefail
cd "$(dirname "$0")/../.."
export TURBO_TELEMETRY_DISABLED=1 DO_NOT_TRACK=1 UV_OFFLINE=1 COREPACK_ENABLE_NETWORK=0 CARGO_NET_OFFLINE=true
status=0
uv run --frozen --offline pytest || status=1
corepack pnpm test || status=1
cargo test --locked --offline --workspace || status=1
exit $status
