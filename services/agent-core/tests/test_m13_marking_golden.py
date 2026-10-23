"""M13 marking: the golden marking cases (CUR-14, CUR-15), the diagram-label and structured markers (VSL-28,
ASM-06, ASM-17) and the misconception signature matcher (CUR-18). The cases are synthetic test data under
`evals/marking/`; the worker's checkers run in-process."""

from __future__ import annotations

import asyncio
import copy
import json
import sqlite3
from dataclasses import replace
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.contracts import validate
from agent_core.engine.learn import LearnDesk
from agent_core.engine.marking import MARKERS, Verdict, label_matches, mark, mark_structured
from agent_core.engine.signatures import UNDECIDED_RULES, SignatureContext, evaluable
from agent_core.store.generated.item_types import ITEM_TYPES
from agent_core.store.pack_index import MisconceptionInfo, PackIndex
from jana_tools import marking_golden as golden
from test_m16_assessment import desk as assessment_desk  # noqa: F401 - shared real learner fixture

SETTINGS = Settings()


def test_live_lesson_check_matches_pack_misconceptions() -> None:
    data = golden.load_signatures()
    item = {**data["items"]["ke_trolley"], "stem": "A synthetic trolley energy question"}
    lesson_id = "les.phy.o.energy.kinetic_energy"
    library = {m["id"]: m for m in data["misconceptions"]}
    content = PackIndex(
        records={
            "items": {item["id"]: item},
            "misconceptions": library,
            "lessons": {lesson_id: {"blocks": [{"type": "quick_check", "item_ids": [item["id"]]}]}},
        }
    )
    content.misconceptions = {
        m["id"]: MisconceptionInfo(m["id"], "A synthetic misconception", tuple(m["kc_ids"])) for m in library.values()
    }
    with sqlite3.connect(":memory:") as conn:
        desk = LearnDesk(content, conn, SETTINGS, run_tool=golden.run_tool)
        result = asyncio.run(desk.check(lesson_id, item["id"], [{"part_id": "a", "kind": "numeric",
                                                                "value": "3", "unit": "J"}]))  # fmt: skip
    assert result is not None
    assert result["parts"][0]["misconception"]["misconception_id"] == "mc.phy.o.ke_without_square"


def _failures(results: list[golden.Result]) -> list[str]:
    return [f"{r.case_id}: {r.detail}" for r in results if not r.passed]


# --- the acceptance tests -------------------------------------------------------------------------------------------


def cur14_marking_golden_suite() -> None:
    """Golden cases exist for every S2 type of the item-type table, and every case passes."""
    s2 = {name for name, row in ITEM_TYPES.items() if row["stage"] == "S2"}
    assert s2 <= set(MARKERS)
    results = golden.run_item_cases()
    covered = {r.item_type for r in results}
    assert s2 <= covered, f"no golden case for {sorted(s2 - covered)}"
    assert not _failures(results), _failures(results)


def cur15_marking_rules_golden() -> None:
    """Every row of the default marking rules is covered by passing cases, ECF recomputation and alias matching
    among them."""
    results = golden.run_item_cases()
    assert not _failures(results), _failures(results)
    covered = {tag for r in results for tag in r.rows}
    assert set(golden.RULE_ROWS) <= {tag.split(".", 1)[0] for tag in covered}
    assert set(golden.RULE_FACETS) <= covered, f"uncovered: {sorted(set(golden.RULE_FACETS) - covered)}"
    assert {"structured_parts.ecf", "journal_entries.alias", "hints.bottom_out"} <= covered


def cur18_signature_matching() -> None:
    """answer_transform and structural signatures name the intended misconception in at least the configured share
    of the seeded set; nothing is matched for the cases that hold no misconception."""
    results = golden.run_signature_cases()
    labelled = [r for r in results if r.kind in ("answer_transform", "structural")]
    kinds = {r.kind for r in labelled}
    assert kinds == {"answer_transform", "structural"}
    share = sum(r.passed for r in labelled) / len(labelled)
    assert share >= SETTINGS.marking_signature_match_share, _failures(labelled)
    clean = [r for r in results if r.kind == "none"]
    assert clean and all(r.passed for r in clean), _failures(clean)
    assert all(r.passed for r in results if r.kind == "step_error"), _failures(results)


