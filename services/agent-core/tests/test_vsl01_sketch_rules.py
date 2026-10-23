"""VSL-01 with the online sketches of VSL-43 (D103, D106): no tutor turn carries a drawing, and a turn served by a
local model carries no request for one either. Either is dropped before the gates, shows nothing of it and is logged
`sketch_not_allowed`; the local decoding schema and the Coach's prompt never name the request. The model replies
are synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.engine.assembly import bundled_schemas
from agent_core.prompts.builder import output_contract
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor

SAFE = "Which quantities does the question give you, and which one does it ask for?"
SKETCH = {"frame": {"x": [0, 10], "y": [0, 10]}, "elements": [{"type": "line", "from": [0, 0], "to": [5, 5]}]}


class Recorder:
    def __init__(self) -> None:
        self.lines: list[dict[str, Any]] = []

    def log(self, level: str, component: str, event: str, **fields: Any) -> None:
        self.lines.append({"level": level, "component": component, "event": event, **fields})


def vsl01_local_model_sketch_rejected(tmp_path: Path) -> None:
    coach = [tutor(SAFE, sketch_wanted="the ball's path up and down"), tutor(SAFE, sketch=SKETCH)]

    async def scenario() -> None:
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps() * 2, "checker": checker_steps() * 2,
                                                 "coach": coach})  # fmt: skip
        recorder = Recorder()
        engine.logger = recorder
        try:
            first = await engine.start_problem(STATEMENT)
            second = await engine.student_turn("I'm not sure where to start")
        finally:
            await close(engine)
        for result in (first, second):
            assert result.status == "complete" and result.tutor_turn is not None, result.stop_reason
            assert result.tutor_turn["say"] == SAFE, "the rest of the turn is shown as it was"
            assert not {"sketch", "sketch_wanted"} & set(result.tutor_turn), "nothing of a sketch is kept"
        dropped = [line for line in recorder.lines if line["event"] == "sketch_not_allowed"]
        assert [line["fields"] for line in dropped] == [["sketch_wanted"], ["sketch"]]
        assert all(line["local"] for line in dropped)
        assert "the ball's path" not in json.dumps(engine.state.transcript), "nothing of the request is kept"

    asyncio.run(scenario())


def test_vsl01_local_grammar_never_names_the_sketch_request() -> None:
    """The decoding schema (the local grammar) and the Coach's output summary leave out `sketch_wanted` (D106)."""
    schema = bundled_schemas()["agents/tutor-turn"]
    assert "sketch_wanted" not in schema["properties"] and "sketch" not in schema["properties"]
    assert "sketch" not in output_contract(schema, "json")
