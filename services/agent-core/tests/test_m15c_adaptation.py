"""M15.c: adaptation decided by code (LRN-15 to LRN-27). Every policy is a pure function over plain values, tested
here table by table; the engine logs each decision in the turn trace. Learners and timings are synthetic."""

from __future__ import annotations

import asyncio
import copy
import itertools
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine import adaptation
from agent_core.learner import model, policies
from agent_core.learner.mastery import DAY_MS, MasteryParams
from agent_core.learner.policies import Candidate, GamingState, SavedPosition
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from learner_harness import Clock, make_learner
from m15_harness import SETTINGS, Practice, physics, row

S = SETTINGS
P = MasteryParams()
LOOP = asyncio.new_event_loop()


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


# --- LRN-15: every policy pure and traced -------------------------------------------------------------------------

# One call per policy of TABLE LRN-15a (the representative inputs of the tables below).
CALLS: dict[str, Any] = {
    "difficulty_targeting": lambda: policies.difficulty_targeting(
        [Candidate("itm.a", 0.6), Candidate("itm.b", 0.83), Candidate("itm.c", 0.95)], S),
    "worked_example_fading": lambda: policies.worked_example_mode(0.5, S, last_mode="problem"),
    "hint_start_rung": lambda: policies.hint_start_rung(0.5, [3, 3, 1, 4, 1, 1], S),
    "gaming_detection": lambda: policies.gaming_on_hint(GamingState(last_hint_s=0.0), 6.0, S)[1],
    "unprompted_help": lambda: policies.unprompted_offer(idle_s=95, focused=True, consecutive_wrong=0,
                                                         offered_on_step=False, mode="guided", preference_on=True,
                                                         has_attempt=True, s=S),
    "self_explanation": lambda: policies.self_explanation_due(steps_since_prompt=4, p_k=0.6, previous_prompted=False,
                                                              previous_worked_example=False, mode="guided", s=S),
    "representation": lambda: policies.next_representation({"diagram": (3, 1)}, ["analogy"], True, 2, S),
    "prerequisite_detour": lambda: policies.detour_offer("kc.x", 2, {"kc.a": 0.3, "kc.b": 0.45}, [], [], S),
    "interleaving": lambda: policies.practice_sequence({"kc.a": 0.7, "kc.b": 0.8, "kc.c": 0.4}, 3,
                                                       {"kc.a": ["kc.b"]}, {}, S),
    "exam_proximity": lambda: policies.exam_proximity(["kc.a", "kc.b"], ["kc.a"], [], [], 10, S),
    "stuck_cap": lambda: policies.stuck_cap(stuck_count=8, stuck_sessions=1, p_k=0.4, revisit_at=None, now=0, s=S),
    "support_level": lambda: policies.support_level(current="standard", diagnostic_mean=0.3,
                                                    active_days_by_week=[5, 5], recovered_weeks=0, s=S),
}  # fmt: skip


def lrn15_policies_pure() -> None:
    assert set(CALLS) == set(policies.POLICIES), "one table per policy of TABLE LRN-15a"
    for name, call in CALLS.items():
        first, second = call(), call()
        assert first == second and first.policy == name, name
        assert json.loads(json.dumps(first.entry())) == first.entry(), "inputs and output are plain data"
    # No policy keeps or changes state it was handed.
    state = GamingState(last_hint_s=0.0)
    held = copy.deepcopy(state)
    policies.gaming_on_hint(state, 6.0, S)
    assert state == held
    posteriors = {"diagram": (3.0, 1.0)}
    policies.representation_outcome(posteriors, "diagram", True)
    assert posteriors == {"diagram": (3.0, 1.0)}
    # The settings are the only source of thresholds: changing a key changes the decision.
    looser = Settings(adapt_target=0.6, adapt_band=(0.5, 0.92))
    cands = [Candidate("itm.a", 0.6), Candidate("itm.b", 0.83)]
    assert policies.difficulty_targeting(cands, S).output["item_id"] == "itm.b"
    assert policies.difficulty_targeting(cands, looser).output["item_id"] == "itm.a"


