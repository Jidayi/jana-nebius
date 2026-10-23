"""SEC-22 supply-chain controls and SEC-23 licence scanning."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import yaml
from jana_tools import REPO_ROOT
from jana_tools.supply_chain import (
    ARTEFACTS,
    Component,
    action_pin_errors,
    artefact_components,
    cargo_lock_errors,
    dependency_review_errors,
    licence_errors,
    lockfile_errors,
    notices_errors,
    npm_closure,
    pnpm_lock_errors,
    python_closure,
    render_notices,
    uv_lock_errors,
    vendored_components,
    vendored_errors,
    write_sboms,
)

MANIFESTS = (
    "package.json", "pnpm-lock.yaml", "pnpm-workspace.yaml", "pyproject.toml", "uv.lock", ".python-version",
    "Cargo.toml", "Cargo.lock", "rust-toolchain.toml",
)  # fmt: skip


def _manifest_copy(tmp: Path) -> Path:
    """The workspaces' manifests and lockfiles (enough for the frozen checks)."""
    root = tmp / "repo"
    for rel in MANIFESTS:
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(REPO_ROOT / rel, root / rel)
    for pattern in ("apps/desktop/package.json", "apps/studio/package.json", "packages/*/package.json",
                    "scripts/pyproject.toml", "services/*/pyproject.toml", "apps/desktop/src-tauri/Cargo.toml",
                    "apps/studio/src-tauri/Cargo.toml"):  # fmt: skip
        for path in REPO_ROOT.glob(pattern):
            dest = root / path.relative_to(REPO_ROOT)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
    for module in ("services/agent-core/agent_core", "services/tool-worker/tool_worker",
                   "services/perception-worker/perception_worker", "services/pack-builder/pack_builder",
                   "scripts/jana_tools"):  # fmt: skip
        (root / module).mkdir(parents=True, exist_ok=True)
        (root / module / "__init__.py").write_text("")
    (root / "apps/desktop/src-tauri/src").mkdir(parents=True, exist_ok=True)
    for rs in ("main.rs", "net.rs"):
        shutil.copy2(REPO_ROOT / "apps/desktop/src-tauri/src" / rs, root / "apps/desktop/src-tauri/src" / rs)
    # The studio is a member of both workspaces (M22): cargo needs its crate to have a target.
    (root / "apps/studio/src-tauri/src").mkdir(parents=True, exist_ok=True)
    (root / "apps/studio/src-tauri/src/main.rs").write_text("fn main() {}\n")
    return root


