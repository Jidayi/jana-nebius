"""M12.b: physics checkers (VER-16 optics and circuits, VER-17 projectiles; VER-12 constants in both)."""

import io
import json
from fractions import Fraction

from agent_core.contracts import errors as contract_errors
from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000002"


def call(name: str, args: dict) -> dict:
    """One call through the real server code, in process: the reply frame as a dict."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    return next(r for r in replies if r.get("id") == "1")


def _golden_failures(tool: str) -> list[str]:
    data = golden.load()[tool]
    assert data["stage"] == "S2" and len(data["cases"]) >= 100
    return [c["id"] for c in data["cases"] if not golden.matches(golden.run(c, tool), c["expect"])]


def _on_line(a: list[float], b: list[float], point: list[float]) -> bool:
    """Whether `point` lies on the line through a and b (to the 6 s.f. of the drawing points)."""
    cross = (b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0])
    return abs(cross) <= 1e-4 * max(1.0, abs(b[0] - a[0]) + abs(b[1] - a[1])) * max(1.0, abs(point[0]), abs(point[1]))


# --- VER-16 -----------------------------------------------------------------------------------------------------


def ver16_lens_golden():
    # An object at 2f gives a real, inverted image at 2f with magnification 1, in both sign conventions.
    for convention, u in (("real_is_positive", "20"), ("cartesian", "-20")):
        args = {"optic": "converging_lens", "focal_length": 10, "object_distance": 20, "object_height": 3,
                "sign_convention": convention, "sign_convention_source": "pack"}  # fmt: skip
        result = call("phys_optics", args)["result"]
        assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", result) == []
        value = result["value"]
        assert value["image_distance"]["text"] == "20" and value["object_distance"]["text"] == u
        assert value["magnification"]["text"] == "1"
        assert value["nature"] == {"type": "real", "orientation": "inverted", "size": "same_size"}
        assert value["sign_convention"] == {"value": convention, "source": "pack"}
        assert value["image_height"]["text"] == "3" and result["check"]["method"] == "exact"
        # The three principal rays meet at the image, and the parallel ray passes through the far focal point.
        rays = {r["ray"]: r["path"] for r in value["rays"]}
        assert set(rays) == {"parallel", "focal", "centre"}
        assert all(path[-1] == value["frame"]["image_top"] == [20.0, -3.0] for path in rays.values())
        assert _on_line(rays["parallel"][1], rays["parallel"][2], [10.0, 0.0])

    # A virtual image: the rays leave diverging and their dashed extensions meet at the image behind the lens.
    virtual = call("phys_optics", {"optic": "converging_lens", "focal_length": 10, "object_distance": 5,
                                   "object_height": 2, "sign_convention": "cartesian"})["result"]["value"]  # fmt: skip
    assert virtual["image_distance"]["text"] == "-10" and virtual["magnification"]["text"] == "2"
    assert virtual["nature"] == {"type": "virtual", "orientation": "upright", "size": "magnified"}
    for ray in virtual["rays"]:
        assert ray["virtual"][-1] == [-10.0, 4.0] and _on_line(ray["path"][1], ray["path"][2], [-10.0, 4.0])
    # The mirror rule in each convention: a concave mirror's real image is in front (negative in cartesian).
    mirror = {"optic": "concave_mirror", "focal_length": 10, "object_distance": 30, "object_height": 2}
    for convention, v, f in (("real_is_positive", "15", "10"), ("cartesian", "-15", "-10")):
        value = call("phys_optics", {**mirror, "sign_convention": convention})["result"]["value"]
        assert (value["image_distance"]["text"], value["focal_length"]["text"]) == (v, f)
        assert all(_on_line(r["path"][1], r["path"][2], value["frame"]["image_top"]) for r in value["rays"])
    # No sign convention stated: unknown, never a guessed sign.
    missing = call("phys_optics", {"optic": "converging_lens", "focal_length": 10, "object_distance": 20})["result"]
    assert missing["value"] == {"status": "unknown", "reason": "convention_missing"}
    assert [w["code"] for w in missing["warnings"]] == ["convention_missing"]
    # Snell's law, total internal reflection and the critical angle.
    snell = call("phys_optics", {"task": "refraction", "n1": 1, "angle1": 45, "angle2": 30})["result"]["value"]
    assert snell["n2"]["text"] == "sqrt(2)" and snell["bends"] == "towards_normal"
    tir = call("phys_optics", {"task": "refraction", "n1": "1.5", "angle1": 60, "n2": 1})["result"]["value"]
    assert tir["case"] == "total_internal_reflection" and tir["critical_angle"]["decimal"] == "41.8103"
    assert call("phys_optics", {"task": "critical_angle", "n1": 2})["result"]["value"]["critical_angle"]["text"] == "30"
    assert _golden_failures("phys_optics") == []


def ver16_circuit_exact():
    # A 6 Ω and 3 Ω parallel pair in series with 4 Ω across 12 V: exactly 2 A, by nodal analysis.
    components = [
        {"id": "B", "kind": "cell", "emf": 12},
        {"id": "R1", "kind": "resistor", "resistance": 6},
        {"id": "R2", "kind": "resistor", "resistance": 3},
        {"id": "R3", "kind": "resistor", "resistance": 4},
    ]
    result = call(
        "phys_circuit", {"components": components, "network": {"series": ["B", {"parallel": ["R1", "R2"]}, "R3"]}}
    )["result"]
    assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", result) == []
    value = result["value"]
    assert value["total_current"] == {"text": "2", "latex": "2", "decimal": "2.00000"}
    assert value["equivalent_resistance"]["text"] == "6"
    parts = value["components"]
    assert [parts[k]["current"]["text"] for k in ("B", "R1", "R2", "R3")] == ["2", "2/3", "4/3", "2"]
    assert [parts[k]["pd"]["text"] for k in ("B", "R1", "R2", "R3")] == ["12", "4", "4", "8"]
    assert [parts[k]["power"]["text"] for k in ("B", "R1", "R2", "R3")] == ["24", "8/3", "16/3", "16"]
    # Energy is conserved exactly: the cell's power equals the sum dissipated.
    assert sum(Fraction(parts[k]["power"]["text"]) for k in ("R1", "R2", "R3")) == Fraction(parts["B"]["power"]["text"])

    # The same circuit as a netlist, with an ammeter in series and a voltmeter across R3.
    meters = [*components, {"id": "A", "kind": "ammeter"}, {"id": "V", "kind": "voltmeter"}]
    links = [("B.pos", "A.a"), ("A.b", "R1.a"), ("A.b", "R2.a"), ("R1.b", "R3.a"), ("R2.b", "R3.a"),
             ("R3.b", "B.neg"), ("V.a", "R3.a"), ("V.b", "R3.b")]  # fmt: skip
    netlist = {"components": meters, "connections": [{"from": a, "to": b} for a, b in links]}
    readings = call("phys_circuit", netlist)["result"]["value"]["components"]
    assert (readings["A"]["reading"]["text"], readings["V"]["reading"]["text"]) == ("2", "8")

    # A short circuit across an ideal cell is a DOMAIN_ERROR with that reason; a cell's internal resistance limits it.
    short = {"components": [{"id": "B", "kind": "cell", "emf": 6}, {"id": "S", "kind": "switch", "state": "closed"}],
             "network": {"series": ["B", "S"]}}  # fmt: skip
    error = call("phys_circuit", short)["error"]
    assert error["code"] == 4 and error["data"]["reason"] == "short_circuit" and "short circuit" in error["message"]
    short["components"][0]["internal_resistance"] = "0.5"
    assert call("phys_circuit", short)["result"]["value"]["total_current"]["text"] == "12"
    # Twenty components (the limit) solve exactly within the call budget; a twenty-first is refused by the schema.
    ladder = [{"id": "B", "kind": "cell", "emf": 9}] + [
        {"id": f"R{i}", "kind": "resistor", "resistance": i + 1} for i in range(19)]  # fmt: skip
    network = {"series": ["B", *({"parallel": [f"R{i}", f"R{i + 1}"]} for i in range(0, 18, 2)), "R18"]}
    assert "result" in call("phys_circuit", {"components": ladder, "network": network})
    too_many = [*ladder, {"id": "R19", "kind": "resistor", "resistance": 1}]
    assert call("phys_circuit", {"components": too_many, "network": network})["error"]["code"] == -32602
    assert _golden_failures("phys_circuit") == []
