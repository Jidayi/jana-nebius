"""M43: building a visual in steps (VSL-41, D103): the kind's declared layers, in order, one per bound step, ending
equal to `show`; a kind with no layers shows whole."""

import json
from fractions import Fraction
from typing import Any

from agent_core.assets.resolvers import resolver
from agent_core.assets.visual_kinds import UNLAYERED, Part, View, layers_of
from agent_core.assets.visuals import Resolver, VisualContext, validate
from agent_core.contracts import errors as contract_errors
from jana_tools import REPO_ROOT
from jana_tools.visual_fixtures import _call

FIXTURES = REPO_ROOT / "packages" / "renderers" / "fixtures" / "visuals"


def _fixtures() -> list[dict[str, Any]]:
    return [json.loads(p.read_text())["spec"] for p in sorted(FIXTURES.glob("*.json"))]


def _built(layers: list[dict[str, Any]], step: int) -> set[str]:
    """The parts shown after `step` bound steps of a build: the first layer, then one more per step."""
    return {i for layer in layers[: step + 2] for i in layer["part_ids"]}


def vsl41_build_follows_declared_layers() -> None:
    layered = 0
    for spec in _fixtures():
        view = View(spec["type"], spec["params"], spec.get("computed", {}), spec.get("steps", []))
        parts = [Part(p["id"], p["name"], p.get("role", "part"), p.get("focusable", True)) for p in spec["parts"]]
        layers = layers_of(view, parts)
        if spec["type"] in UNLAYERED or not parts:
            assert layers == [], spec["type"]
            continue
        layered += 1
        ids = [i for layer in layers for i in layer["part_ids"]]
        # Every part is added by exactly one layer, so the last state equals `show`.
        assert sorted(ids) == sorted(p.id for p in parts) and len(ids) == len(set(ids)), spec["type"]
        assert 1 <= len(layers) <= 12 and len({layer["layer"] for layer in layers}) == len(layers), spec["type"]
        # One declared layer per bound step, in the declared order; nothing is shown before its layer.
        for step in range(-1, len(layers) - 1):
            shown = _built(layers, step)
            assert shown == {i for layer in layers[: step + 2] for i in layer["part_ids"]}
            assert not shown & {i for layer in layers[step + 2 :] for i in layer["part_ids"]}
        assert _built(layers, len(layers) - 2) == set(ids)
    assert layered >= 20  # every graph and template kind of the catalogue declares layers
    # The graph's order: the axes, the grid, the points, the curve, then the labelled answer.
    graph = next(s for s in _fixtures() if s["type"] == "function_graph")
    view = View("function_graph", graph["params"], graph.get("computed", {}))
    order = [layer["layer"] for layer in layers_of(view, [Part(p["id"], p["name"], p["role"]) for p in graph["parts"]])]
    assert order[:2] == ["axes", "grid"] and order.index("curve") < (order.index("answer") if "answer" in order else 99)
    # A free-body diagram: the body, each force, then the resultant.
    body = View(
        "free_body",
        {
            "object": "block",
            "surface": {"kind": "horizontal"},
            "show_resultant": True,
            "forces": [
                {"id": "W", "name": "weight", "magnitude": "49 N", "direction_deg": 270},
                {"id": "R", "name": "normal", "magnitude": "49 N", "direction_deg": 90},
            ],
        },
    )
    parts = [Part("object", "block", "object"), Part("surface", "surface", "line"), Part("W", "weight", "force"),
             Part("R", "normal", "force"), Part("resultant", "resultant", "force")]  # fmt: skip
    assert [layer["layer"] for layer in layers_of(body, parts)] == ["body", "force_1", "force_2", "resultant"]
    # Through the engine: a build request's resolved spec lists its layers (engine only), in the contract.
    line = {"spec_version": 1, "type": "number_line", "presentation": "build",
            "params": {"intervals": [{"id": "sol", "from": "4", "to": "inf", "from_closed": False}], "variable": "x"},
            "numbers_from": ["kn_four"]}  # fmt: skip
    ctx = VisualContext("mathematics", "O", "S3", knowns={"kn_four": Fraction(4)})
    resolved, _ = validate(line, ctx, Resolver(resolver(_call("vsl41"))))
    assert resolved["presentation"] == "build" and [x["layer"] for x in resolved["layers"]] == ["line", "region",
                                                                                              "point"]  # fmt: skip
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    # Each build step's alt line names what it added (VSL-14).
    assert len(resolved["alt"]["steps"]) == len(resolved["layers"]) - 1
    assert resolved["alt"]["steps"][0].startswith("Step 1:") and "added" in resolved["alt"]["steps"][0]


def vsl41_no_layers_shows_whole() -> None:
    # A library diagram declares no layers: a build request renders it whole, with no error.
    library = next(s for s in _fixtures() if s["type"] == "library_diagram")
    view = View("library_diagram", library["params"], library.get("computed", {}))
    assert layers_of(view, [Part(p["id"], p["name"]) for p in library["parts"]]) == []
    # And a show request carries no layers at all: it is drawn whole as before.
    ctx = VisualContext("mathematics", "O", "S3", knowns={"kn_four": Fraction(4)})
    line = {"spec_version": 1, "type": "number_line",
            "params": {"intervals": [{"id": "sol", "from": "4", "to": "inf", "from_closed": False}], "variable": "x"},
            "numbers_from": ["kn_four"]}  # fmt: skip
    resolved, _ = validate(line, ctx, Resolver(resolver(_call("vsl41"))))
    assert "layers" not in resolved and resolved["status"] in ("ok", "repaired")
