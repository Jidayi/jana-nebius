"""M15.a: the learner model's fields, observation rows, credit and blame, cold start and propagation, the parameter
file, budgets and privacy (LRN-03, LRN-04, LRN-06, LRN-08, LRN-10, LRN-11, LRN-42, LRN-43). Learners, answers and
timings are synthetic."""

from __future__ import annotations

import asyncio
import itertools
import random
import time
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.learner.mastery import (
    CLOSES,
    DAY_MS,
    Ability,
    Bkt,
    InvalidClose,
    KcEvidence,
    MasteryParams,
    Opportunity,
    blame,
    fast_guess,
    kc_probability,
    modifiers,
    observation_row,
    observations,
    observe,
)
from agent_core.learner.profile import merge_profile, stored_profile
from agent_core.learner.projections import Projector, default_projections
from agent_core.store.generated.schema import LEARNER
from agent_core.store.ids import new_ulid
from agent_core.store.sqlite import statements
from learner_harness import Clock, Session, make_learner, random_log
from m15_harness import SETTINGS, A, B, C, D, Practice, chain_learner, physics, row
from memory_harness import PACK

P = MasteryParams()
MODES = ("guided", "solution", "check_working", "learn", "practice", "mock", "revision", "diagnostic", "mastery_check",
         "review")  # fmt: skip


# --- LRN-03: every component rebuilds from events alone ---------------------------------------------------------


def _recreate(conn: Any, table: str) -> None:
    """Drop a table (and what hangs on it) and create it again from the storage contract's own statements."""
    owned = [s for s in statements(LEARNER) if f"TABLE {table} (" in s or f" ON {table}(" in s or f" ON {table} " in s
             or (table == "notes" and "notes_fts" in s)]  # fmt: skip
    if table == "notes":
        conn.execute("DROP TABLE IF EXISTS notes_fts")
    conn.execute(f"DROP TABLE {table}")
    for statement in owned:
        conn.execute(statement)


def lrn03_components_rebuildable() -> None:
    held, practice, desk = physics()
    random_log(11, sessions=5, learner=held.learner, clock=held.clock)
    kc = "kc.phy.o.motion.average_speed"
    desk.decide(desk.propose()["plan_id"], "start")
    for _ in range(4):
        practice.opportunity(kc, ("incorrect", "correct"), rung=1, confidence=3)
    practice.end(active_ms=1_200_000)
    held.learner.record("integrity_signal", {"kind": "hint_burst"}, source="engine")
    held.learner.record(
        "misconception_evidence",
        {"misconception_id": "mc.phy.o.average_of_speeds", "kc_id": kc, "evidence_source": "probe", "weight": 1.0},
        source="checker",
    )
    held.learner.record("correction", {"target": "preference", "target_id": "pace", "action": "override",
                                       "value": "short", "actor_role": "student"}, source="student")  # fmt: skip
    projector = held.learner.projector
    for projection in projector.projections:
        before = projector.checksum(projection.name)
        rows = sum(held.conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in projection.tables)  # noqa: S608
        assert rows, f"{projection.name} has rows to lose"
        for table in projection.tables:
            _recreate(held.conn, table)
        assert projector.checksum(projection.name) != before
        projector.rebuild([projection.name])
        assert projector.checksum(projection.name) == before, projection.name
    assert {p.name for p in projector.projections} >= {"kc_mastery", "study_plans", "engagement", "notes",
                                                       "learner_misconceptions", "preferences", "attempts"}  # fmt: skip


# --- LRN-04: a profile merge writes only what changed ---------------------------------------------------------


def lrn04_profile_merge_partial() -> None:
    held, _, _ = physics()
    held.conn.execute("UPDATE profile SET goals = '[\"Pass physics\"]', reading_level = 'standard'")
    before = stored_profile(held.conn)
    stamp = held.conn.execute("SELECT display_name, age_band, created_at FROM profile").fetchone()
    changed = merge_profile(held.learner, {"exam_date": "2027-05-20", "level": before["level"],
                                           "subjects": before["subjects"]}, held.clock.now)  # fmt: skip
    assert changed == ["exam_date"], "an unchanged value offered again is not a change"
    after = stored_profile(held.conn)
    assert after == {**before, "exam_date": "2027-05-20"}
    assert held.conn.execute("SELECT display_name, age_band, created_at FROM profile").fetchone() == stamp
    events = [e for e in held.learner.log.by_seq() if e.type == "profile_updated"]
    assert [e.payload for e in events] == [{"changed_fields": ["exam_date"]}], "field names only, never values"
    assert merge_profile(held.learner, {"exam_date": "2027-05-20"}, held.clock.now) == []
    assert len([e for e in held.learner.log.by_seq() if e.type == "profile_updated"]) == 1
    with pytest.raises(ValueError):
        merge_profile(held.learner, {"answer_policy": "always"}, held.clock.now)  # fixed, never stored (D86)


