"""ARC-30 and API-34: one schema source with generated bindings and a staleness gate."""

import json
import shutil
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.codegen import AGENT_CORE, CONTRACTS, CONTRACTS_TS, TARGETS, TOOL_WORKER, stale_errors
from jana_tools.codegen.sources import load_contracts

CI = (REPO_ROOT / "scripts" / "ci" / "codegen-check.sh").read_text()


def _committed_copy(tmp: Path) -> Path:
    root = tmp / "repo"
    for target in TARGETS:
        shutil.copytree(REPO_ROOT / target, root / target, ignore=shutil.ignore_patterns("__pycache__"))
    return root


def _changed_contracts(tmp: Path) -> Path:
    """The contracts with one additive change (a new event channel value) and no regeneration."""
    contracts = tmp / "contracts"
    shutil.copytree(CONTRACTS, contracts)
    events = contracts / "api" / "events.schema.json"
    schema = json.loads(events.read_text())
    schema["properties"]["channel"]["enum"].append("diagnostics")
    events.write_text(json.dumps(schema, indent=2))
    return contracts


def arc30_generated_contracts_not_stale(tmp_path: Path):
    # Green: the committed bindings are exactly what the schemas generate, for every contract and target.
    assert stale_errors() == []
    contracts = load_contracts(CONTRACTS)
    for contract in contracts:
        assert (REPO_ROOT / AGENT_CORE / f"{contract.module}.py").is_file()
        assert (REPO_ROOT / CONTRACTS_TS / f"{contract.module}.ts").is_file()
        assert f"source sha256: {contract.sha256}" in (REPO_ROOT / AGENT_CORE / f"{contract.module}.py").read_text()
    for contract in (c for c in contracts if c.stem.startswith("tools/")):
        assert (REPO_ROOT / TOOL_WORKER / f"{contract.module}.py").is_file()

    # Red: a schema changed without regenerating fails, naming the Python and TypeScript bindings.
    errors = stale_errors(REPO_ROOT, _changed_contracts(tmp_path))
    assert f"{AGENT_CORE}/api/events.py: differs from its schema (stale or hand-edited; run codegen)" in errors
    assert f"{CONTRACTS_TS}/api/events.ts: differs from its schema (stale or hand-edited; run codegen)" in errors
    assert (
        f"{AGENT_CORE}/schemas/api/events.schema.json: differs from its schema (stale or hand-edited; run codegen)"
        in errors
    )

    # Red: a hand edit to a generated binding fails, as do a deleted and an added file.
    root = _committed_copy(tmp_path)
    model = root / AGENT_CORE / "api" / "events.py"
    model.write_text(model.read_text().replace('extra="forbid"', 'extra="allow"', 1))
    (root / CONTRACTS_TS / "tools" / "tool_result.ts").unlink()
    (root / TOOL_WORKER / "handwritten.py").write_text("class Wire: ...\n")
    assert stale_errors(root) == [
        f"{AGENT_CORE}/api/events.py: differs from its schema (stale or hand-edited; run codegen)",
        f"{TOOL_WORKER}/handwritten.py: not generated from any contract",
        f"{CONTRACTS_TS}/tools/tool_result.ts: missing (run codegen)",
    ]

    # The codegen stage runs the same check in CI.
    assert "jana_tools codegen" in CI


def api34_stale_contracts_fail(tmp_path: Path):
    """The API contracts in particular: an edited generated Pydantic model or TypeScript type, or an API schema
    changed without regenerating, fails the check."""
    root = _committed_copy(tmp_path)
    ts = root / CONTRACTS_TS / "api" / "commands.ts"
    ts.write_text(ts.read_text() + "\nexport interface HandWritten { x: number }\n")
    assert stale_errors(root) == [
        f"{CONTRACTS_TS}/api/commands.ts: differs from its schema (stale or hand-edited; run codegen)"
    ]
    errors = stale_errors(REPO_ROOT, _changed_contracts(tmp_path))
    assert any(e.startswith(f"{CONTRACTS_TS}/validators.js") for e in errors)
