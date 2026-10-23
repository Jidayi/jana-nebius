"""M20.a: uninstall and data removal (PLT-24). The installation, its learner data and its keys are synthetic."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from agent_core.store.keystore import INSTALL_MARKER, FileKeyStore
from agent_core.store.local import open_local
from agent_core.store.uninstall import preflight, uninstall
from agent_core.trace.crashes import DEVICE_KEY_REF


def _installation(tmp_path: Path) -> tuple[Path, Path, FileKeyStore]:
    install = tmp_path / "Programs" / "Jana"
    for name in ("jana-shell.exe", "agent-core/agent-core.exe", "runtime/vulkan/llama-server.exe"):
        (install / name).parent.mkdir(parents=True, exist_ok=True)
        (install / name).write_bytes(b"synthetic binary")
    data = tmp_path / "AppData" / "app.jana.desktop" / "core"
    stores = open_local(data, app_version="1.0.0", now_ms=1_800_000_000_000)
    stores.learner.execute("CREATE TABLE IF NOT EXISTS synthetic_progress (id TEXT)")
    stores.learner.commit()
    stores.close()
    for name in (
        "packs/pack.phy.o.pack",
        "models/packs/mp.synth.8b.q4_k_m.low/model.gguf",
        "runtime/hashes.json",
        "scratch/tmp.bin",
        "crashes/records/x.json",
        "logs/core.jsonl",
        "downloads/dl_x/journal.json",
    ):
        (data / name).parent.mkdir(parents=True, exist_ok=True)
        (data / name).write_bytes(b"synthetic")
    keys = FileKeyStore(tmp_path / "Keychain", data)
    for ref in (INSTALL_MARKER, DEVICE_KEY_REF, "jana.service-credential.ed25519", "jana.profile.synthetic"):
        keys.put(ref, b"synthetic secret")
    keys.put("other.app.secret", b"not ours")
    return install, data, keys


def plt24_uninstall_delete_leaves_nothing(tmp_path: Path) -> None:
    """Choosing delete leaves no product file, no database and no key-store entry of the app; choosing keep removes
    binaries, packs and caches but keeps the learner data and its keys."""
    install, data, keys = _installation(tmp_path / "delete")
    assert preflight(data) == {"tombstones_pending": 0}
    uninstall("delete", data, keys, [install])
    assert not install.exists() and not data.exists()
    assert keys.refs() == ["other.app.secret"], "every jana.* entry is gone, nothing else touched"

    install, data, keys = _installation(tmp_path / "keep")
    uninstall("keep", data, keys, [install])
    assert not install.exists()
    left = sorted(p.relative_to(data).as_posix() for p in data.rglob("*") if p.is_file())
    assert "device.db" in left and any(p.startswith("profiles/") and p.endswith("learner.db") for p in left)
    assert not [p for p in left if p.split("/")[0] in ("packs", "models", "runtime", "scratch", "crashes", "logs",
                                                       "downloads")], left  # fmt: skip
    assert INSTALL_MARKER in keys.refs() and DEVICE_KEY_REF in keys.refs()


def test_uninstall_command_line(tmp_path: Path) -> None:
    """The Windows uninstaller's call: `--uninstall delete --data-dir ... --keystore-dir ...`."""
    install, data, keys = _installation(tmp_path)
    done = subprocess.run([sys.executable, "-m", "agent_core.api", "--uninstall", "delete", "--data-dir", str(data),
                           "--keystore-dir", str(keys.root), "--install-dir", str(install)],
                          capture_output=True, text=True, timeout=120, check=False)  # fmt: skip
    assert done.returncode == 0, done.stderr
    assert json.loads(done.stdout)["removed"] > 0
    assert not data.exists() and not install.exists() and keys.refs() == ["other.app.secret"]
