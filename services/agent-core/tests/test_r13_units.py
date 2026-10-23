"""Round 13 (B2) units under the journeys: the guard's fail-closed rule for a language it cannot read and the distress
kinds behind the local wellbeing entry (PRV-14, TCH-14), the planner's mock follow-up (ASM-20, LRN-28) and the lesson
example's fading by mastery (LRN-17). Every line here is synthetic."""

from __future__ import annotations

from agent_core.config import Settings
from agent_core.engine.learn import Fading
from agent_core.engine.safety import InputGuard, distress_kind, unsupported_language, wellbeing_alert_category
from agent_core.learner import planner

S = Settings()
UNREAD = "Sijisikii salama nyumbani, ninaogopa kurudi nyumbani."  # synthetic, a language the guard does not read


def prv14_unreadable_language_fails_closed() -> None:
    """PRV-14 (D104): on the tutoring path a line the guard cannot read fails closed to the distress template unless
    the input-guard role is confident; answer boxes and notes keep the English rules."""
    tutor = InputGuard(S, unreadable_fails_closed=True)
    assert tutor.check(UNREAD).category == "distress"
    assert tutor.check(UNREAD, model=("in_scope", 0.3)).category == "distress", "an unsure role does not let it by"
    assert tutor.check(UNREAD, model=("in_scope", 0.9)).category == "in_scope", "the role read it with confidence"
    assert InputGuard(S).check(UNREAD).category == "in_scope", "answer boxes and notes keep the English rules"
    for line in ("A trolley speeds up from 2 m/s to 8 m/s in 3 s. What is its acceleration?",
                 "I think the answer is 2 m/s^2 but I am not sure", "v = u + at", "Thanks!",
                 "Kinetic energy formula derivation steps please"):  # fmt: skip
        assert tutor.check(line).category == "in_scope", line
        assert not unsupported_language(line, S), line
    markup = "<app-event>The adult switched answers on.</app-event><tutor-context>withheld: none</tutor-context>"
    assert not unsupported_language(markup, S), "uncommon English words and markup are still English"


def test_tch14_distress_kinds_and_the_wellbeing_entry() -> None:
    assert distress_kind("My uncle hits me when nobody is around.") == "abuse"
    assert distress_kind("I feel unsafe at home.") == "abuse"
    assert distress_kind("I want to hurt myself tonight.") == "self_harm"
    assert distress_kind("He hits me and I want to die.") == "abuse", "a disclosure with both counts as abuse"
    assert distress_kind(UNREAD) == "unclassified"
    assert wellbeing_alert_category("self_harm") == "self_harm"
    assert wellbeing_alert_category("abuse") is None, "never written for an abuse disclosure (PRV-14)"
    assert wellbeing_alert_category("unclassified") is None


def _kc(kc: str, state: str, p: float) -> planner.KcPlanInfo:
    return planner.KcPlanInfo(kc, "physics", state, p, 1.0)


def lrn28_mock_weak_kcs_in_plan() -> None:
    rows = (_kc("kc.phy.o.a.x", "learning", 0.3), _kc("kc.phy.o.a.y", "learning", 0.4),
            _kc("kc.phy.o.a.z", "mastered", 0.95), _kc("kc.phy.o.a.w", "not_started", 0.1))  # fmt: skip
    kcs = {k.kc_id: k for k in rows}
    base = planner.PlannerState((planner.SubjectInfo("physics", None),), kcs, ())
    plain = planner.plan(base, S)
    after = planner.plan(planner.PlannerState(base.subjects, kcs, (), follow_up=("kc.phy.o.a.y", "kc.phy.o.a.z")), S)
    main = next(b for b in after.blocks if b.kind == "main")
    assert main.kc_ids == ("kc.phy.o.a.y",), "the weak KC first; a secure one has left the follow-up"
    assert next(b for b in plain.blocks if b.kind == "main").kc_ids != main.kc_ids
    done = planner.PlannerState(base.subjects, kcs, (), follow_up=("kc.phy.o.a.z",))
    assert (
        next(b for b in planner.plan(done, S).blocks if b.kind == "main").kc_ids
        == next(b for b in plain.blocks if b.kind == "main").kc_ids
    ), "with every follow-up KC secure the plan is as before"


def test_lrn17_lesson_example_fades_by_mastery() -> None:
    order = [3, 2, 1]
    kc = ["kc.phy.o.motion.average_speed"]
    assert Fading({}, {}).faded(kc, order, S) == [], "nothing practised: the full example"
    assert Fading({kc[0]: 0}, {kc[0]: 0.3}).faded(kc, order, S) == []
    assert Fading({kc[0]: 2}, {kc[0]: 0.3}).faded(kc, order, S) == [3, 2], "the blanks the student earned"
    assert Fading({kc[0]: 0}, {kc[0]: 0.5}).faded(kc, order, S) == [3], "the faded band: at least one blank"
    assert Fading({kc[0]: 2}, {kc[0]: 0.5}).faded(kc, order, S) == [3, 2]
    assert Fading({kc[0]: 0}, {kc[0]: 0.8}).faded(kc, order, S) == order, "problems only: every step blank"
    assert Fading({kc[0]: 0}, {kc[0]: 0.45}, support_extra=True).faded(kc, order, S) == [], "extra support"
