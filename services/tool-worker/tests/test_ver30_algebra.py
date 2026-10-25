"""VER-30: the A level algebra of `math_simplify` (version 2: partial fractions, Maclaurin, Taylor and binomial series,
complex numbers in Cartesian and modulus-argument form) and `math_solve` (version 4: complex roots, Newton-Raphson,
fixed-point iteration and the sign-change check) through the real fn.call boundary: both golden sets at 100% with
their pinned fingerprints, working lines carrying the check id, and the earlier calls unchanged."""

from __future__ import annotations

import io
import json
from typing import Any

from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.protocol import Code
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000001"
SETS = ("math_simplify.a_level", "math_solve.a_level")


def call(name: str, args: dict[str, Any]) -> dict[str, Any]:
    """One fn.call through the worker's server code, in process: the reply frame."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    return next(r for r in map(json.loads, out.getvalue().splitlines()) if r.get("id") == "1")


def result(name: str, args: dict[str, Any]) -> dict[str, Any]:
    reply = call(name, args)
    assert "result" in reply, reply
    found: dict[str, Any] = reply["result"]
    assert found["check"]["check_id"] == CHECK and found["check"]["function"] == name
    assert all(line["check_id"] == CHECK for line in found.get("working", []))
    return found


def refused(name: str, args: dict[str, Any], code: int = Code.DOMAIN_ERROR) -> str:
    reply = call(name, args)
    assert "result" not in reply and reply["error"]["code"] == code, reply
    return str(reply["error"]["message"])


def outcome(reply: dict[str, Any]) -> Any:
    """The value, or the refusal as golden.run records it."""
    if "result" in reply:
        return reply["result"]["value"]
    return {"error": reply["error"]["code"], "message": reply["error"]["message"]}


def labels(found: dict[str, Any]) -> dict[str, str]:
    return {line["label"]: line["value"] for line in found.get("working", [])}


def test_ver30_algebra_golden_cases_through_fn_call() -> None:
    pinned = json.loads(golden.FINGERPRINTS.read_text())
    loaded = golden.load()
    for name in SETS:
        data = loaded[name]
        tool = data["tool"]
        assert data["stage"] == "S3" and data["version"] == FUNCTIONS[tool].version and len(data["cases"]) >= 100
        failures, drifted = [], []
        for case in data["cases"]:
            reply = call(tool, case["args"])
            value = outcome(reply)
            if not golden.matches(value, case["expect"]):
                failures.append(case["id"])
            if golden.result_sha256(value) != pinned[case["id"]]:
                drifted.append(case["id"])
            if "result" in reply:
                assert reply["result"]["check"]["result_sha256"] == golden.result_sha256(value), case["id"]
                assert all(line["check_id"] == CHECK for line in reply["result"].get("working", [])), case["id"]
        assert failures == [], name
        assert drifted == [], name
        errors = [i for i, c in enumerate(data["cases"]) if "error" in c["expect"]]
        assert errors and errors == list(range(len(data["cases"]) - len(errors), len(data["cases"])))  # sorted last
        assert any(c["origin"] == "hand" for c in data["cases"])


def test_ver30_versions_and_earlier_calls_unchanged() -> None:
    assert (FUNCTIONS["math_simplify"].version, FUNCTIONS["math_solve"].version) == (2, 4)
    solved = result("math_solve", {"equations": ["2x^2 - 8x + 6 = 0"]})["value"]
    one, three = {"text": "1", "latex": "1", "decimal": "1.00000"}, {"text": "3", "latex": "3", "decimal": "3.00000"}
    assert solved == {"case": "solutions", "solutions": [{"x": one}, {"x": three}]}
    # Outside the complex forms and domain, i stays an ordinary real letter.
    assert (
        result("math_simplify", {"expression": "i^2 + 1", "form": "expanded"})["value"]["result"]["text"] == "i**2 + 1"
    )
    assert result("math_solve", {"equations": ["x^2 + 1 = 0"]})["value"] == {"case": "no_solution"}
    assert "apply only to the A level forms" in refused("math_simplify", {"expression": "x + x", "order": 2})
    assert "apply only with a method" in refused("math_solve", {"equations": ["x^2 = 2"], "start": 1})


def test_ver30_partial_fractions_working_shows_the_identity() -> None:
    found = result("math_simplify", {"expression": "(3x+1)/((x-1)(x+2))", "form": "partial_fractions"})
    value = found["value"]
    assert value["result"]["text"] == "5/(3*(x + 2)) + 4/(3*(x - 1))" and value["proper"] is True
    assert value["constants"] == {"A": "5/3", "B": "4/3"}
    lines = labels(found)
    assert lines["identity"] == "(3*x + 1)/(x**2 + x - 2) = A/(x + 2) + B/(x - 1)"
    assert lines["numerators"] == "3*x + 1 = A*(x - 1) + B*(x + 2)"
    assert (lines["A"], lines["B"]) == ("5/3", "4/3")
    # Improper, repeated and quadratic factors.
    improper = result("math_simplify", {"expression": "(x^3+1)/(x^2-1)", "form": "partial_fractions"})["value"]
    assert improper["proper"] is False and improper["quotient"]["text"] == "x"
    mixed = result("math_simplify", {"expression": "1/((x-1)^2(x^2+1))", "form": "partial_fractions"})["value"]
    assert [(t["factor"]["text"], t["power"], t["numerator"]["text"]) for t in mixed["terms"]] == [
        ("x - 1", 1, "-1/2"), ("x - 1", 2, "1/2"), ("x**2 + 1", 1, "x/2")]  # fmt: skip
    assert "polynomial over a polynomial" in refused("math_simplify", {"expression": "sin(x)/x",
                                                                       "form": "partial_fractions"})  # fmt: skip


def test_ver30_binomial_series_reports_its_validity() -> None:
    value = result("math_simplify", {"expression": "3/sqrt(4-x)", "form": "series", "terms": 3})["value"]
    assert value["result"]["text"] == "3/2 + 3*x/16 + 9*x**2/256"
    assert value["binomial"]["rewritten"]["text"] == "3/2*(1 - x/4)^(-1/2)"
    assert (value["validity"]["text"], value["validity"]["radius"]["text"]) == ("Abs(x) < 4", "4")
    natural = result("math_simplify", {"expression": "(1+2x)^3", "form": "series", "order": 5})["value"]
    assert natural["terminates"] is True and natural["binomial"]["natural"] is True
    assert natural["validity"]["all_real"] is True and natural["order"] == 5
    # Maclaurin derivatives in the working; ln x has no Maclaurin series.
    found = result("math_simplify", {"expression": "e^(2x)", "form": "series", "order": 3})
    assert [labels(found)[f"f^({k})(0)"] for k in (1, 2, 3)] == ["2", "4", "8"]
    assert "no series in powers of x" in refused("math_simplify", {"expression": "ln(x)", "form": "series",
                                                                   "order": 2})  # fmt: skip
    taylor = result("math_simplify", {"expression": "1/x", "form": "series", "order": 2, "about": 2})["value"]
    assert taylor["result"]["text"] == "1/2 - (x - 2)/4 + (x - 2)**2/8" and "validity" not in taylor


def test_ver30_series_order_or_terms() -> None:
    by_terms = result("math_simplify", {"expression": "cos(x)", "form": "series", "terms": 3})["value"]
    by_order = result("math_simplify", {"expression": "cos(x)", "form": "series", "order": 4})["value"]
    assert by_terms["result"] == by_order["result"] and by_terms["order"] == 4
    assert "one of them" in refused("math_simplify", {"expression": "cos(x)", "form": "series"})


def test_ver30_complex_forms_exact_where_possible() -> None:
    polar = result("math_simplify", {"expression": "-1 - i", "form": "modulus_argument"})["value"]
    assert (polar["modulus"]["text"], polar["argument"]["text"]) == ("sqrt(2)", "-3*pi/4")
    assert polar["exponential"]["text"] == "sqrt(2)*exp(-3*I*pi/4)"
    assert polar["argument_degrees"]["text"] == "-135"
    # The principal argument is in (-pi, pi]: a negative real number has argument pi.
    assert (
        result("math_simplify", {"expression": "-2", "form": "modulus_argument"})["value"]["argument"]["text"] == "pi"
    )
    general = result("math_simplify", {"expression": "3 + 4i", "form": "modulus_argument"})["value"]
    assert (general["argument"]["text"], general["argument"]["decimal"]) == ("atan(4/3)", "0.927295")
    back = result("math_simplify", {"expression": "2e^(i pi/3)", "form": "cartesian"})["value"]
    assert back["result"]["text"] == "1 + sqrt(3)*I" and back["result"]["decimal"] == "1.00000 + 1.73205i"
    assert "0 has no argument" in refused("math_simplify", {"expression": "0", "form": "modulus_argument"})
    assert "found x" in refused("math_simplify", {"expression": "x + 2i", "form": "cartesian"})


def test_ver30_complex_roots_in_conjugate_pairs() -> None:
    found = result("math_solve", {"equations": ["z^3 - 3z^2 + 4z - 2 = 0"], "domain": "complex"})
    value = found["value"]
    assert [s["z"]["text"] for s in value["solutions"]] == ["1 - I", "1", "1 + I"]
    assert value["conjugate_pairs"] == [[0, 2]] and value["real_coefficients"] is True
    quadratic = result("math_solve", {"equations": ["w^2 + 4w + 13 = 0"], "domain": "complex"})
    assert labels(quadratic)["discriminant"] == "-36"
    assert [s["w"]["decimal"] for s in quadratic["value"]["solutions"]] == ["-2.00000 - 3.00000i",
                                                                            "-2.00000 + 3.00000i"]  # fmt: skip
    rooted = result("math_solve", {"equations": ["z^2 = 2i"], "domain": "complex"})["value"]
    assert rooted["conjugate_pairs"] == [] and rooted["real_coefficients"] is False
    assert "polynomial" in refused("math_solve", {"equations": ["e^z = 1"], "domain": "complex"})


def test_ver30_newton_raphson_iterates_and_failure() -> None:
    found = result("math_solve", {"equations": ["x^3 - 2x - 5 = 0"], "method": "newton_raphson", "start": 2,
                                  "steps": 3, "dp": 6})  # fmt: skip
    value = found["value"]
    assert [i["x"]["decimal"] for i in value["iterates"]] == ["2.000000", "2.100000", "2.094568", "2.094551"]
    assert value["iterates"][2]["x"]["text"] == "11761/5615" and value["stopped"] == "steps"
    assert (found["check"]["method"], found["check"]["confidence"]) == ("rule_based", "proved")
    assert labels(found)["f'(x_0)"] == "10.00000000"
    flat = result("math_solve", {"equations": ["x^2 - 4 = 0"], "method": "newton_raphson", "start": 0,
                                 "steps": 3, "first_index": 1})["value"]  # fmt: skip
    assert (flat["stopped"], flat["at"], len(flat["iterates"])) == ("derivative_zero", 1, 1)
    assert "needs start" in refused("math_solve", {"equations": ["x^2 = 2"], "method": "newton_raphson", "steps": 2})


def test_ver30_iteration_convergence_and_diagram() -> None:
    converging = result("math_solve", {"equations": ["x^3 - 2x - 5 = 0"], "method": "iteration", "g": "x = cbrt(2x+5)",
                                       "start": 2, "tolerance": "0.00005", "dp": 4})["value"]  # fmt: skip
    assert converging["stopped"] == "tolerance" and converging["root"]["decimal"] == "2.0945"
    assert converging["convergence"] | {"g_prime": None} == {
        "status": "ok", "root": {"decimal": "2.0946", "text": "2.09455148154233"}, "g_prime": None, "converges": True,
        "diagram": "staircase", "rearrangement_matches": True}  # fmt: skip
    diverging = result("math_solve", {"equations": ["x^3 - 2x - 5 = 0"], "method": "iteration", "g": "(x^3 - 5)/2",
                                      "start": 2, "steps": 10})["value"]  # fmt: skip
    assert diverging["stopped"] == "diverged" and diverging["convergence"]["converges"] is False
    oscillating = result("math_solve", {"equations": ["x = e^(-x)"], "method": "iteration", "g": "e^(-x)",
                                        "start": "0.5", "steps": 3})["value"]  # fmt: skip
    assert oscillating["convergence"]["diagram"] == "cobweb" and oscillating["convergence"]["converges"] is True
    wrong = result("math_solve", {"equations": ["x^3 - 2x - 5 = 0"], "method": "iteration", "g": "sqrt(x + 2)",
                                  "start": 2, "steps": 2})["value"]  # fmt: skip
    assert wrong["convergence"]["rearrangement_matches"] is False
    # A cube root of a negative number is real, as on a calculator: x^3 + x + 2 = 0 has the root -1.
    negative = result("math_solve", {"equations": ["x^3 + x + 2 = 0"], "method": "iteration", "g": "cbrt(-x - 2)",
                                     "start": "-1/2", "tolerance": "1e-6", "dp": 4})["value"]  # fmt: skip
    assert negative["stopped"] == "tolerance" and negative["root"]["decimal"] == "-1.0000"
    assert negative["iterates"][1]["x"]["decimal"] == "-1.1447"  # -(3/2)^(1/3)
    assert "needs g" in refused("math_solve", {"equations": ["x^3 = 5"], "method": "iteration", "start": 2,
                                               "steps": 2})  # fmt: skip


def test_ver30_sign_change_bound_and_continuity() -> None:
    value = result("math_solve", {"equations": ["x^3 - 2x - 5 = 0"], "method": "sign_change",
                                  "interval": ["2.0945", "2.0955"]})["value"]  # fmt: skip
    assert value["root_located"] is True
    assert (value["estimate"]["text"], value["error_bound"]["text"]) == ("419/200", "1/2000")
    pole = result("math_solve", {"equations": ["1/(x-1) = 0"], "method": "sign_change", "interval": [0, 2]})["value"]
    assert (pole["sign_change"], pole["continuous"], pole["root_located"]) == (True, False, False)
    assert "estimate" not in pole
    assert "needs interval" in refused("math_solve", {"equations": ["x^3 = 5"], "method": "sign_change"})


def test_ver30_schema_refuses_what_it_does_not_know() -> None:
    assert refused("math_solve", {"equations": ["x^2 = 2"], "method": "bisection", "start": 1, "steps": 2},
                   Code.INVALID_PARAMS)  # fmt: skip
    assert refused("math_solve", {"equations": ["x^2 = 2"], "method": "newton_raphson", "start": 1, "steps": 51},
                   Code.INVALID_PARAMS)  # fmt: skip
    assert refused("math_simplify", {"expression": "e^x", "form": "series", "order": 11}, Code.INVALID_PARAMS)
    assert refused("math_simplify", {"expression": "e^x", "form": "polar"}, Code.INVALID_PARAMS)


def test_ver30_results_are_byte_identical() -> None:
    for name, args in [("math_solve", {"equations": ["e^x = 3x"], "method": "newton_raphson", "start": 0,
                                       "tolerance": "1e-9", "dp": 8}),
                       ("math_simplify", {"expression": "e^x sin(x)", "form": "series", "order": 5})]:  # fmt: skip
        first, second = result(name, args), result(name, args)
        assert first["check"]["result_sha256"] == second["check"]["result_sha256"]
        assert first["value"] == second["value"]
