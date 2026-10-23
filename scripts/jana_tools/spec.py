"""Read requirement IDs and their status from the private specification checkout (docs/).
Only IDs, priorities and statuses are read; no specification text is copied into code."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from . import REPO_ROOT

DOCS = REPO_ROOT / "docs"
_HEADING = re.compile(r"^### ([A-Z0-9]{3}-\d{2}) — ")
_META = re.compile(r"^Stage: (S[0-5]).*? · Priority: (must|should|may)(?:.*?Status: (\S+))?")
ID = re.compile(r"\b[A-Z][A-Z0-9]{2}-\d{2}\b")


@dataclass(frozen=True)
class Requirement:
    id: str
    stage: str
    priority: str
    retired: bool
    file: Path


@cache
def requirements(docs: Path = DOCS) -> dict[str, Requirement]:
    found: dict[str, Requirement] = {}
    for path in sorted((docs / "specification").glob("*.md")) + sorted((docs / "product").glob("*.md")):
        lines = path.read_text().splitlines()
        fenced = False
        for i, line in enumerate(lines):
            if line.startswith("```"):
                fenced = not fenced  # a requirement inside a code block is an example, not a requirement
                continue
            heading = _HEADING.match(line)
            if fenced or not heading:
                continue
            meta = next((m for m in (_META.match(x) for x in lines[i + 1 : i + 4]) if m), None)
            if meta:
                found[heading[1]] = Requirement(heading[1], meta[1], meta[2], meta[3] == "retired", path)
    return found


def active(rid: str, docs: Path = DOCS) -> bool:
    req = requirements(docs).get(rid)
    return req is not None and not req.retired


def table_rows(text: str, label: str) -> list[list[str]]:
    """Cells of the Markdown table that follows the line starting with `label` (for example
    'TABLE SEC-01a'). Header and separator rows are skipped."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(label))
    rows = []
    i = start + 1
    while i < len(lines) and not lines[i].startswith("|"):
        i += 1
    while i < len(lines) and lines[i].startswith("|"):
        rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
        i += 1
    return rows[2:]
