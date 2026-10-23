"""M14.g: the soul and identity with their governance, soul exposure by role, guidance blocks and family overlays, the
per-turn tutor-context block, one-shot reminders, capability notices, writing techniques, prompt change control, and
tone and reading level (PRM-01 to PRM-04, PRM-07, PRM-08, PRM-15 to PRM-17, PRM-21, PRM-23, PED-20, PED-21, LOC-22).

Engine replies are scripted; the student lines, items and fixtures are synthetic."""

from __future__ import annotations

import ast
import asyncio
import json
import re
import shutil
from pathlib import Path
from typing import Any

import pytest
from agent_core.assets.agent import SOUL_SECTIONS, AssetError, soul_problems
from agent_core.assets.skills import SkillSet
from agent_core.config import Settings
from agent_core.engine.assembly import DEV_SKILL_STATUSES
from agent_core.prompts.builder import Message, PromptError, PromptSession, build_prompt
from agent_core.prompts.reminders import REMINDER_KEYS, NoticeText, ReminderLedger, capability_notices
from agent_core.tools.specs import registry
from engine_harness import STATEMENT, checker_steps, close, solver_steps, tutor
from jana_tools import REPO_ROOT
from m14_harness import engine_for
from test_m4e_prompts import CONTENT, assets, build

LOOP = asyncio.new_event_loop()
CORE = REPO_ROOT / "services" / "agent-core" / "agent_core"
SAFE = "Which quantities does the question give you, and which one does it ask for?"
EXPOSURE = {"coach": "full", "diagnoser": "values", "solver": "values", "checker": "values",
            "reflector": "values_boundaries"}  # fmt: skip


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _copy(tmp_path: Path) -> Path:
    content = tmp_path / "agent"
    shutil.copytree(CONTENT, content)
    return content


# --- PRM-01, PRM-02, PRM-03 -----------------------------------------------------------------------------------------


def prm01_soul_shape() -> None:
    soul = assets().soul
    assert len(soul.text) <= 2000
    assert tuple(soul.sections) == SOUL_SECTIONS == ("Values", "Voice", "Teaching stance", "Boundaries")
    assert soul_problems(soul, set(registry().specs)) == []
    assert "Jana" in soul.exposure("full"), "the tutor's name enters through the placeholder"
    # The checks bite: a tool name, a fifth section or an overlong soul is refused.
    named = soul_problems(type(soul)(soul.sections, soul.text + "\nUse math_solve for sums.", soul.sha256),
                          set(registry().specs))  # fmt: skip
    assert named and "math_solve" in named[0]


def prm02_placeholder_refusal(tmp_path: Path) -> None:
    content = _copy(tmp_path)
    soul = content / "soul" / "SOUL.md"
    soul.write_text(soul.read_text().replace("the student's tutor.", "the tutor of {{SCHOOL_NAME}}."))
    loaded = assets(content)
    with pytest.raises(PromptError, match="unfilled_placeholder"):
        build("coach", PromptSession(), loaded)
    # A placeholder only the identity file may fill: an identity without tutor_name is refused at load.
    (content / "soul" / "IDENTITY.yaml").write_text("avatar_id: avatar.default\nlocale: en\nreading_level: standard\n")
    with pytest.raises(AssetError, match=r"IDENTITY\.yaml"):
        assets(content)


