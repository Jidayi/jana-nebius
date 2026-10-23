"""Immutable origin retrieval (OPS-13). No network client is implicit."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from agent_core.config.operations import atomic_json
from agent_core.contracts import errors as contract_errors

from .operations import Candidate, Ring, USBCheck, kit_errors, usb_batch_errors
from .versions import form_errors


def artefact_path(kind: str, artefact_id: str, version: str, sha256: str) -> str:
    if not re.fullmatch(r"[a-f0-9]{64}", sha256):
        raise ValueError("OPS-13: invalid digest")
    parts = (kind, artefact_id, version, sha256)
    if any(not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9._@-]*", p) or p in {".", ".."} for p in parts):
        raise ValueError("OPS-13: invalid path component")
    return "/" + "/".join(parts)


def fetch_verified(
    origins: tuple[str, ...],
    kind: str,
    artefact_id: str,
    version: str,
    sha256: str,
    destination: Path,
    fetch: Callable[[str], bytes],
    verify: Callable[[bytes], None],
) -> Path:
    suffix = artefact_path(kind, artefact_id, version, sha256)
    destination.parent.mkdir(parents=True, exist_ok=True)
    for origin in origins:
        if not origin.startswith("https://"):
            raise ValueError("OPS-13: HTTPS origin required")
        try:
            data = fetch(origin.rstrip("/") + suffix)
            if hashlib.sha256(data).hexdigest() != sha256:
                continue
            verify(data)
        except (OSError, ValueError):
            continue
        fd, temporary = tempfile.mkstemp(dir=destination.parent, prefix=destination.name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return destination
    raise OSError("OPS-13: waiting_for_network; no verified origin available")


KIT_CONTRACT = "ops/usb-kit"
KIT_FORMAT = "jana.usb-kit.1"
UNSIGNED = "$: 'signature' is a required property"  # the one gap an unsigned manifest may have


@dataclass(frozen=True)
class KitArtifact:
    category: str
    kind: str
    source: Path
    relative_path: str
    sha256: str
    channel: str
    ring: str


def build_kit(
    candidate: Candidate,
    ring: Ring,
    destination: str,
    artefacts: list[KitArtifact],
    output: Path,
    kit_id: str,
    matrix_version: int,
    created_at: str,
    sign: Callable[[dict[str, Any]], dict[str, Any]],
) -> Path:
    errors = kit_errors(candidate, ring, destination, {a.category for a in artefacts})
    errors += form_errors("usb_kit", kit_id)
    if type(matrix_version) is not int or matrix_version <= 0:
        errors.append("OPS-15: matrix version required")
    if output.exists():
        errors.append("OPS-15: kit destination already exists")
    names = set()
    for artefact in artefacts:
        relative = Path(artefact.relative_path)
        if (
            relative.is_absolute()
            or not relative.parts
            or any(p in {".", ".."} for p in relative.parts)
            or "\\" in artefact.relative_path
            or relative.as_posix().casefold() == "kit.json"
            or artefact.relative_path.casefold() in names
        ):
            errors.append("OPS-15: unsafe or duplicate kit path")
        names.add(artefact.relative_path.casefold())
        if destination == "school" and (artefact.channel != "stable" or artefact.ring != "R3"):
            errors.append("OPS-15: nonstable artefact in distribution inventory")
        if (
            not artefact.source.is_file()
            or not re.fullmatch(r"[a-f0-9]{64}", artefact.sha256)
            or hashlib.sha256(artefact.source.read_bytes()).hexdigest() != artefact.sha256
        ):
            errors.append("OPS-15: artefact bytes differ from the release inventory")
    if errors:
        raise ValueError("; ".join(errors))
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(dir=output.parent, prefix="kit-"))
    try:
        files = []
        for artefact in artefacts:
            target = staging / artefact.relative_path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(artefact.source, target)
            if hashlib.sha256(target.read_bytes()).hexdigest() != artefact.sha256:
                raise ValueError("OPS-15: source changed during kit build")
            files.append(
                {
                    "path": artefact.relative_path,
                    "kind": artefact.kind,
                    "size_bytes": target.stat().st_size,
                    "sha256": artefact.sha256,
                }
            )
        manifest = {
            "format": KIT_FORMAT,
            "kit_id": kit_id,
            "matrix_version": matrix_version,
            "created_at": created_at,
            "candidate": destination == "candidate",
            "channel": candidate.channel,
            "release_version": candidate.version,
            "files": files,
        }
        # The manifest is checked against the kit contract (D39) before any signature is asked for, and again signed.
        problems = [p for p in contract_errors(KIT_CONTRACT, manifest) if p != UNSIGNED]
        if problems:
            raise ValueError(f"OPS-15: kit manifest does not match its contract ({problems[0]})")
        signed = sign(manifest)
        if {k: v for k, v in signed.items() if k != "signature"} != manifest or "signature" not in signed:
            raise ValueError("OPS-15: signer returned another manifest")
        if problems := contract_errors(KIT_CONTRACT, signed):
            raise ValueError(f"OPS-15: signed kit listing does not match its contract ({problems[0]})")
        atomic_json(staging / "kit.json", signed)
        os.rename(staging, output)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return output


class DispatchStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def record(
        self,
        manifest: dict[str, Any],
        kit_sha256: str,
        school: str,
        operator: str,
        at: datetime,
        batch_size: int,
        checks: list[USBCheck],
    ) -> None:
        if (
            manifest.get("candidate") is not False
            or manifest.get("channel") != "stable"
            or not school.strip()
            or not operator.strip()
            or not re.fullmatch(r"[a-f0-9]{64}", kit_sha256)
        ):
            raise ValueError("OPS-15: distribution kit and dispatcher required")
        if errors := usb_batch_errors(batch_size, kit_sha256, checks):
            raise ValueError("; ".join(errors))
        records = json.loads(self.path.read_text()) if self.path.is_file() else []
        records.append(
            {
                "kit_id": manifest["kit_id"],
                "kit_sha256": kit_sha256,
                "school": school,
                "dispatcher": operator,
                "dispatched_at": at.isoformat(),
                "received_at": None,
            }
        )
        atomic_json(self.path, records)
