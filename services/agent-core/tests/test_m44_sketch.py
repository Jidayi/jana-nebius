"""M44: online sketches (VSL-43, VSL-44, D103, D106): validation of the closed vocabulary, the checks of TABLE VSL-44a
and the "not checked" status. Seeded synthetic sketches; no model."""

import asyncio
import json
import random
from fractions import Fraction
from typing import Any

import pytest
from agent_core.contracts import errors as contract_errors
from agent_core.engine.sketch import SketchContext, SketchRefused, resolve, validate

SEED = 20261044
FRAME = {"visual_id": None, "x_min": -10, "x_max": 10, "y_min": -10, "y_max": 10}


def sketch(elements: list[dict[str, Any]], checks: list[dict[str, Any]] | None = None, **extra: Any) -> dict[str, Any]:
    return {"sketch_version": 1, "frame": FRAME, "elements": elements, "checks": checks or [], **extra}


def context(**values: list[Fraction]) -> SketchContext:
    verified = {Fraction(3), Fraction(4), Fraction(5)}
    return SketchContext(values=dict(values), curves={"f.curve": "x^2 - 4"},
                         guard=lambda text: "kill" not in text.lower(), traced=lambda v: v in verified)  # fmt: skip


async def no_tool(name: str, args: dict[str, Any]) -> tuple[None, None]:
    return None, None


async def evaluate(name: str, args: dict[str, Any]) -> tuple[dict[str, Any], str]:
    """math_evaluate for x^2 - 4, as the worker would answer it."""
    x = Fraction(args["values"]["x"])
    return {"exact": str(x * x - 4)}, "chk_eval1"


def run(coro: Any) -> Any:
    return asyncio.run(coro)


def fuzzed(rng: random.Random) -> Any:
    """A broken or hostile request: out-of-bounds coordinates, too many elements or labels, raw SVG or HTML, unverified
    numbers in labels, a guard-refused label, or wrong types."""
    point = lambda: [rng.uniform(-30, 30), rng.uniform(-30, 30)]  # noqa: E731
    choice = rng.randrange(8)
    if choice == 0:
        return sketch([{"kind": "line", "from": point(), "to": point()} for _ in range(rng.randint(1, 30))])
    if choice == 1:
        return sketch([{"kind": "point", "at": [0, 0]}] * 41)
    if choice == 2:
        return sketch([{"kind": "label", "at": [0, 0], "text": "A"}] * 14)
    if choice == 3:
        return {"svg": "<svg><path d='M0 0 L 10 10'/></svg>"}
    if choice == 4:
        return sketch([{"kind": "path", "d": "M0 0 L1 1"}])
    if choice == 5:
        return sketch([{"kind": "label", "at": [1, 1], "text": f"{rng.randint(6, 99)} N"}])
    if choice == 6:
        return sketch([{"kind": "label", "at": [1, 1], "text": "<script>alert(1)</script>"[: rng.randint(5, 25)]}])
    return rng.choice([None, "text", 42, [], {"sketch_version": 2}, sketch([{"kind": "circle", "center": [0, 0],
                                                                           "radius": -1}])])  # fmt: skip


def vsl43_sketch_validation() -> None:
    rng = random.Random(SEED)
    for _ in range(300):
        request = fuzzed(rng)
        try:
            resolved = run(resolve(request, context(), no_tool))
        except SketchRefused:
            continue  # not a sketch at all: nothing shown, a log record for EVL-28
        # Whatever is kept is inside the frame, within the caps, free of markup and of unverified numbers.
        assert contract_errors("visuals/sketch#/$defs/resolved", resolved) == []
        assert len(resolved["elements"]) <= 40 and sum(e["kind"] == "label" for e in resolved["elements"]) <= 12
        for element in resolved["elements"]:
            text = json.dumps(element)
            assert "<" not in text
            assert all(-10 <= v <= 10 for key in ("from", "to", "at") if key in element for v in element[key])
            if element["kind"] == "label":
                assert all(
                    n in (3, 4, 5) for n in [Fraction(t) for t in __import__("re").findall(r"\d+", element["text"])]
                )
    # Each reason is named for the element it drops.
    _, dropped = validate(sketch([{"kind": "point", "at": [0, 0]}, {"kind": "point", "at": [20, 0]},
                                  {"kind": "label", "at": [1, 1], "text": "7 m"},
                                  {"kind": "label", "at": [1, 1], "text": "kill it"}]), context())  # fmt: skip
    assert dropped == [{"element": 1, "reason": "out_of_bounds"}, {"element": 2, "reason": "unverified_number"},
                       {"element": 3, "reason": "guard_refused"}]  # fmt: skip
    with pytest.raises(SketchRefused):
        validate({**sketch([{"kind": "point", "at": [0, 0]}]), "frame": {**FRAME, "x_min": 5, "x_max": 5}}, context())


