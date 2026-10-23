"""Agent-proposed skill patches (SKL-20): proposals, never live edits.

Agents in the internal authoring environment and the evaluation harness file `{skill, base_version, diff, rationale,
evidence}` into the authoring queue (`evals/skill-proposals/`, never a device and never a teacher queue). Evidence is
eval case ids of the skill's own colocated evals, or ids of separately consented de-identified research statistics
(`stat:<id>`, D51); never student text. An internal curriculum author (`rev_*`) applies, edits or rejects each one. A
proposal against a stale base version is rejected. An applied proposal is an ordinary change under SKL-18: the skill's
minor version is bumped and its status goes back to `in_review`, so it ships only after review, a passing eval run
(EVL-07) and a signed release bundle (SKL-19)."""

from __future__ import annotations

import json
import re
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import REPO_ROOT
from .skills import SKILLS

QUEUE = REPO_ROOT / "evals" / "skill-proposals"
FIELDS = ("skill", "base_version", "diff", "rationale", "evidence")
REVIEWER = re.compile(r"^rev_[a-z0-9_]{2,40}$")
EVIDENCE = re.compile(r"^(case:[a-z0-9_]{3,80}|stat:[a-z0-9_.-]{3,80})$")
QUOTED = re.compile(r"[\"“][^\"”]{20,}[\"”]")  # a quotation long enough to be someone's words


class ProposalRefused(ValueError):
    pass


@dataclass(frozen=True)
class Proposal:
    skill: str
    base_version: str
    diff: str
    rationale: str
    evidence: tuple[str, ...]

    @classmethod
    def of(cls, data: dict[str, Any]) -> Proposal:
        if sorted(data) != sorted(FIELDS):
            raise ProposalRefused(f"a proposal has exactly the fields {', '.join(FIELDS)}")
        return cls(str(data["skill"]), str(data["base_version"]), str(data["diff"]), str(data["rationale"]),
                   tuple(str(e) for e in data["evidence"]))  # fmt: skip


def _skill(name: str, root: Path) -> Any:
    from agent_core.assets.skills import KINDS, discover, parse

    for path in discover(root, KINDS):
        if path.parent.name == name:
            return parse(path)
    raise ProposalRefused(f"there is no skill named {name}")


def file_proposal(data: dict[str, Any], root: Path = SKILLS, queue: Path = QUEUE) -> Path:
    """Validate and queue one proposal; nothing in the skill changes."""
    from .skill_evals import load_cases

    proposal = Proposal.of(data)
    skill = _skill(proposal.skill, root)
    if proposal.base_version != skill.version:
        raise ProposalRefused(f"stale base version {proposal.base_version}; {skill.name} is at {skill.version}")
    if not proposal.evidence:
        raise ProposalRefused("a proposal names its evidence: eval case ids or consented statistics")
    cases = {c["id"] for c in load_cases(skill.folder)[0]}
    for item in proposal.evidence:
        if not EVIDENCE.match(item):
            raise ProposalRefused("evidence is case:<eval case id> or stat:<statistic id>, never student text")
        if item.startswith("case:") and item.removeprefix("case:") not in cases:
            raise ProposalRefused(f"{item} is not one of {skill.name}'s eval cases")
    if QUOTED.search(proposal.rationale) or QUOTED.search(proposal.diff):
        raise ProposalRefused("a proposal quotes no one; describe the pattern in your own words")
    queue.mkdir(parents=True, exist_ok=True)
    out = queue / f"{skill.name}.{skill.version}.{len(list(queue.glob(f'{skill.name}.*.json'))) + 1}.json"
    out.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return out


def apply_proposal(path: Path, reviewer: str, root: Path = SKILLS) -> Path:
    """An internal curriculum author applies a queued proposal: the diff, a minor version bump and status
    `in_review`. Returns the edited SKILL.md."""
    if not REVIEWER.match(reviewer):
        raise ProposalRefused("only an internal curriculum author (rev_*) applies a proposal")
    proposal = Proposal.of(json.loads(path.read_text()))
    skill = _skill(proposal.skill, root)
    if proposal.base_version != skill.version:
        raise ProposalRefused(f"stale base version {proposal.base_version}; {skill.name} is at {skill.version}")
    with tempfile.NamedTemporaryFile("w", suffix=".diff", delete=False) as handle:
        handle.write(proposal.diff)
    # Git applies narrow unified hunks consistently on all supported platforms; macOS patch rejects them.
    applied = subprocess.run(["git", "apply", "--no-index", "--unidiff-zero", "--whitespace=nowarn", handle.name],
                             cwd=skill.folder, capture_output=True, text=True)  # fmt: skip
    Path(handle.name).unlink()
    if applied.returncode != 0:
        raise ProposalRefused(f"the diff does not apply: {applied.stderr.strip()[:200]}")
    major, _, minor = skill.version.partition(".")
    text = skill.path.read_text()
    text = re.sub(r'^version: "?[0-9.]+"?$', f'version: "{major}.{int(minor or 0) + 1}"', text, count=1, flags=re.M)
    text = re.sub(r"^status: \w+$", "status: in_review", text, count=1, flags=re.M)
    skill.path.write_text(text)
    path.unlink()  # the queue holds open proposals only
    return skill.path
