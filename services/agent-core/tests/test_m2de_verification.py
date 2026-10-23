"""M2.d and M2.e: the verification core (VER-01 to VER-07, VER-11, VER-27, VER-29), with the S1 subsets of VER-09,
VER-12 and VER-17 pulled forward from M12."""

import ast
import asyncio
import io
import json
import subprocess
import sys
from functools import cache
from pathlib import Path

import pytest
import sympy as sp
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from jana_tools import REPO_ROOT, golden
from tool_worker.functions import FUNCTIONS
from tool_worker.grammar import ParseRejected, parse
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000001"
WORKER = REPO_ROOT / "services" / "tool-worker" / "tool_worker"
REGISTER = REPO_ROOT / "docs" / "specification" / "registers" / "toolsets.json"


def call_in_process(name: str, args: dict, settings: dict | None = None) -> dict:
    """One call through the real server code, in process: the reply frame as a dict."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits(**(settings or {})))
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {
        "call_id": "c",
        "name": name,
        "version": FUNCTIONS[name].version,
        "args": args,
        "check_id": CHECK,
        "deadline_ms": 15000,
    }
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    return next(r for r in replies if r.get("id") == "1")


@cache
def _golden_results() -> dict[str, tuple[str, dict, object]]:
    """Every golden case run once in-process: id -> (tool, case, value)."""
    results = {}
    for data in golden.load().values():
        for case in data["cases"]:
            results[case["id"]] = (data["tool"], case, golden.run(case, data["tool"]))
    return results


def _s1_worker_tools() -> list[str]:
    register = json.loads(REGISTER.read_text())
    return [
        t["name"] for t in register["toolsets"]["compute"]["tools"] if t["stage"] == "S1" and t["executor"] == "worker"
    ]


def ver01_no_model_or_network_imports():
    banned = {"openai", "anthropic", "httpx", "requests", "aiohttp", "urllib3", "socket", "http", "urllib", "ssl",
              "websockets", "ollama", "llama_cpp"}  # fmt: skip
    found = []
    for path in WORKER.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else (
                [node.module or ""] if isinstance(node, ast.ImportFrom) else [])  # fmt: skip
            found += [f"{path.name}: {n}" for n in names if n.partition(".")[0] in banned]
    assert found == []


def ver01_golden_offline(tmp_path: Path):
    """Every golden case through the real worker, under its OS sandbox (no network at all)."""

    async def scenario() -> list[str]:
        settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=10.0)
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path), settings)
        await supervisor.start()
        assert not supervisor.reduced_protection
        failures = []
        for tool, case, expected_value in _golden_results().values():
            outcome = await supervisor.call(tool, FUNCTIONS[tool].version, case["args"], CHECK, 15000)
            value = outcome.result["value"] if outcome.ok else {"error": outcome.error}
            if not outcome.ok and isinstance(expected_value, dict) and "error" in expected_value:
                continue
            if not golden.matches(value, case["expect"]):
                failures.append(case["id"])
        await supervisor.close()
        return failures

    assert asyncio.run(scenario()) == []


def ver01_byte_identical_results():
    """The committed fingerprints (computed on another machine) equal this machine's result hashes."""
    committed = json.loads(golden.FINGERPRINTS.read_text())
    here = {cid: golden.result_sha256(value) for cid, (_, _, value) in _golden_results().items()}
    assert sorted(committed) == sorted(here)
    assert [cid for cid in here if here[cid] != committed[cid]] == []


def ver02_check_record_valid():
    for name in _s1_worker_tools():
        data = golden.load()[name]
        for case in data["cases"][:10]:
            reply = call_in_process(name, case["args"])
            assert "result" in reply, (name, case["id"], reply)
            assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", reply["result"]) == []
            record = reply["result"]["check"]
            assert record["function"] == name and record["check_id"] == CHECK
            assert record["result_sha256"] == golden.result_sha256(reply["result"]["value"])


