"""M20.a: packaged smoke, bundle budgets, signing, installers, antivirus, memory budget and icons (PLT-01, PLT-02,
PLT-05, PLT-06, PLT-07, PLT-23, DSN-25), and the pinned runtime builds.

Each test first runs what any machine can run (the release check over a synthetic bundle, record or icon set: every
file and record there is made up), then, where the requirement needs a packaged build, a release runner or the device
lab, reads that evidence (`JANA_BUNDLE_DIR`, `JANA_PACKAGED_APP`, `JANA_PACKAGED_RESULTS`, `JANA_AV_RECORD`,
`JANA_DEVLAB_RESULTS`) and skips, saying what is missing, until it exists."""

from __future__ import annotations

import hashlib
import io
import json
import os
import plistlib
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from jana_tools import REPO_ROOT
from jana_tools.release import icons, packaging, runtime_builds, smoke

SETTINGS = Settings()
MB = 1024 * 1024
TAURI = REPO_ROOT / "apps" / "desktop" / "src-tauri"


def _file(path: Path, size: int, head: bytes = b"") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.write(head)
        handle.truncate(max(size, len(head)))  # sparse: the size counts, the disk does not
    return path


def _pe() -> bytes:
    head = bytearray(512)
    head[0:2] = b"MZ"
    head[60:64] = (128).to_bytes(4, "little")
    head[128:132] = b"PE\0\0"
    return bytes(head)


MACHO = b"\xcf\xfa\xed\xfe" + bytes(60)


def _windows_bundle(root: Path, scale: float = 1.0) -> Path:
    """A synthetic installed Windows app: every component of TABLE PLT-02a at a share of its budget."""
    _file(root / "jana-shell.exe", int(20 * MB * scale), _pe())
    _file(root / "jana-precheck.exe", 1 * MB, _pe())
    _file(root / "uninstall.exe", 1 * MB, _pe())
    _file(root / "agent-core" / "agent-core.exe", int(10 * MB * scale), _pe())
    _file(root / "agent-core" / "_internal" / "python312.dll", int(60 * MB * scale), _pe())
    _file(root / "tool-worker" / "tool-worker.exe", int(60 * MB * scale), _pe())
    for variant in ("vulkan", "cpu-avx2", "cpu-baseline"):
        _file(root / "runtime" / variant / "llama-server.exe", int(10 * MB * scale), _pe())
        _file(root / "runtime" / variant / "BUILD.json", 300)
    _file(root / "content" / "agent" / "soul.md", 4000)
    _file(root / "skills" / "teaching" / "skill.json", 4000)
    _file(root / "legal" / "LICENSE", 12000)
    _file(root / "keys" / "trust_anchors.json", 6000)
    _file(root / "keys" / "revocation_list.json", 400)
    return root


# --- PLT-01 -------------------------------------------------------------------------------------------------------


def plt01_smoke_on_supported_platforms() -> None:
    """The packaged smoke (install, first run offline, one guided turn, a practice item, quit) passes on every `must`
    row of TABLE PLT-01a. The check over the smoke reports runs here; the reports come from the `packaged-smoke` CI
    job's runners (JANA_PACKAGED_RESULTS)."""
    passing = {os_name: {"steps": {step: {"ok": True} for step in smoke.STEPS}} for os_name in smoke.MUST_OSES}
    assert smoke.smoke_errors(passing) == []
    failing = json.loads(json.dumps(passing))
    failing["macos"]["steps"]["guided_turn"] = {"ok": False, "detail": "no tutor model in the smoke kit"}
    assert smoke.smoke_errors(failing) == ["macos: guided_turn did not pass (no tutor model in the smoke kit)"]
    assert smoke.smoke_errors({"windows": passing["windows"]}) == ["macos: no packaged smoke report"]

    reports = smoke.results()
    if reports is None:
        pytest.skip(
            "infrastructure: needs the packaged-smoke reports of the Windows and macOS runners "
            "(JANA_PACKAGED_RESULTS), which build once the pins in scripts/packaging/README.md are set"
        )
    assert smoke.smoke_errors(reports) == []