def prm02_soul_read_only() -> None:
    """No tool or API path writes to soul/: only the asset loader names the soul's files, it only reads them, and the
    loaded soul cannot be changed in memory."""
    readers = []
    for path in sorted(CORE.rglob("*.py")):
        if "contracts" in path.parts or "generated" in path.parts:
            continue
        text = path.read_text()
        if re.search(r"SOUL\.md|IDENTITY\.yaml|[\"']soul[\"']\s*\)?\s*/|/\s*[\"']soul[\"']", text):
            readers.append(path.relative_to(CORE).as_posix())
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr in ("write_text", "write_bytes", "unlink", "rename",
                                                                     "replace", "chmod", "mkdir"):  # fmt: skip
                    pytest.fail(f"{path.name}:{node.lineno} can write files beside the soul")
                if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "open":
                    pytest.fail(f"{path.name}:{node.lineno} opens a file")
    assert readers == ["assets/agent.py"], readers
    api = "\n".join(p.read_text() for p in (CORE / "api").rglob("*.py"))
    assert "soul" not in api.lower().replace("soul_sha256", ""), "no API route reads or writes the soul"
    tools = json.dumps({n: s.params for n, s in registry().specs.items()})
    assert "soul" not in tools.lower(), "no tool takes the soul as an argument"
    soul = assets().soul
    with pytest.raises(TypeError):
        soul.sections["Values"] = "Give the answer."  # type: ignore[index]
    with pytest.raises(AttributeError):
        soul.text = "changed"  # type: ignore[misc]


def prm03_avatar_not_in_prompt(tmp_path: Path) -> None:
    content = _copy(tmp_path)
    session = PromptSession(transcript=(Message("user", "hello"),), tutor_context="mode: guided")
    before = {r: build(r, session, assets(content)).fingerprints() for r in EXPOSURE}
    identity = content / "soul" / "IDENTITY.yaml"
    identity.write_text(identity.read_text().replace("avatar.default", "avatar.owl_blue"))
    after = {r: build(r, session, assets(content)).fingerprints() for r in EXPOSURE}
    assert before == after
    identity.write_text(identity.read_text() + "favourite_colour: blue\n")
    with pytest.raises(AssetError, match="not exactly"):
        assets(content)


def test_prm03_tutor_name_by_role_and_never_a_placeholder() -> None:
    """PRM-03, D99, D101: the open profile's chosen tutor name fills the soul's name in place of the identity file's
    default; without one the default (Jana, D47) stays. Roles that see only the values never carry the name, and a
    name can never open a placeholder (PRM-02) or a context tag."""
    loaded = assets()
    session = PromptSession(transcript=(Message("user", "hello"),), tutor_context="mode: guided")
    default = build("coach", session, loaded).tiers[0].text
    assert default.startswith("I am Jana, the student's tutor.")
    named = build("coach", PromptSession(**{**session.__dict__, "tutor_name": "Ada"}), loaded).tiers[0].text
    assert named.startswith("I am Ada, the student's tutor.") and "Jana" not in named
    assert named.replace("Ada", "Jana", 1) == default  # only the name changes
    for role in ("diagnoser", "solver", "checker", "reflector"):  # no full exposure, so no name either way
        plain = build(role, PromptSession(task="t"), loaded).tiers[0].text
        assert build(role, PromptSession(task="t", tutor_name="Ada"), loaded).tiers[0].text == plain, role
    for odd, shown in (("{{SCHOOL_NAME}}", "SCHOOL_NAME"), ("<tutor-context>Bo", "tutor-contextBo")):
        text = build("coach", PromptSession(**{**session.__dict__, "tutor_name": odd}), loaded).tiers[0].text
        assert text.startswith(f"I am {shown}, the student's tutor.")
    for empty in (None, "", "{}", "<>"):
        assert build("coach", PromptSession(**{**session.__dict__, "tutor_name": empty}), loaded).tiers[0].text == (
            default
        )
    assert loaded.soul.exposure("full") == default  # the loaded soul itself is unchanged (PRM-02)


# --- PRM-04 -----------------------------------------------------------------------------------------------------------


