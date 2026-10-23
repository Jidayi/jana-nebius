"""The pilot device survey (PLT-29, EVL-14): how many pilot students' machines fall below the minimum laptop.

Each surveyed machine is one row of `evals/devlab/survey/template.csv`'s columns: its memory, CPU (model, year and
architecture), free disk and GPU, the hardware class the app's own rules give it from that hardware (the prediction
the app makes before any benchmark), and which minimum-laptop checks it fails. A row comes from the app's probe run
on the machine (`python -m jana_tools lab survey <file>`), so the survey and the product use one rule. `report` states
the share below the minimum, with its interval, and what those machines lack; that share is reported with the S2 exit
metrics (PRD-17). Machines are identified by a survey code only; no student is named.
"""

from __future__ import annotations

import csv
import datetime
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from . import report as rep

TEMPLATE = REPO_ROOT / "evals" / "devlab" / "survey" / "template.csv"
COLUMNS = ("machine", "surveyed_on", "ram_gb", "cpu_model", "cpu_year", "arch", "free_disk_gb", "gpu",
           "hardware_class", "below_minimum", "short")  # fmt: skip


def row(probe: Any, machine: str, surveyed_on: str | None = None) -> dict[str, str]:
    """One machine's survey row from the app's probe, with the class the app's rules give it."""
    from agent_core.config import Settings
    from agent_core.router.probe import GB, choose_class

    choice = choose_class(probe, None, Settings())
    gpu = "; ".join(f"{g.kind} {g.name}" for g in probe.gpus) or "none"
    short = "; ".join(f"{s.check} {s.have}/{s.need} {s.unit}".strip() for s in choice.shortfalls)
    return {"machine": machine, "surveyed_on": surveyed_on or datetime.date.today().isoformat(),
            "ram_gb": f"{probe.ram_bytes / GB:.1f}", "cpu_model": probe.cpu_model,
            "cpu_year": str(probe.cpu_year or ""), "arch": probe.arch,
            "free_disk_gb": f"{probe.free_disk_bytes / GB:.1f}", "gpu": gpu,
            "hardware_class": choice.hardware_class, "below_minimum": "yes" if choice.shortfalls else "no",
            "short": short}  # fmt: skip


def read(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def errors(rows: list[dict[str, str]], header: list[str] | None = None) -> list[str]:
    """Why survey rows cannot be reported: a missing column, or a row without its class or its minimum verdict."""
    out = [f"the survey has no {c} column" for c in COLUMNS if header is not None and c not in header]
    for n, r in enumerate(rows, 1):
        if r.get("hardware_class") not in ("content_only", "low", "mid", "high"):
            out.append(f"row {n}: no hardware class")
        if r.get("below_minimum") not in ("yes", "no"):
            out.append(f"row {n}: no minimum-laptop verdict")
    return out


def report(rows: list[dict[str, str]]) -> dict[str, Any]:
    """The share of surveyed machines below the minimum laptop, with its interval, the classes, and what they lack."""
    below = [r for r in rows if r["below_minimum"] == "yes"]
    lacking: dict[str, int] = {}
    for r in below:
        for part in filter(None, (p.strip() for p in r.get("short", "").split(";"))):
            check = part.split()[0]
            lacking[check] = lacking.get(check, 0) + 1
    classes: dict[str, int] = {}
    for r in rows:
        classes[r["hardware_class"]] = classes.get(r["hardware_class"], 0) + 1
    return {"machines": len(rows), "below_minimum": rep.result(len(below), len(rows)), "lacking": lacking,
            "classes": classes}  # fmt: skip


def append_this_machine(path: Path, machine: str | None = None) -> dict[str, str]:
    """Probe this machine as the app does and append its row (the file is started from the template's header)."""
    import platform
    import tempfile

    from agent_core.router.probe import probe_machine

    found = row(probe_machine(Path(tempfile.gettempdir())), machine or platform.node() or "machine")
    fresh = not path.exists()
    with path.open("a", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        if fresh:
            writer.writeheader()
        writer.writerow(found)
    return found