# --- PLT-02 -------------------------------------------------------------------------------------------------------


def plt02_bundle_manifest_and_budgets(tmp_path: Path) -> None:
    """A release build fails if a component exceeds its budget by more than the tolerance, the whole bundle is over
    the base installer total, or a file outside TABLE PLT-02a is present."""
    good = _windows_bundle(tmp_path / "good", scale=0.5)
    manifest = packaging.bundle_manifest(good)
    assert packaging.budget_errors(manifest) == [], manifest
    assert {f["component"] for f in manifest["files"]} == set(packaging.COMPONENTS)
    assert all(len(f["sha256"]) == 64 for f in manifest["files"])

    over = _windows_bundle(tmp_path / "over", scale=0.5)
    _file(over / "tool-worker" / "_internal" / "big.dll", int(SETTINGS.bundle_budget_tool_worker_mb * MB), _pe())
    errors = packaging.budget_errors(packaging.bundle_manifest(over))
    assert any(e.startswith("tool_worker:") for e in errors), errors
    within_tolerance = _windows_bundle(tmp_path / "edge", scale=0.5)
    shell = within_tolerance / "jana-shell.exe"
    _file(shell, int(SETTINGS.bundle_budget_shell_mb * MB * (1 + SETTINGS.bundle_budget_tolerance / 2)) - 2 * MB,
          _pe())  # fmt: skip
    assert not [e for e in packaging.budget_errors(packaging.bundle_manifest(within_tolerance)) if "shell" in e]

    stray = _windows_bundle(tmp_path / "stray", scale=0.5)
    _file(stray / "debug.log", 100)
    _file(stray / "perception-worker" / "ocr.onnx", 100)  # ships in its pack, never in the base installer
    errors = packaging.budget_errors(packaging.bundle_manifest(stray))
    assert "debug.log: not a component of TABLE PLT-02a" in errors
    assert "perception-worker/ocr.onnx: not a component of TABLE PLT-02a" in errors

    mac = tmp_path / "mac" / "Jana.app" / "Contents"
    _file(mac / "MacOS" / "jana-shell", 5 * MB, MACHO)
    _file(mac / "Info.plist", 900)
    _file(mac / "Resources" / "icon.icns", 9000)
    _file(mac / "Resources" / "agent-core" / "agent-core", 5 * MB, MACHO)
    _file(mac / "Resources" / "runtime" / "metal" / "llama-server", 5 * MB, MACHO)
    _file(mac / "_CodeSignature" / "CodeResources", 900)
    assert packaging.budget_errors(packaging.bundle_manifest(tmp_path / "mac")) == []

    # The release build runs the same check on its real bundle (`release bundle`, packaged-smoke job) and fails on it.
    built = os.environ.get("JANA_BUNDLE_DIR")
    if built is not None:
        assert packaging.budget_errors(packaging.bundle_manifest(Path(built))) == []


# --- PLT-05 -------------------------------------------------------------------------------------------------------


def plt05_all_binaries_signed(tmp_path: Path) -> None:
    """A signature audit of the built installer finds no unsigned PE or Mach-O file (here with the development code
    key; the release runner audits with signtool and codesign), and the macOS entitlements are the minimum."""
    root = _windows_bundle(tmp_path / "app", scale=0.01)
    _file(root / "runtime" / "metal-like" / "libggml.dylib", 4096, MACHO)
    signer = packaging.DevSigner.development()
    signatures = signer.sign_bundle(root)
    executables = {p.relative_to(root).as_posix() for p in root.rglob("*")
                   if p.is_file() and packaging.executable_kind(p)}  # fmt: skip
    assert set(signatures) == executables and "runtime/metal-like/libggml.dylib" in executables
    assert "keys/trust_anchors.json" not in executables, "data files are not executables"
    assert packaging.signature_errors(root, signer.verifier(root, signatures)) == []

    _file(root / "runtime" / "vulkan" / "ggml-vulkan.dll", 4096, _pe())  # added after signing
    tampered = root / "tool-worker" / "tool-worker.exe"
    tampered.write_bytes(tampered.read_bytes()[:-1] + b"\x01")
    errors = packaging.signature_errors(root, signer.verifier(root, signatures))
    assert errors == ["runtime/vulkan/ggml-vulkan.dll: unsigned pe", "tool-worker/tool-worker.exe: unsigned pe"]

    assert packaging.entitlement_errors() == []
    weakened = tmp_path / "weak.plist"
    weakened.write_bytes(plistlib.dumps({packaging.WEAKENING_ENTITLEMENTS[1]: True}))
    assert packaging.entitlement_errors(weakened) != []
    assert packaging.entitlement_errors(weakened, recorded=[packaging.WEAKENING_ENTITLEMENTS[1]]) == []

    built = os.environ.get("JANA_BUNDLE_DIR")
    if built is None:
        pytest.skip(
            "owner and infrastructure: the release build, signed with the owner's identities, is audited "
            "with signtool and codesign on the release runners (JANA_BUNDLE_DIR)"
        )
    verify = packaging.codesign_verifier if sys.platform == "darwin" else packaging.signtool_verifier
    assert packaging.signature_errors(Path(built), verify) == []


