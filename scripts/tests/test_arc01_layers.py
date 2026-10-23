"""ARC-01: every package declares exactly one layer."""

import json
from pathlib import Path

from jana_tools import REPO_ROOT
from jana_tools.layers import find_packages, layer_errors


def arc01_every_package_declares_layer(repo_copy: Path):
    assert layer_errors(REPO_ROOT) == []
    assert len(find_packages(REPO_ROOT)) >= 12

    ui = repo_copy / "packages" / "ui" / "package.json"
    data = json.loads(ui.read_text())
    del data["jana"]
    ui.write_text(json.dumps(data))
    core = repo_copy / "services" / "agent-core" / "agent_core" / "planner"
    core.mkdir()
    (core / "__init__.py").write_text("")
    worker = repo_copy / "services" / "tool-worker" / "pyproject.toml"
    worker.write_text(worker.read_text().replace('layer = "capabilities"', 'layer = "toolbox"'))

    assert layer_errors(repo_copy) == [
        "packages/ui/package.json: must declare exactly one of jana.layer or jana.modules",
        "services/agent-core/pyproject.toml: module agent_core.planner declares no layer",
        "services/tool-worker/pyproject.toml: unknown layer 'toolbox'",
    ]
