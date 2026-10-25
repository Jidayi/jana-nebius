"""VER-31: `phys_mechanics`, the A level mechanics checker, through the real fn.call boundary: the golden set at 100%
with its pinned fingerprints, g resolved only when a task needs it (VER-12), undetermined input as `unknown` (VER-27)
and contradictory input refused as a domain error with no number."""

from __future__ import annotations

import io
import json
from typing import Any

from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.protocol import Code
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000001"
TOOL = "phys_mechanics"
TASKS = {"projectile_angle", "moments", "incline_friction", "connected_particles", "work_energy_power",
         "momentum_impulse", "circular_motion", "shm"}  # fmt: skip
G10 = {"g": 10, "g_source": "question"}


def call(args: dict[str, Any]) -> dict[str, Any]:
    """One fn.call through the worker's server code, in process: the reply frame."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": TOOL, "version": FUNCTIONS[TOOL].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    return next(r for r in map(json.loads, out.getvalue().splitlines()) if r.get("id") == "1")


def result(args: dict[str, Any]) -> dict[str, Any]:
    reply = call(args)
    assert "result" in reply, reply
    found: dict[str, Any] = reply["result"]
    assert found["check"]["check_id"] == CHECK and found["check"]["function"] == TOOL
    return found


def refused(args: dict[str, Any], code: int = Code.DOMAIN_ERROR) -> str:
    reply = call(args)
    assert "result" not in reply and reply["error"]["code"] == code, reply
    return str(reply["error"]["message"])


def outcome(reply: dict[str, Any]) -> Any:
    """The value, or the refusal as golden.run records it."""
    if "result" in reply:
        return reply["result"]["value"]
    return {"error": reply["error"]["code"], "message": reply["error"]["message"]}


def ver31_mechanics_golden() -> None:
    data = golden.load()[TOOL]
    assert data["tool"] == TOOL and data["stage"] == "S3" and len(data["cases"]) >= 100
    pinned = json.loads(golden.FINGERPRINTS.read_text())
    failures, drifted, seen = [], [], set()
    for case in data["cases"]:
        reply = call(case["args"])
        value = outcome(reply)
        if not golden.matches(value, case["expect"]):
            failures.append(case["id"])
        if golden.result_sha256(value) != pinned[case["id"]]:
            drifted.append(case["id"])
        if "result" in reply:
            assert reply["result"]["check"]["result_sha256"] == golden.result_sha256(value), case["id"]
            assert all(line["check_id"] == CHECK for line in reply["result"].get("working", [])), case["id"]
        seen.add(case["args"]["task"])
    assert failures == []
    assert drifted == []
    assert seen == TASKS  # every topic of VER-31 is in the set
    kinds = {"error" if "error" in c["expect"] else c["expect"].get("status", "answer") for c in data["cases"]}
    assert kinds == {"answer", "unknown", "error"}


def test_mechanics_default_g_is_recorded_and_warned() -> None:
    found = result({"task": "projectile_angle", "speed": 20, "angle": 45})
    assert found["check"]["constants"] == [{"symbol": "g", "value": "9.80665", "unit": "m/s^2", "source": "default"}]
    assert [w["code"] for w in found["warnings"]] == ["convention_default_used"]
    assert found["value"]["max_height"]["text"] == "2000000/196133"


def test_mechanics_g_only_when_a_task_needs_it() -> None:
    found = result({"task": "momentum_impulse", "part": "collision", "mass_a": 2, "mass_b": 3, "velocity_a": 5,
                    "velocity_b": -2, "restitution": "0.5"})  # fmt: skip
    assert "constants" not in found["check"] and "warnings" not in found
    assert (found["check"]["method"], found["check"]["confidence"]) == ("exact", "proved")
    # A beam loaded in newtons needs no g either; one loaded in kilograms records the question's g.
    beam = {"task": "moments", "length": 4, "supports": [{"id": "A", "distance": 0}, {"id": "B", "distance": 4}]}
    newtons = result({**beam, "loads": [{"id": "P", "distance": 1, "force": 40}]})
    assert "constants" not in newtons["check"]
    assert newtons["value"]["supports"]["A"]["reaction"]["text"] == "30"
    kilograms = result({**beam, "loads": [{"id": "P", "distance": 1, "mass": 4}], **G10})
    assert kilograms["check"]["constants"] == [{"symbol": "g", "value": "10", "source": "question"}]
    assert kilograms["value"]["supports"]["B"]["reaction"]["text"] == "10"


def test_mechanics_unknown_is_undecided_never_a_number() -> None:
    found = result({"task": "connected_particles", "arrangement": "table", "mass_a": 4, "mass_b": 1,
                    "surface": "rough", **G10})  # fmt: skip
    assert found["value"] == {"task": "connected_particles", "status": "unknown", "reason": "underdetermined",
                              "needs": "the surface is rough: give the coefficient of friction mu"}  # fmt: skip
    assert (found["check"]["method"], found["check"]["confidence"]) == ("heuristic", "undecided")
    timed = result({"task": "shm", "amplitude": "0.1", "period": 2, "time": "0.5"})["value"]
    assert (timed["status"], timed["reason"]) == ("unknown", "ambiguous")


def test_mechanics_units_and_tangent_angles_stay_exact() -> None:
    # 90 km/h = 25 m/s at tan a = 3/4: components 20 and 15 exactly, so T = 3 s and the range 60 m.
    value = result({"task": "projectile_angle", "speed": "90 km/h", "tan_angle": "3/4", **G10})["value"]
    assert (value["launch"]["vx"]["text"], value["launch"]["vy"]["text"]) == ("20", "15")
    assert (value["time_of_flight"]["text"], value["range"]["text"]) == ("3", "60")
    assert "found m, expected m s⁻¹" in refused({"task": "projectile_angle", "speed": "5 m", "angle": 30, **G10})


def test_mechanics_friction_limiting_and_static() -> None:
    # 5 kg on tan a = 3/4 with mu = 3/4 is exactly limiting: friction 30 N = mu R, no sliding.
    value = result({"task": "incline_friction", "mass": 5, "tan_angle": "3/4", "mu": "0.75", **G10})["value"]
    assert (value["slides"], value["limiting"], value["friction"]["text"]) == (False, True, "30")
    # The same block with mu = 0.8 is held by 30 N of friction, below the 32 N limit.
    value = result({"task": "incline_friction", "mass": 5, "tan_angle": "3/4", "mu": "0.8", **G10})["value"]
    assert (value["slides"], value["limiting"], value["limiting_friction"]["text"]) == (False, False, "32")


def test_mechanics_contradictions_are_refused() -> None:
    beam = {"task": "moments", "length": 4, "loads": [{"id": "P", "distance": 1, "force": 30}]}
    # One unknown but two equations that disagree: no reaction at B balances the beam.
    assert "equilibrium" in refused({**beam, "supports": [{"id": "A", "distance": 0, "reaction": 10},
                                                          {"id": "B", "distance": 3}]})  # fmt: skip
    collision = {"task": "momentum_impulse", "part": "collision", "mass_a": 1, "mass_b": 1, "velocity_a": 4,
                 "velocity_b": 0}  # fmt: skip
    assert "momentum" in refused({**collision, "final_velocity_a": 1, "final_velocity_b": 1})
    assert "at most 1" in refused({**collision, "restitution": "1.5"})
    assert "P = F v" in refused({"task": "work_energy_power", "part": "power", "power": 100, "speed": 10,
                                 "driving_force": 20})  # fmt: skip


def test_mechanics_schema_requires_each_tasks_inputs() -> None:
    invalid = int(Code.INVALID_PARAMS)
    refused({"task": "projectile_angle", "speed": 20, "angle": 30, "tan_angle": "3/4"}, invalid)
    refused({"task": "projectile_angle", "angle": 30}, invalid)
    refused({"task": "moments", "length": 4, "beam_mass": 2, "beam_weight": 20,
             "supports": [{"id": "A", "distance": 0}]}, invalid)  # fmt: skip
    refused({"task": "work_energy_power", "power": 10}, invalid)
    refused({"task": "momentum_impulse", "part": "impulse", "mass": 1}, invalid)
    refused({"task": "shm", "part": "collision", "amplitude": 1}, invalid)
    refused({"task": "incline_friction", "mass": 1, "angle": 30, "acceleration": 2}, invalid)  # needs a direction


def test_mechanics_deterministic_bytes() -> None:
    args = {"task": "circular_motion", "part": "conical_pendulum", "length": 1, "angle": 60, "mass": 2, **G10}
    first, second = result(args), result(args)
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert first["value"]["tension"]["text"] == "40" and first["value"]["angular_speed"]["text"] == "2*sqrt(5)"
