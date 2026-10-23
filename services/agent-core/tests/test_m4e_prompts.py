"""M4.e: the prompt builder (PRM-09 to PRM-14, PRM-22, EVL-09)."""

import ast
import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from agent_core.assets.agent import AgentAssets
from agent_core.config import Settings
from agent_core.engine.assembly import DEV_SKILL_STATUSES, bundled_schemas
from agent_core.prompts.builder import TIER_NAMES, Message, Passage, PromptSession, build_prompt
from agent_core.tools.catalogue import role_tools
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.spec import InitCtx
from agent_core.tools.specs import registry
from jana_tools import REPO_ROOT
from jana_tools import prompt_snapshots as snapshots

CONTENT = REPO_ROOT / "content" / "agent"
SCHEMAS = bundled_schemas()
OUTPUTS = {
    "coach": "agents/tutor-turn",
    "diagnoser": "agents/diagnosis",
    "solver": "agents/solution-plan",
    "checker": "agents/verdict",
    "reflector": "agents/reflection",
}


def assets(content: Path = CONTENT, skills: Path = REPO_ROOT / "skills") -> AgentAssets:
    return AgentAssets.load(content, skills, DEV_SKILL_STATUSES)


def build(
    role: str,
    session: PromptSession,
    loaded: AgentAssets | None = None,
    family: str = "qwen3",
    mode: str | None = None,
    settings: Settings | None = None,
):
    reg = registry()
    loaded = loaded or assets()
    names = role_tools(role, loaded.roles[role].tools, reg, REGISTER["roleGrants"])
    definitions = [reg.specs[n].model_definition(InitCtx()) for n in names]
    return build_prompt(
        role,
        family,
        session,
        definitions,
        set(names),
        set(reg.specs),
        loaded,
        settings or Settings(),
        SCHEMAS[OUTPUTS[role]],
        prompt_mode_override=mode,
    )


def _learner_block(count: int) -> Any:
    """Tier 6 as the engine renders it: `count` notes cut to the smallest class's allowance in the fixed order."""
    from agent_core.memory.queries import NoteRecord, ProfileSummary
    from agent_core.memory.render import allowance, fit_block
    from agent_core.memory.snapshot import FrozenMemory

    notes = tuple(NoteRecord(f"01J9ZZNOTE{n:016d}", "Sets the positive direction first and checks units at the end",
                             "active", "physics", (), 1_760_000_000_000 - n, "reflector", "")
                  for n in range(count))  # fmt: skip
    frozen = FrozenMemory("2026-10-09", ProfileSummary("O", ("physics",), "in 90 days", None, "standard",
                                                       "after_attempt"), (), (), (), notes[:2], notes[2:])  # fmt: skip
    settings = Settings()
    return fit_block(frozen, variant="local", allowance_chars=allowance(settings, "minimal", "low"), settings=settings)


def maximal() -> PromptSession:
    """A maximal fixture: every tier filled past its budget, so the overflow rules must hold it within budget."""
    passages = tuple(
        Passage(f"phy.o.p{n}", "A ball thrown upwards slows down by about 9.8 m/s every second. " * 20, n)
        for n in range(1, 30)
    )
    block = _learner_block(40)
    transcript = tuple(Message("user" if n % 2 == 0 else "assistant", f"message {n}") for n in range(20))
    return PromptSession(
        passages=passages,
        learner_block=block.text,
        learner_dropped=block.dropped,
        transcript=transcript,
        task="Solve the problem.",
        tutor_context="mode: guided\nstep: 1 of 2\nhint rung: 0",
        session_date="2026-10-09",
        glossary=("s: displacement in m",),
        session_tools=frozenset(registry().specs),
    )


# --- PRM-09 ---------------------------------------------------------------------------------------------------------


def prm09_tier_budgets():
    settings = Settings()
    tables = {
        "full": settings.prompt_budget_full,
        "compact": settings.prompt_budget_compact,
        "minimal": settings.prompt_budget_minimal,
    }
    for role in OUTPUTS:
        for mode in ("full", "compact", "minimal"):
            built = build(role, maximal(), mode=mode)
            for tier in built.tiers[:8]:
                assert len(tier.text) <= tables[mode][tier.index - 1], (role, mode, tier.name, len(tier.text))


def prm09_tier_order():
    built = build("coach", maximal(), mode="full")
    assert [t.name for t in built.tiers] == list(TIER_NAMES)
    system = built.messages[0].content
    positions = [system.find(t.text[:40]) for t in built.tiers[:7] if t.text]
    assert positions == sorted(positions) and -1 not in positions
    last_student = [m for m in built.messages if m.role == "user"][-1]
    assert "<tutor-context>\n" in last_student.content and "<tutor-context>\n" not in system


# --- PRM-10, PRM-11 -------------------------------------------------------------------------------------------------


def prm10_deterministic():
    first, second = build("coach", maximal()), build("coach", maximal())
    assert [m.content for m in first.messages] == [m.content for m in second.messages]
    assert first.fingerprints() == second.fingerprints() and first.tools == second.tools


def prm10_dropped_reported():
    built = build("coach", maximal(), mode="minimal")
    reasons = {d["item"]: d["reason"] for d in built.dropped}
    assert reasons["guidance:solver-tool-discipline"] == "not for role coach"
    assert reasons["guidance:hint-rung-discipline"] in ("not essential (minimal prompt mode)", "over the tier budget")
    gemma = build("solver", maximal(), family="gemma3")
    assert (
        any(d["item"] == "guidance:solver-tool-discipline" for d in gemma.dropped)
        or "Batch independent" in gemma.messages[0].content
    )


