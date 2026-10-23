"""The core's side of the shell's keychain bridge (SEC-17, G81, D97): the device secrets arrive in `control.keys`, a
secret the core creates goes back to the shell as `control.key_put`, and a release core never runs on a key store held
only in memory."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from agent_core.api.__main__ import CONTROL_PROTOCOL
from agent_core.config.resolve import app_settings
from agent_core.contracts import errors
from agent_core.engine.assembly import AppRuntime
from agent_core.store.keystore import ShellKeyStore, decode_secret, encode_secret
from agent_core.trace.crashes import DEVICE_KEY_REF
from jana_tools import REPO_ROOT

STARTUP_S = 90.0


class Core:
    """`python -m agent_core.api` driven as the shell drives it, every stdout line kept."""

    def __init__(self) -> None:
        env = {k: v for k, v in os.environ.items() if not k.startswith("JANA_")}
        self.proc = subprocess.Popen([sys.executable, "-m", "agent_core.api"], stdin=subprocess.PIPE,
                                     stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, env=env)  # fmt: skip
        self.lines: list[dict[str, Any]] = []
        self._reader = threading.Thread(target=self._read, daemon=True)
        self._reader.start()

    def _read(self) -> None:
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            try:
                self.lines.append(json.loads(line))
            except ValueError:
                continue

    def send(self, message: dict[str, Any]) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def wait_for(self, kind: str, timeout_s: float = STARTUP_S) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            found = next((m for m in self.lines if m.get("type") == kind), None)
            if found is not None or self.proc.poll() is not None:
                return found
            time.sleep(0.05)
        return None

    def stop(self) -> list[dict[str, Any]]:
        self.send({"type": "control.shutdown", "grace_ms": 0})
        self.proc.wait(timeout=60)
        self._reader.join(timeout=10)
        return self.lines


def _config(data: Path, *, release: bool) -> dict[str, Any]:
    config: dict[str, Any] = {"type": "control.config", "data_dir": str(data),
                              "content_root": str(REPO_ROOT / "content" / "agent"),
                              "skills_root": str(REPO_ROOT / "skills"), "release": release}  # fmt: skip
    if not release:
        config["scripted"] = True
    return config


def _launch(data: Path, keys: dict[str, Any] | None, *, release: bool = False) -> Core:
    core = Core()
    core.send({"type": "control.hello", "protocol": CONTROL_PROTOCOL})
    if keys is not None:
        core.send(keys)
    core.send(_config(data, release=release))
    core.send({"type": "control.secret", "name": "launch_token", "value": "t" * 43})
    return core


def sec17_release_core_needs_shell_keys(tmp_path: Path) -> None:
    """A release core waits for the shell's `control.keys` and never starts on a memory store; a secret the core
    creates reaches the shell as `control.key_put` and comes back with the next start's `control.keys`."""
    # A release core given everything but the shell's keys does not start: no port, no error, a clean bye.
    waiting = _launch(tmp_path / "release", None, release=True)
    assert waiting.wait_for("control.ready", timeout_s=5) is None
    lines = waiting.stop()
    assert [m["type"] for m in lines] == ["control.bye"], lines
    with pytest.raises(RuntimeError, match="SEC-17"):
        AppRuntime(app_settings("release"), tmp_path, tmp_path, tmp_path / "data", release=True).key_store()

    # First start: the shell holds nothing; the device key the core creates is handed to the shell to keep.
    data = tmp_path / "data"
    first = _launch(data, {"type": "control.keys", "store": "os_keychain", "entries": []})
    assert first.wait_for("control.ready") is not None, first.lines
    sent = first.stop()
    puts = [m for m in sent if m["type"] == "control.key_put"]
    assert puts and all(errors("control/control#/$defs/ToShell", m) == [] for m in puts)
    device_key = next(m["value"] for m in puts if m["ref"] == DEVICE_KEY_REF)
    assert len(decode_secret(device_key)) == 32
    assert not any(device_key in p.read_bytes().decode("latin-1") for p in data.rglob("*") if p.is_file())

    # Next start: the shell sends it back and the core keeps using it, asking to store nothing new for it.
    entries = [{"ref": m["ref"], "value": m["value"]} for m in puts]
    second = _launch(data, {"type": "control.keys", "store": "os_keychain", "entries": entries})
    assert second.wait_for("control.ready") is not None, second.lines
    again = second.stop()
    assert not [m for m in again if m["type"] == "control.key_put" and m["ref"] == DEVICE_KEY_REF]


def test_shell_key_store_round_trip_and_results() -> None:
    sent: list[dict[str, Any]] = []
    keys = ShellKeyStore.from_control({"type": "control.keys", "store": "os_keychain",
                                       "entries": [{"ref": "jana.device-db", "value": encode_secret(b"k" * 32)}]},
                                      sent.append)  # fmt: skip
    assert keys.get("jana.device-db") == b"k" * 32 and keys.os_keychain
    keys.put("jana.service-credential.id", b"dcr_example")
    keys.delete("jana.device-db")
    assert sent == [{"type": "control.key_put", "ref": "jana.service-credential.id",
                     "value": encode_secret(b"dcr_example")},
                    {"type": "control.key_delete", "ref": "jana.device-db"}]  # fmt: skip
    assert all(errors("control/control#/$defs/ToShell", m) == [] for m in sent)
    assert keys.refs() == ["jana.service-credential.id"] and keys.get("jana.device-db") is None
    assert "dcr_example" not in repr(keys) and encode_secret(b"dcr_example") not in repr(keys)
    keys.on_result({"type": "control.key_result", "ref": "jana.service-credential.id", "op": "put", "ok": False,
                    "store": "os_keychain"})  # fmt: skip
    assert not keys.os_keychain  # a secret the shell could not keep: the keychain line shows (OBS-15)
    keys.on_result({"type": "control.key_result", "ref": "jana.service-credential.id", "op": "put", "ok": True,
                    "store": "user_file"})  # fmt: skip
    assert not keys.os_keychain and keys.store == "user_file"  # the SEC-17 file fallback
    with pytest.raises(ValueError):
        keys.put("other.secret", b"x")
