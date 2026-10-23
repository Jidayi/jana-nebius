"""PRV-29 S2 board/visual state and explicit local/cloud student-photo requests, with foreign-field canaries."""

from __future__ import annotations

import ast
import asyncio
import json
from pathlib import Path

import pytest
from agent_core.engine.events import new_id
from agent_core.engine.state import BoardStep
from engine_harness import STATEMENT, checker_steps, close, make_engine, reply, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.harness.context import audit_requests
from test_capture_reader_schema import reader_regions
from test_m11d_images import _photo_with_gps
from test_m11f_vision import masked, reader_engine, run
from test_m14a_roles import diagnosis


def prv29_tutor_context_is_structured(tmp_path: Path) -> None:
    async def check() -> None:
        engine, provider = await make_engine(
            tmp_path,
            {
                "diagnoser": [diagnosis(inference="")] * 4,
                "solver": solver_steps(),
                "checker": checker_steps(),
                "coach": [tutor("Which quantities are given?")] * 5,
            },
            stage="S2",
        )
        foreign = "FOREIGN_SCREEN_CLIPBOARD_WINDOW_CANARY"
        engine.state.screen = foreign
        engine.state.clipboard = foreign
        engine.window_titles = foreign
        try:
            await engine.start_problem(STATEMENT)
            step = BoardStep(new_id("stp"), 1, "u = 14", None, "student", "awaiting")
            engine.state.board.steps.append(step)
            visual = new_id("vis")
            engine.state.shown_visuals = [
                {
                    "visual_id": visual,
                    "parts": ["axis_x", "point_A"],
                    "screenshot": foreign,
                    "other_app": foreign,
                    "clipboard": foreign,
                }
            ]
            await engine.student_turn("Which of my lines should I use?")
            audit = audit_requests(provider.requests)
            assert not audit["failures"] and audit["requests"] > 3 and audit["tutor_contexts"] > 0
            assert foreign not in json.dumps(provider.requests)
            contexts = [
                m["content"]
                for r in provider.requests
                for m in r["messages"]
                if m["role"] == "user" and "<tutor-context>\n" in str(m["content"])
            ]
            assert any("board 1: [student, awaiting] u = 14" in text for text in contexts)
            assert any(visual in text and "axis_x" in text for text in contexts)
            assert all("image_url" not in str(r) for r in provider.requests)
        finally:
            await close(engine)

    asyncio.run(check())


@pytest.mark.parametrize("cloud_on", [False, True])
def test_prv29_tutor_context_is_structured_photo(tmp_path: Path, cloud_on: bool) -> None:
    engine, local, cloud = reader_engine(tmp_path, cloud_on=cloud_on)
    output = json.dumps({"regions": reader_regions(), "refusal": None})
    local.script = cloud.script = {"vision": [reply(output)]}
    try:
        result = run(engine.read_photo(_photo_with_gps(), send_to_cloud=cloud_on, screen=masked, structured=True))
        assert result.status == "read"
        audit = audit_requests([*local.requests, *cloud.requests])
        assert audit["failures"] == [] and audit["requests"] == audit["student_images"] == 1
        assert audit["roles"] == {"vision": 1} and audit["tutor_contexts"] == 0
    finally:
        run(close(engine))


def test_image_request_producers_are_explicit_photo_reader_only() -> None:
    producers = set()
    root = REPO_ROOT / "services/agent-core/agent_core"
    for file in root.rglob("*.py"):
        if "contracts" in file.parts:
            continue
        for node in ast.walk(ast.parse(file.read_text())):
            if isinstance(node, ast.Call) and any(k.arg == "images" for k in node.keywords):
                producers.add(file.relative_to(root).as_posix())
    assert producers == {"engine/vision.py"}
