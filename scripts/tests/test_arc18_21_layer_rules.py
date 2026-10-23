"""ARC-18 to ARC-21: dependency rules, each proven by a seeded forbidden import."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.bundle_scan import bundle_scan_errors
from jana_tools.layer_rules import ROWS, importlinter_errors

LINT_IMPORTS = Path(sys.executable).parent / "lint-imports"
DEPCRUISE = REPO_ROOT / "node_modules" / ".bin" / "depcruise"
PY_PACKAGES = {
    "agent_core": "services/agent-core",
    "tool_worker": "services/tool-worker",
    "perception_worker": "services/perception-worker",
    "study_worker": "services/study-worker",
}
# One forbidden import per ARC-18 row: (module file to seed, import line, contract broken).
PY_SEEDS = {
    "api": ("agent_core/api/__init__.py", "import agent_core.router"),
    "engine": ("agent_core/engine/__init__.py", "import agent_core.api"),
    "prompts": ("agent_core/prompts/__init__.py", "import agent_core.store"),
    "tools": ("agent_core/tools/__init__.py", "import agent_core.learner"),
    "router-providers": ("agent_core/router/__init__.py", "import agent_core.engine"),
    "learner-memory": ("agent_core/memory/__init__.py", "import agent_core.net"),
    "net": ("agent_core/net/__init__.py", "import agent_core.engine"),
    "roles": ("agent_core/roles/__init__.py", "import agent_core.router"),
    "assets": ("agent_core/assets/__init__.py", "import agent_core.engine"),
    "retrieval": ("agent_core/retrieval/__init__.py", "import agent_core.router"),
    "store": ("agent_core/store/__init__.py", "import agent_core.trace"),
    "trace": ("agent_core/trace/__init__.py", "import agent_core.engine"),
    "config": ("agent_core/config/__init__.py", "import agent_core.store"),
    "tool-worker": ("tool_worker/__init__.py", "import socket"),
    "perception-worker": ("perception_worker/__init__.py", "import agent_core"),
    "study-worker": ("study_worker/__init__.py", "import socket"),
}
TS_SEEDS = {
    "arc18-ui-imports": ("packages/ui/src/seed.ts", 'import "../../../apps/desktop/src/launch";'),
    "arc18-renderers-imports": ("packages/renderers/src/seed.ts", 'import "../../ui/src/index";'),
    "arc18-ui-no-http-client": ("packages/ui/src/seed2.ts", 'import "axios";'),
    "arc19-no-model-sdk": ("apps/desktop/src/seed.ts", 'import "openai";'),
}


def _copy_python(tmp: Path) -> dict[str, Path]:
    roots = {}
    for package, service in PY_PACKAGES.items():
        dest = tmp / service
        shutil.copytree(REPO_ROOT / service / package, dest / package, ignore=shutil.ignore_patterns("__pycache__"))
        roots[package] = dest
    shutil.copy2(REPO_ROOT / ".importlinter", tmp / ".importlinter")
    return roots


def _lint_imports(tmp: Path, roots: dict[str, Path]) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": os.pathsep.join(str(p) for p in roots.values())}
    return subprocess.run(
        [str(LINT_IMPORTS), "--config", str(tmp / ".importlinter"), "--no-cache"],
        cwd=tmp,
        env=env,
        capture_output=True,
        text=True,
    )


def _copy_typescript(tmp: Path) -> None:
    for rel in ("packages", "apps/desktop/src"):
        shutil.copytree(REPO_ROOT / rel, tmp / rel, ignore=shutil.ignore_patterns("node_modules", "dist"))
    for rel in (".dependency-cruiser.cjs", "tsconfig.base.json"):
        shutil.copy2(REPO_ROOT / rel, tmp / rel)


def _depcruise(tmp: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(DEPCRUISE), "--config", ".dependency-cruiser.cjs", "--output-type", "err", "packages", "apps/desktop/src"],
        cwd=tmp,
        capture_output=True,
        text=True,
    )


def arc18_forbidden_imports_fail(tmp_path: Path):
    assert importlinter_errors(REPO_ROOT) == []
    assert set(PY_SEEDS) == {row.name for row in ROWS}, "every ARC-18 row needs a seeded import"

    roots = _copy_python(tmp_path / "py")
    clean = _lint_imports(tmp_path / "py", roots)
    assert clean.returncode == 0, clean.stdout + clean.stderr
    for name, (module, line) in PY_SEEDS.items():
        package = module.split("/")[0]
        target = roots[package] / module
        original = target.read_text()
        target.write_text(original + line + "\n")
        result = _lint_imports(tmp_path / "py", roots)
        target.write_text(original)
        assert result.returncode != 0, f"seeded import for row {name} was not caught"
        assert f"ARC-18 {name} BROKEN" in result.stdout, result.stdout

    # Only agent_core.net may import a network client: every row forbids it, and so do the generated contracts.
    store = roots["agent_core"] / "agent_core" / "store" / "__init__.py"
    store.write_text(store.read_text() + "import httpx\n")
    result = _lint_imports(tmp_path / "py", roots)
    assert "ARC-18 store imports no network client directly BROKEN" in result.stdout, result.stdout
    contracts = roots["agent_core"] / "agent_core" / "contracts" / "__init__.py"
    contracts.write_text(contracts.read_text() + "import httpx\n")
    result = _lint_imports(tmp_path / "py", roots)
    assert "ARC-18 only agent_core.net imports a network client BROKEN" in result.stdout, result.stdout
    # Provider keys stay server-side: shipped code never imports the cloud gateway (ARC-12, SEC-20).
    net = roots["agent_core"] / "agent_core" / "net" / "__init__.py"
    net.write_text(net.read_text() + "import cloud_gateway\n")
    result = _lint_imports(tmp_path / "py", roots)
    assert "ARC-12 SEC-20 shipped code never imports the cloud gateway or its key custody BROKEN" in result.stdout
    # The intake that holds received reports and bundles is server-side too (OBS-17, OBS-20, OPS-24).
    net.write_text(net.read_text() + "import ingest\n")
    result = _lint_imports(tmp_path / "py", roots)
    assert "OBS-17 OBS-20 OPS-24 the ingest is server-side: shipped code never imports it BROKEN" in result.stdout

    _copy_typescript(tmp_path / "ts")
    clean = _depcruise(tmp_path / "ts")
    assert clean.returncode == 0, clean.stdout + clean.stderr
    for path, line in TS_SEEDS.values():
        (tmp_path / "ts" / path).write_text(line + "\n")
    seeded = _depcruise(tmp_path / "ts")
    assert seeded.returncode != 0
    for rule in TS_SEEDS:
        assert rule in seeded.stdout + seeded.stderr, f"seeded import for {rule} was not caught"


def arc19_client_bundle_has_no_model_access(tmp_path: Path):
    assert bundle_scan_errors(REPO_ROOT) == []

    root = tmp_path / "repo"
    for rel in ("packages", "apps/desktop/src"):
        shutil.copytree(REPO_ROOT / rel, root / rel, ignore=shutil.ignore_patterns("node_modules"))
    (root / "packages/ui/src/chat.ts").write_text('import OpenAI from "openai";\n')
    (root / "packages/renderers/dist").mkdir()
    (root / "packages/renderers/dist/bundle.js").write_text('fetch("https://api.anthropic.com/v1/messages")\n')
    (root / "apps/desktop/src/direct.ts").write_text('const url = "http://127.0.0.1:8080/v1/chat/completions";\n')
    pkg = root / "packages/client-core/package.json"
    manifest = json.loads(pkg.read_text())
    manifest.setdefault("dependencies", {})["ollama"] = "1.0.0"
    pkg.write_text(json.dumps(manifest, indent=2))

    assert bundle_scan_errors(root) == [
        "apps/desktop/src/direct.ts:1: names a model runtime address /v1/chat/completions",
        "apps/desktop/src/direct.ts:1: names a model runtime address 127.0.0.1:8080",
        "packages/client-core/package.json: depends on model SDK ollama",
        "packages/renderers/dist/bundle.js:1: names model provider host api.anthropic.com",
        "packages/ui/src/chat.ts:1: imports model SDK openai",
    ]


def test_arc21_static_rules_seeded(tmp_path: Path):
    """The static half of ARC-21 (the runtime acceptance tests follow in M2 and M4; gaps.md G4)."""
    roots = _copy_python(tmp_path)
    roles = roots["agent_core"] / "agent_core" / "roles" / "__init__.py"
    roles.write_text(roles.read_text() + "import agent_core.memory\n")
    worker = roots["tool_worker"] / "tool_worker" / "__init__.py"
    worker.write_text(worker.read_text() + "import agent_core.store\n")
    result = _lint_imports(tmp_path, roots)
    assert "ARC-21 specialist roles never reach learner state BROKEN" in result.stdout, result.stdout
    assert "ARC-18 tool-worker BROKEN" in result.stdout, result.stdout