# --- LRN-06: observation rows and modifiers -------------------------------------------------------------------

OUTCOME_SEQUENCES = ((), ("correct",), ("incorrect",), ("partial",), ("unverifiable",), ("incorrect", "correct"),
                     ("partial", "correct"), ("correct", "correct"), ("incorrect", "incorrect"),
                     ("incorrect", "unverifiable"), ("unverifiable", "correct"))  # fmt: skip


def lrn06_close_outcomes_exhaustive() -> None:
    rows_seen: set[str] = set()
    for close, outcomes, rung, mode in itertools.product((*CLOSES, "closed_silently", ""), OUTCOME_SEQUENCES,
                                                          range(6), MODES):  # fmt: skip
        op = Opportunity(mode, outcomes, rung, close=close)
        invalid = close not in CLOSES or (close == "verdict" and not outcomes)
        if invalid:
            with pytest.raises(InvalidClose):
                observation_row(op, P)
            continue
        name, rows = observation_row(op, P)  # exactly one row, by precedence
        rows_seen.add(name)
        assert observations(op, P) == [(y, w * _product(modifiers(op, P))) for y, w in rows]
    assert rows_seen == {
        "excluded",
        "bottom_out",
        "not_learned",
        "abandoned_unattempted",
        "abandoned_after_attempt",
        "terminal_incorrect",
        "partial",
        "recovered",
        "hinted_first_correct",
        "first_correct",
    }
    # The configured weights are the ones applied (keys, not literals).
    tuned = MasteryParams.from_settings(Settings(obs_terminal_incorrect_w=0.55,
                                                 obs_hinted_first_correct_w=(0.45, 0.35, 0.25, 0.15)))  # fmt: skip
    assert observations(Opportunity("practice", ("incorrect",), 0), tuned) == [(0, 0.55)]
    for rung, weight in zip(range(1, 5), (0.45, 0.35, 0.25, 0.15), strict=True):
        assert observations(Opportunity("practice", ("correct",), rung), tuned) == [(1, weight)]


def _product(found: list[tuple[str, float]]) -> float:
    out = 1.0
    for _, factor in found:
        out *= factor
    return out