CASES = [
    # claim, element, against values, the same element moved beyond tolerance
    ("point_value", {"kind": "point", "at": [2, 0]}, {"chk_root": [Fraction(2), Fraction(0)]},
     {"kind": "point", "at": [3, 0]}),
    ("intersection", {"kind": "point", "at": [1, 1]}, {"chk_meet": [Fraction(1), Fraction(1)]},
     {"kind": "point", "at": [1, 2.5]}),
    ("length", {"kind": "line", "from": [0, 0], "to": [3, 4]}, {"chk_len": [Fraction(5)]},
     {"kind": "line", "from": [0, 0], "to": [3, 6]}),
    ("direction", {"kind": "arrow", "from": [0, 0], "to": [3, 4]}, {"chk_vec": [Fraction(3), Fraction(4)]},
     {"kind": "arrow", "from": [0, 0], "to": [4, 3]}),
    ("angle", {"kind": "arc", "center": [0, 0], "radius": 1, "start_deg": 0, "end_deg": 30},
     {"chk_ang": [Fraction(30)]}, {"kind": "arc", "center": [0, 0], "radius": 1, "start_deg": 0, "end_deg": 40}),
    ("label_value", {"kind": "label", "at": [1, 1], "text": "5 N"}, {"chk_f": [Fraction(5)]},
     {"kind": "label", "at": [1, 1], "text": "4 N"}),
]  # fmt: skip


def vsl44_checks_by_claim() -> None:
    for claim, good, values, moved in CASES:
        against = next(iter(values))
        ok = run(
            resolve(sketch([good], [{"element": 0, "claim": claim, "against": against}]), context(**values), no_tool)
        )
        assert ok["checks"] == [{"element": 0, "claim": claim, "result": "pass", "check_id": against}], claim
        assert ok["elements"] == [good] and ok["status"] == "checked", claim
        bad = run(
            resolve(sketch([moved], [{"element": 0, "claim": claim, "against": against}]), context(**values), no_tool)
        )
        assert bad["checks"][0]["result"] == "fail" and bad["elements"] == [], claim  # the failed element is dropped
        assert {"element": 0, "reason": "check_failed"} in bad["dropped"], claim
    # point_on_curve asks the tool for the curve's value at the point's x.
    on_curve = [{"element": 0, "claim": "point_on_curve", "against": "f.curve"}]
    on = run(resolve(sketch([{"kind": "point", "at": [3, 5]}], on_curve),
                     context(), evaluate))  # fmt: skip
    assert on["checks"][0] == {"element": 0, "claim": "point_on_curve", "result": "pass", "check_id": "chk_eval1"}
    off = run(resolve(sketch([{"kind": "point", "at": [3, 8]}], on_curve),
                      context(), evaluate))  # fmt: skip
    assert off["checks"][0]["result"] == "fail" and off["elements"] == []


def vsl44_label_unless_checked() -> None:
    values = {"chk_len": [Fraction(5)]}
    line = {"kind": "line", "from": [0, 0], "to": [3, 4]}
    # Checked: every checkable element passed a check.
    checked = run(
        resolve(sketch([line], [{"element": 0, "claim": "length", "against": "chk_len"}]), context(**values), no_tool)
    )
    assert checked["status"] == "checked"
    # A checkable element left unchecked keeps the not-checked label.
    other = {"kind": "point", "at": [1, 1]}
    partly = run(
        resolve(
            sketch([line, other], [{"element": 0, "claim": "length", "against": "chk_len"}]), context(**values), no_tool
        )
    )
    assert partly["status"] == "not_checked"
    # Only pictorial elements (shapes, layout): never checkable, never "checked".
    shapes = [{"kind": "circle", "center": [0, 0], "radius": 2},
              {"kind": "polygon", "points": [[0, 0], [1, 0], [0, 1]]}]
    picture = run(resolve(sketch(shapes), context(), no_tool))
    assert picture["status"] == "not_checked" and picture["checks"] == []
    # A check the element cannot carry, or one against an unknown value, is not a check that ran.
    wrong = run(
        resolve(sketch([line], [{"element": 0, "claim": "angle", "against": "chk_len"}]), context(**values), no_tool)
    )
    assert wrong["status"] == "not_checked" and wrong["checks"][0]["result"] == "not_checkable"
    # The alt text is the engine's, from the kept elements.
    assert picture["alt"].startswith("Rough sketch: 1 circle, 1 shape")