FUZZ = """
import builtins, random, sys
import sympy as sp
import sympy.core.sympify as sympify_module
import sympy.parsing.sympy_parser as parser_module
from tool_worker.grammar import ParseRejected, TooLarge, parse

current = [""]


def reaches_input(args):
    for arg in args:
        text = arg.decode(errors="replace") if isinstance(arg, bytes) else arg
        if isinstance(text, str) and current[0].strip() and current[0].strip() in text:
            return True
    return False


def trap(original, name):
    def guarded(*args, **kwargs):
        if reaches_input(args):
            print(f"the input {current[0]!r} reached {name}", file=sys.stderr)
            sys.exit(3)
        return original(*args, **kwargs)
    return guarded


# Only the fuzzed text counts: SymPy's own lazy imports compile SymPy's source, which is not student input.
builtins.eval = trap(builtins.eval, "eval")
builtins.exec = trap(builtins.exec, "exec")
builtins.compile = trap(builtins.compile, "compile")
sp.sympify = sympify_module.sympify = trap(sp.sympify, "sympify")
parser_module.parse_expr = trap(parser_module.parse_expr, "parse_expr")
rng = random.Random(1)
alphabet = "0123456789xyzabt+-*/^()[]{}|=<>.,_ ²³√πθ\\fracsqrtlogsincoepi"
for _ in range(100_000):
    current[0] = "".join(rng.choice(alphabet) for _ in range(rng.randint(1, 24)))
    try:
        parse(current[0])
    except (ParseRejected, TooLarge, ZeroDivisionError, ValueError, TypeError, RecursionError):
        pass
print("ok")
"""


def ver03_no_eval_under_fuzz():
    """100,000 random strings through the grammar with eval, exec, compile, sympify-on-strings and parse_expr
    trapped (in a separate process, so the traps cannot disturb the test runner)."""
    result = subprocess.run([sys.executable, "-c", FUZZ], capture_output=True, text=True, timeout=600)
    assert result.returncode == 0, result.stderr[-2000:]
    assert result.stdout.strip() == "ok"


def ver03_grammar_golden():
    x = sp.Symbol("x", real=True)
    assert parse("2x(x+1)").tree == sp.Mul(2, x, x + 1)
    assert sp.srepr(parse(r"\frac{1}{2}x^2").tree) == "Mul(Rational(1, 2), Pow(Symbol('x', real=True), Integer(2)))"
    mixed = parse("2 1/2")
    assert mixed.tree == sp.Rational(5, 2)
    assert mixed.as_written != sp.Rational(5, 2) and sp.simplify(mixed.as_written) == sp.Rational(5, 2)


def ver03_error_position():
    for text, position in (("2x +* 3", 4), (r"\foo{x}", 0), ("(x+1", 4), ("x = ", 4), ("3 + #", 4)):
        with pytest.raises(ParseRejected) as rejected:
            parse(text)
        assert rejected.value.position == position, text
    reply = call_in_process("math_parse", {"text": "2x +* 3"})
    assert reply["error"]["code"] == 3 and reply["error"]["data"]["position"] == 4


def ver04_equivalence_golden():
    false_equivalent = false_different = 0
    for tool, case, value in _golden_results().values():
        if tool != "math_check_equivalence":
            continue
        expected, actual = case["expect"]["verdict"], value["verdict"]
        false_equivalent += expected == "not_equivalent" and actual.startswith("equivalent")
        false_different += expected.startswith("equivalent") and actual == "not_equivalent"
    assert (false_equivalent, false_different) == (0, 0)


def ver04_counterexample_valid():
    proved = call_in_process("math_check_equivalence", {"a": "sin^2 x + cos^2 x", "b": "1"})["result"]
    assert proved["value"]["verdict"] == "equivalent" and proved["check"]["confidence"] == "proved"
    for a, b in (("2x+3", "2x+4"), ("(x+1)^2", "x^2+1"), ("sqrt(x^2)", "x")):
        value = call_in_process("math_check_equivalence", {"a": a, "b": b})["result"]["value"]
        assert value["verdict"] == "not_equivalent"
        point = {sp.Symbol(k, real=True): sp.Float(v, 30) for k, v in value["counterexample"]["at"].items()}
        va, vb = parse(a).tree.subs(point), parse(b).tree.subs(point)
        assert abs(sp.N(va - vb)) > 1e-9, (a, b, point)


def ver05_assumptions_change_verdict():
    real = call_in_process("math_check_equivalence", {"a": "sqrt(x^2)", "b": "x"})["result"]["value"]
    asserted = {"a": "sqrt(x^2)", "b": "x", "assumptions": {"x": ["positive"]}}
    positive = call_in_process("math_check_equivalence", asserted)["result"]["value"]
    assert (real["verdict"], positive["verdict"]) == ("not_equivalent", "equivalent")