def prm11_overflow_order():
    from agent_core.assets.skills import SkillSet

    skill = SkillSet.load(REPO_ROOT / "skills", DEV_SKILL_STATUSES).skills["pedagogy-guided-solve"]
    session = PromptSession(
        teaching_skill=skill, passages=maximal().passages, session_tools=frozenset(registry().specs)
    )
    built = build("coach", session, mode="compact")
    topic = built.tiers[4].text
    assert "pedagogy-guided-solve" in topic and 'id="phy.o.p1"' in topic  # the skill and the top passage stay
    cut = [d["item"] for d in built.dropped if d["tier"] == "5"]
    assert cut and all(c.startswith("passage:") for c in cut) and "passage:phy.o.p1" not in cut


# --- PRM-12, PRM-13 -------------------------------------------------------------------------------------------------


def prm12_stable_prefix():
    one = build("coach", PromptSession(transcript=(Message("user", "first"),), tutor_context="rung 0"))
    two = build(
        "coach",
        PromptSession(
            transcript=(Message("user", "first"), Message("assistant", "q?"), Message("user", "second")),
            tutor_context="rung 1",
        ),
    )
    end = two.cache_breakpoints[1]
    assert one.messages[0].content[:end] == two.messages[0].content[:end]
    assert "<tutor-context>" not in two.messages[1].content  # stripped once it is not the last student message


def prm12_no_clock_above_turn():
    sources = sorted((REPO_ROOT / "services/agent-core/agent_core/prompts").glob("*.py"))
    for path in sources:
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in ("now", "today", "time", "monotonic", "utcnow"):
                pytest.fail(f"{path.name}:{node.lineno} reads a clock")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] + ([node.module] if isinstance(node, ast.ImportFrom) else [])
                assert not {"time", "datetime", "random", "uuid", "secrets"} & set(names), path.name


def prm13_fingerprints_recorded():
    built = build("coach", PromptSession(transcript=(Message("user", "hello"),)))
    fingerprints = built.fingerprints()
    assert len(fingerprints["tiers"]) == 9 and all(len(t["sha256"]) == 64 for t in fingerprints["tiers"])
    empty = [t for t in fingerprints["tiers"] if t["bytes"] == 0]
    assert empty and all(
        t["sha256"] == "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855" for t in empty
    )
    assert len(fingerprints["tools_sha256"]) == 64
    assert "hello" not in json.dumps(fingerprints)  # no student text


def prm13_fingerprint_locality(tmp_path: Path):
    content = tmp_path / "agent"
    shutil.copytree(CONTENT, content)
    block = content / "guidance" / "one-question-per-turn.md"
    session = PromptSession(transcript=(Message("user", "hi"),))
    before = build("coach", session, assets(content)).fingerprints()
    block.write_text(block.read_text().replace("Ask exactly one question", "Ask just one question"))
    after = build("coach", session, assets(content)).fingerprints()
    changed = [b["name"] for b, a in zip(before["tiers"], after["tiers"], strict=True) if b["sha256"] != a["sha256"]]
    assert changed == ["guidance"]


# --- PRM-14 ---------------------------------------------------------------------------------------------------------


def prm14_minimal_for_delegates():
    for hardware in ("low", "mid", "high", "cloud"):
        built = build(
            "solver",
            PromptSession(
                hardware_class=hardware, task="solve it", learner_block="About this student: prefers diagrams"
            ),
        )
        assert built.prompt_mode == "minimal" and built.tiers[5].text == ""  # no learner snapshot
        assert [m.role for m in built.messages] == ["system", "user"]  # no transcript, only the task


# --- PRM-22, EVL-09 -------------------------------------------------------------------------------------------------


def prm22_snapshot_diff_fails(tmp_path: Path):
    assert snapshots.diff_errors() == []
    content = tmp_path / "agent"
    shutil.copytree(CONTENT, content)
    coach = content / "roles" / "coach.md"
    coach.write_text(coach.read_text().replace("Make one teaching move", "Make one short teaching move"))
    built = _build_all_with(content)
    errors = snapshots.diff_errors(built=built)
    assert errors and all(e.startswith("coach/") for e in errors)


def _build_all_with(content: Path):
    """The snapshot matrix built from a modified copy of the prompt files."""
    import agent_core.assets.agent as agent_module

    original = agent_module.AgentAssets.load

    def load(root, skills_root, statuses=DEV_SKILL_STATUSES):
        return original(content, skills_root, statuses)

    agent_module.AgentAssets.load = staticmethod(load)  # type: ignore[method-assign]
    try:
        return snapshots.build_all()
    finally:
        agent_module.AgentAssets.load = original  # type: ignore[method-assign]


def evl09_snapshot_change_requires_review(tmp_path: Path):
    root = tmp_path / "snapshots"
    root.mkdir()
    assert snapshots.write(root) == 60
    pending = snapshots.review_errors(root)
    assert len(pending) == 60  # nothing is approved until a reviewer records it
    snapshots.approve("rev_engine_reviewer", root)
    assert snapshots.review_errors(root) == []
    content = tmp_path / "agent"
    shutil.copytree(CONTENT, content)
    block = content / "guidance" / "hint-rung-discipline.md"
    block.write_text(block.read_text().replace("never go above it", "never go beyond it"))
    built = _build_all_with(content)
    for name, (text, _) in built.items():
        (root / name).write_text(text)
    index = {
        name: {"sha256": __import__("hashlib").sha256(text.encode()).hexdigest(), "tiers": tiers}
        for name, (text, tiers) in built.items()
    }
    (root / "index.json").write_text(json.dumps(index))
    blocked = snapshots.review_errors(root)
    assert blocked and all(e.split("/")[0] == "coach" for e in blocked)  # only the affected snapshots, until approved
