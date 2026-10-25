"""Synthetic visual events for API and browser integration checks, never a model substitute in the app."""
import hashlib
import json
from pathlib import Path

from agent_core.engine.events import new_id
from agent_core.engine.sketch import SketchContext, resolve
from agent_core.engine.state import Board, BoardStep
from agent_core.engine.ui import step_event

ROOT = Path(__file__).resolve().parents[3]


async def seed_visuals(core, session_id):
    entry = core.sessions[session_id]
    engine = core._engine(entry)
    events = engine.events
    turn = next(m["turn_id"] for m in reversed(entry.state["messages"]) if m["role"] == "tutor")
    events.begin_turn(turn)
    events._index = max(p["index"] for p in entry.state["parts"].values()) + 1
    problem = engine.state.problem
    board = Board(problem_key=f"{problem.problem_id}:{hashlib.sha256(problem.statement.encode()).hexdigest()[:16]}")
    engine.state.board = board
    line = BoardStep(new_id("stp"), 0, "x = 4", "Read the end point", "tutor", "final")
    board.steps.append(line)
    part = events.start_part("board")
    events.emit({"type": "board.reset", "board_id": board.board_id, "part_id": part, "reason": "new_problem",
                 "problem": {"text": "Match the point shown on the diagram", "latex": None}})
    events.emit(step_event(board.board_id, line))
    events.emit({"type": "board.annotate", "board_id": board.board_id, "annotation_id": new_id("ann"),
                 "mark": "circle", "target": {"step_id": line.step_id, "terms": "t2", "visual_id": None,
                                              "part_id": None}, "to": None, "note": None})
    events.end_part(part)
    visuals = {}
    for name in ("number-line", "function-graph", "free-body", "cycle-diagram"):
        spec = json.loads((ROOT / f"packages/renderers/fixtures/visuals/{name}.json").read_text())["spec"]
        visual = new_id("vis")
        spec["visual_id"] = visual
        visual_part = events.start_part("visual")
        events.emit({"type": "visual.spec", "part_id": visual_part, "visual_id": visual, "spec": spec})
        events.end_part(visual_part)
        engine.state.shown_visuals.append({"visual_id": visual, "kind": spec["type"],
                                          "parts": [p["id"] for p in spec["parts"] if p.get("focusable")]})
        visuals[name] = visual

    async def no_tool(name, args):
        return None, None

    drawing = await resolve({"sketch_version": 1,
                             "frame": {"visual_id": None, "x_min": 0, "x_max": 10, "y_min": 0, "y_max": 10},
                             "elements": [{"kind": "line", "from": [0, 0], "to": [3, 4]}], "checks": []},
                            SketchContext(guard=lambda _: True, traced=lambda _: True), no_tool)
    sketch_part = events.start_part("visual")
    events.emit({"type": "visual.sketch", "part_id": sketch_part, "sketch": drawing})
    events.end_part(sketch_part)
    events.turn_id = None
    core.persist(entry)
    return {"visuals": visuals, "board": board.board_id, "sketch": drawing["sketch_id"], "part": part,
            "sketch_part": sketch_part, "line": line.step_id}