# --- the sketch around a tutor turn (VSL-43, VSL-44, MDL-33) ----------------------------------------------------------

SLOPE = "a box on a rough slope with the forces acting on it"


def sketch_reply(stall_s: float = 0.0, elements: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    from engine_harness import reply

    request = sketch(elements or [{"kind": "arrow", "from": [0, 0], "to": [0, -5]},
                                  {"kind": "label", "at": [1, -5], "text": "weight"}])  # fmt: skip
    step = reply(json.dumps(request))
    return {**step, "stall_s": stall_s} if stall_s else step


async def online(
    tmp_path: Any,
    coach: list[Any],
    cloud_coach: list[Any],
    settings: Any = None,
    device_class: str | None = "content_only",
) -> Any:
    from agent_core.engine.state import Plan, PlanStep, Problem
    from agent_core.providers.scripted import ScriptedProvider
    from engine_harness import make_engine

    def enable(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True

    from agent_core.config import Settings

    base = settings or Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))
    settings = base.model_copy(update={"sketch_live_kinds": ("forces", "graph", "geometry", "ray_diagram")})
    cloud = ScriptedProvider({"coach": cloud_coach}, kind="cloud")
    engine, local = await make_engine(tmp_path, {"coach": coach}, overrides=enable, cloud=cloud, hardware_class="cloud",
                                      device_class=device_class, worker=False, settings=settings)  # fmt: skip
    engine.deps.router.cloud_on = lambda role: True  # type: ignore[method-assign]
    engine.state.problem = Problem("prb_sk", "A 5 kg box rests on a slope.", "prb_sk#statement")
    engine.state.plan = Plan([PlanStep(1, "W = 49", "49", None, "chk_SKa")], "49", None, "chk_SKa", "plan", "W = 49")
    engine.state.check_values.update({"chk_SKa": [Fraction(49)]})
    engine.state.step = 1
    return engine, local, cloud


def events_of(engine: Any) -> list[dict[str, Any]]:
    return [f["event"] for f in engine.events.frames]


def mdl33_sketch_only_online(tmp_path: Any) -> None:
    from engine_harness import close, tutor

    async def check() -> tuple[Any, Any, Any]:
        engine, local, cloud = await online(tmp_path / "online", [], [tutor("Picture the forces.", sketch_wanted=SLOPE),
                                                                      sketch_reply()])  # fmt: skip
        try:
            await engine.student_turn("can you explain the first step?")
            await engine.sketches.task
            return engine, local, cloud
        finally:
            await close(engine)

    engine, local, cloud = asyncio.run(check())
    coach = [r for r in cloud.requests if r.get("_role") == "coach"]
    assert len(coach) == 2 and local.requests == []
    # The tutor turn's call to the online candidate is offered sketch_wanted; the sketch call is its own.
    assert "sketch_wanted" in json.dumps(coach[0].get("response_format") or coach[0])
    assert "sketch contract" in json.dumps(coach[1]["messages"])
    shown = [e for e in events_of(engine) if e["type"] == "visual.sketch"]
    assert len(shown) == 1 and contract_errors("api/events#/$defs/ev_visual_sketch", shown[0]) == []

    # On a local candidate the decode schema never has sketch_wanted, a reply carrying it is cut and no sketch is made.
    async def local_run() -> Any:
        from agent_core.engine.state import Plan, PlanStep, Problem
        from engine_harness import make_engine

        script = {"coach": [tutor("Picture the forces.", sketch_wanted=SLOPE)]}
        engine, local = await make_engine(tmp_path / "local", script,
                                          worker=False)  # fmt: skip
        engine.state.problem = Problem("prb_sl", "A 5 kg box rests on a slope.", "prb_sl#statement")
        engine.state.plan = Plan([PlanStep(1, "W = 49", "49", None, "chk_SLa")], "49", None, "chk_SLa", "p", "W = 49")
        engine.state.step = 1
        try:
            await engine.student_turn("can you explain the first step?")
            assert engine.sketches.task is None
            return engine, local
        finally:
            await close(engine)

    engine, local = asyncio.run(local_run())
    assert local.requests and all("sketch_wanted" not in json.dumps(r) for r in local.requests)
    assert not [e for e in events_of(engine) if e["type"] == "visual.sketch"]