def plt05_gatekeeper_offline() -> None:
    """The notarised macOS app passes Gatekeeper's assessment offline with its stapled ticket."""
    app = os.environ.get("JANA_PACKAGED_APP")
    if sys.platform != "darwin" or app is None or not app.endswith(".app"):
        pytest.skip(
            "owner and infrastructure: needs the app notarised with the owner's Developer ID on the macOS "
            "release runner (JANA_PACKAGED_APP)"
        )
    if not Path(app).is_dir():
        pytest.skip(f"JANA_PACKAGED_APP names no app bundle here ({app}); the macOS release runner sets it")
    staple = _gatekeeper_step(["xcrun", "stapler", "validate", app])
    assert staple.returncode == 0, staple.stdout + staple.stderr
    assessed = _gatekeeper_step(["spctl", "--assess", "--type", "execute", "-vv", app])
    assert assessed.returncode == 0 and "Notarized Developer ID" in assessed.stderr, assessed.stderr


def _gatekeeper_step(command: list[str]) -> subprocess.CompletedProcess[str]:
    """One Gatekeeper step, bounded by `gatekeeper_check_timeout_s`: a step that hangs (a ticket lookup that waits on
    a network, a first-run tools prompt) fails the check with what it was waiting on instead of blocking the suite."""
    limit = SETTINGS.gatekeeper_check_timeout_s
    try:
        return subprocess.run(command, capture_output=True, text=True, check=False, timeout=limit)
    except subprocess.TimeoutExpired:
        step = " ".join(command[:2])
        pytest.fail(f"PLT-05: `{step}` gave no answer within {limit:g} s (gatekeeper_check_timeout_s); rerun it "
                    "by hand on the release runner to see what it waits on")  # fmt: skip
    except FileNotFoundError:
        pytest.skip(f"{command[0]} is not installed here; the macOS release runner has it")


def test_plt05_gatekeeper_steps_are_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A Gatekeeper step that hangs fails within its configured time, naming the step, and never blocks the suite."""

    def hang(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        assert kwargs["timeout"] == SETTINGS.gatekeeper_check_timeout_s
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(subprocess, "run", hang)
    with pytest.raises(pytest.fail.Exception, match=r"xcrun stapler.*gatekeeper_check_timeout_s"):
        _gatekeeper_step(["xcrun", "stapler", "validate", "/nowhere/Jana.app"])


# --- PLT-06 -------------------------------------------------------------------------------------------------------


def plt06_offline_install_without_webview2() -> None:
    """On Windows 10 with no WebView2 and no network, the USB-kit installer completes and the app starts. The kit's
    installer carries the WebView2 offline installer and runs the precheck; the run itself is the Windows runner's."""
    kit = json.loads((TAURI / "tauri.usbkit.conf.json").read_text())
    assert kit["bundle"]["windows"]["webviewInstallMode"]["type"] == "offlineInstaller"
    release = json.loads((TAURI / "tauri.release.conf.json").read_text())
    assert release["bundle"]["windows"]["nsis"]["installMode"] == "currentUser", "per-user: no admin rights"
    assert "NSIS_HOOK_PREINSTALL" in (TAURI / "installer" / "hooks.nsh").read_text()
    # Every Windows build pass that applies the kit's configuration makes both kit installers: the per-user NSIS and
    # the schools' per-machine MSI (PLT-21), so neither needs the network for WebView2.
    workflow = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    kit_passes = [line for line in workflow.splitlines() if "tauri.usbkit.conf.json" in line]
    builds = [line for line in workflow.splitlines() if "cargo tauri build --bundles" in line]
    assert kit_passes and len(builds) == len(kit_passes)
    assert all("--bundles nsis,msi " in line for line in builds), builds
    reports = smoke.results()
    if reports is None or "windows-usbkit" not in reports:
        pytest.skip(
            "infrastructure: needs the Windows 10 runner's USB-kit install without WebView2 or network "
            "(JANA_PACKAGED_RESULTS: windows-usbkit)"
        )
    assert smoke.smoke_errors({"windows-usbkit": reports["windows-usbkit"]}, ("windows-usbkit",)) == []


