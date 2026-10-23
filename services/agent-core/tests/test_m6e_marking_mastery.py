"""M6.e: deterministic verdicts (ASM-02, with the ASM-03 and ASM-04 subset) and the minimal mastery projection
(LRN-07, LRN-09 subset). Items and logs are synthetic."""

from __future__ import annotations

import asyncio
import math
import random
from decimal import Decimal
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import document, validate
from agent_core.engine.marking import MARKERS, Converted, Verdict, mark, parse_numeric, settle
from agent_core.learner.mastery import (
    DAY_MS,
    Ability,
    KcEvidence,
    MasteryParams,
    StateInputs,
    kc_probability,
    kc_state,
    observe,
)
from agent_core.store.generated.item_types import ITEM_TYPES
from learner_harness import KCS, random_log

SETTINGS = Settings()


async def convert(quantity: str, to: str) -> Converted | None:
    """The worker's unit conversion, run in-process for the tests."""
    from tool_worker.functions.units import units_convert
    from tool_worker.protocol import WorkerError
    from tool_worker.registry import CallContext

    context = CallContext("t", "chk_test_units", {}, {}, lambda: False, settings={})
    try:
        value, _ = units_convert({"quantity": quantity, "to": to}, context)
    except WorkerError:
        return None
    return Converted(Decimal(value["value"]["decimal"]), "chk_test_units")


def numeric(value: str, unit: str | None, policy: str = "equivalent", tolerance: dict | None = None) -> dict:
    answer = {
        "kind": "numeric",
        "value": value,
        "unit": unit,
        "unit_policy": policy,
        "tolerance": tolerance or {"mode": "relative", "value": 0.005},
        "check_id": "chk_build_test_key",
    }
    return {"id": "itm.phy.o.kinematics.9001", "type": "numeric",
            "parts": [{"id": "a", "prompt": "Speed?", "marks": 2, "answer": answer, "hints": []}]}  # fmt: skip


def choice() -> dict:
    options = [{"id": "a", "text": "5 m/s", "correct": True},
               {"id": "b", "text": "0.2 m/s", "correct": False, "misconception_id": "mc.phy.o.time_over_distance"},
               {"id": "c", "text": "50 m/s", "correct": False}]  # fmt: skip
    return {"id": "itm.phy.o.kinematics.9002", "type": "mcq",
            "parts": [{"id": "a", "prompt": "Pick", "marks": 1,
                       "answer": {"kind": "mcq", "diagnostic": False, "options": options}, "hints": []}]}  # fmt: skip


def run(item: dict, response: Any) -> Verdict:
    return asyncio.run(mark(item, "a", response, convert, SETTINGS))


# --- ASM-04 ---------------------------------------------------------------------------------------------------------


def asm04_numeric_cases() -> None:
    speed = numeric("15", "m/s")
    rows = [
        # (item, response, outcome, error_category): one or more fixtures per row of TABLE ASM-04a
        (speed, "15 m/s", "correct", None),  # value and unit right
        (speed, "54 km/h", "correct", None),  # an equivalent unit is accepted unless the item fixes one
        (speed, "15.04 m/s", "correct", None),  # within the relative tolerance
        (speed, "15", "partial", "units_missing"),  # value right, unit missing where required
        (numeric("15", "m/s", "exact"), "54 km/h", "incorrect", "unit_error"),  # right after conversion, wrong unit
        (speed, "15 km/h", "incorrect", "unit_error"),  # the right number with the wrong unit
        (speed, "150 m/s", "incorrect", "power_of_ten"),  # off by a power of ten
        (speed, "1.5", "incorrect", "power_of_ten"),
        (numeric("2.00", "m/s^2", tolerance={"mode": "sig_figs", "value": 3}), "2 m/s^2", "partial", "sig_figs"),
        (numeric("2.0", "m/s^2", tolerance={"mode": "sig_figs", "value": 2}), "2 m/s^2", "correct", None),  # ±1
        # More figures than stated is feedback only (VER-09): full marks.
        (numeric("2.0", "m/s^2", tolerance={"mode": "sig_figs", "value": 2}), "2.000 m/s^2", "correct", None),
        (speed, "17 m/s", "incorrect", "value"),  # outside tolerance
        (speed, "fifteen", "incorrect", "unreadable"),
    ]
    for item, response, outcome, category in rows:
        verdict = run(item, response)
        assert (verdict.outcome, verdict.error_category) == (outcome, category), response
    assert run(speed, "15 m/s").marks_awarded == 2 and run(speed, "15").marks_awarded == 1
    assert parse_numeric("v = 1.5 \\times 10^{1} m/s") is not None
    assert parse_numeric("1.5 × 10^1 m/s").value == Decimal(15)  # type: ignore[union-attr]


