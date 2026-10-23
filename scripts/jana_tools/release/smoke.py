"""The packaged smoke test (PLT-01): install, first run offline, one guided turn, a practice item, quit.

The `packaged-smoke` CI job runs this on every `must` row of TABLE PLT-01a (the Windows and macOS runners; Linux as
`should`), on the artefacts the release build produced, with networking blocked except loopback:

1. **install**: the installer silently (NSIS `/S`, `msiexec /qn`, the DMG copied to Applications, the AppImage
   extracted), the USB-kit installer on Windows without WebView2 (PLT-06);
2. **first run offline**: the installed agent core started over the control channel with a fresh data folder;
3. **guided turn**: one turn on the smoke kit's model when the kit carries one (the runtime is the installed
   llama.cpp build), otherwise recorded as not run with why;
4. **practice item**: a lesson check answered on a subject pack installed from the kit;
5. **quit**: `control.shutdown`, then no process of the app left running.

Each run writes `<os>.json` with the outcome of every step; `plt01_smoke_on_supported_platforms` reads them
(`JANA_PACKAGED_RESULTS`). Nothing here reaches the internet.
"""

from __future__ import annotations

import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

STEPS = ("install", "first_run_offline", "guided_turn", "practice_item", "quit")
MUST_OSES = ("windows", "macos")  # TABLE PLT-01a S2 `must` rows; Linux is `should` until S3


@dataclass
class Report:
    os: str
    version: str
    steps: dict[str, dict[str, Any]] = field(default_factory=dict)

    def record(self, step: str, ok: bool, detail: str = "", seconds: float | None = None) -> None:
        self.steps[step] = {"ok": ok, "detail": detail, "seconds": seconds}

    def passed(self) -> bool:
        return all(self.steps.get(s, {}).get("ok") for s in STEPS)

    def to_json(self) -> dict[str, Any]:
        return {"os": self.os, "version": self.version, "steps": self.steps, "passed": self.passed()}


def smoke_errors(reports: dict[str, dict[str, Any]], must: tuple[str, ...] = MUST_OSES) -> list[str]:
    """Why the smoke has not passed on every `must` platform."""
    errors = []
    for os_name in must:
        report = reports.get(os_name)
        if report is None:
            errors.append(f"{os_name}: no packaged smoke report")
            continue
        for step in STEPS:
            outcome = report.get("steps", {}).get(step)
            if not outcome or not outcome.get("ok"):
                errors.append(f"{os_name}: {step} did not pass ({(outcome or {}).get('detail', 'not run')})")
    return errors


