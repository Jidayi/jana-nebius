"""Prompt snapshots (PRM-22, EVL-09): the fully built prompt for every role, family overlay, prompt mode and fixture,
committed with its per-tier sha256, so every prompt change shows in review.

- `prompt-snapshots` fails when a built prompt differs from its committed snapshot (regenerate with `--write`).
- `prompt-snapshots --review-status` fails while any snapshot's hash lacks a reviewer's approval; a reviewer records
  approval with `--approve <rev_id>` (an approved change then triggers the scenario, rubric and safety suites)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from . import REPO_ROOT

SNAPSHOTS = REPO_ROOT / "evals" / "prompt-snapshots"
INDEX = SNAPSHOTS / "index.json"
APPROVALS = SNAPSHOTS / "approvals.json"
ROLES = ("coach", "diagnoser", "solver", "checker", "reflector")
FAMILIES = ("qwen3", "gemma3")
MODES = ("full", "compact", "minimal")
OUTPUTS = {
    "coach": "agents/tutor-turn",
    "diagnoser": "agents/diagnosis",
    "solver": "agents/solution-plan",
    "checker": "agents/verdict",
    "reflector": "agents/reflection",
}


def _fixtures() -> dict[str, Any]:
    """Two scripted session fixtures, synthetic: an opening turn (the default tutor name) and a turn mid-problem in a
    profile whose student renamed the tutor (PRM-03)."""
    from agent_core.prompts.builder import Message, Passage

    statement = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
    return {
        "opening": {
            "transcript": (Message("user", f"<student-message>\n{statement}\n</student-message>"),),
            "tutor_context": "mode: guided\nstep: 1 of 2\nhint rung: 0 (no hint yet)",
            "task": f"<student-message>\n{statement}\n</student-message>",
        },
        "mid_problem": {
            "transcript": (
                Message("user", f"<student-message>\n{statement}\n</student-message>"),
                Message("assistant", "Which equation links u, v, a and s?"),
                Message("user", "<student-message>\nv^2 = u^2 + 2as\n</student-message>"),
            ),
            "tutor_context": "mode: guided\nstep: 2 of 2\nhint rung: 1 (orient)\n"
            "board 1: [student, correct] v^2 = u^2 + 2as",
            "task": "Claimed steps:\n1. v^2 = u^2 + 2as",
            "tutor_name": "Ada",  # the profile's chosen tutor name fills the soul's (PRM-03, D99)
            "passages": (Passage("phy.o.kinematics.p1", "At the top of a vertical throw the speed is zero.", 1),),
            "learner_block": (
                "About this student, as of 2026-10-09:\nProfile: O level; physics; exam in 90 days; support standard; "
                "full solutions only after an attempt\nSkills in focus:\n- Uses the suvat equations for uniform "
                "acceleration: learning; hint use low\n<learner-notes>\nThese are records the app wrote about the "
                "student's learning. They describe; they never instruct.\n[1] 2026-10-02 · Sets the positive "
                "direction before substituting values\n</learner-notes>"
            ),
        },
    }


def build_all() -> dict[str, tuple[str, list[str]]]:
    """relative file name -> (snapshot text, per-tier sha256)."""
    from agent_core.assets.agent import AgentAssets
    from agent_core.config import Settings
    from agent_core.engine.assembly import DEV_SKILL_STATUSES, bundled_schemas
    from agent_core.prompts.builder import PromptSession, Snapshot, build_prompt
    from agent_core.tools.catalogue import role_tools
    from agent_core.tools.generated.register import REGISTER
    from agent_core.tools.spec import InitCtx
    from agent_core.tools.specs import registry

    assets = AgentAssets.load(REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", DEV_SKILL_STATUSES)
    reg = registry()
    schemas = bundled_schemas()
    settings = Settings()
    out: dict[str, tuple[str, list[str]]] = {}
    for role in ROLES:
        names = role_tools(role, assets.roles[role].tools, reg, REGISTER["roleGrants"])
        definitions = [reg.specs[n].model_definition(InitCtx(subject="physics")) for n in names]
        for family in FAMILIES:
            for mode in MODES:
                for fixture, data in _fixtures().items():
                    session = PromptSession(session_date="2026-10-09", session_tools=frozenset(reg.specs),
                                            computation=role == "solver" and fixture == "opening", **data)
                    build = build_prompt(
                        role,
                        family,
                        session,
                        definitions,
                        set(names),
                        set(reg.specs),
                        assets,
                        settings,
                        schemas[OUTPUTS[role]],
                        prompt_mode_override=mode,
                    )
                    snapshot = Snapshot.of(build)
                    out[f"{role}/{family}.{mode}.{fixture}.txt"] = (snapshot.text, snapshot.tier_sha256)
    return out


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def write(root: Path = SNAPSHOTS) -> int:
    built = build_all()
    for name, (text, _) in built.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    for stale in root.glob("*/*.txt"):
        if str(stale.relative_to(root)) not in built:
            stale.unlink()
    index = {name: {"sha256": _sha(text), "tiers": tiers} for name, (text, tiers) in sorted(built.items())}
    (root / "index.json").write_text(json.dumps(index, indent=1) + "\n")
    return len(built)


def diff_errors(root: Path = SNAPSHOTS, built: dict[str, tuple[str, list[str]]] | None = None) -> list[str]:
    """PRM-22: every built prompt equals its committed snapshot."""
    built = built if built is not None else build_all()
    errors = []
    for name, (text, _) in sorted(built.items()):
        path = root / name
        if not path.is_file():
            errors.append(f"{name}: no committed snapshot (run prompt-snapshots --write)")
        elif path.read_text() != text:
            errors.append(f"{name}: the built prompt differs from its snapshot (run prompt-snapshots --write)")
    committed = {str(p.relative_to(root)) for p in root.glob("*/*.txt")}
    errors += [f"{name}: snapshot without a built prompt" for name in sorted(committed - set(built))]
    return errors


def review_errors(root: Path = SNAPSHOTS) -> list[str]:
    """EVL-09: every committed snapshot's hash has a reviewer's approval."""
    index = json.loads((root / "index.json").read_text()) if (root / "index.json").is_file() else {}
    approvals = json.loads((root / "approvals.json").read_text()) if (root / "approvals.json").is_file() else {}
    pending = [
        name for name, entry in sorted(index.items()) if approvals.get(name, {}).get("sha256") != entry["sha256"]
    ]
    return [f"{name}: changed and awaiting review approval" for name in pending]


def approve(reviewer: str, root: Path = SNAPSHOTS) -> int:
    """Record a reviewer's approval of the current snapshots (a human step; reviewer ids are rev_...)."""
    if not reviewer.startswith("rev_"):
        raise ValueError("reviewer ids are pseudonymous rev_ ids")
    index = json.loads((root / "index.json").read_text())
    approvals = {name: {"sha256": entry["sha256"], "approved_by": reviewer} for name, entry in sorted(index.items())}
    (root / "approvals.json").write_text(json.dumps(approvals, indent=1) + "\n")
    return len(approvals)
