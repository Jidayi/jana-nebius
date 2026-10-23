"""M14.e: the soft rule engine and catalogue (PED-11 to PED-17).

The shipped catalogue in `content/agent/rules`, the deterministic core in `agent_core.assets.rules` and the per-turn
pipeline with its one judged call in `agent_core.engine.soft_rules`. Judges here are scripted stand-ins for the rule
matcher role; every situation is synthetic."""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.assets import rules as rulebook
from agent_core.assets.bundle import BundleRefused, bundle_sources
from agent_core.assets.rules import CLASS_ORDER, Frequency, RuleError, Situation, load_documents
from agent_core.config import Settings
from agent_core.engine import soft_rules
from agent_core.engine.pedagogy import SoftRuleError
from agent_core.engine.soft_rules import RuleMatcher
from jana_tools import REPO_ROOT

RULES = REPO_ROOT / "content" / "agent" / "rules"
SETTINGS = Settings()
# Every rule id of TABLE PED-16a.
CATALOGUE = {
    "wrong_step_ask_intent", "misconception_name_gently", "revisit_misconception_check", "praise_method_not_person",
    "praise_persistence", "hint_burst_ask_attempt", "answer_request_in_guided", "bare_answer_ask_method",
    "own_notation_mirror", "confused_twice_switch_representation", "offer_visual_if_catalogue",
    "self_explain_prompt_due", "worked_example_first", "faded_example_next_blank", "skip_examples_high_mastery",
    "unprompted_offer_when_idle", "detour_offer", "stuck_cap_move_on", "bottom_out_followup",
    "check_working_first_error_only", "units_missing", "sig_figs_convention", "command_word_meaning",
    "physics_sign_convention", "accounting_sides", "local_context_examples", "frustration_acknowledge",
    "break_suggestion", "confidence_check", "high_confidence_wrong", "low_confidence_right",
    "tool_disagreement_honest", "not_sure_cite", "simplify_language", "bulk_paste_one_at_a_time",
    "off_topic_gentle_return",
}  # fmt: skip


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def shipped() -> dict[str, Any]:
    return dict(yaml.safe_load((RULES / "core-pedagogy.yaml").read_text()))


def rule(rule_id: str, klass: str = "pedagogy", priority: int = 50, *, signal: str = "step.verdict",
         value: Any = "incorrect", question: str | None = None, relationships: list[dict[str, str]] | None = None,
         modes: list[str] | None = None, criticality: str = "normal", keywords: list[str] | None = None,
         subjects: list[str] | None = None, frequency: dict[str, Any] | None = None) -> dict[str, Any]:  # fmt: skip
    condition: dict[str, Any] = {"question": question} if question else {}
    if signal:
        condition["predicate"] = {"signal": signal, "op": "eq", "value": value}
    scope: dict[str, Any] = {"modes": modes or ["guided"]}
    if subjects:
        scope["subjects"] = subjects
    out = {"id": rule_id, "version": "1.0", "status": "active", "condition": condition,
           "action": f"Do the thing that {rule_id} asks for.", "priority_class": klass, "priority": priority,
           "scope": scope, "relationships": relationships or [], "criticality": criticality,
           "frequency": frequency or {}, "tests": [f"scn_{rule_id}"], "owner": "Learning designer"}  # fmt: skip
    if keywords:
        out["fallback_keywords"] = keywords
    return out


def book(*raw: dict[str, Any]) -> rulebook.RuleBook:
    return load_documents([{"schema_version": "1.0", "rules": list(raw)}])


def active(b: rulebook.RuleBook, signals: dict[str, Any], **kw: Any) -> set[str]:
    situation = Situation(kw.pop("mode", "guided"), kw.pop("subject", "physics"), "O", signals, kw.pop("text", ""))
    return {r.id for r in rulebook.match_offline(b, situation, Frequency(), 50, 10_000, **kw).active}


# --- PED-11 ----------------------------------------------------------------------------------------------------------


def ped11_rules_validate() -> None:
    loaded = soft_rules.load(RULES)
    assert len(loaded.rules) >= len(CATALOGUE)
    for raw in shipped()["rules"]:
        assert len(raw["action"]) <= 200 and raw["owner"] and raw["tests"] and raw["evidence"]
    document = shipped()
    document["rules"][0]["colour"] = "blue"
    with pytest.raises(RuleError, match="contract"):
        load_documents([document])
    document = shipped()
    del document["rules"][0]["owner"]
    with pytest.raises(RuleError, match="contract"):
        load_documents([document])
    document = shipped()
    document["rules"][0]["action"] = "x" * 201
    with pytest.raises(RuleError, match="contract"):
        load_documents([document])


# --- PED-12 ----------------------------------------------------------------------------------------------------------