def lrn15_policy_decision_traced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.contracts import errors as contract_errors

    # The record carries the decisions in the trace contract's `policy_decisions` (trace 1.1, D99).
    coach = [tutor("Which quantities does the question give you?"), tutor("Not quite yet."),
             tutor("Think about the speed at the top.", hint_rung=2)]  # fmt: skip
    engine, _ = run(make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach}))
    held, practice, _ = physics()
    kc = "kc.phy.o.motion.average_speed"
    for _ in range(3):
        practice.opportunity(kc, ("incorrect", "correct"), rung=3)
    engine._item_kcs = lambda: [kc]  # type: ignore[method-assign]
    engine.start_rung = lambda kcs: adaptation.start_rung(held.conn, P, kcs, S, held.clock.now)
    run(engine.start_problem(STATEMENT))
    run(engine.student_turn("s = 7 m"))
    result = run(engine.student_turn("I'm stuck"))
    run(close(engine))
    decisions = result.trace["policy_decisions"]
    assert [d["policy"] for d in decisions] == ["hint_start_rung"]
    inputs = decisions[0]["inputs"]
    assert inputs["recent_max_rungs"] == [3, 3, 3] and 0 <= inputs["p_k"] <= 1
    assert decisions[0]["output"]["rung"] == 2 and engine.state.rung == 2, "the decision is what the engine did"
    assert contract_errors("trace/turn-trace", result.trace) == [], "the committed record is the contract's (trace 1.1)"
    # Practice selection logs its decisions too (LRN-16, LRN-26), on the desk that served the set.
    from agent_core.engine.assessment.service import AssessmentDesk
    from memory_harness import PACK

    desk = AssessmentDesk(held.learner, PACK, S, clock_ms=held.clock)
    desk.create_practice("physics", [kc], 2)
    assert {d.policy for d in desk.policy_decisions} == {"difficulty_targeting"}
    assert all("candidates" in d.inputs and d.output["item_id"] for d in desk.policy_decisions)


# --- LRN-16: difficulty targeting --------------------------------------------------------------------------------


def lrn16_nearest_target() -> None:
    rows = [
        # (candidates, extra support, frustration, chosen)
        ([("a", 0.70), ("b", 0.81), ("c", 0.90)], False, 0.0, "b"),
        ([("a", 0.80), ("b", 0.845), ("c", 0.90)], False, 0.0, "a"),  # 0.825: a is 0.025 away, b 0.02... see below
        ([("a", 0.80), ("b", 0.86)], True, 0.0, "b"),  # extra support aims at 0.85
        ([("a", 0.80), ("b", 0.86)], False, 0.7, "b"),  # so does high frustration
        ([("a", 0.80), ("b", 0.86)], False, 0.5, "a"),
    ]
    rows[1] = ([("a", 0.79), ("b", 0.845), ("c", 0.90)], False, 0.0, "b")
    for cands, extra, frustration, chosen in rows:
        decision = policies.difficulty_targeting([Candidate(i, p) for i, p in cands], S, support_extra=extra,
                                                 frustration=frustration)  # fmt: skip
        assert decision.output["item_id"] == chosen and not decision.output["fallback"], (cands, extra, frustration)
    # Ties break by lower exposure, then pack order.
    tied = [Candidate("x", 0.80, exposures=2, pack_order=0), Candidate("y", 0.85, exposures=1, pack_order=2),
            Candidate("z", 0.85, exposures=1, pack_order=1)]  # fmt: skip
    assert policies.difficulty_targeting(tied, S).output["item_id"] == "z"
    # Through the selection the engine runs: the nearest of the physics items for a fresh learner.
    held, _, _ = physics()
    from memory_harness import PACK

    items = [i for i in PACK.table("items") if "kc.phy.o.motion.average_speed" in i["kc_ids"]][:8]
    chosen, decisions = adaptation.practice_selection(held.conn, P, items, 3, S, held.clock.now,
                                                      difficulty=PACK.item_difficulty)  # fmt: skip
    assert len(chosen) == 3 and [d.output["item_id"] for d in decisions] == [str(i["id"]) for i in chosen]
    first = decisions[0]
    target = first.inputs["target"]
    distances = [abs(p - target) for _, p, _, _ in first.inputs["candidates"]]
    picked = next(p for i, p, _, _ in first.inputs["candidates"] if i == first.output["item_id"])
    assert abs(picked - target) == pytest.approx(min(distances))
    # The weekly tuning nudges the offset toward correction, within its bound.
    assert policies.tuned_offset([0.95, 0.95], 0.825, 0.0, S) == pytest.approx(-0.02)
    assert policies.tuned_offset([0.6, 0.6], 0.825, 0.04, S) == pytest.approx(0.05)
    assert policies.tuned_offset([0.95, 0.8], 0.825, 0.0, S) == 0.0


