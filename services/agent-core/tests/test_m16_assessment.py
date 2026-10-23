"""M16.b-d acceptance checks, using synthetic items only."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.engine.assessment.adaptive import probe_problems, select_diagnostic
from agent_core.engine.assessment.service import AssessmentDesk, Refused, iso
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database

KC = "kc.mth.o.number.add"
TOPIC = "cur.mth.o.number"


def item(n: int, *, probe: bool = False) -> dict:
    return {
        "id": f"itm.mth.o.number.{n:04d}",
        "type": "mcq_diagnostic" if probe else "mcq",
        "stem": f"Synthetic item {n}",
        "kc_ids": [KC],
        "template_id": f"template{n}",
        "review": {"status": "published"},
        "difficulty": {"prior": 0},
        "parts": [
            {
                "id": "a",
                "prompt": "Choose",
                "marks": 1,
                "answer": {
                    "kind": "mcq",
                    "diagnostic": probe,
                    "check_id": "chk_fixture",
                    "options": [
                        {
                            "id": x,
                            "text": x,
                            "correct": x == "a",
                            "misconception_id": None if x == "a" else f"mc.mth.o.error_{x}",
                        }
                        for x in "abcd"
                    ],
                },
            }
        ],
    }


def answer(option: str = "a") -> dict:
    return {"parts": [{"part_id": "a", "kind": "mcq", "option_id": option}]}


class Clock:
    def __init__(self) -> None:
        self.wall = 1_800_000_000_000
        self.active = 0

    def advance(self, ms: int) -> None:
        self.wall += ms
        self.active += ms


@pytest.fixture
def desk(tmp_path: Path):
    clock = Clock()
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    bank = [item(n) for n in range(1, 45)] + [item(50, probe=True)]
    paper = {
        "id": "mock.mth.o.fixture",
        "subject": "mth",
        "level": "o",
        "title": "Fixture",
        "duration_minutes": 60,
        "total_marks": 2,
        "calculator": False,
        "blueprint": {"topic_weights": {TOPIC: 1}},
        "sections": [
            {
                "section_id": "s1",
                "title": "One",
                "item_types": ["mcq"],
                "marks": 2,
                "questions": [
                    {"question_id": f"q{n}", "item_id": bank[n - 1]["id"], "marks": 1, "kc_ids": [KC]} for n in (1, 2)
                ],
            }
        ],
    }
    library = [
        {
            "id": f"mc.mth.o.error_{x}",
            "kc_ids": [KC],
            "student_name": f"Error {x}",
            "fix": {"text": {"en": "Check the operation"}},
        }
        for x in "bcd"
    ]
    index = PackIndex.from_tables(
        [
            (
                {"pack_id": "pack.mth.o", "version": "1.0.0", "subject": "mth"},
                {
                    "items": bank,
                    "mock_papers": [paper],
                    "kcs": [
                        {
                            "id": KC,
                            "statement": "Add",
                            "node_id": TOPIC,
                            "code": "add",
                            "status": "active",
                            "prerequisites": [],
                            "misconception_ids": [],
                        }
                    ],
                    "curriculum_nodes": [
                        {"id": "cur.mth.o", "title": "Math", "kind": "subject"},
                        {"id": TOPIC, "title": "Number", "kind": "topic", "parent_id": "cur.mth.o"},
                    ],
                    "misconceptions": library,
                },
            )
        ]
    )
    learner = Learner.open(
        conn,
        profile_id="0" * 26,
        device_id="f" * 32,
        wall_ms=lambda: clock.wall,
        max_skew_ms=Settings().sync_clock_skew_max_ms,
        params=MasteryParams.from_settings(Settings()),
        content=index,
    )
    value = AssessmentDesk(learner, index, Settings(), clock_ms=lambda: clock.wall, monotonic_ms=lambda: clock.active)
    yield value, clock
    conn.close()


def run(awaitable):
    return asyncio.run(awaitable)


def start_mock(desk):
    exam = desk.create_mock("mock.mth.o.fixture")
    return desk.transition(exam["exam_id"], "start")


def asm10_caps(desk):
    d, c = desk
    state = d.start_assessment("diagnostic", "mathematics")
    for n in range(d.settings.diagnostic_max_items):
        if state["state"] == "completed":
            break
        state = run(d.assessment_answer(state["assessment_id"], str(n), state["current_item"]["item_id"], answer("b")))
    assert state["state"] == "completed"
    assert state["answered_count"] <= d.settings.diagnostic_max_items
    state = d.start_assessment("diagnostic", "mathematics")
    c.advance(d.settings.diagnostic_max_minutes * 60_000)
    assert d.assessment(state["assessment_id"])["state"] == "completed"


def asm10_partial_completion(desk):
    d, _ = desk
    state = d.start_assessment("diagnostic", "mathematics")
    state = run(
        d.assessment_answer(state["assessment_id"], "first", state["current_item"]["item_id"], None, not_learned=True)
    )
    stopped = d.stop_assessment(state["assessment_id"])
    assert stopped["state"] == "stopped" and stopped["answered_count"] == 1
    assert d.diagnostic_observations(stopped["assessment_id"])[0] == (0, d.settings.diagnostic_not_learned_weight)
    resumed = d.resume_assessment(stopped["assessment_id"])
    assert resumed["answered_count"] == 1
    assert "score" not in resumed and "verdict" not in resumed


def asm11_selection_reference():
    bank = [
        {"id": "one", "kc_ids": ["a"], "predicted_success": 0.7},
        {"id": "two", "kc_ids": ["b"], "predicted_success": 0.51},
        {"id": "three", "kc_ids": ["b"], "predicted_success": 0.8},
    ]
    assert select_diagnostic({"a": 0.5, "b": 0.4, "c": 0.5}, {"b": ["c"]}, bank, 0.3)["id"] == "two"
    assert select_diagnostic({"a": 0.9}, {}, bank, 0.3) is None


def asm12_probe_linter(desk):
    d, _ = desk
    probe = item(50, probe=True)
    original = copy.deepcopy(probe)
    library = d.content.table("misconceptions")
    assert probe_problems([probe], library, d.settings) == []
    probe["parts"][0]["answer"]["options"][1]["misconception_id"] = None
    assert probe_problems([probe], library, d.settings)
    probe = copy.deepcopy(original)
    probe["parts"][0]["answer"]["options"][1]["correct"] = True
    assert probe_problems([probe], library, d.settings)
    assert item(50, probe=True) == original


def asm13_probe_activates(desk):
    d, _ = desk
    assert d.probe_for(KC, first_lesson=True)["id"] == item(50)["id"]
    found = d.choose_probe(item(50)["id"], "b")
    assert found["misconception_id"] == "mc.mth.o.error_b" and found["fix"]
    row = d.learner.conn.execute(
        "SELECT status FROM learner_misconceptions WHERE misconception_id = ?", (found["misconception_id"],)
    ).fetchone()
    assert row[0] == "active"


def asm14_spaced_three(desk):
    d, c = desk
    state = d.start_assessment("mastery_check", "mathematics", KC)
    for n in range(2):
        state = run(d.assessment_answer(state["assessment_id"], str(n), state["current_item"]["item_id"], answer()))
    assert state["state"] == "waiting" and state["current_item"] is None
    c.advance(int(d.settings.mastery_check_min_spacing_hours * 3_600_000))
    state = d.assessment(state["assessment_id"])
    state = run(d.assessment_answer(state["assessment_id"], "third", state["current_item"]["item_id"], answer()))
    assert state["state"] == "completed"
    assert d.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id = ?", (KC,)).fetchone()[0] == "mastered"


def asm14_no_hints(desk):
    d, _ = desk
    d.start_assessment("mastery_check", "mathematics", KC)
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()


def asm22_search_exposure(desk):
    d, _ = desk
    shown = d.search("Synthetic")
    ids = {i["item_id"] for i in shown}
    assert item(1)["id"] not in ids and item(2)["id"] not in ids
    assert not ids.intersection(i["id"] for i in d.eligible("mastery_check"))
    assert any(e.type == "item_exposed" for e in d.learner.log.by_seq())


def asm22_mock_pool_reserved(desk):
    d, _ = desk
    assert not {item(1)["id"], item(2)["id"]}.intersection(i["id"] for i in d.eligible("practice"))


def asm22_variant_keys_verified(desk):
    d, _ = desk
    variant = item(70)
    with pytest.raises(Refused):
        d.accept_variant(variant, None)
    with pytest.raises(Refused):
        d.accept_variant(variant, "chk_variant_tool")
    test_variant_key_is_computed_by_the_worker(desk)


def asm16_timer_survives_restart(desk):
    d, c = desk
    exam = start_mock(d)
    c.advance(1234)
    saved = d.mock(exam["exam_id"])
    c.wall += 7_200_000
    restarted = AssessmentDesk(
        d.learner, d.content, d.settings, clock_ms=lambda: c.wall, monotonic_ms=lambda: c.active, recover=True
    )
    interrupted = restarted.mock(exam["exam_id"])
    assert interrupted["state"] == "interrupted" and interrupted["remaining_ms"] == saved["remaining_ms"]
    assert restarted.transition(exam["exam_id"], "resume")["remaining_ms"] == saved["remaining_ms"]
    _crashed_mock_restart(desk)


def asm16_tutor_locked(desk):
    d, _ = desk
    exam = start_mock(d)
    for action in (None, "pause", "resume", "interrupt"):
        if action:
            d.transition(exam["exam_id"], action)
        with pytest.raises(Refused, match="tutor_locked"):
            d.guard_tutor()


def asm16_auto_submit(desk):
    d, c = desk
    exam = start_mock(d)
    d.save_mock_answer(exam["exam_id"], "q1", answer(), False)
    c.advance(exam["duration_ms"])
    assert d.mock(exam["exam_id"])["state"] == "submitted"
    assert d.learner.conn.execute("SELECT count(*) FROM exam_answers WHERE answer IS NOT NULL").fetchone()[0] == 1
    with pytest.raises(Refused):
        d.save_mock_answer(exam["exam_id"], "q2", answer(), False)


def api27_mock_clear_and_flag(desk):
    d, _ = desk
    exam = start_mock(d)
    eid = exam["exam_id"]
    d.save_mock_answer(eid, "q1", None, True)
    d.save_mock_answer(eid, "q2", answer(), False)
    d.save_mock_answer(eid, "q2", None, False)
    assert d.mock(eid)["answers"] == {"q1": {"answer": None, "flagged": True}, "q2": {"answer": None, "flagged": False}}
    assert d.learner.conn.execute("SELECT count(*) FROM exam_answers WHERE answer IS NULL").fetchone()[0] == 2
    report = run(d.submit_mock(eid))
    assert report["score"] == 0 and report["unanswered"] == ["q1", "q2"]


def api27_mock_active_time(desk):
    d, c = desk
    exam = start_mock(d)
    c.advance(100)
    paused = d.transition(exam["exam_id"], "pause")
    assert paused["running_deadline_ts"] is None
    c.advance(300)
    assert d.transition(exam["exam_id"], "resume")["remaining_ms"] == exam["duration_ms"] - 100


def asm18_signals_only(desk):
    d, _ = desk
    exam = start_mock(d)
    assert not d.integrity(exam["exam_id"], "focus_loss", 30_000)
    assert d.integrity(exam["exam_id"], "focus_loss", 30_001)
    assert d.integrity(exam["exam_id"], "large_paste", 201)
    with pytest.raises(Refused):
        d.integrity(exam["exam_id"], "camera", 1)
    assert run(d.submit_mock(exam["exam_id"]))["integrity_counts"] == {"focus_loss": 1, "large_paste": 1}


def asm20_show_me_why(desk):
    d, _ = desk
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", answer("b"), False)
    report = run(d.submit_mock(eid))
    ref = report["review_items"][0]["show_me_why_ref"]
    review = d.review(ref)
    assert review["item"]["id"] == item(1)["id"] and review["answer"] == answer("b")
    assert review["origin"]["kind"] == "exam_review" and review["mode"] == "guided"


def asm20_totals_consistent(desk):
    d, _ = desk
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", answer(), True)
    report = run(d.submit_mock(eid))
    assert report["score"] == sum(t["score"] for t in report["by_topic"])
    assert report["max_score"] == sum(t["max_score"] for t in report["by_topic"])
    assert report["flagged"] == ["q1"]


def test_mock_report_has_no_band_without_the_boards_letters(desk):
    """ASM-19, D27, UXS-26: a paper whose pack sets no board grade letters reports no band at all (no `grade_band`);
    with letters, too little evidence is a null band ("Not enough evidence yet for a band")."""
    from agent_core.contracts import errors

    d, _ = desk
    eid = start_mock(d)["exam_id"]
    report = run(d.submit_mock(eid))
    assert "grade_band" not in report and errors("api/commands#/$defs/MockResult", report) == []
    paper = d.content.record("mock_papers", "mock.mth.o.fixture")
    paper["grade_config"] = {"boundaries": [0.6], "labels": ["P", "Q"]}  # invented letters, not a board's
    eid = start_mock(d)["exam_id"]
    report = run(d.submit_mock(eid))
    assert report["grade_band"] is None and errors("api/commands#/$defs/MockResult", report) == []


def loc24_extra_time(desk):
    d, _ = desk
    d.settings = Settings(extra_time_percent=25)
    exam = d.create_mock("mock.mth.o.fixture")
    assert exam["duration_ms"] == 75 * 60_000 and exam["extra_time_percent"] == 25
    assert d.transition(exam["exam_id"], "start")["extra_time_percent"] == 25
    d.settings = Settings(extra_time_percent=50)
    assert d.mock(exam["exam_id"])["extra_time_percent"] == 25


def api27_practice_without_model(desk):
    d, _ = desk
    state = d.create_practice("mathematics", [KC], 1)
    result = run(d.practice_answer(state["set_id"], "first", state["current_item"]["item_id"], answer(), 100))
    assert result["verdict"] == "correct" and result["next_item"] is None
    assert d.learner.conn.execute("SELECT n_eff FROM kc_mastery WHERE kc_id = ?", (KC,)).fetchone()[0] > 0


def api27_assessment_lifecycle(desk):
    d, _ = desk
    first = d.start_assessment("diagnostic", "mathematics")
    assert d.start_assessment("diagnostic", "mathematics")["assessment_id"] == first["assessment_id"]
    stopped = d.stop_assessment(first["assessment_id"])
    assert stopped["state"] == "stopped"
    assert d.resume_assessment(first["assessment_id"])["state"] == "in_progress"


def test_mastery_failure_retry(desk):
    d, _ = desk
    state = d.start_assessment("mastery_check", "mathematics", KC)
    state = run(d.assessment_answer(state["assessment_id"], "bad", state["current_item"]["item_id"], answer("b")))
    assert state["state"] == "failed" and state["retry_at"]
    with pytest.raises(Refused):
        d.start_assessment("mastery_check", "mathematics", KC)


def test_duplicate_answer_is_atomic(desk):
    d, _ = desk
    state = d.start_assessment("diagnostic", "mathematics")
    args = (state["assessment_id"], "same", state["current_item"]["item_id"], answer())
    first = run(d.assessment_answer(*args))
    assert run(d.assessment_answer(*args)) == first
    assert d.assessment(state["assessment_id"])["answered_count"] == 1
    body = d.learner.conn.execute("SELECT body FROM assessment_runs").fetchone()[0]
    assert "option_id" not in body


def asm17_a_needs_m():
    from agent_core.engine.assessment.criteria import score_criteria

    criteria = [
        {"criterion_id": "M1", "mark_type": "M", "marks": 1, "pass_if": "method", "requires": []},
        {"criterion_id": "A1", "mark_type": "A", "marks": 1, "pass_if": "accuracy", "requires": ["M1"]},
    ]
    scored = score_criteria(criteria, {"M1": False, "A1": True})
    assert sum(c["awarded"] for c in scored) == 0


def asm17_method_agreement(desk):
    from agent_core.engine.assessment.criteria import decide_method

    async def equivalent(left, right):
        return (left.replace(" ", "") == right.replace(" ", ""), "chk_method")

    assert run(decide_method([" x + 2 "], ["x+2"], equivalent, judge_allowed=False)) is True
    assert run(decide_method(["wrong"], ["x+2"], equivalent, judge_allowed=False)) is False

    async def uncertain(left, right):
        return None, None

    assert run(decide_method(["wrong"], ["x+2"], uncertain, judge_allowed=False)) is None

    from tool_worker.functions.maths import math_check_equivalence
    from tool_worker.registry import CallContext

    d, _ = desk
    context = CallContext(
        "fixture",
        "chk_method",
        {},
        {"cpu_ms": d.settings.worker_call_cpu_ms},
        lambda: False,
        settings=d.settings.model_dump(),
    )

    async def local_tool(name, args):
        assert name == "math_check_equivalence"
        value, _ = math_check_equivalence(args, context)
        return value, "chk_method"

    d.run_tool = local_tool
    reference = []
    for n in range(1, d.settings.mock_method_reference_cases + 1):
        reference.append((f"{n}*(x+1)", f"{n}*x+{n}", True))
        reference.append((f"{n}*(x+1)", f"{n}*x+{n + 1}", False))
    matches = sum(run(d._method_equivalent(left, right, ["x"]))[0] is expected for left, right, expected in reference)
    assert matches / len(reference) >= d.settings.mock_method_agreement_min


def asm17_unresolved_excluded():
    from agent_core.engine.assessment.criteria import score_criteria

    criteria = [{"criterion_id": "M1", "mark_type": "M", "marks": 1, "pass_if": "Show substitution"}]
    result = score_criteria(criteria, {"M1": None})[0]
    assert result["awarded"] == result["available"] == 0
    assert result["scheme"] == "Show substitution" and result["notice_key"] == "assessment.not_marked_automatically"


def test_method_judges_are_independent_and_must_agree():
    from agent_core.engine.assessment.criteria import decide_method

    calls = []

    async def equiv(left, right):
        return None, None

    async def judge(lines, alternatives):
        calls.append(len(calls))
        return len(calls) == 1

    assert run(decide_method(["a"], ["b"], equiv, judge_allowed=True, judge=judge)) is None
    assert len(calls) == 2


def api27_item_types_roundtrip(desk):
    from agent_core.contracts import errors
    from agent_core.engine.assessment.items import present, validate_answer

    d, _ = desk
    numbered_fixture(d.content)
    inputs = {
        "mcq": (
            {"options": [{"id": "a", "text": "A", "correct": True}, {"id": "b", "text": "B", "correct": False}]},
            {"option_id": "a"},
        ),
        "multi_select": ({"options": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}]}, {"option_ids": ["a"]}),
        "numeric": ({"value": "7", "unit": "m", "unit_policy": "exact"}, {"value": "7", "unit": "m"}),
        "algebraic": ({"variables": ["x"], "expression": "x+1"}, {"latex": "x+1"}),
        "equation_solutions": ({"variable": "x", "values": ["7"]}, {"values": ["7"]}),
        "chemical_equation": (
            {
                "reactants": [{"formula": "H2"}, {"formula": "O2"}],
                "products": [{"formula": "H2O"}],
                "state_symbols": "required",
            },
            {"equation": "2H2+O2->2H2O"},
        ),
        "journal_entry": ({"chart_of_accounts": "coa.test.v1", "currency": "USD"}, {"lines": []}),
        "accounting_table": (
            {"currency": "USD", "rows": [{"label": "secret", "amount": "7"}]},
            {"rows": [["cash", "7", "debit"]]},
        ),
        "diagram_label": (
            {"diagram_id": "diagram.test", "targets": [{"part_id": "tip", "accepted_labels": ["secret"]}]},
            {"labels": [{"target_id": "tip", "label": "tip"}]},
        ),
        "ordering": (
            {"elements": [{"id": "a", "text": "A"}, {"id": "b", "text": "B"}], "correct_order": ["b", "a"]},
            {"element_ids": ["a", "b"]},
        ),
        "short_text": ({"model_answer": "secret"}, {"text": "my response"}),
    }
    for n, (kind, (key, payload)) in enumerate(inputs.items()):
        source = item(80 + n)
        source["type"] = kind
        source["parts"][0]["answer"] = {"kind": kind, **key}
        if kind == "diagram_label":
            source["id"] = source["id"].replace(".mth.", ".chm.")
            d.content.subject_packs["cur.chm.o"] = d.content.subject_packs["cur.mth.o"]
        shown = present(source, d.content, d.settings)
        assert errors("api/commands#/$defs/PracticeItem", shown) == []
        encoded = json.dumps(shown)
        assert all(
            field not in encoded
            for field in ("correct_order", "accepted_labels", "model_answer", "expression", "secret")
        )
        typed = {"parts": [{"part_id": "a", "kind": kind, **payload}]}
        assert validate_answer(source, typed) == typed
    source["type"] = "structured"
    source["parts"].append(
        {
            "id": "b",
            "prompt": "Then",
            "marks": 1,
            "uses_parts": ["a"],
            "answer": {"kind": "numeric", "unit_policy": "none"},
        }
    )
    assert present(source, d.content, d.settings)["parts"][1]["uses_parts"] == ["a"]
    source["type"] = "mcq_diagnostic"
    source["parts"] = item(50, probe=True)["parts"]
    assert "marks" not in present(source, d.content, d.settings, diagnostic=True)


def agt24_exam_lock(desk, tmp_path):
    from agent_core.api.core import CoreService
    from agent_core.api.errors import ApiError
    from agent_core.store.sessions import SessionStore

    d, _ = desk
    core = CoreService(d.settings, lambda entry: None, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d
    start_mock(d)
    for method, args in (
        (core.create_session, ({},)),
        (core.start_turn, ("missing", {})),
        (core.side_question, ("missing", {})),
        (core.answer_card, ("missing", {})),
    ):
        with pytest.raises(ApiError) as caught:
            method(*args)
        assert caught.value.status == 423 and caught.value.code == "tutor_locked"


def api27_tutor_locked_in_mock(desk, tmp_path):
    agt24_exam_lock(desk, tmp_path)


def test_http_assessment_and_mock_routes(desk, tmp_path):
    import httpx
    from agent_core.api.app import create_app
    from agent_core.api.core import CoreService
    from agent_core.api.security import LaunchSecret
    from agent_core.store.sessions import SessionStore
    from api_harness import cli

    d, _ = desk
    core = CoreService(d.settings, lambda entry: None, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d
    secret = LaunchSecret("fixture-token")
    app = create_app(core, secret, lambda: 8910)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8910"
        ) as client:
            headers = {"authorization": "Bearer fixture-token", "origin": "tauri://localhost", "idempotency-key": cli()}
            reply = await client.post(
                "/v1/assessments", json={"kind": "diagnostic", "subject": "mathematics"}, headers=headers
            )
            assert reply.status_code == 200, reply.text
            identity = reply.json()["assessment_id"]
            assert (await client.get(f"/v1/assessments/{identity}", headers=headers)).status_code == 200

    run(scenario())


def test_not_learned_half_weight_survives_projection_replay(desk):
    d, _ = desk
    state = d.start_assessment("diagnostic", "mathematics")
    run(
        d.assessment_answer(
            state["assessment_id"], "not-learned", state["current_item"]["item_id"], None, not_learned=True
        )
    )
    before = d.learner.conn.execute("SELECT fail_w,n_eff FROM kc_mastery WHERE kc_id=?", (KC,)).fetchone()
    assert before == (0.5, 0.5)
    d.learner.projector.rebuild()
    assert d.learner.conn.execute("SELECT fail_w,n_eff FROM kc_mastery WHERE kc_id=?", (KC,)).fetchone() == before


def test_grade_prediction_gates_and_recent_mock_blend():
    from agent_core.engine.assessment.bands import predict_band

    settings = Settings()
    letters = ["P", "Q", "R", "S", "T"]  # invented for the test, not a board's
    assert predict_band({KC: (0.8, 10)}, {KC: 1}, 29, 0.6, [], settings, seed=7, labels=letters) is None
    assert predict_band({KC: (0.8, 10)}, {KC: 1}, 30, 0.59, [], settings, seed=7, labels=letters) is None
    forecast = predict_band({KC: (0.8, 100)}, {KC: 1}, 30, 1, [], settings, seed=7, labels=letters)
    recent = predict_band({KC: (0.8, 100)}, {KC: 1}, 30, 1, [0.4], settings, seed=7, labels=letters)
    assert forecast["score_interval"][0] > recent["score_interval"][0]
    assert forecast["band"] in letters and not forecast["board_neutral"]


def test_no_band_without_the_boards_letters():
    """ASM-19, D27: with ample evidence but no board grade letters in the pack, no band at all, never "1" to "5"."""
    from agent_core.engine.assessment.bands import pack_scale, predict_band

    settings = Settings()
    assert predict_band({KC: (0.8, 100)}, {KC: 1}, 300, 1, [], settings, seed=7) is None
    assert predict_band({KC: (0.8, 100)}, {KC: 1}, 300, 1, [], settings, seed=7,
                        boundaries=settings.grade_boundaries) is None  # fmt: skip
    scale = {"boundaries": [0.7, 0.5], "labels": ["P", "Q", "R"]}
    papers = [{"subject": "mth"}, {"subject": "phy", "grade_config": scale}]
    assert pack_scale(papers, "mth") is None and pack_scale(papers, "phy") == scale


def test_wire_replies_validate_against_the_adopted_contracts(desk):
    """The assessment replies satisfy the bundled contracts (D92 adopted the shapes M16 proposed)."""
    from agent_core.contracts import errors
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    d, _ = desk
    state = d.start_assessment("diagnostic", "mathematics")
    assert errors("learning/student-records#/$defs/AssessmentState", state) == []
    d.stop_assessment(state["assessment_id"])
    practice = d.create_practice("mathematics", [KC], 1)
    assert errors("api/commands#/$defs/PracticeSet", practice) == []
    marked = run(d.practice_answer(practice["set_id"], "wire", practice["current_item"]["item_id"], answer(), 0))
    assert errors("api/commands#/$defs/PracticeMarked", marked) == []
    assert errors("api/commands#/$defs/PracticeSet", d.practice(practice["set_id"])) == []
    exam = d.create_mock("mock.mth.o.fixture")
    assert errors("api/commands#/$defs/MockExam", exam) == []
    d.transition(exam["exam_id"], "start")
    question = exam["question_ids"][0]
    assert errors("api/commands#/$defs/Saved", d.navigate(exam["exam_id"], question)) == []
    report = run(d.submit_mock(exam["exam_id"]))
    assert errors("api/commands#/$defs/MockResult", report) == []
    for key in ("GET /v1/mocks", "GET /v1/practice/sets/{set_id}", "GET /v1/search/items",
                "POST /v1/mocks/{exam_id}/navigate", "POST /v1/mocks/{exam_id}/integrity",
                "GET /v1/lessons/{lesson_id}/probe", "POST /v1/probes/{probe_id}/answers"):  # fmt: skip
        assert ENDPOINTS_BY_KEY[key]["auth"] == ["launch", "profile"], key


def test_method_judge_can_resolve_a_nonmatching_line():
    from agent_core.engine.assessment.criteria import decide_method

    async def equivalent(left, right):
        return False, "chk_method"

    async def judge(lines, alternatives):
        return True

    assert (
        run(decide_method(["alternative derivation"], ["scheme"], equivalent, judge_allowed=True, judge=judge)) is True
    )


def test_mock_method_working_round_trip(desk):
    d, _ = desk
    paper = d.content.records["mock_papers"]["mock.mth.o.fixture"]
    paper["sections"][0]["questions"][0]["criteria"] = [
        {
            "criterion_id": "M1",
            "mark_type": "M",
            "marks": 1,
            "pass_if": "Use the sum",
            "check": {"method_lines": ["2+3"]},
        },
        {"criterion_id": "A1", "mark_type": "A", "marks": 1, "pass_if": "Select a", "requires": ["M1"]},
    ]

    async def tool(name, args):
        assert name == "math_check_equivalence"
        return {"verdict": "equivalent" if args["a"] == args["b"] else "not_equivalent"}, "chk_method"

    d.run_tool = tool
    typed = {**answer(), "working": [{"part_id": "a", "latex": "2+3"}]}
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", typed, False)
    report = run(d.submit_mock(eid))
    assert report["criteria"][0]["criteria"][0]["awarded"] == 1


def uxs24_help_me_round_trip(desk, tmp_path):
    from agent_core.api.core import CoreService
    from agent_core.store.sessions import SessionStore
    from api_harness import cli

    d, _ = desk
    state = d.create_practice("mathematics", [KC], 1)
    item_id = state["current_item"]["item_id"]
    loaded = d.practice_help(state["set_id"], item_id)
    core = CoreService(d.settings, lambda state: None, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d
    session = core.create_session(
        {"client_session_id": cli(), "mode": "guided", "subject": "mathematics", "origin": loaded["origin"]}
    )
    entry = core.entry(session["session_id"])
    assert entry.engine_state.practice["item"]["id"] == item_id
    assert entry.engine_state.plan is not None
    assert d._get(state["set_id"])["index"] == 0


def test_profile_scoped_assessment_desk(desk, tmp_path):
    from agent_core.api.assessment import desk as opened
    from agent_core.api.core import CURRENT_PROFILE, CoreService
    from agent_core.api.errors import ApiError
    from agent_core.store.sessions import SessionStore

    d, _ = desk
    core = CoreService(d.settings, lambda state: None, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d

    class Directory:
        def exists(self):
            return True

    core.directory = Directory()
    core.records_profile = "profile-b"
    scope = CURRENT_PROFILE.set("profile-a")
    try:
        with pytest.raises(ApiError) as caught:
            opened(core)
        assert caught.value.status == 404
    finally:
        CURRENT_PROFILE.reset(scope)


def test_variant_key_is_computed_by_the_worker(desk):
    d, _ = desk
    base = item(60)
    base["type"] = "numeric"
    base["template_id"] = "tpl.synthetic"
    base["parts"][0]["answer"] = {
        "kind": "numeric",
        "value": "2",
        "unit": None,
        "unit_policy": "none",
        "check_id": "chk_old",
    }
    d.content.records["items"][base["id"]] = base
    d.content.records["item_templates"]["tpl.synthetic"] = {
        "id": "tpl.synthetic",
        "stem_template": "Add {a} and {b}",
        "parameters": [
            {"name": "a", "kind": "integer", "min": 1, "max": 10},
            {"name": "b", "kind": "integer", "min": 1, "max": 10},
        ],
        "answer_tool": {"tool": "math_evaluate", "args": {"expression": "{a}+{b}"}},
    }
    calls = []

    async def tool(name, args):
        calls.append((name, args))
        return {"status": "ok", "exact": {"text": "7"}}, "chk_generated"

    d.run_tool = tool
    variant = run(d.generate_variant(base["id"], {"a": 3, "b": 4}))
    assert calls == [("math_evaluate", {"expression": "3+4"})]
    assert (
        variant["parts"][0]["answer"]["value"] == "7" and variant["parts"][0]["answer"]["check_id"] == "chk_generated"
    )
    assert base["parts"][0]["answer"]["value"] == "2"


def test_reserved_share_and_runtime_blueprint(desk):
    import math

    d, _ = desk
    published = d.content.table("items")
    assert len(d._reserved()) >= math.ceil(len(published) * d.settings.mock_reserved_bank_share)
    d.content.records["mock_papers"]["mock.mth.o.fixture"]["blueprint"]["topic_weights"] = {TOPIC: 0.4}
    with pytest.raises(Refused, match="blueprint"):
        d.create_mock("mock.mth.o.fixture")


def test_one_active_check_per_subject_kind(desk):
    d, _ = desk
    first = d.start_assessment("mastery_check", "mathematics", KC)
    d.content.kcs["kc.mth.o.number.other"] = d.content.kcs[KC]
    second = d.start_assessment("mastery_check", "mathematics", "kc.mth.o.number.other")
    assert first["assessment_id"] == second["assessment_id"]


def test_first_lesson_probe_is_persisted_and_reaches_coach(desk):
    d, _ = desk
    lesson_id = "les.mth.o.number.first"
    d.content.records.setdefault("lessons", {})[lesson_id] = {"id": lesson_id, "kc_ids": [KC], "node_id": TOPIC}
    probe = d.lesson_probe(lesson_id)
    assert probe["current_item"]["item_id"] == item(50)["id"]
    assert d.lesson_probe(lesson_id)["probe_id"] == probe["probe_id"]
    loaded = d.answer_probe(probe["probe_id"], "b")
    assert loaded["misconception_id"] == "mc.mth.o.error_b" and loaded["fix"]
    assert d.lesson_probe(lesson_id) is None


def test_two_unmatched_errors_schedule_probe(desk):
    d, _ = desk
    for i in d.content.records["items"].values():
        if i["type"] != "mcq_diagnostic":
            for option in i["parts"][0]["answer"]["options"]:
                option["misconception_id"] = None
    practice = d.create_practice("mathematics", [KC], 3)
    current = practice["current_item"]
    for n in range(2):
        reply = run(d.practice_answer(practice["set_id"], str(n), current["item_id"], answer("b"), 0))
        current = reply["next_item"]
    assert current["kind"] == "mcq_diagnostic"


def test_extra_time_reads_the_profile_preference(desk):
    from agent_core.store.sqlite import transaction

    d, _ = desk
    with transaction(d.learner.conn):
        d.learner.conn.execute(
            "INSERT INTO settings (key,value,source,hlc,updated_at)"
            " VALUES ('extra_time_percent','25','student','fixture',0)"
        )
    assert d.create_mock("mock.mth.o.fixture")["duration_ms"] == 75 * 60_000


def test_pause_budget_and_abandonment(desk):
    d, c = desk
    eid = start_mock(d)["exam_id"]
    d.transition(eid, "pause")
    c.advance(d.settings.mock_pause_minutes * 60_000 + 500)
    assert d.mock(eid)["state"] == "in_progress"
    with pytest.raises(Refused, match="pause_budget"):
        d.transition(eid, "pause")
    d.transition(eid, "interrupt")
    c.advance(d.settings.mock_abandon_days * 86_400_000)
    assert d.mock(eid)["state"] == "abandoned"


def test_mock_marks_feed_the_same_criteria_to_learning(desk):
    d, _ = desk
    paper = d.content.records["mock_papers"]["mock.mth.o.fixture"]
    paper["sections"][0]["questions"][0]["criteria"] = [
        {
            "criterion_id": "M1",
            "mark_type": "M",
            "marks": 1,
            "pass_if": "Show method",
            "check": {"method_lines": ["2+3"]},
        }
    ]
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", answer(), False)
    result = run(d.submit_mock(eid))
    assert result["criteria"][0]["criteria"][0]["available"] == 0
    assert (
        d.learner.conn.execute("SELECT outcome FROM attempts WHERE item_ref=?", (item(1)["id"],)).fetchone()[0]
        == "unverifiable"
    )


def _crashed_mock_restart(desk, unsaved_ms: int = 0):
    import subprocess
    import sys

    from agent_core.store.sqlite import open_database

    d, c = desk
    path = Path(d.learner.conn.execute("PRAGMA database_list").fetchone()[2]).with_name("forced-kill.db")
    tables = {table: list(records.values()) for table, records in d.content.records.items()}
    tables["curriculum_nodes"] = list(d.content.nodes.values())
    payload = {"pack_id": "pack.mth.o", "version": "1.0.0", "tables": tables, "wall": c.wall, "unsaved_ms": unsaved_ms}
    script = """
