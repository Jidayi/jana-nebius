#!/usr/bin/env bash
# Release job: build the agent core and tool worker one-dir bundles (PLT-02, PLT-03) from the locked uv environment,
# fetch the pinned llama.cpp builds (PLT-04), and stage every bundle resource under apps/desktop/src-tauri/resources/
# for `tauri build --config tauri.release.conf.json`. Needs the network (PyPI for the build tools, the llama.cpp
# release) and the owner's pins; it refuses any PLACEHOLDER. Never run in the offline job.
set -euo pipefail

os="${1:?usage: build-sidecars.sh windows|macos|linux}"
root="$(cd "$(dirname "$0")/../.." && pwd)"
resources="$root/apps/desktop/src-tauri/resources"
work="${RUNNER_TEMP:-$(mktemp -d)}/jana-sidecars"

if grep -q PLACEHOLDER "$root/scripts/packaging/requirements-build.txt"; then
  echo "build tools are not pinned yet (scripts/packaging/requirements-build.txt)" >&2
  exit 3
fi

cd "$root"
uv sync --locked --all-packages
uv pip install --require-hashes -r scripts/packaging/requirements-build.txt
rm -rf "$resources" "$work"
mkdir -p "$resources" "$work"
uv run pyinstaller --noconfirm --distpath "$work/dist" --workpath "$work/build" scripts/packaging/agent-core.spec
uv run pyinstaller --noconfirm --distpath "$work/dist" --workpath "$work/build" scripts/packaging/tool-worker.spec
# PLT-02: the perception worker is delivered in its separate signed pack, never the base installer.
# Prepare its one-dir artifact only when the release job supplied the independently reviewed OCR asset.
if [[ -n "${JANA_OCR_DATA_FILE:-}" ]]; then
  uv run pyinstaller --noconfirm --distpath "$work/perception-pack" --workpath "$work/build" scripts/packaging/perception-worker.spec
fi
uv run python -m jana_tools release resources --os "$os" --sidecars "$work/dist" --out "$resources"
uv run python -m jana_tools release runtime-fetch --os "$os" --out "$resources" --cache "$work/cache"
