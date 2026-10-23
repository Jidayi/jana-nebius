"""ARC-01 layer declarations: every product package declares exactly one layer, or maps
each of its modules to exactly one layer."""

from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

LAYERS = frozenset(
    {
        "experience",
        "streaming",
        "agent_runtime",
        "assets",
        "capabilities",
        "models",
        "state",
        "connectivity",
    }
)


@dataclass(frozen=True)
class Package:
    manifest: Path
    declaration: dict | None  # the "jana" metadata table, if any


def find_packages(root: Path) -> list[Package]:
    found: list[Package] = []
    for manifest in sorted(root.glob("apps/*/package.json")) + sorted(root.glob("packages/*/package.json")):
        found.append(Package(manifest, json.loads(manifest.read_text()).get("jana")))
    for manifest in sorted(root.glob("services/*/pyproject.toml")):
        found.append(Package(manifest, tomllib.loads(manifest.read_text()).get("tool", {}).get("jana")))
    for manifest in sorted(root.glob("apps/*/src-tauri/Cargo.toml")):
        meta = tomllib.loads(manifest.read_text()).get("package", {}).get("metadata", {})
        found.append(Package(manifest, meta.get("jana")))
    return found


def _module_errors(pkg: Package, modules: dict, root: Path) -> list[str]:
    errors = []
    where = pkg.manifest.parent
    rel = pkg.manifest.relative_to(root)
    if pkg.manifest.name == "pyproject.toml":
        name = tomllib.loads(pkg.manifest.read_text())["tool"]["uv"]["build-backend"]["module-name"]
        subpackages = {p.parent.name for p in (where / name).glob("*/__init__.py")}
        for missing in sorted(subpackages - modules.keys()):
            errors.append(f"{rel}: module {name}.{missing} declares no layer")
        for extra in sorted(modules.keys() - subpackages):
            errors.append(f"{rel}: declared module {name}.{extra} does not exist")
    elif pkg.manifest.name == "Cargo.toml":
        src = where / "src"
        sources = {p.stem for p in src.glob("*.rs")} | {p.parent.name for p in src.glob("*/mod.rs")}
        for missing in sorted(sources - modules.keys()):
            errors.append(f"{rel}: module {missing} declares no layer")
        for extra in sorted(modules.keys() - sources):
            errors.append(f"{rel}: declared module {extra} does not exist")
    else:
        for path in modules:
            if not (where / path).is_dir():
                errors.append(f"{rel}: declared module {path} does not exist")
    return errors


def layer_errors(root: Path) -> list[str]:
    errors: list[str] = []
    for pkg in find_packages(root):
        rel = pkg.manifest.relative_to(root)
        decl = pkg.declaration
        if not isinstance(decl, dict) or (("layer" in decl) == ("modules" in decl)):
            errors.append(f"{rel}: must declare exactly one of jana.layer or jana.modules")
            continue
        layers = [decl["layer"]] if "layer" in decl else list(decl["modules"].values())
        errors += [f"{rel}: unknown layer {layer!r}" for layer in layers if layer not in LAYERS]
        if "modules" in decl:
            errors += _module_errors(pkg, decl["modules"], root)
    return errors
