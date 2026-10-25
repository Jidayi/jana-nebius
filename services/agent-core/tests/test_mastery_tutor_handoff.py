"""A finished mastery question keeps its verified key when asked again in the tutor."""

import pytest
from test_m16_assessment import KC, answer, run
from test_m16_assessment import desk as fixture_desk

desk = fixture_desk


def finish(d, clock):
    state = d.start_assessment("mastery_check", "mathematics", KC)
    identity = state["assessment_id"]
    for n in range(3):
        item_id = state["current_item"]["item_id"]
        state = run(d.assessment_answer(identity, str(n), item_id, answer()))
        if n == 1:
            clock.advance(24 * 3_600_000)
            state = d.assessment(identity)
    assert state["state"] == "completed"
    selected = d._get(identity)["selected"]
    item = next(iter(selected.values()))
    return identity, item, item["stem"] + " " + item["parts"][0]["prompt"]


def test_finished_mastery_question_reuses_a_copy_of_the_pinned_key(desk):
    d, clock = desk
    _, item, question = finish(d, clock)
    loaded, part_id = d.completed_tutor_question(question, "mathematics")
    assert loaded == item and part_id == "a"
    loaded["parts"][0]["answer"]["options"][0]["correct"] = False
    assert d.completed_tutor_question(question, "mathematics")[0] == item
    guided = question + " Please guide me through this one step at a time."
    assert d.completed_tutor_question(guided, "mathematics")[0] == item


@pytest.mark.parametrize("change", ["number", "subject", "instruction", "unanswered", "active"])
def test_handoff_does_not_match_changed_or_unfinished_questions(desk, change):
    d, clock = desk
    _, item, question = finish(d, clock)
    subject = "mathematics"
    if change == "number":
        question = question.replace(item["stem"], item["stem"] + "0")
    elif change == "subject":
        subject = "accounting"
    elif change == "instruction":
        question += " Change the given number and use a different answer."
    elif change == "unanswered":
        unseen = next(i for i in d.content.table("items") if i["id"] not in d._get(d.store.all()[0]["id"])["selected"])
        question = unseen["stem"] + " " + unseen["parts"][0]["prompt"]
    else:
        d.start_assessment("mastery_check", "mathematics", KC)
    assert d.completed_tutor_question(question, subject) is None


def test_ambiguous_finished_questions_do_not_choose_an_arbitrary_key(desk):
    d, clock = desk
    identity, item, question = finish(d, clock)
    state = d._get(identity)
    other = next(i for i in state["selected"].values() if i["id"] != item["id"])
    other["stem"] = item["stem"]
    other["parts"][0]["prompt"] = item["parts"][0]["prompt"]
    d.content.records["items"][other["id"]]["stem"] = other["stem"]
    d.content.records["items"][other["id"]]["parts"][0]["prompt"] = other["parts"][0]["prompt"]
    d._commit(state)
    assert d.completed_tutor_question(question, "mathematics") is None


def test_engine_keeps_the_completed_key_and_marks_both_answers(tmp_path):
    import asyncio

    from engine_harness import close, make_engine, tutor

    async def scenario():
        engine, provider = await make_engine(
            tmp_path,
            {"coach": [tutor("How could you start?"), tutor("Check your addition."), tutor("That is correct.")]},
        )
        engine.state.subject = "mathematics"
        source = {
            "id": "itm.mth.o.number.9001",
            "type": "numeric",
            "kc_ids": [KC],
            "stem": "Add 30 and 4.",
            "parts": [
                {
                    "id": "a",
                    "prompt": "Find the sum.",
                    "marks": 1,
                    "answer": {
                        "kind": "numeric",
                        "value": "34",
                        "unit": None,
                        "unit_policy": "none",
                        "tolerance": {"mode": "absolute", "value": 0.000001},
                        "check_id": "chk_build_handoff_sum",
                    },
                }
            ],
            "solution": {"steps": [{"n": 1, "latex": "30 + 4 = 34", "check_id": "chk_build_handoff_sum"}]},
        }
        engine.completed_assessment_question = lambda text, subject: (source, "a")
        try:
            await engine.start_problem("Add 30 and 4. Find the sum.")
            assert engine.state.plan.final_value == "34"
            assert engine.state.practice["item"]["id"] == source["id"]
            await engine.student_turn("33")
            assert not engine.state.solved
            assert engine.state.board.steps[-1].status == "incorrect"
            await engine.student_turn("34")
            assert engine.state.solved
            assert engine.state.board.steps[-1].status == "correct"
            assert engine.state.board.steps[-1].check_id
            assert not any(r.get("_role") in ("solver", "diagnoser") for r in provider.requests)
            closing = str([r for r in provider.requests if r.get("_role") == "coach"][-1])
            assert "invite the student to choose another question" in closing
            assert "explain their method in words" not in closing
        finally:
            await close(engine)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text,correct", [("B", True), ("B. A compound", True), ("A compound", True), ("B. An element", False)]
)
def test_chat_choices_use_only_unambiguous_visible_labels(text, correct):
    from agent_core.engine.marking import mark_choice
    from agent_core.engine.slice import chat_answer

    part = {
        "marks": 1,
        "answer": {
            "kind": "mcq",
            "options": [
                {"id": "A", "text": "An element", "correct": False},
                {"id": "B", "text": "A compound", "correct": True},
            ],
        },
    }
    verdict = mark_choice(part, chat_answer(part, text))
    assert (verdict.outcome == "correct") is correct