# --- plain tests ----------------------------------------------------------------------------------------------------


def test_golden_files_are_well_formed() -> None:
    for name, data in golden.load().items():
        assert "Not real student work" in data["provenance"], name
        for key, item in data["items"].items():
            for part in item["parts"]:
                validate("content/content-pack#/$defs/Answer", part["answer"]), (name, key)
        ids = [c["id"] for c in data["cases"]]
        assert len(ids) == len(set(ids)), name


def test_label_tolerance() -> None:
    """VSL-28: case and spacing never matter; one edit is tolerated for names of five or more letters only."""
    names = ["Left ventricle", "left_ventricle"]
    assert label_matches("Left ventricel", names, SETTINGS)  # two letters swapped is one edit
    assert label_matches("  LEFT   VENTRICLE ", names, SETTINGS)
    assert not label_matches("ventricle", names, SETTINGS)
    assert label_matches("lens", ["Lens"], SETTINGS)
    assert not label_matches("lent", ["Lens"], SETTINGS)  # four letters: no tolerance
    assert not label_matches("Left ventriclxx", names, SETTINGS)


def test_evaluable_expressions() -> None:
    """Only arithmetic over the item's quantities reaches the checker; text, choices, equations and unknown names
    never do."""
    quantities = {"total": "10", "a": "2", "b1": "3"}
    assert evaluable("total - a - b1", quantities) is not None
    assert evaluable("sqrt(a) * 2", quantities) is not None
    for text in ("choice: balanced equation that is a multiple", "F = 0", "v ~ 1/d", "f(a)*2", "swap(a, total)",
                 "total - c", ""):  # fmt: skip
        assert evaluable(text, quantities) is None, text


def test_quantity_names_up_to_32_characters() -> None:
    """D91 (CUR-18): an item's quantity names may be up to 32 characters, and a signature over long names fires like
    any other; the contract refuses a 33-character name. Synthetic item and misconception."""
    speed = "speed_of_trolley_in_metres_per_s"  # 32 characters
    mass = "mass_of_trolley_kg"
    assert len(speed) == 32
    item = {**golden.load_signatures()["items"]["ke_trolley"], "quantities": {mass: "2", speed: "3"}}
    quantities = "content/content-pack#/$defs/Item/properties/quantities"
    validate(quantities, item["quantities"])
    try:
        validate(quantities, {speed + "x": "3"})
    except ValueError:
        pass
    else:
        raise AssertionError("a 33-character quantity name passed the contract")
    assert evaluable(f"1/2*{mass}*{speed}^2", item["quantities"]) is not None
    context = SignatureContext(misconceptions=[{"id": "mc.phy.o.ke_without_square",
                                                "kc_ids": ["kc.phy.o.energy.kinetic"],
                                                "signatures": [{"kind": "answer_transform",
                                                                "expression": f"1/2*{mass}*{speed}"}]}])  # fmt: skip
    named = asyncio.run(mark(item, "a", "3 J", golden.convert, SETTINGS, golden.run_tool, signatures=context))
    assert (named.outcome, named.error_category, named.misconception_id) == (
        "incorrect", "misconception", "mc.phy.o.ke_without_square")  # fmt: skip
    right = asyncio.run(mark(item, "a", "9 J", golden.convert, SETTINGS, golden.run_tool, signatures=context))
    assert right.outcome == "correct"


def test_undecided_rules_reported() -> None:
    assert UNDECIDED_RULES == frozenset({"sign_of_g_flipped"})


def _structured() -> dict[str, Any]:
    data = golden.load()["structured"]
    return data["items"]["ke_then_speed"]


