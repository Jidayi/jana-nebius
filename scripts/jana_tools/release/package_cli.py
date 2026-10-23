"""`python -m jana_tools release <command>` for the desktop packaging steps of the release job (M20).

    resources --os OS --sidecars DIR --out DIR     stage the bundle resources (sidecars, keys, legal) for Tauri
    runtime-fetch --os OS --out DIR [--cache DIR]  fetch, check and extract the pinned llama.cpp builds (PLT-04)
    bundle DIR [--manifest OUT]                    the bundle manifest and the PLT-02 budgets
    sign-audit DIR [--dev SIGNATURES] [--os OS]    every PE and Mach-O signed (PLT-05); entitlements minimal
    antivirus RECORD SHA256SUMS                    a clean scan per listed product for the release hashes (PLT-07)
    icons [--release] [--write] [DIR]              the icon sizes, and no placeholder in a release (DSN-25)
    smoke --os OS --installer F [--kit DIR] --out DIR   the packaged smoke test (PLT-01) and PLT-02 on the install
    pins [--release]                               what the owner still has to pin (PLACEHOLDER values)

Each returns a list of problems; an empty list is a pass.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from .. import REPO_ROOT
from . import icons, packaging, runtime_builds, smoke

KEYS = REPO_ROOT / "services" / "agent-core" / "agent_core" / "config"
LEGAL = ("LICENSE", "NOTICE", "THIRD_PARTY_NOTICES")


def _option(args: list[str], name: str) -> str | None:
    return args[args.index(name) + 1] if name in args and args.index(name) + 1 < len(args) else None


def _positional(args: list[str]) -> list[str]:
    out, skip = [], False
    for arg in args:
        if skip:
            skip = False
            continue
        if arg.startswith("--"):
            skip = arg not in ("--release", "--write")
            continue
        out.append(arg)
    return out


def stage_resources(sidecars: Path, out: Path) -> list[str]:
    """Copy the one-dir sidecars, the public keys with the revocation list, and the legal notices into `out`."""
    problems = []
    for name in ("agent-core", "tool-worker"):
        source = sidecars / name
        if not source.is_dir():
            problems.append(f"no {name} bundle in {sidecars}")
            continue
        shutil.copytree(source, out / name, dirs_exist_ok=True)
    (out / "keys").mkdir(parents=True, exist_ok=True)
    for name in ("trust_anchors.json", "revocation_list.json"):
        shutil.copyfile(KEYS / name, out / "keys" / name)
    (out / "legal").mkdir(parents=True, exist_ok=True)
    for name in LEGAL:
        shutil.copyfile(REPO_ROOT / name, out / "legal" / name)
    (out / "config").mkdir(parents=True, exist_ok=True)
    return problems


def _resources(args: list[str]) -> list[str]:
    sidecars, out = _option(args, "--sidecars"), _option(args, "--out")
    if not sidecars or not out:
        return ["usage: release resources --os OS --sidecars DIR --out DIR"]
    return stage_resources(Path(sidecars), Path(out))


def _runtime_fetch(args: list[str]) -> list[str]:
    os_name, out = _option(args, "--os"), _option(args, "--out")
    if os_name not in runtime_builds.OSES or not out:
        return ["usage: release runtime-fetch --os windows|macos|linux --out DIR [--cache DIR]"]
    cache = Path(_option(args, "--cache") or tempfile.mkdtemp())
    try:
        runtime_builds.fetch(runtime_builds.load_pins(), os_name, Path(out), cache)
    except runtime_builds.FetchRefused as error:
        return [str(error)]
    return []


def _bundle(args: list[str]) -> list[str]:
    paths = _positional(args)
    if not paths:
        return ["usage: release bundle DIR [--manifest OUT]"]
    manifest = packaging.bundle_manifest(Path(paths[0]))
    if target := _option(args, "--manifest"):
        packaging.write_json(Path(target), manifest)
    return packaging.budget_errors(manifest)


def _sign_audit(args: list[str]) -> list[str]:
    paths = _positional(args)
    if not paths:
        return ["usage: release sign-audit DIR [--dev SIGNATURES] [--os windows|macos]"]
    root = Path(paths[0])
    dev = _option(args, "--dev")
    if dev:
        verify = packaging.DevSigner.development().verifier(root, json.loads(Path(dev).read_text()))
    elif _option(args, "--os") == "macos":
        verify = packaging.codesign_verifier
    else:
        verify = packaging.signtool_verifier
    return packaging.signature_errors(root, verify) + packaging.entitlement_errors()


def _antivirus(args: list[str]) -> list[str]:
    paths = _positional(args)
    if len(paths) != 2:
        return ["usage: release antivirus RECORD SHA256SUMS"]
    record = json.loads(Path(paths[0]).read_text())
    sums = {}
    for line in Path(paths[1]).read_text().splitlines():
        if line.strip():
            sha, name = line.split(maxsplit=1)
            sums[name.lstrip("*")] = sha
    return packaging.av_errors(record, sums, packaging.av_products())


def _icons(args: list[str]) -> list[str]:
    if "--write" in args:
        icons.write_placeholder()
        return []
    paths = _positional(args)
    return icons.icon_errors(Path(paths[0]) if paths else icons.ICONS, release="--release" in args)


def _smoke(args: list[str]) -> list[str]:
    os_name, installer, out = _option(args, "--os"), _option(args, "--installer"), _option(args, "--out")
    if os_name is None or installer is None or out is None:
        return ["usage: release smoke --os OS --installer FILE [--kit DIR] --out DIR"]
    kit = _option(args, "--kit")
    target = Path(tempfile.mkdtemp())
    installed: list[Path] = []

    def install() -> Path:
        installed.append(smoke.install_from(os_name, Path(installer), target))
        return installed[0]

    report = smoke.run(os_name, _option(args, "--version") or "0.0.0", install,
                       lambda app: smoke.resources_of(os_name, app), Path(kit) if kit else None, Path(out))  # fmt: skip
    problems = [] if report.passed() else smoke.smoke_errors({os_name: report.to_json()}, (os_name,))
    if installed:  # PLT-02 on what was really installed
        manifest = packaging.bundle_manifest(installed[0])
        packaging.write_json(Path(out) / f"{os_name}-bundle-manifest.json", manifest)
        problems += packaging.budget_errors(manifest)
    return problems


# What a development-signed packaged build needs pinned, and what a signed release needs on top.
BUILD_PINS = (
    "scripts/release/runtime-builds.toml",
    "scripts/packaging/requirements-build.txt",
    "scripts/packaging/tauri-cli.version",
)
RELEASE_PINS = (
    "scripts/release/antivirus-products.toml",
    "apps/desktop/src-tauri/tauri.release.conf.json",
    "apps/desktop/src-tauri/tauri.updater.conf.json",
)


def owner_pins(release: bool) -> list[str]:
    """Every value the owner still has to provide (PLACEHOLDER lines): for a packaged build, or for a signed release."""
    missing = []
    for name in (*BUILD_PINS, *(RELEASE_PINS if release else ())):
        for number, line in enumerate((REPO_ROOT / name).read_text().splitlines(), 1):
            if "PLACEHOLDER" in line and not line.lstrip().startswith("#"):
                missing.append(f"{name}:{number}: {line.strip()[:100]}")
    if release:
        from signing_service.hierarchy import production_anchors

        if not production_anchors().roots:
            missing.append("trust_anchors.json: no release root yet (the key ceremony, SEC-12)")
        missing += release_placeholders()
    return missing


POLICY = "services/agent-core/agent_core/net/policy.json"
REVIEWERS = "services/signing-service/signing_service/safety_reviewers.json"
RESOURCES = "content/agent/safety/resources.yaml"


def release_placeholders() -> list[str]:
    """What a signed release still lacks outside the pin files: real service hosts and TLS pins for the pilot and
    production environments (SEC-31, OPS-35), a content safety reviewer key (CUR-27) and the pilot country's verified
    helplines (PRV-14, TABLE PRD-22a)."""
    import yaml

    found = []
    policy = json.loads((REPO_ROOT / POLICY).read_text())
    for environment in ("pilot", "production"):
        hosts = policy["services"].get(environment, {})
        placeholder = sorted(service for service, host in hosts.items() if not host or host.endswith(".invalid"))
        if placeholder:
            found.append(f"{POLICY}: {environment} hosts are placeholders (.invalid): {', '.join(placeholder)}")
        if len(policy["pins"].get(environment) or []) < 2:
            found.append(f"{POLICY}: {environment} has no primary and backup TLS pins (SEC-31)")
    if not json.loads((REPO_ROOT / REVIEWERS).read_text()).get("reviewers"):
        found.append(f"{REVIEWERS}: no content safety reviewer key yet (CUR-27)")
    resources = yaml.safe_load((REPO_ROOT / RESOURCES).read_text()) or {}
    if not resources.get("country") or not resources.get("verified_by"):
        found.append(f"{RESOURCES}: no pilot country or verifying child-protection partner yet (PRV-14, PRD-22)")
    if not any(isinstance(e, dict) and e.get("verified") is True for e in resources.get("entries") or []):
        found.append(f"{RESOURCES}: no verified emergency number or child helpline yet (PRV-14)")
    return found


def _pins(args: list[str]) -> list[str]:
    return owner_pins(release="--release" in args)


COMMANDS: dict[str, Callable[[list[str]], list[str]]] = {
    "pins": _pins,
    "resources": _resources,
    "runtime-fetch": _runtime_fetch,
    "bundle": _bundle,
    "sign-audit": _sign_audit,
    "antivirus": _antivirus,
    "icons": _icons,
    "smoke": _smoke,
}