@pytest.mark.parametrize(
    "text,correct",
    [
        ("47 cm < 0.48 m < 490 mm", True),
        ("e2, e1, e3", True),
        ("0.48 m < 47 cm < 490 mm", False),
        ("47 cm < 47 cm < 490 mm", False),
        ("47 cm < something else < 490 mm", False),
    ],
)
def test_chat_ordering_keeps_the_actual_order_and_rejects_unknowns(text, correct):
    from agent_core.engine.marking import mark_order
    from agent_core.engine.slice import chat_answer

    part = {
        "marks": 2,
        "answer": {
            "kind": "ordering",
            "scoring": "exact",
            "elements": [
                {"id": "e1", "text": "0.48 m"},
                {"id": "e2", "text": "47 cm"},
                {"id": "e3", "text": "490 mm"},
            ],
            "correct_order": ["e2", "e1", "e3"],
        },
    }
    verdict = mark_order(part, chat_answer(part, text))
    assert (verdict.outcome == "correct") is correct


def test_full_part_hint_releases_its_checked_answer_only_at_rung_five():
    from agent_core.engine.state import Plan, PlanStep, SessionState

    state = SessionState("ses_test")
    state.plan = Plan(
        [
            PlanStep(1, "5100 - 4200 + 28000 + 300", "300", None, "chk_first"),
            PlanStep(2, "29200", "29200", "$", "chk_final"),
        ],
        "29200",
        "$",
        "chk_final",
    )
    state.practice = {"completed_mastery": True, "item": {"parts": [{"id": "a"}]}}
    state.rung = 4
    assert any(value == 29200 for value, _ in state.withheld())
    state.rung = 5
    assert state.withheld() == []
    state.practice["completed_mastery"] = False
    assert any(value == 29200 for value, _ in state.withheld())


@pytest.mark.parametrize("unit,shown", [("kJ/mol", "85 kJ/mol"), ("m^2", "85 m²"), ("cm^3", "85 cm^3")])
def test_composite_units_are_not_misread_as_their_prefix(unit, shown):
    from agent_core.engine.claims import claim_problems
    from agent_core.engine.state import Plan, PlanStep, Problem, SessionState

    state = SessionState("ses_test")
    state.problem = Problem("p", "Find the requested quantity.", "p#s")
    state.plan = Plan([PlanStep(1, "85", "85", unit, "chk_final")], "85", unit, "chk_final")
    state.check_values = {"chk_final": [85]}
    assert claim_problems({"say": "The result is " + shown + "."}, state) == []
    wrong = shown.replace("/mol", "") if "/mol" in shown else shown.replace("²", "").replace("^3", "")
    assert claim_problems({"say": "The result is " + wrong + "."}, state)


def test_signed_conversion_constant_keeps_the_complete_worked_line(tmp_path):
    import asyncio
    from fractions import Fraction

    from agent_core.engine.state import state_from_json, state_to_json
    from engine_harness import close, make_engine, tutor

    async def scenario():
        engine, _ = await make_engine(tmp_path, {"coach": [tutor("Use the same unit for each ribbon.")]})
        engine.state.subject, engine.state.mode = "mathematics", "solution"
        engine.deps.visual_sources = lambda subject: {
            "pack_values": {
                "pack:pack.mth.o/conventions/mth.metric_hundred": Fraction(100),
                "pack:pack.mth.o/conventions/unrelated": Fraction(999),
            }
        }
        item = {
            "id": "itm.mth.o.number.9001",
            "type": "numeric",
            "kc_ids": [KC],
            "stem": "A ribbon is 0.48 m long.",
            "parts": [
                {
                    "id": "a",
                    "prompt": "Find its length in cm.",
                    "marks": 1,
                    "answer": {
                        "kind": "numeric",
                        "value": "48",
                        "unit": "cm",
                        "unit_policy": "equivalent",
                        "tolerance": {"mode": "absolute", "value": 0.000001},
                        "check_id": "chk_build_conversion",
                    },
                }
            ],
            "solution": {"steps": [{"n": 1, "latex": "0.48*100=48", "check_id": "chk_build_conversion"}]},
        }
        engine.completed_assessment_question = lambda text, subject: (item, "a")
        try:
            result = await engine.start_problem("A ribbon is 0.48 m long. Find its length in cm.")
            assert not result.degraded
            assert len(engine.state.board.steps) == 1
            assert engine.state.board.steps[0].latex == "0.48*100=48"
            assert engine.state.board.steps[0].check_id
            assert Fraction(100) in engine.state.provenance()
            assert Fraction(999) not in engine.state.provenance()
            assert Fraction(100) in state_from_json(state_to_json(engine.state)).provenance()
        finally:
            await close(engine)

    asyncio.run(scenario())


