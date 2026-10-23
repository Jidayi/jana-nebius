"""Release checks on a built desktop bundle (PLT-02, PLT-05, PLT-07).

**Bundle manifest and budgets (PLT-02).** Every file of a built bundle belongs to one component of TABLE PLT-02a:
the shell with its UI assets, the agent core and tool worker one-dir sidecars, the llama.cpp builds per variant, the
configuration and signed assets, and the public keys with the revocation list. A file that belongs to none fails the
build, and so does a component more than `bundle_budget_tolerance` over its budget, or the whole bundle over the base
installer total. The manifest written alongside lists every file with its size, sha256 and component; the signing
audit and the antivirus record work from it.

**Signature audit (PLT-05).** Every PE (`.exe`, `.dll`) and Mach-O file in the bundle must be signed: on Windows by
Authenticode with a timestamp (`signtool verify /pa /tw`), on macOS by a Developer ID with the hardened runtime
(`codesign --verify --strict` and the `runtime` flag); development builds are signed with the development code key
instead (`DevSigner`, a detached Ed25519 signature per file in `bundle-signatures.json`, never trusted by a release).
macOS entitlements must be the minimum: the two that weaken code signing are refused unless the release notes record
a reason.

**Antivirus record (PLT-07).** The release checklist names the products (Microsoft Defender plus the most common on
pilot machines); the record must hold a clean scan by each for the exact sha256 of every release artefact, and the
Microsoft submission id. Any detection, any missing product or any hash that differs blocks the release.
"""

from __future__ import annotations

import base64
import hashlib
import json
import plistlib
import subprocess
import tomllib
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from agent_core.config import Settings
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from .. import REPO_ROOT

MB = 1024 * 1024
TAURI = REPO_ROOT / "apps" / "desktop" / "src-tauri"
ENTITLEMENTS = TAURI / "entitlements.plist"
AV_PRODUCTS = REPO_ROOT / "scripts" / "release" / "antivirus-products.toml"
WEAKENING_ENTITLEMENTS = (
    "com.apple.security.cs.allow-unsigned-executable-memory",
    "com.apple.security.cs.disable-library-validation",
)
# TABLE PLT-02a: component -> its budget key. The perception worker ships inside its pack, not the base installer.
COMPONENTS = {
    "shell": "bundle_budget_shell_mb",
    "agent_core": "bundle_budget_agent_core_mb",
    "tool_worker": "bundle_budget_tool_worker_mb",
    "runtime": "bundle_budget_runtime_mb",
    "config": "bundle_budget_config_mb",
    "keys": "bundle_budget_keys_mb",
}
SHELL_FILES = frozenset({"jana-shell", "jana-shell.exe", "jana-precheck", "jana-precheck.exe", "Info.plist", "PkgInfo",
                         "jana.desktop", "AppRun", ".DirIcon", "uninstall.exe", "Jana.desktop"})  # fmt: skip
CONFIG_ROOTS = ("config", "assets", "content", "skills", "legal")


def component_of(relative: str) -> str | None:
    """The TABLE PLT-02a component a bundle file belongs to, or None when it is not a listed component.

    Paths are relative to the installed app: the Windows install folder, a macOS `Jana.app/Contents/` (resources under
    `Resources/`) or a Linux AppDir (`usr/bin`, resources under `usr/lib/Jana/`). The resource folders are those of
    `tauri.release.conf.json`: `agent-core/`, `tool-worker/`, `runtime/<variant>/`, the configuration roots and
    `keys/`."""
    parts = PurePosixPath(relative).parts
    for prefix in (("Jana.app", "Contents"), ("usr", "lib", "Jana"), ("usr",)):
        if parts[: len(prefix)] == prefix:
            parts = parts[len(prefix) :]
            break
    if parts[:1] in (("Resources",), ("resources",)) and len(parts) > 1:
        if len(parts) == 2 and parts[1].endswith((".icns", ".ico", ".png")):
            return "shell"
        parts = parts[1:]
    if not parts:
        return None
    head = parts[0]
    if head in ("MacOS", "bin") and len(parts) == 2 and parts[1] in SHELL_FILES:
        return "shell"
    if head == "_CodeSignature" or (head in ("icons", "share") and parts[-1].endswith((".png", ".ico", ".icns"))):
        return "shell"
    if len(parts) == 1:
        return "shell" if head in SHELL_FILES or head.endswith((".ico", ".icns")) else None
    if head == "agent-core":
        return "agent_core"
    if head == "tool-worker":
        return "tool_worker"
    if head == "runtime" and len(parts) >= 3:
        return "runtime"
    if head in CONFIG_ROOTS:
        return "config"
    if head == "keys":
        return "keys"
    return None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(MB):
            digest.update(block)
    return digest.hexdigest()


