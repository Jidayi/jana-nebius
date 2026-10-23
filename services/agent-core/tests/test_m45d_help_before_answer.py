"""M45.d: help before the answer (ASM-28, D120) and the chat's automatic title (UXS-68), with synthetic items only."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.contracts import errors
from agent_core.engine.assessment.items import text_latex
from agent_core.engine.assessment.service import AssessmentDesk, Refused
from agent_core.engine.titles import chat_title
from agent_core.learner.mastery import MasteryParams
from agent_core.learner.service import Learner
from agent_core.store.pack_index import PackIndex
from agent_core.store.sqlite import open_database

KC = "kc.phy.o.forces.newton_second"
TOPIC = "cur.phy.o.forces"
RIGHT = "Resultant force equals mass times acceleration"
WRONG = ("Force is always zero", "Mass equals force", "Acceleration is constant")


def item(n: int) -> dict:
    texts = [RIGHT, *WRONG]
    return {
        "id": f"itm.phy.o.forces.{n:04d}",
        "type": "mcq",
        "stem": f"Which statement is Newton's second law? ({n})",
        "kc_ids": [KC],
        "template_id": f"template{n}",
        "review": {"status": "published"},
        "difficulty": {"prior": 0},
        "solution": {"steps": [{"latex": "F = ma", "reason": "Newton's second law", "check_id": "chk_law"}]},
        "parts": [
            {
                "id": "a",
                "prompt": "Choose one",
                "marks": 1,
                "answer": {
                    "kind": "mcq",
                    "diagnostic": False,
                    "options": [
                        {
                            "id": x,
                            "text": texts[i],
                            "correct": i == 0,
                            "misconception_id": None if i == 0 else f"mc.phy.o.e{x}",
                        }
                        for i, x in enumerate("abcd")
                    ],
                },
            }
        ],
    }


def choose(option: str) -> dict:
    return {"parts": [{"part_id": "a", "kind": "mcq", "option_id": option}]}


@pytest.fixture
def desk(tmp_path: Path):
    wall = [1_800_000_000_000]
    conn, _ = open_database(tmp_path / "learner.db", "learner")
    fix = {"text": {"en": "Look again"}}
    library = [{"id": f"mc.phy.o.e{x}", "kc_ids": [KC], "student_name": f"Error {x}", "fix": fix} for x in "bcd"]
    kc = {
        "id": KC,
        "statement": "Newton's second law",
        "node_id": TOPIC,
        "code": "n2",
        "status": "active",
        "prerequisites": [],
        "misconception_ids": [],
    }
    nodes = [
        {"id": "cur.phy.o", "title": "Physics", "kind": "subject"},
        {"id": TOPIC, "title": "Forces", "kind": "topic", "parent_id": "cur.phy.o"},
    ]
    pack = {"pack_id": "pack.phy.o", "version": "1.0.0", "subject": "phy"}
    tables = {
        "items": [item(n) for n in range(1, 6)],
        "kcs": [kc],
        "curriculum_nodes": nodes,
        "misconceptions": library,
    }
    index = PackIndex.from_tables([(pack, tables)])
    learner = Learner.open(
        conn,
        profile_id="0" * 26,
        device_id="f" * 32,
        wall_ms=lambda: wall[0],
        max_skew_ms=Settings().sync_clock_skew_max_ms,
        params=MasteryParams.from_settings(Settings()),
        content=index,
    )
    yield AssessmentDesk(learner, index, Settings(), clock_ms=lambda: wall[0], monotonic_ms=lambda: 0)
    conn.close()


def run(awaitable):
    return asyncio.run(awaitable)


def adopted(reply: dict) -> list[str]:
    """The reply against the adopted contract once the proposed `worked` (contract-additions-m45d.json) is set aside;
    `worked` itself is the adopted `WorkedExampleView`."""
    rest = {k: v for k, v in reply.items() if k != "worked"}
    problems = errors("api/commands#/$defs/PracticeMarked", rest)
    if "worked" in reply:
        problems += errors("api/commands#/$defs/WorkedExampleView", reply["worked"])
    return problems


def asm28_no_reveal_on_first_miss(desk) -> None:
    """After one wrong answer the correct option and the final value are absent; after the second attempt or Don't know
    the worked answer appears with its check."""
    practice = desk.create_practice("physics", [KC], 2)
    shown = practice["current_item"]
    first = run(desk.practice_answer(practice["set_id"], "cli_1", shown["item_id"], choose("b"), 1000))
    assert first["verdict"] == "incorrect" and "worked" not in first
    assert first["next_item"]["item_id"] == shown["item_id"]  # the same question, for a second try
    beyond_question = json.dumps({k: v for k, v in first.items() if k != "next_item"})
    assert RIGHT not in beyond_question and "F = ma" not in beyond_question and '"correct": true' not in beyond_question
    assert "correct" not in json.dumps(first["next_item"])  # the options again, none of them marked
    assert adopted(first) == []

    second = run(desk.practice_answer(practice["set_id"], "cli_2", shown["item_id"], choose("c"), 1000))
    assert second["verdict"] == "incorrect" and second["next_item"]["item_id"] != shown["item_id"]
    worked = second["worked"]
    assert worked["steps"][0]["latex"] == "F = ma" and worked["steps"][0]["check_id"] == "chk_law"
    assert worked["final_answer"]["latex"] == text_latex(RIGHT) and worked["final_answer"]["check_id"]
    assert adopted(second) == []

    # Don't know on the next question: its worked answer, nothing marked, and the set moves on.
    nxt = second["next_item"]
    revealed = desk.practice_reveal(practice["set_id"], nxt["item_id"])
    assert revealed["worked"]["final_answer"]["latex"] == text_latex(RIGHT) and revealed["next_item"] is None
    assert errors("api/commands#/$defs/WorkedExampleView", revealed["worked"]) == []
    with pytest.raises(Refused):
        desk.practice_reveal(practice["set_id"], nxt["item_id"])  # no longer the question shown


def test_asm28_a_right_second_try_settles_without_a_worked_answer(desk) -> None:
    practice = desk.create_practice("physics", [KC], 1)
    shown = practice["current_item"]
    run(desk.practice_answer(practice["set_id"], "cli_1", shown["item_id"], choose("d"), 500))
    right = run(desk.practice_answer(practice["set_id"], "cli_2", shown["item_id"], choose("a"), 500))
    assert right["verdict"] == "correct" and "worked" not in right and right["next_item"] is None


def test_asm28_a_retried_request_is_the_same_reply(desk) -> None:
    practice = desk.create_practice("physics", [KC], 1)
    shown = practice["current_item"]
    once = run(desk.practice_answer(practice["set_id"], "cli_same", shown["item_id"], choose("b"), 500))
    assert run(desk.practice_answer(practice["set_id"], "cli_same", shown["item_id"], choose("b"), 500)) == once


def test_uxs68_title_is_six_words_with_no_value() -> None:
    assert chat_title("A ball is thrown up at 20 m/s. How high does it go?") == "A ball is thrown up at"
    assert chat_title("**Why** does ice float on water when it is solid?") == "Why does ice float on water"
    assert chat_title("\\(2x + 3 = 7\\)") == ""
    assert chat_title("\n\n  Balance  \\(H_2 + O_2\\)\nsecond line") == "Balance"
