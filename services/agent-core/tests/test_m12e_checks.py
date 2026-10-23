"""M12.e: plausibility bands (VER-26), and two checker defects found in M12.a: malformed unit text must be a parse
rejection, not a function failure (G102), and the mathematics checkers read pack conventions in the worker
protocol's `{value, source}` shape (G103, G104).

The calls go through the real worker server code in process, so every request and reply is checked against the
worker-protocol contract."""

import io
import json
from typing import Any

from agent_core.tools.executor import band_conventions
from tool_worker.functions import FUNCTIONS
from tool_worker.protocol import Code
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000026"


def call(name: str, args: dict[str, Any], conventions: dict[str, Any] | None = None) -> dict[str, Any]:
    """One call through the real server code, in process: the reply's `result`, or `{"error": ...}`."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params: dict[str, Any] = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args,
                              "check_id": CHECK, "deadline_ms": 15000}  # fmt: skip
    if conventions is not None:
        params["conventions"] = conventions
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    reply = next(r for r in (json.loads(line) for line in out.getvalue().splitlines()) if r.get("id") == "1")
    return reply.get("result") or {"error": reply["error"]}


# --- G102: malformed unit text is rejected, not raised ---------------------------------------------------------------

MALFORMED_UNITS = ["x+6", "5 (s", "((", "kg*)", "1/0", "m^(1/2", "m^x", "m^99999999999", "m**1e400"]


def test_malformed_unit_is_parse_rejected():
    for text in MALFORMED_UNITS:
        converted = call("units_convert", {"quantity": "5 m", "to": text})
        assert converted.get("error", {}).get("code") == Code.PARSE_REJECTED, (text, converted)
        checked = call("units_check_dimensions", {"quantity": "5 m", "expected": text})
        assert checked.get("error", {}).get("code") == Code.PARSE_REJECTED, (text, checked)
    # The same text after a number is a quantity with a malformed unit.
    quantity = call("units_convert", {"quantity": "5 (s", "to": "s"})
    assert quantity["error"]["code"] == Code.PARSE_REJECTED


def test_wellformed_units_still_parse():
    assert call("units_convert", {"quantity": "72 km/h", "to": "m/s"})["value"]["value"]["text"] == "20"
    assert call("units_check_dimensions", {"quantity": "9.8 m s^-2", "expected": "N/kg"})["value"]["match"] is True


# --- G103, G104: conventions in the worker protocol's shape ----------------------------------------------------------


def test_numeric_convention_read_in_protocol_shape():
    args = {"student": "2.35", "key": "2.3456"}
    default = call("math_check_answer", args)["value"]["components"]["precision"]
    assert default["item_sf"] == 3
    pack = call("math_check_answer", args, {"numeric.sf": {"value": "4", "source": "pack"}})
    assert pack["value"]["components"]["precision"]["item_sf"] == 4
    # The item's own rule still wins over the pack.
    item = call("math_check_answer", args | {"rule": {"sf": 2}}, {"numeric.sf": {"value": 4, "source": "pack"}})
    assert item["value"]["components"]["precision"]["item_sf"] == 2


def test_quartile_convention_read_in_protocol_shape():
    data = {"data": [1, 2, 3, 4, 5, 6, 7, 8]}
    default = call("stats_compute", data)
    assert [w["code"] for w in default.get("warnings", [])] == ["convention_default_used"]
    pack = call("stats_compute", data, {"quartile_method": {"value": "inclusive", "source": "pack"}})
    assert "warnings" not in pack
    assert pack["value"] != default["value"]  # the inclusive method gives other quartiles for this data
    stated = call("stats_compute", data | {"quartile_method": "inclusive"})
    assert stated["value"] == pack["value"]


def test_nested_convention_shapes_are_not_the_protocol():
    """The shapes M12.a first read (a nested `numeric` object, a bare value) never reach a function: the worker
    refuses them as requests that break the protocol, so the functions read only `{value, source}` entries."""
    for conventions in ({"numeric": {"sf": 4}}, {"quartile_method": "inclusive"}):
        refused = call("stats_compute", {"data": [1, 2]}, conventions)
        assert refused["error"]["code"] == Code.INVALID_PARAMS


# --- VER-26: plausibility bands -------------------------------------------------------------------------------------

# A thrown-ball height band, as a teaching skill's front matter states it (synthetic).
HEIGHT = {"quantity": "height", "unit": "m", "min": 0.5, "max": 50}
THROWN = {"motion": "vertical", "speed": 198, "direction": "up", "g": 9.8, "g_source": "question", "points": 3}
SOLVED = {"equations": ["v^2 = u^2 + 2*a*h"], "unknowns": ["h"], "units": {"h": "m"},
          "quantities": {"u": "198 m/s", "a": "-9.8 m/s^2", "v": "0 m/s"}}  # fmt: skip


def _band(**band: Any) -> dict[str, Any]:
    return band_conventions((band,))


def _flags(result: dict[str, Any]) -> list[str]:
    return [w["message"] for w in result.get("warnings", []) if w["code"] == "implausible"]


def ver26_band_flags_result():
    # A ball thrown up at 198 m/s rises 2,000.2 m: a correct computation, far outside a 0.5-50 m band.
    plain = call("phys_projectile", THROWN)
    banded = call("phys_projectile", THROWN, _band(**HEIGHT))
    assert plain["value"]["max_height"]["decimal"] == "2000.20"
    assert _flags(plain) == []
    [flag] = _flags(banded)
    assert "max_height" in flag and "height" in flag and "2000.20 m" in flag
    # Flagged, never changed: the value and its check hash are the same with the band.
    assert banded["value"] == plain["value"]
    assert banded["check"]["result_sha256"] == plain["check"]["result_sha256"]
    # The same height solved for as an unknown in a stated unit is flagged too, after conversion into the band's unit.
    assert len(_flags(call("math_solve", SOLVED, _band(**HEIGHT)))) == 1
    in_km = call("math_solve", SOLVED | {"units": {"h": "km"}}, _band(**HEIGHT))
    assert in_km["value"]["solutions"][0]["h"]["unit"] == "km" and len(_flags(in_km)) == 1
    assert _flags(call("math_solve", SOLVED, _band(**HEIGHT | {"unit": "km", "min": 0.5, "max": 3}))) == []
    assert len(_flags(call("math_solve", SOLVED, _band(**HEIGHT | {"unit": "cm", "min": 50, "max": 5000})))) == 1


def test_ver26_in_band_and_unnamed_results_pass():
    # A ball thrown up at 14 m/s rises 10 m: inside the band, no warning.
    assert _flags(call("phys_projectile", THROWN | {"speed": 14}, _band(**HEIGHT))) == []
    # A band applies by quantity name, never by dimension alone: a converted 2000 m is not a height.
    assert _flags(call("units_convert", {"quantity": "2 km", "to": "m"}, _band(**HEIGHT))) == []
    # A speed band checks the projectile's launch and landing speeds; a band with another dimension never matches.
    speed = _band(quantity="speed", unit="km/h", min=0, max=200)
    assert len(_flags(call("phys_projectile", THROWN, speed))) == 2  # 198 m/s is 712.8 km/h, up and down
    assert _flags(call("phys_projectile", THROWN, _band(quantity="height", unit="s", min=0, max=1))) == []
    # Incomplete bands are ignored rather than guessed.
    half = {"plausibility.height.min": {"value": 0.5, "unit": "m", "source": "pack"}}
    assert _flags(call("phys_projectile", THROWN, half)) == []


def test_ver26_bands_reach_the_worker_from_the_session(tmp_path):
    """The host sends the pushed skill's bands with each worker call and shows the warning to the model."""
    import asyncio

    from agent_core.config import Settings
    from agent_core.tools.executor import ToolCall, ToolExecutor
    from agent_core.tools.spec import SessionCtx
    from agent_core.tools.specs import registry
    from agent_core.tools.spill import SpillStore
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    async def run() -> list[dict[str, Any]]:
        settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path / "w"), settings)
        await supervisor.start()
        try:
            executor = ToolExecutor(registry(), settings, SpillStore(tmp_path / "spill"), supervisor)
            out = []
            for bands in ((), (HEIGHT,)):
                session = SessionCtx(subject="physics", role="solver", session_id="ses_01JZ0000000000000000000026",
                                     plausibility=bands)  # fmt: skip
                out.append(await executor.run_one(ToolCall("call_1_0", "phys_projectile", THROWN), "solver", session))
            return out
        finally:
            await supervisor.close()

    plain, banded = asyncio.run(run())
    assert plain["status"] == banded["status"] == "ok"
    assert "warnings" not in json.loads(plain["output"])
    [warning] = json.loads(banded["output"])["warnings"]
    assert warning["code"] == "implausible" and "height" in warning["message"]
    assert json.loads(banded["output"])["value"] == json.loads(plain["output"])["value"]