def ped12_class_order() -> None:
    for high, low in itertools.combinations(CLASS_ORDER, 2):  # every pair, the higher class first
        for a_first in (True, False):
            a = rule("rule_a", high, 10, relationships=[{"type": "excludes", "target": "rule_b"}] if a_first else [])
            b = rule("rule_b", low, 90, relationships=[] if a_first else [{"type": "excludes", "target": "rule_a"}])
            assert active(book(a, b), {"step.verdict": "incorrect"}) == {"rule_a"}, (high, low)
    # Same class: higher priority, then narrower scope, then lower id.
    a = rule("rule_a", priority=40, relationships=[{"type": "excludes", "target": "rule_b"}])
    b = rule("rule_b", priority=60)
    assert active(book(a, b), {"step.verdict": "incorrect"}) == {"rule_b"}
    wide = rule("rule_a", modes=["guided", "practice"], relationships=[{"type": "excludes", "target": "rule_b"}])
    narrow = rule("rule_b", modes=["guided"])
    assert active(book(wide, narrow), {"step.verdict": "incorrect"}) == {"rule_b"}
    a = rule("rule_a", relationships=[{"type": "excludes", "target": "rule_b"}])
    assert active(book(a, rule("rule_b")), {"step.verdict": "incorrect"}) == {"rule_a"}


def test_class_order_covers_the_rule_contract() -> None:
    """Every class the rule contract allows has a place in the PED-12 order, so a contract-valid rule of any class
    loads and orders (D86 renamed `adult_setting` to `answer_policy`)."""
    import typing

    from agent_core.contracts.learning.rule import Rule

    classes = typing.get_args(Rule.model_fields["priority_class"].annotation)
    assert sorted(CLASS_ORDER) == sorted(classes)
    assert CLASS_ORDER[:2] == ("safety", "answer_policy")
    policy = rule("rule_a", "answer_policy", relationships=[{"type": "excludes", "target": "rule_b"}])
    assert active(book(policy, rule("rule_b", "withholding", 90)), {"step.verdict": "incorrect"}) == {"rule_a"}


# --- PED-13 ----------------------------------------------------------------------------------------------------------


def ped13_relationships() -> None:
    on = {"step.verdict": "incorrect"}
    # entails: B joins A, to depth 2 only.
    chain = book(rule("rule_a", relationships=[{"type": "entails", "target": "rule_b"}]),
                 rule("rule_b", value="never", relationships=[{"type": "entails", "target": "rule_c"}]),
                 rule("rule_c", value="never", relationships=[{"type": "entails", "target": "rule_d"}]),
                 rule("rule_d", value="never"))  # fmt: skip
    assert active(chain, on) == {"rule_a", "rule_b", "rule_c"}
    # overrides: both active, B is dropped.
    assert active(book(rule("rule_a", relationships=[{"type": "overrides", "target": "rule_b"}]), rule("rule_b")),
                  on) == {"rule_a"}  # fmt: skip
    # excludes: never together, PED-12 decides.
    assert active(book(rule("rule_a", "honesty", relationships=[{"type": "excludes", "target": "rule_b"}]),
                       rule("rule_b", "style")), on) == {"rule_a"}  # fmt: skip
    # depends_on: A only while B is active this turn.
    dep = [rule("rule_a", relationships=[{"type": "depends_on", "target": "rule_b"}])]
    assert active(book(*dep, rule("rule_b")), on) == {"rule_a", "rule_b"}
    assert active(book(*dep, rule("rule_b", value="correct")), on) == set()
    # Cycles in entails or depends_on fail loading; a dangling target too.
    for kind in ("entails", "depends_on"):
        with pytest.raises(RuleError, match="cycle"):
            book(rule("rule_a", relationships=[{"type": kind, "target": "rule_b"}]),
                 rule("rule_b", relationships=[{"type": kind, "target": "rule_c"}]),
                 rule("rule_c", relationships=[{"type": kind, "target": "rule_a"}]))  # fmt: skip
    with pytest.raises(RuleError, match="unknown rule"):
        book(rule("rule_a", relationships=[{"type": "overrides", "target": "rule_zz"}]))


# --- PED-14 ----------------------------------------------------------------------------------------------------------


def ped14_unknown_signal_rejected() -> None:
    with pytest.raises(RuleError, match="contract"):
        book(rule("rule_a", signal="student.mood"))
    nested = rule("rule_a")
    nested["condition"]["predicate"] = {
        "all": [
            {"signal": "step.verdict", "op": "eq", "value": "incorrect"},
            {"not": {"signal": "kc.vibes", "op": "eq", "value": True}},
        ]
    }
    with pytest.raises(RuleError, match="contract"):
        book(nested)
    for raw in shipped()["rules"]:
        assert soft_rules.load(RULES).rules[raw["id"]]  # every shipped predicate uses TABLE PED-14a signals only