def lrn06_observation_table() -> None:
    # TABLE LRN-06a, one fixture per row, in precedence order.
    table_a = [
        (Opportunity("solution", ("correct",), 0), []),
        (Opportunity("practice", ("unverifiable",), 0), []),
        (Opportunity("practice", ("incorrect", "correct"), 5), [(0, 1.0)]),
        (Opportunity("diagnostic", (), 0, close="not_learned"), [(0, 0.5)]),
        (Opportunity("practice", (), 2, close="abandoned"), []),
        (Opportunity("practice", ("incorrect",), 0, close="abandoned"), [(0, 0.5)]),
        (Opportunity("mock", ("incorrect",), 0), [(0, 0.6)]),
        (Opportunity("practice", ("partial",), 0), [(1, 0.5)]),
        *[(Opportunity("practice", ("incorrect", "correct"), r), [(0, 0.6), (1, w)])
          for r, w in enumerate((0.5, 0.4, 0.3, 0.2, 0.1))],
        *[(Opportunity("practice", ("partial", "correct"), r), [(0, 0.6), (1, w)])
          for r, w in enumerate((0.5, 0.4, 0.3, 0.2, 0.1))],
        *[(Opportunity("practice", ("correct",), r), [(1, w)]) for r, w in zip(range(1, 5), (0.4, 0.3, 0.2, 0.1),
                                                                                strict=True)],
        (Opportunity("practice", ("correct",), 0), [(1, 1.0)]),
        (Opportunity("practice", ("correct", "correct"), 0), [(1, 1.0)]),  # repeats collapse to the first correct
    ]  # fmt: skip
    for op, expected in table_a:
        assert observations(op, P) == pytest.approx(expected), op
    # TABLE LRN-06b, one fixture per row (median 40 s; MCQ with 4 options).
    base = {"outcomes": ("correct",), "max_rung": 0, "median_ms": 40_000}
    table_b = [
        (Opportunity("guided", **base, time_ms=30_000), 1.0),
        *[(Opportunity(m, **base, time_ms=30_000), 1.0) for m in ("practice", "review", "revision", "diagnostic",
                                                                   "mastery_check", "mock")],
        (Opportunity("check_working", **base, time_ms=30_000), 0.8),
        (Opportunity("learn", **base, time_ms=30_000), 0.5),
        (Opportunity("practice", ("incorrect",), 0, time_ms=2_000, median_ms=40_000), 0.6 * 0.3),
        (Opportunity("practice", ("incorrect",), 0, time_ms=7_000, median_ms=40_000), 0.6 * 0.3),  # 0.2 x median
        (Opportunity("practice", ("incorrect",), 0, time_ms=9_000, median_ms=40_000), 0.6),
        (Opportunity("practice", **base, time_ms=2_000, options=4), 0.5),
        (Opportunity("practice", **base, time_ms=30_000, options=4), 0.75),
        (Opportunity("practice", **base, time_ms=130_000), 0.8),
        (Opportunity("practice", **base, time_ms=130_000, options=4), 0.75 * 0.8),
        (Opportunity("practice", **base, time_ms=30_000, kc_source="diagnoser", kc_confidence=0.2), 0.5),
        (Opportunity("practice", **base, time_ms=30_000, kc_source="diagnoser", kc_confidence=0.7), 0.7),
        (Opportunity("practice", ("unverifiable",), 0, time_ms=30_000), None),
    ]  # fmt: skip
    for op, weight in table_b:
        found = observations(op, P)
        if weight is None:
            assert found == []
        else:
            assert sum(w for _, w in found) == pytest.approx(weight), op
    assert fast_guess(Opportunity("practice", ("incorrect",), 0, time_ms=2_000), P)
    assert not fast_guess(Opportunity("practice", ("incorrect",), 0, time_ms=60_000), P)
    # The projection applies the same rows: an abandoned step, a "not learned" answer and a superseding verdict.
    learner = make_learner()
    practice = Practice(learner, Clock())
    kc = "kc.mth.o.algebra.rearrange_linear"
    practice.opportunity(kc, ("incorrect",), close=False)
    practice.end("student_left")
    assert row(learner, kc)["fail_w"] == pytest.approx(0.5) and row(learner, kc)["attempts"] == 1
    practice.opportunity(kc, ("unverifiable",), close=False)  # no graded attempt: nothing when abandoned
    practice.end("student_left")
    assert row(learner, kc)["attempts"] == 1
    other = "kc.mth.o.algebra.expand_brackets"
    first = practice.opportunity(other, ("incorrect",))
    before = row(learner, other)
    learner.record("verdict", {"verdict_id": new_ulid(), "attempt_id": _attempt_of(learner, first[0]),
                               "outcome": "correct", "check_ids": ["chk_test_key"], "closes_opportunity": True,
                               "supersedes": first[0], "marker_version": "test.2"},
                   source="checker", session_id=practice.session)  # fmt: skip
    after = row(learner, other)
    assert after["attempts"] == before["attempts"] == 1, "a correction never adds a second opportunity"
    assert after["fail_w"] == 0 and after["succ_w"] == pytest.approx(1.0), "the corrected verdict replaces the row"
    checksum = learner.projector.checksum()
    learner.projector.rebuild()
    assert learner.projector.checksum() == checksum


def _attempt_of(learner: Any, verdict_id: str) -> str:
    return next(e.payload["attempt_id"] for e in learner.log.by_seq()
                if e.type == "verdict" and e.payload["verdict_id"] == verdict_id)  # fmt: skip


def lrn06_bottom_out_is_failure() -> None:
    rng = random.Random(6)
    for _ in range(2000):
        outcomes = tuple(rng.choice(("correct", "incorrect", "partial", "unverifiable"))
                         for _ in range(rng.randint(1, 3)))  # fmt: skip
        op = Opportunity(rng.choice(MODES), outcomes, 5, close=rng.choice(CLOSES),
                         time_ms=rng.randint(500, 200_000), median_ms=rng.choice((None, 30_000)),
                         options=rng.choice((None, 4)))  # fmt: skip
        if op.close == "verdict" and not outcomes:
            continue
        assert all(y == 0 for y, _ in observations(op, P)), op
    learner = make_learner()
    practice = Practice(learner, Clock())
    kc = "kc.mth.o.algebra.rearrange_linear"
    practice.opportunity(kc, ("incorrect", "correct"), rung=5)
    found = row(learner, kc)
    assert found["succ_w"] == 0 and found["fail_w"] == pytest.approx(1.0)


