"""The KC → checker coverage matrix (VER-36, CUR-04): which verification tools can check each knowledge component of
every subject and level a stage launches, and which computational KCs nothing can check.

Three sources, read as they are, so the matrix is generic over subjects:
- the stage's catalogue (TABLE CUR-01a, `agent_core.store.catalogue`) says which subject-level pairs a stage
  launches;
- the tool register says which checkers exist for a pair at the stage: worker-executed compute tools of that stage or
  earlier whose subjects include the pack's subject (or `general`) and whose levels include its level;
- each pack's sources under `content/curriculum/<subject>/<level>/` give the KCs with the tools they name, and the
  items with the tools their `checks:` run, tagged with the KCs they assess.

A KC is computational when its kind is `procedural` (the kinds of CUR-04); conceptual and factual KCs are content
only and may name no tool. The gate fails when a computational KC names no checker for its pair, when a KC or an
item check names a tool that cannot check its pair at the stage, or when a launched subject has no checker of its
own. An item check whose tool its KC does not name is reported as a note: the KC should usually name it. A launched
pair with no pack yet is listed with what its KCs will have to satisfy; it does not fail the gate until its pack
exists.

    python -m jana_tools kc-coverage [S2]    # print the matrix
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

CURRICULUM = REPO_ROOT / "content" / "curriculum"
SUBJECTS = {"mth": "mathematics", "phy": "physics", "chm": "chemistry", "bio": "biology", "acc": "accounting"}
STAGES = ("S1", "S2", "S3", "S4", "S5")
COMPUTATIONAL = ("procedural",)
STAGE = "S2"  # the stage whose checkers M12 delivers; the default `python -m jana_tools` gate checks it


@dataclass
class KcRow:
    kc_id: str
    kind: str
    named: list[str]  # the checkers the KC names that can check its pair
    checked_by: list[str]  # the tools its items' checks run
    status: str  # "mapped", "content_only" or "unmapped"


@dataclass
class PackCoverage:
    subject: str
    level: str
    checkers: list[str]
    rows: list[KcRow] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Matrix:
    stage: str
    packs: list[PackCoverage]
    pending: list[str]  # launched pairs with no pack yet, with what their KCs must satisfy
    errors: list[str]


def _compute_tools() -> list[dict[str, Any]]:
    from agent_core.tools.generated.register import REGISTER

    return [t for t in REGISTER["toolsets"]["compute"]["tools"] if t["executor"] == "worker"]


def _refusal(tool: dict[str, Any] | None, stage: str, subject: str, level: str) -> str | None:
    """Why a tool cannot check a subject-level pair at a stage, or None when it can."""
    if tool is None:
        return "not a registered checker"
    if STAGES.index(tool["stage"]) > STAGES.index(stage):
        return f"a {tool['stage']} checker"
    if not ({SUBJECTS[subject], "general"} & set(tool["subjects"])):
        return f"not a {SUBJECTS[subject]} checker"
    if level.upper() not in tool["levels"]:
        return f"not a {level.upper()} level checker"
    return None


def checkers(stage: str, subject: str, level: str) -> list[str]:
    """The checkers that can verify a pair's KCs at a stage, in register order."""
    return [t["name"] for t in _compute_tools() if _refusal(t, stage, subject, level) is None]


def launched(stage: str) -> list[tuple[str, str]]:
    from agent_core.store.catalogue import catalogue

    return [(listing.subject, listing.level) for listing in catalogue(stage)]


def _records(folder: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for path in sorted(folder.glob("*.yaml")):
        loaded = yaml.safe_load(path.read_text())
        out.extend(loaded if isinstance(loaded, list) else [loaded])
    return out


def pack_coverage(stage: str, subject: str, level: str, root: Path = CURRICULUM) -> PackCoverage:
    tools = {t["name"]: t for t in _compute_tools()}
    pack = root / subject / level
    found = PackCoverage(subject, level, checkers(stage, subject, level))
    own = [t for t in found.checkers if "general" not in tools[t]["subjects"]]
    if not own:
        found.errors.append(f"{subject} {level}: no {SUBJECTS[subject]} checker exists at {stage}")
    kcs = [kc for kc in _records(pack / "kcs") if kc.get("status") == "active"]
    checked_by: dict[str, list[str]] = {}
    for item in _records(pack / "items"):
        for check_id, check in sorted((item.get("checks") or {}).items()):
            why = _refusal(tools.get(check["tool"]), stage, subject, level)
            if why:
                found.errors.append(f"{item['id']}: check {check_id} runs {check['tool']}, {why}")
            for kc_id in item.get("kc_ids", []):
                if check["tool"] not in checked_by.setdefault(kc_id, []):
                    checked_by[kc_id].append(check["tool"])
    for kc in kcs:
        named = []
        for tool in kc.get("tools", []):
            why = _refusal(tools.get(tool), stage, subject, level)
            if why:
                found.errors.append(f"{kc['id']}: names {tool}, {why}")
            else:
                named.append(tool)
        by_items = sorted(checked_by.get(kc["id"], []))
        if named:
            status = "mapped"
        elif kc["kind"] in COMPUTATIONAL:
            status = "unmapped"
            found.errors.append(f"{kc['id']}: a {kc['kind']} KC that names no checker for {subject} {level} at "
                                f"{stage} (items checked by: {', '.join(by_items) or 'none'})")  # fmt: skip
        else:
            status = "content_only"
        unnamed = [t for t in by_items if t not in named]
        if unnamed:
            found.notes.append(f"{kc['id']}: its items are checked by {', '.join(unnamed)}, which it does not name")
        found.rows.append(KcRow(kc["id"], kc["kind"], named, by_items, status))
    return found


def matrix(stage: str = STAGE, root: Path = CURRICULUM) -> Matrix:
    packs, pending = [], []
    for subject, level in launched(stage):
        if (root / subject / level / "kcs").is_dir():
            packs.append(pack_coverage(stage, subject, level, root))
        else:
            options = ", ".join(checkers(stage, subject, level))
            pending.append(f"{subject} {level}: no pack yet; each procedural KC will have to name one of {options}, "
                           f"and each item check run one of them")  # fmt: skip
    return Matrix(stage, packs, pending, [e for p in packs for e in p.errors])


def errors(stage: str = STAGE) -> list[str]:
    return matrix(stage).errors


def render(found: Matrix) -> str:
    lines = [f"KC → checker coverage at {found.stage} (VER-36)", ""]
    for pack in found.packs:
        counts = {s: sum(r.status == s for r in pack.rows) for s in ("mapped", "content_only", "unmapped")}
        lines.append(f"## {pack.subject} {pack.level}: {len(pack.rows)} KCs, "
                     + ", ".join(f"{n} {s.replace('_', ' ')}" for s, n in counts.items()))  # fmt: skip
        lines += ["", "| KC | Kind | Names | Items checked by | Status |", "| --- | --- | --- | --- | --- |"]
        for row in pack.rows:
            lines.append(f"| {row.kc_id} | {row.kind} | {', '.join(row.named) or '-'} | "
                         f"{', '.join(row.checked_by) or '-'} | {row.status} |")  # fmt: skip
        lines += [""] + [f"- note: {n}" for n in pack.notes] + [f"- error: {e}" for e in pack.errors]
        lines.append("")
    if found.pending:
        lines += ["## Launched with no pack yet", ""] + [f"- {p}" for p in found.pending] + [""]
    return "\n".join(lines).rstrip() + "\n"