def ver06_seeded_error_detection():
    found = category_ok = total = 0
    for _tool, case, value in _golden_results().values():
        if not case["id"].startswith("seeded_") or case["expect"]["verdict"] != "invalid":
            continue
        total += 1
        found += value.get("verdict") == "invalid"
        category_ok += value.get("category") == case["expect"]["category"]
    assert total >= 300
    assert found / total >= 0.95 and category_ok / total >= 0.80, (found, category_ok, total)


def ver06_lost_solution_flagged():
    value = call_in_process("math_check_step", {"prev": "x^2 = 3x", "next": "x = 3"})["result"]["value"]
    assert value["verdict"] == "valid_but_lost_solutions" and value["lost_solutions"] == ["x = 0"]


def ver07_solve_golden():
    value = call_in_process("math_solve", {"equations": ["2x^2 - 8x + 6 = 0"]})["result"]["value"]
    assert [s["x"]["text"] for s in value["solutions"]] == ["1", "3"]
    assert call_in_process("math_solve", {"equations": ["x + 1 = x"]})["result"]["value"] == {"case": "no_solution"}
    failures = [cid for cid, (tool, case, v) in _golden_results().items()
                if tool == "math_solve" and not golden.matches(v, case["expect"])]  # fmt: skip
    assert failures == []


def ver11_convert_and_dimension_golden():
    assert (
        call_in_process("units_convert", {"quantity": "72 km/h", "to": "m/s"})["result"]["value"]["value"]["text"]
        == "20"
    )
    height = call_in_process("units_check_dimensions", {"quantity": "20 m/s", "expected": "m"})["result"]["value"]
    assert height == {"match": False, "found": "m s⁻¹", "expected": "m", "message": "found m s⁻¹, expected m"}
    failures = [cid for cid, (tool, case, v) in _golden_results().items()
                if tool.startswith("units_") and not golden.matches(v, case["expect"])]  # fmt: skip
    assert failures == []


def ver11_temperature_difference():
    rise = call_in_process("units_convert", {"quantity": "20 °C", "to": "K", "difference": True})["result"]["value"]
    absolute = call_in_process("units_convert", {"quantity": "20 °C", "to": "K"})["result"]["value"]
    assert rise["value"]["text"] == "20" and absolute["value"]["decimal"] == "293.150"


def ver27_timeout_is_unknown():
    # An equivalent pair, and a slice that is exhausted before any work: the verdict must be unknown, never
    # equivalent.
    equivalent = {
        "a": "(x+1)^12",
        "b": "x^12 + 12x^11 + 66x^10 + 220x^9 + 495x^8 + 792x^7 + 924x^6 + 792x^5 + 495x^4 + 220x^3 + 66x^2 + 12x + 1",
    }
    reply = call_in_process("math_check_equivalence", equivalent, settings={"symbolic_slice_ms": 0})
    value = reply["result"]["value"]
    assert value == {"verdict": "unknown", "reason": "timeout"}
    assert reply["result"]["check"]["confidence"] == "undecided"


def ver29_golden_counts():
    sets = golden.load()
    minimums = Settings()
    for tool in _s1_worker_tools():
        assert len(sets[tool]["cases"]) >= minimums.golden_min_cases_per_tool, tool
    assert len(sets["math_check_step.seeded_errors"]["cases"]) >= minimums.golden_min_seeded_step_pairs
    for data in sets.values():
        assert data["review"] in ("pending", "reviewed") and data["provenance"]


def ver29_golden_all_pass():
    failures = [cid for cid, (tool, case, value) in _golden_results().items()
                if not golden.matches(value, case["expect"])]  # fmt: skip
    assert failures == []


# --- pulled forward from M12: the S1 subsets of VER-09, VER-12 and VER-17 --------------------------------------