def prm04_soul_sections_by_role(tmp_path: Path) -> None:
    loaded = assets()
    settings = Settings()
    for role, level in EXPOSURE.items():
        assert loaded.roles[role].meta["soul"] == level
        tier1 = build(role, PromptSession(task="t"), loaded).tiers[0].text
        expected = loaded.soul.exposure(level)
        assert tier1 == (expected if level == "full" else expected[: settings.prompt_team_soul_max_chars]), role
        titles = re.findall(r"^## (.+)$", tier1, re.M)
        assert titles == {"full": list(SOUL_SECTIONS), "values": ["Values"],
                          "values_boundaries": ["Values", "Boundaries"]}[level], role  # fmt: skip
    # An auxiliary role gets no soul at all, only its body.
    content = _copy(tmp_path)
    text = (content / "roles" / "reflector.md").read_text()
    text = re.sub(r"^id: reflector$", "id: title", text, flags=re.M)
    text = re.sub(r"^kind: specialist$", "kind: auxiliary", text, flags=re.M)
    text = re.sub(r"^soul: \S+$", "soul: none", text, flags=re.M)
    (content / "roles" / "title.md").write_text(text)
    aux = assets(content)
    built = build_prompt("title", "qwen3", PromptSession(task="Name this session."), [], set(), set(registry().specs),
                         aux, settings)  # fmt: skip
    assert built.tiers[0].text == "" and built.tiers[1].text.startswith("## Role")


# --- PRM-07, PRM-08 ---------------------------------------------------------------------------------------------------


def _skill_with_line(tmp_path: Path, line: str) -> Any:
    root = tmp_path / "skills"
    shutil.copytree(REPO_ROOT / "skills", root)
    path = root / "teaching" / "phy" / "phy-o-motion" / "SKILL.md"
    text = path.read_text()
    for section in ("## Teaching sequence\n", "## Hint ladder\n", "## Verification checklist\n"):
        text = text.replace(section, f"{section}{line}\n", 1)
    path.write_text(text)
    return SkillSet.load(root, DEV_SKILL_STATUSES).skills["phy-o-motion"]


def prm07_tool_lines_dropped(tmp_path: Path) -> None:
    """The Solver may call `math_check_equivalence`; with it hidden this turn (worker circuit open), no line of tiers
    2 to 5 names it, the pushed skill's lines included, and each dropped line is reported."""
    from agent_core.tools.catalogue import role_tools
    from agent_core.tools.generated.register import REGISTER
    from agent_core.tools.spec import InitCtx
    from test_m4e_prompts import OUTPUTS, SCHEMAS

    skill = _skill_with_line(tmp_path, "Confirm the rearranged form with `math_check_equivalence` first.")
    loaded = assets()
    reg = registry()
    for role in ("solver", "coach"):
        names = [n for n in role_tools(role, loaded.roles[role].tools, reg, REGISTER["roleGrants"])
                 if n != "math_check_equivalence"]  # fmt: skip
        definitions = [reg.specs[n].model_definition(InitCtx()) for n in names]
        session = PromptSession(teaching_skill=skill, task="Solve it.", tutor_context="mode: guided",
                                transcript=(Message("user", "hi"),))  # fmt: skip
        built = build_prompt(role, "qwen3", session, definitions, set(names), set(reg.specs), loaded, Settings(),
                             SCHEMAS[OUTPUTS[role]], prompt_mode_override="full")  # fmt: skip
        for tier in built.tiers[1:5]:
            assert "math_check_equivalence" not in tier.text, (role, tier.name)
        reasons = [d for d in built.dropped if d["reason"] == "names unavailable tool math_check_equivalence"]
        assert any(d["item"] == "skill:phy-o-motion" for d in reasons), role


def prm07_family_filter(tmp_path: Path) -> None:
    content = _copy(tmp_path)
    (content / "guidance" / "qwen-only-note.md").write_text(
        '---\nid: qwen-only-note\nversion: "0.1"\nkind: technique\napplies_to: [coach]\nmodels: [qwen3]\n'
        "priority: 95\nmax_chars: 200\nowner: Engine lead\nstatus: draft\n---\nQZVQWEN keep replies in the JSON.\n"
    )
    loaded = assets(content)
    qwen = build("coach", PromptSession(), loaded, family="qwen3", mode="full")
    gemma = build("coach", PromptSession(), loaded, family="gemma4", mode="full")
    assert "QZVQWEN" in qwen.tiers[2].text and "QZVQWEN" not in gemma.messages[0].content
    assert {"tier": "3", "item": "guidance:qwen-only-note", "reason": "not for model family gemma4"} in gemma.dropped