def lrn16_band_fallback() -> None:
    low = [Candidate("a", 0.40), Candidate("b", 0.55), Candidate("c", 0.97)]
    decision = policies.difficulty_targeting(low, S)
    assert decision.output == {"item_id": "c", "p_hat": 0.97, "fallback": True}, "nearest outside the band, logged"
    assert decision.inputs["band"] == list(S.adapt_band)
    inside = policies.difficulty_targeting([Candidate("a", 0.40), Candidate("b", 0.71)], S)
    assert inside.output["item_id"] == "b" and inside.output["fallback"] is False
    assert policies.difficulty_targeting([], S).output == {"item_id": None, "p_hat": None, "fallback": False}


# --- LRN-17: worked-example fading ------------------------------------------------------------------------------


def lrn17_threshold_modes() -> None:
    table = {0.3: {"worked_example"}, 0.5: {"faded_example", "problem"}, 0.8: {"problem"}}
    for p_k, modes in table.items():
        seen = set()
        last = None
        for _ in range(4):
            mode = policies.worked_example_mode(p_k, S, last_mode=last).output["mode"]
            seen.add(mode)
            last = mode
        assert seen <= modes | ({"faded_example"} if p_k == 0.3 else set()), (p_k, seen)
        assert policies.worked_example_mode(p_k, S).output["mode"] == {0.3: "worked_example", 0.5: "faded_example",
                                                                       0.8: "problem"}[p_k]  # fmt: skip
    # Low mastery: the full example, then a faded one; the middle band alternates; extra support raises the bar.
    assert policies.worked_example_mode(0.3, S, last_mode="worked_example").output["mode"] == "faded_example"
    assert policies.worked_example_mode(0.5, S, last_mode="faded_example").output["mode"] == "problem"
    assert policies.worked_example_mode(0.45, S, support_extra=True).output["mode"] == "worked_example"


def lrn17_adaptive_fading() -> None:
    steps = [(True, False), (False, False), (True, False), (True, False), (False, True), (True, False)]
    stage, seen = 0, []
    for unaided, bottom in steps:
        stage = policies.fading_step(
            stage, unaided_correct_blank=unaided, bottom_out=bottom, max_stage=S.fading_max_stage
        )
        seen.append(stage)
    assert seen == [1, 1, 2, 3, 2, 3]
    # The projection keeps the stage per KC from the same rules.
    clock = Clock()
    learner = make_learner(clock=clock)
    practice = Practice(learner, clock)
    kc = "kc.mth.o.algebra.rearrange_linear"
    blanks = iter(f"wex.mth.o.algebra.{n:04d}" for n in range(1, 10))
    practice.opportunity(kc, ("correct",), problem=next(blanks))
    assert row(learner, kc)["fading"] == 1
    practice.opportunity(kc, ("correct",), problem=next(blanks), rung=1)  # a hinted blank does not fade
    practice.opportunity(kc, ("incorrect", "correct"), problem=next(blanks))  # nor a wrong first try
    assert row(learner, kc)["fading"] == 1
    practice.opportunity(kc, ("correct",), problem=next(blanks))
    assert row(learner, kc)["fading"] == 2
    practice.opportunity(kc, ("incorrect", "correct"), problem="prob_x", rung=5)  # a bottom-out brings one back
    assert row(learner, kc)["fading"] == 1


# --- LRN-18: hint starting rung --------------------------------------------------------------------------------


def lrn18_start_rung() -> None:
    table = [
        (0.30, [], 2),  # low P_k
        (0.39, [1, 1, 1, 1, 1, 1], 2),
        (0.40, [1, 1, 1, 1, 1, 1], 1),
        (0.80, [3, 4, 5, 1, 1, 1], 2),  # half of the last six needed rung 3 or more
        (0.80, [3, 4, 1, 1, 1, 1], 1),
        (0.80, [1, 1, 1, 1, 3, 3, 3, 3], 2),  # only the last six count
        (0.80, [3, 3, 3, 1, 1, 1, 1, 1, 1], 1),
    ]
    for p_k, rungs, expected in table:
        assert policies.hint_start_rung(p_k, rungs, S).output["rung"] == expected, (p_k, rungs)


