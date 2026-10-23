"""Round 13, the tutoring-flow gaps the M25 journeys recorded (JRN-04, JRN-06, PRD-05), at unit level: the first wrong
line's error and the line later lines depend on (ASM-09, API-12, UXS-16), worded steps kept unchecked (VER-27), journal
rows checked entry by entry (VER-22, ASM-07), the Diagnoser's KC candidates ranked by the question (AGT-01), the
faster tutor in the router (UXS-03, MDL-05), and a numeric misconception's fix reaching the Coach (PRM-15, CUR-18).
The journeys play the same behaviour end to end (test_m25a_snap_and_working, test_m25b_numbers_and_answers). Every
question, line and record here is synthetic."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.engine import ledger_input, slice, team
from agent_core.engine.prompt_inputs import misconception_lines
from agent_core.engine.state import SessionState
from agent_core.engine.ui import error_of


def test_worded_steps_are_never_algebra() -> None:
    """VER-27, VER-03: a step written in words is kept unchecked; maths with function names or Greek letters is not
    worded."""
    assert slice.worded("divide both sides by two")
    assert slice.worded("so x is the answer here")
    for maths in ("2(x + 3) = 14", "x = 5.5", "sin(theta) = 0.5", "\\frac{1}{2} g t^2 = 45", "y = log(x)"):
        assert not slice.worded(maths), maths


def test_first_error_named_and_later_lines_name_it() -> None:
    """ASM-09, UXS-15: the first wrong line carries its TABLE VER-06a category; a later line says which line its
    error is carried from; a worded line says no tool checked it."""
    first = slice.LineResult("2x + 3 = 14", "incorrect", "chk_aaa", "dropped_term")
    later = slice.LineResult("2x = 11", "correct", "chk_bbb", None, carried_forward=True, first_error=1)
    words = slice.LineResult("divide both sides by two", "unchecked", None, worded=True)
    assert slice.line_reason(first) == "dropped_term"
    assert "carried forward from line 2" in (slice.line_reason(later) or "")
    assert slice.line_reason(words) == slice.WORDED_REASON
    assert error_of("dropped_term") == {"category": "dropped_term", "message_key": "board.error.dropped_term"}
    assert error_of("unbalanced") == {"category": "other", "message_key": "board.error.other"}, "outside VER-06a"
    assert error_of(None) is None


def _journal(rows: list[list[str]]) -> list[dict[str, Any]]:
    return [{"type": "ledger_table", "template": "journal", "columns": ["Date", "Particulars", "Folio", "Dr", "Cr"],
             "rows": rows, "text_fallback": ""}]  # fmt: skip


def test_journal_rows_grouped_into_entries() -> None:
    """VER-22, ASM-07: a new date, or a debit after the entry's credits, starts the next entry; a blank date continues
    the one before."""
    rows = [["1 Mar", "Equipment", "", "5000", ""], ["", "Cash", "", "", "2500"], ["", "Payables", "", "", "2500"],
            ["", "Rent", "", "300", ""], ["", "Cash", "", "", "300"], ["2 Mar", "Wages", "", "80", ""],
            ["2 Mar", "Cash", "", "", "80"]]  # fmt: skip
    grouped = ledger_input.entries(_journal(rows))
    assert [[line["account"] for line in e["lines"]] for e in grouped] == [
        ["Equipment", "Cash", "Payables"], ["Rent", "Cash"], ["Wages", "Cash"]]  # fmt: skip
    assert [e["date"] for e in grouped] == ["1 Mar", None, "2 Mar"]
    assert len(ledger_input.response(_journal(rows))) == 7, "the flat lines the marker reads are unchanged"


def test_journal_reason_names_the_first_unbalanced_entry() -> None:
    """VER-22: the reason gives the tool's difference in total and the first entry that does not balance, with its
    accounts and the tool's own totals."""
    grouped = [{"date": "1 Mar", "lines": [{"account": "Equipment"}, {"account": "Cash"}]},
               {"date": "2 Mar", "lines": [{"account": "Rent"}, {"account": "Cash"}]}]  # fmt: skip
    value = {"all_balanced": False, "trial_balance": {"difference": "100.00"},
             "entries": [{"balanced": True, "total_debit": "5000.00", "total_credit": "5000.00"},
                         {"balanced": False, "total_debit": "300.00", "total_credit": "200.00"}]}  # fmt: skip
    reason = ledger_input.ledger_reason(value, grouped)
    assert "not balance" in reason and "100.00" in reason and "2 Mar" in reason and "Rent, Cash" in reason
    assert "300.00" in reason and "200.00" in reason and len(reason) <= 300
    assert "balances" in ledger_input.ledger_reason({"all_balanced": True}, grouped)


