"""Supply-chain controls (SEC-22) and licence policy (SEC-23).

- Lockfiles: every resolved third-party package carries a hash, and installs are frozen
  (the manifests match the lockfiles).
- CI actions are pinned by commit.
- Every direct dependency has a review record (purpose, licence, maintainer health, size).
- SBOMs (CycloneDX 1.6 JSON) list every component bundled into each release artefact, with
  licences read from the installed package metadata; THIRD_PARTY_NOTICES is generated from them.
- Shipped components must carry an approved licence; LGPL needs a recorded review.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
import re
import subprocess
import tomllib
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from email.parser import HeaderParser
from pathlib import Path

import yaml

from . import REPO_ROOT

# --- lockfiles ------------------------------------------------------------------------------


def pnpm_lock_errors(text: str) -> list[str]:
    data = yaml.safe_load(text) or {}
    errors = []
    for key, entry in (data.get("packages") or {}).items():
        resolution = (entry or {}).get("resolution", {})
        if "directory" in resolution:  # a workspace or local directory, not a download
            continue
        if not str(resolution.get("integrity", "")).startswith(("sha512-", "sha384-", "sha256-")):
            errors.append(f"pnpm-lock.yaml: {key} has no integrity hash")
    return errors


def uv_lock_errors(text: str) -> list[str]:
    errors = []
    for package in tomllib.loads(text).get("package", []):
        source = package.get("source", {})
        if "registry" not in source:
            if "git" in source or "url" in source:
                errors.append(f"uv.lock: {package['name']} comes from an unhashed {next(iter(source))} source")
            continue  # workspace members and local paths
        artefacts = ([package["sdist"]] if "sdist" in package else []) + package.get("wheels", [])
        if not artefacts or any(not str(a.get("hash", "")).startswith("sha256:") for a in artefacts):
            errors.append(f"uv.lock: {package['name']} {package.get('version')} has a download without a hash")
    return errors


def cargo_lock_errors(text: str) -> list[str]:
    errors = []
    for package in tomllib.loads(text).get("package", []):
        source = package.get("source")
        if source is None:
            continue  # a workspace crate
        if not source.startswith("registry+") or not re.fullmatch(r"[0-9a-f]{64}", package.get("checksum", "")):
            errors.append(f"Cargo.lock: {package['name']} {package['version']} has no checksum")
    return errors


Runner = Callable[[list[str], Path], subprocess.CompletedProcess]


def _run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)


FROZEN_CHECKS = (
    ("pnpm-lock.yaml", ["corepack", "pnpm", "install", "--frozen-lockfile", "--lockfile-only", "--offline"]),
    ("uv.lock", ["uv", "lock", "--check", "--offline"]),
    ("Cargo.lock", ["cargo", "metadata", "--locked", "--offline", "--format-version", "1"]),
)


def lockfile_errors(root: Path = REPO_ROOT, run: Runner = _run) -> list[str]:
    errors = []
    for name, check in (
        ("pnpm-lock.yaml", pnpm_lock_errors),
        ("uv.lock", uv_lock_errors),
        ("Cargo.lock", cargo_lock_errors),
    ):
        path = root / name
        errors += check(path.read_text()) if path.is_file() else [f"{name} is missing"]
    for name, cmd in FROZEN_CHECKS:
        result = run(cmd, root)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout).strip().splitlines()[-1:] or [""]
            errors.append(f"{name} does not match its manifests (frozen install fails): {detail[0]}")
    return errors


# --- CI actions -----------------------------------------------------------------------------

_USES = re.compile(r"^\s*-?\s*uses:\s*([^\s#]+)", re.MULTILINE)


def action_pin_errors(root: Path = REPO_ROOT) -> list[str]:
    errors = []
    for path in sorted((root / ".github").rglob("*.yml")):
        for ref in _USES.findall(path.read_text()):
            if ref.startswith("./"):
                continue
            if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", ref):
                errors.append(f"{path.relative_to(root)}: action {ref} is not pinned by commit")
    return errors


# --- dependency reviews ---------------------------------------------------------------------

REVIEW_FIELDS = ("purpose", "licence", "maintainer_health", "size")


def direct_dependencies(root: Path = REPO_ROOT) -> dict[str, set[str]]:
    """Direct dependencies by ecosystem, from every manifest in the workspaces."""
    deps: dict[str, set[str]] = {"npm": set(), "pypi": set(), "cargo": set()}
    workspace = {json.loads(p.read_text())["name"] for p in root.glob("packages/*/package.json")}
    for manifest in [
        root / "package.json",
        *root.glob("apps/desktop/package.json"),
        *root.glob("packages/*/package.json"),
    ]:
        data = json.loads(manifest.read_text())
        for field in ("dependencies", "devDependencies", "optionalDependencies"):
            deps["npm"] |= set(data.get(field, {})) - workspace
    name = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*")
    members = {tomllib.loads(p.read_text())["project"]["name"] for p in root.glob("services/*/pyproject.toml")}
    for manifest in [
        root / "pyproject.toml",
        root / "scripts" / "pyproject.toml",
        *root.glob("services/*/pyproject.toml"),
    ]:
        data = tomllib.loads(manifest.read_text())
        specs = list(data.get("project", {}).get("dependencies", []))
        for group in data.get("dependency-groups", {}).values():
            specs += [s for s in group if isinstance(s, str)]
        for spec in specs:
            match = name.match(spec)
            if match and match[0] not in members:
                deps["pypi"].add(match[0].lower())
    for manifest in root.glob("apps/*/src-tauri/Cargo.toml"):
        data = tomllib.loads(manifest.read_text())
        for field in ("dependencies", "dev-dependencies", "build-dependencies"):
            deps["cargo"] |= set(data.get(field, {}))
    return deps


def dependency_review_errors(root: Path = REPO_ROOT) -> list[str]:
    path = root / "dependency-reviews.toml"
    reviews = tomllib.loads(path.read_text()) if path.is_file() else {}
    errors = []
    for ecosystem, names in direct_dependencies(root).items():
        recorded = reviews.get(ecosystem, {})
        for dep in sorted(names):
            entry = recorded.get(dep)
            if entry is None:
                errors.append(f"dependency-reviews.toml: no review for {ecosystem} dependency {dep}")
                continue
            missing = [f for f in REVIEW_FIELDS if not str(entry.get(f, "")).strip()]
            if missing:
                errors.append(f"dependency-reviews.toml: {ecosystem} {dep} lacks {', '.join(missing)}")
    return errors


# --- SBOM -----------------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class Component:
    ecosystem: str
    name: str
    version: str
    licence: str  # SPDX expression, or "UNKNOWN"

    @property
    def purl(self) -> str:
        return f"pkg:{self.ecosystem}/{self.name}@{self.version}"


@dataclass(frozen=True)
class Artefact:
    name: str
    ecosystem: str
    root: str  # uv member, pnpm importer path, or cargo package name


# Release artefacts (S1): the sidecars, the desktop shell and the desktop UI bundle.
ARTEFACTS = (
    Artefact("agent-core", "pypi", "jana-agent-core"),
    Artefact("tool-worker", "pypi", "jana-tool-worker"),
    Artefact("perception-worker", "pypi", "jana-perception-worker"),
    Artefact("desktop-shell", "cargo", "jana-shell"),
    Artefact("desktop-ui", "npm", "apps/desktop"),
)

# The desktop release platforms (PLT-01), including Intel and Apple Silicon Macs.
# Cargo's unfiltered graph also includes Android and WebAssembly packages that are never shipped in the desktop.
DESKTOP_RUST_TARGETS = (
    "x86_64-pc-windows-msvc",
    "x86_64-apple-darwin",
    "aarch64-apple-darwin",
    "x86_64-unknown-linux-gnu",
)


def _python_licence(name: str, site_packages: Path | None) -> str:
    if site_packages is None:
        return "UNKNOWN"
    if name == "pypdfium2":
        from .study_licences import metadata_licence

        reviewed = metadata_licence(name, site_packages)
        if reviewed:
            return reviewed
    normalised = re.sub(r"[-_.]+", "_", name).lower()
    for meta in site_packages.glob("*.dist-info/METADATA"):
        if re.sub(r"[-_.]+", "_", meta.parent.name.removesuffix(".dist-info").rsplit("-", 1)[0]).lower() != normalised:
            continue
        headers = HeaderParser().parsestr(meta.read_text(errors="replace"))
        if headers.get("License-Expression"):
            return str(headers["License-Expression"])
        classifiers = [c.split(" :: ")[-1] for c in headers.get_all("Classifier", []) if c.startswith("License ::")]
        mapped = [CLASSIFIER_SPDX.get(c, c) for c in classifiers]
        if mapped:
            return " OR ".join(mapped)
        licence = (headers.get("License") or "").strip()
        return licence if licence and "\n" not in licence and len(licence) < 64 else "UNKNOWN"
    return "UNKNOWN"


CLASSIFIER_SPDX = {
    "MIT License": "MIT",
    "BSD License": "BSD-3-Clause",
    "Apache Software License": "Apache-2.0",
    "ISC License (ISCL)": "ISC",
    "Python Software Foundation License": "PSF-2.0",
    "Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
    "GNU General Public License v3 (GPLv3)": "GPL-3.0-only",
    "GNU General Public License v2 (GPLv2)": "GPL-2.0-only",
    "GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    "GNU Lesser General Public License v3 or later (LGPLv3+)": "LGPL-3.0-or-later",
}


def python_closure(lock_text: str, member: str, site_packages: Path | None) -> list[Component]:
    packages = {p["name"]: p for p in tomllib.loads(lock_text).get("package", [])}
    seen: set[str] = set()
    stack = [d["name"] for d in packages[member].get("dependencies", [])]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        stack += [d["name"] for d in packages.get(name, {}).get("dependencies", [])]
    return sorted(
        Component("pypi", n, packages[n].get("version", "0"), _python_licence(n, site_packages))
        for n in seen
        if "registry" in packages.get(n, {}).get("source", {})
    )


def _npm_manifest(root: Path, name: str, version: str) -> Path | None:
    """The installed package.json in pnpm's store (directory names may carry a peer suffix)."""
    store = root / "node_modules" / ".pnpm"
    prefix = f"{name.replace('/', '+')}@{version}"
    for candidate in sorted(store.glob(f"{prefix}*/node_modules/{name}/package.json")):
        rest = candidate.parts[len(store.parts)][len(prefix) :]
        if rest == "" or rest.startswith("_"):
            return candidate
    return None