def prm08_overlay_only_difference(tmp_path: Path) -> None:
    session = PromptSession(transcript=(Message("user", "hello"),), tutor_context="mode: guided")
    for mode in ("full", "compact", "minimal"):
        qwen, gemma = build("coach", session, family="qwen3", mode=mode), build("coach", session, family="gemma4",
                                                                                mode=mode)  # fmt: skip
        differ = [a.name for a, b in zip(qwen.tiers, gemma.tiers, strict=True) if a.sha256 != b.sha256]
        assert differ == ["guidance"], (mode, differ)
    # One body per role: an overlay is a small family_overlay block, never a forked prompt.
    content = _copy(tmp_path)
    overlay = content / "families" / "gemma.md"
    overlay.write_text(overlay.read_text().replace("kind: family_overlay", "kind: technique"))
    with pytest.raises(AssetError, match="family overlay"):
        assets(content)
    assert sorted(p.stem for p in (CONTENT / "roles").glob("*.md")) == sorted(assets().roles)


# --- PRM-15, PRM-16, PRM-17 -------------------------------------------------------------------------------------------


def _user_texts(request: dict[str, Any]) -> list[str]:
    return [str(m["content"]) for m in request["messages"] if m["role"] == "user"]


def prm15_block_not_persisted(tmp_path: Path) -> None:
    script = {"solver": solver_steps(), "checker": checker_steps(),
              "coach": [tutor(SAFE), tutor("Good. Which equation links them?"), tutor(SAFE)]}  # fmt: skip
    engine, provider = run(engine_for(tmp_path, script))
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("u = 14 m/s and v = 0 at the top"))
    run(engine.student_turn("I'm stuck"))
    run(close(engine))
    coach = [r for r in provider.requests if "<tutor-context>" in json.dumps(r)]
    assert coach, "the Coach was given the block"
    for request in coach:  # only on the last student message of each request
        users = _user_texts(request)
        last = max(i for i, m in enumerate(request["messages"]) if m["role"] == "user" and "<student-message>" in
                   str(m["content"]))  # fmt: skip
        assert all(
            "<tutor-context>\n" not in str(m["content"])
            for i, m in enumerate(request["messages"])
            if i != last and m["role"] != "system"
        ), "the role body names the block; no other message holds one"
        assert sum("<tutor-context>\n" in u for u in users) == 1
    stored = json.dumps(engine.state.transcript) + json.dumps(engine.persisted, default=str)
    assert "<tutor-context>" not in stored and "tutor-context" not in json.dumps(engine.state.transcript)


def prm15_no_withheld_values(tmp_path: Path) -> None:
    from agent_core.engine.prompt_inputs import misconception_lines, without_withheld
    from agent_core.engine.state import numbers_in

    engine, _ = run(engine_for(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                           "coach": [tutor(SAFE), tutor(SAFE)]}))  # fmt: skip
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("I don't know"))
    block = engine._tutor_context("hint at rung 1")
    withheld = {v for v, _ in engine.state.withheld()}
    assert withheld == {numbers_in("10")[0]}
    assert not set(numbers_in(block)) & withheld and "10" not in block.split()
    # A matched misconception whose authored fix would carry the key is left out of the block.
    state = engine.state
    item = {"id": "itm.test", "kc_ids": [], "parts": [{"id": "a", "answer": {"kind": "mcq", "options": [
        {"id": "A", "text": "10 m", "correct": True},
        {"id": "B", "text": "20 m", "correct": False, "misconception_id": "mc.phy.o.test_wrong_idea",
         "feedback": "Halve it: the height is 10 m."}]}}]}  # fmt: skip
    state.practice = {
        "item": item,
        "part": "a",
        "verdicts": ["incorrect"],
        "misconception_id": "mc.phy.o.test_wrong_idea",
    }
    state.student_lines.append("B")
    lines = misconception_lines(state)
    assert any("mc.phy.o.test_wrong_idea" in ln for ln in lines) and any("option B" in ln for ln in lines)
    kept = without_withheld(lines, state, engine.deps.settings)
    assert all("10" not in ln for ln in kept) and any("option B" in ln for ln in kept)
    run(close(engine))


