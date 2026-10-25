"""M43: annotations anchored to ids (VSL-40, D103) and the board line's term split they address (API-12)."""

from fractions import Fraction
from typing import Any

import pytest
from agent_core.contracts import errors as contract_errors
from agent_core.engine.annotations import split_terms
from agent_core.engine.state import Problem, SessionState
from agent_core.engine.ui import HandlerError, update_board


def _op(op: str, **kw: Any) -> dict[str, Any]:
    base = {"op": op, "step": None, "latex": None, "reason": None, "owner": None, "status": None, "terms": [],
            "prompt": None, "check_id": None, "mark": None, "part": None, "to": None}  # fmt: skip
    return {**base, **kw}


def _board() -> SessionState:
    state = SessionState("ses")
    state.problem = Problem("p", "2x - 3 = 7", "p#s")
    update_board([_op("add_step", latex="2x - 3 = 7", owner="tutor", status="final"),
                  _op("add_step", latex="2x = 4", owner="student", status="final")], state, {Fraction(4)})  # fmt: skip
    state.shown_visuals = [{"visual_id": "vis_01JZ0000000000000000000001", "parts": ["axis.x", "curve.f"]}]
    return state


def test_vsl40_terms_split_at_top_level() -> None:
    line = "\\frac{a+b}{2} - 3x = 7"
    assert [line[t["start"] : t["end"]] for t in split_terms(line)] == ["\\frac{a+b}{2}", "- 3x", "7"]
    assert [t["term_id"] for t in split_terms("a = -b + c")] == ["t1", "t2", "t3"]


def test_vsl40_board_step_carries_terms() -> None:
    state = _board()
    events = update_board([_op("add_step", latex="x = 2", owner="tutor", status="final")], state, {Fraction(2)}).events
    assert events[0]["terms"] == [{"term_id": "t1", "start": 0, "end": 1}, {"term_id": "t2", "start": 4, "end": 5}]
    assert contract_errors("api/events#/$defs/ev_board_step", events[0]) == []


def vsl40_unknown_target_dropped() -> None:
    state = _board()
    ops = [
        _op("annotate", mark="circle", step=9),  # no such step
        _op("annotate", mark="underline", step=1, terms=["t7"]),  # no such term
        _op("annotate", mark="circle", part="force.weight"),  # no visual on screen holds it
        _op("annotate", mark="arrow", step=1, terms=["t1"]),  # an arrow with no end
        _op("annotate", mark="strike", step=2, terms=["t1"]),  # never through the student's writing
        _op("annotate", mark="margin_note", step=1, reason="subtract 9 from both sides"),  # 9 is not verified
    ]
    result = update_board(ops, state, set())
    assert result.applied and result.events == []  # nothing is placed by position
    assert [d["reason"] for d in result.dropped] == ["step_unknown", "terms_unknown", "part_not_on_screen",
                                                     "arrow_without_end", "strike_not_on_tutor_line",
                                                     "note_number_unverified"]  # fmt: skip
    # Resolvable targets are emitted by id: a term range, a part on screen, an arrow between terms, a look-here mark
    # on the student's line and a short margin note.
    ok = update_board([
        _op("annotate", mark="circle", step=1, terms=["t1-t2"]),
        _op("annotate", mark="underline", part="curve.f"),
        _op("annotate", mark="arrow", step=1, terms=["t2"], to="t3"),
        _op("annotate", mark="look_here", step=2, terms=["t1"]),
        _op("annotate", mark="margin_note", step=1, reason="add 3 to both sides"),
    ], state, {Fraction(3)})  # fmt: skip
    assert ok.dropped == [] and [e["mark"] for e in ok.events] == ["circle", "underline", "arrow", "look_here",
                                                                   "margin_note"]  # fmt: skip
    circle, part, arrow, look, note = ok.events
    assert circle["target"] == {"step_id": state.board.steps[0].step_id, "terms": "t1-t2", "visual_id": None,
                                "part_id": None}  # fmt: skip
    assert part["target"]["visual_id"] == "vis_01JZ0000000000000000000001" and part["target"]["part_id"] == "curve.f"
    assert arrow["to"]["terms"] == "t3" and look["target"]["step_id"] == state.board.steps[1].step_id
    assert note["note"] == "add 3 to both sides"
    for event in ok.events:
        assert contract_errors("api/events#/$defs/ev_board_annotate", event) == []


def vsl40_closed_vocabulary() -> None:
    state = _board()
    # A mark outside TABLE VSL-40a fails the tutor-turn contract, and so does any coordinate field.
    with pytest.raises(HandlerError):
        update_board([_op("annotate", mark="scribble", step=1)], state, set())
    with pytest.raises(HandlerError):
        update_board([{**_op("annotate", mark="circle", step=1), "x": 120, "y": 40}], state, set())
    # A mark on any op but annotate is refused too.
    with pytest.raises(HandlerError):
        update_board([_op("highlight", step=1, mark="circle")], state, set())