def test_plt24_uninstaller_asks_with_two_labelled_choices(tmp_path: Path) -> None:
    """The uninstaller's first page offers keeping and deleting the students' progress as two labelled choices,
    keeping selected; only the delete choice runs the core's delete, so a silent uninstall keeps the progress. Every
    word it shows is an installer string key (LOC-01), and a word written into hooks.nsh fails the check."""
    from jana_tools.release.installer_strings import catalogue, installer_string_errors

    hooks = (TAURI / "installer" / "hooks.nsh").read_text()
    assert "UninstPage custom un.JanaLearnerDataPage un.JanaLearnerDataLeave" in hooks
    assert '${NSD_CreateRadioButton} 0 46u 100% 12u "$(janaUninstallKeep)"' in hooks
    assert '${NSD_CreateRadioButton} 0 78u 100% 12u "$(janaUninstallDelete)"' in hooks
    assert "${NSD_Check} $JanaKeepChoice" in hooks
    unin = hooks.split("!macro NSIS_HOOK_PREUNINSTALL", 1)[1]
    assert unin.index('${If} $JanaLearnerData == "delete"') < unin.index("--uninstall delete") < unin.index("${Else}")
    assert "MessageBox" not in unin
    assert installer_string_errors() == []
    words = catalogue()
    assert set(words) == {"en"} and {"janaUninstallKeep", "janaUninstallDelete"} <= set(words["en"])
    # A word written straight into hooks.nsh, a key with no words, and a stale strings.nsh each fail.
    copy = tmp_path / "installer"
    shutil.copytree(TAURI / "installer", copy)
    (copy / "hooks.nsh").write_text(hooks.replace('"$(janaUninstallTitle)"', '"Students\' progress"'))
    assert any("shows words that are not an installer string key" in e for e in installer_string_errors(copy))
    (copy / "hooks.nsh").write_text(hooks.replace("$(janaUninstallTitle)", "$(janaNoSuchKey)"))
    assert any("janaNoSuchKey" in e for e in installer_string_errors(copy))
    (copy / "hooks.nsh").write_text(hooks)
    (copy / "strings.nsh").write_text("; edited by hand\n")
    assert any("stale" in e for e in installer_string_errors(copy))


