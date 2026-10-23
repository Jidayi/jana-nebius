"""M23 governance records one at a time, then assembled into the files the gates read.

Each record is filled the day its event happens (counsel signs off, the tabletop runs, the red team reports), so each
can be checked on its own with the gate's own rules; `assemble` then writes the release evidence read by
`m23 release-check` and `release stage S2 --m23-evidence`, and the programme file read by `m23 pilot-start-check`.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

from ..m23 import gates, programme
from .placeholders import placeholder_errors

SECTIONS = ("counsel", "tabletop", "redteam", "security")
PROGRAMME = ("country", "protocol", "wtp", "experiments")


def record_errors(
    kind: str,
    record: Any,
    *,
    candidate: str = "",
    stage: str = "S2",
    gate: str | None = None,
    today: date | None = None,
) -> list[str]:
    """What the gate says about one filled record ([] means this record would not block its gate). A tabletop is
    checked for `gate`, or for the gate it names (PRV-21: one per stage gate)."""
    if kind in SECTIONS:
        return gates.section_errors(kind, record, candidate=candidate, stage=stage, gate=gate, today=today)
    if kind == "protocol":
        return programme.protocol_errors(record)
    if kind == "wtp":
        return programme.wtp_errors(record)
    if kind == "experiments":
        if not isinstance(record, list):
            return ["BIZ-14: the experiment register is a list (use [] when no pricing experiment ran)"]
        return programme.experiment_errors(record)
    if kind == "country":
        return programme.country_errors(record)
    if kind == "contacts":
        contacts = record.get("contacts") if isinstance(record, dict) else None
        if (
            not isinstance(contacts, list)
            or not contacts
            or not all(isinstance(c, str) and c.strip() for c in contacts)
        ):
            return ["SEC-26: a non-empty list of licence-contact references is required"]
        return placeholder_errors("SEC-26", record)
    raise KeyError(f"unknown record kind {kind!r}")


def _load(folder: Path, name: str) -> Any:
    path = folder / f"{name}.json"
    return json.loads(path.read_text()) if path.is_file() else None


def tabletop_file(gate: str) -> str:
    """The tabletop drill's record for one stage gate (PRV-21): each gate keeps its own exercise."""
    return f"tabletop-{gate}"


def assemble(
    folder: Path, *, candidate: str, stage: str, gate: str, out: Path | None = None, today: date | None = None
) -> dict[str, Any]:
    """Write release.json (and programme.json when the pilot records are present) from the records in `folder`.
    Missing records are left out, so the gate names them; nothing is filled in on the owner's behalf."""
    out = out or folder
    release: dict[str, Any] = {"candidate": candidate, "stage": stage, "gate": gate}
    for name in SECTIONS:
        value = _load(folder, name)
        if name == "tabletop":  # this gate's own exercise, else the hand-filled template copy
            value = _load(folder, tabletop_file(gate)) or value
        if value is not None:
            release[name] = value
    written = {"release": str(out / "release.json")}
    (out / "release.json").write_text(json.dumps(release, indent=2) + "\n")
    errors = gates.release_errors(release, candidate=candidate, stage=stage, gate=gate, today=today)
    pieces = {name: _load(folder, name) for name in PROGRAMME}
    if any(value is not None for value in pieces.values()):
        body = {
            "country": pieces["country"] or {},
            "protocol": pieces["protocol"] or {},
            "wtp": pieces["wtp"] or {},
            "experiments": pieces["experiments"] if pieces["experiments"] is not None else [],
            "release": release,
        }
        (out / "programme.json").write_text(json.dumps(body, indent=2) + "\n")
        written["programme"] = str(out / "programme.json")
    return {"written": written, "release_errors": errors}
