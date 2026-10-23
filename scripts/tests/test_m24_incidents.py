"""OPS-21/26..38: synthetic records validate workflow, not completed staff drills."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from jana_tools.release import hotfix
from jana_tools.release import incidents as inc

NOW = datetime(2026, 10, 16, 20, tzinfo=UTC)
HASH = "a" * 64


def incident():
    return inc.Incident("inc_synthetic", "SEV1", "commander", "comms", NOW, "child_safety")


def test_policy_ops21_after_hours_page_drill():
    page = inc.Page("SEV1", NOW, NOW + timedelta(minutes=10), "operator", HASH)
    assert not inc.page_errors(page)
    assert inc.page_errors(replace(page, acknowledged_at=NOW + timedelta(hours=2)))
    assert inc.page_errors(replace(page, signal="ordinary_warning"))


def ops26_sla_reported_weekly():
    # School timezone dates, explicit non-school days, and no overnight/weekend support-hour charging.
    calendar = inc.SchoolCalendar("Africa/Lagos", frozenset())
    start = datetime(2026, 10, 16, 15, tzinfo=UTC)  # Friday 16:00 local
    end = datetime(2026, 10, 19, 8, tzinfo=UTC)  # Monday 09:00 local
    assert calendar.support_hours(start, end) == 2
    ticket = inc.SupportTicket("ticket_synthetic", "P1", start, end, end)
    report = inc.sla_report([ticket], calendar, end)
    assert report["tickets"] == 1 and report["response_met"] == 1
    assert inc.sla_report([replace(ticket, responded_at=None)], calendar, end)["response_met"] == 0


def ops30_incident_record_fields():
    record = incident()
    assert inc.incident_errors(record)  # acknowledgment and timeline are mandatory before containment
    with pytest.raises(ValueError):
        inc.transition(record, "contained", NOW, "operator")
    record = inc.acknowledge(record, NOW + timedelta(minutes=10), "commander")
    record = inc.transition(record, "contained", NOW + timedelta(hours=1), "commander")
    assert not inc.incident_errors(record)
    with pytest.raises(ValueError):
        inc.transition(record, "reviewed", NOW + timedelta(hours=2), "commander")


def test_policy_ops31_child_safety_tabletop():
    record = inc.acknowledge(incident(), NOW + timedelta(minutes=10), "commander")
    record = inc.transition(record, "contained", NOW + timedelta(minutes=30), "commander")
    tabletop = inc.Tabletop(
        record.incident_id,
        "safety_lead",
        NOW + timedelta(minutes=20),
        True,
        True,
        True,
        True,
        HASH,
        frozenset({"safety_lead", "commander"}),
    )
    assert not inc.tabletop_errors(record, tabletop)
    assert inc.tabletop_errors(record, replace(tabletop, no_student_contact=False))
    assert inc.tabletop_errors(record, replace(tabletop, handed_off_at=NOW + timedelta(hours=2)))


def test_policy_ops32_schools_notified():
    record = inc.transition(inc.acknowledge(incident(), NOW, "commander"), "contained", NOW, "commander")
    receipt = inc.Notification(
        "lic_one",
        "registered_contact",
        "phone",
        NOW + timedelta(hours=1),
        NOW + timedelta(hours=2),
        "kit_synthetic",
        "USB instructions",
        HASH,
    )
    assert not inc.notification_errors(record, {"lic_one"}, [receipt])
    assert inc.notification_errors(record, {"lic_one", "lic_offline"}, [receipt])
    assert inc.notification_errors(record, {"lic_one"}, [replace(receipt, route="student")])


def ops33_review_required_to_close():
    record = inc.acknowledge(incident(), NOW, "commander")
    record = inc.transition(record, "contained", NOW, "commander")
    record = inc.transition(record, "resolved", NOW + timedelta(hours=1), "commander")
    with pytest.raises(ValueError):
        inc.transition(record, "reviewed", NOW + timedelta(hours=2), "commander")
    review = inc.Review(
        "summary",
        "aggregate impact",
        ("timeline",),
        "cause",
        "detection gap",
        (inc.Action("repair", "owner", NOW + timedelta(days=1)),),
        ("ops30_regression",),
        HASH,
    )
    assert inc.transition(record, "reviewed", NOW + timedelta(hours=2), "commander", review=review).state == "reviewed"
    with pytest.raises(ValueError):
        inc.transition(record, "reviewed", NOW + timedelta(days=30), "commander", review=review)


def test_policy_ops34_drills_current():
    catalogue = inc.required_drills("S2")
    drills = [
        inc.Drill(name, "owner", NOW, True, HASH, "trigger", ("step",), "verify", "rollback", "USB", ())
        for name in catalogue
    ]
    assert not inc.drill_errors("S2", NOW, drills, term_start=NOW, release_at=NOW)
    assert inc.drill_errors("S2", NOW + timedelta(days=400), drills, term_start=NOW, release_at=NOW)
    assert inc.drill_errors("S2", NOW, drills[:-1], term_start=NOW, release_at=NOW)
    assert inc.drill_errors("S2", NOW, [replace(d, passed=False) for d in drills], term_start=NOW, release_at=NOW)


def ops38_weekly_record_complete():
    metrics = {name: {"value": None, "reason": "not launched"} for name in inc.WEEKLY_AREAS}
    record = inc.Weekly(
        NOW - timedelta(days=7),
        NOW,
        frozenset({"safety", "support"}),
        metrics,
        ("reliability first",),
        (inc.Action("repair", "owner", NOW + timedelta(days=1)),),
    )
    assert not inc.weekly_errors(record, cloud_live=False)
    assert inc.weekly_errors(record, cloud_live=True)
    assert inc.weekly_errors(replace(record, metrics={}), cloud_live=False)
    metrics["incidents"] = {"value": None}
    assert inc.weekly_errors(record, cloud_live=False)


def test_policy_ops27_wrong_key_hotfix_flow(tmp_path: Path):
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "wrong_key", "itm.synthetic.old", NOW, {"1.0.0", "1.1.0"})
    assert flow.errors(case)
    flow.record_intake(case, NOW, NOW, inc.SchoolCalendar("UTC", frozenset()))
    flow.withdraw(case, NOW + timedelta(hours=1), "safety_entry_1")
    with pytest.raises(ValueError):
        flow.correct(case, "itm.synthetic.old", "1.0.1", {"1.0.0", "1.1.0"}, HASH, NOW + timedelta(days=1))
    flow.correct(case, "itm.synthetic.new", "1.0.1", {"1.0.0", "1.1.0"}, HASH, NOW + timedelta(days=1))
    flow.remarked(case, "replay_job_1", HASH, NOW + timedelta(days=1))
    flow.notified(case, {"lic_synthetic"}, "change summary", NOW + timedelta(days=1))
    assert not flow.errors(case, schools={"lic_synthetic"})
    assert hotfix.HotfixStore(tmp_path).get(case)["old_id"] == "itm.synthetic.old"


def ops28_fix_reaches_supported_versions(tmp_path: Path):
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "skill", "solve@2.0.0", NOW, {"1.0", "1.1"})
    flow.withdraw(case, NOW, "entry_1")
    with pytest.raises(ValueError):
        flow.correct(case, "solve@2.0.1", "2.0.1", {"1.1"}, HASH, NOW)
    flow.correct(case, "solve@2.0.1", "2.0.1", {"1.0", "1.1"}, HASH, NOW)
    assert not flow.errors(case)


def test_policy_cur36_withdraw_and_remark(tmp_path: Path):
    # The execution port is deliberately separate from the owned learner/marker modules.
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "wrong_key", "itm.old", NOW, {"1.0.0"})
    flow.withdraw(case, NOW, "entry_1")
    flow.correct(case, "itm.new", "1.0.1", {"1.0.0"}, HASH, NOW)
    attempts = [{"attempt_id": "attempt_1", "item_id": "itm.old", "verdict": "incorrect"}]
    seen = []
    result = flow.execute_remark(case, lambda old, new: seen.append((old, new)) or ("job", HASH), NOW)
    assert result == "job" and seen == [("itm.old", "itm.new")]
    assert attempts == [{"attempt_id": "attempt_1", "item_id": "itm.old", "verdict": "incorrect"}]
    assert flow.execute_remark(case, lambda *_: pytest.fail("must not replay twice"), NOW) == "job"


def cur36_withdrawn_item_never_served(tmp_path: Path):
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "wrong_key", "itm.old", NOW, {"1.0.0"})
    flow.withdraw(case, NOW, "entry_1")
    assert flow.select_items([{"id": "itm.old"}, {"id": "itm.other"}]) == [{"id": "itm.other"}]


def test_ops_weekly_rejects_unlisted_fields():
    metrics = {name: {"value": None, "reason": "not launched"} for name in inc.WEEKLY_AREAS}
    metrics["safety"]["student_name"] = "synthetic"
    record = inc.Weekly(
        NOW - timedelta(days=7),
        NOW,
        frozenset({"safety", "support"}),
        metrics,
        ("continue",),
        (inc.Action("repair", "owner", NOW),),
    )
    assert inc.weekly_errors(record, cloud_live=False)


def test_ops_child_tabletop_requires_containment():
    record = inc.acknowledge(incident(), NOW, "commander")
    drill = inc.Tabletop(
        record.incident_id, "safety_lead", NOW, True, True, True, True, HASH, frozenset({"safety_lead"})
    )
    assert inc.tabletop_errors(record, drill)


def test_ops_hotfix_can_notify_at_containment_before_patch(tmp_path: Path):
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "wrong_key", "itm.old", NOW, {"1.0.0"})
    flow.withdraw(case, NOW, "entry_1")
    flow.notified(case, {"lic_synthetic"}, "Contained; correction delivery is being arranged.", NOW)
    assert flow.get(case)["notified_at"] == NOW.isoformat()
    with pytest.raises(ValueError):
        flow.notified(case, {"lic_synthetic"}, "late", NOW + timedelta(days=2))


def test_ops_hotfix_triage_uses_school_calendar(tmp_path: Path):
    flow = hotfix.HotfixStore(tmp_path)
    case = flow.open("inc_synthetic", "wrong_key", "itm.old", NOW, {"1.0.0"})
    calendar = inc.SchoolCalendar("UTC", frozenset())
    with pytest.raises(ValueError):
        flow.record_intake(case, NOW - timedelta(days=2), NOW, calendar)
    flow.record_intake(case, NOW, NOW, calendar)
    assert flow.get(case)["triaged_at"] == NOW.isoformat()