@pytest.mark.parametrize("number", [108, 109, 113, 114, 118, 119])
def test_distance_working_uses_the_distance_symbol(number):
    from decimal import Decimal

    import yaml
    from agent_core.engine.state import numbers_in
    from jana_tools import REPO_ROOT

    source = REPO_ROOT / f"content/curriculum/phy/o/items/itm.phy.o.motion.{number:04}.yaml"
    item = yaml.safe_load(source.read_text())
    final = item["solution"]["steps"][-1]
    assert final["latex"].startswith("s = ")
    assert item["parts"][0]["answer"]["unit"] == "m"
    assert numbers_in(final["latex"])[0] == Decimal(item["parts"][0]["answer"]["value"])
    assert final["check_id"] == item["parts"][0]["answer"]["check_id"]


def test_uncomputed_operand_is_not_reported_as_the_numeric_check_result():
    from fractions import Fraction

    from agent_core.engine.slice import plan_from_item
    from agent_core.engine.state import SessionState
    from agent_core.engine.ui import tutor_step_status

    item = {
        "parts": [{"id": "a", "answer": {"kind": "numeric", "value": "9", "unit": "m", "check_id": "chk_build_s"}}],
        "solution": {"steps": [{"n": 1, "latex": "s = 0 + 0.5*6^2/2", "check_id": "chk_build_s"}]},
    }
    plan, values = plan_from_item(item, "a")
    assert plan.steps[0].value == "9"
    assert set(values[plan.steps[0].check_id]) == {Fraction(9)}
    state = SessionState("ses_test")
    state.practice = {"completed_mastery": True}
    state.plan, state.check_values = plan, values
    assert tutor_step_status(plan.steps[0].latex, plan.steps[0].check_id, state)[1] == plan.steps[0].check_id
    assert tutor_step_status("s = 0 + 0.5*7^2/2", plan.steps[0].check_id, state) == ("unchecked", None)


@pytest.mark.parametrize("change", ["withdrawn", "key_changed", "corrected_working"])
def test_completed_context_respects_the_current_pack_revision(desk, change):
    d, clock = desk
    _, item, question = finish(d, clock)
    current = d.content.records["items"][item["id"]]
    if change == "withdrawn":
        current["review"]["status"] = "retired"
    elif change == "key_changed":
        current["parts"][0]["answer"]["options"][0]["correct"] = False
        current["parts"][0]["answer"]["options"][1]["correct"] = True
    else:
        current["solution"] = {"steps": [{"n": 1, "latex": "corrected working"}]}
    loaded = d.completed_tutor_question(question, "mathematics")
    if change == "corrected_working":
        assert loaded[0]["solution"] == current["solution"]
    else:
        assert loaded is None


def test_mastery_selection_does_not_validate_excluded_diagnostic_probes(desk, monkeypatch):
    from agent_core.engine.assessment import service

    d, _ = desk
    original = service.probe_problems
    checked = []

    def tracked(items, library, settings):
        checked.extend(i["id"] for i in items)
        return original(items, library, settings)

    monkeypatch.setattr(service, "probe_problems", tracked)
    mastery = d.eligible("mastery_check", [KC], "mathematics")
    assert mastery and all(i["type"] != "mcq_diagnostic" for i in mastery)
    assert checked == []
    diagnostic = d.eligible("diagnostic", [KC], "mathematics")
    assert any(i["type"] == "mcq_diagnostic" for i in diagnostic)
    assert checked
    checked.clear()
    assert d.eligible("diagnostic", ["kc.mth.o.unrelated.skill"], "mathematics") == []
    assert checked == []


