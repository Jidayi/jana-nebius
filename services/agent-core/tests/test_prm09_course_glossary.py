"""The course glossary in tier 5 and the reply check against it (PRM-09: "notation glossary that overrides the model's
own definitions"; AGT-10), and the withheld tool-answer path that never names a tool or doubts its explanation (PED-10
H1/H2, TABLE PED-16a `tool_disagreement_honest`).

Found by the 2026-10-21 hint re-run: concrete hints stated the local model's own facts ("independent events" for
draws without replacement, AVCO as "Average Cost Value"), and one opening turn read "The tool suggests the formula
V = IR might be useful, though it may contain an error". Every question, student line and reply here is synthetic."""

from __future__ import annotations

import asyncio
import json
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml
from agent_core.assets.glossary import Glossary, contradictions, lines
from agent_core.engine.pedagogy import remove_internals
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from test_m25b_numbers_and_answers import _disagreement_script, rule_action, settings, visible_numbers

LOOP = asyncio.new_event_loop()  # the sandboxed workers belong to the loop that started them
GLOSSARY = REPO_ROOT / "content" / "agent" / "glossary" / "en.yaml"
CURRICULUM = REPO_ROOT / "content" / "curriculum"
DRAWS = "Two counters are taken out, one after the other, without replacement."
SAFE = "Which quantities does the question give you, and which one does it ask for?"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def pack_glossaries() -> dict[str, list[str]]:
    """Every pack KC's glossary terms, read from the curriculum sources the packs are built from."""
    out: dict[str, list[str]] = {}
    for path in CURRICULUM.glob("*/*/kcs/*.yaml"):
        for kc in yaml.safe_load(path.read_text()) or []:
            out[kc["id"]] = [str(t).lower() for t in kc.get("glossary") or []]
    return out


def test_prm09_glossary_terms_from_the_packs() -> None:
    """Each definition names KCs that exist, and its term or an alias is in each of those KCs' pack glossary, so the
    glossary defines the packs' own terms; the definitions carry no digits (a number the Coach repeats must trace)."""
    glossary = Glossary.load(GLOSSARY)
    packs = pack_glossaries()
    assert len(glossary.entries) >= 6
    for entry in glossary.entries:
        names = {entry.term.lower(), *(a.lower() for a in entry.aliases)}
        for kc in entry.kcs:
            assert kc in packs, f"{entry.term}: unknown KC {kc}"
            assert names & set(packs[kc]), f"{entry.term}: not in the glossary of {kc}"
        assert not any(c.isdigit() for c in entry.definition), entry.term
    terms = {e.term for e in glossary.entries}
    assert {"AVCO", "dependent event", "independent event"} <= terms  # the bench errors (2026-10-21)


def test_prm09_glossary_in_play_and_contradictions() -> None:
    glossary = Glossary.load(GLOSSARY)
    draws = glossary.in_play([], f"A bag holds red and blue counters. {DRAWS}")
    assert [e.term for e in draws] == ["dependent event"], "a cue in the question brings the entry in"
    statement = f"A bag holds red and blue counters. {DRAWS}"
    found = contradictions(["This is a problem about independent events happening one after the other."], draws,
                           statement)  # fmt: skip
    assert found and "without replacement is dependent" in found[0]
    assert not contradictions(["These events are not independent: the second pick changes."], draws, statement)
    # Without the cue the dependent entry's wrong phrase is not checked: independent spins are independent.
    spins = glossary.in_play(["kc.mth.o.probability.dependent_events", "kc.mth.o.probability.independent_events"],
                             "Two spinners are spun. Find the probability that both show a six.")  # fmt: skip
    assert not contradictions(["These are independent events."], spins, "Two spinners are spun.")

    avco = glossary.in_play(["kc.acc.o.inventory.avco"], "Using AVCO, value the closing inventory.")
    assert "Weighted average cost (AVCO)" in "\n".join(lines(avco))
    wrong = contradictions(["In accounting, AVCO stands for Average Cost Value."], avco, "Using AVCO, value it.")
    assert wrong and wrong[0].startswith('"Average Cost Value"')
    assert not contradictions(["AVCO means weighted average cost."], avco, "Using AVCO, value it.")


def test_prm09_glossary_in_play_ranks_the_question_terms_first(tmp_path: Path) -> None:
    """A topic holds more terms than tier 5 takes: the terms the question names come first, then those with a known
    wrong phrase, then file order, so a full glossary never pushes the question's own terms out."""
    kc = "kc.acc.o.inventory.avco"
    filler = [{"term": f"term {chr(97 + i)}", "definition": f"Term {chr(97 + i)}: synthetic.", "kcs": [kc]}
              for i in range(10)]  # fmt: skip
    flagged = {"term": "flagged", "definition": "Flagged: synthetic.", "kcs": [kc], "wrong": ["flagged wrongly"]}
    named = {"term": "closing inventory", "aliases": ["closing stock"], "definition": "Closing inventory: synthetic.",
             "kcs": [kc]}  # fmt: skip
    path = tmp_path / "en.yaml"
    path.write_text(yaml.safe_dump({"terms": [*filler, flagged, named]}))
    found = [e.term for e in Glossary.load(path).in_play([kc], "Find the value of the closing stock.")]
    assert found[:3] == ["closing inventory", "flagged", "term a"] and len(found) == 8


