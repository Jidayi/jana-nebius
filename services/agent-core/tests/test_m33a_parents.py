"""M33.a: the weekly parent digest and the alerts (TCH-12, TCH-14, JRN-13), on a learner written through the real
learner service. Every learner, answer and timing here is synthetic test data."""

from __future__ import annotations

import json
from datetime import date
from functools import cache
from pathlib import Path
from typing import Any

from agent_core.contracts._validation import _registry
from agent_core.engine.parents import ParentDesk
from agent_core.engine.safety import wellbeing_alert_category
from agent_core.engine.tutor_flows import record_wellbeing_shown
from agent_core.learner.mastery import DAY_MS
from agent_core.store.ids import new_ulid
from jsonschema import Draft202012Validator
from m15_harness import SETTINGS, Practice, physics
from memory_harness import PROFILE_B, Store, store

HOUR = 3_600_000
MINUTE = 60_000
ADDITIONS = Path(__file__).resolve().parents[3] / "contract-additions-m33a.json"
SPEED = "kc.phy.o.motion.average_speed"
ATOM = "kc.phy.o.atom.atomic_structure"
SERIES = "kc.phy.o.circuits.series_circuits"
MONDAY, SUNDAY = "2026-10-19", "2026-10-25"  # the scripted week


@cache
def _proposed() -> dict[str, Any]:
    entries = json.loads(ADDITIONS.read_text())["additions"]
    return {e["pointer"].removeprefix("/$defs/"): e["value"] for e in entries if e["pointer"].startswith("/$defs/")}


def proposed_errors(name: str, value: Any) -> list[str]:
    """Problems with a reply against its proposed definition (contract-additions-m33a.json), until it is adopted."""
    schema = {"$defs": _proposed(), "$ref": f"#/$defs/{name}"}
    validator = Draft202012Validator(schema, registry=_registry())
    return sorted(f"{e.json_path}: {e.message}" for e in validator.iter_errors(value))


def desk_of(held: Store) -> ParentDesk:
    from memory_harness import PACK

    return ParentDesk(held.conn, held.learner.projector.ctx.params, PACK, SETTINGS, clock_ms=held.clock)


def passed(held: Store, kc: str) -> None:
    for item in (1, 2, 3):
        held.clock.now += MINUTE
        held.learner.record("mastery_check", {"kc_id": kc, "item_index": item, "attempt_id": new_ulid(held.clock.now),
                                              "item_result": "pass",
                                              "check_state": "passed" if item == 3 else "in_progress"},
                            source="checker")  # fmt: skip


def solution_view(held: Store) -> None:
    held.clock.now += MINUTE
    held.learner.record("integrity_signal", {"kind": "solution_view"}, source="engine")


def at(held: Store, day: int, hour: int) -> None:
    """The clock to a day of the scripted week (0 is the Monday) at an hour."""
    held.clock.now = _monday_ms() + day * DAY_MS + hour * HOUR


def _monday_ms() -> int:
    """Midnight UTC (the local day, offset 0) starting the scripted Monday."""
    from memory_harness import at_ms

    return at_ms(MONDAY) - 12 * HOUR


def scripted_week() -> tuple[Store, Practice, dict[str, Any]]:
    """Monday: 25 minutes, two steps (one to the bottom-out), a solution viewed. Wednesday: 40 minutes, a step with
    hints, the speed KC's mastery check passed. Nothing else that week. Returns what the script did, by hand."""
    held, practice, _ = physics(day=MONDAY)
    at(held, 0, 9)
    practice.start()
    practice.opportunity(SPEED, ("correct",), time_ms=6 * MINUTE)  # checked work enough for the streak (LRN-33)
    practice.opportunity(ATOM, ("incorrect", "correct"), rung=5, time_ms=3 * MINUTE)
    solution_view(held)
    practice.end(active_ms=25 * MINUTE)
    at(held, 2, 16)
    practice.start()
    practice.opportunity(SPEED, ("correct",), rung=2, time_ms=6 * MINUTE)
    practice.opportunity(SPEED, ("correct",), time_ms=6 * MINUTE)
    passed(held, SPEED)
    practice.end(active_ms=40 * MINUTE)
    script = {"minutes": {MONDAY: 25, "2026-10-21": 40}, "sessions": 2, "steps": 4, "bottom_outs": 1, "hinted": 2,
              "solutions": 1, "mastered": [SPEED]}  # fmt: skip
    return held, practice, script