def test_all_new_mastery_questions_and_corrected_physics_keep_every_checked_board_line(tmp_path):
    """Deterministic board preflight; actual model exchanges are separate integration evidence."""
    import asyncio

    import yaml
    from agent_core.store.pack_index import PackIndex
    from engine_harness import close, make_engine, tutor
    from jana_tools import REPO_ROOT

    sources = sorted((REPO_ROOT / "content/curriculum").glob("*/*/items/itm.*.9*.yaml"))
    sources = [p for p in sources if 9001 <= int(p.stem.split(".")[-1]) <= 9053]
    assert len(sources) == 53
    sources += [
        REPO_ROOT / f"content/curriculum/phy/o/items/itm.phy.o.motion.{n:04d}.yaml"
        for n in (108, 109, 113, 114, 118, 119)
    ]
    index = PackIndex.from_tables(
        [
            (
                {"pack_id": f"pack.{code}.o", "subject": code, "version": "test"},
                {
                    "conventions": yaml.safe_load(
                        (REPO_ROOT / f"content/curriculum/ref/{code}-o/conventions.yaml").read_text()
                    )
                },
            )
            for code in ("acc", "chm", "mth", "phy")
        ]
    )

    async def scenario():
        engine, _ = await make_engine(tmp_path, {"coach": [tutor("Review the checked working.")] * (len(sources) * 2)})
        engine.deps.visual_sources = index.visual_sources
        try:
            for source in sources:
                item = yaml.safe_load(source.read_text())
                engine.state.subject = {
                    "acc": "accounting",
                    "chm": "chemistry",
                    "mth": "mathematics",
                    "phy": "physics",
                }[item["subject"]]
                engine.state.mode = "solution"
                engine.completed_assessment_question = lambda text, subject, item=item: (item, "a")
                await engine.start_problem(item["stem"] + " " + item["parts"][0]["prompt"])
                shown = {(line.latex, line.check_id) for line in engine.state.board.steps}
                required = {(step.latex, step.check_id) for step in engine.state.plan.steps if step.check_id}
                assert required <= shown, (item["id"], required - shown)
                key = item["parts"][0]["answer"]
                if key["kind"] == "numeric" and key.get("unit") is None:
                    before = sum(o.role == "input_guard" for o in engine.auxiliary.log)
                    await engine.student_turn(key["value"])
                    assert engine.state.solved, item["id"]
                    assert sum(o.role == "input_guard" for o in engine.auxiliary.log) == before
                if item["id"] == "itm.mth.o.number.9031":
                    from agent_core.engine.claims import claim_problems
                    from agent_core.engine.gates import untraced_numbers

                    explanation = "The sale price is 85% of the original, so divide 68 by 0.85."
                    assert not untraced_numbers({"say": explanation}, engine.state, set())
                    assert not claim_problems({"say": explanation}, engine.state)
                    assert untraced_numbers({"say": "The remaining percentage is 86%."}, engine.state, set())
        finally:
            await close(engine)

    asyncio.run(scenario())


@pytest.mark.parametrize(
    "text,unit", [("-8", None), (" -0.25 ", None), ("+2e3", None), ("8", None), ("\u22128", None), ("-1/2", None),
                  ("-8 N", "N"), ("-2.5m/s^2", "m/s^2"), ("48 cm", "cm")],
)  # fmt: skip
def test_numeric_only_reads_numbers_as_the_engine_does(text, unit):
    from agent_core.engine.turn import numeric_only

    assert numeric_only(text, unit)


@pytest.mark.parametrize(
    "text,unit", [("-8 please explain", None), ("-8 N", None), ("-8 kill", "N"), ("8 mm", "m"), ("\uff18", None),
                  ("\u0668", None), ("-8\nI want to hurt myself", None)],
)  # fmt: skip
def test_numeric_only_rejects_prose_other_units_and_other_digits(text, unit):
    from agent_core.engine.turn import numeric_only

    assert not numeric_only(text, unit)


@pytest.mark.parametrize(
    "text,answer,numeric,calls",
    [("\u221248 cm", True, True, []), ("-48", True, True, []), ("-48", False, True, ["-48"]),
     ("-48", True, False, ["-48"]), ("-48 please explain", True, True, ["-48 please explain"])],
)  # fmt: skip
def test_guard_model_skips_the_role_only_for_a_numeric_answer_to_the_open_part(tmp_path, text, answer, numeric, calls):
    """The engine decides the skip from the open practice part and the answer path; the guard itself still runs."""
    import asyncio

    from engine_harness import close, make_engine

    async def scenario():
        engine, _ = await make_engine(tmp_path, {}, stage="S2")
        seen = []

        async def guard_input(redacted):
            seen.append(redacted)
            return "in_scope", 1.0, "model"

        engine.auxiliary.guard_input = guard_input
        part = {"id": "a", "answer": {"kind": "numeric" if numeric else "short_text", "value": "48", "unit": "cm"}}
        engine.state.problem = object()
        engine.state.practice = {"item": {"parts": [part]}, "part": "a"}
        try:
            model = await engine._guard_model(text, answer=answer)
            assert seen == calls
            assert model == (None if not calls else ("in_scope", 1.0))
            if not calls:  # the patterns, classifier and redaction still decide on the message
                assert engine.guard.check(text, engine.state.level, model).category == "in_scope"
        finally:
            await close(engine)

    asyncio.run(scenario())