def _edit(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    assert old in text
    path.write_text(text.replace(old, new, 1))


def sec22_frozen_hashed_lockfiles(tmp_path: Path):
    assert lockfile_errors() == []
    assert action_pin_errors() == []
    assert dependency_review_errors() == []

    # A manifest that no longer matches its lockfile fails the frozen install, per toolchain.
    root = _manifest_copy(tmp_path)
    assert lockfile_errors(root) == []
    ui = root / "packages/ui/package.json"
    manifest = json.loads(ui.read_text())
    manifest.setdefault("dependencies", {})["left-pad"] = "1.3.0"
    ui.write_text(json.dumps(manifest, indent=2))
    _edit(root / "services/tool-worker/pyproject.toml", "dependencies = [", 'dependencies = ["requests>=2", ')
    _edit(root / "apps/desktop/src-tauri/Cargo.toml", "[dependencies]\n", '[dependencies]\nleft-pad-rs = "0.1"\n')
    errors = lockfile_errors(root)
    assert [e.split(" does not match")[0] for e in errors] == ["pnpm-lock.yaml", "uv.lock", "Cargo.lock"]

    # A resolved dependency without a hash fails, in every lockfile format.
    pnpm = (REPO_ROOT / "pnpm-lock.yaml").read_text()
    stripped = re.sub(r"resolution: \{integrity: [^}]+\}", "resolution: {tarball: https://example.invalid/x.tgz}",
                      pnpm, count=1)  # fmt: skip
    assert len(pnpm_lock_errors(stripped)) == 1
    uv = (REPO_ROOT / "uv.lock").read_text()
    assert len(uv_lock_errors(re.sub(r', hash = "sha256:[0-9a-f]+"', "", uv, count=1))) == 1
    assert uv_lock_errors('[[package]]\nname = "x"\nversion = "1"\nsource = { git = "https://example.invalid/x" }\n')
    cargo = '[[package]]\nname = "serde"\nversion = "1.0.0"\nsource = "registry+https://github.com/rust-lang/crates.io-index"\n'
    assert cargo_lock_errors(cargo) == ["Cargo.lock: serde 1.0.0 has no checksum"]
    assert cargo_lock_errors(cargo + f'checksum = "{"a" * 64}"\n') == []

    # CI actions are pinned by commit, and every direct dependency has a review record.
    (root / ".github" / "workflows").mkdir(parents=True)
    (root / ".github/workflows/x.yml").write_text("jobs:\n  a:\n    steps:\n      - uses: actions/checkout@v4\n")
    assert action_pin_errors(root) == [".github/workflows/x.yml: action actions/checkout@v4 is not pinned by commit"]
    shutil.copy2(REPO_ROOT / "dependency-reviews.toml", root / "dependency-reviews.toml")
    assert "dependency-reviews.toml: no review for npm dependency left-pad" in dependency_review_errors(root)


def _installed_npm(root: Path) -> set[tuple[str, str]]:
    """Every package pnpm installed, read from its store (independent of the lockfile walk)."""
    found = set()
    for entry in (root / "node_modules" / ".pnpm").iterdir():
        if entry.name in ("node_modules", "lock.yaml") or "@" not in entry.name.lstrip("@"):
            continue
        name, _, version = entry.name.split("_", 1)[0].rpartition("@")
        found.add((name.replace("+", "/"), version))
    return found


def sec22_sbom_complete(tmp_path: Path):
    per_artefact = write_sboms(tmp_path / "sbom")
    assert sorted(per_artefact) == sorted(a.name for a in ARTEFACTS)
    for artefact in ARTEFACTS:
        bom = json.loads((tmp_path / "sbom" / f"{artefact.name}.cdx.json").read_text())
        assert bom["bomFormat"] == "CycloneDX" and bom["specVersion"] == "1.6"
        assert bom["metadata"]["component"]["name"] == artefact.name
        listed = {(c["name"], c["version"]) for c in bom["components"]}
        assert listed == {(c.name, c.version) for c in artefact_components(artefact)}
        assert all(c["licenses"][0]["expression"] for c in bom["components"])

    # Files bundled as copies (the D89 brand faces) are components of their artefact too, and are what they claim.
    desktop = next(a for a in ARTEFACTS if a.name == "desktop-ui")
    vendored = vendored_components(desktop)
    assert {c.name for c in vendored} >= {"@fontsource-variable/funnel-sans", "@fontsource-variable/funnel-display"}
    assert set(vendored) <= set(artefact_components(desktop))
    assert vendored_errors() == []
    copy = tmp_path / "copy"
    shutil.copytree(REPO_ROOT / "packages" / "ui" / "assets" / "fonts", copy / "packages" / "ui" / "assets" / "fonts")
    (copy / "packages/ui/assets/fonts/funnel-sans/funnel-sans-latin-wght-normal.woff2").write_bytes(b"changed")
    (copy / "packages/ui/assets/fonts/stray.woff2").write_bytes(b"unlisted")
    assert vendored_errors(copy) == [
        "packages/ui/assets/fonts/vendored.json: funnel-sans/funnel-sans-latin-wght-normal.woff2 of "
        "@fontsource-variable/funnel-sans does not match its recorded sha256",
        "packages/ui/assets/fonts/vendored.json: stray.woff2 is bundled but not listed",
    ]

    # The closure walk is complete: checked against independent sources on non-empty closures.
    python = python_closure((REPO_ROOT / "uv.lock").read_text(), "jana-tools", None)
    exported = subprocess.run(
        # No dependency group at all: neither the dev tools nor the test-only `conformance` libraries ship.
        ["uv", "export", "--package", "jana-tools", "--no-default-groups", "--frozen", "--no-hashes",
         "--no-emit-workspace", "--no-header", "--no-annotate"],
        cwd=REPO_ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    assert {(c.name, c.version) for c in python} == {
        tuple(line.split(";")[0].strip().split("==")) for line in exported.splitlines() if "==" in line
    }
    lock = (REPO_ROOT / "pnpm-lock.yaml").read_text()
    walked = set()
    for importer in yaml.safe_load(lock)["importers"]:  # every workspace member, with its dev tooling
        walked |= {(c.name, c.version) for c in npm_closure(lock, importer, REPO_ROOT, include_dev=True)}
    assert walked == _installed_npm(REPO_ROOT)


def sec23_disallowed_licence_fails():
    shipped = [
        Component("npm", "katex", "0.16.11", "MIT"),
        Component("pypi", "sympy", "1.14.0", "BSD-3-Clause"),
        Component("cargo", "either", "1.13.0", "MIT OR Apache-2.0"),
        Component("cargo", "unicode-ident", "1.0.0", "(MIT OR Apache-2.0) AND Unicode-3.0"),
        Component("cargo", "x", "1.0.0", "Apache-2.0 WITH LLVM-exception"),
    ]
    assert licence_errors(shipped, set()) == []
    bad = [
        Component("pypi", "gpl-thing", "1.0", "GPL-3.0-only"),
        Component("npm", "agpl-thing", "1.0", "AGPL-3.0-or-later"),
        Component("npm", "mystery", "1.0", "UNKNOWN"),
        Component("cargo", "busl", "1.0", "BUSL-1.1"),
        Component("npm", "nc", "1.0", "CC-BY-NC-4.0"),
        Component("cargo", "mixed", "1.0", "MIT AND GPL-2.0-only"),
        Component("pypi", "lgpl-thing", "1.0", "LGPL-3.0-only"),
    ]
    assert licence_errors(bad, set()) == [
        "pkg:pypi/gpl-thing@1.0: licence GPL-3.0-only is not on the approved list",
        "pkg:npm/agpl-thing@1.0: licence AGPL-3.0-or-later is not on the approved list",
        "pkg:npm/mystery@1.0: licence UNKNOWN is not on the approved list",
        "pkg:cargo/busl@1.0: licence BUSL-1.1 is not on the approved list",
        "pkg:npm/nc@1.0: licence CC-BY-NC-4.0 is not on the approved list",
        "pkg:cargo/mixed@1.0: licence MIT AND GPL-2.0-only is not on the approved list",
        "pkg:pypi/lgpl-thing@1.0: licence LGPL-3.0-only needs a recorded LGPL review",
    ]
    assert licence_errors(bad[-1:], {"lgpl-thing"}) == []


def sec23_attributions_complete():
    """THIRD_PARTY_NOTICES lists every SBOM component with its licence (the About -> Licences page
    that renders it arrives in M5; gaps.md G5)."""
    assert notices_errors() == []
    notices = (REPO_ROOT / "THIRD_PARTY_NOTICES").read_text()
    for artefact in ARTEFACTS:
        for c in artefact_components(artefact):
            assert f"{c.name} {c.version} ({c.ecosystem}): {c.licence}" in notices

    sample = {"desktop-ui": [Component("npm", "katex", "0.16.11", "MIT")], "agent-core": []}
    assert "katex 0.16.11 (npm): MIT" in render_notices(sample)
    assert "No third-party components are bundled yet." in render_notices({})