def week_window(held: Store) -> tuple[int, int]:
    return _monday_ms(), _monday_ms() + 7 * DAY_MS


# --- TCH-12 --------------------------------------------------------------------------------------------------------


def tch12_digest_numbers_match():
    """Every number in the digest equals the projection value for that week."""
    held, _, _ = scripted_week()
    at(held, 6, 19)  # Sunday 19:00: the week's digest is due
    digest = desk_of(held).latest_digest()
    assert proposed_errors("ParentDigest", digest) == []
    start, end = week_window(held)
    conn = held.conn
    daily = dict(conn.execute("SELECT day, minutes_active FROM engagement_daily").fetchall())
    assert {d["day"]: d["minutes"] for d in digest["time_by_day"]} == {
        d["day"]: daily.get(d["day"], 0) for d in digest["time_by_day"]
    }
    for key, column in (("minutes_total", "minutes_active"), ("sessions", "sessions"),
                        ("solutions_viewed", "solutions_viewed")):  # fmt: skip
        query = f"SELECT sum({column}) FROM engagement_daily WHERE day BETWEEN ? AND ?"  # noqa: S608 - fixed columns
        assert digest[key] == conn.execute(query, (MONDAY, SUNDAY)).fetchone()[0], key
    steps = conn.execute(
        "SELECT max(max_rung), max(hints_used) FROM attempts WHERE occurred_at >= ? AND occurred_at < ?"
        " GROUP BY session_id, item_ref, step_id",
        (start, end),
    ).fetchall()
    assert digest["steps"] == len(steps)
    assert digest["bottom_out_hints"] == sum(1 for rung, _ in steps if rung >= 5)
    assert digest["steps_with_hints"] == sum(1 for _, hints in steps if hints > 0)
    last = conn.execute("SELECT streak_length FROM engagement_daily WHERE streak_length > 0 AND day <= ?"
                        " ORDER BY day DESC", (SUNDAY,)).fetchone()  # fmt: skip
    assert digest["streak_days"] > 0 and digest["streak_days"] == last[0]
    states = dict(conn.execute("SELECT kc_id, status FROM kc_mastery").fetchall())
    assert [k["kc_id"] for k in digest["mastered"]] == [kc for kc, s in states.items() if s == "mastered"]
    assert digest["exam"] == {"subject": "physics", "days": (date(2027, 6, 1) - date(2026, 10, 25)).days}
    assert digest["days_studied"] == 2 and digest["final"] is False


def tch12_digest_no_free_text():
    """The digest contains none of the seeded transcript or note strings, and no safety-flag detail."""
    held, _, _ = scripted_week()
    transcript = "my secret transcript canary about the bus to Kumasi"
    note = "note canary: prefers worked examples on Tuesdays"
    tutor = "tutor canary: let's use v equals d over t"
    sid = held.session("ses_" + new_ulid(held.clock.now))
    held.conn.execute("INSERT INTO turns (turn_id, session_id, idx, speaker, status, student_text, started_at) VALUES"
                      " ('msg_1', ?, 0, 'student', 'complete', ?, ?)", (sid, transcript, held.clock.now))  # fmt: skip
    held.conn.execute("INSERT INTO turns (turn_id, session_id, idx, speaker, status, started_at)"
                      " VALUES ('trn_1', ?, 1, 'tutor', 'complete', ?)", (sid, held.clock.now))  # fmt: skip
    held.conn.execute("INSERT INTO parts (part_id, turn_id, idx, kind, status, content, created_at, updated_at)"
                      " VALUES ('prt_1', 'trn_1', 0, 'text', 'complete', ?, 0, 0)",
                      (json.dumps({"text": tutor}),))  # fmt: skip
    held.note(note, "ses_" + sid)
    held.learner.record("safety_flagged", {"category": "distress", "template_id": "tpl.distress_self_harm",
                                           "turn_id": "trn_1"}, source="engine", session_id=sid)  # fmt: skip
    record_wellbeing_shown(held.conn, "self_harm", held.clock.now)
    at(held, 6, 20)
    text = json.dumps(desk_of(held).latest_digest())
    for canary in (transcript, note, tutor, "canary", "distress", "self_harm", "tpl."):
        assert canary not in text