def test_extreme_student_exponents_do_not_crash_marking() -> None:
    item = numeric("15", None, "none")
    for response in ("1e1000", "1e-1000", "-1e1000", "1.000e1000"):
        verdict = run(item, response)
        assert (verdict.outcome, verdict.error_category) == ("incorrect", "value"), response
    for response in ("1e1000000", "1e999999999999999999999999999"):
        verdict = run(item, response)
        assert (verdict.outcome, verdict.error_category) == ("incorrect", "unreadable"), response


def test_asm04_over_precise_rounds_to_key() -> None:
    """An answer with more figures than the item states is right when it rounds to the key at that precision
    (VER-09 `too_many` is feedback only); a simple fraction is an exact answer."""
    item = numeric("20", "m/s")
    item["checks"] = {"chk_build_test_key": {"args": {"sf": 2}}}
    for response, outcome in (
        ("19.6 m/s", "correct"),
        ("20.4 m/s", "correct"),
        ("21 m/s", "incorrect"),
        ("19.4 m/s", "incorrect"),
        ("15 m/s", "incorrect"),
        ("196/10 m/s", "correct"),
    ):
        assert run(item, response).outcome == outcome, response
    # A pack item keeps no checks: the key's own figures are the stated precision, never below two.
    assert run(numeric("11", "m/s"), "10.625 m/s").outcome == "correct"
    assert run(numeric("8.8", "m/s"), "8.75 m/s").outcome == "correct"
    assert run(numeric("8.8", "m/s"), "8.74 m/s").outcome == "incorrect"
    assert run(numeric("400", "m"), "350 m").outcome == "incorrect"
    # A whole-number key counts every digit (its trailing zeros are ambiguous): 2049 is not $2000.
    assert run(numeric("2000", None, "none"), "2049").outcome == "incorrect"
    assert run(numeric("2000", None, "none"), "2000.4").outcome == "correct"
    assert run(numeric("20", "m/s"), "19.6 m/s").outcome == "correct"  # two figures written, two meant
    assert run(numeric("9.5", "m/s"), "19/2 m/s").outcome == "correct"
    assert parse_numeric("200/27 m/s").unit == "m/s"  # type: ignore[union-attr]


# --- ASM-02 ---------------------------------------------------------------------------------------------------------


def _suite() -> list[tuple[dict, Any]]:
    speed = numeric("15", "m/s")
    multi = {"id": "itm.phy.o.kinematics.9003", "type": "multi_select", "parts": [{"id": "a", "prompt": "Pick",
             "marks": 2, "hints": [], "answer": {"kind": "multi_select", "scoring": "per_option", "options": [
                 {"id": "a", "text": "speed", "correct": True}, {"id": "b", "text": "velocity", "correct": True},
                 {"id": "c", "text": "mass", "correct": False}]}}]}  # fmt: skip
    order = {"id": "itm.phy.o.kinematics.9004", "type": "ordering", "parts": [{"id": "a", "prompt": "Order",
             "marks": 2, "hints": [], "answer": {"kind": "ordering", "scoring": "adjacent_pairs",
             "elements": [{"id": "x", "text": "x"}, {"id": "y", "text": "y"}, {"id": "z", "text": "z"}],
             "correct_order": ["x", "y", "z"]}}]}  # fmt: skip
    cases: list[tuple[dict, Any]] = [(speed, r) for r in ("15 m/s", "54 km/h", "15", "150 m/s", "17 m/s", "x")]
    cases += [(choice(), r) for r in ("a", "b", "c", "z")]
    cases += [(multi, r) for r in (["a", "b"], ["a"], ["c"], ["a", "c"])]
    cases += [(order, r) for r in (["x", "y", "z"], ["x", "y", "z"][::-1], ["y", "z", "x"])]
    return cases