def test_mark_without_signatures_unchanged() -> None:
    """A caller that passes no misconception library gets the verdict it always had."""
    item = golden.load()["numeric"]["items"]["speed"]
    plain = asyncio.run(mark(item, "a", "7 m/s", golden.convert, SETTINGS, golden.run_tool))
    library = asyncio.run(mark(item, "a", "7 m/s", golden.convert, SETTINGS, golden.run_tool,
                               signatures=SignatureContext(misconceptions=[])))  # fmt: skip
    assert replace(plain, check_ids=()) == replace(library, check_ids=()) and plain.misconception_id is None
    data = golden.load_signatures()
    seeded = data["items"]["ke_trolley"]
    without = asyncio.run(mark(seeded, "a", "3 J", golden.convert, SETTINGS, golden.run_tool))
    assert (without.outcome, without.error_category, without.misconception_id) == ("incorrect", "value", None)
    context = SignatureContext(misconceptions=data["misconceptions"])
    named = asyncio.run(mark(seeded, "a", "3 J", golden.convert, SETTINGS, golden.run_tool, signatures=context))
    assert (named.outcome, named.error_category, named.misconception_id) == (
        "incorrect", "misconception", "mc.phy.o.ke_without_square")  # fmt: skip
    assert len(named.check_ids) > len(without.check_ids)  # the transform's math_evaluate check is recorded


def test_structured_parts_and_payloads() -> None:
    """Each part is marked on its own and its verdict is a valid learning-event payload; an A mark never stands
    without its M (ASM-17)."""
    item = _structured()
    verdicts = asyncio.run(mark_structured(item, {"a": "9 J", "b": "3 m/s"}, golden.convert, SETTINGS,
                                           golden.run_tool))  # fmt: skip
    assert set(verdicts) == {"a", "b"}
    for verdict in verdicts.values():
        _payload(verdict)
        passed = {c["criterion_id"] for c in verdict.criteria if c["result"] == "pass"}
        assert not ({"A1"} <= passed and "M1" not in passed)


def _payload(verdict: Verdict) -> None:
    payload = verdict.payload(verdict_id="01J9ZZTESTVERD1CT000000000", attempt_id="01J9ZZTESTATTEMPT000000000",
                              closes_opportunity=True)  # fmt: skip
    validate("learning/learning-event#/$defs/payload_verdict", payload)


@pytest.mark.parametrize(
    "earlier,later,awarded,carried",
    [
        ("18 J", "8.49 m/s", 2, True),
        ("0.018 kJ", "30.5 km/h", 2, True),
        ("8 J", "5.66 m/s", 2, True),
        ("18 J", "7 m/s", 0, False),
        ("18 J", "6 m/s", 2, False),
    ],
)
def asm06_follow_through(request, earlier, later, awarded, carried):
    """Wrong (a) never earns its own marks or the later part's KC credit; consistent (b) does."""
    from pack_builder.follow_through import problems

    d, _ = request.getfixturevalue("assessment_desk")
    for misconception in d.content.records["misconceptions"].values():
        misconception.setdefault("signatures", [])
    own_a, own_b = "kc.mth.o.number.add", "kc.mth.o.number.multiply"
    item = copy.deepcopy(_structured())
    item["kc_ids"] = [own_a, own_b]
    item["parts"][0]["kc_ids"] = [own_a]
    item["parts"][1]["kc_ids"] = [own_b]
    assert problems([item]) == []
    verdicts = asyncio.run(mark_structured(item, {"a": earlier, "b": later}, golden.convert, SETTINGS, golden.run_tool))
    assert verdicts["a"].marks_awarded == 0
    assert verdicts["b"].marks_awarded == awarded
    assert any(c.get("follow_through") for c in verdicts["b"].criteria) == carried
    assert verdicts["b"].provenance
    if carried:
        assert verdicts["b"].check_ids, "recomputation cites its worker checks"
    state = d._new("practice", "mathematics")
    typed = {
        "parts": [
            {"part_id": pid, "kind": "numeric", "value": text.rsplit(" ", 1)[0], "unit": text.rsplit(" ", 1)[1]}
            for pid, text in (("a", earlier), ("b", later))
        ]
    }
    _, events, transcript = d._attempt_events(state, item, verdicts, typed, 1000)
    d.learner.record_batch(events, extra=lambda conn, stored: transcript())
    rows = d.learner.conn.execute("SELECT kc_ids,outcome,step_id FROM attempts ORDER BY step_id").fetchall()
    assert [(json.loads(k)[0]["kc_id"], outcome, step) for k, outcome, step in rows] == [
        (own_a, "incorrect", "1"),
        (own_b, "correct" if awarded else "incorrect", "2"),
    ]
    assert all(len(json.loads(k)) == 1 for k, _, _ in rows)
    from agent_core.engine.assessment.remark import remark_withdrawn

    corrected = copy.deepcopy(item)
    corrected["id"] = "itm.phy.o.energy.9799"
    corrected["parts"][1]["ecf"] = False
    corrected["parts"][1].pop("follow_through")
    corrected["parts"][1]["answer"]["value"] = "5"
    d.content.records["items"][corrected["id"]] = corrected
    d.run_tool, d._convert = golden.run_tool, golden.convert
    result = asyncio.run(remark_withdrawn(d, item["id"], corrected["id"]))
    assert result.projections_equal_full_replay and result.original_sha256 == result.retained_sha256
    assert result.changed_results == (1 if awarded else 0)
    assert asyncio.run(remark_withdrawn(d, item["id"], corrected["id"])).appended == 0
    # Build refuses ambiguous ownership rather than credit an earlier part's skill on a multi-KC ECF item.
    missing = copy.deepcopy(item)
    del missing["parts"][1]["kc_ids"]
    assert any("every part tagged" in p for p in problems([missing]))
    foreign = copy.deepcopy(item)
    foreign["parts"][1]["kc_ids"] = ["kc.mth.o.number.foreign"]
    assert any("must belong" in p for p in problems([foreign]))