def _npm_licence(root: Path, name: str, version: str) -> str:
    manifest = _npm_manifest(root, name, version)
    if manifest is None:
        return "UNKNOWN"
    licence = json.loads(manifest.read_text()).get("license")
    return licence if isinstance(licence, str) and licence else "UNKNOWN"


def npm_closure(lock_text: str, importer: str, root: Path, include_dev: bool = False) -> list[Component]:
    data = yaml.safe_load(lock_text) or {}
    importers, snapshots = data.get("importers", {}), data.get("snapshots", {}) or {}
    fields = ["dependencies", "optionalDependencies"] + (["devDependencies"] if include_dev else [])
    seen_importers: set[str] = set()
    seen: set[str] = set()
    pending_importers = [importer]
    stack: list[str] = []
    optional_keys: set[str] = set()
    while pending_importers:
        current = pending_importers.pop()
        if current in seen_importers:
            continue
        seen_importers.add(current)
        for field in fields:
            for name, spec in (importers.get(current, {}).get(field) or {}).items():
                version = str(spec["version"])
                if version.startswith("link:"):
                    # A workspace link ("link:../../packages/ui") names another importer; normalise the "..".
                    pending_importers.append(posixpath.normpath(posixpath.join(current, version.removeprefix("link:"))))
                else:
                    stack.append(f"{name}@{version}")
    optional: list[str] = []
    while stack or optional:
        key = stack.pop() if stack else optional.pop()
        if key in seen:
            continue
        name, _, bare = key.split("(", 1)[0].rpartition("@")
        if key in optional_keys and _npm_manifest(root, name, bare) is None:
            continue  # an optional, platform-specific package not installed on this platform
        seen.add(key)
        snapshot = snapshots.get(key) or {}
        stack += [f"{n}@{v}" for n, v in (snapshot.get("dependencies") or {}).items()]
        for n, v in (snapshot.get("optionalDependencies") or {}).items():
            optional_keys.add(f"{n}@{v}")
            optional.append(f"{n}@{v}")
    components = set()
    for key in seen:
        name, _, bare = key.split("(", 1)[0].rpartition("@")
        components.add(Component("npm", name, bare, _npm_licence(root, name, bare)))
    return sorted(components)