def test_plt24_delete_choice_clears_the_keychain_and_overrides_tauris_box() -> None:
    """Only the delete choice runs the shell's keychain step (G81) and removes the app's own folders; Tauri's "Delete
    the application data" box is set off before the uninstall section reads it, so it can never delete the progress
    the adult chose to keep. A failed keychain step is said in the installer's words. The NSIS run itself is the
    Windows runner's (OWNER ACTION in hooks.nsh)."""
    hooks = (TAURI / "installer" / "hooks.nsh").read_text()
    unin = hooks.split("!macro NSIS_HOOK_PREUNINSTALL", 1)[1].split("!macroend", 1)[0]
    delete, keep = unin.split("${Else}", 1)
    assert unin.index("StrCpy $DeleteAppDataCheckboxState 0") < unin.index('${If} $JanaLearnerData == "delete"')
    assert "--uninstall-keys" in delete and "--uninstall-keys" not in keep
    assert '"$INSTDIR\\${MAINBINARYNAME}.exe" --uninstall-keys --keys-dir "${JANA_KEYS}"' in delete
    assert '!define JANA_KEYS "$LOCALAPPDATA\\jana\\keys"' in hooks  # the shell's fallback folder, local (data_home)
    assert '!define JANA_DATA "$LOCALAPPDATA\\app.jana.desktop"' in hooks
    # A machine whose roaming folder was never moved (or whose move was interrupted) is handled by both choices.
    for place in ("${JANA_ROAMING_DATA}", "${JANA_STAGING}"):
        assert f'--uninstall delete --data-dir "{place}\\core"' in delete and f'RmDir /r "{place}"' in delete
        assert f'--uninstall keep --data-dir "{place}\\core"' in keep
    assert '--uninstall-keys --keys-dir "${JANA_ROAMING_KEYS}"' in delete
    assert 'DetailPrint "$(janaUninstallKeysFailed)"' in delete
    assert "RmDir /r" in delete and "RmDir /r" not in keep
    # The precheck words its message in the installer's language and hands it over as UTF-16LE (LOC-01).
    pre = hooks.split("!macro NSIS_HOOK_PREINSTALL", 1)[1].split("!macroend", 1)[0]
    assert "--lang $LANGUAGE" in pre and "FileReadUTF16LE" in pre
    assert "--lang [UserLanguageID]" in (TAURI / "installer" / "precheck.wxs").read_text()


def test_precheck_messages_are_installer_string_keys(tmp_path: Path) -> None:
    """LOC-01: the precheck shows only catalogue keys, which strings.nsh leaves out (the precheck reads them itself);
    a key the precheck names that the catalogue lacks fails the check."""
    from jana_tools.release.installer_strings import catalogue, installer_string_errors

    english = catalogue()["en"]
    source = (TAURI / "src" / "installer.rs").read_text()
    shown = {k for k in english if k.startswith("janaPrecheck")}
    assert shown and all(f'"{k}"' in source for k in shown)
    assert "janaPrecheck" not in (TAURI / "installer" / "strings.nsh").read_text()
    assert not any(phrase in source for phrase in ("too old for the tutor", "GB of free space")), "no English in Rust"
    copy = tmp_path / "src-tauri"
    shutil.copytree(TAURI / "installer", copy / "installer")
    (copy / "src").mkdir()
    (copy / "src" / "installer.rs").write_text(source.replace('"janaPrecheckDiskFull"', '"janaPrecheckNoSuchKey"'))
    assert any("janaPrecheckNoSuchKey" in e for e in installer_string_errors(copy / "installer"))


def test_installer_description_follows_d60() -> None:
    """The installers' short description uses D60's category phrase: no exam level, and offline is not the product's
    identity."""
    description = json.loads((TAURI / "tauri.release.conf.json").read_text())["bundle"]["shortDescription"]
    assert description and not any(word in description.lower() for word in ("o level", "a level", "offline", "exam"))


# --- PLT-07 -------------------------------------------------------------------------------------------------------


