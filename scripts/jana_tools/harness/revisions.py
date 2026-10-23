"""Tuning discipline (EVL-19) and regression cases for every fixed failure (EVL-20).

A tuning unit is one prompt role, guidance block, model-family note, skill, the template catalogue or the router
settings. A revision changes exactly one unit; a tuning cycle has at most `MAX_CANDIDATES` candidate revisions; the
revision log (`evals/revisions.jsonl`) records each with its fingerprints before and after and the development-suite
results it was rerun against. A commit that says it fixes an incident (`INC-n`, PRV-21) or a user report (`RPT-n`,
PRV-22) must add a `regression` split item linked to that source in the same change.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from .. import REPO_ROOT
from .bank import BankItem

LOG = REPO_ROOT / "evals" / "revisions.jsonl"
MAX_CANDIDATES = 3
_UNITS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^content/agent/roles/([\w-]+)\.md$"), "prompt:{0}"),
    (re.compile(r"^content/agent/soul/"), "prompt:soul"),
    (re.compile(r"^content/agent/guidance/([\w-]+)\.md$"), "guidance:{0}"),
    (re.compile(r"^content/agent/families/([\w-]+)\.md$"), "family:{0}"),
    (re.compile(r"^content/agent/templates/"), "templates"),
    (re.compile(r"^skills/[\w-]+/([\w-]+)/"), "skill:{0}"),
    (re.compile(r"^services/agent-core/agent_core/router/(router\.yaml|recommended_models\.json)$"), "router"),
)
SOURCE = re.compile(r"\b((?:INC|RPT)-\d+)\b")
REQUIRED = ("revision", "cycle", "date", "unit", "files", "fingerprints", "results")


class RevisionError(ValueError):
    """A revision the log refuses (EVL-19)."""


def unit_of(path: str) -> str | None:
    for pattern, unit in _UNITS:
        if match := pattern.search(path):
            return unit.format(*match.groups())
    return None


def units(paths: Iterable[str]) -> set[str]:
    return {u for p in paths if (u := unit_of(p)) is not None}


EXEMPTION = re.compile(r"^Tuning-exemption:\s*(D\d+)\s*$", re.M)


def commit_errors(message: str, modified: Iterable[str], decided: set[str]) -> list[str]:
    """EVL-19 for one commit. Only modified units count (writing a new unit is authoring, not tuning). A change a
    decided decision requires across several units (a model family swap, say) names it: `Tuning-exemption: D58`."""
    exemption = EXEMPTION.search(message)
    if exemption and exemption[1] in decided:
        return []
    errors = revision_errors(modified)
    if exemption:
        errors = [f"Tuning-exemption names {exemption[1]}, which is not a decided decision", *errors]
    return errors


def revision_errors(paths: Iterable[str]) -> list[str]:
    touched = sorted(units(paths))
    if len(touched) > 1:
        return [f"one change per revision (EVL-19): this revision touches {len(touched)} tuning units: "
                f"{', '.join(touched)}"]  # fmt: skip
    return []


def read_log(path: Path = LOG) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.is_file() else []


def append(entry: dict[str, Any], path: Path = LOG) -> None:
    """Record one revision; refuse it when it breaks the tuning discipline."""
    missing = [k for k in REQUIRED if k not in entry]
    if missing:
        raise RevisionError(f"revision record lacks {', '.join(missing)}")
    if problems := revision_errors(entry["files"]):
        raise RevisionError(problems[0])
    touched = units(entry["files"])
    if touched != {entry["unit"]}:
        raise RevisionError(f"revision says unit {entry['unit']} but its diff touches {sorted(touched) or 'none'}")
    if not entry["results"]:
        raise RevisionError("rerun the affected development suites before recording the revision (EVL-19)")
    log = read_log(path)
    if any(r["revision"] == entry["revision"] for r in log):
        raise RevisionError(f"revision {entry['revision']} is already recorded")
    candidates = [r for r in log if r["cycle"] == entry["cycle"]]
    if len(candidates) >= MAX_CANDIDATES:
        raise RevisionError(f"cycle {entry['cycle']} already has {MAX_CANDIDATES} candidate revisions (EVL-19)")
    with path.open("a") as out:
        out.write(json.dumps(entry, sort_keys=True) + "\n")


def regression_errors(messages: Iterable[str], bank: Iterable[BankItem], changed: Iterable[str]) -> list[str]:
    """A fix referencing an incident or report must add a regression item linked to it in the same change."""
    changed_files = set(changed)
    linked: dict[str, list[str]] = {}
    for item in bank:
        sidecar = item.suite_file.removesuffix(".yaml") + ".meta.yaml"
        if item.split != "regression" or not {item.suite_file, sidecar} & changed_files:
            continue
        sources = item.meta.get("regression_of") or []
        for source in [sources] if isinstance(sources, str) else sources:
            linked.setdefault(source, []).append(item.item_id)
    errors = []
    for source in sorted({s for m in messages for s in SOURCE.findall(m)}):
        if source not in linked:
            errors.append(f"{source}: the fix adds no regression item linked to it (EVL-20)")
    return errors