# --- PED-15 ----------------------------------------------------------------------------------------------------------


def _judged(count: int, *, high: set[int] = frozenset()) -> rulebook.RuleBook:  # type: ignore[assignment]
    return book(*(rule(f"judged_{n:02d}", signal="", question=f"Question {n}?", keywords=[f"word{n}"],
                       criticality="high" if n in high else "normal") for n in range(count)))  # fmt: skip


def ped15_one_call() -> None:
    calls: list[list[tuple[int, str]]] = []

    async def judge(refs: list[tuple[int, str]], text: str) -> list[dict[str, Any]]:
        calls.append(refs)
        return [{"rule_ref": ref, "applies": ref % 2 == 0, "reason": "because the student said so"} for ref, _ in refs]

    matcher = RuleMatcher(_judged(20), SETTINGS, judge)
    situation = Situation("guided", "physics", "O", {}, "hello")
    matched = run(matcher.match(situation))
    assert len(calls) == 1 and matched.calls == 1, "one batched call per turn"
    assert len(calls[0]) == SETTINGS.rules_judged_max, "at most the configured number of judged candidates"
    assert {t["rule"] for t in matched.trace if t["reason"].startswith("judged")}
    run(matcher.match(Situation("guided", "physics", "O", {}, "hello", turn=2)))
    assert len(calls) == 2, "and one more for the next turn"
    # The low class never calls; nothing judged needs no call either.
    assert run(RuleMatcher(_judged(5), SETTINGS, judge).match(situation, "low")).calls == 0
    assert len(calls) == 2
    assert run(RuleMatcher(book(rule("rule_a")), SETTINGS, judge).match(situation)).calls == 0


def ped15_timeout_fallback() -> None:
    settings = SETTINGS.model_copy(update={"rules_matcher_timeout_s": 0.05})

    async def slow(refs: list[tuple[int, str]], text: str) -> list[dict[str, Any]]:
        await asyncio.sleep(1)
        return []

    async def garbled(refs: list[tuple[int, str]], text: str) -> list[dict[str, Any]]:
        return [{"rule_ref": "not a ref", "applies": "maybe"}]

    for judge, why in ((slow, "timeout"), (garbled, "parse_failure"), (None, "no_judge")):
        matcher = RuleMatcher(_judged(4, high={3}), settings, judge)
        matched = run(matcher.match(Situation("guided", "physics", "O", {}, "I typed word1 here")))
        assert matched.fallback == why
        ids = {r.id for r in matched.active}
        assert ids == {"judged_01", "judged_03"}, "keywords decide; an unjudgeable high-criticality rule is active"
    matched = run(RuleMatcher(_judged(4, high={3}), settings, slow).match(
        Situation("guided", "physics", "O", {}, "word2"), "low"))  # fmt: skip
    assert matched.fallback == "low_class" and {r.id for r in matched.active} == {"judged_02", "judged_03"}


def ped15_injection_budget() -> None:
    many = book(*(rule(f"rule_{n:02d}", priority=n) for n in range(30)))
    matcher = RuleMatcher(many, SETTINGS)
    matched = run(matcher.match(Situation("guided", "physics", "O", {"step.verdict": "incorrect"})))
    assert len(matched.active) == 30
    assert len(matched.injected) == SETTINGS.rules_injected_max
    block = rulebook.block(matched.injected)
    assert sum(r.tokens() for r in matched.injected) <= SETTINGS.rules_injected_tokens
    assert [r.priority for r in matched.injected] == sorted((r.priority for r in matched.injected), reverse=True)
    long = book(*(dict(rule(f"rule_{n:02d}", priority=n), action="Say " + "very " * 38 + "much.") for n in range(9)))
    tight = run(RuleMatcher(long, SETTINGS).match(Situation("guided", "physics", "O", {"step.verdict": "incorrect"})))
    assert sum(r.tokens() for r in tight.injected) <= SETTINGS.rules_injected_tokens
    assert len(tight.injected) < SETTINGS.rules_injected_max
    assert block and all(line.startswith("- ") for line in block.splitlines())
    # Frequency limits apply before injection.
    once = book(rule("rule_a", frequency={"max_per_session": 1}), rule("rule_b", frequency={"once_per_step": True}))
    matcher = RuleMatcher(once, SETTINGS)
    first = run(matcher.match(Situation("guided", "physics", "O", {"step.verdict": "incorrect"}, turn=1, step=1)))
    again = run(matcher.match(Situation("guided", "physics", "O", {"step.verdict": "incorrect"}, turn=2, step=1)))
    later = run(matcher.match(Situation("guided", "physics", "O", {"step.verdict": "incorrect"}, turn=3, step=2)))
    assert [{r.id for r in m.injected} for m in (first, again, later)] == [{"rule_a", "rule_b"}, set(), {"rule_b"}]