def prm16_reminder_dedupe(tmp_path: Path) -> None:
    text = NoticeText.load(CONTENT / "notices" / "capability.en.yaml")
    assert set(text.reminders) == set(REMINDER_KEYS)
    ledger = ReminderLedger(text, Settings().reminder_max_chars)
    assert ledger.offer("checker.first_wrong_step", "3", 1) is not None
    assert ledger.offer("checker.first_wrong_step", "3", 2) is None, "the same key and value is sent once"
    assert ledger.offer("checker.first_wrong_step", "4", 3) is not None, "a changed value is sent once more"
    assert ledger.offer("checker.first_wrong_step", "4", 4) is None
    assert ledger.offer("mode.changed", "guided", 1) is None, "the opening mode is the baseline, not news"
    assert ledger.offer("mode.changed", "practice", 5).text == "The mode is now practice."
    assert all(len(r.text) <= Settings().reminder_max_chars for r in ledger.sent)
    # In the engine: the rung change is sent once, stays where it was sent, and is never sent twice.
    script = {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)] * 4}
    engine, provider = run(engine_for(tmp_path, script))
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("v = 0 at the top"))  # an attempt, so a hint request is answered with a hint
    run(engine.student_turn("I'm stuck"))  # rung 0 -> 1
    run(engine.student_turn("ok, what next?"))
    run(close(engine))
    requests = [r for r in provider.requests if "<tutor-context>" in json.dumps(r)]
    counts = [sum("The hint rung is now 1." in u for u in _user_texts(r)) for r in requests]
    assert counts[-2:] == [1, 1] and max(counts) == 1, counts
    nonce = engine.app_events.nonce
    assert all(f'<app-event nonce="{nonce}">' in u for r in requests for u in _user_texts(r) if "hint rung is now" in u)


def test_prm17_capability_notices(tmp_path: Path) -> None:
    """PRM-17: what is off is said per turn in the block, never in tiers 1 to 7."""
    text = NoticeText.load(CONTENT / "notices" / "capability.en.yaml")
    assert capability_notices(text, checks=True, visuals=True, cloud=None) == []
    off = capability_notices(text, checks=False, visuals=False, cloud=False, vision=False, memory_saving=False)
    assert len(off) == 5 and "Saving notes is off: do not say you will remember anything." in off
    engine, _ = run(engine_for(tmp_path, {"solver": [], "checker": [], "coach": [tutor(SAFE)]},
                                       worker=False))  # fmt: skip
    block = engine._tutor_context("opening")
    assert text.notices["checks_off"] in block and text.notices["visuals_off"] in block
    system = build("coach", PromptSession()).messages[0].content
    assert text.notices["checks_off"] not in system
    run(close(engine))


# --- PRM-21 -----------------------------------------------------------------------------------------------------------


def test_prm21_writing_techniques_linted(tmp_path: Path) -> None:
    from agent_core.prompts.lint import technique_findings

    assert technique_findings(assets()) == []
    content = _copy(tmp_path)
    solver = content / "roles" / "solver.md"
    solver.write_text(solver.read_text().replace("Never work out arithmetic or algebra\nyourself; use the checked "
                                                 "values or a tool.", "IMPORTANT: be careful."))  # fmt: skip
    found = technique_findings(assets(content))
    assert {f.split(":")[0] for f in found} == {"solver"}
    assert any("technique 1" in f for f in found) and any("technique 11" in f for f in found)


# --- PRM-23 -----------------------------------------------------------------------------------------------------------


