"""The tool worker bundle's module inventory (PLT-03) against the worker's import allow-list (SEC-07).

The worker bundle is built from the locked uv environment, so the third-party modules it can carry are the top-level
modules of the distributions in `jana-tool-worker`'s locked dependency closure, plus the worker package itself. That
inventory must match the allow-list: every module in it is allowed, and every allowed third-party module the worker
actually imports is in it. The standard library subset comes from the bundled runtime and is not inventoried here.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Iterable, Mapping
from importlib import metadata
from pathlib import Path

from . import REPO_ROOT
from .supply_chain import _site_packages, python_closure

WORKER_DISTRIBUTION = "jana-tool-worker"
WORKER_PACKAGE = "tool_worker"

# Modules a locked distribution ships that the bundle leaves out, with the reason. The bundle spec excludes them.
BUNDLE_EXCLUDES = {
    "isympy": "SymPy's interactive console launcher: a tool that runs code supplied at run time (SEC-09)",
}


def _normalise(name: str) -> str:
    return name.lower().replace("_", "-").replace(".", "-")


def distribution_modules(site_packages: Path) -> dict[str, set[str]]:
    """Each installed distribution's top-level importable modules, read from its installed file list."""
    found: dict[str, set[str]] = {}
    for dist in metadata.distributions(path=[str(site_packages)]):
        modules = found.setdefault(_normalise(dist.metadata["Name"]), set())
        for file in dist.files or ():
            top = file.parts[0]
            if top in ("..", "__pycache__") or top.endswith((".dist-info", ".data", ".pth")):
                continue
            if len(file.parts) == 1:  # a single-file module or an extension module (name.cpython-312-darwin.so)
                if not top.endswith((".py", ".so", ".pyd")):
                    continue
                top = top.split(".", 1)[0]
            if top.isidentifier():
                modules.add(top)
    return found


def bundle_inventory(closure: Iterable[str], modules: Mapping[str, set[str]]) -> dict[str, str]:
    """Top-level module -> the distribution that brings it into the worker bundle."""
    inventory = {WORKER_PACKAGE: WORKER_DISTRIBUTION}
    for dist in closure:
        provided = modules.get(_normalise(dist))
        if not provided:
            inventory[f"<{dist}>"] = dist  # a locked distribution that is not installed: its modules are unknown
            continue
        for module in provided:
            inventory.setdefault(module, dist)
    return {m: d for m, d in sorted(inventory.items()) if m not in BUNDLE_EXCLUDES}


def worker_imports(python: str = sys.executable) -> set[str]:
    """Top-level modules the worker has loaded once its libraries are preloaded, as at start (TOL-26): confined to its
    own dependency closure before any library loads, as `tool_worker.__main__` does."""
    probe = (
        "import json, sys\nfrom tool_worker.closure import confine\nconfine()\n"
        "import tool_worker.__main__, tool_worker.server\nfrom tool_worker.functions import preload\npreload()\n"
        "print(json.dumps(sorted({n.partition('.')[0] for n in sys.modules})))\n"
    )
    out = subprocess.run([python, "-c", probe], check=True, capture_output=True, text=True, cwd=REPO_ROOT).stdout
    return set(json.loads(out.strip().splitlines()[-1]))


def inventory_errors(inventory: Mapping[str, str], allowed: Iterable[str], imported: Iterable[str] = ()) -> list[str]:
    allowed = set(allowed)
    errors = [
        f"worker bundle: {module} (from {dist}) is not on the SEC-07 allow-list"
        for module, dist in inventory.items()
        if module not in allowed
    ]
    stdlib = set(sys.stdlib_module_names)
    errors += [
        f"worker bundle: the worker imports {module}, which is allowed but not in its locked closure"
        for module in sorted(set(imported) & allowed - stdlib - set(inventory))
    ]
    return errors


def worker_inventory(root: Path = REPO_ROOT) -> dict[str, str]:
    site_packages = _site_packages(root)
    if site_packages is None:
        raise FileNotFoundError(f"no installed environment under {root / '.venv'}")
    closure = [c.name for c in python_closure((root / "uv.lock").read_text(), WORKER_DISTRIBUTION, None)]
    return bundle_inventory(closure, distribution_modules(site_packages))