# --- LRN-08: credit and blame ------------------------------------------------------------------------------------


def lrn08_blame_first_error_kc() -> None:
    weights = {A: 0.5, B: 0.5}
    ability, evidence = Ability(), {A: KcEvidence(), B: KcEvidence()}
    update = observe(y=0, w=0.6, t=0, weights=weights, first_error_kc=B, ability=ability, evidence=evidence, p=P)
    assert update.direct == {B: 0.6} and evidence[A].fail_w == 0 and evidence[B].fail_w == pytest.approx(0.6)
    # Through the projection: the Checker's first-error KC takes the whole failure.
    learner = make_learner()
    practice = Practice(learner, Clock())
    k1, k2 = "kc.mth.o.algebra.rearrange_linear", "kc.mth.o.algebra.expand_brackets"
    practice.opportunity([k1, k2], ("incorrect",), first_error_kc=k2)
    assert row(learner, k1)["fail_w"] == 0 and row(learner, k2)["fail_w"] == pytest.approx(0.6)
    # A success credits every tagged KC in full.
    practice.opportunity([k1, k2], ("correct",))
    assert row(learner, k1)["succ_w"] == pytest.approx(1.0) and row(learner, k2)["succ_w"] == pytest.approx(1.0)


def lrn08_blame_proportional() -> None:
    probabilities = {A: 0.9, B: 0.3, C: 0.6}
    shares = blame(0.6, {A: 1 / 3, B: 1 / 3, C: 1 / 3}, None, probabilities)
    assert sum(shares.values()) == pytest.approx(0.6)
    assert shares[B] > shares[C] > shares[A], "the weakest KC takes most blame"
    assert shares[B] / shares[A] == pytest.approx((1 - 0.3) / (1 - 0.9))
    assert blame(0.6, {A: 0.5, B: 0.5}, "kc.mth.o.other.not_tagged", {A: 0.5, B: 0.5}) == {A: 0.3, B: 0.3}
    ability = Ability()
    evidence = {A: KcEvidence(succ_w=4.0), B: KcEvidence()}
    update = observe(y=0, w=1.0, t=0, weights={A: 0.5, B: 0.5}, first_error_kc=None, ability=ability,
                     evidence=evidence, p=P)  # fmt: skip
    assert sum(update.direct.values()) == pytest.approx(1.0) and update.direct[B] > update.direct[A]


# --- LRN-10: cold start and prerequisite propagation -------------------------------------------------------------


def lrn10_implied_depth_and_weight() -> None:
    learner = chain_learner()
    practice = Practice(learner, Clock())
    practice.opportunity(D, ("correct",))  # D needs C, C needs B, B needs A
    assert row(learner, C)["implied_w"] == pytest.approx(0.3) and row(learner, C)["succ_w"] == pytest.approx(0.3)
    assert row(learner, B)["implied_w"] == pytest.approx(0.15), "halved at the second level"
    assert row(learner, A) == {}, "nothing beyond depth 2"
    failed = chain_learner()
    practice = Practice(failed, Clock())
    practice.opportunity(A, ("incorrect",))  # a failure flows to the KCs that depend on A
    assert row(failed, B)["fail_w"] == pytest.approx(0.3) and row(failed, C)["fail_w"] == pytest.approx(0.15)
    assert row(failed, D) == {}
    tuned = chain_learner(params=MasteryParams.from_settings(Settings(mastery_implied_w=0.2, mastery_implied_depth=1)))
    Practice(tuned, Clock()).opportunity(D, ("correct",))
    assert row(tuned, C)["implied_w"] == pytest.approx(0.2) and row(tuned, B) == {}
    # Cold start: a new profile starts at theta 0 and the pack priors.
    assert kc_probability(0.0, KcEvidence(), P, PACK.reference_difficulty("kc.phy.o.motion.average_speed")) == (
        pytest.approx(kc_probability(0.0, KcEvidence(), P, PACK.kcs["kc.phy.o.motion.average_speed"].difficulty_prior
                                     or 0.0)))  # fmt: skip