def prm23_eval_required(tmp_path: Path) -> None:
    from jana_tools.release.prompts import current_files, record_run, release_errors

    content = _copy(tmp_path)
    runs = tmp_path / "prompt-runs.jsonl"
    assert release_errors(content, runs), "no eval run record at all: refused"
    record_run(content, {"scenarios": "passed", "safety": "passed", "simulated_students": "passed"}, runs,
               run_id="run1", date="2026-10-13")  # fmt: skip
    assert release_errors(content, runs) == []
    block = content / "guidance" / "one-question-per-turn.md"
    block.write_text(block.read_text().replace("Ask exactly one question", "Ask one question"))
    errors = release_errors(content, runs)
    assert errors and any("one-question-per-turn.md" in e for e in errors)
    assert any("version" in e for e in errors), "a changed file without a version bump is named too"
    block.write_text(block.read_text().replace('version: "0.1"', 'version: "0.2"'))
    record_run(content, {"scenarios": "passed", "safety": "failed", "simulated_students": "passed"}, runs,
               run_id="run2", date="2026-10-13")  # fmt: skip
    assert release_errors(content, runs), "a run whose gates did not hold does not clear the change"
    record_run(content, {"scenarios": "passed", "safety": "passed", "simulated_students": "passed"}, runs,
               run_id="run3", date="2026-10-13")  # fmt: skip
    assert release_errors(content, runs) == []
    assert set(current_files(content)) >= {"soul/SOUL.md", "roles/coach.md", "families/gemma.md"}


# --- PED-20, PED-21, LOC-22 -------------------------------------------------------------------------------------------


def _corpus() -> list[dict[str, Any]]:
    """Tutor turns of the committed dialogue corpora: the simulated-student runs and the skill-eval runs."""
    from jana_tools.harness.simulator import corpus

    return corpus()


def ped20_banned_lexicon() -> None:
    from agent_core.engine.pedagogy import apply_lexicon
    from agent_core.engine.tone import banned_phrases

    for phrase in ("Great question!", "That's incorrect.", "This is easy.", "Obviously it is", "You're so smart",
                   "that is wrong", "Just do the sum"):  # fmt: skip
        assert banned_phrases(phrase), phrase
        assert banned_phrases(apply_lexicon(phrase)[0]) == [], phrase
    turns = _corpus()
    if not turns:
        pytest.skip("no dialogue corpus has been recorded (run eval simulate or eval skills on a local model)")
    hits = [(t["source"], banned_phrases(t["tutor"])) for t in turns if banned_phrases(t["tutor"])]
    assert hits == [], hits[:5]


def ped21_word_caps() -> None:
    from agent_core.engine.pedagogy import word_count
    from agent_core.engine.tone import cap_words, word_cap

    settings = Settings()
    assert (word_cap(settings, "O"), word_cap(settings, "A"), word_cap(settings, "O", "support")) == (60, 90, 40)
    long = " ".join(["The speed changes because the force acts for a while."] * 8) + " What does the force do?"
    capped = cap_words(long, 40)
    assert word_count(capped) <= 40 and capped.endswith("What does the force do?")
    turns = _corpus()
    if not turns:
        pytest.skip("no dialogue corpus has been recorded (run eval simulate or eval skills on a local model)")
    over = [t for t in turns if word_count(t["tutor"]) > word_cap(settings, t.get("level", "O"))]
    assert over == [], [(t["source"], word_count(t["tutor"])) for t in over[:5]]


def loc22_readability_lint() -> None:
    from jana_tools.readability import lint_errors, measure

    plain = measure("The ball goes up. It slows down. At the top it stops for a moment.")
    assert plain.sentence_words < 8 and plain.grade < 4
    dense = measure("Notwithstanding considerable experimental uncertainty, investigators consistently "
                    "demonstrated extraordinarily sophisticated relationships characterising electromagnetic "
                    "phenomena, unequivocally substantiating theoretical predictions.")  # fmt: skip
    assert dense.grade > 10
    assert lint_errors() == []
