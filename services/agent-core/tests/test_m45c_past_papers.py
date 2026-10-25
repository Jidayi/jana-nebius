"""M45.c: imported past papers marked honestly, and exam dates that count down into the plan (ASM-27, LRN-44; D119).

Every paper, mark scheme, answer, learner and date here is synthetic test content in our own words, never a board's.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import replace
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import validator
from agent_core.engine.assessment.past_papers import matches_precision, numeric_key, parse_paper, parse_scheme
from agent_core.engine.assessment.service import AssessmentDesk, Refused
from agent_core.engine.exam_dates import ExamDateRefused
from agent_core.engine.plans import PlanDesk
from agent_core.learner import planner
from agent_core.learner.mastery import DAY_MS, MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database
from learner_harness import learner_db
from m15_harness import Practice
from memory_harness import PACK_DIR, at_ms
from pack_builder.build import load_source

S = Settings()
REPO = Path(__file__).resolve().parents[3]
SPEED = "kc.phy.o.motion.average_speed"
DENSITY = "kc.phy.o.matter.density"
SOURCE = {"source_id": "src_" + "0" * 26, "revision": 1}
SCHEME = {"source_id": "src_" + "1" * 26, "revision": 1}

PAPER = """PHYSICS PAPER 2 (practice)
Answer all questions. Electronic calculators may be used.
1 A cyclist rides 120 m along a straight road in 8.0 s. Calculate her average speed.   [2]
2 Which of these is a vector quantity?
A mass
B speed
C velocity
D energy
3 (a) State what is meant by density.   [1]
(b) Fig. 3.1 shows a block of mass 600 g and volume 200 cm3. Calculate the density of the block.   [2]
"""

MARK_SCHEME = """Mark scheme
1 15 m/s M1 120 / 8.0 A1 15
2 C
3(a) mass per unit volume B1
3(b) 3.0 g/cm3 [2]
"""


def chunks(text: str, page: int = 1) -> list[dict[str, Any]]:
    return [{"text": text, "locator": {"kind": "page", "page": page}}]


class Clock:
    def __init__(self) -> None:
        self.wall = 1_800_000_000_000
        self.active = 0

    def advance(self, ms: int) -> None:
        self.wall += ms
        self.active += ms


def pack() -> PackIndex:
    kcs = [
        {"id": SPEED, "statement": "Average speed", "node_id": "cur.phy.o.motion.average_speed", "code": "speed",
         "status": "active", "prerequisites": [], "misconception_ids": []},
        {"id": DENSITY, "statement": "Density", "node_id": "cur.phy.o.matter.density", "code": "density",
         "status": "active", "prerequisites": [], "misconception_ids": []},
    ]  # fmt: skip
    nodes = [
        {"id": "cur.phy.o", "title": "Physics", "kind": "subject"},
        {"id": "cur.phy.o.motion", "title": "Motion", "kind": "topic", "parent_id": "cur.phy.o"},
        {"id": "cur.phy.o.motion.average_speed", "title": "Average speed", "kind": "subtopic",
         "parent_id": "cur.phy.o.motion"},
        {"id": "cur.phy.o.matter", "title": "Matter", "kind": "topic", "parent_id": "cur.phy.o"},
        {"id": "cur.phy.o.matter.density", "title": "Density", "kind": "subtopic", "parent_id": "cur.phy.o.matter"},
    ]  # fmt: skip
    tables = {"items": [], "mock_papers": [], "kcs": kcs, "curriculum_nodes": nodes, "misconceptions": []}
    return PackIndex.from_tables([({"pack_id": "pack.phy.o", "version": "1.0.0", "subject": "phy"}, tables)])


async def tool(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """A deterministic stand-in for the maths worker: decimal equality, with a check id like the real one."""
    TOOL_CALLS.append(name)
    if name == "math_check_equivalence":
        try:
            same = Decimal(str(args["a"])) == Decimal(str(args["b"]))
        except ArithmeticError:
            return {"verdict": "unknown"}, None
        return {"verdict": "equivalent" if same else "not_equivalent"}, f"chk_{len(TOOL_CALLS):04d}"
    return None, None


async def judge(rule: dict[str, Any], working: list[str]) -> bool | None:
    """A stand-in local judge: passes a point whose words appear in the answer."""
    JUDGED.append(rule["criterion_id"])
    said = " ".join(working).lower()
    return all(word in said for word in str(rule.get("pass_if", "")).lower().split()[:2])


TOOL_CALLS: list[str] = []
JUDGED: list[str] = []


@pytest.fixture
def desk(tmp_path: Path):
    TOOL_CALLS.clear()
    JUDGED.clear()
    clock = Clock()
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    index = pack()
    learner = Learner.open(conn, profile_id="0" * 26, device_id="f" * 32, wall_ms=lambda: clock.wall,
                           max_skew_ms=S.sync_clock_skew_max_ms, params=MasteryParams.from_settings(S),
                           content=index)  # fmt: skip
    value = AssessmentDesk(learner, index, S, clock_ms=lambda: clock.wall, monotonic_ms=lambda: clock.active,
                           run_tool=tool, judge_method=judge)  # fmt: skip
    yield value, clock
    conn.close()


def imported(d: AssessmentDesk, scheme: str | None = MARK_SCHEME) -> dict[str, Any]:
    body = {
        "client_import_id": "cli_" + "0" * 26,
        "title": "Physics paper 2 (practice)",
        "subject": "physics",
        "duration_minutes": 60,
        "paper": SOURCE,
        "mark_scheme": SCHEME if scheme else None,
        "syllabus": None,
    }
    return d.import_past_paper(body, chunks(PAPER), chunks(scheme) if scheme else None)


def valid(definition: str, body: Any) -> None:
    problems = [f"{list(e.absolute_path)}: {e.message}" for e in validator(definition).iter_errors(body)]
    assert problems == [], problems[:3]


def evidence(d: AssessmentDesk) -> tuple[int, list[Any]]:
    events = d.learner.conn.execute(
        "SELECT count(*) FROM events WHERE type IN ('attempt','verdict','misconception_evidence','item_exposure')"
    ).fetchone()[0]
    return events, d.learner.conn.execute("SELECT * FROM kc_mastery ORDER BY kc_id").fetchall()


def number(value: str, unit: str | None, part: str = "p1") -> dict[str, Any]:
    return {"part_id": part, "kind": "numeric", "value": value, "unit": unit}


def test_asm27_past_paper_marked_honestly(desk) -> None:
    d, clock = desk
    paper = imported(d)
    valid("api/commands#/$defs/PastPaperView", paper)
    assert paper["has_mark_scheme"] and paper["calculator"] and paper["linked"]
    labels = [(q["number_label"], q["marks"], q["marking"]) for q in paper["questions_found"]]
    assert labels == [("1", 2, "checked"), ("2", 1, "key"), ("3(a)", 1, "judged"), ("3(b)", 2, "checked")]
    before = evidence(d)

    exam = d.create_mock(paper["paper_id"])
    valid("api/commands#/$defs/MockExam", exam)
    eid = exam["exam_id"]
    shown = json.dumps(exam)
    # Questions as written, with their numbering and diagrams; the keys never reach the student's view.
    assert "Calculate her average speed" in shown and exam["questions"][2]["number_label"] == "3"
    assert exam["questions"][2]["parts"][0]["prompt"].startswith("(a) State what is meant by density")
    assert exam["questions"][2]["figures"][0]["caption"] == "Fig. 3.1"
    assert "mass per unit volume" not in shown and "velocity" in shown and '"correct"' not in shown
    with pytest.raises(Refused):  # timed: nothing is saved before the clock starts
        d.save_mock_answer(eid, "q1", {"parts": [number("15", "m/s")]}, False)
    started = d.transition(eid, "start")
    assert started["duration_ms"] == 60 * 60_000 and d.guard_tutor is not None
    with pytest.raises(Refused):  # the tutor is locked while the paper is sat
        d.guard_tutor()
    clock.advance(10 * 60_000)
    assert d.mock(eid)["remaining_ms"] == 50 * 60_000

    d.save_mock_answer(eid, "q1", {"parts": [number("15", "m/s")]}, False)
    d.save_mock_answer(eid, "q2", {"parts": [{"part_id": "p1", "kind": "mcq", "option_id": "B"}]}, False)
    d.save_mock_answer(
        eid,
        "q3",
        {
            "parts": [
                {"part_id": "p1", "kind": "short_text", "text": "The mass per unit volume of a substance"},
                number("4", "g/cm3", "p2"),
            ]
        },
        False,
    )
    report = asyncio.run(d.submit_mock(eid))
    valid("api/commands#/$defs/MockResult", report)

    # Numeric answers are tool-checked against the scheme's key; the choice against its verified key; the written
    # answer is judged and says so.
    marking = {(m["question_id"], m["part_id"]): m for m in report["past_paper"]["marking"]}
    assert marking[("q1", "p1")]["method"] == "checked" and marking[("q1", "p1")]["check_ids"]
    assert marking[("q2", "p1")]["method"] == "key"
    assert marking[("q3", "p1")]["method"] == "judged" and JUDGED
    assert marking[("q3", "p2")]["method"] == "checked" and marking[("q3", "p2")]["check_ids"]
    assert "math_check_equivalence" in TOOL_CALLS
    rows = {r["question_id"]: r["criteria"] for r in report["criteria"]}
    assert {c["method"] for c in rows["q3"]} == {"judged", "checked"}
    assert (report["score"], report["max_score"]) == (3, 6)

    # Marks lost by topic, as the mock report shows them with Practise this.
    topics = {t["topic_id"]: (t["score"], t["max_score"]) for t in report["by_topic"]}
    assert topics == {"cur.phy.o.motion": (2, 2), "cur.phy.o.matter": (1, 3)}
    assert DENSITY in report["practice_kc_ids"] and SPEED not in report["practice_kc_ids"]

    # And it never changes mastery: no attempt, verdict or exposure event, and no mastery row moved.
    assert report["past_paper"]["mastery_changed"] is False
    assert evidence(d) == before
    assert asyncio.run(d.submit_mock(eid)) == report  # asking again returns the same report


def test_asm27_without_a_scheme_everything_is_judged(desk) -> None:
    d, _ = desk
    paper = imported(d, scheme=None)
    assert not paper["has_mark_scheme"]
    assert {q["marking"] for q in paper["questions_found"]} == {"judged"}
    eid = d.create_mock(paper["paper_id"])["exam_id"]
    d.transition(eid, "start")
    d.save_mock_answer(eid, "q1", {"parts": [number("15", "m/s")]}, False)
    report = asyncio.run(d.submit_mock(eid))
    assert {m["method"] for m in report["past_paper"]["marking"]} <= {"judged", "not_marked"}
    assert all(not m["check_ids"] for m in report["past_paper"]["marking"])


def test_asm27_import_refuses_what_is_not_a_paper(desk) -> None:
    d, _ = desk
    body = {
        "client_import_id": "cli_" + "0" * 26,
        "title": "Notes",
        "subject": "physics",
        "duration_minutes": 30,
        "paper": SOURCE,
        "mark_scheme": None,
        "syllabus": None,
    }
    with pytest.raises(Refused, match="no_questions_found"):
        d.import_past_paper(body, chunks("Some notes about forces with no numbered questions."), None)
    with pytest.raises(Refused, match="syllabus_subject_mismatch"):
        d.import_past_paper({**body, "syllabus": "cur.mth.o"}, chunks(PAPER), None)
    listed = d.list_past_papers()
    valid("api/commands#/$defs/PastPaperList", listed)
    assert listed["papers"] == []


def test_asm27_parser_keeps_numbering_marks_and_choices() -> None:
    questions, calculator = parse_paper(chunks(
        "Instructions: answer every question.\n"
        "1 Work out 3 + 4.  [1]\n"
        "2 (a) (i) Name the unit of force. [1]\n"
        "(ii) State Newton's second law. (2 marks)\n"
        "(b) Explain why a moving ball slows down.\n"
        "on a rough floor [3]\n"
        "3 Which is a metal? A. sulfur B. copper C. carbon D. neon\n"
        "4\n"
        "(a) Expand 2(x + 3). [2]\n"
    ))  # fmt: skip
    assert not calculator
    leaves = [(leaf.label, leaf.marks, len(leaf.options)) for q in questions for leaf in q.leaves]
    assert leaves == [("1", 1, 0), ("2(a)(i)", 1, 0), ("2(a)(ii)", 2, 0), ("2(b)", 3, 0), ("3", None, 4),
                      ("4(a)", 2, 0)]  # fmt: skip
    assert questions[1].leaves[2].lines == ["Explain why a moving ball slows down.", "on a rough floor"]
    scheme = parse_scheme(chunks("1 7 B1\n2(a)(i) newton\n2(a)(ii) F = ma M1 A1\n3 B\n4a 2x + 6 B2\n"
                                 "1. A 2. C 3. D\n"))  # fmt: skip
    assert scheme["2(a)(i)"].answer == "newton"
    assert [p["type"] for p in scheme["2(a)(ii)"].points] == ["M", "A"] and scheme["2(a)(ii)"].marks == 2
    assert scheme["4(a)"].answer == "2x + 6" and scheme["4(a)"].marks == 2
    assert scheme["3"].answer == "D"  # the objective key line comes later and wins


def test_asm27_numeric_keys_round_to_their_own_precision() -> None:
    assert numeric_key("15 m/s") == {"value": "15", "unit": "m/s"}
    assert numeric_key("x = 4") == {"value": "4", "unit": None}
    assert numeric_key("2.5 x 10^3 J") == {"value": "2500", "unit": "J"}
    assert numeric_key("mass per unit volume") is None
    assert matches_precision(Decimal("12.54"), "12.5") and not matches_precision(Decimal("12.6"), "12.5")


# --- LRN-44: exam dates, the countdown and the plan ------------------------------------------------------------------

MTH_DIR = REPO / "content" / "curriculum" / "mth" / "o"


def two_subjects() -> tuple[Learner, Practice, PlanDesk, Any]:
    from learner_harness import Clock as HarnessClock

    index = PackIndex.from_tables(
        [
            ({"pack_id": "pack.phy.o", "version": "0.1.0"}, load_source(PACK_DIR).tables),
            ({"pack_id": "pack.mth.o", "version": "0.1.0"}, load_source(MTH_DIR).tables),
        ]
    )
    clock = HarnessClock(at_ms("2026-10-09"))  # noon
    learner = Learner.open(learner_db(), profile_id="0" * 26, device_id="d" * 32, wall_ms=clock,
                           max_skew_ms=86_400_000, params=MasteryParams(), content=index)  # fmt: skip
    conn = learner.conn
    conn.execute("INSERT INTO meta VALUES (1, ?, 1, ?, 'test', ?, 'test')", ("0" * 26, clock.now, clock.now))
    conn.execute(
        "INSERT INTO profile (profile_id, display_name, avatar, age_band, level, subjects, exam_date, created_at,"
        " updated_at) VALUES (?, 'Ama', 'disc-teal', '13_15', 'O', '[\"physics\", \"mathematics\"]', '2027-06-01',"
        " ?, ?)",
        ("0" * 26, clock.now, clock.now),
    )
    return learner, Practice(learner, clock), PlanDesk(learner, index, S, clock_ms=clock), clock


def test_lrn44_countdown_shapes_plan() -> None:
    learner, practice, desk, clock = two_subjects()
    maths = max(
        (k for k in sorted(desk.content.kcs) if k.startswith("kc.mth.o.")),
        key=lambda k: desk.content.exam_weight(k) or 0,
    )  # the maths idea worth most marks
    weak_physics = SPEED
    for _ in range(2):  # a weak maths idea and a weak (but less weak) physics one, both with recent errors
        practice.opportunity(maths, ("incorrect", "incorrect", "incorrect"))
        practice.opportunity(weak_physics, ("incorrect", "correct"))
    practice.end()
    today = clock.now
    exam_day = (desk.params.local_day(today) + 12) * DAY_MS
    from agent_core.learner.projections import local_date

    added = desk.exams().create({"client_exam_date_id": "cli_" + "0" * 26, "subject": "physics",
                                 "name": "Physics paper 2", "date": local_date(exam_day // DAY_MS),
                                 "time": "09:00"})  # fmt: skip
    plan = desk.propose()
    valid("api/commands#/$defs/PlanView", plan)
    # Home shows the countdown...
    assert plan["countdown"] == {"exam_id": added["exam_id"], "subject": "physics", "name": "Physics paper 2",
                                 "date": local_date(exam_day // DAY_MS), "time": "09:00", "days": 12}  # fmt: skip
    listed = desk.exams().list()
    valid("api/commands#/$defs/ExamDateList", listed)
    assert listed["countdown"]["days"] == 12
    # ...and the plan's next items come from that subject's weakest topics.
    main = next(b for b in plan["blocks"] if b["kind"] in ("main", "mock"))
    assert main["kind"] == "main" and main["kc_ids"] == [weak_physics]
    # Without the exam date the same learner would be served the weaker maths idea first.
    state = desk.state(clock.now)
    unshaped = planner.plan(replace(state, frontload=None), S)
    assert next(b for b in unshaped.blocks if b.kind == "main").kc_ids == (maths,)
    # Dates and reminders never become events: nothing to sync, nothing sent.
    assert learner.conn.execute("SELECT count(*) FROM events WHERE payload LIKE '%Physics paper 2%'").fetchone()[0] == 0


def test_lrn44_reminders_on_the_device() -> None:
    _, _, desk, clock = two_subjects()
    exams = desk.exams()
    from agent_core.learner.projections import local_date

    def on(days: int) -> str:
        return local_date(desk.params.local_day(clock.now) + days)

    seven = exams.create({"client_exam_date_id": "cli_" + "1" * 26, "subject": "physics", "name": "Physics paper 1",
                          "date": on(7)})  # fmt: skip
    exams.create({"client_exam_date_id": "cli_" + "2" * 26, "subject": "mathematics", "name": "Maths paper 2",
                  "date": on(9), "reminders": False})  # fmt: skip
    assert [(r["name"], r["kind_id"]) for r in exams.reminders_due()] == [("Physics paper 1", "d7")]
    exams.patch(seven["exam_id"], {"dismiss": "d7"})
    assert exams.reminders_due() == []
    clock.now += 7 * DAY_MS  # the day itself: from the morning hour (the harness clock reads noon)
    assert [r["kind_id"] for r in exams.reminders_due()] == ["day"]
    exams.patch(seven["exam_id"], {"reminders": False})
    assert exams.reminders_due() == []
    with pytest.raises(ExamDateRefused):
        exams.create({"client_exam_date_id": "cli_" + "3" * 26, "subject": "music", "name": "x", "date": on(1)})
    assert [e["name"] for e in exams.delete(seven["exam_id"])["exams"]] == ["Maths paper 2"]
