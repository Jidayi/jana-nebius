"""M26.a: A level mathematics (VER-30): implicit and parametric differentiation, volumes of revolution, the trapezium
rule, substitution and parts, separable differential equations (`math_solve_ode`) and statistics
(`stats_distribution`), through the real worker boundary and against the S3 golden sets."""

from jana_tools import golden
from test_m12d_accounting import call

CALCULUS_SETS = ("math_differentiate.a_level", "math_integrate.a_level", "math_solve_ode")
STATISTICS_SETS = ("stats_distribution",)
ALGEBRA_SETS = ("math_simplify.a_level", "math_solve.a_level")


def _golden_failures(names: tuple[str, ...]) -> dict[str, list[str]]:
    data = golden.load()
    failures = {}
    for name in names:
        assert data[name]["stage"] == "S3" and len(data[name]["cases"]) >= 100, name
        failures[name] = [c["id"] for c in data[name]["cases"]
                          if not golden.matches(golden.run(c, data[name]["tool"]), c["expect"])]  # fmt: skip
    return {k: v for k, v in failures.items() if v}


def ver30_a_level_maths_golden() -> None:
    # Implicit: x² + y² = 25 at (3, 4) has gradient -3/4; a point off the curve is refused.
    circle = call("math_differentiate", {"mode": "implicit", "expression": "x^2 + y^2 = 25", "point": [3, 4],
                                         "student": "-x/y"})["result"]  # fmt: skip
    assert circle["value"]["at"]["gradient"]["text"] == "-3/4" and circle["value"]["student"]["value"] == "correct"
    assert circle["working"][0]["check_id"] == circle["check"]["check_id"]
    off = call("math_differentiate", {"mode": "implicit", "expression": "x^2 + y^2 = 25", "point": [1, 1]})
    assert off["error"]["code"] == 4
    # Parametric: x = cos t, y = sin t at t = 0 has a vertical tangent, stated rather than divided by zero.
    vertical = call("math_differentiate", {"mode": "parametric", "x_expression": "cos(t)", "y_expression": "sin(t)",
                                           "at": "pi/2"})["result"]["value"]  # fmt: skip
    assert vertical["at"]["gradient"]["text"] == "0" and vertical["at"]["normal"]["vertical"] is True
    # Volume of revolution with an exact constant limit; the trapezium rule over-estimates a convex curve.
    volume = call("math_integrate", {"expression": "e^x", "volume": "x_axis", "lower": 0, "upper": "ln(2)"})
    assert volume["result"]["value"]["volume"]["value"]["text"] == "3*pi/2"
    trapezium = call("math_integrate", {"expression": "x^2", "method": "trapezium", "strips": 2, "lower": 0,
                                        "upper": 2})["result"]["value"]  # fmt: skip
    assert trapezium["estimate"]["text"] == "3" and trapezium["error"]["text"] == "1/3"
    assert trapezium["estimate_kind"] == "overestimate" and trapezium["percentage_error"] == "12.50"
    # A substitution changes the limits; parts names u, dv and the remaining integral.
    substituted = call("math_integrate", {"expression": "x (x^2 + 1)^3", "substitution": "u = x^2 + 1", "lower": 0,
                                          "upper": 1})["result"]["value"]  # fmt: skip
    assert [u["text"] for u in substituted["limits_in_u"]] == ["1", "2"] and substituted["definite"]["text"] == "15/8"
    by_parts = call("math_integrate", {"expression": "x e^x", "parts_u": "x"})["result"]["value"]
    assert by_parts["remaining_integral"]["text"] == "exp(x)" and by_parts["antiderivative"]["text"] == "(x - 1)*exp(x)"
    # Separable ODE: the constant from the condition, the branch through the point, a value; ln|y| in the working.
    growth = call("math_solve_ode", {"rhs": "x y", "condition": [0, -2], "at": 1})["result"]
    assert growth["value"]["particular"]["text"] == "-2*exp(x**2/2)"
    assert growth["value"]["implicit"]["text"] == "log(Abs(y)) = x**2/2 + c"
    assert growth["value"]["at"]["y"]["decimal"] == "-3.29744"
    branch = call("math_solve_ode", {"rhs": "x/y", "condition": [0, -3]})["result"]["value"]
    assert branch["particular"]["text"] == "-sqrt(x**2 + 9)"
    # A student's solution is checked by substitution; one that misses the condition is incorrect.
    student = call("math_solve_ode", {"rhs": "x y", "student": "2 e^(x^2/2)", "condition": [0, 3]})["result"]
    assert student["value"]["student"] == {"satisfies_equation": True, "satisfies_condition": False,
                                           "value": "incorrect"}  # fmt: skip
    # Not separable: unknown, never solved by another method silently.
    linear = call("math_solve_ode", {"rhs": "x + y"})["result"]
    assert linear["value"] == {"status": "unknown", "reason": "not_separable"}
    assert linear["check"]["confidence"] == "undecided"

    # Statistics: B(20, 0.3) exactly, the 5% upper point of the normal, and a two-tailed binomial critical region.
    binomial = call("stats_distribution", {"task": "binomial", "n": 20, "p": "0.3", "relation": "le", "k": 4})
    assert binomial["result"]["value"]["probability"]["decimal"] == "0.2375"
    point = call("stats_distribution", {"task": "normal", "find": "value", "mean": 0, "sd": 1, "probability": "0.05",
                                        "tail": "above", "normal_values": "tables"})["result"]  # fmt: skip
    assert point["check"]["method"] == "table_lookup"
    region = call(
        "stats_distribution",
        {
            "task": "hypothesis_test",
            "test": "binomial",
            "n": 20,
            "p": "0.3",
            "alternative": "two_sided",
            "significance_level": "0.05",
        },
    )["result"]["value"]
    assert region["critical_region"]["lower"]["x_max"] == 1 and region["critical_region"]["upper"]["x_min"] == 11
    # A bare 5 is ambiguous between 5% and 0.05: refused, never guessed.
    ambiguous = call("stats_distribution", {"task": "hypothesis_test", "test": "binomial", "n": 20, "p": "0.3",
                                            "alternative": "greater", "significance_level": 5})  # fmt: skip
    assert "error" in ambiguous

    # The A level calculus and statistics golden sets (stage S3) pass at 100%.
    # Algebra: partial fractions, a binomial series with its validity, complex roots, Newton-Raphson.
    fractions = call("math_simplify", {"expression": "(5x+3)/((1+x)(1-2x))", "form": "partial_fractions"})
    assert fractions["result"]["value"]["status"] == "ok" and fractions["result"]["working"]
    roots = call("math_solve", {"equations": ["z^2 + 2z + 5 = 0"], "domain": "complex"})["result"]["value"]
    assert [s["z"]["text"] for s in roots["solutions"]] == ["-1 - 2*I", "-1 + 2*I"]
    assert roots["conjugate_pairs"] == [[0, 1]]
    newton = call("math_solve", {"equations": ["x^2 - 2 = 0"], "method": "newton_raphson", "start": 1, "steps": 3})
    assert [i["x"]["text"] for i in newton["result"]["value"]["iterates"]] == ["1", "3/2", "17/12", "577/408"]

    # The A level calculus, algebra and statistics golden sets (stage S3) pass at 100%.
    assert _golden_failures(CALCULUS_SETS + ALGEBRA_SETS + STATISTICS_SETS) == {}