def lrn10_implied_cannot_master() -> None:
    learner = chain_learner()
    practice = Practice(learner, Clock())
    for _ in range(40):
        practice.opportunity(D, ("correct",))
    found = row(learner, C)
    assert found["p"] >= 0.85 and found["status"] == "not_started", "implied evidence alone shows not started"
    assert found["n_eff"] == pytest.approx(0.0, abs=1e-9)
    practice.opportunity(C, ("correct",))
    found = row(learner, C)
    assert found["status"] == "learning", "one direct observation: n_eff below the bar however high P is"
    assert found["n_eff"] < P.mastery_ready_n_eff <= found["succ_w"]


# --- LRN-11: the bake-off, the parameter file and the BKT path ---------------------------------------------------


def _params_document(**mastery: Any) -> dict[str, Any]:
    return {"kind": "mastery_params", "version": "0.1.0", "schema_version": "1.0", "pack": "pack.phy.o",
            "params_version": "0.1.0", "fitted": False,
            "mastery": {"model": "pfa_elo", "count_half_life_days": 90, "elo": {"k_a": 0.4, "k_c": 0.05},
                        "kc_defaults": {"beta": 0.0, "gamma": 0.35, "rho": -0.15},
                        "kc_overrides": {"kc.phy.o.motion.average_speed": {"beta": -0.2, "gamma": 0.41, "rho": -0.11}},
                        **mastery}}  # fmt: skip


def _contract(target: str) -> Any:
    """The generated validator of a contract (D99 adopted the learner-model additions)."""
    from agent_core.contracts import validator

    return validator(target)


def lrn11_params_signed_and_valid(tmp_path: Path) -> None:
    from agent_core.config.environments import Environment
    from agent_core.store.mastery_params import problems
    from agent_core.store.pack_index import PackIndex
    from agent_core.store.packs import PackRejectedError, verify, write_pack
    from m20_fixtures import REQUIRED_TABLES, content_pack
    from signing_service.hierarchy import dev_trust

    good = _params_document()
    check = _contract("learning/mastery-params")
    assert list(check.iter_errors(good)) == [] and problems(good) == []
    out_of_range = _params_document(elo={"k_a": 9.0, "k_c": 0.05})
    wrong_shape = _params_document(model="deep_kt")
    for bad in (out_of_range, wrong_shape):
        assert problems(bad) and list(check.iter_errors(bad)), "the schema and the device agree it is invalid"
    trust = dev_trust()
    first = tmp_path / "a.pack"
    content_pack(first, signed_files={"signed/mastery-params.json": good})
    verify(first, Environment.DEV, trust)
    index = PackIndex.load([first], Environment.DEV, trust)
    assert index.kc_params == {"kc.phy.o.motion.average_speed": (-0.2, 0.41, -0.11)}
    params = MasteryParams.from_settings(SETTINGS, kc_overrides=index.kc_overrides())
    assert params.kc_values("kc.phy.o.motion.average_speed") == (-0.2, 0.41, -0.11)
    assert params.kc_values("kc.phy.o.motion.distance_or_displacement") == (0.0, 0.35, -0.15)
    # A newer pack whose file fails schema, or whose signature fails, is rejected; the previous parameters stay.
    newer = tmp_path / "b.pack"
    content_pack(newer, version="0.2.0", signed_files={"signed/mastery-params.json": out_of_range})
    with pytest.raises(PackRejectedError, match="mastery-params"):
        verify(newer, Environment.DEV, trust)
    forged = tmp_path / "c.pack"  # a signature that does not verify
    signed = content_pack(forged, version="0.3.0", signed_files={"signed/mastery-params.json": good})
    value = signed["signature"]["value"]
    tables = {t: [] for t in REQUIRED_TABLES}
    write_pack(forged, {**signed, "signature": {**signed["signature"], "value": value[::-1]}}, tables,
               {"signed/mastery-params.json": good})  # fmt: skip
    edited = tmp_path / "d.pack"  # the file changed after signing: its hash no longer matches the signed manifest
    signed = content_pack(edited, version="0.4.0", signed_files={"signed/mastery-params.json": good})
    write_pack(edited, signed, tables, {"signed/mastery-params.json": _params_document(model="bkt")})
    for candidate in (forged, edited):
        with pytest.raises(PackRejectedError):
            verify(candidate, Environment.DEV, trust)
    for candidate in (newer, forged, edited):
        shelf = PackIndex.load([first, candidate], Environment.DEV, trust)
        assert shelf.kc_params == index.kc_params and shelf.mastery_models == {"pack.phy.o": "pfa_elo"}
        assert [name for name, _ in shelf.rejected] == [candidate.name]