def ver09_rounding_and_sf():
    from decimal import Decimal

    from tool_worker.functions.numeric import compare_sf, read_number, round_sf

    assert str(round_sf(Decimal("2.45"), 2)) == "2.5"  # half away from zero, never banker's rounding
    assert str(round_sf(Decimal("-2.45"), 2)) == "-2.5"
    assert str(round_sf(Decimal("0.0125"), 2)) == "0.013"
    nine_eight = compare_sf("9.8", "9.81", min_sf=2, max_sf=3)
    assert nine_eight["accepted"] and nine_eight["sf"] == "ok"
    ten = compare_sf("10", "9.81", min_sf=2, max_sf=3)
    assert ten == {"accepted": False, "value_matches": True, "sf": "too_few", "student_sf": 1}
    assert compare_sf("9.810", "9.81", min_sf=2, max_sf=3)["sf"] == "too_many"
    assert not compare_sf("9.7", "9.81", min_sf=2)["accepted"]
    # Leading zeros never count; trailing zeros after the point count; integer trailing zeros only in standard form.
    assert [read_number(t)[1] for t in ("0.0050", "1200", "1.200e3", "1.2 × 10^3", "120.")] == [2, 2, 4, 2, 3]
    reply = call_in_process("math_evaluate", {"expression": "2.45", "sf": 2})
    assert reply["result"]["value"]["rounded"] == "2.5"
    # M12: the answer marker applies the same rules (TABLE VER-09a, measurement row).
    for student, verdict, sf in (("9.8", "correct", "ok"), ("10", "incorrect", "too_few")):
        marked = call_in_process("math_check_answer", {"student": student, "key": "9.81"})["result"]["value"]
        assert (marked["verdict"], marked["components"]["precision"]["sf"]) == (verdict, sf)


def ver09_too_many_is_feedback_only():
    from tool_worker.functions.numeric import compare_sf

    # More figures than the item's precision: compared at that precision, accepted, and only reported.
    assert compare_sf("9.806", "9.81", min_sf=2, max_sf=3) == {
        "accepted": True, "value_matches": True, "sf": "too_many", "student_sf": 4}  # fmt: skip
    assert not compare_sf("9.826", "9.81", min_sf=2, max_sf=3)["accepted"]  # still the key's value at 3 s.f.
    # M12: the answer marker gives full marks and reports too_many as feedback only.
    marked = call_in_process("math_check_answer", {"student": "9.806", "key": "9.81", "rule": {"sf": 3}})
    assert marked["result"]["value"]["verdict"] == "correct" and "because" not in marked["result"]["value"]
    assert marked["result"]["value"]["components"]["precision"]["sf"] == "too_many"


def ver06_copy_precedes_arithmetic():
    # With 25 given, a line that writes 52 where 25 belongs is a copying slip naming 25, not an arithmetic error.
    copied = call_in_process("math_check_step", {"prev": "y = 25 * 2", "next": "y = 52 * 2", "givens": ["25"]})
    assert copied["result"]["value"]["category"] == "copy"
    assert "25" in copied["result"]["value"]["message"]
    # With no given that 12 transcribes, 3x = 12 -> x = 3 stays arithmetic.
    slip = call_in_process("math_check_step", {"prev": "3x = 12", "next": "x = 3", "givens": ["5"]})
    assert slip["result"]["value"]["category"] == "arithmetic"


def ver12_question_constant_wins():
    every_source = [
        {"symbol": "g", "source": "default"},
        {"symbol": "g", "value": "9.8", "unit": "m/s^2", "source": "pack"},
        {"symbol": "g", "value": 10, "unit": "m/s^2", "source": "question"},
    ]
    reply = call_in_process("math_solve", {"equations": ["0 = 20 - g*t"], "unknowns": ["t"], "constants": every_source})
    result = reply["result"]
    assert result["value"]["solutions"] == [{"t": {"text": "2", "latex": "2", "decimal": "2.00000"}}]
    assert result["check"]["constants"] == [{"symbol": "g", "value": "10", "unit": "m/s^2", "source": "question"}]
    assert "warnings" not in result
    assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", result) == []

    # Without a question value the pack's convention applies; with nothing else the tool default, with a warning.
    pack = call_in_process("math_evaluate", {"expression": "g*2", "constants": every_source[:2]})["result"]
    assert pack["value"]["exact"]["text"] == "98/5" and pack["check"]["constants"][0]["source"] == "pack"
    default = call_in_process("math_evaluate", {"expression": "g", "constants": every_source[:1]})["result"]
    assert default["check"]["constants"][0] == {"symbol": "g", "value": "9.80665", "unit": "m/s^2", "source": "default"}
    assert [w["code"] for w in default["warnings"]] == ["convention_default_used"]

    # A constant cannot also be an unknown, and a value cannot be given twice.
    clash = call_in_process("math_solve", {"equations": ["0 = 20 - g*t"], "unknowns": ["g"], "constants": every_source})
    assert clash["error"]["code"] == 4
    twice = call_in_process("math_evaluate", {"expression": "g", "values": {"g": 10}, "constants": every_source})
    assert twice["error"]["code"] == 4

    # M12: the physics checkers resolve g the same way (VER-16, VER-17).
    thrown = {"motion": "vertical", "speed": 20, "direction": "up"}
    question = call_in_process("phys_projectile", {**thrown, "constants": every_source})["result"]
    assert question["value"]["max_height"]["text"] == "20" and "warnings" not in question
    assert question["check"]["constants"] == [{"symbol": "g", "value": "10", "unit": "m/s^2", "source": "question"}]
    flat = call_in_process(
        "phys_projectile", {**thrown, "g": 10, "g_source": "question", "constants": every_source[1:2]}
    )
    assert flat["result"]["check"]["constants"][0]["source"] == "question"
    unstated = call_in_process("phys_projectile", thrown)["result"]
    assert unstated["check"]["constants"][0] == {
        "symbol": "g",
        "value": "9.80665",
        "unit": "m/s^2",
        "source": "default",
    }
    assert [w["code"] for w in unstated["warnings"]] == ["convention_default_used"]


