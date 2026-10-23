"""PLT-03: the tool worker bundle carries only modules on the SEC-07 allow-list."""

import sys

from jana_tools import REPO_ROOT
from jana_tools.supply_chain import _site_packages
from jana_tools.worker_bundle import (
    BUNDLE_EXCLUDES,
    bundle_inventory,
    distribution_modules,
    inventory_errors,
    worker_imports,
    worker_inventory,
)
from tool_worker.guard import ALLOWED, FORBIDDEN


def plt03_worker_bundle_inventory():
    inventory = worker_inventory()
    imported = worker_imports()
    assert inventory_errors(inventory, ALLOWED, imported) == []
    # Matches both ways: the bundle holds exactly the allowed third-party modules the worker imports.
    assert set(inventory) == (imported & ALLOWED) - set(sys.stdlib_module_names), sorted(inventory)
    assert not set(inventory) & FORBIDDEN
    assert {"tool_worker", "sympy", "mpmath", "pint", "pydantic", "jsonschema"} <= set(inventory)

    # A dependency bringing an unlisted module fails the check, naming the module and its distribution.
    site_packages = _site_packages(REPO_ROOT)
    assert site_packages is not None
    modules = distribution_modules(site_packages)
    closure = sorted(d for m, d in inventory.items() if m != "tool_worker")
    leaky = bundle_inventory([*closure, "leaky-client"], {**modules, "leaky-client": {"leaky_client"}})
    assert inventory_errors(leaky, ALLOWED, imported) == [
        "worker bundle: leaky_client (from leaky-client) is not on the SEC-07 allow-list"
    ]
    # An allowed module the worker imports but that the locked closure does not provide fails too.
    assert inventory_errors(inventory, ALLOWED, imported | {"numpy"}) == [
        "worker bundle: the worker imports numpy, which is allowed but not in its locked closure"
    ]
    # SymPy's console launcher ships in its distribution but never in the bundle.
    assert set(BUNDLE_EXCLUDES) <= modules["sympy"] and not set(BUNDLE_EXCLUDES) & set(inventory)


PROBE = """
import importlib.util, json, sys
from importlib import metadata
from tool_worker.closure import confine
modules = confine()
import tool_worker.__main__, tool_worker.server as server
from tool_worker.functions import preload
preload()
import sysconfig
sysconfig.get_config_vars()
try:
    import numpy
    refused = False
except ModuleNotFoundError:
    refused = True
print(json.dumps({"loaded": sorted(sys.modules), "refused": refused, "closure": sorted(modules),
                  "spec": importlib.util.find_spec("numpy") is not None, "libraries": sorted(server._libraries())}))
"""


def test_development_worker_loads_only_its_closure():
    """A worker started from the shared development environment (where the perception worker's NumPy and OpenCV are
    installed) is confined to its own closure before any library loads: Pint's and SymPy's optional NumPy import falls
    back as in the bundle, the standard library still loads, and the hello reports only the closure's libraries."""
    import json
    import subprocess

    from tool_worker.closure import _requirement_name

    assert _requirement_name("sympy>=1.14,<2") == "sympy"
    assert _requirement_name('typing_extensions>=4; python_version < "3.13"') == "typing-extensions"
    assert _requirement_name('numpy>=2; extra == "numpy"') is None
    out = subprocess.run([sys.executable, "-c", PROBE], check=True, capture_output=True, text=True, cwd=REPO_ROOT)
    seen = json.loads(out.stdout.strip().splitlines()[-1])
    assert {"sympy", "pint", "mpmath", "tool_worker"} <= set(seen["closure"]) and "numpy" not in seen["closure"]
    assert not {m for m in seen["loaded"] if m.partition(".")[0] in ("numpy", "cv2")}
    assert seen["refused"] and not seen["spec"], "absent, as in the bundle, not an error"
    assert {"sympy", "mpmath", "pint"} <= set(seen["libraries"]) and "numpy" not in seen["libraries"]
