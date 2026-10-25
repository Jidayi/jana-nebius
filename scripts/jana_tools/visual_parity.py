"""Parity between the visual catalogue register and the client's renderers (VSL-02, VSL-18).

A renderer registered for a kind the register does not list fails, and so does a register kind at or before the
build's stage that the client cannot draw. Kinds on the `visual.spec` channel need a renderer in RENDERERS
(packages/renderers); kinds carried by board events need the client to handle their board event."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from . import REPO_ROOT

REGISTER = REPO_ROOT / "contracts/registers/visual-catalogue.json"
RENDERERS_SRC = Path("packages") / "renderers" / "src"
CLIENT_EVENTS = Path("packages") / "client-core" / "src" / "session.ts"
STAGES = ("S1", "S2", "S3", "S4", "S5")

_RENDERERS = re.compile(r"export const RENDERERS\b[^=]*=\s*\[([^\]]*)\]")
_DEFINITION = re.compile(
    r"export const (\w+)\s*(?::\s*VisualRenderer\s*)?=\s*(?:define\(\s*)?\{\s*kind:\s*\"([^\"]+)\""
)
_EVENTS = re.compile(r"export const KNOWN_EVENTS\s*=\s*new Set\(\[(.*?)\]\)", re.S)


def build_stage() -> str:
    """The stage this build ships (the same constant the tool registry filters on)."""
    from agent_core.tools.specs import BUILD_STAGE

    return BUILD_STAGE


def register_kinds(path: Path | None = None) -> list[dict[str, Any]]:
    from agent_core.assets.generated.visual_catalogue import VISUAL_CATALOGUE

    kinds: list[dict[str, Any]] = (json.loads(path.read_text()) if path is not None else VISUAL_CATALOGUE)["kinds"]
    return kinds


def renderer_kinds(root: Path = REPO_ROOT) -> tuple[list[str], list[str]]:
    """The kinds of the renderers listed in RENDERERS, in order, and any entry whose kind cannot be read."""
    src = root / RENDERERS_SRC
    listed = _RENDERERS.search((src / "index.ts").read_text())
    if listed is None:
        return [], [f"{RENDERERS_SRC / 'index.ts'}: no RENDERERS list"]
    definitions: dict[str, str] = {}
    for path in sorted(src.rglob("*.ts*")):
        definitions |= dict(_DEFINITION.findall(path.read_text()))
    kinds, errors = [], []
    for name in (n.strip() for n in listed[1].split(",")):
        if not name:
            continue
        if name in definitions:
            kinds.append(definitions[name])
        else:
            errors.append(f"renderer {name} in RENDERERS has no `{name}: VisualRenderer = {{ kind: ... }}` definition")
    return kinds, errors


def client_events(root: Path = REPO_ROOT) -> set[str]:
    found = _EVENTS.search((root / CLIENT_EVENTS).read_text())
    return set(re.findall(r"\"([^\"]+)\"", found[1])) if found else set()


def _board_drawn(channel: str, events: set[str]) -> bool:
    if channel.endswith(".*"):
        return any(e.startswith(channel[:-1]) for e in events)
    return channel in events


def parity_errors(kinds: list[dict[str, Any]], renderers: list[str], events: set[str], stage: str) -> list[str]:
    """Errors for a client whose renderers draw `renderers` and whose store handles `events`, in a `stage` build."""
    by_kind = {k["kind"]: k for k in kinds}
    errors = [f"renderer registered for {kind}, which is not in the visual catalogue register"
              for kind in sorted(set(renderers) - set(by_kind))]  # fmt: skip
    errors += [f"more than one renderer registered for {kind}" for kind in sorted({k for k in renderers
               if renderers.count(k) > 1})]  # fmt: skip
    limit = STAGES.index(stage)
    for kind in sorted(by_kind):
        row = by_kind[kind]
        if STAGES.index(row["stage"]) > limit:
            continue
        channel = row.get("channel", "visual.spec")
        if channel == "visual.spec":
            if kind not in renderers:
                errors.append(f"{kind} (stage {row['stage']}) has no renderer in a {stage} build")
        elif channel.startswith("board.") and not _board_drawn(channel, events):
            errors.append(f"{kind} (stage {row['stage']}) is carried by {channel}, which the client does not handle")
    return errors


def check(root: Path = REPO_ROOT, register: Path = REGISTER, stage: str | None = None) -> list[str]:
    """Everything CI runs for VSL-02 parity."""
    renderers, errors = renderer_kinds(root)
    return errors + parity_errors(register_kinds(register), renderers, client_events(root), stage or build_stage())