# --- LRN-19: gaming detection ---------------------------------------------------------------------------------


def lrn19_hint_burst_pause() -> None:
    state, first = policies.gaming_on_hint(GamingState(), 100.0, S)
    assert first.output["allow_hint"] and not first.output["raised"]
    state, burst = policies.gaming_on_hint(state, 106.0, S)  # 6 s later
    assert burst.output == {"allow_hint": False, "raised": True, "coach": "hint_burst_ask_attempt",
                            "suggest_break": False}  # fmt: skip
    state, paused = policies.gaming_on_hint(state, 160.0, S)
    assert not paused.output["allow_hint"] and not paused.output["raised"], "paused until an attempt arrives"
    state, attempt = policies.gaming_on_attempt(state, wrong=True, fast=False, s=S)
    assert attempt.output["hints_resumed"] and not state.paused
    state, after = policies.gaming_on_hint(state, 200.0, S)
    assert after.output["allow_hint"]
    # Slow requests never pause.
    calm, _ = policies.gaming_on_hint(GamingState(), 0.0, S)
    calm, slow = policies.gaming_on_hint(calm, S.gaming_hint_gap_s + 1, S)
    assert slow.output["allow_hint"]


def lrn19_fast_guess_flag() -> None:
    state = GamingState()
    raised = []
    for _ in range(3):
        state, decision = policies.gaming_on_attempt(state, wrong=True, fast=True, s=S)
        raised.append(decision.output["raised"])
    assert raised == [False, False, True] and state.session_flags == 1
    slow = GamingState()
    for _ in range(5):
        slow, decision = policies.gaming_on_attempt(slow, wrong=True, fast=False, s=S)
        assert not decision.output["raised"]
    # A correct or slow answer breaks the run; three flags in a session suggest a break.
    broken = GamingState()
    for fast, wrong in ((True, True), (True, True), (True, False), (True, True)):
        broken, decision = policies.gaming_on_attempt(broken, wrong=wrong, fast=fast, s=S)
    assert not decision.output["raised"]
    many = GamingState(session_flags=2)
    for _ in range(3):
        many, decision = policies.gaming_on_attempt(many, wrong=True, fast=True, s=S)
    assert decision.output["suggest_break"] and many.session_flags == 3


# --- LRN-20: unprompted help ---------------------------------------------------------------------------------


def _offer(**kw: Any) -> dict[str, Any]:
    base = {"idle_s": 0.0, "focused": True, "consecutive_wrong": 0, "offered_on_step": False, "mode": "guided",
            "preference_on": True, "has_attempt": True}  # fmt: skip
    return policies.unprompted_offer(**{**base, **kw}, s=S).output


def lrn20_offer_once_per_step() -> None:
    assert _offer(idle_s=S.offer_idle_s)["offer"] and _offer(idle_s=S.offer_idle_s)["trigger"] == "idle"
    assert _offer(consecutive_wrong=2)["trigger"] == "repeated_errors"
    assert not _offer(idle_s=S.offer_idle_s - 1)["offer"]
    assert not _offer(idle_s=600, focused=False)["offer"], "only while the window is focused"
    assert not _offer(idle_s=600, offered_on_step=True)["offer"], "at most once per step"
    assert not _offer(consecutive_wrong=5, offered_on_step=True)["offer"]
    assert _offer(idle_s=600, has_attempt=False)["on_accept"] == "entry_question"
    assert _offer(consecutive_wrong=2)["on_accept"] == "hint"


def lrn20_offer_suppressed() -> None:
    for mode in policies.TIMED_MODES:
        assert not _offer(idle_s=600, mode=mode)["offer"] and not _offer(consecutive_wrong=3, mode=mode)["offer"]
    assert not _offer(idle_s=600, preference_on=False)["offer"]
    assert not _offer(consecutive_wrong=3, preference_on=False)["offer"]


# --- LRN-21: self-explanation cadence ------------------------------------------------------------------------


