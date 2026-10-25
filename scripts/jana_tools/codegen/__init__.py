"""Contract code generation (ARC-30, API-34; D39, D45).

One entry point generates every binding from the public JSON Schemas in contracts/:

- Pydantic v2 models (`extra="forbid"`) into `agent_core.contracts` (every contract),
  `tool_worker.contracts` (the tool contracts), `ingest.contracts` (the bodies the ingest receives) and
  `cloud_gateway.contracts` (the gateway and licence contracts), with the prose-free canonical schemas and a
  validation runtime that checks instances against them (JSON Schema 2020-12, offline registry);
- TypeScript types and precompiled, eval-free runtime validators into `packages/contracts-ts/src/generated`.

Every generated file carries a header naming its source schema and the source's sha256. `check()` regenerates
into a scratch directory and reports any committed file that differs, is missing or is extra, so a schema change
without regeneration and a hand edit both fail (the codegen stage of CI).

    python -m jana_tools codegen           # regenerate and write
    python -m jana_tools codegen --check   # fail on stale or hand-edited bindings
"""

from __future__ import annotations

import filecmp
import shutil
import tempfile
from pathlib import Path

from .. import REPO_ROOT
from .availability import generate_availability
from .event_registry import generate_event_registry
from .item_types import generate_item_types
from .python import generate_python
from .rust_control import generate_rust_control
from .schema_sql import generate_schema_sql
from .sources import Contract, load_contracts
from .tokens import generate_tokens
from .tooldata import (
    generate_client_keys,
    generate_endpoints,
    generate_renderer_data,
    generate_shell_keys,
    generate_tool_data,
    generate_ui_tools,
    generate_visual_data,
)
from .typescript import generate_typescript

# Public generation inputs: schemas, runtime registers, and policy identifiers.
CONTRACTS = REPO_ROOT / "contracts"
REGISTERS = CONTRACTS / "registers"
SPEC = CONTRACTS / "policies"

# Output roots, relative to the repository root.
AGENT_CORE = Path("services/agent-core/agent_core/contracts")
TOOL_WORKER = Path("services/tool-worker/tool_worker/contracts")
INGEST = Path("services/ingest/ingest/contracts")
# The bodies and replies of the telemetry, crash and support intake (OBS-17, OBS-20, OPS-22, OPS-24).
INGEST_CONTRACTS = frozenset({"trace/telemetry", "ops/support-bundle", "cloud/outbox", "ops/support-upload"})
CONTRACTS_TS = Path("packages/contracts-ts/src/generated")
TOOL_DATA = Path("services/agent-core/agent_core/tools/generated")
VISUAL_DATA = Path("services/agent-core/agent_core/assets/generated")
CLIENT_KEYS = Path("packages/client-core/src/generated")
RENDERER_DATA = Path("packages/renderers/src/generated")
UI_TOKENS = Path("packages/ui/src/generated")
SHELL_KEYS = Path("apps/desktop/src-tauri/src/generated")
STORE_DATA = Path("services/agent-core/agent_core/store/generated")
# The cloud gateway is a separate service that may not import agent_core: it gets its own bindings (D39).
CLOUD_GATEWAY = Path("services/cloud-gateway/cloud_gateway/contracts")
TARGETS = (
    AGENT_CORE, TOOL_WORKER, INGEST, CONTRACTS_TS, TOOL_DATA, VISUAL_DATA, CLIENT_KEYS, RENDERER_DATA, UI_TOKENS,
    SHELL_KEYS, STORE_DATA, CLOUD_GATEWAY,
)  # fmt: skip
GATEWAY_CONTRACTS = frozenset({"cloud/gateway", "ops/licence"})


def _tool_contracts(contract: Contract) -> bool:
    return contract.stem.startswith("tools/")


