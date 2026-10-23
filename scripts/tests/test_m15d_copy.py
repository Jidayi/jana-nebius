"""LRN-35: the copy linter rejects dark patterns in every locale file. The seeded phrases below are written for this
test; none is product copy."""

from __future__ import annotations

import json

from jana_tools.copy_lint import RULES, copy_lint_errors, locale_files, violations

SEEDED = {
    "loss_framed_streak": ("home.streak_warning", "Don't lose your 12-day streak!"),
    "countdown_pressure": ("practice.nudge", "Hurry, time is running out on today's practice."),
    "random_reward": ("lesson.done", "Open your mystery reward!"),
    "leaderboard": ("progress.compare", "See where you are on the class leaderboard."),
    "guilt": ("home.welcome_back", "We missed you yesterday."),
    "purchase_in_learning": ("tutor.limit", "Upgrade to keep going with this question."),
    "infinite_feed": ("practice.more", "Endless questions, keep scrolling."),
    "fake_scarcity": ("home.offer", "Last chance: this plan expires today."),
    "praise_of_person": ("card.right", "You're so smart!"),
}


def lrn35_copy_linter() -> None:
    assert locale_files(), "the locale catalogues are found"
    assert copy_lint_errors() == [], copy_lint_errors()[:5]
    assert {rule.name for rule in RULES} == set(SEEDED)
    for rule, (key, text) in SEEDED.items():
        found = violations({key: text}, "seeded")
        assert any(f": {rule} (" in line for line in found), (rule, found)
    # Scope: a countdown is the point of a mock sitting; Settings names the subscription plainly.
    assert violations({"mock.timer": "Hurry: 5 minutes left."}) == []
    assert violations({"settings.online.cloud.off": "Off. Upgrade to the cloud tutor in Settings."}) == []
    assert violations({"tutor.cloud": "Upgrade to the cloud tutor."}) != []
    # Neutral wording passes: work praised, a new streak started, an estimate given.
    neutral = {"home.streak_new": "New streak: day 1", "card.right": "That step is right: you divided both sides.",
               "home.plan": "Next up (about 20 min)", "home.freeze": "A freeze kept your streak."}  # fmt: skip
    assert violations(neutral) == []
    # The core's own plan-card copy keeps to the same rules.
    from agent_core.engine.plans import KIND_TEXT

    core_copy = {f"plan.{kind}": text for kind, text in KIND_TEXT.items()}
    core_copy.update({"plan.title": "Next up", "plan.keep_learning": "Keep learning"})
    assert violations(core_copy) == []
    assert json.dumps(sorted(core_copy))