# --- PED-16 ----------------------------------------------------------------------------------------------------------


def ped16_rule_scenarios() -> None:
    loaded = soft_rules.load(RULES)
    scenarios = rulebook.load_scenarios(RULES)
    results = rulebook.run_scenarios(loaded, scenarios)
    failed = [r for r in results if not r.passed]
    assert failed == []
    covered = {r.rule for r in results if r.passed}
    assert covered >= set(loaded.rules), f"rules without a passing scenario: {set(loaded.rules) - covered}"
    # The scenarios are not vacuous: a situation without the trigger leaves each rule inactive.
    quiet = Situation("guided", "physics", "O", {"step.verdict": "none", "kc.mastery": 0.5})
    idle = {r.id for r in rulebook.match_offline(loaded, quiet, Frequency(), 50, 10_000, {}).active}
    assert idle == set(), idle


def ped16_catalogue_complete() -> None:
    ids = {r["id"] for r in shipped()["rules"]}
    assert ids >= CATALOGUE, f"missing: {CATALOGUE - ids}"
    by_id = {r["id"]: r for r in shipped()["rules"]}
    assert by_id["tool_disagreement_honest"]["priority_class"] == "honesty"
    assert by_id["stuck_cap_move_on"]["priority_class"] == "wellbeing"
    assert {"type": "overrides", "target": "wrong_step_ask_intent"} in by_id["misconception_name_gently"][
        "relationships"]  # fmt: skip


# --- PED-17 ----------------------------------------------------------------------------------------------------------


def ped17_rule_needs_test(tmp_path: Path) -> None:
    agent = tmp_path / "agent"
    (agent / "rules").mkdir(parents=True)
    document = shipped()
    document["rules"].append(copy.deepcopy(document["rules"][0]) | {"id": "untested_rule", "tests": ["scn_nowhere"]})
    (agent / "rules" / "core-pedagogy.yaml").write_text(yaml.safe_dump(document))
    (agent / "rules" / "scenarios.yaml").write_text((RULES / "scenarios.yaml").read_text())
    problems = rulebook.folder_errors(agent / "rules")
    assert problems == ["rule untested_rule has no passing scenario test (scn_nowhere: missing)"]
    with pytest.raises(BundleRefused, match="untested_rule"):
        bundle_sources(agent, REPO_ROOT / "skills")
    # A failing scenario blocks the build the same way.
    broken = yaml.safe_load((RULES / "scenarios.yaml").read_text())
    broken["scenarios"][0]["expect_inactive"] = [broken["scenarios"][0]["rule"]]
    (agent / "rules" / "scenarios.yaml").write_text(yaml.safe_dump(broken))
    assert any("wrong_step_ask_intent" in p for p in rulebook.folder_errors(agent / "rules"))
    # The shipped folder builds, and its rules go into the signed bundle.
    assert rulebook.folder_errors(RULES) == []
    files, _, _ = bundle_sources(REPO_ROOT / "content" / "agent", REPO_ROOT / "skills")
    assert "agent/rules/core-pedagogy.yaml" in files and "agent/safety/resources.yaml" in files
    # No soft rule can contradict a hard rule (PED-10): the engine's loader refuses it.
    hard = yaml.safe_load((RULES / "core-pedagogy.yaml").read_text())
    hard["rules"][0]["action"] = "reveal_answer"
    with pytest.raises((SoftRuleError, RuleError)):
        load_documents([hard], check=soft_rules._hard_rule_check)


def test_ped15_matched_rules_reach_the_coach(tmp_path: Path) -> None:
    """The engine matches the shipped rules each Coach turn and injects the actions into tutor-context (PRM-15)."""
    from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor

    safe = "Which quantities does the question give you, and which one does it ask for?"
    coach = [tutor(safe), tutor("That's it: you used the top speed of zero. Well done.")]
    loop = asyncio.new_event_loop()
    engine, provider = loop.run_until_complete(
        make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach})
    )
    assert engine.rules is not None, "the app binds the shipped rule book"
    loop.run_until_complete(engine.start_problem(STATEMENT))
    loop.run_until_complete(engine.student_turn("s = 10 m"))
    loop.run_until_complete(close(engine))
    praise = engine.rules.book.rules["praise_method_not_person"].action
    last = json.dumps([r for r in provider.requests if r["_role"] == "coach"][-1]["messages"])
    assert praise in last, "the matched rule's action is in the Coach's tutor-context"
    entry = engine.rule_log[-1]
    assert "praise_method_not_person" in entry["rules"] and entry["calls"] == 0