@dataclass
class _Passage:
    kc_ids: tuple[str, ...]


@dataclass
class _Hit:
    passage: _Passage


@dataclass
class _Index:
    """A pack index with one long topic whose question-matching KC sorts last by id."""

    topic_kcs: dict[str, list[str]]
    hits: list[_Hit]
    entries: list[tuple[str, str, float]] = field(default_factory=list)
    settings: Settings = field(default_factory=Settings)

    def kcs_in_topic(self, topic: str) -> list[str]:
        return sorted(self.topic_kcs.get(topic, []))

    def search(self, query: str, limit: int = 5, **_: Any) -> list[_Hit]:
        return self.hits[:limit]

    def curriculum_search(self, query: str, limit: int = 8, **_: Any) -> list[tuple[str, str, float]]:
        return self.entries[:limit]


def test_diagnoser_candidates_keep_the_kc_the_question_is_about() -> None:
    """AGT-01, LRN-06: the cap never drops the KC the question's words find, however many KCs its topic has."""
    many = [f"kc.phy.o.energy.k{n:02d}" for n in range(30)]
    wanted = "kc.phy.o.motion.free_fall"
    index = _Index({"cur.phy.o.big": [*many, wanted]}, [_Hit(_Passage((wanted,)))])
    ranked = team.ranked_kcs(index, "A stone is dropped from rest.", ["cur.phy.o.big"], 20)
    assert ranked[0] == wanted and len(ranked) == 20
    plain = team.ranked_kcs(_Index({"cur.phy.o.big": many}, []), "anything", ["cur.phy.o.big"], 5)
    assert plain == many[:5], "with no match the topic's KCs in order"


def mdl05_faster_tutor_serves_fast_tier() -> None:
    """UXS-03, MDL-05 (D103): with `faster_tutor` on, a strong-tier role is served from the fast tier (the tier its
    call record, and so its `status`, names); the background Reflector and the fast roles keep theirs. The stored
    preference reaching the router is `test_d103_faster_tutor_and_wake_word_preferences`."""
    import yaml
    from agent_core.engine.assembly import CORE
    from agent_core.router.config import load
    from agent_core.router.core import Router

    router = Router(load(yaml.safe_load((CORE / "router" / "router.yaml").read_text())), Settings(), {})
    assert router.tier_of("solver") == "strong" and router.tier_of("coach") == "fast"
    router.prefer_fast = lambda: True
    assert router.tier_of("solver") == "fast"
    assert router.tier_of("reflector") == "strong", "a background role keeps its tier"
    assert router.tier_of("coach") == "fast"


def test_numeric_misconception_match_carries_its_fix() -> None:
    """PRM-15, CUR-18: a misconception a numeric signature matched (no option carries it) reaches the Coach with the
    pack's fix; a choice item's option feedback still comes first."""
    state = SessionState("ses_01JZ0000000000000000000R13")
    item = {"id": "itm.test", "kc_ids": [], "parts": [{"id": "a", "answer": {"kind": "numeric", "value": "4"}}]}
    state.practice = {"item": item, "part": "a", "verdicts": ["incorrect"], "misconception_id": "mc.phy.o.test_idea"}
    fixes = {"mc.phy.o.test_idea": "Multiply the mass by g first."}
    lines = misconception_lines(state, lambda mc: fixes.get(mc, ""))
    assert lines == ["matched misconception [1] mc.phy.o.test_idea; its fix: Multiply the mass by g first."]
    assert misconception_lines(state) == ["matched misconception [1] mc.phy.o.test_idea"]


@pytest.mark.parametrize("confidence, expected", [("high", 0.9), ("medium", 0.75), ("low", 0.5), (None, 0.5)])
def test_diagnoser_confidence_as_kc_confidence(confidence: str | None, expected: float) -> None:
    """LRN-06: an ad-hoc attempt's KC tags come from the Diagnoser with its confidence as a number (the projection
    clips it to `obs_diagnoser_clip`)."""
    from agent_core.engine.turn import Engine

    engine = SimpleNamespace(state=SessionState("ses_01JZ0000000000000000000R13"),
                             diagnosis=SimpleNamespace(output={"confidence": confidence}),
                             deps=SimpleNamespace(settings=Settings()))  # fmt: skip
    assert Engine._kc_source(engine) == ("diagnoser", expected)  # type: ignore[arg-type]