def lrn21_cadence_constraints() -> None:
    prompted: list[int] = []
    since: int | None = None
    previous_prompted = False
    worked = {3, 11, 12, 25}
    timed = set(range(30, 36))
    mastery = [0.3 if n < 2 else 0.9 if 18 <= n < 22 else 0.6 for n in range(40)]
    for n in range(40):
        decision = policies.self_explanation_due(steps_since_prompt=since, p_k=mastery[n],
                                                 previous_prompted=previous_prompted,
                                                 previous_worked_example=(n - 1) in worked,
                                                 mode="mock" if n in timed else "guided", s=S)  # fmt: skip
        due = decision.output["due"]
        if due:
            prompted.append(n)
        since = 1 if due else (since + 1 if since is not None else None)
        previous_prompted = due
    assert prompted, "prompts happen"
    for a, b in itertools.pairwise(prompted):
        assert b - a >= S.self_explanation_every_steps, "at most once per four steps, never consecutive"
    low, high = S.self_explanation_band
    for n in prompted:
        assert low <= mastery[n] < high and (n - 1) not in worked and n not in timed


# --- LRN-22: representation switching ------------------------------------------------------------------------


def lrn22_representation_order() -> None:
    posteriors = {"diagram": (2.0, 3.0), "simpler_numbers": (4.0, 1.0), "analogy": (3.0, 1.0),
                  "worked_example": (1.0, 1.0)}  # fmt: skip
    pick = lambda used, diagram=True, signals=2: policies.next_representation(  # noqa: E731
        posteriors, used, diagram, signals, S).output["representation"]  # fmt: skip
    assert pick([]) == "simpler_numbers"
    assert pick(["simpler_numbers"]) == "analogy"
    assert pick(["simpler_numbers", "analogy"]) == "worked_example"
    assert pick(["simpler_numbers", "analogy", "worked_example"]) == "diagram"
    assert pick(["simpler_numbers", "analogy", "worked_example"], diagram=False) is None, "no catalogue entry"
    assert pick([], signals=1) is None, "not before the trigger"
    prior = policies.next_representation({}, [], True, 2, S).output["representation"]
    assert prior == "diagram", "Beta(1,1) everywhere: the listed order"


def lrn22_preference_update() -> None:
    start = {"diagram": (1.0, 1.0)}
    won = policies.representation_outcome(start, "diagram", True)
    lost = policies.representation_outcome(won, "analogy", False)
    assert won["diagram"] == (2.0, 1.0) and lost["analogy"] == (1.0, 2.0) and lost["diagram"] == (2.0, 1.0)
    assert set(lost) == set(policies.REPRESENTATIONS)


# --- LRN-23: prerequisite detours ---------------------------------------------------------------------------


def lrn23_detour_and_return() -> None:
    prereqs = {"kc.p.one": 0.45, "kc.p.two": 0.30, "kc.p.three": 0.70}
    decision = policies.detour_offer("kc.k", 2, prereqs, [], [], S)
    assert decision.output["offer"] and decision.output["prerequisite_kc_id"] == "kc.p.two", "the weakest"
    assert decision.output["items"] == S.detour_items and decision.output["minutes"] == S.detour_minutes
    assert not policies.detour_offer("kc.k", 1, prereqs, [], [], S).output["offer"]
    assert not policies.detour_offer("kc.k", 2, {"kc.p": 0.6}, [], [], S).output["offer"]
    assert policies.detour_offer("kc.k", 2, prereqs, ["kc.k"], [], S).output["refused"] == "declined_this_session"
    saved = SavedPosition("kc.k", "prob_7", 3, {"steps": ["v = 14 - 9.8t"]})
    stack = policies.detour_push((), saved, S)
    back, rest = policies.detour_pop(stack)
    assert back == saved and back.step_index == 3 and back.board == {"steps": ["v = 14 - 9.8t"]} and rest == ()


def lrn23_stack_depth() -> None:
    first = SavedPosition("kc.k", "prob_1", 0)
    second = SavedPosition("kc.p", "prob_2", 1)
    stack = policies.detour_push(policies.detour_push((), first, S), second, S)
    assert len(stack) == S.detour_max_depth
    with pytest.raises(ValueError):
        policies.detour_push(stack, SavedPosition("kc.q", "prob_3", 0), S)
    third = policies.detour_offer("kc.q", 2, {"kc.r": 0.2}, [], stack, S)
    assert not third.output["offer"] and third.output["refused"] == "stack_full"


# --- LRN-24, LRN-25: block, then interleave; exam proximity ---------------------------------------------------


def _runs(sequence: list[str]) -> int:
    longest, run_len = 0, 0
    for i, kc in enumerate(sequence):
        run_len = run_len + 1 if i and sequence[i - 1] == kc else 1
        longest = max(longest, run_len)
    return longest