def cargo_closure(metadata: dict, package: str) -> list[Component]:
    by_id = {p["id"]: p for p in metadata["packages"]}
    nodes = {n["id"]: n for n in metadata["resolve"]["nodes"]}
    start = next(p["id"] for p in metadata["packages"] if p["name"] == package and p["source"] is None)
    seen: set[str] = set()
    stack = [start]
    while stack:
        node = nodes[stack.pop()]
        for dep in node.get("deps", []):
            if any(k.get("kind") in (None, "normal") for k in dep.get("dep_kinds", [])) and dep["pkg"] not in seen:
                seen.add(dep["pkg"])
                stack.append(dep["pkg"])
    return sorted(
        Component("cargo", by_id[i]["name"], by_id[i]["version"], by_id[i].get("license") or "UNKNOWN")
        for i in seen
        if by_id[i]["source"] is not None
    )


def _site_packages(root: Path) -> Path | None:
    found = sorted((root / ".venv" / "lib").glob("python3*/site-packages"))
    if not found:
        found = sorted((root / ".venv" / "Lib").glob("site-packages"))
    return found[0] if found else None


# Third-party files bundled into an artefact as copies rather than as resolved packages (the D89 brand faces, DSN-06).
# Each manifest lists components with the sha256 of every copied file; they join the artefact's SBOM and the notices.
VENDORED: dict[str, tuple[str, ...]] = {"desktop-ui": ("packages/ui/assets/fonts/vendored.json",)}