import json, os, sys
from pathlib import Path
from typing import Any
from agent_core.config import Settings
from agent_core.engine.assessment.service import AssessmentDesk
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database
p=json.loads(sys.stdin.read())
c,_=open_database(Path(sys.argv[1]),"learner")
content=PackIndex.from_tables([(p,p["tables"])])
settings=Settings()
learner=Learner.open(c,profile_id="0"*26,device_id="f"*32,wall_ms=lambda:p["wall"],max_skew_ms=settings.sync_clock_skew_max_ms,params=MasteryParams.from_settings(settings),content=content)
clock={"mono":0}
d=AssessmentDesk(learner,content,settings,clock_ms=lambda:p["wall"],monotonic_ms=lambda:clock["mono"])
e=d.create_mock("mock.mth.o.fixture")
d.transition(e["exam_id"],"start")
d.save_mock_answer(e["exam_id"],"q1",None,True)
clock["mono"]=1234
saved=d.mock(e["exam_id"])
clock["mono"] += p["unsaved_ms"]
saved["_unsaved_ms"] = p["unsaved_ms"]
os.write(1,json.dumps(saved).encode())
os._exit(17)
"""
    child = subprocess.run(
        [sys.executable, "-c", script, str(path)], input=json.dumps(payload), capture_output=True, text=True, timeout=30
    )
    assert child.returncode == 17, child.stderr
    saved = json.loads(child.stdout)
    conn, _ = open_database(path, "learner")
    try:
        learner = Learner.open(
            conn,
            profile_id="0" * 26,
            device_id="f" * 32,
            wall_ms=lambda: c.wall + 7_200_000,
            max_skew_ms=d.settings.sync_clock_skew_max_ms,
            params=MasteryParams.from_settings(d.settings),
            content=d.content,
        )
        recovered = AssessmentDesk(
            learner, d.content, d.settings, clock_ms=lambda: c.wall + 7_200_000, monotonic_ms=lambda: 0, recover=True
        )
        after = recovered.mock(saved["exam_id"])
        assert after["state"] == "interrupted" and after["remaining_ms"] == saved["remaining_ms"]
        expected_remaining_at_kill = max(0, saved["remaining_ms"] - saved["_unsaved_ms"])
        assert 0 <= after["remaining_ms"] - expected_remaining_at_kill <= 30_000
        assert after["answers"]["q1"] == {"answer": None, "flagged": True}
        assert recovered.transition(saved["exam_id"], "resume")["remaining_ms"] == saved["remaining_ms"]
    finally:
        conn.close()


def test_ready_to_check_is_scheduled_without_a_model(desk):
    d, _ = desk
    practice = d.create_practice("mathematics", [KC], 10)
    current = practice["current_item"]
    for n in range(10):
        reply = run(d.practice_answer(practice["set_id"], str(n), current["item_id"], answer(), 0))
        current = reply["next_item"]
    assert (
        d.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id=?", (KC,)).fetchone()[0] == "ready_to_check"
    )
    assert d.schedule_ready_checks() == 1
    assert d.schedule_ready_checks() == 0
    exposed = len(list(d.learner.log.by_seq()))
    scheduled = next(s for s in d.list_assessments() if s["kind"] == "mastery_check")
    assert scheduled["kc_id"] == KC and scheduled["state"] == "waiting" and scheduled["current_item"] is None
    assert len(list(d.learner.log.by_seq())) == exposed
    d.guard_tutor()  # Listing a planned check must not begin it or lock the tutor.
    opened = d.assessment(scheduled["assessment_id"])
    assert opened["current_item"] is not None
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()


def test_probe_fix_is_in_the_actual_coach_input(desk):
    from agent_core.engine.assessment.tutor import load_context
    from agent_core.engine.prompt_inputs import misconception_lines
    from agent_core.engine.state import SessionState

    d, _ = desk
    lesson_id = "les.mth.o.number.first"
    d.content.records.setdefault("lessons", {})[lesson_id] = {"id": lesson_id, "kc_ids": [KC], "node_id": TOPIC}
    probe = d.lesson_probe(lesson_id)
    loaded = d.answer_probe(probe["probe_id"], "b")
    state = SessionState("ses_" + "0" * 26)
    load_context(state, loaded)
    context = " ".join(misconception_lines(state))
    assert loaded["misconception_id"] in context and loaded["fix"] in context


def test_typed_accounting_responses_fit_marker_inputs():
    from agent_core.engine.assessment.items import response
    from agent_core.engine.marking import journal_lines, mark_accounting_table

    journal = {
        "kind": "journal_entry",
        "part_id": "a",
        "lines": [{"account_id": "cash", "side": "debit", "amount": "7"}],
    }
    assert journal_lines(response(journal)) is not None
    table = {"kind": "accounting_table", "part_id": "a", "rows": [["Sales", "7", "total"]]}

    async def no_tool(name, args):
        raise AssertionError("this independent total is checked against its key")

    part = {"id": "a", "marks": 1, "answer": {"rows": [{"label": "Sales", "amount": "7", "side": "total"}]}}
    assert run(mark_accounting_table(part, response(table), no_tool)).outcome == "correct"


def test_http_practice_mock_clear_and_review(desk, tmp_path):
    import httpx
    from agent_core.api.app import create_app
    from agent_core.api.core import CoreService
    from agent_core.api.security import LaunchSecret
    from agent_core.store.sessions import SessionStore
    from api_harness import ask, cli

    d, _ = desk
    models = []

    def engine(state):
        models.append(state)
        raise AssertionError("no model is needed by these commands")

    core = CoreService(d.settings, engine, SessionStore(tmp_path / "sessions"))
    core.assessments = lambda: d
    app = create_app(core, LaunchSecret("fixture-token"), lambda: 8910)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://127.0.0.1:8910"
        ) as client:

            async def send(method, path, body):
                result = await client.request(
                    method,
                    path,
                    json=body,
                    headers={
                        "authorization": "Bearer fixture-token",
                        "origin": "tauri://localhost",
                        "idempotency-key": cli(),
                    },
                )
                assert result.status_code == 200, result.text
                return result.json()

            practice = await send(
                "POST",
                "/v1/practice/sets",
                {"client_set_id": cli(), "subject": "mathematics", "size": 1, "source": "topic", "kc_ids": [KC]},
            )
            help_session = await send(
                "POST", f"/v1/practice/sets/{practice['set_id']}/help", {"item_id": practice["current_item"]["item_id"]}
            )
            await send(
                "POST",
                f"/v1/practice/sets/{practice['set_id']}/answers",
                {
                    "client_attempt_id": cli(),
                    "item_id": practice["current_item"]["item_id"],
                    "answer": answer(),
                    "time_ms": 0,
                    "hints_used": 0,
                },
            )
            exam = await send("POST", "/v1/mocks", {"client_exam_id": cli(), "paper_id": "mock.mth.o.fixture"})
            eid = exam["exam_id"]
            await send("POST", f"/v1/mocks/{eid}/start", {})
            locked = await client.post(
                f"/v1/sessions/{help_session['session_id']}/turns",
                json=ask("help"),
                headers={
                    "authorization": "Bearer fixture-token",
                    "origin": "tauri://localhost",
                    "idempotency-key": cli(),
                },
            )
            assert locked.status_code == 423 and not models
            await send("PUT", f"/v1/mocks/{eid}/answers/q1", {"answer": None, "flagged": True})
            await send("PUT", f"/v1/mocks/{eid}/answers/q2", {"answer": answer(), "flagged": False})
            await send("PUT", f"/v1/mocks/{eid}/answers/q2", {"answer": None, "flagged": False})
            report = await send("POST", f"/v1/mocks/{eid}/submit", {})
            assert report["score"] == 0 and report["unanswered"] == ["q1", "q2"]
            review = await send(
                "POST",
                "/v1/sessions",
                {
                    "client_session_id": cli(),
                    "mode": "guided",
                    "subject": "mathematics",
                    "origin": {"kind": "exam_review", "ref": report["review_items"][0]["show_me_why_ref"]},
                },
            )
            state = core.entry(review["session_id"]).engine_state
            assert state.mock_answer_submitted and state.mode == "guided" and state.leak_gated()

    run(scenario())


def test_authored_method_check_id_uses_the_solution_line(desk):
    d, _ = desk
    source = d.content.records["items"][item(1)["id"]]
    source["parts"][0]["mark_points"] = [
        {"id": "M1", "type": "M", "marks": 1, "criterion": "Use the sum", "check_id": "chk_method"}
    ]
    source["solution"] = {"steps": [{"n": 1, "latex": "2+3", "check_id": "chk_method"}]}

    async def tool(name, args):
        return {"verdict": "equivalent" if args == {"a": "2+3", "b": "2+3"} else "not_equivalent"}, "chk_equivalence"

    d.run_tool = tool
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", {**answer(), "working": [{"part_id": "a", "latex": "2+3"}]}, False)
    result = run(d.submit_mock(eid))
    assert result["criteria"][0]["criteria"][0]["awarded"] == 1


def test_optional_section_counts_only_the_chosen_questions(desk):
    d, _ = desk
    paper = d.content.records["mock_papers"]["mock.mth.o.fixture"]
    paper["sections"][0].update(choose=1, marks=1)
    paper["total_marks"] = 1
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q2", answer(), False)
    with pytest.raises(Refused, match="choice_limit"):
        d.save_mock_answer(eid, "q1", answer(), False)
    d.save_mock_answer(eid, "q1", None, True)
    result = run(d.submit_mock(eid))
    assert result["score"] == result["max_score"] == 1
    assert result["optional_omitted"] == ["q1"]


def test_navigator_uses_blueprint_question_order(desk):
    d, _ = desk
    questions = d.content.records["mock_papers"]["mock.mth.o.fixture"]["sections"][0]["questions"]
    questions[0]["question_id"] = "q2"
    questions[1]["question_id"] = "q10"
    exam = d.create_mock("mock.mth.o.fixture")
    assert exam["question_ids"] == ["q2", "q10"]
    assert exam["questions"][0]["item_id"] == questions[0]["item_id"]


def test_mock_report_generates_an_unseen_practice_set(desk):
    d, _ = desk
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", answer("b"), False)
    report = run(d.submit_mock(eid))
    assert report["practice_set_ref"] is not None
    practice = d.practice(report["practice_set_ref"])
    assert practice["current_item"]["item_id"] not in {item(1)["id"], item(2)["id"]}
    assert any(e.type == "item_exposed" and e.payload["surface"] == "review" for e in d.learner.log.by_seq())


def test_unverifiable_check_does_not_fail_mastery(desk):
    from agent_core.engine.marking import Verdict

    d, _ = desk
    state = d.start_assessment("mastery_check", "mathematics", KC)

    async def unavailable(item, answer):
        return {"a": Verdict("unverifiable", 0, 1, "fixture")}

    d._mark = unavailable
    with pytest.raises(Refused, match="worker_unavailable"):
        run(d.assessment_answer(state["assessment_id"], "offline", state["current_item"]["item_id"], answer()))
    assert d.assessment(state["assessment_id"])["answered_count"] == 0


def test_review_pins_referenced_verified_solution(desk):
    from agent_core.engine.assessment.tutor import load_context
    from agent_core.engine.state import SessionState

    d, _ = desk
    reference = "wex.mth.o.number.0001"
    d.content.records.setdefault("worked_examples", {})[reference] = {
        "id": reference,
        "steps": [{"n": 1, "latex": "2+3=5", "reason": "Add", "check_id": "chk_solution"}],
    }
    d.content.records["items"][item(1)["id"]]["solution"] = {"worked_example_id": reference}
    eid = start_mock(d)["exam_id"]
    report = run(d.submit_mock(eid))
    d.content.records["worked_examples"].clear()
    loaded = d.review(report["review_items"][0]["show_me_why_ref"])
    state = SessionState("ses_" + "0" * 26)
    load_context(state, loaded)
    assert state.plan.steps[0].latex == "2+3=5" and state.check_values[state.plan.steps[0].check_id] == [5]


def test_duplicate_submit_cannot_double_apply_evidence(desk):
    d, _ = desk
    eid = start_mock(d)["exam_id"]
    d.save_mock_answer(eid, "q1", answer(), False)
    original = d._mark

    async def scenario():
        entered, released = asyncio.Event(), asyncio.Event()

        async def delayed(item, response):
            entered.set()
            await released.wait()
            return await original(item, response)

        d._mark = delayed
        first = asyncio.create_task(d.submit_mock(eid))
        await entered.wait()
        second = asyncio.create_task(d.submit_mock(eid.removeprefix("exm_")))
        await asyncio.sleep(0)
        try:
            assert second.done() and isinstance(second.exception(), Refused)
        finally:
            released.set()
            await asyncio.gather(first, second, return_exceptions=True)

    run(scenario())
    assert d.learner.conn.execute("SELECT count(*) FROM attempts").fetchone()[0] == 1


def test_mock_uses_the_markers_binary_criterion_results(desk):
    from agent_core.engine.marking import Verdict

    d, _ = desk
    source = item(90)
    source["parts"][0].update(
        marks=2,
        mark_points=[
            {"id": "B1", "type": "B", "marks": 1, "criterion": "First point"},
            {"id": "B2", "type": "B", "marks": 1, "criterion": "Second point"},
        ],
    )

    async def marked(item, response):
        return {
            "a": Verdict(
                "partial",
                1,
                2,
                "fixture",
                criteria=(
                    {"criterion_id": "B1", "mark_type": "B", "result": "pass", "method": "key"},
                    {"criterion_id": "B2", "mark_type": "B", "result": "fail", "method": "key"},
                ),
            )
        }

    d._mark = marked
    score, available, _, _ = run(d._score_question({"question_id": "q1"}, source, answer()))
    assert (score, available) == (1, 2)


def test_extra_time_is_copied_when_the_ready_paper_starts(desk):
    d, _ = desk
    exam = d.create_mock("mock.mth.o.fixture")
    d.settings = Settings(extra_time_percent=25)
    started = d.transition(exam["exam_id"], "start")
    assert started["duration_ms"] == 75 * 60_000 and started["extra_time_percent"] == 25
    d.settings = Settings(extra_time_percent=50)
    assert d.mock(exam["exam_id"])["extra_time_percent"] == 25


def test_diagnostic_persists_implied_evidence_to_the_configured_depth(desk):
    from dataclasses import replace

    d, _ = desk
    parent, grandparent = "kc.mth.o.number.base", "kc.mth.o.number.foundation"
    original = d.content.kcs[KC]
    d.content.kcs[KC] = replace(original, prerequisites=(parent,))
    d.content.kcs[parent] = replace(original, kc_id=parent, prerequisites=(grandparent,))
    d.content.kcs[grandparent] = replace(original, kc_id=grandparent, prerequisites=())
    state = d.start_assessment("diagnostic", "mathematics")
    run(d.assessment_answer(state["assessment_id"], "depth", state["current_item"]["item_id"], answer()))
    row = d.learner.conn.execute("SELECT implied_w FROM kc_mastery WHERE kc_id=?", (grandparent,)).fetchone()
    assert row is not None and row[0] == d.settings.mastery_implied_w / 2


def test_runtime_method_judges_are_local_and_must_agree(desk, tmp_path):
    from types import SimpleNamespace

    from agent_core.engine.assembly import AppRuntime
    from jana_tools import REPO_ROOT

    d, _ = desk
    calls = []
    judgements = [True, False]

    class LocalRouter:
        def __init__(self):
            self.providers = {"local": SimpleNamespace(kind="local"), "cloud": SimpleNamespace(kind="cloud")}

        async def complete(self, role, messages, **kwargs):
            assert set(self.providers) == {"local"} and self.cloud_on(role) is False
            assert role == "judge" and "Use addition" in messages[-1].content
            calls.append(role)
            return SimpleNamespace(
                turn=SimpleNamespace(served_by="local"),
                schema_valid=True,
                structured={"criteria": [{"id": "M1", "pass": judgements[len(calls) - 1], "evidence": "fixture"}]},
            )

    router = LocalRouter()
    runtime = AppRuntime(d.settings, REPO_ROOT / "content/agent", REPO_ROOT / "skills", tmp_path)
    runtime.providers = dict(router.providers)
    runtime._router = lambda: router
    runtime.hardware_class = lambda: "mid"
    d.judge_method = runtime._assessment_judge
    source = item(91)
    source["parts"][0]["mark_points"] = [
        {"id": "M1", "type": "M", "marks": 1, "criterion": "Use addition", "judge_allowed": True}
    ]
    score, available, _, _ = run(
        d._score_question({"question_id": "q1"}, source, {**answer(), "working": [{"part_id": "a", "latex": "2+3"}]})
    )
    assert calls == ["judge", "judge"] and (score, available) == (0, 0)

    calls.clear()
    judgements[:] = [True, True]
    score, available, _, _ = run(
        d._score_question({"question_id": "q1"}, source, {**answer(), "working": [{"part_id": "a", "latex": "2+3"}]})
    )
    assert calls == ["judge", "judge"] and (score, available) == (1, 1)


def test_mock_list_offers_papers_and_finds_sittings(desk):
    """`GET /v1/mocks` (`MockList`, UXS-25, D93): every installed paper with what the chooser shows, and the profile's
    sittings newest first, each brought up to date before it is listed (a time-up submits, a long gap abandons)."""
    from agent_core.contracts import errors

    d, clock = desk
    papers = d.content.records["mock_papers"]
    paper = papers.pop("mock.mth.o.fixture")
    paper.update(id="mck.mth.o.0001", paper_kind="section_mock", duration_minutes=1)
    papers["mck.mth.o.0001"] = paper
    listed = d.list_mocks()
    assert errors("api/commands#/$defs/MockList", listed) == []
    assert listed["sittings"] == []
    assert listed["papers"] == [
        {
            "paper_id": "mck.mth.o.0001", "subject": "mathematics", "level": "O", "title": "Fixture",
            "paper_kind": "section_mock", "duration_minutes": 1, "total_marks": 2, "questions": 2, "calculator": False,
        }
    ]  # fmt: skip
    first = d.create_mock("mck.mth.o.0001")["exam_id"]
    d.transition(first, "start")
    clock.advance(20_000)
    listed = d.list_mocks()
    assert errors("api/commands#/$defs/MockList", listed) == []
    assert [(s["exam_id"], s["state"], s["remaining_ms"]) for s in listed["sittings"]] == [
        (first, "in_progress", 40_000)
    ]
    # Time up while nobody looked: listing the sittings submits it, as reading it would (ASM-16).
    clock.advance(60_000)
    assert d.list_mocks()["sittings"][0]["state"] == "submitted"
    report = run(d.submit_mock(first))
    clock.advance(1)
    second = d.create_mock("mck.mth.o.0001")["exam_id"]
    d.transition(second, "start")
    d.interrupt_all()
    listed = d.list_mocks()
    assert errors("api/commands#/$defs/MockList", listed) == []
    assert [(s["exam_id"], s["state"]) for s in listed["sittings"]] == [(second, "interrupted"), (first, "marked")]
    assert (listed["sittings"][1]["score"], listed["sittings"][1]["max_score"]) == (
        report["score"],
        report["max_score"],
    )
    # Not resumed within the abandonment window: abandoned, its answers kept (UXS-25's Home card).
    clock.advance(d.settings.mock_abandon_days * 86_400_000)
    assert d.list_mocks()["sittings"][0]["state"] == "abandoned"


def test_mastery_presentation_has_only_the_deterministic_mark(desk):
    d, _ = desk
    state = d.start_assessment("mastery_check", "mathematics", KC)
    state = run(d.assessment_answer(state["assessment_id"], "presentation", state["current_item"]["item_id"], answer()))
    assert state["last_mark"] == {"verdict": "correct", "marks_awarded": 1, "marks_total": 1}
    assert d.assessment(state["assessment_id"])["last_mark"] == state["last_mark"]
    assert "answer" not in json.dumps(state["current_item"])


def test_diagnostic_presentation_never_carries_mark_feedback(desk):
    d, _ = desk
    state = d.start_assessment("diagnostic", "mathematics")
    state = run(
        d.assessment_answer(state["assessment_id"], "presentation", state["current_item"]["item_id"], answer("b"))
    )
    assert "last_mark" not in state
    assert "marks" not in json.dumps(state["current_item"])
    assert "correct" not in json.dumps(state["current_item"])


def numbered_fixture(index):
    index.visuals.setdefault("chm", {"diagrams": {}, "presets": {}, "conventions": {}, "pack_values": {}})["diagrams"][
        "diagram.test"
    ] = {
        "id": "diagram.test",
        "version": "1.0.0",
        "title": "Secret tipped device",
        "licence": "LicenseRef-Own",
        "approved": True,
        "alt_text": "A vertical rectangle with a numbered label at its upper edge.",
        "parts": [{"id": "tip", "name": "Secret", "function": "The secret answer", "tab_order": 0}],
        "svg": (
            '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 480 320"><title>Secret</title>'
            '<g id="tip" data-part="tip"><rect x="20" y="20" width="50" height="200" fill="none" '
            'stroke="var(--color-ink)"/></g><text x="100" y="40" data-label-for="tip">Secret</text></svg>'
        ),
    }


def test_numbered_diagram_roundtrip_and_unavailable_selection(desk):
    from agent_core.engine.assessment.items import present, public_answer, ready, validate_answer

    d, _ = desk
    numbered_fixture(d.content)
    source = item(80)
    source["id"] = source["id"].replace(".mth.", ".chm.")
    d.content.subject_packs["cur.chm.o"] = d.content.subject_packs["cur.mth.o"]
    source["type"] = "diagram_label"
    source["parts"][0]["answer"] = {
        "kind": "diagram_label",
        "diagram_id": "diagram.test",
        "targets": [{"part_id": "tip", "accepted_labels": ["secret"]}],
    }
    shown = present(source, d.content, d.settings)
    assert shown["parts"][0]["input"]["target_ids"] == ["label_1"]
    assert shown["visual"]["type"] == "library_diagram"
    assert not any(word in json.dumps(shown).lower() for word in ("secret", "tip", "function", "accepted_labels"))
    typed = {
        "parts": [{"part_id": "a", "kind": "diagram_label", "labels": [{"target_id": "label_1", "label": "secret"}]}]
    }
    assert validate_answer(source, typed) == typed
    assert run(d._mark(source, typed))["a"].outcome == "correct"
    old = copy.deepcopy(typed)
    old["parts"][0]["labels"][0]["target_id"] = "tip"
    assert public_answer(source, old) == typed
    duplicate = copy.deepcopy(typed)
    duplicate["parts"][0]["labels"].append({"target_id": "tip", "label": "secret"})
    with pytest.raises(ValueError, match="repeated"):
        validate_answer(source, duplicate)
    assert ready(source, d.content, d.settings)
    d.content.records["items"][source["id"]] = source
    paper = d.content.table("mock_papers")[0]
    paper["sections"][0]["questions"][0]["item_id"] = source["id"]
    paper["sections"][0]["item_types"].append("diagram_label")
    exam = start_mock(d)
    d.save_mock_answer(exam["exam_id"], "q1", typed, False)
    assert d.mock(exam["exam_id"])["answers"]["q1"]["answer"] == typed
    run(d.submit_mock(exam["exam_id"]))
    d.content.visuals["chm"]["diagrams"]["diagram.test"]["alt_text"] = "The secret is visible."
    assert not ready(source, d.content, d.settings)
    assert d.list_mocks()["papers"] == []
    with pytest.raises(Refused, match="unavailable"):
        d.create_mock(paper["id"])
    d.content.records["items"][source["id"]] = source
    assert source["id"] not in {i["id"] for i in d.eligible("practice")}


def test_typed_subject_answers_use_real_markers_and_lesson_presentation(desk):
    from agent_core.engine.assessment.items import present, ready, validate_answer
    from agent_core.engine.learn import LearnDesk, student_item
    from test_m13_structured_marking import journal, propane, run_tool

    d, _ = desk
    d.run_tool = run_tool
    chemicals = propane(states="required")
    journal_item = journal()
    d.content.charts["coa.acc.o.standard.v1"] = {
        "accounts": [{"id": k, "name": k.title()} for k in ("equipment", "cash", "trade_payables")]
    }
    pairs = [
        (chemicals, {"part_id": "a", "kind": "chemical_equation", "equation": "C3H8(g) + 5O2(g) -> 3CO2(g) + 4H2O(l)"}),
        (
            journal_item,
            {
                "part_id": "a",
                "kind": "journal_entry",
                "lines": [
                    {
                        "account_id": line["account_id"],
                        "side": "debit" if line["debit"] != "0" else "credit",
                        "amount": line["debit"] if line["debit"] != "0" else line["credit"],
                    }
                    for line in journal_item["parts"][0]["answer"]["lines"]
                ],
            },
        ),
    ]
    for n, (source, typed_part) in enumerate(pairs):
        # Bind these synthetic marker fixtures to the installed subject/lesson.
        source.update(id=f"itm.mth.o.number.{90 + n:04d}", stem="Synthetic subject question", kc_ids=[KC])
        source["parts"][0]["uses_parts"] = []
        assert ready(source, d.content, d.settings)
        assert student_item(source, None, d.content, d.settings) == present(source, d.content, d.settings)
        typed = {"parts": [typed_part]}
        assert validate_answer(source, typed) == typed
        assert run(d._mark(source, typed))["a"].outcome == "correct"
        d.content.records["items"][source["id"]] = source
        lesson = "les.mth.o.number.synthetic"
        d.content.records.setdefault("lessons", {})[lesson] = {"blocks": [{"item_id": source["id"]}]}
        learn = LearnDesk(d.content, d.learner.conn, d.settings, run_tool=run_tool)
        assert run(learn.check(lesson, source["id"], typed["parts"]))["verdict"] == "correct"
    written = item(93)
    written["type"] = "short_text"
    written["parts"][0]["answer"] = {"kind": "short_text", "model_answer": "private"}
    assert ready(written, d.content, d.settings)
    assert not ready(written, d.content, d.settings, automatic=True)


@pytest.mark.parametrize("unsaved_ms", [0, 1, Settings().mock_checkpoint_ms - 1])
def dat07_exam_timer_survives_restart(desk, unsaved_ms):
    """Abrupt process death leaves at most one checkpoint interval unrecorded; answer/flag and timer recover.

    This exercises WAL recovery after os._exit without a graceful shutdown. Physical power-cut/device evidence is
    separate; this assertion covers the software checkpoint/recovery boundary.
    """
    _crashed_mock_restart(desk, unsaved_ms)


@pytest.mark.parametrize("status", ["in_progress", "paused"])
@pytest.mark.parametrize("wall_jump", [-7_200_000, 7_200_000])
def dat07_exam_clock_change(desk, status, wall_jump):
    d, c = desk
    exam = start_mock(d)
    c.advance(1234)
    if status == "paused":
        d.transition(exam["exam_id"], "pause")
    before = d.mock(exam["exam_id"])
    c.wall += wall_jump
    after = d.mock(exam["exam_id"])
    assert after["remaining_ms"] == before["remaining_ms"]
    assert after["state"] == status
    c.active += 1234  # Only monotonic time progresses now; wall time remains fixed.
    after = d.mock(exam["exam_id"])
    assert after["remaining_ms"] == before["remaining_ms"] - (1234 if status == "in_progress" else 0)
    if status == "paused":
        assert d.transition(exam["exam_id"], "resume")["remaining_ms"] == before["remaining_ms"]
        assert d.mock(exam["exam_id"])["pauses"][-1]["length_ms"] == 1234


def test_paused_timer_clock_jump_recovery_preserves_durable_pause_budget(desk):
    d, c = desk
    eid = start_mock(d)["exam_id"]
    c.advance(100)
    d.transition(eid, "pause")
    c.advance(200)
    c.wall += 7_200_000
    checkpoint = d.mock(eid)
    assert checkpoint["pauses"][-1]["length_ms"] == 200
    c.wall -= 14_400_000
    fresh_clock = [0]
    restarted = AssessmentDesk(
        d.learner, d.content, d.settings, clock_ms=lambda: c.wall, monotonic_ms=lambda: fresh_clock[0], recover=True
    )
    recovered = restarted.mock(eid)
    assert recovered["state"] == "interrupted" and recovered["remaining_ms"] == checkpoint["remaining_ms"]
    assert recovered["pauses"][-1]["length_ms"] == 200
    restarted.transition(eid, "resume")
    fresh_clock[0] += 500
    assert restarted.mock(eid)["remaining_ms"] == checkpoint["remaining_ms"] - 500


@pytest.mark.parametrize("kind", ["diagnostic", "mastery_check", "practice", "mock", "probe"])
def asm01_mode_tagging(desk, kind):
    """Actual entry points write attempts with their mode; each verdict resolves to that same tagged opportunity."""
    d, _ = desk
    if kind in ("diagnostic", "mastery_check"):
        state = d.start_assessment(kind, "mathematics", KC if kind == "mastery_check" else None)
        run(d.assessment_answer(state["assessment_id"], "mode-audit", state["current_item"]["item_id"], answer()))
    elif kind == "practice":
        state = d.create_practice("mathematics", [KC], 1)
        run(d.practice_answer(state["set_id"], "mode-audit", state["current_item"]["item_id"], answer(), 100))
    elif kind == "mock":
        state = start_mock(d)
        d.save_mock_answer(state["exam_id"], "q1", answer(), False)
        run(d.submit_mock(state["exam_id"]))
    else:
        lesson = "les.mth.o.number.first"
        d.content.records.setdefault("lessons", {})[lesson] = {"id": lesson, "kc_ids": [KC], "node_id": TOPIC}
        probe = d.lesson_probe(lesson)
        d.answer_probe(probe["probe_id"], "b")
        # An idempotent replay cannot issue a second opportunity.
        before = d.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0]
        d.answer_probe(probe["probe_id"], "b")
        assert d.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] == before
    rows = d.learner.conn.execute(
        "SELECT type,payload,session_id FROM events WHERE type IN ('attempt','verdict') ORDER BY seq"
    ).fetchall()
    attempts = {json.loads(p)["attempt_id"]: (json.loads(p), sid) for t, p, sid in rows if t == "attempt"}
    verdicts = [(json.loads(p), sid) for t, p, sid in rows if t == "verdict"]
    assert attempts and verdicts
    expected = "diagnostic" if kind == "probe" else kind
    assert {p["mode"] for p, _ in attempts.values()} == {expected}
    for verdict, sid in verdicts:
        attempt, source_session = attempts[verdict["attempt_id"]]
        assert source_session == sid and attempt["mode"] == expected
    assert set(attempts) == {v["attempt_id"] for v, _ in verdicts}


def _verify_mock_followup(desk, accept_set, perfect, existing=False, crashed=False):
    """A low-mastery full-mark KC is excluded; only lost-mark KCs enter the optional set and next plan."""
    from dataclasses import replace

    from agent_core.engine.plans import PlanDesk

    d, clock = desk
    kcs = [KC] + [f"kc.mth.o.number.skill_{n}" for n in range(1, 5)]
    for n, kc in enumerate(kcs):
        d.content.kcs[kc] = replace(d.content.kcs[KC], kc_id=kc)
        # Seed a deliberately very weak KC that will nevertheless earn full marks on this paper.
        fail = 100 if n == 0 else 2 * (5 - n)
        d.learner.conn.execute(
            "INSERT INTO kc_mastery(kc_id,status,p_mastery,n_eff,fail_w,last_event_seq,last_seen_at)"
            " VALUES (?,'learning',?,?,?,0,?)",
            (kc, 0.01 if n == 0 else 0.1 * n, fail, fail, clock.wall),
        )
        for number in (n + 1, n + 20, n + 30):
            d.content.records["items"][item(number)["id"]]["kc_ids"] = [kc]
    d.learner.conn.execute(
        "INSERT INTO profile(profile_id,display_name,avatar,age_band,level,subjects,created_at,updated_at)"
        " VALUES (?,'Synthetic','avatar.jana','18_plus','O','[\"mathematics\"]',?,?)",
        ("0" * 26, clock.wall, clock.wall),
    )
    paper = d.content.records["mock_papers"]["mock.mth.o.fixture"]
    questions = [
        {"question_id": f"q{n}", "item_id": item(n)["id"], "marks": 1, "kc_ids": [kc]} for n, kc in enumerate(kcs, 1)
    ]
    paper["sections"][0].update(questions=questions, marks=5)
    paper["total_marks"] = 5
    planner = PlanDesk(d.learner, d.content, d.settings, clock_ms=lambda: clock.wall)
    old_plan = planner.propose() if existing else None
    exam = start_mock(d)
    for n in range(1, 6):
        d.save_mock_answer(exam["exam_id"], f"q{n}", answer("a" if n == 1 or perfect else "b"), False)
    if crashed:
        refresh = d._refresh_mock_plan

        def fail():
            raise RuntimeError("simulated stop after durable marking")

        d._refresh_mock_plan = fail
        with pytest.raises(RuntimeError, match="simulated stop"):
            run(d.submit_mock(exam["exam_id"]))
        d._refresh_mock_plan = refresh
    report = run(d.submit_mock(exam["exam_id"]))
    count = d.learner.conn.execute("SELECT count(*) FROM study_plans").fetchone()[0]
    assert run(d.submit_mock(exam["exam_id"])) == report
    assert d.learner.conn.execute("SELECT count(*) FROM study_plans").fetchone()[0] == count
    planner = PlanDesk(d.learner, d.content, d.settings, clock_ms=lambda: clock.wall)
    if perfect:
        assert report["practice_kc_ids"] == [] and report["practice_set_ref"] is None
        assert planner.state(clock.wall).follow_up == ()
        return
    probabilities = dict(d.learner.conn.execute("SELECT kc_id,p_mastery FROM kc_mastery"))
    assert probabilities[KC] < min(probabilities[k] for k in kcs[1:]), "full-mark KC remains the least mastered"
    expected = sorted(kcs[1:], key=lambda k: (probabilities[k], k))[: d.settings.mock_weakest_kcs]
    assert report["practice_kc_ids"] == expected and KC not in expected
    assert report["practice_set_ref"]
    stored = d._get(report["practice_set_ref"])
    assert {k for i in stored["items"] for k in i["kc_ids"]} == set(expected)
    if accept_set:
        assert d.practice(report["practice_set_ref"])["current_item"] is not None
    planner = PlanDesk(d.learner, d.content, d.settings, clock_ms=lambda: clock.wall)
    plan = planner.current()
    assert plan is not None and (old_plan is None or plan["plan_id"] != old_plan["plan_id"])
    main = next(b for b in plan["blocks"] if b["kind"] == "main")
    assert main["kc_ids"] == expected and main["reason_code"] == "mock_follow_up"
    # Securing all the follow-up skills releases the priority. No accepting/opening the optional set is required.
    for kc in expected:
        d.learner.conn.execute(
            "UPDATE kc_mastery SET status='mastered',p_mastery=0.99,mastery_check_state='passed',attempts=10,n_eff=10"
            " WHERE kc_id=?",
            (kc,),
        )
    assert not set(planner.state(clock.wall).follow_up) - set(expected)
    from agent_core.learner.planner import follow_up

    assert follow_up(planner.state(clock.wall)) == ()


@pytest.mark.parametrize("accept_set,perfect", [(False, False), (True, False), (False, True)])
def asm20_followup_weak_kcs_only(desk, accept_set, perfect):
    _verify_mock_followup(desk, accept_set, perfect)


@pytest.mark.parametrize("existing,crashed", [(False, False), (True, False), (True, True)])
def uxs26_practice_weak_kcs_to_plan(desk, existing, crashed):
    _verify_mock_followup(desk, False, False, existing, crashed)


def test_mastery_surface_groups_templates_and_number_variants_not_broad_tags():
    import yaml

    root = Path(__file__).resolve().parents[3] / "content/curriculum/phy/o/items"
    car, cyclist, trolley, car_variant = [
        yaml.safe_load((root / f"itm.phy.o.motion.{n:04d}.yaml").read_text()) for n in (107, 108, 109, 112)
    ]
    assert car["context_tags"] == cyclist["context_tags"] == trolley["context_tags"] == ["transport"]
    assert len({AssessmentDesk._surface(i) for i in (car, cyclist, trolley)}) == 3
    assert AssessmentDesk._surface(car) == AssessmentDesk._surface(car_variant)
    # An authored template is authoritative, even when variants change the wording or tags.
    car["template_id"] = cyclist["template_id"] = "tpl.motion.final_velocity"
    assert AssessmentDesk._surface(car) == AssessmentDesk._surface(cyclist)


def test_mastery_surface_includes_the_requested_quantity():
    first = {"stem": "A car accelerates from 2 m/s at 3 m/s^2 for 4 s.", "parts": [{"prompt": "Find its final speed."}]}
    other = {**first, "parts": [{"prompt": "Find the distance travelled."}]}
    assert AssessmentDesk._surface(first) != AssessmentDesk._surface(other)


def test_mastery_restores_legacy_transport_check_and_completes_spaced_three(desk, monkeypatch):
    import yaml
    from tool_worker.functions.units import units_convert
    from tool_worker.registry import CallContext

    d, c = desk
    context = CallContext("fixture", "chk_mastery_units", {}, {}, lambda: False)

    async def local_tool(name, args):
        assert name == "units_convert"
        value, _ = units_convert(args, context)
        return value, context.check_id

    d.run_tool = local_tool
    root = Path(__file__).resolve().parents[3] / "content/curriculum/phy/o/items"
    bank = []
    for n in (107, 108, 109, 112):
        source = yaml.safe_load((root / f"itm.phy.o.motion.{n:04d}.yaml").read_text())
        source.update(id=f"itm.mth.o.number.{n:04d}", kc_ids=[KC])
        bank.append(source)
    # The normal reserved-bank share reserves the dummy; the three distinct contexts remain available.
    dummy = item(90)
    d.content.records["items"] = {i["id"]: i for i in (dummy, *bank)}
    d.content.records["mock_papers"]["mock.mth.o.fixture"]["sections"][0]["questions"][0]["item_id"] = dummy["id"]
    state = d.start_assessment("mastery_check", "mathematics", KC)
    assert state["current_item"]["item_id"] == bank[0]["id"]
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()

    def submit(view, value, unit):
        return run(
            d.assessment_answer(
                view["assessment_id"],
                str(view["answered_count"]),
                view["current_item"]["item_id"],
                {"parts": [{"part_id": "a", "kind": "numeric", "value": value, "unit": unit}]},
            )
        )

    # Retain the checkpoint shape produced by the old broad-tag selector after its first answer,
    # without letting today's preflight reject the obsolete one-surface bank before that answer.
    def legacy_wait(saved):
        saved.update(state="waiting", current_id=None, surfaces=["['transport']"])
        return []

    monkeypatch.setattr(d, "_advance", legacy_wait)
    state = submit(state, "20", "m/s")
    assert state["last_mark"]["verdict"] == "correct"
    assert state["state"] == "waiting" and state["answered_count"] == 1
    # Reopen that actual saved checkpoint with the corrected selector.
    legacy = d._get(state["assessment_id"])
    assert legacy["surfaces"] == ["['transport']"]
    d = AssessmentDesk(
        d.learner, d.content, d.settings, clock_ms=lambda: c.wall, monotonic_ms=lambda: c.active, run_tool=local_tool
    )
    state = d.assessment(state["assessment_id"])
    assert state["state"] == "in_progress" and state["answered_count"] == 1
    assert state["current_item"]["item_id"] == bank[1]["id"]
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()
    state = submit(state, "20", "m")
    assert state["answered_count"] == 2 and state["state"] == "waiting"
    assert state["available_at"] == iso(legacy["first_served"] + 24 * 3_600_000)
    d.guard_tutor()  # No current question during the spacing interval.
    c.advance(24 * 3_600_000 - 1)
    assert d.assessment(state["assessment_id"])["current_item"] is None
    c.advance(1)
    state = d.assessment(state["assessment_id"])
    assert state["current_item"]["item_id"] == bank[2]["id"]
    with pytest.raises(Refused, match="tutor_locked"):
        d.guard_tutor()
    state = submit(state, "27", "m")
    assert state["state"] == "completed" and state["answered_count"] == 3
    assert state["current_item"] is None and state["last_mark"]["verdict"] == "correct"
    assert len({a["item_id"] for a in state["answered_items"]}) == 3
    assert d.learner.conn.execute("SELECT status FROM kc_mastery WHERE kc_id=?", (KC,)).fetchone()[0] == "mastered"
    d.guard_tutor()
    assert d.assessment(state["assessment_id"])["state"] == "completed"