def lrn11_bkt_matches_pybkt() -> None:
    """The BKT path's one-step predictions are pyBKT's (the test-only `conformance` group, pyBKT 1.4.3) on a fixture,
    to 1e-6. pyBKT builds its model structures in a `preload` fit; the parameters are then set to the fixture's, and
    pyBKT's own forward pass predicts."""
    import numpy as np
    import pandas as pd
    from pyBKT.models import Model

    fixture = [True, False, True, True, False, True, True, True]
    bkt = Bkt(0.3, 0.12, 0.1, 0.2)
    frame = pd.DataFrame({"order_id": range(len(fixture)), "user_id": "s", "skill_name": "skill",
                          "correct": [int(c) for c in fixture]})  # fmt: skip
    model = Model(seed=0, num_fits=1, parallel=False)
    model.fit(data=frame, preload=True)
    model.fit_model["skill"].update(prior=bkt.p_init, learns=np.array([bkt.p_transit]), forgets=np.array([0.0]),
                                    guesses=np.array([bkt.p_guess]), slips=np.array([bkt.p_slip]))  # fmt: skip
    expected = list(model.predict(data=frame)["correct_predictions"])
    assert bkt.trace(fixture) == pytest.approx(expected, abs=1e-6)


def test_bkt_follows_its_published_update() -> None:
    """Without pyBKT: the BKT path is the four-parameter update LRN-11 states, step by step."""
    bkt = Bkt(0.3, 0.12, 0.1, 0.2)
    p_l, expected = 0.3, []
    for correct in (True, False, True):
        expected.append(p_l * 0.9 + (1 - p_l) * 0.2)
        likelihood = (p_l * 0.9 / (p_l * 0.9 + (1 - p_l) * 0.2) if correct
                      else p_l * 0.1 / (p_l * 0.1 + (1 - p_l) * 0.8))  # fmt: skip
        p_l = likelihood + (1 - likelihood) * 0.12
    assert bkt.trace([True, False, True]) == pytest.approx(expected, abs=1e-12)


# --- LRN-42: budgets and the content-only class --------------------------------------------------------------------


def lrn42_budgets() -> None:
    settings = Settings()
    # One mastery and schedule update: a closing verdict folded into every projection.
    held, practice, desk = physics()
    random_log(3, sessions=6, learner=held.learner, clock=held.clock)
    kcs = sorted(PACK.kcs)[:12]
    for kc in kcs:
        practice.opportunity(kc, ("correct",))
    timings = []
    for n in range(30):
        started = time.perf_counter()
        practice.opportunity(kcs[n % len(kcs)], ("incorrect", "correct"), rung=1)
        timings.append((time.perf_counter() - started) * 1000 / 4)  # four events per opportunity (hint, 2x2)
    assert sorted(timings)[len(timings) // 2] <= settings.budget_update_ms, timings
    # The daily plan over the physics pack.
    started = time.perf_counter()
    desk.propose()
    assert (time.perf_counter() - started) * 1000 <= settings.budget_plan_ms
    # A full rebuild of the configured number of events, every projection, in the background budget.
    clock = Clock()
    learner = make_learner(clock=clock, projections=[])
    rng = random.Random(42)
    while learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] < settings.projection_rebuild_budget_events:
        Session(rng, learner, clock).run(rng.randint(2, 6))
        clock.now += rng.randint(3_600_000, 3 * DAY_MS)
    projector = Projector(learner.conn, MasteryParams(), None, default_projections(settings))
    started = time.perf_counter()
    projector.rebuild()
    elapsed = time.perf_counter() - started
    # Measured on the development machine; the low hardware class reference laptop runs it in the device lab (EVL-14).
    assert elapsed <= settings.projection_rebuild_budget_s, f"{elapsed:.2f} s"