def test_tch12_digest_due_sunday_evening_and_kept_once_over():
    """Due on Sunday at 18:00 local: before it, the previous week's; rebuilt until the week is over, then kept."""
    held, practice, _ = scripted_week()
    desk = desk_of(held)
    at(held, 6, 17)
    assert desk.latest_digest()["week_start"] == "2026-10-12"  # the week before: not due yet
    at(held, 6, 18)
    first = desk.latest_digest()
    assert first["week_start"] == MONDAY and first["final"] is False
    practice.start()  # Sunday evening study still counts while the week runs
    practice.end(active_ms=10 * MINUTE)
    at(held, 6, 23)
    assert desk.latest_digest()["minutes_total"] == first["minutes_total"] + 10
    at(held, 9, 12)  # Wednesday of the next week: the digest is kept as the week left it
    practice.start()
    practice.end(active_ms=30 * MINUTE)
    kept = desk.latest_digest()
    assert kept["week_start"] == MONDAY and kept["final"] is True and kept["minutes_total"] == 75
    assert desk.latest_digest() == kept
    assert held.conn.execute("SELECT count(*) FROM digests").fetchone()[0] == 2


def test_tch12_watch_list():
    """KCs to watch: learning for over two weeks, or moved on; a KC learning for a week is not one."""
    held, practice, _ = physics(day="2026-10-01")
    practice.opportunity(SERIES, ("incorrect",))
    practice.end()
    at(held, 0, 9)
    practice.opportunity(ATOM, ("incorrect",))
    practice.end()
    at(held, 6, 19)
    watch = desk_of(held).latest_digest()["to_watch"]
    assert [(w["kc_id"], w["reason"]) for w in watch] == [(SERIES, "learning_long")]
    assert watch[0]["topic_title"] and watch[0]["subject"] == "physics"


# --- JRN-13 --------------------------------------------------------------------------------------------------------


def jrn13_weekly_summary():
    """The summary of a scripted week matches the event log: each day's minutes, the sessions, the steps and their
    help, the solutions viewed, the idea secured and a marked mock."""
    held, _, script = scripted_week()
    exam_id = new_ulid(held.clock.now)
    held.conn.execute("INSERT INTO exams (exam_id, paper_ref, status, duration_ms, submitted_at) VALUES"
                      " (?, 'mck.phy.o.0001', 'marked', 3600000, ?)", (exam_id, held.clock.now))  # fmt: skip
    held.conn.executemany("INSERT INTO exam_answers (exam_id, item_ref, updated_at, marks_awarded, marks_available)"
                          " VALUES (?, ?, 0, ?, ?)", [(exam_id, "q1", 3, 4), (exam_id, "q2", 1, 2)])  # fmt: skip
    at(held, 6, 19)
    digest = desk_of(held).latest_digest()
    assert {d["day"]: d["minutes"] for d in digest["time_by_day"] if d["minutes"]} == script["minutes"]
    assert digest["minutes_total"] == sum(script["minutes"].values())
    assert digest["sessions"] == script["sessions"] and digest["activity"] == "enough"
    assert (digest["steps"], digest["bottom_out_hints"], digest["steps_with_hints"]) == (
        script["steps"], script["bottom_outs"], script["hinted"])  # fmt: skip
    assert digest["solutions_viewed"] == script["solutions"]
    assert [k["kc_id"] for k in digest["mastered"]] == script["mastered"]
    [mock] = digest["mocks"]
    assert mock["exam_id"] == "exm_" + exam_id and (mock["marks_awarded"], mock["marks_available"]) == (4, 6)
    assert mock["title"]  # the pack paper's own title