def asm02_verdict_has_provenance() -> None:
    for item, response in _suite():
        verdict = run(item, response)
        assert verdict.outcome != "unverifiable"
        assert verdict.provenance, (item["type"], response)
        payload = verdict.payload(verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                                  closes_opportunity=True)  # fmt: skip
        validate("learning/learning-event#/$defs/payload_verdict", payload)
    # A type with no marker in this build makes no claim: unverifiable, and no mastery observation follows.
    algebraic = {"id": "itm.phy.o.kinematics.9005", "type": "algebraic", "parts": [{"id": "a", "marks": 1}]}
    assert run(algebraic, "x").outcome == "unverifiable"


def asm02_model_cannot_mark() -> None:
    for item, response in _suite():
        verdict = run(item, response)
        for proposal in ("correct", "incorrect", "partial", "unverifiable"):
            settled = settle(proposal, verdict)
            # The marker's outcome and marks stand whatever the model proposed; a disagreement is recorded.
            assert (settled.outcome, settled.marks_awarded) == (verdict.outcome, verdict.marks_awarded)
            assert settled.discarded_model_outcome == (None if proposal == verdict.outcome else proposal)
            assert "discarded_model_outcome" not in settled.payload(
                verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                closes_opportunity=True)  # fmt: skip


# --- ASM-03 ---------------------------------------------------------------------------------------------------------


def asm03_types_match_pack_contract() -> None:
    contract = document("content/content-pack")["$defs"]["Item"]["properties"]["type"]["enum"]
    assert sorted(ITEM_TYPES) == sorted(contract)  # one row per type: the generator refuses a type listed twice
    assert set(MARKERS) <= set(ITEM_TYPES)
    assert all(row["marker"] for row in ITEM_TYPES.values())


# --- LRN-07 ---------------------------------------------------------------------------------------------------------


def lrn07_default_learning_curve() -> None:
    p = MasteryParams()
    kc = KCS[1]
    ability, evidence = Ability(), {kc: KcEvidence()}
    assert kc_probability(ability.theta, evidence[kc], p) == 0.5
    for n in range(5):
        observe(y=1, w=1.0, t=n * 60_000, weights={kc: 1.0}, first_error_kc=None, ability=ability,
                evidence=evidence, p=p)  # fmt: skip
    assert kc_probability(ability.theta, evidence[kc], p) >= 0.85


def lrn07_implied_decay_nonnegative() -> None:
    p = MasteryParams()
    rng = random.Random(7)
    target, other = KCS[0], KCS[1]
    prerequisites = {other: [target]}  # successes on `other` imply evidence on `target`
    dependents = {target: [other]}
    ability, evidence = Ability(), {}
    direct = 0.0  # the target's direct evidence, decayed whenever its counts are
    t = 0
    for _ in range(400):
        t += rng.choice((60_000, DAY_MS, 30 * DAY_MS, 400 * DAY_MS))  # long gaps included
        on_target = rng.random() < 0.5
        y = rng.random() < 0.6
        weights = {target: 1.0} if on_target else {other: 1.0}
        previous = evidence[target].decayed_at if target in evidence else None
        update = observe(y=int(y), w=1.0, t=t, weights=weights, first_error_kc=None, ability=ability,
                         evidence=evidence, p=p, prerequisites=prerequisites, dependents=dependents)  # fmt: skip
        ev_now = evidence.get(target)
        if previous is not None and ev_now is not None and ev_now.decayed_at != previous:
            direct *= 2 ** (-(ev_now.decayed_at - previous) / (p.mastery_half_life_days * DAY_MS))
        direct += update.direct.get(target, 0.0)
        ev = evidence.get(target)
        if ev is not None:
            raw = ev.succ_w + ev.fail_w - ev.implied_w
            assert raw >= -1e-12
            assert math.isclose(raw, direct, rel_tol=1e-9, abs_tol=1e-12)