def lrn42_content_only_class(tmp_path: Path) -> None:
    """No model at all: practice marks and moves mastery, plans are proposed and decided, progress reads, offline."""
    import socket

    from agent_core.engine.assessment.service import AssessmentDesk

    attempts: list[Any] = []
    real = socket.socket.connect

    def offline(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost") and not str(host).startswith("/"):
            attempts.append(host)
            raise OSError("networking is blocked in this test")
        return real(sock, address)

    held, _, desk = physics()
    assessments = AssessmentDesk(held.learner, PACK, SETTINGS, clock_ms=held.clock)
    mcq = next(i for i in PACK.table("items") if i["type"] == "mcq" and (i.get("review") or {}).get("status")
               == "published")  # fmt: skip
    kc = mcq["kc_ids"][0]
    patch = pytest.MonkeyPatch()
    patch.setattr(socket.socket, "connect", offline)
    try:
        practice = assessments.create_practice("physics", [kc], 1)
        item = practice["current_item"]
        record = PACK.record("items", item["item_id"]) or {}
        right = next(o["id"] for o in record["parts"][0]["answer"]["options"] if o.get("correct"))
        answer = {"parts": [{"part_id": record["parts"][0]["id"], "kind": "mcq", "option_id": right}]}
        marked = asyncio.run(assessments.practice_answer(practice["set_id"], "cli_a", item["item_id"], answer, 20_000))
        assert marked["verdict"] == "correct"
        assert row(held.learner, item["kc_ids"][0] if "kc_ids" in item else kc)["succ_w"] > 0
        plan = desk.propose()
        assert plan["blocks"] and desk.decide(plan["plan_id"], "start")["status"] == "started"
        assert desk.progress()["subjects"][0]["subject"] == "physics"
    finally:
        patch.undo()
    assert attempts == []


# --- LRN-43: learner data stays local by default ----------------------------------------------------------------

# TABLE DAT-18a: the features that may carry a learning record, the data classes each may name, and the payload
# classes that carry it. Everything else stays on the device.
LEARNER_TRANSFERS = {
    "cloud_tier": ({"question_text", "board", "image", "learner_summary"}, {"cloud_prompt"}),
    "cloud_backup": ({"learner_summary", "progress_report"}, {"backup_snapshot"}),
    "multi_device": ({"progress_report"}, {"multi_device_segment"}),
    "parent_remote_view": ({"progress_report"}, {"parent_digest"}),
}
LEARNER_CLASSES = {"learner_summary", "progress_report"}


def lrn43_egress_allowlist() -> None:
    from agent_core.net.policy import EgressRefused, load_policy

    policy = load_policy()
    carriers = {f for f, entry in policy.features.items() if LEARNER_CLASSES & set(entry.data_classes)}
    assert carriers == set(LEARNER_TRANSFERS), carriers
    record_payloads = set().union(*(payloads for _, payloads in LEARNER_TRANSFERS.values()))
    for feature, entry in policy.features.items():
        if feature in LEARNER_TRANSFERS:
            classes, payloads = LEARNER_TRANSFERS[feature]
            assert set(entry.data_classes) <= classes, feature
            assert payloads <= set(entry.payload_classes), feature
            assert entry.consent == "profile", f"{feature}: needs the profile own consent (PRV-05)"
            assert entry.authenticated and entry.dpia_gate, feature
        else:
            assert not record_payloads & set(entry.payload_classes), f"{feature} may not carry a learning record"
    # Parent summaries exclude transcripts and notes (TCH-15).
    assert set(policy.features["parent_remote_view"].data_classes) == {"progress_report"}
    # Enabled, a transfer reaches only its own service with only its own payloads; off, nothing goes.
    for enabled in ([], ["cloud_tier"], ["cloud_tier", "telemetry", "crash_reports"]):
        resolved = policy.resolve("dev", enabled)
        for feature in resolved.features:
            host = policy.host(feature, "dev")
            for payload in sorted(record_payloads):
                allowed = feature in enabled and payload in LEARNER_TRANSFERS.get(feature, (set(), set()))[1]
                try:
                    resolved.check(feature, f"https://{host}/v1/x", payload)
                    sent = True
                except EgressRefused:
                    sent = False
                assert sent == allowed, (enabled, feature, payload)
    # The S4 transfers are refused outright in this build: their stage has not shipped.
    with pytest.raises(EgressRefused, match="stage_not_shipped"):
        policy.resolve("dev", ["cloud_backup"]).check("cloud_backup", "https://backup.dev.jana.invalid/v1/x",
                                                       "backup_snapshot")  # fmt: skip