def ver17_vertical_motion():
    """A ball thrown up at 20 m/s with g = 10 m/s² reaches 20 m at 2 s (up positive: s = ut - ½gt²)."""
    args = {
        "equations": ["20 = 20*t - 1/2*g*t^2"],
        "unknowns": ["t"],
        "constants": [{"symbol": "g", "value": 10, "unit": "m/s^2", "source": "question"}],
        "positive_direction": "up",
    }
    result = call_in_process("math_solve", args)["result"]
    assert result["value"]["case"] == "solutions"
    assert [s["t"]["text"] for s in result["value"]["solutions"]] == ["2"]
    assert result["value"]["positive_direction"] == "up"
    assert result["check"]["constants"][0]["source"] == "question"
    # The velocity at that moment is zero: the top of the flight.
    velocity = call_in_process(
        "math_evaluate", {"expression": "u - g*t", "values": {"u": 20, "t": 2}, "constants": args["constants"]}
    )
    assert velocity["result"]["value"]["exact"]["text"] == "0"

    # M12: the same problem with quantities and units, dimension-checked, solved in the unit asked for.
    with_units = {**args, "equations": ["s = u*t - 1/2*g*t^2"], "units": {"t": "s"},
                  "quantities": {"s": "20 m", "u": "72 km/h"}}  # fmt: skip
    solved = call_in_process("math_solve", with_units)["result"]["value"]
    assert solved["solutions"] == [{"t": {"text": "2", "latex": "2", "decimal": "2.00000", "unit": "s"}}]
    assert solved["positive_direction"] == "up"
    in_kmh = call_in_process(
        "math_solve",
        {
            "equations": ["v = u - g*t"],
            "unknowns": ["v"],
            "units": {"v": "km/h"},
            "quantities": {"u": "20 m/s", "t": "1 s"},
            "constants": args["constants"],
        },
    )
    assert in_kmh["result"]["value"]["solutions"][0]["v"]["text"] == "36"  # 10 m/s
    wrong = call_in_process("math_solve", {**with_units, "quantities": {"s": "20 m/s", "u": "20 m/s"}})["error"]
    assert wrong["code"] == 4 and "found m, expected m s⁻¹" in wrong["message"]  # both dimensions named

    # M12: phys_projectile gives the whole flight for the simulation and the motion graphs (up positive).
    flight = call_in_process(
        "phys_projectile", {"motion": "vertical", "speed": 20, "direction": "up", "g": 10, "g_source": "question"}
    )["result"]
    value = flight["value"]
    assert (value["time_to_max_height"]["text"], value["max_height"]["text"]) == ("2", "20")
    assert (value["time_of_flight"]["text"], value["range"]["text"]) == ("4", "0")
    assert value["positive_direction"] == "up" and flight["check"]["constants"][0]["source"] == "question"
    top = next(p for p in value["points"] if p["t"] == 2.0)
    assert (top["y"], top["vy"]) == (20.0, 0.0) and len(value["points"]) == 21
    # Horizontal projection from a cliff: t = sqrt(2h/g), range u t.
    cliff = call_in_process(
        "phys_projectile", {"motion": "horizontal", "speed": "72 km/h", "height": "45 m", "g": 10, "g_source": "pack"}
    )["result"]["value"]
    assert (cliff["time_of_flight"]["text"], cliff["range"]["text"]) == ("3", "60")
    assert cliff["landing"]["speed"]["text"] == "10*sqrt(13)" and cliff["points"][-1]["y"] == 0.0