def _reference_replay(events: list[Any], p: MasteryParams) -> tuple[dict[str, float], dict[str, float]]:
    """An independent, plain re-implementation of the observation rows and the pfa_elo update, for comparison."""
    theta: dict[str, float] = {}
    count: dict[str, float] = {}
    s: dict[str, float] = {}
    f: dict[str, float] = {}
    at: dict[str, int] = {}
    attempts: dict[str, dict[str, Any]] = {}
    verdicts: dict[str, list[tuple[str, str, str]]] = {}
    hints: dict[tuple[str, str, Any], int] = {}
    superseded: set[str] = set()

    def sig(x: float) -> float:
        return 1 / (1 + math.exp(-x))

    for e in events:
        pl = e.payload
        if e.type == "attempt":
            attempts[pl["attempt_id"]] = pl
        elif e.type == "hint":
            key = (e.session_id, pl["problem_ref"], pl.get("step_index"))
            hints[key] = max(hints.get(key, 0), pl["rung"])
        elif e.type == "verdict":
            a = attempts.get(pl["attempt_id"])
            if a is None:
                continue
            step = (e.session_id, a["problem_ref"], a.get("step_index"))
            verdicts.setdefault(str(step), []).append((pl["verdict_id"], pl["outcome"], pl["attempt_id"]))
            if pl.get("supersedes"):
                superseded.add(pl["supersedes"])
            if not pl["closes_opportunity"]:
                continue
            outcomes = [o for v, o, _ in verdicts[str(step)] if v not in superseded and o != "unverifiable"]
            if pl["outcome"] == "unverifiable":
                outcomes.append("unverifiable")
            rung = hints.get(step, 0)
            final = outcomes[-1] if outcomes else None
            if a["mode"] == "solution" or final in (None, "unverifiable"):
                obs = []
            elif rung >= 5:
                obs = [(0, 1.0)]
            elif final == "incorrect":
                obs = [(0, 0.6)]
            elif final == "partial":
                obs = [(1, 0.5)]
            elif any(o in ("incorrect", "partial") for o in outcomes[:-1]):
                obs = [(0, 0.6), (1, (0.5, 0.4, 0.3, 0.2, 0.1)[rung])]
            elif rung >= 1:
                obs = [(1, (0.4, 0.3, 0.2, 0.1)[rung - 1])]
            else:
                obs = [(1, 1.0)]
            m = {"check_working": 0.8, "learn": 0.5}.get(a["mode"], 1.0)
            if final == "incorrect" and 0 < a["time_ms"] < 3000:  # a fast wrong answer (no item median: 3 s)
                m *= 0.3
            q: dict[str, float] = {}
            total = sum(k["weight"] for k in a["kc_ids"])
            for k in a["kc_ids"]:
                q[k["kc_id"]] = q.get(k["kc_id"], 0.0) + k["weight"] / total
            subject = {"phy": "physics", "mth": "mathematics"}[next(iter(q)).split(".")[1]]
            now = int(e.hlc.split("-")[0])
            for y, w in obs:
                w *= m
                for k in q:
                    if k in at:
                        decay = 2 ** (-max(0, now - at[k]) / (p.mastery_half_life_days * DAY_MS))
                        s[k], f[k] = s[k] * decay, f[k] * decay
                        at[k] = max(at[k], now)
                    else:
                        s[k], f[k], at[k] = 0.0, 0.0, now
                th = theta.get(subject, 0.0)
                eta = th + sum(q[k] * (0.0 + 0.35 * s[k] - 0.15 * f[k]) for k in q)
                p_hat = sig(eta)
                theta[subject] = th + 0.4 / (1 + 0.05 * count.get(subject, 0.0)) * w * (y - p_hat)
                count[subject] = count.get(subject, 0.0) + w
                if y == 1:
                    for k in q:
                        s[k] += w
                elif pl.get("first_error_kc") in q:
                    f[pl["first_error_kc"]] += w
                else:
                    gaps = {k: 1 - sig(theta[subject] + 0.35 * s[k] - 0.15 * f[k]) for k in q}
                    for k, g in gaps.items():
                        f[k] += w * g / sum(gaps.values())
    probability = {}
    for k in s:
        subject = {"phy": "physics", "mth": "mathematics"}[k.split(".")[1]]
        probability[k] = sig(theta.get(subject, 0.0) + 0.35 * s[k] - 0.15 * f[k])
    return probability, theta


