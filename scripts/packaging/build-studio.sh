#!/usr/bin/env bash
# Stage the internal authoring runtime separately from the learner application. Native signing happens afterwards.
set -euo pipefail
root="$(cd "$(dirname "$0")/../.." && pwd)"
work="${JANA_STUDIO_BUILD_DIR:-$root/dist/studio-runtime}"
python="${JANA_STUDIO_BUILD_PYTHON:-$root/.venv/bin/python}"
resources="$root/apps/studio/src-tauri/resources"
if [[ "$work" == / || "$work" == "$root" ]]; then
  echo "Choose a dedicated Studio build directory." >&2
  exit 2
fi
if rg -q PLACEHOLDER "$root/scripts/packaging/requirements-build.txt"; then
  echo "Pin the build tool versions and hashes before packaging Studio." >&2
  exit 3
fi
: "${JANA_STUDIO_NODE:?Set the reviewed Node executable used for the bundled KaTeX checker.}"
: "${JANA_STUDIO_NODE_LICENSE:?Set the full licence file from that Node distribution.}"
cd "$root"
"$python" -m PyInstaller --noconfirm --distpath "$work/dist" --workpath "$work/build" scripts/packaging/studio-backend.spec
"$python" -m PyInstaller --noconfirm --distpath "$work/dist" --workpath "$work/build" scripts/packaging/tool-worker.spec
mkdir -p "$resources"
for bundle in studio-backend tool-worker; do
  if [[ -d "$resources/$bundle" ]]; then
    mv "$resources/$bundle" "$work/previous-$bundle-$(date +%s)"
  fi
  cp -R "$work/dist/$bundle" "$resources/$bundle"
done
backend="$resources/studio-backend/studio-backend"
if [[ -f "$backend.exe" ]]; then backend="$backend.exe"; fi
"$python" scripts/packaging/studio-smoke.py --backend "$backend"