def jrn13_failure_branches():
    """F1: too little activity gives time studied only (`low`), an empty week `none`. F2: one summary per profile, with
    no other profile's data."""
    held, practice, _ = physics(day=MONDAY)
    at(held, 1, 10)
    practice.start()
    practice.end(active_ms=5 * MINUTE)
    at(held, 6, 19)
    low = desk_of(held).latest_digest()
    assert low["activity"] == "low" and low["minutes_total"] == 5
    other = store(PROFILE_B, day=MONDAY)
    at(other, 6, 19)
    empty = desk_of(other).latest_digest()
    assert empty["activity"] == "none" and empty["minutes_total"] == 0 and empty["sessions"] == 0
    assert other.conn.execute("SELECT count(*) FROM digests").fetchone()[0] == 1
    assert held.conn.execute("SELECT count(*) FROM digests").fetchone()[0] == 1


# --- TCH-14 --------------------------------------------------------------------------------------------------------


def test_tch14_alerts_from_projections_and_events():
    """Each kind of TABLE TCH-14a is raised by code once, newest first, kind and date only; dismissing puts one away."""
    held, practice, _ = scripted_week()
    desk = desk_of(held)
    at(held, 3, 9)
    for _ in range(5):  # Thursday: five more steps to the bottom-out (6 of the week's 10)
        practice.opportunity(ATOM, ("correct",), rung=5)
    practice.opportunity(SPEED, ("incorrect",))  # a miss after the speed KC's check: it needs review
    practice.end()
    exam_id = new_ulid(held.clock.now)
    held.conn.execute("INSERT INTO exams (exam_id, paper_ref, status, duration_ms, submitted_at) VALUES"
                      " (?, 'mck.phy.o.0001', 'submitted', 3600000, ?)", (exam_id, held.clock.now))  # fmt: skip
    record_wellbeing_shown(held.conn, "self_harm", held.clock.now)
    at(held, 11, 9)  # seven days and more since the last session
    listed = desk.alerts()
    assert proposed_errors("AlertList", {"alerts": listed}) == []
    kinds = [a["kind"] for a in listed]
    assert sorted(kinds) == ["bottom_out_heavy", "inactive", "mastery_drop", "mock_result", "wellbeing_message_shown"]
    assert [a["created_at"] for a in listed] == sorted((a["created_at"] for a in listed), reverse=True)
    drop = next(a for a in listed if a["kind"] == "mastery_drop")
    assert drop["kc_id"] == SPEED and drop["severity"] == "info"
    wellbeing = next(a for a in listed if a["kind"] == "wellbeing_message_shown")
    assert wellbeing == {**wellbeing, "severity": "urgent", "kc_id": None} and "category" not in wellbeing
    assert desk.alerts() == listed  # each trigger is written once
    assert desk.dismiss(drop["alert_id"]) and drop["alert_id"] not in [a["alert_id"] for a in desk.alerts()]
    assert desk.dismiss(drop["alert_id"])  # again: already put away
    assert not desk.dismiss("alr_" + new_ulid(held.clock.now))


def test_tch14_no_wellbeing_alert_for_abuse_or_unreadable():
    """The wellbeing alert is self-harm distress only, category only: an abuse disclosure or a line the guard could not
    read writes none (PRV-14, D104)."""
    assert wellbeing_alert_category("abuse") is None and wellbeing_alert_category("unclassified") is None
    assert wellbeing_alert_category("self_harm") == "self_harm"


def test_tch14_quiet_week_raises_nothing():
    """A profile never used raises no alert; a light week with the bottom-out once raises no bottom-out alert."""
    held, practice, _ = physics(day=MONDAY)
    assert desk_of(held).alerts() == []
    at(held, 0, 9)
    practice.opportunity(SPEED, ("correct",), rung=5)
    practice.end()
    assert desk_of(held).alerts() == []
