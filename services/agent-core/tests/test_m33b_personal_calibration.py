"""LRN-12: per-student calibration on the device, offline: a learning-rate multiplier on gamma_k with shrinkage
toward 1.0 and personal FSRS weights, each adopted only when it predicts the student's most recent 20% of events at
least 2% better.

Synthetic students only, drawn from seeded models: no real learner's events exist to fit yet."""

from __future__ import annotations

import random
from dataclasses import replace

from agent_core.config import Settings
from agent_core.learner.fsrs import DAY_MS, scheduler_of
from agent_core.learner.mastery import Ability, KcEvidence, MasteryParams, item_probability, observe
from agent_core.learner.personal import Graded, Review, fit_fsrs, fit_learning_rate, personal_fits, scaled

PARAMS = MasteryParams.from_settings(Settings())
KCS = [f"kc.mth.o.number.skill_{n}" for n in range(50)]


def learner(true_multiplier: float, n: int, seed: int) -> list[Graded]:
    """A student who learns as pfa_elo does with gamma times `true_multiplier`, on a seeded run of practice."""
    rng = random.Random(seed)
    truth = scaled(PARAMS, true_multiplier)
    ability, evidence = Ability(), {}  # type: ignore[var-annotated]
    rows = []
    for k in range(n):
        weights = {rng.choice(KCS): 1.0}
        t = 1_800_000_000_000 + k * DAY_MS // 2
        b = rng.uniform(0.0, 2.5)
        for kc in weights:
            evidence.setdefault(kc, KcEvidence()).decay_to(t, truth)
        correct = rng.random() < item_probability(ability.theta, weights, evidence, truth, b)
        observe(y=int(correct), w=1.0, t=t, weights=weights, first_error_kc=None, ability=ability, evidence=evidence,
                p=truth, b_item=b)  # fmt: skip
        rows.append(Graded(weights, correct, t, b))
    return rows


def test_lrn12_rate_needs_enough_observations():
    """Below 200 observations in a subject nothing is fitted and the defaults remain."""
    fit = fit_learning_rate(learner(3.0, 199, 1), PARAMS)
    assert fit.value is None and fit.adopted is False and fit.reason == "too_few_observations"


def test_lrn12_fast_learner_rate_adopted():
    """A student who learns three times as fast as the default gets a multiplier above 1, adopted because it predicts
    their most recent 20% of opportunities better."""
    for seed in (2, 3, 4):
        fit = fit_learning_rate(learner(3.0, 400, seed), PARAMS)
        assert fit.value is not None and fit.value > 1.5
        assert fit.adopted is True and fit.personal_loss < fit.default_loss * 0.98


def test_lrn12_default_learner_keeps_defaults():
    """A student who learns at the default rate is shrunk toward 1.0 and gains nothing worth adopting."""
    for seed in (1, 2, 3, 4):
        fit = fit_learning_rate(learner(1.0, 400, seed), PARAMS)
        assert fit.value is not None and 0.5 < fit.value < 2.0
        assert fit.adopted is False and fit.reason == "no_gain"


def reviewer(growth: float, kcs: int, per_kc: int, seed: int) -> list[Review]:
    """A student whose memory follows FSRS with the stability growth weight (w8) and the initial stabilities (w0-w3)
    times `growth`, reviewed at a seeded spread of intervals, interleaved in time across KCs."""
    rng = random.Random(seed)
    base = scheduler_of(PARAMS)
    truth = replace(base, weights=tuple(w * growth if i in (0, 1, 2, 3, 8) else w for i, w in enumerate(base.weights)))
    reviews = []
    for k in range(kcs):
        card, t = None, 1_800_000_000_000 + k * 3_600_000
        for _ in range(per_kc):
            recalled = card is None or rng.random() < truth.retrievability(card, t)
            rating = "good" if recalled else "again"
            reviews.append(Review(f"kc.mth.o.number.k{k}", t, rating))
            card = truth.review(card, rating, t)
            t += rng.choice((1, 2, 3, 5, 8, 13)) * DAY_MS
    return sorted(reviews, key=lambda r: r.t_ms)


def test_lrn12_fsrs_needs_enough_reviews():
    fit = fit_fsrs(reviewer(0.3, 39, 10, 4), PARAMS)
    assert fit.value is None and fit.reason == "too_few_reviews"


def test_lrn12_fsrs_personal_weights_adopted_only_with_gain():
    """A student who forgets much faster than the default weights predict gets personal weights; students who forget
    as the defaults predict keep them, whatever the seed."""
    for seed in (5, 6, 7):
        fast = fit_fsrs(reviewer(0.3, 100, 9, seed), PARAMS)
        assert fast.adopted is True and fast.personal_loss < fast.default_loss * 0.98
        assert fast.value is not None and fast.value != tuple(PARAMS.fsrs_weights)
        usual = fit_fsrs(reviewer(1.0, 100, 9, seed), PARAMS)
        assert usual.adopted is False and usual.reason == "no_gain"


def test_lrn12_adopted_fit_matches_the_proposed_event():
    """An adopted fit is what the proposed `personal_calibration` event carries (contract-additions-m33b.json, D72):
    the event is how the fold would apply it from the log once the contract adopts it."""
    import json
    from pathlib import Path

    from jsonschema import Draft202012Validator

    additions = json.loads((Path(__file__).parents[3] / "contract-additions-m33b.json").read_text())["additions"]
    events = json.loads((Path(__file__).parents[1] / "agent_core/contracts/schemas/learning/learning-event.schema.json")
                        .read_text())  # fmt: skip
    payload = next(a["value"] for a in additions if a["pointer"] == "/$defs/payload_personal_calibration")
    validator = Draft202012Validator({"$defs": events["$defs"], **payload})
    for fit in (fit_learning_rate(learner(3.0, 400, 2), PARAMS, subject="mathematics"),
                fit_fsrs(reviewer(0.3, 100, 9, 5), PARAMS)):  # fmt: skip
        assert fit.adopted
        body = {"kind": fit.kind, "subject": fit.subject, "value": list(fit.value) if isinstance(fit.value, tuple)
                else fit.value, "events": fit.events, "default_log_loss": fit.default_loss,
                "personal_log_loss": fit.personal_loss}  # fmt: skip
        assert list(validator.iter_errors(body)) == []


def test_lrn12_fits_read_the_learner_database(tmp_path):
    """The fits read the attempts projection of the student's own database and write nothing to it."""
    from test_cur36_remark_readers import OTHER_ITEM, RIGHT_OLD
    from test_m24_remark import OLD, OTHER, Clock, index, make_desk
    from test_m33b_research_rows import answered

    clock = Clock()
    desk = make_desk(tmp_path, "learner", index(RIGHT_OLD, OTHER_ITEM), clock)
    answered(desk, clock, "1" * 26, [(OLD, "a"), (OTHER, "c")] * 3, 0)  # six opportunities over two days
    before = desk.learner.conn.total_changes
    fits = personal_fits(desk.learner.conn, PARAMS, lambda item: 0.0)
    assert [(f.kind, f.subject, f.events, f.adopted) for f in fits] == [
        ("learning_rate", "mathematics", 6, False), ("fsrs", None, 2, False)]  # fmt: skip
    assert desk.learner.conn.total_changes == before
    desk.learner.conn.close()
