#!/usr/bin/env bash
# Run the CI offline job locally in Docker (Linux network namespace + connection monitor).
# Needs Docker with --privileged. Installs dependencies with the network, then runs the suite without it.
#   scripts/ci/offline-local.sh                      # full suite (scripts/ci/run-all-tests.sh)
#   scripts/ci/offline-local.sh uv run pytest -k x   # any other command under the harness
set -euo pipefail
here="$(cd "$(dirname "$0")/../.." && pwd)"
docker build -q -f "$here/scripts/ci/offline.Dockerfile" -t jana-offline "$here/scripts/ci" >/dev/null
cmd="${*:-scripts/ci/run-all-tests.sh}"
docker run --rm --privileged -e CMD="$cmd" -v "$here":/src:ro jana-offline bash -c '
  set -euo pipefail
  tar -C /src --exclude=./node_modules --exclude=./.venv --exclude=./target --exclude="*/node_modules" \
      --exclude=./dist -cf - . | tar -C /work -xf -
  uv python install 3.12 -q
  corepack pnpm install --frozen-lockfile >/dev/null
  uv sync --locked --all-packages -q
  cargo fetch --locked -q
  cargo test --locked --workspace --no-run -q 2>/dev/null
  sudo -E scripts/ci/offline-selftest.sh
  sudo -E env "PATH=$PATH" scripts/ci/offline-run.sh --user runner -- bash -c "$CMD"
'
