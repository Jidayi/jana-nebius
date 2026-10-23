"""M12.a: the mathematics checkers of verification breadth (VER-08, VER-09, VER-10, VER-13, VER-14, VER-15).

The acceptance tests call the real worker server code in process; the golden sets run in full, and every new tool's
results carry a schema-valid check record."""

import io
import json
from functools import cache

from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.tools.catalogue import visible_tools
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.spec import SessionCtx
from agent_core.tools.specs import M12_TOOLS, registry
from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000012"


def call(name: str, args: dict, settings: dict | None = None) -> dict:
    """One call through the real server code, in process: the reply's `result` (or `error`)."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits(**(settings or {})))
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": CHECK,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    reply = next(r for r in (json.loads(line) for line in out.getvalue().splitlines()) if r.get("id") == "1")
    return reply.get("result") or {"error": reply["error"]}


@cache
def _maths_golden() -> dict[str, list[tuple[dict, object]]]:
    sets = golden.load()
    return {name: [(case, golden.run(case, name)) for case in sets[name]["cases"]] for name in sorted(M12_TOOLS)}


# --- acceptance ----------------------------------------------------------------------------------------------------


def ver08_constant_of_integration():
    result = call("math_integrate", {"expression": "x^2", "student": "x^3/3"})
    assert result["value"]["student"] == {"value": "correct", "form": "missing_constant"}
    assert result["value"]["antiderivative"]["text"] == "x**3/3"
    assert result["check"]["confidence"] == "proved"
    with_constant = call("math_integrate", {"expression": "x^2", "student": "x^3/3 + c"})["value"]["student"]
    assert (with_constant["value"], with_constant["form"]) == ("correct", "ok")
    wrong = call("math_integrate", {"expression": "x^2", "student": "x^3 + c"})["value"]["student"]
    assert wrong["value"] == "incorrect"


def ver10_composite_components():
    convertible = call("math_check_answer", {"student": "2 km", "key": "2000 m"})["value"]
    assert convertible["verdict"] == "correct"
    assert convertible["components"]["value"] == "correct" and convertible["components"]["unit"] == "convertible"
    seconds = call("math_check_answer", {"student": "2000 s", "key": "2000 m"})["value"]
    assert seconds["components"]["unit"] == "wrong_dimension" and seconds["verdict"] == "incorrect"
    # A rule that fixes the unit makes the convertible answer wrong; a missing unit costs what the rule says.
    fixed = call("math_check_answer", {"student": "2 km", "key": "2000 m", "rule": {"unit_policy": "exact"}})
    assert fixed["value"]["verdict"] == "incorrect" and fixed["value"]["because"] == ["unit"]
    bare = call("math_check_answer", {"student": "2000", "key": "2000 m"})["value"]
    assert bare["components"]["unit"] == "missing" and bare["verdict"] == "partial"
    assert set(convertible["components"]) == {"value", "unit", "precision", "form"}


def ver10_form_vs_value():
    found = call("math_check_answer", {"student": "2(x+3)", "key": "2x+6", "rule": {"form": "expanded"}})["value"]
    assert found["components"]["value"] == "correct"
    assert found["components"]["form"] == "not_expanded" and found["verdict"] == "partial"
    met = call("math_check_answer", {"student": "2x+6", "key": "2(x+3)", "rule": {"form": "expanded"}})["value"]
    assert met["components"]["form"] == "ok" and met["verdict"] == "correct"
    unsimplified = call("math_check_answer", {"student": "2/4", "key": "1/2", "rule": {"form": "simplest"}})["value"]
    assert unsimplified["components"] | {"precision": None} == {"value": "correct", "unit": "ok", "precision": None,
                                                                 "form": "unsimplified"}  # fmt: skip


def ver13_grouped_mean_exact():
    classes = [{"lower": 0, "upper": 5, "frequency": 3}, {"lower": 5, "upper": 10, "frequency": 4},
               {"lower": 10, "upper": 20, "frequency": 5}]  # fmt: skip
    # By hand: (2.5 x 3 + 7.5 x 4 + 15 x 5) / 12 = 112.5 / 12 = 75/8.
    value = call("stats_compute", {"grouped": classes})["value"]
    assert value["mean"]["text"] == "75/8" and value["mean"]["decimal"] == "9.37500"
    assert value["modal_by"] == "frequency_density" and value["modal_class"][0]["lower"]["text"] == "5"
    # Median by interpolation: position 6 lies in 5-10 (cumulative 3 before it): 5 + (6 - 3)/4 x 5 = 35/4.
    assert value["median"]["text"] == "35/4"
    failures = [c["id"] for c, v in _maths_golden()["stats_compute"] if not golden.matches(v, c["expect"])]
    assert failures == []
    # The quartile method is a parameter, from the pack's convention when the call names none, else the default.
    listed = call("stats_compute", {"data": [1, 2, 3, 4, 5, 6, 7]})
    assert listed["value"]["quartiles"]["method"] == "exclusive"
    assert [w["code"] for w in listed["warnings"]] == ["convention_default_used"]


def ver14_asymptote_split():
    result = call("math_plot_points", {"curves": [{"id": "f", "expr": "1/(x-2)"}], "x_range": [-5, 5]})
    curve = result["value"]["curves"][0]
    assert len(curve["segments"]) == 2
    left, right = curve["segments"]
    assert max(p[0] for p in left) < 2 < min(p[0] for p in right)
    assert all(p[1] < 0 for p in left) and all(p[1] > 0 for p in right)
    assert [a["x"]["text"] for a in curve["asymptotes"]] == ["2"]
    assert curve["roots"] == []  # no false root where the sign changes across the asymptote
    assert curve["points"] <= Settings().ver_plot_max_points
    assert all(f["check_id"] == CHECK for f in (*curve["asymptotes"], curve["y_intercept"]))
    assert result["check"]["confidence"] == "proved"


def ver15_ambiguous_case():
    result = call("geom_figure", {"template": "triangle", "givens": {"A": 30, "a": 5, "b": 8}})
    value = result["value"]
    assert value["ambiguous"] is True and len(value["solutions"]) == 2
    # sin B = 8 sin 30° / 5 = 4/5: B = 53.13° or 126.87°, and c = 4√3 ± 3 (by the cosine of each B).
    assert [s["angles"]["B"]["decimal"] for s in value["solutions"]] == ["53.1301", "126.870"]
    assert [s["sides"]["c"]["text"] for s in value["solutions"]] == ["3 + 4*sqrt(3)", "-3 + 4*sqrt(3)"]
    one = call("geom_figure", {"template": "triangle", "givens": {"A": 30, "a": 10, "b": 8}})["value"]
    assert one["ambiguous"] is False and len(one["solutions"]) == 1
    none = call("geom_figure", {"template": "triangle", "givens": {"A": 30, "a": 3, "b": 8}})
    assert none["error"]["code"] == 4
    over = call("geom_figure", {"template": "triangle", "givens": {"A": 100, "B": 90, "c": 10}})
    assert over["error"]["code"] == 4


# --- supporting checks ----------------------------------------------------------------------------------------------


def test_power_after_a_letter_run_binds_to_its_last_letter():
    """VER-03: in a run of letters split into a product, a power belongs to the last letter only: ab^2 is a*b^2,
    as a student means it, never (ab)^2."""
    same = call("math_check_equivalence", {"a": "5(3a^2b + 2ab^2)", "b": "5ab(3a + 2b)"})["value"]
    assert same["verdict"] == "equivalent", same
    for written, meant in [("10ab^2", "10*a*b^2"), ("xy²", "x*y^2"), ("3pq^{3}", "3*p*q^3"), ("ab", "a*b")]:
        value = call("math_check_equivalence", {"a": written, "b": meant})["value"]
        assert value["verdict"] == "equivalent", (written, value)
    assert call("math_check_equivalence", {"a": "(ab)^2", "b": "a^2b^2"})["value"]["verdict"] == "equivalent"


def test_inverse_trig_answers_in_degrees_at_special_angles():
    """asin, acos and atan answer in degrees when degrees are asked for, and by default at O level, including the
    arguments whose angle is a simple multiple of pi (which must not collapse to radians while parsing)."""
    for expression, degrees in [("asin(1/2)", "30"), ("acos(0)", "90"), ("atan(1)", "45"), ("atan(sqrt(3))", "60"),
                                ("2*asin(1/2)+1", "61"), ("asin(0.3)", "180*asin(3/10)/pi")]:  # fmt: skip
        value = call("math_evaluate", {"expression": expression, "angle_unit": "degrees"})["value"]
        assert value["exact"]["text"] == degrees, expression
    by_default = call("math_evaluate", {"expression": "asin(1/2)", "level": "O"})
    assert by_default["value"]["exact"]["text"] == "30"
    assert any(w["code"] == "assumption_added" for w in by_default.get("warnings", [])), by_default
    radians = call("math_evaluate", {"expression": "asin(1/2)", "angle_unit": "radians"})["value"]
    assert radians["exact"]["text"] == "pi/6"


def test_ver09_table_rows():
    """The rows of TABLE VER-09a through math_check_answer."""

    def check(student: str, key: str, **rule: object) -> dict:
        return call("math_check_answer", {"student": student, "key": key, "rule": rule})

    drift = check("9.75", "9.81", carried=True)
    assert drift["value"]["components"]["value"] == "within_tolerance" and drift["value"]["verdict"] == "correct"
    assert [w["code"] for w in drift["warnings"]] == ["rounding_drift"]
    assert check("9.70", "9.81", carried=True)["value"]["verdict"] == "incorrect"  # beyond the 1% share
    assert check("12.50", "12.5", quantity="money", dp=2)["value"]["verdict"] == "correct"
    assert check("12.5", "12.50", quantity="money", dp=2)["value"]["components"]["precision"]["dp"] == "wrong"
    assert check("13", "12.6", quantity="money", dp=0)["value"]["verdict"] == "correct"
    assert check("36.8", "36.87", quantity="angle")["value"]["components"]["value"] == "within_tolerance"
    assert check("36.7", "36.87", quantity="angle")["value"]["verdict"] == "incorrect"
    exact = check("1.414", "sqrt(2)", quantity="exact")["value"]
    assert exact["components"]["form"] == "not_exact" and exact["verdict"] == "partial"
    assert check("1/3", "1/3", quantity="probability")["value"]["verdict"] == "correct"
    assert check("0.333", "1/3", quantity="probability")["value"]["verdict"] == "correct"
    assert check("0.33", "1/3", quantity="probability")["value"]["components"]["precision"]["sf"] == "too_few"
    # A pack convention or the configured default sets the item's precision when the rule is silent.
    assert check("9.8066", "9.80665")["value"]["components"]["precision"]["sf"] == "too_many"
    four = call("math_check_answer", {"student": "9.807", "key": "9.80665"}, settings={"default_sf": 4})
    assert four["value"]["components"]["precision"]["sf"] == "ok"


def test_m12a_golden_sets_pass():
    sizes = {name: len(results) for name, results in _maths_golden().items()}
    assert all(n >= Settings().golden_min_cases_per_tool for n in sizes.values()), sizes
    failures = [
        c["id"] for results in _maths_golden().values() for c, v in results if not golden.matches(v, c["expect"])
    ]
    assert failures == []
    for name in M12_TOOLS:
        assert golden.load()[name]["stage"] == "S2" and golden.load()[name]["review"] == "pending"


def test_m12a_check_records_valid():
    for name in sorted(M12_TOOLS):
        for case in golden.load()[name]["cases"][:6]:
            result = call(name, case["args"])
            assert "error" not in result, (name, case["id"], result)
            assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", result) == [], (name, case["id"])
            assert result["check"]["function"] == name and result["check"]["check_id"] == CHECK
            assert result["check"]["result_sha256"] == golden.result_sha256(result["value"])


def test_m12a_tools_offered_early():
    """The S2 mathematics tools ship in the S1 build and are offered to the Solver in a mathematics session."""
    tools = registry()
    assert M12_TOOLS <= set(tools.specs)
    session = SessionCtx(subject="mathematics", level="O", session_id="ses_01JZ0000000000000000000012")
    offered = visible_tools("solver", list(tools.specs), tools, session, lambda spec, ctx: True,
                            REGISTER["roleGrants"], Settings())  # fmt: skip
    assert M12_TOOLS <= {s.name for s in offered}