def test_prm09_glossary_cut_before_the_pushed_skills() -> None:
    """A full tier 5 cuts the course definitions beyond the first (the least relevant, ranked last, first) before the
    pushed pedagogy or teaching skill (PRM-11: like the passages beyond the top-ranked one); the reply check still
    covers every entry in play."""
    from agent_core.assets.skills import SkillSet
    from agent_core.prompts.builder import PromptSession
    from agent_core.tools.specs import registry
    from test_m4e_prompts import DEV_SKILL_STATUSES, build

    skills = SkillSet.load(REPO_ROOT / "skills", DEV_SKILL_STATUSES).skills
    definitions = tuple(f"- Term {chr(97 + i)}: " + "a synthetic definition of course words. " * 5 for i in range(8))
    session = PromptSession(teaching_skill=skills["phy-o-motion"], pedagogy_skill=skills["pedagogy-guided-solve"],
                            glossary=definitions, session_tools=frozenset(registry().specs))  # fmt: skip
    built = build("coach", session)
    topic = built.tiers[4].text
    cut = [d["item"] for d in built.dropped if d["tier"] == "5"]
    assert cut and all(c.startswith("glossary:") for c in cut) and cut[0] == "glossary:Term h"
    assert "glossary:Term a" not in cut and "- Term a:" in topic and "pedagogy-guided-solve" in topic


def test_prm09_glossary_reaches_the_coach_and_a_wrong_term_is_sent_back(tmp_path: Path) -> None:
    """The definitions in play reach the Coach's tier 5 (never the Solver's), and a reply naming a term the course
    defines otherwise is sent back with the definition before the student sees it."""
    statement = f"{STATEMENT} {DRAWS}"
    wrong = tutor("This is a problem about independent events. " + SAFE)
    engine, provider = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(),
                                                  "coach": [wrong, tutor(SAFE)]}))  # fmt: skip
    try:
        result = run(engine.start_problem(statement))
    finally:
        run(close(engine))
    text = engine.events.student_text(result.turn_id)
    assert "independent" not in text.lower() and text.endswith(SAFE)
    coach = [json.dumps(q["messages"]) for q in provider.requests if q.get("_role") == "coach"]
    solver = [json.dumps(q["messages"]) for q in provider.requests if q.get("_role") == "solver"]
    assert len(coach) == 2 and all("Drawing without replacement is dependent" in c for c in coach)
    assert solver and not any("Drawing without replacement is dependent" in s for s in solver)
    assert "names a term wrongly" in coach[1] and "names a term wrongly" not in coach[0]


def test_ped10_internals_taken_out_of_a_reply() -> None:
    seen = ("We want to find the potential difference. The tool suggests the formula V = I x R might be useful, "
            "though it may contain an error. How would you start this calculation?")  # fmt: skip
    said, removed = remove_internals(seen)
    assert removed and said == "We want to find the potential difference. How would you start this calculation?"
    assert remove_internals("The solver found a plan. What is given?")[0] == "What is given?"
    doubt = "Here is the method. My explanation may contain an error. What do you get?"
    assert remove_internals(doubt)[0] == "Here is the method. What do you get?"
    assert remove_internals(doubt, doubt_allowed=True) == (doubt, False), "beside a checked result (H1)"
    plain = "A spanner is a tool for turning a nut. Your answer may contain an error in step two. Check it?"
    assert remove_internals(plain) == (plain, False)


def test_ped10_withheld_tool_answer_never_names_a_tool(tmp_path: Path) -> None:
    """The tool's answer becomes the plan after the model disagreed twice, but in guided mode it is withheld (H2 wins):
    the honesty rule does not reach the Coach, and a reply that credits a tool or doubts its explanation reaches the
    student without that sentence."""
    script = _disagreement_script()
    leaky = ("We want to find the height. The tool suggests the formula linking speed and height might be useful, "
             "though it may contain an error. " + SAFE)  # fmt: skip
    script["coach"] = [tutor(leaky)]
    engine, provider = run(make_engine(tmp_path, script, settings=settings()))
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    assert engine.state.plan is not None and engine.state.withheld(), "the tool's plan, withheld"
    assert Fraction(12) not in visible_numbers(engine)
    coach = [json.dumps(q["messages"]) for q in provider.requests if q.get("_role") == "coach"]
    assert coach and rule_action("tool_disagreement_honest") not in coach[-1]
    text = engine.events.student_text(result.turn_id)
    assert "tool" not in text.lower() and "may contain an error" not in text and text.endswith(SAFE)
