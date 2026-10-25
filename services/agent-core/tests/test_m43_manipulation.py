"""M43: manipulable visuals as the student's turn (VSL-42, D103): a placement on a number line, a function graph or a
free-body diagram is checked by the same verification tool, with the same result, as typing the value."""

import asyncio
from pathlib import Path
from typing import Any

import pytest
from agent_core.contracts import errors as contract_errors
from agent_core.engine.manipulation import ManipulationRefused, check_typed, typed_line
from engine_harness import make_engine
from test_m12d_accounting import call

LOOP = asyncio.new_event_loop()
VISUALS = {
    "number_line": ("vis_01JZ00000000000000000000N1", ["sol.from"], {"sol.from": "4"}, "4", "5"),
    "function_graph": ("vis_01JZ00000000000000000000G1", ["f.root1"], {"f.root1": "(2, 0)"}, "(2, 0)", "(3, 0)"),
    "free_body": ("vis_01JZ00000000000000000000F1", ["W"], {"W": "49 N at 270"}, "49 N at 270", "49 N at 90"),
}


async def run(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """The worker's check, in process through its real server code (the Checker's call)."""
    reply = call(name, args)
    if "result" not in reply:
        return None, None
    return reply["result"]["value"], reply["result"]["check"]["check_id"]


def _engine(tmp_path: Path) -> Any:
    engine, _ = LOOP.run_until_complete(make_engine(tmp_path, {}, worker=False))
    engine.state.shown_visuals = [{"visual_id": v[0], "parts": v[1], "kind": kind} for kind, v in VISUALS.items()]
    return engine


def vsl42_manipulation_checked_by_tools(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    for kind, (visual_id, parts, keys, right, wrong) in VISUALS.items():
        for value, expected in ((right, "correct"), (wrong, "incorrect")):
            step_id = engine.open_manipulation(visual_id, keys, "Place it on the diagram")
            await_event = next(
                f["event"] for f in reversed(engine.events.frames) if f.get("event", {}).get("type") == "visual.await"
            )
            assert await_event["part_ids"] == parts and contract_errors("api/events#/$defs/ev_visual_await",
                                                                        await_event) == []  # fmt: skip
            body = {"client_answer_id": "cli_01JZ0000000000000000000001", "step_id": step_id,
                    "values": [{"part_id": parts[0], "value": value}]}  # fmt: skip
            assert contract_errors("api/commands#/$defs/ManipulationSubmit", body) == []
            result = LOOP.run_until_complete(engine.answer_manipulation(visual_id, body, run))
            assert contract_errors("api/commands#/$defs/ManipulationResult", result) == []
            assert result["status"] == expected, (kind, value)
            assert result["check_id"] is not None  # marked by the verification tool, never by the model
            # Typing the same value is checked by the same tool with the same result.
            typed = typed_line(kind, parts[0], value)
            assert LOOP.run_until_complete(check_typed(kind, typed, keys[parts[0]], "x", run))[0] == expected
            # The result is the student's board line with its status (UXS-16).
            line = engine.state.board.steps[-1]
            assert line.step_id == step_id and line.owner == "student" and line.status == expected
            assert line.latex == typed and engine.state.manipulation is None


def test_vsl42_refusals(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    visual_id, _parts, keys, _, _ = VISUALS["number_line"]
    with pytest.raises(ManipulationRefused):
        engine.open_manipulation("vis_01JZ00000000000000000000X1", keys, "?")  # not on screen
    with pytest.raises(ManipulationRefused):
        engine.open_manipulation(visual_id, {"axis": "1"}, "?")  # not an adjustable part
    step_id = engine.open_manipulation(visual_id, keys, "Place x")
    body = {"client_answer_id": "cli_01JZ0000000000000000000002", "step_id": step_id,
            "values": [{"part_id": "other", "value": "4"}]}  # fmt: skip
    with pytest.raises(ManipulationRefused):
        LOOP.run_until_complete(engine.answer_manipulation(visual_id, body, run))

    # Without a worker the line is unchecked, never guessed.
    async def unavailable(name: str, args: dict[str, Any]) -> tuple[None, None]:
        return None, None

    body["values"] = [{"part_id": "sol.from", "value": "4"}]
    assert LOOP.run_until_complete(engine.answer_manipulation(visual_id, body, unavailable))["status"] == "unchecked"