def lrn07_matches_reference() -> None:
    p = MasteryParams()
    for seed in range(40):
        learner = random_log(seed, sessions=4)
        expected_p, expected_theta = _reference_replay(list(learner.log.merged()), p)
        theta = dict(learner.conn.execute("SELECT subject, theta FROM subject_ability"))
        assert theta.keys() == expected_theta.keys()
        for subject, value in theta.items():
            assert math.isclose(value, expected_theta[subject], abs_tol=1e-9), (seed, subject)
        # A KC row's probability is current as of its own last update; compare those rows recomputed now.
        for kc, succ, fail in learner.conn.execute("SELECT kc_id, succ_w, fail_w FROM kc_mastery"):
            if kc in expected_p:
                now_p = kc_probability(theta[{"phy": "physics", "mth": "mathematics"}[kc.split(".")[1]]],
                                       KcEvidence(succ, fail), p)  # fmt: skip
                assert math.isclose(now_p, expected_p[kc], abs_tol=1e-9), (seed, kc)


# --- LRN-09 ---------------------------------------------------------------------------------------------------------

STATES = {"not_started", "learning", "ready_to_check", "mastered", "needs_review", "moved_on"}


def lrn09_total_state_function() -> None:
    p = MasteryParams()
    fixtures = {
        "no direct evidence, high prior": StateInputs(0, 0.99, 0.0),
        "no direct evidence, implied only": StateInputs(0, 0.9, 0.0, confirmed=True),
        "high probability, low n_eff": StateInputs(2, 0.95, 2.99),
        "at both thresholds": StateInputs(3, 0.85, 3.0),
        "just under probability": StateInputs(5, 0.8499999, 5.0),
        "confirmed": StateInputs(4, 0.9, 4.0, confirmed=True),
        "confirmed then failed": StateInputs(4, 0.9, 4.0, confirmed=True, failed_since_confirmed=True),
        "confirmed, low retrievability": StateInputs(4, 0.9, 4.0, confirmed=True, low_retrievability=True),
        "retry lock with high probability": StateInputs(6, 0.97, 6.0, retry_lock_active=True),
        "deferral and confirmation": StateInputs(6, 0.97, 6.0, confirmed=True, deferral_active=True),
    }
    expected = {
        "no direct evidence, high prior": "not_started",
        "no direct evidence, implied only": "not_started",
        "high probability, low n_eff": "learning",
        "at both thresholds": "ready_to_check",
        "just under probability": "learning",
        "confirmed": "mastered",
        "confirmed then failed": "needs_review",
        "confirmed, low retrievability": "needs_review",
        "retry lock with high probability": "learning",
        "deferral and confirmation": "moved_on",
    }
    for name, inputs in fixtures.items():
        state = kc_state(inputs, p)
        assert state in STATES
        assert state == expected[name], name
    # Exhaustively over a grid of inputs, the function is total and returns exactly one known state.
    for direct in (0, 1, 3):
        for prob in (0.1, 0.85, 0.99):
            for n_eff in (0.0, 3.0):
                for flags in range(32):
                    bits = [bool(flags >> i & 1) for i in range(5)]
                    assert kc_state(StateInputs(direct, prob, n_eff, *bits), p) in STATES


