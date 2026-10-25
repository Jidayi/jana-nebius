"""M43: replay an explanation (UXS-59, D103): from the recorded events and the tutor's words, with no model call and no
network, ending in exactly the board's final state; no audio is ever stored."""

import asyncio
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.contracts import errors as contract_errors
from agent_core.engine.replay import board_replay, final_state
from agent_core.engine.state import Plan, PlanStep, Problem
from engine_harness import close, make_engine, tutor

AUDIO = (".wav", ".mp3", ".ogg", ".opus", ".webm", ".m4a", ".flac", ".pcm", ".aac")


def _turns() -> list[dict[str, Any]]:
    line = {"op": "add_step", "step": None, "reason": None, "owner": "tutor", "status": "final", "terms": [],
            "prompt": None, "check_id": None, "mark": None, "part": None, "to": None}  # fmt: skip
    return [tutor("First move the 3 across.", board=[{**line, "latex": "2x - 3 = 7"}]),
            tutor("Then add 3 to both sides.", board=[{**line, "latex": "\\text{add 3 to both sides}"}])]  # fmt: skip


def _recorded(tmp_path: Path) -> tuple[dict[str, Any], dict[str, Any], int]:
    async def run() -> tuple[dict[str, Any], dict[str, Any], int]:
        engine, provider = await make_engine(tmp_path, {"coach": _turns()})
        try:
            engine.state.problem = Problem("prb_rp", "Solve 2x - 3 = 7.", "prb_rp#statement")
            steps = [PlanStep(1, "2x = 10", "10", None, "chk_RPa"), PlanStep(2, "x = 5", "5", None, "chk_RPb")]
            engine.state.plan = Plan(steps, "5", None, "chk_RPb", "the plan", "x = 5")
            engine.state.check_values.update({"chk_RPa": [Fraction(10)], "chk_RPb": [Fraction(5)]})
            engine.state.step = 1
            await engine.student_turn("can you explain the first step?")
            await engine.student_turn("can you explain the next step?")
            calls = len(provider.requests)
            board = engine.state.board
            steps = {s.step_id: {"latex": s.latex, "owner": s.owner, "status": s.status} for s in board.steps}
            replay = board_replay(engine.persisted, board.board_id)
            assert replay is not None
            # Replaying calls no model: the provider saw nothing more.
            assert len(provider.requests) == calls
            return replay, steps, calls
        finally:
            await close(engine)

    return asyncio.run(run())


def uxs59_replay_without_model(tmp_path: Path) -> None:
    replay, steps, _ = _recorded(tmp_path)
    assert contract_errors("api/commands#/$defs/BoardReplay", replay) == []
    # It ends in exactly the board's final state, with the tutor's words before the lines they explain.
    assert final_state(replay["items"]) == steps and steps
    spoken = [i["spoken_text"] for i in replay["items"] if i["spoken_text"]]
    assert spoken and all("3" in s for s in spoken)
    assert [i["offset_ms"] for i in replay["items"]] == sorted(i["offset_ms"] for i in replay["items"])
    assert replay["duration_ms"] >= replay["items"][-1]["offset_ms"]


def uxs59_no_audio_stored(tmp_path: Path) -> None:
    _recorded(tmp_path)
    # The replay is events and words only: nothing in the app's data directory is audio.
    stored = [p for p in tmp_path.rglob("*") if p.is_file() and p.suffix.lower() in AUDIO]
    assert stored == []