def lrn24_no_triple_run() -> None:
    for counts in ({"a": 4, "b": 4}, {"a": 5, "b": 3, "c": 2}, {"a": 3, "b": 3, "c": 3}, {"a": 4, "b": 2}):
        mixed = policies.interleave(counts, S.interleave_max_run)
        assert sorted(mixed) == sorted(k for k, n in counts.items() for _ in range(n))
        assert _runs(mixed) <= S.interleave_max_run, mixed
    decision = policies.practice_sequence({"kc.a": 0.7, "kc.b": 0.8, "kc.c": 0.9}, 4,
                                          {"kc.a": ["kc.b", "kc.c"]}, {}, S)  # fmt: skip
    assert _runs(decision.output["sequence"]) <= S.interleave_max_run


def lrn24_block_until_threshold() -> None:
    kcs = {"kc.weak": 0.5, "kc.ok": 0.7, "kc.near": 0.65, "kc.words": 0.9}
    decision = policies.practice_sequence(kcs, 3, {"kc.ok": ["kc.near", "kc.weak"], "kc.words": ["kc.ok"]},
                                          {"kc.words": "factual"}, S)  # fmt: skip
    out = decision.output
    assert out["blocked"] == ["kc.weak", "kc.words"], "below the threshold, and recall-type KCs, are only blocked"
    assert all("kc.weak" not in group and "kc.words" not in group for group in out["mixed_groups"])
    sequence = out["sequence"]
    weak = [i for i, k in enumerate(sequence) if k == "kc.weak"]
    assert weak == list(range(weak[0], weak[0] + 3)), "a contiguous block"


def lrn25_no_new_kc_final() -> None:
    candidates = ["kc.new", "kc.old_ok", "kc.old_wrong", "kc.chosen"]
    started = ["kc.old_ok", "kc.old_wrong"]
    decision = policies.exam_proximity(candidates, started, ["kc.old_wrong"], ["kc.chosen"], 10, S)
    assert decision.output["phase"] == "final"
    assert decision.output["allowed"] == ["kc.old_wrong", "kc.old_ok", "kc.chosen"], "recent errors first, no new KC"
    assert "kc.new" in policies.exam_proximity(candidates, started, [], [], 40, S).output["allowed"]
    assert policies.exam_proximity(candidates, started, [], [], 40, S).output["interleave_share"] == 0.5
    # The planner in the final phase proposes no unassigned new KC.
    held, practice, desk = physics(exam=None)
    kc = "kc.phy.o.motion.average_speed"
    practice.opportunity(kc, ("incorrect",))
    held.conn.execute("UPDATE profile SET exam_date = ?", ("2026-10-19",))  # 10 days from the store's day
    plan = desk.propose()
    assert plan["phase"] == "final"
    started_kcs = {r[0] for r in held.conn.execute("SELECT kc_id FROM kc_mastery WHERE attempts > 0")}
    mains = [b for b in plan["blocks"] if b["kind"] == "main"]
    assert mains and all(set(b["kc_ids"]) <= started_kcs for b in mains)
    assert all(set(a["kc_ids"]) <= started_kcs for a in plan["alternatives"])
    chosen = desk.propose(kc_id="kc.phy.o.motion.acceleration_from_change")
    assert chosen["blocks"][[b["kind"] for b in chosen["blocks"]].index("main")]["kc_ids"] == [
        "kc.phy.o.motion.acceleration_from_change"], "unless the student chooses it"  # fmt: skip


# --- LRN-26: stuck cap ---------------------------------------------------------------------------------------