def _expected_states(learner: Any, p: MasteryParams) -> None:
    """Every KC row's state follows the table, given the confirmation the log's mastery checks establish."""
    confirmed: dict[str, bool] = {}
    for event in learner.log.merged():
        if event.type == "mastery_check" and event.payload["check_state"] in ("passed", "failed"):
            confirmed[event.payload["kc_id"]] = event.payload["check_state"] == "passed"
    rows = learner.conn.execute("SELECT kc_id, status, p_mastery, n_eff, attempts, mastery_check_state FROM kc_mastery")
    for kc, status, prob, n_eff, attempts, check_state in rows:
        if status in ("mastered", "needs_review"):
            assert check_state == "passed" and confirmed.get(kc)
        if status == "ready_to_check":
            assert prob >= p.mastery_ready_p and n_eff >= p.mastery_ready_n_eff and check_state != "passed"
        assert (status == "not_started") == (attempts == 0)


def lrn09_state_table() -> None:
    p = MasteryParams()
    for seed in range(60):
        learner = random_log(seed, sessions=5)
        _expected_states(learner, p)
        # Incremental states equal the states of a rebuild, row for row.
        before = learner.conn.execute("SELECT kc_id, status FROM kc_mastery ORDER BY kc_id").fetchall()
        learner.projector.rebuild()
        assert learner.conn.execute("SELECT kc_id, status FROM kc_mastery ORDER BY kc_id").fetchall() == before


def lrn09_mastered_requires_check() -> None:
    seen_mastered = 0
    for seed in range(120):
        learner = random_log(seed, sessions=6)
        passed = {
            e.payload["kc_id"]
            for e in learner.log.merged()
            if e.type == "mastery_check" and e.payload["check_state"] == "passed"
        }
        for (kc,) in learner.conn.execute("SELECT kc_id FROM kc_mastery WHERE status IN ('mastered', 'needs_review')"):
            seen_mastered += 1
            assert kc in passed, (seed, kc)
    assert seen_mastered > 0  # the corpus exercises the path


STANDARD_FORM = ["3.2e-4", "3.2E-4", "3.2x10^-4", "3.2X10^-4", "3.2 x 10^-4", "3.2*10^-4", "3.2*10**-4",
                 "3.2×10^-4", "3.2 × 10⁻⁴", "3.2x10^(-4)", "3.2·10^-4", "3.2x10^{-4}"]


@pytest.mark.parametrize("typed", STANDARD_FORM)
def test_every_way_of_typing_standard_form_reads_the_same(typed: str) -> None:
    # What students type, and the form the app itself shows back, are one value (polish pass, ASM-04).
    parsed = parse_numeric(typed)
    assert parsed is not None and parsed.value == Decimal("0.00032")
    assert parsed.unit is None and parsed.sig_figs == 2


SPELLINGS = [("9.8 m/s²", "9.8", "m/s^2"), ("0.5 mol dm⁻³", "0.5", "mol dm^-3"), ("−4.5", "-4.5", None),
             ("12 345.6 kg", "12345.6", "kg"), ("v = 3.0 × 10⁸ m/s", "3.0E+8", "m/s")]


@pytest.mark.parametrize(("typed", "value", "unit"), SPELLINGS)
def test_superscripts_minus_signs_and_grouped_thousands(typed: str, value: str, unit: str | None) -> None:
    parsed = parse_numeric(typed)
    assert parsed is not None and parsed.value == Decimal(value) and parsed.unit == unit