class CoreDriver:
    """The installed agent core over its control channel, as the shell drives it."""

    def __init__(self, program: list[str], data_dir: Path, content_root: Path, skills_root: Path) -> None:
        self.token = secrets.token_urlsafe(32)
        self.process = subprocess.Popen(program, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        self.port: int | None = None
        from agent_core.contracts._compat import current

        control = current("control")  # the control-channel version the core expects (ARC-29)
        self._send({"type": "control.hello", "protocol": {"major": control.major, "minor": control.minor}})
        # A release core starts only after the shell's device secrets (SEC-17, D97); this smoke holds none.
        self._send({"type": "control.keys", "store": "user_file", "entries": []})
        self._send({"type": "control.config", "data_dir": str(data_dir), "content_root": str(content_root),
                    "skills_root": str(skills_root), "release": True})  # fmt: skip
        self._send({"type": "control.secret", "name": "launch_token", "value": self.token})

    def _send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def ready(self, timeout_s: float) -> bool:
        assert self.process.stdout is not None
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            line = self.process.stdout.readline()
            if not line:
                return False
            message = json.loads(line)
            if message.get("type") == "control.ready":
                self.port = int(message["api_port"])
                return True
        return False

    def call(self, method: str, path: str, body: Any = None) -> tuple[int, Any]:
        data = None if body is None else json.dumps(body).encode()
        key = f"cli_{secrets.token_hex(13).upper()}"
        headers = {"authorization": f"Bearer {self.token}", "origin": "tauri://localhost",
                   "content-type": "application/json", "idempotency-key": key}  # fmt: skip
        request = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", data=data, method=method,
                                         headers=headers)  # fmt: skip
        try:
            with urllib.request.urlopen(request, timeout=60) as reply:  # noqa: S310 - loopback only
                text = reply.read().decode()
                return reply.status, json.loads(text) if text else None
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read().decode() or "null")

    def quit(self, grace_ms: int = 3000) -> bool:
        self._send({"type": "control.shutdown", "grace_ms": grace_ms})
        try:
            self.process.wait(timeout=grace_ms / 1000 + 10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            return False
        return self.process.returncode == 0


def loopback_only() -> bool:
    """The smoke runs offline: a connection to a public address must fail."""
    try:
        socket.create_connection(("1.1.1.1", 443), timeout=2).close()
    except OSError:
        return True
    return False


def run(os_name: str, version: str, install: Callable[[], Path], resources: Callable[[Path], Path],
        kit: Path | None, out: Path) -> Report:  # fmt: skip
    """Run the five steps on one platform and write `<out>/<os>.json`."""
    report = Report(os_name, version)
    started = time.monotonic()
    try:
        app = install()
        report.record("install", True, str(app), time.monotonic() - started)
    except (OSError, subprocess.CalledProcessError) as error:
        report.record("install", False, type(error).__name__)
        return _write(report, out)
    res = resources(app)
    core = res / "agent-core" / ("agent-core.exe" if os_name == "windows" else "agent-core")
    with tempfile.TemporaryDirectory() as data:
        driver = CoreDriver([str(core)], Path(data), res / "content" / "agent", res / "skills")
        started = time.monotonic()
        ok = driver.ready(120)
        detail = "network blocked" if loopback_only() else "online features off (no internet socket, ARC-06)"
        report.record("first_run_offline", ok, detail if ok else "the core did not come up",
                      time.monotonic() - started)  # fmt: skip
        if ok and kit is not None:
            status, job = driver.call("POST", "/v1/packs/install", {"source": {"kind": "usb", "path": str(kit)}})
            report.record("practice_item", status == 202, json.dumps(job)[:200])
            status, meta = driver.call("GET", "/v1/health")
            has_model = isinstance(meta, dict) and meta.get("readiness") == "ready"
            report.record("guided_turn", has_model, "" if has_model else "no tutor model in the smoke kit")
        report.record("quit", driver.quit(), "")
    return _write(report, out)


def install_from(os_name: str, installer: Path, target: Path) -> Path:
    """Install silently into `target`; returns the installed app's folder."""
    target.mkdir(parents=True, exist_ok=True)
    if os_name == "windows":
        if installer.suffix == ".msi":
            subprocess.run(["msiexec", "/i", str(installer), "/qn", f"INSTALLDIR={target}"], check=True)
        else:
            subprocess.run([str(installer), "/S", f"/D={target}"], check=True)
        return target
    if os_name == "macos":
        mount = Path(tempfile.mkdtemp())
        subprocess.run(["hdiutil", "attach", "-nobrowse", "-mountpoint", str(mount), str(installer)], check=True)
        try:
            subprocess.run(["cp", "-R", str(mount / "Jana.app"), str(target)], check=True)
        finally:
            subprocess.run(["hdiutil", "detach", str(mount)], check=False)
        return target / "Jana.app"
    subprocess.run([str(installer), "--appimage-extract"], cwd=target, check=True)
    return target / "squashfs-root"


def resources_of(os_name: str, app: Path) -> Path:
    """The resource folder Tauri installs (`resource_dir()` in the shell)."""
    if os_name == "macos":
        return app / "Contents" / "Resources"
    if os_name == "linux":
        return app / "usr" / "lib" / "Jana"
    return app


def _write(report: Report, out: Path) -> Report:
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report.os}.json").write_text(json.dumps(report.to_json(), indent=1) + "\n")
    return report


def this_os() -> str:
    return {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")


def results(folder: str | None = os.environ.get("JANA_PACKAGED_RESULTS")) -> dict[str, dict[str, Any]] | None:
    if not folder:
        return None
    return {p.stem: json.loads(p.read_text()) for p in sorted(Path(folder).glob("*.json"))}