def generate_into(out_root: Path, contracts_dir: Path = CONTRACTS, registers_dir: Path = REGISTERS) -> None:
    """Generate every target under `out_root` (a repository root or a scratch directory)."""
    contracts = load_contracts(contracts_dir)
    generate_python(contracts, out_root / AGENT_CORE, package="agent_core.contracts")
    generate_python(
        [c for c in contracts if _tool_contracts(c)], out_root / TOOL_WORKER, package="tool_worker.contracts",
        all_contracts=contracts,
    )  # fmt: skip
    generate_python(
        [c for c in contracts if c.stem in INGEST_CONTRACTS], out_root / INGEST, package="ingest.contracts",
        all_contracts=contracts,
    )  # fmt: skip
    generate_python([c for c in contracts if c.stem in GATEWAY_CONTRACTS], out_root / CLOUD_GATEWAY,
                    package="cloud_gateway.contracts", all_contracts=contracts)  # fmt: skip
    generate_typescript(contracts, out_root / CONTRACTS_TS)
    generate_tool_data(out_root / TOOL_DATA, registers_dir)
    generate_visual_data(out_root / VISUAL_DATA, registers_dir)
    generate_client_keys(out_root / CLIENT_KEYS)
    generate_renderer_data(REPO_ROOT / "packages/ui/tokens.json", out_root / RENDERER_DATA)
    generate_tokens(REPO_ROOT / "packages/ui/tokens.json", out_root / UI_TOKENS)
    generate_ui_tools(registers_dir, out_root / UI_TOKENS)
    generate_shell_keys(out_root / SHELL_KEYS)
    generate_rust_control(contracts, out_root / SHELL_KEYS)  # control.rs, and mod.rs naming both modules
    generate_schema_sql(contracts_dir, out_root / STORE_DATA)
    generate_event_registry(SPEC, out_root / STORE_DATA)
    generate_availability(SPEC, out_root / STORE_DATA)
    generate_item_types(SPEC, out_root / STORE_DATA)
    generate_endpoints(contracts_dir, out_root / AGENT_CORE / "api" / "endpoints.py",
                       out_root / CONTRACTS_TS / "api" / "endpoints.ts")  # fmt: skip


def generate(root: Path = REPO_ROOT, contracts_dir: Path = CONTRACTS) -> None:
    """Regenerate the committed bindings in place (each target directory is replaced)."""
    with tempfile.TemporaryDirectory() as scratch:
        generate_into(Path(scratch), contracts_dir)
        for target in TARGETS:
            shutil.rmtree(root / target, ignore_errors=True)
            shutil.copytree(Path(scratch) / target, root / target)


def _tree(root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file() and "__pycache__" not in p.parts}


def stale_errors(root: Path = REPO_ROOT, contracts_dir: Path = CONTRACTS) -> list[str]:
    """Differences between the committed bindings and a fresh generation."""
    errors = []
    with tempfile.TemporaryDirectory() as scratch:
        generate_into(Path(scratch), contracts_dir)
        for target in TARGETS:
            fresh, committed = Path(scratch) / target, root / target
            want, have = _tree(fresh), _tree(committed) if committed.is_dir() else set()
            errors += [f"{target}/{f}: missing (run codegen)" for f in sorted(want - have)]
            errors += [f"{target}/{f}: not generated from any contract" for f in sorted(have - want)]
            errors += [
                f"{target}/{f}: differs from its schema (stale or hand-edited; run codegen)"
                for f in sorted(want & have)
                if not filecmp.cmp(fresh / f, committed / f, shallow=False)
            ]
    return errors


def drift_metric(root: Path = REPO_ROOT, contracts_dir: Path = CONTRACTS) -> tuple[int, int, list[str]]:
    """S1 exit metric "contracts generate types with zero drift": (contracts with Python and TypeScript bindings
    and no drift, all contracts, the drifting files)."""
    contracts = load_contracts(contracts_dir)
    errors = stale_errors(root, contracts_dir)
    drifting = {c.rel for c in contracts for e in errors if f"/{c.module}." in e or c.rel in e}
    clean = [
        c for c in contracts
        if c.rel not in drifting
        and (root / AGENT_CORE / f"{c.module}.py").is_file()
        and (root / CONTRACTS_TS / f"{c.module}.ts").is_file()
    ]  # fmt: skip
    return len(clean), len(contracts), errors