def lrn26_cap_and_revisit() -> None:
    from agent_core.engine.assessment.service import AssessmentDesk
    from memory_harness import PACK

    held, practice, desk = physics()
    kc = "kc.phy.o.motion.average_speed"
    practice.opportunity(kc, ("incorrect",), rung=4)
    while row(held.learner, kc)["p"] >= S.stuck_cap_mastery:  # an easy KC's first answers still sit above the bar
        practice.opportunity(kc, ("incorrect",), rung=4)
    for n in range(S.stuck_cap_opportunities - 1):
        assert row(held.learner, kc)["status"] != "moved_on" and row(held.learner, kc)["stuck"] == n + 1
        practice.opportunity(kc, ("incorrect",), rung=4)
    found = row(held.learner, kc)
    assert found["status"] == "moved_on" and found["moved_on_at"] is not None
    revisit = found["moved_on_at"] + int(S.stuck_revisit_days * DAY_MS)
    view = model.kc_views(held.conn, P, held.clock.now)[kc]
    assert view.state == "moved_on" and view.revisit_at == revisit, "the revisit is scheduled"
    # The ninth opportunity is not served: practice selection and the planner skip the KC until the revisit.
    assessments = AssessmentDesk(held.learner, PACK, S, clock_ms=held.clock)
    items = [i for i in PACK.table("items") if i["kc_ids"] == [kc]]
    chosen, decisions = adaptation.practice_selection(held.conn, P, items, 3, S, held.clock.now)
    assert chosen == [] and decisions and all(d.policy == "stuck_cap" and not d.output["serve"] for d in decisions)
    plan = desk.propose()
    assert all(kc not in b["kc_ids"] for b in plan["blocks"] if b["kind"] == "main")
    assert assessments is not None
    # On the revisit date it comes back first, with a different representation first.
    held.clock.now = revisit + 60_000
    assert model.kc_views(held.conn, P, held.clock.now)[kc].state == "learning"
    back = desk.propose()
    main = next(b for b in back["blocks"] if b["kind"] == "main")
    assert main["kc_ids"] == [kc] and main["reason_code"] == "revisit_moved_on"
    decision = policies.stuck_cap(stuck_count=0, stuck_sessions=0, p_k=view.p_mastery, revisit_at=revisit,
                                  now=held.clock.now, s=S)  # fmt: skip
    assert decision.output["serve"] and decision.output["change_representation"]
    # Three sessions without progress reach the cap as well.
    other = "kc.phy.o.motion.distance_or_displacement"
    for _ in range(S.stuck_cap_sessions):
        practice.start()
        practice.opportunity(other, ("incorrect",), rung=4)
        practice.end()
    assert row(held.learner, other)["status"] == "moved_on"


# --- LRN-27: support for weaker students ----------------------------------------------------------------------


def lrn27_support_level_toggle() -> None:
    def level(current: str, mean: float | None, weeks: list[int], recovered: int) -> dict[str, Any]:
        return policies.support_level(current=current, diagnostic_mean=mean, active_days_by_week=weeks,
                                      recovered_weeks=recovered, s=S).output  # fmt: skip

    assert level("standard", 0.30, [5, 5], 0)["support_level"] == "extra", "a low entry diagnostic"
    assert level("standard", 0.60, [2, 1], 0)["support_level"] == "extra", "low attendance two weeks running"
    assert level("standard", 0.60, [2, 4], 0)["support_level"] == "standard", "one low week is not enough"
    assert level("extra", 0.60, [4, 5], 1)["support_level"] == "extra", "cleared only after two good weeks"
    assert level("extra", 0.60, [4, 5], 2)["support_level"] == "standard"
    effects = level("standard", 0.30, [5, 5], 0)["effects"]
    assert effects == {"example_below": S.support_example_below, "target_success": S.adapt_target_supported,
                       "activity_minutes": S.support_activity_minutes, "weekly_freezes": S.support_weekly_freezes,
                       "daily_reminder": True}  # fmt: skip
    assert level("standard", 0.6, [5, 5], 0)["effects"]["weekly_freezes"] == S.streak_weekly_freezes
    # The plan desk writes the level to the profile (field name only in the event) and the plan sizes to it.
    held, practice, desk = physics()
    kc = "kc.phy.o.motion.average_speed"
    while row(held.learner, kc).get("p", 1.0) >= S.support_diagnostic_below:
        practice.opportunity(kc, ("incorrect",))
    held.learner.record("diagnostic_item", {"subject": "physics", "kc_id": kc, "response": "answered"},
                        source="engine")  # fmt: skip
    desk.refresh_support_level()
    assert held.conn.execute("SELECT support_level FROM profile").fetchone()[0] == "extra"
    events = [e.payload for e in held.learner.log.by_seq() if e.type == "profile_updated"]
    assert events == [{"changed_fields": ["support_level"]}]
    plan = desk.propose()
    assert sum(b["minutes"] for b in plan["blocks"] if b["kind"] != "warmup") <= S.support_activity_minutes
    assert desk.decisions and desk.decisions[-1].output["support_level"] == "extra"
