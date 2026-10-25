#!/usr/bin/env bash
# Contract codegen check (ARC-30, API-34): regenerate every binding from the public contracts and fail
# on any difference (a schema changed without regeneration, or a hand-edited binding); the fixture corpus
# and the fakes' recorded scripts must be current too.
set -euo pipefail
cd "$(dirname "$0")/../.."
uv run --frozen python -m jana_tools codegen --check
uv run --frozen python -m jana_tools fixtures --check