def vsl43_template_first_sketch_only_without_fit(tmp_path: Any) -> None:
    from engine_harness import close, tutor

    async def check() -> tuple[Any, Any]:
        fits = tutor("Draw the forces.", sketch_wanted="a free body diagram of the box")
        engine, _, cloud = await online(tmp_path, [], [fits, tutor("Picture it.", sketch_wanted=SLOPE), sketch_reply()])
        try:
            await engine.student_turn("can you explain the first step?")
            assert engine.sketches.task is None  # a catalogue kind fits: no sketch call
            await engine.student_turn("can you explain the next step?")
            await engine.sketches.task
            return engine, cloud
        finally:
            await close(engine)

    engine, cloud = asyncio.run(check())
    assert len([r for r in cloud.requests if r.get("_role") == "coach"]) == 3  # two turns, one sketch call
    gates = [(g["gate"], g["fired"]) for t in engine.traces for g in t["gates"] if g["gate"].startswith("sketch")]
    assert gates == [
        ("sketch_template", True),
        ("sketch_call", False),
        ("sketch_template", False),
        ("sketch_call", True),
    ]


def vsl43_speech_never_waits_for_sketch(tmp_path: Any) -> None:
    from agent_core.config import Settings
    from engine_harness import close, tutor

    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), sketch_deadline_ms=500)

    async def check(stall: float, elements: list[dict[str, Any]] | None = None) -> tuple[Any, float, float]:
        engine, _, _ = await online(tmp_path / str(stall), [], [tutor("Picture the forces.", sketch_wanted=SLOPE),
                                                                 sketch_reply(stall, elements)], settings)  # fmt: skip
        try:
            started = asyncio.get_running_loop().time()
            await engine.student_turn("can you explain the first step?")
            said = asyncio.get_running_loop().time() - started
            await engine.sketches.task
            return engine, said, asyncio.get_running_loop().time() - started
        finally:
            await close(engine)

    quick, said_quick, _ = asyncio.run(check(0.0))
    slow, said_slow, done = asyncio.run(check(1.0))
    # The turn (its text and its end) never waits for the sketch call.
    assert said_slow < done - 0.5 and abs(said_slow - said_quick) < 0.5
    events = events_of(slow)
    ended = next(i for i, e in enumerate(events) if e["type"] == "turn.end")
    sketched = next(i for i, e in enumerate(events) if e["type"] == "visual.sketch")
    assert ended < sketched
    # Late: the engine's own line comes with it, never model text.
    texts = [e["delta"] for e in events[sketched:] if e["type"] == "text.delta"]
    assert any("sketched it on the board" in t for t in texts)
    assert not any("sketched it on the board" in e.get("delta", "") for e in events_of(quick))
    # A sketch that fails validation leaves only a log record: nothing shown, nothing said.
    broken, _, _ = asyncio.run(check(0.0, [{"kind": "point", "at": [50, 50]}]))
    after = events_of(broken)
    assert not [e for e in after if e["type"] == "visual.sketch"]


def mdl33_allowance_exhausted_no_sketch(tmp_path: Any) -> None:
    from engine_harness import close, tutor

    class Spent:
        def allows(self) -> bool:
            return False

        def record(self, usd: float, tokens: int) -> None:
            return None

    async def check() -> tuple[Any, Any, Any]:
        engine, _, cloud = await online(tmp_path, [tutor("Picture the forces.", sketch_wanted=SLOPE)],
                                            [sketch_reply()], device_class=None)  # fmt: skip
        engine.deps.router.budget = Spent()
        try:
            result = await engine.student_turn("can you explain the first step?")
            return engine, result, cloud
        finally:
            await close(engine)

    engine, result, cloud = asyncio.run(check())
    assert result.status == "complete" and engine.sketches.task is None
    assert cloud.requests == [] and not [e for e in events_of(engine) if e["type"] == "visual.sketch"]


def vsl43_student_removes_sketch(tmp_path: Any) -> None:
    from agent_core.api import projection
    from agent_core.engine.replay import board_replay
    from engine_harness import close, tutor

    async def check() -> Any:
        engine, _, _ = await online(tmp_path, [], [tutor("Picture the forces.", sketch_wanted=SLOPE), sketch_reply()])
        try:
            await engine.student_turn("can you explain the first step?")
            await engine.sketches.task
            return engine
        finally:
            await close(engine)

    engine = asyncio.run(check())
    state = projection.empty({"session_id": engine.state.session_id}, engine.events.epoch)
    for frame in engine.events.frames:
        projection.apply(state, frame)
    sketch_id = next(e["sketch"]["sketch_id"] for e in events_of(engine) if e["type"] == "visual.sketch")
    part = engine.sketches.shown[sketch_id]
    assert part in state["parts"] and part in engine.persisted
    # "Remove sketch": gone from the engine's record (history and replay are built from it) and the saved session.
    assert engine.sketches.remove(sketch_id) == part
    projection.remove_part(state, part)
    assert part not in engine.persisted and part not in state["parts"]
    assert all(part not in m.get("part_ids", []) for m in state["messages"])
    assert all(r["kind"] != "sketch" for r in engine.persisted.values())
    if engine.state.board.steps:
        replay = board_replay(engine.persisted, engine.state.board.board_id) or {"items": []}
        assert "sketch" not in json.dumps(replay)
    assert engine.sketches.remove(sketch_id) is None  # a second removal finds nothing (404 at the API)