def vendored_components(artefact: Artefact, root: Path = REPO_ROOT) -> list[Component]:
    found = set()
    for manifest in VENDORED.get(artefact.name, ()):
        path = root / manifest
        if path.is_file():
            for c in json.loads(path.read_text())["components"]:
                found.add(Component(c["ecosystem"], c["name"], c["version"], c["licence"]))
    return sorted(found)


def vendored_errors(root: Path = REPO_ROOT) -> list[str]:
    """Every vendored file is present, unchanged (its recorded sha256) and listed; nothing unlisted sits beside it."""
    errors = []
    for manifests in VENDORED.values():
        for manifest in manifests:
            path = root / manifest
            if not path.is_file():
                errors.append(f"{manifest}: vendored manifest missing")
                continue
            listed: set[Path] = {path}
            for c in json.loads(path.read_text())["components"]:
                for name, sha in c["files"].items():
                    file = path.parent / name
                    listed.add(file)
                    if not file.is_file():
                        errors.append(f"{manifest}: {name} of {c['name']} is missing")
                    elif hashlib.sha256(file.read_bytes()).hexdigest() != sha:
                        errors.append(f"{manifest}: {name} of {c['name']} does not match its recorded sha256")
            for file in sorted(path.parent.rglob("*")):
                if file.is_file() and file.suffix in (".woff2", ".woff", ".ttf", ".otf") and file not in listed:
                    errors.append(f"{manifest}: {file.relative_to(path.parent)} is bundled but not listed")
    return errors


def artefact_components(artefact: Artefact, root: Path = REPO_ROOT) -> list[Component]:
    if artefact.ecosystem == "pypi":
        closure = python_closure((root / "uv.lock").read_text(), artefact.root, _site_packages(root))
        if any(c.name == "pypdfium2" for c in closure):
            from .study_licences import native_component

            native = native_component(root)
            if native:
                closure.append(Component("generic", native["name"], native["version"], native["licence"]))
        return sorted(closure)
    if artefact.ecosystem == "npm":
        closure = npm_closure((root / "pnpm-lock.yaml").read_text(), artefact.root, root)
        return sorted(set(closure) | set(vendored_components(artefact, root)))
    components: set[Component] = set()
    for target in DESKTOP_RUST_TARGETS:
        metadata = json.loads(
            subprocess.run(
                ["cargo", "metadata", "--locked", "--offline", "--format-version", "1", "--filter-platform", target],
                cwd=root, capture_output=True, text=True, check=True,
            ).stdout
        )  # fmt: skip
        components.update(cargo_closure(metadata, artefact.root))
    return sorted(components)


def cyclonedx(artefact: Artefact, components: Iterable[Component]) -> dict:
    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.6",
        "serialNumber": f"urn:uuid:{uuid.uuid5(uuid.NAMESPACE_URL, 'jana:' + artefact.name)}",
        "version": 1,
        "metadata": {"component": {"type": "application", "name": artefact.name, "bom-ref": artefact.name}},
        "components": [
            {
                "type": "library",
                "name": c.name,
                "version": c.version,
                "purl": c.purl,
                "bom-ref": c.purl,
                "licenses": [{"expression": c.licence}],
            }
            for c in components
        ],
    }


def write_sboms(out: Path, root: Path = REPO_ROOT) -> dict[str, list[Component]]:
    out.mkdir(parents=True, exist_ok=True)
    result = {}
    for artefact in ARTEFACTS:
        components = artefact_components(artefact, root)
        (out / f"{artefact.name}.cdx.json").write_text(json.dumps(cyclonedx(artefact, components), indent=2) + "\n")
        result[artefact.name] = components
    return result


