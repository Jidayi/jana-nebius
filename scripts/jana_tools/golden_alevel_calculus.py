"""Golden sets for the A level calculus checkers (VER-30; VER-29), built by construction with their own seed so every
other set is unchanged.

Expected answers never come from the checkers under test. Implicit curves pass through a chosen lattice point, and the
gradient there is -H_x / H_y from the hand-written partial derivatives; parametric curves are chosen polynomials in t,
differentiated by the power rule; volumes, trapezium estimates, substitutions and integrals by parts are computed with
exact fractions from antiderivatives written by hand; separable differential equations are built from a chosen
solution (exponential growth and decay, y = Cx^n, y² = x² + C), and their values are computed with mpmath at high
precision and rounded half away from zero. Every case is synthetic; each set says `review: pending` until two subject
teachers have authored and reviewed it."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from math import comb
from typing import Any

import mpmath

Case = dict[str, Any]
SEED = 20261030


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> Case:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _errors_last(cases: list[Case]) -> list[Case]:
    return [c for c in cases if "error" not in c["expect"]] + [c for c in cases if "error" in c["expect"]]


def _text(value: Fraction | int) -> str:
    """An exact rational as the checker writes it: p, or p/q in lowest terms."""
    return str(Fraction(value))


def _sf(value: Any, sf: int = 6) -> str:
    """Half away from zero to `sf` significant figures, as decimal text."""
    d = Decimal(mpmath.nstr(value, 40, strip_zeros=False))
    if d == 0:
        return "0"
    quantum = Decimal(1).scaleb(d.adjusted() - sf + 1)
    return format(d.quantize(quantum, rounding=ROUND_HALF_UP), "f")


def _poly(coefficients: list[int], var: str) -> str:
    """A polynomial written for the parser, highest power first: [a, b, c] -> a var^2 + b var + c."""
    degree = len(coefficients) - 1
    terms = []
    for k, a in enumerate(coefficients):
        power = degree - k
        if a == 0:
            continue
        body = "" if power == 0 else var if power == 1 else f"{var}^{power}"
        coef = str(a) if (power == 0 or abs(a) != 1) else ("-" if a < 0 else "")
        terms.append(f"{coef}{'*' if coef not in ('', '-') and body else ''}{body}")
    return " + ".join(terms).replace("+ -", "- ") or "0"


def _value(coefficients: list[int], t: Fraction) -> Fraction:
    out = Fraction(0)
    for a in coefficients:
        out = out * t + a
    return out


def _derivative(coefficients: list[int]) -> list[int]:
    degree = len(coefficients) - 1
    return [a * (degree - k) for k, a in enumerate(coefficients[:-1])] or [0]


# --- math_differentiate: implicit and parametric -------------------------------------------------------------------


def differentiation_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("implicit_circle_doc", {"mode": "implicit", "expression": "x^2 + y^2 = 25", "point": [3, 4]},
              {"status": "ok", "derivative": {"text": "-x/y"},
               "at": {"gradient": {"text": "-3/4"}, "tangent": {"text": "y = 25/4 - 3*x/4"}}}, "hand"),
        _case("parametric_doc", {"mode": "parametric", "x_expression": "t^2", "y_expression": "2t", "order": 2,
                                 "at": 2},
              {"status": "ok", "derivative": {"text": "1/t"}, "second_derivative": {"text": "-1/(2*t**3)"},
               "at": {"x": {"text": "4"}, "y": {"text": "4"}, "gradient": {"text": "1/2"}}}, "hand"),
        _case("parametric_vertical_tangent", {"mode": "parametric", "x_expression": "cos(t)",
                                              "y_expression": "sin(t)", "at": 0},
              {"status": "ok", "at": {"gradient": {"vertical": True}, "tangent": {"vertical": True}}}, "hand"),
        _case("implicit_point_off_curve", {"mode": "implicit", "expression": "x^2 + y^2 = 25", "point": [1, 1]},
              {"error": 4}, "hand"),
        _case("implicit_needs_equation", {"mode": "implicit", "expression": "x^2 + y^2"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(60):
        while True:
            a, b, d, e = rng.randint(-3, 3), rng.choice([-2, -1, 1, 2, 3]), rng.randint(-4, 4), rng.randint(-4, 4)
            x0, y0 = rng.randint(-4, 4), rng.choice([-3, -2, -1, 1, 2, 3])
            hx, hy = 2 * x0 + a * y0 + d, a * x0 + 2 * b * y0 + e
            if hy != 0:
                break
        k = x0 * x0 + a * x0 * y0 + b * y0 * y0 + d * x0 + e * y0
        lhs = f"x^2 + {a}*x*y + {b}*y^2 + {d}*x + {e}*y".replace("+ -", "- ")
        args: dict[str, Any] = {"mode": "implicit", "expression": f"{lhs} = {k}", "point": [x0, y0]}
        cases.append(
            _case(
                f"implicit_{i:03d}",
                args,
                {
                    "status": "ok",
                    "at": {
                        "x": {"text": _text(x0)},
                        "y": {"text": _text(y0)},
                        "gradient": {"text": _text(Fraction(-hx, hy))},
                    },
                },
            )
        )
    for i in range(60):
        while True:
            xs = [rng.randint(-3, 3), rng.randint(-5, 5), rng.randint(-5, 5)]
            ys = [rng.randint(-2, 2), rng.randint(-3, 3), rng.randint(-5, 5), rng.randint(-5, 5)]
            t0 = Fraction(rng.randint(-4, 4))
            dx, dy = _value(_derivative(xs), t0), _value(_derivative(ys), t0)
            if dx != 0 and xs[:2] != [0, 0] and ys[:3] != [0, 0, 0]:
                break
        args = {"mode": "parametric", "x_expression": _poly(xs, "t"), "y_expression": _poly(ys, "t"),
                "at": int(t0)}  # fmt: skip
        cases.append(_case(f"parametric_{i:03d}", args, {"status": "ok", "at": {
            "x": {"text": _text(_value(xs, t0))}, "y": {"text": _text(_value(ys, t0))},
            "gradient": {"text": _text(dy / dx)}}}))  # fmt: skip
    return _errors_last(cases)


# --- math_integrate: volumes, trapezium rule, substitution, parts --------------------------------------------------


def integration_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("volume_sqrt_doc", {"expression": "sqrt(x)", "volume": "x_axis", "lower": 0, "upper": 4},
              {"status": "ok", "volume": {"value": {"text": "8*pi"}, "over_pi": {"text": "8"}}}, "hand"),
        _case("volume_exp_ln_limit", {"expression": "e^x", "volume": "x_axis", "lower": 0, "upper": "ln(2)"},
              {"status": "ok", "volume": {"value": {"text": "3*pi/2"}}}, "hand"),
        _case("trapezium_doc", {"expression": "x^2", "method": "trapezium", "strips": 2, "lower": 0, "upper": 2},
              {"status": "ok", "estimate": {"text": "3"}, "exact": {"text": "8/3"}, "error": {"text": "1/3"},
               "percentage_error": "12.50", "estimate_kind": "overestimate"}, "hand"),
        _case("parts_xex_doc", {"expression": "x e^x", "parts_u": "x", "lower": 0, "upper": 1},
              {"status": "ok", "antiderivative": {"text": "(x - 1)*exp(x)"}, "definite": {"text": "1"}}, "hand"),
        _case("substitution_doc", {"expression": "x (x^2 + 1)^3", "substitution": "u = x^2 + 1", "lower": 0,
                                   "upper": 1},
              {"status": "ok", "integrand_in_u": {"text": "u**3/2"}, "definite": {"text": "15/8"}}, "hand"),
        _case("volume_discontinuous", {"expression": "1/x", "volume": "x_axis", "lower": -1, "upper": 1},
              {"error": 4}, "hand"),
        _case("substitution_not_an_equation", {"expression": "x^2", "substitution": "x^2 + 1"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(30):  # volumes of y = mx + k about the x-axis: π∫(mx + k)² dx = π[(mx + k)³ / 3m]
        m, k = rng.choice([-3, -2, -1, 1, 2, 3]), rng.randint(-5, 5)
        p, q = sorted(rng.sample(range(-4, 6), 2))
        over_pi = Fraction((m * q + k) ** 3 - (m * p + k) ** 3, 3 * m)
        args = {"expression": _poly([m, k], "x"), "volume": "x_axis", "lower": p, "upper": q}
        cases.append(_case(f"volume_{i:03d}", args, {"status": "ok", "volume": {"over_pi": {"text": _text(over_pi)}}}))
    for i in range(30):  # the trapezium rule on a quadratic: the error is -(b - a) h² f'' / 12 exactly
        a2, a1, a0 = rng.choice([-3, -2, -1, 1, 2, 3]), rng.randint(-5, 5), rng.randint(-5, 5)
        n, h = rng.randint(2, 6), Fraction(rng.choice([1, 2, 3]), rng.choice([1, 2]))
        lo = Fraction(rng.randint(-3, 3))
        hi = lo + n * h
        ys = [_value([a2, a1, a0], lo + j * h) for j in range(n + 1)]
        estimate = h / 2 * (ys[0] + 2 * sum(ys[1:-1]) + ys[-1])

        def antiderivative(x: Fraction, a2: int = a2, a1: int = a1, a0: int = a0) -> Fraction:
            return Fraction(a2, 3) * x**3 + Fraction(a1, 2) * x**2 + a0 * x

        exact = antiderivative(hi) - antiderivative(lo)
        args = {"expression": _poly([a2, a1, a0], "x"), "method": "trapezium", "strips": n,
                "lower": _text(lo), "upper": _text(hi)}  # fmt: skip
        cases.append(
            _case(
                f"trapezium_{i:03d}",
                args,
                {
                    "status": "ok",
                    "estimate": {"text": _text(estimate)},
                    "exact": {"text": _text(exact)},
                    "error": {"text": _text(estimate - exact)},
                    "estimate_kind": "overestimate" if a2 > 0 else "underestimate",
                },
            )
        )
    for i in range(30):  # ∫ x (x² + k)^n dx with u = x² + k: [u^(n+1) / 2(n+1)] between the new limits
        k, n, q = rng.randint(1, 5), rng.randint(1, 4), rng.randint(1, 3)
        ua, ub = k, q * q + k
        definite = Fraction(ub ** (n + 1) - ua ** (n + 1), 2 * (n + 1))
        args = {"expression": f"x (x^2 + {k})^{n}", "substitution": f"u = x^2 + {k}", "lower": 0, "upper": q}
        cases.append(
            _case(
                f"substitution_{i:03d}",
                args,
                {
                    "status": "ok",
                    "definite": {"text": _text(definite)},
                    "limits_in_u": [{"text": str(ua)}, {"text": str(ub)}],
                },
            )
        )
    for i in range(30):  # ∫ x (x + k)^n dx by parts with u = x, from 0 to q, checked by expanding the product
        k, n, q = rng.randint(-3, 3), rng.randint(1, 3), rng.randint(1, 3)
        coefficients = [0] * (n + 2)  # x (x + k)^n expanded, lowest power first
        for j in range(n + 1):
            coefficients[j + 1] += comb(n, j) * k ** (n - j)
        definite = sum((Fraction(c, p + 1) * q ** (p + 1) for p, c in enumerate(coefficients)), Fraction(0))
        args = {"expression": f"x (x + {k})^{n}".replace("+ -", "- "), "parts_u": "x", "lower": 0, "upper": q}
        cases.append(_case(f"parts_{i:03d}", args, {"status": "ok", "definite": {"text": _text(definite)}}))
    return _errors_last(cases)


# --- math_solve_ode ---------------------------------------------------------------------------------------------------


def ode_cases(rng: random.Random) -> list[Case]:
    mpmath.mp.dps = 50
    cases = [
        _case("ode_growth_doc", {"rhs": "x y", "condition": [0, 2], "at": 1},
              {"status": "ok", "particular": {"text": "2*exp(x**2/2)"}, "at": {"y": {"decimal": "3.29744"}}}, "hand"),
        _case("ode_decay_ln2", {"rhs": "-2 P", "independent": "t", "dependent": "P", "condition": [0, 100],
                                "at": "ln(2)"},
              {"status": "ok", "particular": {"text": "100*exp(-2*t)"}, "at": {"y": {"text": "25"}}}, "hand"),
        _case("ode_negative_branch", {"rhs": "x/y", "condition": [0, -3]},
              {"status": "ok", "particular": {"text": "-sqrt(x**2 + 9)"}}, "hand"),
        _case("ode_constant_solution", {"rhs": "y - 3", "condition": [0, 3]},
              {"status": "ok", "particular": {"text": "3"}}, "hand"),
        _case("ode_student_general", {"rhs": "x y", "student": "y = A e^(x^2/2)"},
              {"status": "ok", "student": {"value": "correct", "satisfies_equation": True}}, "hand"),
        _case("ode_student_misses_condition", {"rhs": "x y", "student": "2 e^(x^2/2)", "condition": [0, 3]},
              {"status": "ok", "student": {"value": "incorrect", "satisfies_condition": False}}, "hand"),
        _case("ode_not_separable", {"rhs": "x + y"}, {"status": "unknown", "reason": "not_separable"}, "hand"),
        _case("ode_same_variables", {"rhs": "x", "independent": "x", "dependent": "x"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(40):  # dy/dx = a x^m y: y = y0 exp(a (x^(m+1) - x0^(m+1)) / (m + 1))
        a, m = rng.choice([-3, -2, -1, 1, 2, 3]), rng.randint(0, 2)
        x0, y0, x1 = rng.randint(-1, 1), rng.choice([-5, -2, -1, 1, 2, 3, 10]), rng.choice([-1, 1, 2])
        y1 = y0 * mpmath.exp(mpmath.mpf(a) * (mpmath.mpf(x1) ** (m + 1) - mpmath.mpf(x0) ** (m + 1)) / (m + 1))
        rhs = f"{a} x^{m} y" if m else f"{a} y"
        cases.append(
            _case(
                f"ode_exponential_{i:03d}",
                {"rhs": rhs, "condition": [x0, y0], "at": x1},
                {"status": "ok", "at": {"y": {"decimal": _sf(y1)}}},
            )
        )
    for i in range(30):  # dy/dx = n y / x through (x0, y0), x0 > 0: y = y0 (x / x0)^n
        n, x0, y0, x1 = rng.randint(1, 3), rng.randint(1, 3), rng.choice([-4, -1, 1, 2, 5]), rng.randint(1, 5)
        y1 = Fraction(y0) * Fraction(x1, x0) ** n
        cases.append(
            _case(
                f"ode_power_{i:03d}",
                {"rhs": f"{n} y / x", "condition": [x0, y0], "at": x1},
                {"status": "ok", "at": {"y": {"text": _text(y1)}}},
            )
        )
    for i in range(30):  # dy/dx = x / y through (x0, y0): y² = x² + (y0² - x0²), on y0's branch
        x0, y0, x1 = rng.randint(-3, 3), rng.choice([-4, -3, -2, 2, 3, 4]), rng.randint(-3, 3)
        square = x1 * x1 + y0 * y0 - x0 * x0
        if square <= 0:
            x1, square = x0, y0 * y0
        y1 = mpmath.sqrt(square) * (1 if y0 > 0 else -1)
        cases.append(
            _case(
                f"ode_hyperbola_{i:03d}",
                {"rhs": "x / y", "condition": [x0, y0], "at": x1},
                {"status": "ok", "at": {"y": {"decimal": _sf(y1)}}},
            )
        )
    return _errors_last(cases)


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The VER-30 calculus sets by name (stage S3)."""
    return {
        "math_differentiate.a_level": differentiation_cases(rng),
        "math_integrate.a_level": integration_cases(rng),
        "math_solve_ode": ode_cases(rng),
    }