def vsl43_never_replaces_catalogue_visual(tmp_path: Any) -> None:
    from agent_core.engine.sketch_flow import template_for
    from engine_harness import close, tutor

    # A visual the turn asks for, or a catalogue kind the drawing names, is the template: no sketch is made.
    assert template_for(SLOPE, {"visual": [{"type": "free_body"}]}, "physics") == "requested_visual"
    assert template_for("a free body diagram of the box", {}, "physics") == "free_body"
    assert template_for("a ray diagram for the convex lens", {}, "physics") == "ray_diagram"
    assert template_for(SLOPE, {}, "physics") is None

    async def check() -> tuple[Any, Any]:
        fits = tutor("Here are the forces.", sketch_wanted="a free body diagram of the box")
        engine, _, cloud = await online(tmp_path, [], [fits])
        try:
            await engine.student_turn("can you explain the first step?")
            return engine, cloud
        finally:
            await close(engine)

    engine, cloud = asyncio.run(check())
    assert engine.sketches.task is None and len(cloud.requests) == 1
    assert not [e for e in events_of(engine) if e["type"] == "visual.sketch"]


def vsl44_late_sketch_offered_after_turn(tmp_path: Any) -> None:
    from agent_core.config import Settings
    from engine_harness import close, tutor

    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), sketch_deadline_ms=500)

    async def check() -> Any:
        engine, _, _ = await online(tmp_path, [], [tutor("Picture the forces.", sketch_wanted=SLOPE),
                                                   sketch_reply(1.0)], settings)  # fmt: skip
        try:
            await engine.student_turn("can you explain the first step?")
            await engine.sketches.task
            return engine
        finally:
            await close(engine)

    engine = asyncio.run(check())
    frames = engine.events.frames
    ended = next(i for i, f in enumerate(frames) if f["event"]["type"] == "turn.end")
    turn_id = frames[ended]["turn_id"]
    after = frames[ended + 1 :]
    sketch = next(f for f in after if f["event"]["type"] == "visual.sketch")
    assert sketch["turn_id"] == turn_id  # placed in the turn it was made for
    # The engine's own late line and, unchecked, its spoken notice: never model text.
    said = "".join(f["event"]["delta"] for f in after if f["event"]["type"] == "text.delta")
    assert said == "I've sketched it on the board.This is a rough sketch, and I haven't checked it."
    assert sketch["event"]["sketch"]["status"] == "not_checked"


def test_mdl33_cost_model_carries_sketch_calls_as_their_own_line() -> None:
    """BIZ-08, MDL-33: sketch calls are their own line of the cost model, from the measured share of online turns with
    one (the engine's sketch.outcome records carry each call's tokens)."""
    from jana_tools.cost_model import Usage, load_prices, workbook

    traces = [{"model_calls": [{"role": "coach", "provider_kind": "cloud",
                                "tokens": {"input": 3000, "output": 250, "cache_read": 0}}]}] * 4  # fmt: skip
    outcomes = [{"turn_id": "trn_1", "tokens": {"input": 900, "output": 400, "cache_read": 0}}]
    usage = Usage(cloud_share=1.0, turns_per_month=200)
    plain = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, measured_release="2026-10",
                     price_usd=6.0)  # fmt: skip
    book = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, measured_release="2026-10",
                    price_usd=6.0, sketch_outcomes=outcomes)  # fmt: skip
    assert "sketch" not in plain["roles"] and book["roles"]["sketch"]["calls_per_turn"] == 0.25
    prices = load_prices()["models"]["strong-model"]
    sketch = 200 * 0.25 * (900 * prices["price_in_per_mtok"] / 1e6 + 400 * prices["price_out_per_mtok"] / 1e6)
    assert abs(book["c_cloud_usd_per_student_month"] - plain["c_cloud_usd_per_student_month"] - sketch) < 1e-12