def test_follow_through_mock_part_evidence(request):
    """The mock's criteria totals and persisted part evidence agree on ECF; no credit reaches the earlier KC."""
    from test_m16_assessment import KC, start_mock

    d, _ = request.getfixturevalue("assessment_desk")
    paper = d.content.records["mock_papers"]["mock.mth.o.fixture"]
    question = paper["sections"][0]["questions"][0]
    structured = copy.deepcopy(_structured())
    structured.update(
        id=question["item_id"], stem="Synthetic energy then speed", kc_ids=[KC, "kc.mth.o.number.multiply"]
    )
    for part, kc in zip(structured["parts"], structured["kc_ids"], strict=True):
        part["kc_ids"] = [kc]
    structured["parts"][0]["mark_points"][0]["method_lines"] = ["0.5*2*3^2"]
    d.content.records["items"][structured["id"]] = structured
    question.update(marks=4, kc_ids=structured["kc_ids"])
    paper["sections"][0].update(questions=[question], marks=4, item_types=["structured"])
    paper["total_marks"] = 4
    d.content.kcs["kc.mth.o.number.multiply"] = replace(d.content.kcs[KC], kc_id="kc.mth.o.number.multiply")
    for misconception in d.content.records["misconceptions"].values():
        misconception.setdefault("signatures", [])
    d.run_tool = golden.run_tool
    d._convert = golden.convert
    exam = start_mock(d)
    answer = {
        "parts": [
            {"part_id": "a", "kind": "numeric", "value": "18", "unit": "J"},
            {"part_id": "b", "kind": "numeric", "value": "8.49", "unit": "m/s"},
        ]
    }
    answer["working"] = [{"part_id": "a", "latex": "2*3^2"}]
    d.save_mock_answer(exam["exam_id"], question["question_id"], answer, False)
    report = asyncio.run(d.submit_mock(exam["exam_id"]))
    assert report["score"] == 2 and report["max_score"] == 4
    rows = d.learner.conn.execute("SELECT kc_ids,outcome FROM attempts ORDER BY step_id").fetchall()
    assert [(json.loads(k)[0]["kc_id"], outcome) for k, outcome in rows] == [
        (KC, "incorrect"),
        ("kc.mth.o.number.multiply", "correct"),
    ]