def bundle_manifest(root: Path) -> dict[str, Any]:
    """Every file of the bundle with its size, sha256 and component (None for an unlisted file)."""
    files = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        relative = path.relative_to(root).as_posix()
        files.append({"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path),
                      "component": component_of(relative)})  # fmt: skip
    return {"format": "jana.bundle-manifest.1", "files": files}


def budget_errors(manifest: Mapping[str, Any], settings: Settings | None = None) -> list[str]:
    """PLT-02: unlisted files, components over budget by more than the tolerance, and the base installer total."""
    settings = settings or Settings()
    tolerance = 1 + settings.bundle_budget_tolerance
    errors = [f"{f['path']}: not a component of TABLE PLT-02a" for f in manifest["files"] if f["component"] is None]
    sizes: dict[str, int] = {}
    for entry in manifest["files"]:
        if entry["component"] is not None:
            sizes[entry["component"]] = sizes.get(entry["component"], 0) + int(entry["bytes"])
    for component, key in COMPONENTS.items():
        budget = float(getattr(settings, key)) * MB
        if sizes.get(component, 0) > budget * tolerance:
            errors.append(f"{component}: {sizes[component] / MB:.1f} MB is over its {budget / MB:.0f} MB budget")
    total = sum(sizes.values())
    if total > settings.bundle_budget_total_mb * MB * tolerance:
        errors.append(f"the base installer is {total / MB:.1f} MB, over {settings.bundle_budget_total_mb:.0f} MB")
    return errors


# --- PLT-05: every executable signed -------------------------------------------------------------------------------

MACHO_MAGIC = {b"\xfe\xed\xfa\xce", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"}


def executable_kind(path: Path) -> str | None:
    """`pe` or `macho` by the file's magic bytes (not its name); None for anything else."""
    with path.open("rb") as handle:
        head = handle.read(4096)
    if head[:2] == b"MZ" and len(head) >= 64:
        offset = int.from_bytes(head[60:64], "little")
        if offset + 4 <= len(head) and head[offset : offset + 4] == b"PE\0\0":
            return "pe"
    if head[:4] in MACHO_MAGIC:
        return "macho"
    return None


Verifier = Callable[[Path, str], bool]  # (file, kind) -> signed as the release needs


def codesign_verifier(path: Path, kind: str) -> bool:
    """macOS: a valid Developer ID signature with the hardened runtime."""
    check = subprocess.run(["codesign", "--verify", "--strict", str(path)], capture_output=True, check=False)
    if check.returncode != 0:
        return False
    details = subprocess.run(["codesign", "-d", "--verbose=2", str(path)], capture_output=True, text=True, check=False)
    return "runtime" in details.stderr and "Authority=Developer ID Application" in details.stderr


def signtool_verifier(path: Path, kind: str) -> bool:
    """Windows: Authenticode under the default policy, with a timestamp."""
    done = subprocess.run(["signtool", "verify", "/pa", "/tw", str(path)], capture_output=True, check=False)
    return done.returncode == 0


@dataclass(frozen=True)
class DevSigner:
    """The development code-signing key: a detached Ed25519 signature per executable, for pipeline runs without the
    owner's certificates. It proves the audit and the pipeline work; it is never a release signature."""

    key: Ed25519PrivateKey

    @staticmethod
    def development() -> DevSigner:
        seed = hashlib.sha256(b"jana development code signing: never a release signature").digest()
        return DevSigner(Ed25519PrivateKey.from_private_bytes(seed))

    def public(self) -> str:
        return base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()

    def sign_bundle(self, root: Path) -> dict[str, str]:
        """Sign every executable; returns path -> signature (written to `bundle-signatures.json` beside the bundle)."""
        signatures = {}
        for path in sorted(p for p in root.rglob("*") if p.is_file()):
            if executable_kind(path) is not None:
                signatures[path.relative_to(root).as_posix()] = base64.b64encode(
                    self.key.sign(path.read_bytes())
                ).decode()
        return signatures

    def verifier(self, root: Path, signatures: Mapping[str, str]) -> Verifier:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(self.public()))

        def verify(path: Path, kind: str) -> bool:
            value = signatures.get(path.relative_to(root).as_posix())
            if value is None:
                return False
            try:
                public.verify(base64.b64decode(value), path.read_bytes())
            except (InvalidSignature, ValueError):
                return False
            return True

        return verify