# --- licences (SEC-23) ----------------------------------------------------------------------

# The SEC-23 approved list; MIT-CMU by D69.
APPROVED = frozenset({
    "MIT", "MIT-0", "MIT-CMU", "BSD-2-Clause", "BSD-3-Clause", "0BSD", "Apache-2.0", "ISC", "Zlib", "PSF-2.0",
    "Python-2.0", "CC0-1.0", "MPL-2.0", "Unicode-3.0", "Unicode-DFS-2016",
})  # fmt: skip
NEEDS_REVIEW = re.compile(r"^LGPL-")
_WITH = re.compile(r"\s+WITH\s+[\w.-]+")


def _licence_ok(expression: str, reviewed: bool) -> bool:
    # Cargo's legacy notation "MIT/Apache-2.0" means "MIT OR Apache-2.0".
    expr = _WITH.sub("", expression).replace("/", " OR ").replace("(", " ").replace(")", " ")
    for alternative in re.split(r"\s+OR\s+", expr.strip()):
        terms = [t.strip() for t in re.split(r"\s+AND\s+", alternative) if t.strip()]
        if terms and all(t in APPROVED or (reviewed and NEEDS_REVIEW.match(t)) for t in terms):
            return True
    return False


# Bundled fonts (DSN-06 requires OFL-1.1 or MIT faces). SEC-23's list does not name OFL, so it is allowed for font
# packages only (working assumption, gaps.md).
FONT_LICENCES = frozenset({"OFL-1.1"})
FONT_PACKAGES = re.compile(r"^@fontsource(?:-variable)?/")


def licence_errors(components: Iterable[Component], lgpl_reviews: set[str]) -> list[str]:
    from .study_licences import native_component

    native = native_component()
    errors = []
    for c in components:
        if native and c == Component("generic", native["name"], native["version"], native["licence"]):
            continue  # Only this owner-reviewed native bundle; hashes are checked by shipped_licence_errors.
        if c.licence in FONT_LICENCES and FONT_PACKAGES.match(c.name):
            continue
        if not _licence_ok(c.licence, reviewed=c.name in lgpl_reviews):
            why = "needs a recorded LGPL review" if NEEDS_REVIEW.search(c.licence) else "is not on the approved list"
            errors.append(f"{c.purl}: licence {c.licence} {why}")
    return errors


def lgpl_reviews(root: Path = REPO_ROOT) -> set[str]:
    path = root / "dependency-reviews.toml"
    reviews = tomllib.loads(path.read_text()) if path.is_file() else {}
    return {
        name for eco in reviews.values() if isinstance(eco, dict) for name, e in eco.items() if e.get("lgpl_review")
    }


def render_notices(per_artefact: dict[str, list[Component]]) -> str:
    components = sorted({c for cs in per_artefact.values() for c in cs})
    lines = [
        "THIRD-PARTY NOTICES",
        "",
        "GENERATED by `python -m jana_tools notices --write` from the release SBOMs. Do not edit by hand.",
        "Lists every third-party component bundled into a Jana release artefact, with its licence (SEC-23).",
        f"Artefacts: {', '.join(a.name for a in ARTEFACTS)}.",
        "",
    ]
    if not components:
        lines.append("No third-party components are bundled yet.")
    for c in components:
        lines.append(f"{c.name} {c.version} ({c.ecosystem}): {c.licence}")
    if any(c.name == "pypdfium2" for c in components):
        lines += [
            "",
            "This software is based in part on the work of the Independent JPEG Group.",
            "This software is based in part on the work of the FreeType Team (https://freetype.org/).",
            "Complete PDFium and bundled library licence texts accompany the application in legal/pypdfium2.",
        ]
    return "\n".join(lines) + "\n"


def notices_errors(root: Path = REPO_ROOT) -> list[str]:
    expected = render_notices({a.name: artefact_components(a, root) for a in ARTEFACTS})
    path = root / "THIRD_PARTY_NOTICES"
    if not path.is_file() or path.read_text() != expected:
        return ["THIRD_PARTY_NOTICES is stale; run: uv run python -m jana_tools notices --write"]
    return []


def shipped_licence_errors(root: Path = REPO_ROOT) -> list[str]:
    from .study_licences import audit

    reviews = lgpl_reviews(root)
    return audit(_site_packages(root), root) + [
        e for a in ARTEFACTS for e in licence_errors(artefact_components(a, root), reviews)
    ]