def plt07_av_clean_for_release_hashes() -> None:
    """The release checklist records a clean result per listed product for the exact release hashes; a missing
    product, a detection, a scan of another hash or a missing Microsoft submission blocks the release."""
    artefacts = {"Jana_1.0.0_x64-setup.exe": "a" * 64, "Jana_1.0.0_x64.msi": "b" * 64}
    products = ["Microsoft Defender", "Product B"]
    clean = {"scans": [{"product": p, "sha256": h, "result": "clean"} for p in products for h in artefacts.values()],
             "microsoft_submission": {"id": "synthetic-submission"}}  # fmt: skip
    assert packaging.av_errors(clean, artefacts, products) == []
    detected = json.loads(json.dumps(clean))
    detected["scans"][0]["result"] = "detected"
    assert packaging.av_errors(detected, artefacts, products) == [
        "Microsoft Defender: an open detection on Jana_1.0.0_x64-setup.exe"]  # fmt: skip
    other = dict(clean, scans=[*clean["scans"][1:], {"product": "Microsoft Defender", "sha256": "c" * 64,
                                                     "result": "clean"}])  # fmt: skip
    errors = packaging.av_errors(other, artefacts, products)
    assert any("no scan of Jana_1.0.0_x64-setup.exe" in e for e in errors)
    assert any("not a release artefact" in e for e in errors)
    assert packaging.av_errors({"scans": clean["scans"]}, artefacts, products) == [
        "the release was not submitted to Microsoft for analysis"]  # fmt: skip
    listed = packaging.av_products()
    assert listed[0] == "Microsoft Defender" and len(listed) == 4

    record = os.environ.get("JANA_AV_RECORD")
    sums = os.environ.get("JANA_RELEASE_SHA256SUMS")
    if record is None or sums is None:
        pytest.skip(
            "owner: needs the release manager's antivirus scan record for the release SHA256SUMS "
            "(JANA_AV_RECORD, JANA_RELEASE_SHA256SUMS)"
        )
    release = {name.lstrip("*"): sha for sha, name in (line.split(maxsplit=1) for line in
               Path(sums).read_text().splitlines() if line.strip())}  # fmt: skip
    assert packaging.av_errors(json.loads(Path(record).read_text()), release, listed) == []


# --- PLT-23 -------------------------------------------------------------------------------------------------------


def plt23_memory_headroom() -> None:
    """During a 20-turn session on the low-class reference laptop, peak product memory stays at least the headroom
    below installed RAM (the gate here; the measurement is the device lab's)."""
    gb = 1024**3

    def lap(peak: float, turns: int = 20) -> dict[str, Any]:
        return {"name": "synthetic", "ram_bytes": 8 * gb, "session_peak_rss_bytes": int(peak * gb),
                "session_turns": turns}  # fmt: skip

    assert packaging.memory_headroom_errors(lap(5.5)) == []
    assert packaging.memory_headroom_errors(lap(6.5)), "less than the headroom left"
    assert packaging.memory_headroom_errors(lap(1.0, turns=5)), "a short session is no evidence"
    lab = os.environ.get("JANA_DEVLAB_RESULTS")
    if lab is None:
        pytest.skip("needs the low-class reference laptop's 20-turn session (device lab: JANA_DEVLAB_RESULTS)")
    laptops = [json.loads(p.read_text()) for p in sorted(Path(lab).glob("*.json"))]
    low = [lap for lap in laptops if lap.get("hardware_class") == "low" and lap.get("reference", True)]
    if not low or "session_peak_rss_bytes" not in low[0]:
        pytest.skip("the device lab has no low-class 20-turn memory run yet")
    assert packaging.memory_headroom_errors(low[0]) == []


# --- DSN-25 -------------------------------------------------------------------------------------------------------


def dsn25_icon_sizes_and_no_placeholder(tmp_path: Path) -> None:
    """The icon set holds every listed size (ICO 16-256, ICNS 16-1,024, PNG 16-512) and the bundle config uses it;
    a release build fails while the placeholder is present, and passes with other artwork of the same sizes."""
    assert icons.icon_errors(icons.ICONS, release=False) == []
    assert icons.ico_sizes((icons.ICONS / "icon.ico").read_bytes()) == set(icons.ICO_SIZES)
    assert icons.icns_sizes((icons.ICONS / "icon.icns").read_bytes()) == set(icons.ICNS_TYPES.values())
    placeholder = icons.icon_errors(icons.ICONS, release=True)
    assert placeholder and all("placeholder" in e for e in placeholder)

    artwork = tmp_path / "artwork"
    artwork.mkdir()
    other = {s: icons.png(s, (10, 120, 60), (250, 250, 240)) for s in (*icons.PNG_SIZES, 24, 1024)}
    (artwork / "icon.ico").write_bytes(icons.ico({s: other[s] for s in icons.ICO_SIZES}))
    (artwork / "icon.icns").write_bytes(icons.icns({k: other[s] for k, s in icons.ICNS_TYPES.items()}))
    for size in icons.PNG_SIZES:
        (artwork / f"{size}x{size}.png").write_bytes(other[size])
    assert icons.icon_errors(artwork, release=True) == []
    (artwork / "icon.ico").write_bytes(icons.ico({s: other[s] for s in (16, 32)}))
    assert icons.icon_errors(artwork, release=True) == ["icon.ico lacks sizes [24, 48, 64, 128, 256]"]

    release = json.loads((TAURI / "tauri.release.conf.json").read_text())
    for name in release["bundle"]["icon"]:
        assert (TAURI / name).is_file(), name
    assert {"icons/icon.ico", "icons/icon.icns"} <= set(release["bundle"]["icon"])