def signature_errors(root: Path, verify: Verifier) -> list[str]:
    """PLT-05: every PE and Mach-O file in the built installer or app is signed."""
    errors = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        kind = executable_kind(path)
        if kind is not None and not verify(path, kind):
            errors.append(f"{path.relative_to(root).as_posix()}: unsigned {kind}")
    return errors


def entitlement_errors(path: Path = ENTITLEMENTS, recorded: Iterable[str] = ()) -> list[str]:
    """macOS entitlements are the minimum: none of the signing-weakening ones unless recorded with a reason."""
    granted = plistlib.loads(path.read_bytes())
    allowed = set(recorded)
    return [f"{path.name}: {key} without a recorded reason" for key in WEAKENING_ENTITLEMENTS
            if granted.get(key) and key not in allowed]  # fmt: skip


# --- PLT-07: antivirus scans on the exact release hashes --------------------------------------------------------------


def av_products(path: Path = AV_PRODUCTS) -> list[str]:
    return [str(p["name"]) for p in tomllib.loads(path.read_text())["product"]]


def av_errors(record: Mapping[str, Any], artefacts: Mapping[str, str], products: Iterable[str]) -> list[str]:
    """`artefacts` maps each release file to its sha256; `record` is the checklist's scan record."""
    errors = []
    scans = record.get("scans", [])
    for product in products:
        for name, sha in sorted(artefacts.items()):
            mine = [s for s in scans if s.get("product") == product and s.get("sha256") == sha]
            if not mine:
                errors.append(f"{product}: no scan of {name} ({sha[:12]})")
            elif any(s.get("result") != "clean" for s in mine):
                errors.append(f"{product}: an open detection on {name}")
    known = set(artefacts.values())
    errors += [f"{s.get('product')}: scanned a hash that is not a release artefact ({str(s.get('sha256'))[:12]})"
               for s in scans if s.get("sha256") not in known]  # fmt: skip
    if not record.get("microsoft_submission"):
        errors.append("the release was not submitted to Microsoft for analysis")
    return errors


def memory_headroom_errors(lap: Mapping[str, Any], settings: Settings | None = None) -> list[str]:
    """PLT-23 on a device-lab record: the peak resident memory of all product processes during the 20-turn session
    (`session_peak_rss_bytes`) stays `memory_headroom_gb` below installed RAM (`ram_bytes`)."""
    settings = settings or Settings()
    peak, ram = lap.get("session_peak_rss_bytes"), lap.get("ram_bytes")
    if not isinstance(peak, int) or not isinstance(ram, int):
        return [f"{lap.get('name', '?')}: no session_peak_rss_bytes or ram_bytes recorded"]
    if lap.get("session_turns", 0) < 20:
        return [f"{lap.get('name', '?')}: the session ran {lap.get('session_turns', 0)} turns, not 20"]
    limit = ram - settings.memory_headroom_gb * 1024**3
    return [] if peak <= limit else [f"{lap.get('name', '?')}: peak {peak / 1024**3:.2f} GB leaves less than "
                                     f"{settings.memory_headroom_gb:g} GB of {ram / 1024**3:.1f} GB"]  # fmt: skip


def write_json(path: Path, value: Any) -> Path:
    path.write_text(json.dumps(value, indent=1, sort_keys=True) + "\n")
    return path
