"""M15.b: FSRS review scheduling and the verdict-to-rating table (LRN-13, LRN-14). Review histories are synthetic."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta

import pytest
from agent_core.learner import model
from agent_core.learner.fsrs import Card, Reviewed, exam_capped_due, replay, review_rating, scheduler_of
from agent_core.learner.mastery import DAY_MS, MasteryParams
from agent_core.store.ids import new_ulid
from learner_harness import Clock, make_learner
from m15_harness import SETTINGS, Practice, card, physics, row

P = MasteryParams()
SCHEDULER = scheduler_of(P)
RATINGS = ("again", "hard", "good", "easy")


def review_corpus(seed: int, histories: int = 200) -> list[list[tuple[int, str]]]:
    """Synthetic review histories: one review per day at most, gaps of a day to several months."""
    rng = random.Random(seed)
    start = 1_760_000_000_000
    out = []
    for _ in range(histories):
        t, reviews = start + rng.randint(0, 50) * DAY_MS, []
        for _ in range(rng.randint(1, 12)):
            reviews.append((t, rng.choice(RATINGS)))
            t += rng.choice((1, 2, 3, 7, 14, 30, 90, 200)) * DAY_MS + rng.randint(0, 3_600_000)
        out.append(reviews)
    return out


def lrn13_matches_py_fsrs() -> None:
    """Our scheduler against py-fsrs 6.3.2 (the test-only `conformance` group) on a seeded review corpus."""
    import fsrs

    reference = fsrs.Scheduler(parameters=P.fsrs_weights, desired_retention=P.fsrs_desired_retention,
                               learning_steps=(), relearning_steps=(), maximum_interval=P.fsrs_maximum_interval_days,
                               enable_fuzzing=False)  # fmt: skip
    names = {"again": fsrs.Rating.Again, "hard": fsrs.Rating.Hard, "good": fsrs.Rating.Good, "easy": fsrs.Rating.Easy}
    for history in review_corpus(13):
        theirs = fsrs.Card()
        for at, rating in history:
            theirs, _ = reference.review_card(theirs, names[rating], datetime.fromtimestamp(at / 1000, UTC))
        ours = replay(SCHEDULER, history)
        assert ours is not None
        assert ours.due_ms == int(theirs.due.timestamp() * 1000), history
        assert ours.stability == pytest.approx(theirs.stability, rel=1e-9)
        assert ours.difficulty == pytest.approx(theirs.difficulty, rel=1e-9)


def test_scheduler_shape_without_py_fsrs() -> None:
    """The FSRS-6 shape the conformance test pins, checked without the library: a new card's first interval grows with
    the rating, recall at the scheduled interval is the desired retention, and a lapse shortens the next interval."""
    first = {r: SCHEDULER.review(None, r, 0) for r in RATINGS}
    intervals = [first[r].due_ms // DAY_MS for r in RATINGS]
    assert intervals == sorted(intervals) and intervals[0] >= 1
    good = first["good"]
    assert SCHEDULER.retrievability_after(SCHEDULER.next_interval(good.stability), good.stability) == pytest.approx(
        P.fsrs_desired_retention, abs=0.02
    )
    later = good.due_ms
    recalled, lapsed = SCHEDULER.review(good, "good", later), SCHEDULER.review(good, "again", later)
    assert lapsed.due_ms - later < recalled.due_ms - later and lapsed.lapses == 1 and recalled.lapses == 0
    assert all(1 <= c.difficulty <= 10 for c in first.values())


def lrn13_exam_window_cap() -> None:
    window = SETTINGS.fsrs_exam_window_days
    rng = random.Random(5)
    for _ in range(2000):
        last = rng.randint(0, 400) * DAY_MS
        built = Card("review", rng.uniform(0.5, 400), rng.uniform(1, 10), last + rng.randint(1, 400) * DAY_MS, 3, 0,
                     last)  # fmt: skip
        exam = last + rng.randint(2, 300) * DAY_MS
        due = exam_capped_due(built, exam, window)
        assert due <= exam, "no interval ends after the exam"
        if built.due_ms > exam:
            assert exam - window * DAY_MS <= due or due == built.last_review_ms + DAY_MS, "inside the final window"
    # End to end: a mastered KC whose card falls due after the exam is due inside the final 14 days, and is offered
    # in the final window's warm-up.
    held, practice, desk = physics()
    kc = "kc.phy.o.motion.average_speed"
    for gap in (1, 3, 7, 15):
        practice.opportunity(kc, ("correct",), time_ms=10_000)
        practice.day(gap)
    for item in (1, 2, 3):
        state = "passed" if item == 3 else "in_progress"
        held.learner.record(
            "mastery_check",
            {"kc_id": kc, "item_index": item, "attempt_id": new_ulid(), "item_result": "pass", "check_state": state},
            source="checker",
        )
    assert model.kc_views(held.conn, P, held.clock.now)[kc].state == "mastered"
    stored = model.cards(held.conn)[kc]
    exam_day = (stored.due_ms // DAY_MS) - 3  # the exam comes before the card's own due date
    assert exam_day * DAY_MS > held.clock.now
    held.conn.execute("UPDATE profile SET exam_date = ?", (str(date(1970, 1, 1) + timedelta(days=exam_day)),))
    exams = desk.exam_days()
    exam = exams["physics"]
    assert stored.due_ms > exam
    capped = exam_capped_due(stored, exam, window)
    assert exam - window * DAY_MS <= capped <= exam
    in_window = [d.kc_id for d in model.due_cards(held.conn, P, exam - DAY_MS, exams, window)]
    assert kc in in_window, "due at least once in the final window"
    held.clock.now = exam - 2 * DAY_MS
    warmup = next(b for b in desk.propose()["blocks"] if b["kind"] == "warmup")
    assert kc in warmup["kc_ids"]


def lrn13_one_review_per_day() -> None:
    clock = Clock(1_760_000_000_000 - 1_760_000_000_000 % DAY_MS + 8 * 3_600_000)  # 08:00 UTC
    learner = make_learner(clock=clock)
    practice = Practice(learner, clock)
    kc = "kc.mth.o.algebra.rearrange_linear"
    practice.opportunity(kc, ("correct",))
    first = card(learner, kc)
    assert first is not None and first["reps"] == 1, "a KC entering learning gets its card"
    practice.opportunity(kc, ("incorrect",))
    practice.opportunity(kc, ("correct",), rung=2)
    assert card(learner, kc) == first, "same-day repeats leave the card unchanged"
    assert row(learner, kc)["attempts"] == 3, "they still count as mastery evidence"
    practice.day(1)
    practice.opportunity(kc, ("incorrect",))
    second = card(learner, kc)
    assert second is not None and second["reps"] == 2 and second["last_review_at"] != first["last_review_at"]
    checksum = learner.projector.checksum("kc_mastery")
    learner.projector.rebuild(["kc_mastery"])
    assert learner.projector.checksum("kc_mastery") == checksum


def lrn14_rating_table() -> None:
    s = SETTINGS
    median = 40_000

    def rate(**kw: object) -> str:
        reviewed = Reviewed(**{"outcomes": ("correct",), "max_rung": 0, "time_ms": 30_000, "median_ms": median,
                               "p_mastery": 0.5, **kw})  # type: ignore[arg-type]  # fmt: skip
        return review_rating(reviewed, s.rating_easy_time_share, s.rating_easy_min_mastery, s.rating_hard_time_multiple)

    rows = {
        "again": [{"outcomes": ("incorrect",)}, {"outcomes": ("incorrect", "incorrect")},
                  {"outcomes": ("incorrect", "correct"), "max_rung": 5}, {"max_rung": 5},
                  {"outcomes": ("incorrect",), "close": "abandoned"}, {"outcomes": (), "close": "not_learned"}],
        "hard": [{"max_rung": 1}, {"max_rung": 4}, {"outcomes": ("incorrect", "correct")},
                 {"outcomes": ("partial", "correct")}, {"time_ms": 3 * median + 1}, {"outcomes": ("partial",)}],
        "good": [{}, {"time_ms": 3 * median}, {"time_ms": int(0.4 * median), "p_mastery": 0.89}],
        "easy": [{"time_ms": int(0.4 * median), "p_mastery": 0.9}, {"time_ms": 1_000, "p_mastery": 0.99}],
    }  # fmt: skip
    for expected, fixtures in rows.items():
        for fixture in fixtures:
            assert rate(**fixture) == expected, (expected, fixture)
    # The projection rates the day's first reviewable opportunity by the same table.
    clock = Clock()
    learner = make_learner(clock=clock)
    practice = Practice(learner, clock)
    practice.opportunity("kc.mth.o.algebra.rearrange_linear", ("incorrect", "correct"), rung=2)
    hard = card(learner, "kc.mth.o.algebra.rearrange_linear")
    assert hard is not None
    expected = SCHEDULER.review(None, "hard", hard["last_review_at"])
    assert (hard["stability"], hard["difficulty"], hard["due_at"]) == (expected.stability, expected.difficulty,
                                                                      expected.due_ms)  # fmt: skip
    assert timedelta(milliseconds=hard["due_at"] - hard["last_review_at"]).days >= 1
