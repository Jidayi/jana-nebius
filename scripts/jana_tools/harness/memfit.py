"""The memory estimate against measured resident memory (MDL-17).

The router decides whether a model fits from an estimate made before loading: weights + KV cache at the chosen
context + runtime overhead + projector + the enabled side features (`agent_core.router.fit.estimate_bytes`). MDL-17
requires that estimate to be within `memory_estimate_tolerance` of what the runtime really holds once loaded, for
every candidate GGUF on the reference laptops. `measure` starts llama-server on one GGUF at one context, waits for it
to answer, runs one short generation so the KV cache and compute buffers exist, and reads the process's resident
memory; the record it returns goes in the laptop's device-lab file under `memory_fit` (`python -m jana_tools lab
memfit`). `errors` checks a laptop's records. Nothing here fabricates a measurement.
"""

from __future__ import annotations

import os
import platform
import re
import secrets
import socket
import subprocess
import tempfile
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx

GB = 1024**3


def header(gguf: Path) -> dict[str, Any]:
    from agent_core.providers.gguf import read_header

    return asdict(read_header(gguf))


def estimate(record: dict[str, Any]) -> int:
    """The router's estimate for a record's header, context, projector and side features."""
    from agent_core.config import Settings
    from agent_core.providers.gguf import GgufInfo
    from agent_core.router.fit import estimate_bytes

    info = GgufInfo(**record["header"])
    return estimate_bytes(info, int(record["context"]), Settings(), int(record.get("projector_bytes", 0)),
                          int(record.get("extras_bytes", 0)))  # fmt: skip


def errors(laptop: dict[str, Any]) -> list[str]:
    """Why a laptop's memory-fit records miss MDL-17: none recorded, or an estimate off by more than the tolerance."""
    from agent_core.config import Settings

    tolerance = Settings().memory_estimate_tolerance
    name, records = laptop.get("name", "?"), laptop.get("memory_fit") or []
    if not records:
        return [f"{name}: no memory-fit measurements (python -m jana_tools lab memfit)"]
    out = []
    for record in records:
        measured = int(record["measured_bytes"])
        off = abs(estimate(record) - measured) / measured
        if off > tolerance:
            out.append(f"{name}: {record['model']} at {record['context']} tokens: estimate off by {off:.0%} of "
                       f"measured {measured / GB:.2f} GB (tolerance {tolerance:.0%})")  # fmt: skip
    return out


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _post(url: str, body: dict[str, Any], key: str, timeout: float) -> dict[str, Any]:
    reply = httpx.post(url, json=body, headers={"authorization": f"Bearer {key}"}, timeout=timeout)
    reply.raise_for_status()
    result: dict[str, Any] = reply.json()
    return result


def resident_bytes(pid: int) -> int:
    """The process's resident memory: on macOS its physical footprint (unified memory, Metal buffers included),
    elsewhere its resident set."""
    rss_text = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)], capture_output=True, text=True, check=False)
    rss = int(rss_text.stdout.strip() or 0) * 1024
    if platform.system() == "Darwin":
        out = subprocess.run(["footprint", "-p", str(pid)], capture_output=True, text=True, check=False).stdout
        found = re.search(r"Footprint:\s*([\d.]+)\s*(B|KB|MB|GB)", out)
        if found:
            footprint = int(float(found.group(1)) * {"B": 1, "KB": 1024, "MB": 1024**2, "GB": GB}[found.group(2)])
            return max(rss, footprint)
    return rss


@dataclass(frozen=True)
class Served:
    url: str
    key: str
    pid: int


@contextmanager
def serving(server: Path, gguf: Path, context: int, projector: Path | None = None, timeout_s: float = 300.0,
            alias: str | None = None) -> Iterator[Served]:  # fmt: skip
    """llama-server on loopback with `gguf` (and `projector`) at `context` and a fresh key, until the block ends.
    Raises when it does not answer `/health` within `timeout_s`. Used by the device-lab measurements."""
    port = _free_port()
    key = secrets.token_urlsafe(24)
    with tempfile.TemporaryDirectory() as tmp:
        key_file = Path(tmp) / "key"
        key_file.write_text(key)
        os.chmod(key_file, 0o600)
        args = [str(server), "--host", "127.0.0.1", "--port", str(port), "--api-key-file", str(key_file),
                "--model", str(gguf), "--alias", alias or gguf.stem, "--ctx-size", str(context), "--parallel", "1",
                "--no-webui", "--no-context-shift"]  # fmt: skip
        if projector is not None:
            args += ["--mmproj", str(projector)]
        process = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            base = f"http://127.0.0.1:{port}"
            deadline = time.monotonic() + timeout_s
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f"llama-server ended ({process.returncode}) before it was ready")
                try:
                    if httpx.get(base + "/health", timeout=2).status_code == 200:
                        break
                except httpx.HTTPError:
                    pass
                if time.monotonic() > deadline:
                    raise RuntimeError("llama-server did not become ready in time")
                time.sleep(0.5)
            yield Served(base, key, process.pid)
        finally:
            process.terminate()
            try:
                process.wait(10)
            except subprocess.TimeoutExpired:
                process.kill()


def measure(server: Path, gguf: Path, context: int, projector: Path | None = None, timeout_s: float = 300.0,
            extras_bytes: int = 0) -> dict[str, Any]:  # fmt: skip
    """Load `gguf` (and `projector`) in llama-server at `context` on loopback, generate a few tokens, read the
    resident memory."""
    with serving(server, gguf, context, projector, timeout_s) as served:
        _post(served.url + "/completion", {"prompt": "Count to five:", "n_predict": 16, "cache_prompt": False},
              served.key, timeout_s)  # fmt: skip
        time.sleep(1.0)
        measured = resident_bytes(served.pid)
    record = {"model": gguf.stem, "header": header(gguf), "context": context,
              "projector_bytes": projector.stat().st_size if projector is not None else 0,
              "extras_bytes": extras_bytes, "measured_bytes": measured}  # fmt: skip
    record["estimate_bytes"] = estimate(record)
    return record