# --- the pinned llama.cpp builds (the M11 packaging gap) ------------------------------------------------------------


def _archive(path: Path, files: dict[str, bytes]) -> str:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as bundle:
        for name, data in files.items():
            bundle.writestr(name, data)
    path.write_bytes(buffer.getvalue())
    return hashlib.sha256(buffer.getvalue()).hexdigest()


def test_runtime_builds_are_pinned_and_hash_checked(tmp_path: Path) -> None:
    """The release fetch refuses placeholders and a wrong hash, and extracts only the pinned members of a verified
    archive, flattened into runtime/<variant>/ with a BUILD.json; the pins file covers every desktop variant."""
    pins = runtime_builds.load_pins()
    variants = {(b.os, b.variant) for b in pins.builds}
    assert variants == {("windows", "vulkan"), ("windows", "cpu-avx2"), ("windows", "cpu-baseline"),
                        ("macos", "metal"), ("macos", "cpu-arm64"), ("linux", "vulkan"), ("linux", "cpu-avx2"),
                        ("linux", "cpu-baseline")}  # fmt: skip
    with pytest.raises(runtime_builds.FetchRefused, match="placeholder"):
        runtime_builds.fetch(pins, "windows", tmp_path / "out", tmp_path / "cache")

    served = tmp_path / "served"
    served.mkdir()
    sha = _archive(served / "llama-b1-bin-macos-arm64.zip", {"build/bin/llama-server": b"server",
                                                             "build/bin/libggml.dylib": b"lib",
                                                             "build/bin/llama-cli": b"not pinned",
                                                             "../escape": b"never"})  # fmt: skip
    builds = tuple(runtime_builds.Build("macos", v, "llama-{release}-bin-macos-arm64.zip", sha,
                                        ("build/bin/llama-server", "build/bin/*.dylib", "../escape"))
                   for v in ("metal", "cpu-arm64"))  # fmt: skip
    local = runtime_builds.Pins("b1", "0" * 40, "MIT", served.as_uri() + "/{asset}", builds)
    opened: list[str] = []

    def opener(url: str) -> Any:
        opened.append(url)
        from urllib.request import urlopen

        return urlopen(url)  # noqa: S310 - a file:// URL in the test's own folder

    written = runtime_builds.fetch(local, "macos", tmp_path / "out", tmp_path / "cache", opener=opener)
    assert [p.name for p in written] == ["metal", "cpu-arm64"]
    assert len(opened) == 1, "an archive serving two variants is fetched once"
    assert sorted(p.name for p in written[0].iterdir()) == ["BUILD.json", "libggml.dylib", "llama-server"]
    assert json.loads((written[0] / "BUILD.json").read_text())["sha256"] == sha
    assert not (tmp_path / "escape").exists()

    bad_hash = runtime_builds.Build("macos", "metal", builds[0].asset, "f" * 64, builds[0].members)
    wrong = runtime_builds.Pins("b1", "0" * 40, "MIT", served.as_uri() + "/{asset}", (bad_hash,))
    shutil.rmtree(tmp_path / "cache")
    with pytest.raises(runtime_builds.FetchRefused, match="does not match"):
        runtime_builds.fetch(wrong, "macos", tmp_path / "out2", tmp_path / "cache")
    assert not (tmp_path / "out2" / "runtime" / "metal").exists(), "nothing extracted from an unverified archive"
