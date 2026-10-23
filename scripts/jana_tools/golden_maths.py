"""Golden sets for the M12.a mathematics checkers (VER-08, VER-09, VER-10, VER-13, VER-14, VER-15; VER-29), built by
construction like the S1 sets in `golden.py`.

Expected answers never come from the checkers under test: derivatives and integrals from the power rule on chosen
coefficients, statistics from Python fractions on chosen data, graph features from chosen roots and asymptotes,
triangles from Pythagorean ratios (the ambiguous case from a chosen sine), and answer verdicts from the rule each
case was built to exercise. Every case is synthetic; each set says `review: pending` until two subject teachers have
authored and reviewed it."""

from __future__ import annotations

import itertools
import random
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction
from typing import Any

import sympy as sp

x = sp.Symbol("x", real=True)
Case = dict[str, Any]


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> Case:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _text(value: Fraction | int | sp.Expr) -> str:
    if isinstance(value, Fraction):
        return sp.sstr(sp.Rational(value.numerator, value.denominator))
    return sp.sstr(sp.Integer(value) if isinstance(value, int) else value)


def _plain(expr: sp.Basic) -> str:
    return sp.sstr(expr).replace("**", "^")


def _dec(value: sp.Expr | Fraction | int, sf: int = 6) -> str:
    """A decimal to `sf` significant figures, half away from zero (the worker's display rule, computed here)."""
    if isinstance(value, Fraction):
        value = sp.Rational(value.numerator, value.denominator)
    d = Decimal(str(sp.N(value, 40)))
    if d == 0:
        return "0"
    rounded = d.quantize(Decimal(1).scaleb(d.adjusted() - sf + 1), rounding=ROUND_HALF_UP)
    return format(rounded, "f")


def _signed(n: int | Fraction) -> str:
    return f"+ {n}" if n >= 0 else f"- {-n}"


# --- math_differentiate (VER-08) -------------------------------------------------------------------------------------


def differentiate_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case(
            "diff_doc_cubic_stationary",
            {"expression": "x^3 - 3x", "stationary_points": True},
            {
                "derivative": {"text": "3*x**2 - 3"},
                "stationary_points": [
                    {"x": {"text": "-1"}, "y": {"text": "2"}, "nature": "maximum"},
                    {"x": {"text": "1"}, "y": {"text": "-2"}, "nature": "minimum"},
                ],
            },
            "hand",
        ),
        _case(
            "diff_doc_inflection",
            {"expression": "x^3", "stationary_points": True},
            {"stationary_points": [{"x": {"text": "0"}, "nature": "inflection"}]},
            "hand",
        ),
        _case(
            "diff_doc_tangent_normal",
            {"expression": "y = x^3 - 3x", "at": 2},
            {
                "at": {
                    "gradient": {"text": "9"},
                    "tangent": {"text": "y = 9*x - 16"},
                    "normal": {"gradient": {"text": "-1/9"}, "intercept": {"text": "20/9"}},
                }
            },
            "hand",
        ),
        _case(
            "diff_doc_rational_power",
            {"expression": "sqrt(x) + 4/x^2"},
            {"derivative": {"text": "-8/x**3 + 1/(2*sqrt(x))"}},
            "hand",
        ),
        _case(
            "diff_doc_student_right",
            {"expression": "x^4", "student": "4x^3"},
            {"student": {"value": "correct"}},
            "hand",
        ),
        _case(
            "diff_doc_student_wrong",
            {"expression": "x^4", "student": "4x^4"},
            {"student": {"value": "incorrect"}},
            "hand",
        ),
        _case(
            "diff_doc_second_order",
            {"expression": "x^4 - 2x^2", "order": 2},
            {"derivative": {"text": "12*x**2 - 4"}},
            "hand",
        ),
        _case(
            "diff_doc_horizontal_tangent",
            {"expression": "x^2 + 1", "at": 0},
            {"at": {"tangent": {"text": "y = 1"}, "normal": {"vertical": True, "text": "x = 0"}}},
            "hand",
        ),
        _case("diff_doc_undefined_point", {"expression": "1/x", "at": 0}, {"error": 4}, "hand"),
    ]
    for i in range(40):  # polynomials: the power rule on chosen coefficients
        coefficients = [rng.randint(-9, 9) for _ in range(5)]
        poly = sum(c * x**k for k, c in enumerate(coefficients))
        derivative = sum(k * c * x ** (k - 1) for k, c in enumerate(coefficients) if k)
        cases.append(
            _case(
                f"diff_poly_{i:03d}",
                {"expression": _plain(poly)},
                {"derivative": {"text": sp.sstr(sp.expand(derivative))}},
            )
        )
    for i in range(20):  # x^n with rational n: d/dx a x^(p/q) = a p/q x^(p/q - 1)
        a, p, q = rng.randint(1, 6), rng.choice([1, 3, 5, -1, -3]), rng.choice([2, 3])
        n = sp.Rational(p, q)
        cases.append(
            _case(
                f"diff_rational_power_{i:03d}",
                {"expression": f"{a}x^({p}/{q})"},
                {"derivative": {"text": sp.sstr(a * n * x ** (n - 1))}},
            )
        )
    for i in range(25):  # quadratics k(x - h)^2 + m: one stationary point (h, m), a minimum when k > 0
        k, h, m = rng.choice([-3, -2, -1, 1, 2, 3]), rng.randint(-6, 6), rng.randint(-9, 9)
        poly = sp.expand(k * (x - h) ** 2 + m)
        cases.append(
            _case(
                f"diff_turning_{i:03d}",
                {"expression": _plain(poly), "stationary_points": True},
                {
                    "stationary_points": [
                        {"x": {"text": str(h)}, "y": {"text": str(m)}, "nature": "minimum" if k > 0 else "maximum"}
                    ]
                },
            )
        )
    for i in range(20):  # tangents to a x^2 + b x + c at x0: gradient 2 a x0 + b, intercept y0 - m x0
        a, b, c, x0 = rng.randint(-4, 4) or 1, rng.randint(-6, 6), rng.randint(-9, 9), rng.randint(-4, 4)
        y0, m = a * x0 * x0 + b * x0 + c, 2 * a * x0 + b
        cases.append(
            _case(
                f"diff_tangent_{i:03d}",
                {"expression": _plain(a * x**2 + b * x + c), "at": x0},
                {
                    "at": {
                        "y": {"text": str(y0)},
                        "gradient": {"text": str(m)},
                        "tangent": {"intercept": {"text": str(y0 - m * x0)}},
                    }
                },
            )
        )
    return cases  # fmt: skip


# --- math_integrate (VER-08) -----------------------------------------------------------------------------------------


def _antiderivative(coefficients: list[int]) -> sp.Expr:
    return sum(sp.Rational(c, k + 1) * x ** (k + 1) for k, c in enumerate(coefficients))


def _evaluate(coefficients: list[int], at: Fraction) -> Fraction:
    return sum((Fraction(c, k + 1) * at ** (k + 1) for k, c in enumerate(coefficients)), Fraction(0))


def integrate_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case(
            "int_doc_missing_constant",
            {"expression": "x^2", "student": "x^3/3"},
            {"antiderivative": {"text": "x**3/3"}, "student": {"value": "correct", "form": "missing_constant"}},
            "hand",
        ),
        _case(
            "int_doc_with_constant",
            {"expression": "x^2", "student": "x^3/3 + c"},
            {"student": {"value": "correct", "form": "ok", "constant": "c"}},
            "hand",
        ),
        _case(
            "int_doc_wrong_value",
            {"expression": "x^2", "student": "x^3/2 + c"},
            {"student": {"value": "incorrect"}},
            "hand",
        ),
        _case(
            "int_doc_area_split",
            {"expression": "x^2 - 4", "lower": -3, "upper": 3, "area": True},
            {
                "definite": {"text": "-6"},
                "area": {
                    "total": {"text": "46/3"},
                    "pieces": [
                        {"signed": {"text": "7/3"}, "side": "above"},
                        {"signed": {"text": "-32/3"}, "side": "below"},
                        {"signed": {"text": "7/3"}, "side": "above"},
                    ],
                },
            },
            "hand",
        ),
        _case(
            "int_doc_rational_power", {"expression": "sqrt(x)"}, {"antiderivative": {"text": "2*x**(3/2)/3"}}, "hand"
        ),
        _case("int_doc_across_asymptote", {"expression": "1/x^2", "lower": -1, "upper": 1}, {"error": 4}, "hand"),
        _case(
            "int_doc_definite_student",
            {"expression": "3x^2", "lower": 0, "upper": 2, "student": "8"},
            {"definite": {"text": "8"}, "student": {"value": "correct"}},
            "hand",
        ),
    ]
    for i in range(35):
        coefficients = [rng.randint(-9, 9) for _ in range(4)]
        poly = sum(c * x**k for k, c in enumerate(coefficients))
        cases.append(
            _case(
                f"int_poly_{i:03d}",
                {"expression": _plain(poly)},
                {"antiderivative": {"text": sp.sstr(_antiderivative(coefficients))}},
            )
        )
    for i in range(30):
        coefficients = [rng.randint(-6, 6) for _ in range(3)]
        lower = rng.randint(-4, 2)
        upper = lower + rng.randint(1, 5)
        value = _evaluate(coefficients, Fraction(upper)) - _evaluate(coefficients, Fraction(lower))
        poly = sum(c * x**k for k, c in enumerate(coefficients))
        cases.append(
            _case(
                f"int_definite_{i:03d}",
                {"expression": _plain(poly), "lower": lower, "upper": upper},
                {"definite": {"text": _text(value)}},
            )
        )
    for i in range(20):  # area between (x - r)(x - s) and the x-axis over [r - 1, s + 1]: three pieces
        r = rng.randint(-5, 2)
        s = r + rng.randint(1, 4)
        coefficients = [r * s, -(r + s), 1]
        cuts = [Fraction(r - 1), Fraction(r), Fraction(s), Fraction(s + 1)]
        pieces = [_evaluate(coefficients, b) - _evaluate(coefficients, a) for a, b in itertools.pairwise(cuts)]
        cases.append(
            _case(
                f"int_area_{i:03d}",
                {"expression": f"(x {_signed(-r)})(x {_signed(-s)})", "lower": r - 1, "upper": s + 1, "area": True},
                {
                    "area": {
                        "total": {"text": _text(sum(abs(p) for p in pieces))},
                        "pieces": [{"signed": {"text": _text(p)}} for p in pieces],
                    }
                },
            )
        )
    for i in range(20):  # a student's answer with and without the arbitrary constant, and a wrong coefficient
        coefficients = [rng.randint(1, 6) for _ in range(3)]
        poly = sum(c * x**k for k, c in enumerate(coefficients))
        right = _plain(_antiderivative(coefficients))
        kind = i % 3
        student = [f"{right} + C", right, f"{right} + {coefficients[0]}x + C"][kind]
        expect = [
            {"value": "correct", "form": "ok"},
            {"value": "correct", "form": "missing_constant"},
            {"value": "incorrect"},
        ][kind]
        cases.append(
            _case(f"int_student_{i:03d}", {"expression": _plain(poly), "student": student}, {"student": expect})
        )
    return cases  # fmt: skip


# --- math_check_answer (VER-09, VER-10) -------------------------------------------------------------------------------


def _round_sf(value: Fraction, sf: int) -> Decimal:
    d = Decimal(value.numerator) / Decimal(value.denominator)
    return d.quantize(Decimal(1).scaleb(d.adjusted() - sf + 1), rounding=ROUND_HALF_UP)


def answer_cases(rng: random.Random) -> list[Case]:
    def verdict(value: str, overall: str, **components: Any) -> dict[str, Any]:
        return {"verdict": overall, "components": {"value": value, **components}}

    cases = [
        _case(
            "ans_doc_convertible",
            {"student": "2 km", "key": "2000 m"},
            verdict("correct", "correct", unit="convertible"),
            "hand",
        ),
        _case(
            "ans_doc_wrong_dimension",
            {"student": "2000 s", "key": "2000 m"},
            {"verdict": "incorrect", "components": {"unit": "wrong_dimension"}},
            "hand",
        ),
        _case(
            "ans_doc_unit_fixed",
            {"student": "2 km", "key": "2000 m", "rule": {"unit_policy": "exact"}},
            verdict("correct", "incorrect", unit="convertible"),
            "hand",
        ),
        _case(
            "ans_doc_unit_missing",
            {"student": "2000", "key": "2000 m"},
            verdict("correct", "partial", unit="missing"),
            "hand",
        ),
        _case(
            "ans_doc_form_expanded",
            {"student": "2(x+3)", "key": "2x+6", "rule": {"form": "expanded"}},
            verdict("correct", "partial", form="not_expanded"),
            "hand",
        ),
        _case(
            "ans_doc_form_factorised",
            {"student": "2(x+2)(x+1)", "key": "2x^2+6x+4", "rule": {"form": "factorised"}},
            verdict("correct", "correct", form="ok"),
            "hand",
        ),
        _case(
            "ans_doc_not_fully_factorised",
            {"student": "(2x+4)(x+1)", "key": "2x^2+6x+4", "rule": {"form": "factorised"}},
            verdict("correct", "partial", form="not_factorised"),
            "hand",
        ),
        _case(
            "ans_doc_too_many",
            {"student": "9.806", "key": "9.81"},
            verdict("correct", "correct", precision={"sf": "too_many"}),
            "hand",
        ),
        _case("ans_doc_two_sf", {"student": "9.8", "key": "9.81"}, verdict("correct", "correct"), "hand"),
        _case(
            "ans_doc_too_few",
            {"student": "10", "key": "9.81"},
            verdict("correct", "incorrect", precision={"sf": "too_few"}),
            "hand",
        ),
        _case(
            "ans_doc_carried_drift",
            {"student": "9.75", "key": "9.81", "rule": {"carried": True}},
            verdict("within_tolerance", "correct"),
            "hand",
        ),
        _case(
            "ans_doc_money_places",
            {"student": "12.5", "key": "12.50", "rule": {"quantity": "money", "dp": 2}},
            verdict("correct", "incorrect", precision={"dp": "wrong"}),
            "hand",
        ),
        _case(
            "ans_doc_money_separator",
            {"student": "1,250.00", "key": "1250", "rule": {"quantity": "money"}},
            verdict("correct", "correct", precision={"dp": "ok"}),
            "hand",
        ),
        _case(
            "ans_doc_angle_tolerance",
            {"student": "36.8", "key": "36.87", "rule": {"quantity": "angle"}},
            verdict("within_tolerance", "correct"),
            "hand",
        ),
        _case(
            "ans_doc_probability_fraction",
            {"student": "1/3", "key": "1/3", "rule": {"quantity": "probability"}},
            verdict("correct", "correct"),
            "hand",
        ),
        _case(
            "ans_doc_probability_3sf",
            {"student": "0.333", "key": "1/3", "rule": {"quantity": "probability"}},
            verdict("correct", "correct"),
            "hand",
        ),
        _case(
            "ans_doc_probability_2sf",
            {"student": "0.33", "key": "1/3", "rule": {"quantity": "probability"}},
            verdict("correct", "incorrect", precision={"sf": "too_few"}),
            "hand",
        ),
        _case(
            "ans_doc_exact_asked",
            {"student": "1.414", "key": "sqrt(2)", "rule": {"quantity": "exact"}},
            verdict("within_tolerance", "partial", form="not_exact"),
            "hand",
        ),
        _case(
            "ans_doc_unsimplified",
            {"student": "2/4", "key": "1/2", "rule": {"form": "simplest"}},
            verdict("correct", "partial", form="unsimplified"),
            "hand",
        ),
        _case(
            "ans_doc_single_fraction",
            {"student": "x/2 + 1/3", "key": "(3x+2)/6", "rule": {"form": "single_fraction"}},
            verdict("correct", "partial", form="not_single_fraction"),
            "hand",
        ),
        _case(
            "ans_doc_surd",
            {"student": "sqrt(12)", "key": "2sqrt(3)", "rule": {"form": "surd_simplest"}},
            verdict("correct", "partial", form="not_surd_simplest"),
            "hand",
        ),
        _case(
            "ans_doc_rationalise",
            {"student": "1/sqrt(2)", "key": "sqrt(2)/2", "rule": {"form": "surd_simplest"}},
            verdict("correct", "partial", form="not_surd_simplest"),
            "hand",
        ),
        _case(
            "ans_doc_standard_form",
            {"student": "3.2 \u00d7 10^4", "key": "32000", "rule": {"form": "standard_form"}},
            verdict("correct", "correct", form="ok"),
            "hand",
        ),
        _case(
            "ans_doc_not_standard_form",
            {"student": "32000", "key": "32000", "rule": {"form": "standard_form"}},
            verdict("correct", "partial", form="not_standard_form"),
            "hand",
        ),
        _case(
            "ans_doc_mixed_number",
            {"student": "2 1/2", "key": "5/2", "rule": {"form": "mixed_number"}},
            verdict("correct", "correct", form="ok"),
            "hand",
        ),
        _case(
            "ans_doc_bearing",
            {"student": "045", "key": "45", "rule": {"form": "bearing"}},
            verdict("correct", "correct", form="ok"),
            "hand",
        ),
        _case(
            "ans_doc_bearing_two_figures",
            {"student": "45", "key": "45", "rule": {"form": "bearing"}},
            verdict("correct", "partial", form="not_bearing"),
            "hand",
        ),
        _case(
            "ans_doc_wrong_value", {"student": "x^2 + 1", "key": "(x+1)^2"}, verdict("incorrect", "incorrect"), "hand"
        ),
        _case(
            "ans_doc_form_ignored",
            {"student": "2(x+3)", "key": "2x+6", "rule": {"form": "expanded", "on_form_unmet": "ignore"}},
            verdict("correct", "correct", form="not_expanded"),
            "hand",
        ),
    ]
    for i in range(30):  # measurements: a key to 3 s.f.; answers to 2, 3 and 4 s.f., to 1 s.f., and a wrong value
        cents = rng.choice([n for n in range(101, 1000) if n % 100])
        key = Fraction(cents, 100)
        key_text = format(Decimal(cents) / 100, "f")
        kind = i % 5
        if kind == 0:
            text, expect = format(_round_sf(key, 2), "f"), verdict("correct", "correct", precision={"sf": "ok"})
        elif kind == 1:
            text, expect = key_text, verdict("correct", "correct", precision={"sf": "ok"})
        elif kind == 2:
            text = f"{key_text}{rng.randint(1, 4)}"  # a fourth figure that rounds back to the key
            expect = verdict("correct", "correct", precision={"sf": "too_many"})
        elif kind == 3:
            text, expect = format(_round_sf(key, 1), "f"), verdict("correct", "incorrect", precision={"sf": "too_few"})
        else:
            text, expect = format(Decimal(cents + 7) / 100, "f"), verdict("incorrect", "incorrect")
        cases.append(_case(f"ans_measure_{i:03d}", {"student": text, "key": key_text}, expect))
    for i in range(20):  # units: the same length in km, cm or mm against a key in m; a time is the wrong dimension
        metres = Fraction(rng.randint(2, 99) * 10)
        unit, factor = rng.choice([("km", Fraction(1, 1000)), ("cm", Fraction(100)), ("mm", Fraction(1000))])
        given = metres * factor
        magnitude = format(Decimal(given.numerator) / Decimal(given.denominator), "f")
        if i % 4 == 3:
            cases.append(
                _case(
                    f"ans_units_{i:03d}",
                    {"student": f"{magnitude} s", "key": f"{metres} m"},
                    {"verdict": "incorrect", "components": {"unit": "wrong_dimension"}},
                )
            )
        else:
            cases.append(
                _case(
                    f"ans_units_{i:03d}",
                    {"student": f"{magnitude} {unit}", "key": f"{metres} m", "rule": {"sf": 4}},
                    verdict("correct", "correct", unit="convertible"),
                )
            )
    for i in range(25):  # factorised and expanded forms of (x - r)(x - s)
        r, s = rng.randint(-7, 7), rng.randint(-7, 7)
        factored = f"(x {_signed(-r)})(x {_signed(-s)})"
        expanded = _plain(sp.expand((x - r) * (x - s)))
        if i % 2:
            args = {"student": factored, "key": expanded, "rule": {"form": "expanded"}}
            expect = verdict("correct", "partial", form="not_expanded")
        else:
            args = {"student": expanded, "key": factored, "rule": {"form": "expanded"}}
            expect = verdict("correct", "correct", form="ok")
        cases.append(_case(f"ans_form_{i:03d}", args, expect))
    for i in range(15):  # money to 2 d.p. and angles to 1 d.p. within 0.1°
        cents = rng.randint(100, 99999)
        key = Fraction(cents, 100)
        text = format(Decimal(cents) / 100, ".2f")
        cases.append(
            _case(
                f"ans_money_{i:03d}",
                {"student": text, "key": text, "rule": {"quantity": "money"}},
                verdict("correct", "correct"),
            )
        )
        tenths = rng.randint(10, 3590)
        angle = Fraction(tenths, 10)
        off = rng.choice([0, 1, -1, 3])
        student = format(Decimal(tenths + off) / 10, ".1f")
        exact_key = format(Decimal(angle.numerator) / Decimal(angle.denominator), ".1f")
        status = "correct" if off == 0 else "within_tolerance" if abs(off) <= 1 else "incorrect"
        cases.append(
            _case(
                f"ans_angle_{i:03d}",
                {"student": student, "key": exact_key, "rule": {"quantity": "angle"}},
                verdict(status, "incorrect" if status == "incorrect" else "correct"),
            )
        )
    return cases  # fmt: skip


# --- stats_compute (VER-13) ------------------------------------------------------------------------------------------


def _median(values: list[Fraction]) -> Fraction:
    n = len(values)
    return values[n // 2] if n % 2 else (values[n // 2 - 1] + values[n // 2]) / 2


def _quartiles(values: list[Fraction], method: str) -> tuple[Fraction, Fraction]:
    """Independent implementation by slicing the sorted list."""
    n = len(values)
    if method == "interpolated":

        def at(position: Fraction) -> Fraction:
            position = min(max(position, Fraction(1)), Fraction(n))
            low = int(position)
            share = position - low
            return values[low - 1] + (share * (values[low] - values[low - 1]) if share else 0)

        return at(Fraction(n + 1, 4)), at(Fraction(3 * (n + 1), 4))
    half = n // 2
    if n % 2 and method == "inclusive":
        return _median(values[: half + 1]), _median(values[half:])
    return _median(values[:half]), _median(values[n - half :])


def stats_cases(rng: random.Random) -> list[Case]:
    classes = [
        {"lower": 0, "upper": 10, "frequency": 5},
        {"lower": 10, "upper": 20, "frequency": 8},
        {"lower": 20, "upper": 30, "frequency": 7},
    ]
    cases = [
        _case(
            "stats_doc_grouped_mean",
            {"grouped": classes},
            {"mean": {"text": "16"}, "median": {"text": "65/4"}, "modal_class": [{"lower": {"text": "10"}}]},
            "hand",
        ),
        _case(
            "stats_doc_grouped_mean_fraction",
            {
                "grouped": [
                    {"lower": 0, "upper": 5, "frequency": 3},
                    {"lower": 5, "upper": 10, "frequency": 4},
                    {"lower": 10, "upper": 20, "frequency": 5},
                ]
            },
            {"mean": {"text": "75/8"}, "modal_class": [{"lower": {"text": "5"}}], "modal_by": "frequency_density"},
            "hand",
        ),
        _case(
            "stats_doc_list",
            {"data": [3, 7, 8, 5, 12, 14, 21, 13, 18], "quartile_method": "exclusive"},
            {
                "mean": {"text": "101/9"},
                "median": {"text": "12"},
                "quartiles": {"q1": {"text": "6"}, "q3": {"text": "16"}},
                "variance": {"text": "2588/81"},
                "standard_deviation": {"text": "2*sqrt(647)/9"},
            },
            "hand",
        ),
        _case(
            "stats_doc_events",
            {"events": {"p_a": "1/2", "p_b": "1/3", "relation": "independent"}},
            {"p_a_and_b": {"text": "1/6"}, "p_a_or_b": {"text": "2/3"}, "p_a_given_b": {"text": "1/2"}},
            "hand",
        ),
        _case(
            "stats_doc_conditional",
            {"events": {"p_a": "0.6", "p_b": "0.5", "p_a_and_b": "0.2"}},
            {"p_a_given_b": {"text": "2/5"}, "p_b_given_a": {"text": "1/3"}, "independent": False},
            "hand",
        ),
        _case("stats_doc_tree", {"sequence": ["3/5", "2/4"]}, {"product": {"text": "3/10"}}, "hand"),
        _case(
            "stats_doc_impossible", {"events": {"p_a": "0.3", "p_b": "0.4", "p_a_and_b": "0.5"}}, {"error": 4}, "hand"
        ),
    ]
    methods = ("exclusive", "inclusive", "interpolated")
    for i in range(45):  # lists: mean, median, range and quartiles by each method
        values = sorted(Fraction(rng.randint(0, 60)) for _ in range(rng.randint(5, 30)))
        method = methods[i % 3]
        q1, q3 = _quartiles(values, method)
        mean = sum(values, Fraction(0)) / len(values)
        variance = sum(((v - mean) ** 2 for v in values), Fraction(0)) / len(values)
        data = [int(v) for v in values]
        rng.shuffle(data)
        cases.append(
            _case(
                f"stats_list_{i:03d}",
                {"data": data, "quartile_method": method},
                {
                    "n": len(values),
                    "mean": {"text": _text(mean)},
                    "median": {"text": _text(_median(values))},
                    "range": {"text": _text(values[-1] - values[0])},
                    "quartiles": {"q1": {"text": _text(q1)}, "q3": {"text": _text(q3)}, "method": method},
                    "variance": {"text": _text(variance)},
                },
            )
        )
    for i in range(30):  # grouped data with equal widths: the mean from midpoints, exactly
        width, start = rng.choice([5, 10, 20]), rng.choice([0, 10, 20, 100])
        frequencies = [rng.randint(0, 15) for _ in range(rng.randint(3, 7))]
        frequencies[rng.randrange(len(frequencies))] += 1
        rows = [
            {"lower": start + k * width, "upper": start + (k + 1) * width, "frequency": f}
            for k, f in enumerate(frequencies)
        ]
        n = sum(frequencies)
        mean = sum((Fraction(r["lower"] + r["upper"], 2) * r["frequency"] for r in rows), Fraction(0)) / n
        top = max(frequencies)
        modal = [{"lower": {"text": str(r["lower"])}} for r in rows if r["frequency"] == top]
        cases.append(
            _case(
                f"stats_grouped_{i:03d}",
                {"grouped": rows},
                {"n": n, "mean": {"text": _text(mean)}, "modal_class": modal},
            )
        )
    for i in range(25):  # two events: union, intersection and conditionals as fractions
        p_a, p_b = Fraction(rng.randint(1, 9), 10), Fraction(rng.randint(1, 11), 12)
        independent = i % 2 == 0
        low, high = max(Fraction(0), p_a + p_b - 1), min(p_a, p_b)
        both = p_a * p_b if independent else low + (high - low) * Fraction(rng.randint(0, 4), 4)
        events: dict[str, Any] = {"p_a": _text(p_a), "p_b": _text(p_b)}
        if independent:
            events["relation"] = "independent"
        else:
            events["p_a_and_b"] = _text(both)
        cases.append(
            _case(
                f"stats_events_{i:03d}",
                {"events": events},
                {
                    "p_a_and_b": {"text": _text(both)},
                    "p_a_or_b": {"text": _text(p_a + p_b - both)},
                    "p_a_given_b": {"text": _text(both / p_b)},
                },
            )
        )
    return cases  # fmt: skip


# --- math_plot_points (VER-14) -------------------------------------------------------------------------------------


def plot_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case(
            "plot_doc_asymptote_split",
            {"curves": [{"id": "f", "expr": "1/(x-2)"}], "x_range": [-5, 5]},
            {"curves": [{"id": "f", "asymptotes": [{"x": {"text": "2"}}], "roots": []}]},
            "hand",
        ),
        _case(
            "plot_doc_hole",
            {"curves": [{"id": "f", "expr": "(x^2-1)/(x-1)"}], "x_range": [-5, 5]},
            {
                "curves": [
                    {"id": "f", "asymptotes": [], "holes": [{"x": {"text": "1"}}], "roots": [{"x": {"text": "-1"}}]}
                ]
            },
            "hand",
        ),
        _case(
            "plot_doc_intersections",
            {"curves": [{"id": "f", "expr": "x^2 - 4"}, {"id": "g", "expr": "x + 2"}], "x_range": [-5, 5]},
            {"intersections": [{"x": {"text": "-2"}, "y": {"text": "0"}}, {"x": {"text": "3"}, "y": {"text": "5"}}]},
            "hand",
        ),
        _case(
            "plot_doc_tan_degrees",
            {
                "curves": [{"id": "f", "expr": "tan(x)"}],
                "x_range": [0, 360],
                "angle_unit": "degrees",
                "marks": ["asymptotes", "roots"],
            },
            {
                "curves": [
                    {
                        "id": "f",
                        "asymptotes": [{"x": {"text": "90"}}, {"x": {"text": "270"}}],
                        "roots": [{"x": {"text": "0"}}, {"x": {"text": "180"}}, {"x": {"text": "360"}}],
                    }
                ]
            },
            "hand",
        ),
        _case(
            "plot_doc_sqrt_domain",
            {"curves": [{"id": "f", "expr": "sqrt(x-1)"}], "x_range": [-5, 5]},
            {"curves": [{"id": "f", "roots": [{"x": {"text": "1"}}], "asymptotes": []}]},
            "hand",
        ),
    ]
    for i in range(45):  # parabolas k(x - r)(x - s): roots r and s, a turning point midway, y-intercept k r s
        r, s = sorted(rng.sample(range(-6, 7), 2))
        k = rng.choice([-2, -1, 1, 2])
        h = Fraction(r + s, 2)
        turning_y = k * (h - r) * (h - s)
        expr = _plain(sp.expand(k * (x - r) * (x - s)))
        cases.append(
            _case(
                f"plot_parabola_{i:03d}",
                {"curves": [{"id": "f", "expr": expr}], "x_range": [-8, 8], "max_points": 60},
                {
                    "curves": [
                        {
                            "id": "f",
                            "roots": [{"x": {"text": str(r)}}, {"x": {"text": str(s)}}],
                            "turning_points": [
                                {
                                    "x": {"text": _text(h)},
                                    "y": {"text": _text(turning_y)},
                                    "nature": "minimum" if k > 0 else "maximum",
                                }
                            ],
                            "y_intercept": {"y": {"text": str(k * r * s)}},
                            "asymptotes": [],
                        }
                    ]
                },
            )
        )
    for i in range(35):  # a/(x - p) + q: one vertical asymptote at p, a root at p - a/q, never a root at p
        a, p, q = rng.choice([1, 2, 3, -1, -2]), rng.randint(-4, 4), rng.choice([1, 2, -1, -2])
        root = Fraction(p) - Fraction(a, q)
        roots = [{"x": {"text": _text(root)}}] if -8 <= root <= 8 else []
        cases.append(
            _case(
                f"plot_reciprocal_{i:03d}",
                {
                    "curves": [{"id": "f", "expr": f"{a}/(x {_signed(-p)}) {_signed(q)}"}],
                    "x_range": [-8, 8],
                    "max_points": 80,
                    "marks": ["asymptotes", "roots"],
                },
                {"curves": [{"id": "f", "asymptotes": [{"x": {"text": str(p)}}], "roots": roots}]},
            )
        )
    for i in range(20):  # a line meeting a parabola at two chosen points
        u, v = sorted(rng.sample(range(-5, 6), 2))
        m, c = rng.randint(-3, 3), rng.randint(-5, 5)
        parabola = _plain(sp.expand((x - u) * (x - v) + m * x + c))
        line = _plain(m * x + c) if m or c else "0"
        expect = [{"curves": ["f", "g"], "x": {"text": str(t)}, "y": {"text": str(m * t + c)}} for t in (u, v)]
        cases.append(
            _case(
                f"plot_intersection_{i:03d}",
                {
                    "curves": [{"id": "f", "expr": parabola}, {"id": "g", "expr": line}],
                    "x_range": [-6, 6],
                    "max_points": 40,
                    "marks": ["intersections"],
                },
                {"intersections": expect},
            )
        )
    return cases  # fmt: skip


# --- geom_figure (VER-15) -------------------------------------------------------------------------------------------

SINES = [(3, 5), (4, 5), (5, 13), (12, 13), (8, 17), (15, 17), (7, 25), (24, 25)]


def geometry_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case(
            "geom_doc_ambiguous_case",
            {"template": "triangle", "givens": {"A": 30, "a": 5, "b": 8}},
            {
                "ambiguous": True,
                "solutions": [
                    {"sides": {"c": {"decimal": _dec(3 + 4 * sp.sqrt(3))}}, "angles": {"B": {"decimal": "53.1301"}}},
                    {"sides": {"c": {"decimal": _dec(4 * sp.sqrt(3) - 3)}}, "angles": {"B": {"decimal": "126.870"}}},
                ],
            },
            "hand",
        ),
        _case(
            "geom_doc_no_triangle", {"template": "triangle", "givens": {"A": 30, "a": 3, "b": 8}}, {"error": 4}, "hand"
        ),
        _case(
            "geom_doc_angles_over_180",
            {"template": "triangle", "givens": {"A": 100, "B": 90, "c": 10}},
            {"error": 4},
            "hand",
        ),
        _case(
            "geom_doc_pythagoras",
            {"template": "triangle", "givens": {"a": 3, "b": 4, "right_angle": "C"}},
            {
                "solutions": [
                    {
                        "sides": {"c": {"text": "5"}},
                        "angles": {"C": {"text": "90"}},
                        "area": {"text": "6"},
                        "methods": ["pythagoras"],
                    }
                ]
            },
            "hand",
        ),
        _case(
            "geom_doc_sector",
            {"template": "circle", "givens": {"r": 6, "angle": 60}},
            {"arc": {"text": "2*pi"}, "sector": {"text": "6*pi"}, "chord": {"text": "6"}},
            "hand",
        ),
        _case(
            "geom_doc_bearing",
            {"template": "bearing", "givens": {"from": [0, 0], "to": [3, 4]}},
            {
                "bearing": {"three_figure": "036.9"},
                "back_bearing": {"three_figure": "216.9"},
                "distance": {"text": "5"},
            },
            "hand",
        ),
        _case(
            "geom_doc_centre_angle",
            {"template": "circle_theorem", "givens": {"theorem": "angle_at_centre", "angle": 35}},
            {"derived": {"text": "70"}},
            "hand",
        ),
        _case(
            "geom_doc_cone",
            {"template": "mensuration", "givens": {"shape": "cone", "dims": {"radius": 3, "height": 4}}},
            {"volume": {"text": "12*pi"}, "slant_height": {"text": "5"}, "surface_area": {"text": "24*pi"}},
            "hand",
        ),
        _case(
            "geom_doc_similar",
            {
                "template": "similar",
                "givens": {"scale_from": {"kind": "area", "a": 4, "b": 9}, "convert": {"kind": "volume", "a": 16}},
            },
            {"length_factor": {"text": "3/2"}, "converted": {"b": {"text": "54"}}},
            "hand",
        ),
    ]
    for i in range(30):  # two sides and a non-included angle A = 30°, with sin B chosen: two triangles when B > 30°
        p, q = SINES[i % len(SINES)]
        sin_b = sp.Rational(p, q)
        b = 2 * p * rng.randint(1, 3)  # a = b / (2 sin B) is then a whole number
        a = sp.Rational(b * q, 2 * p)
        cos_b = sp.sqrt(1 - sin_b**2)
        cs = [a * (cos_b + sp.sqrt(3) * sin_b)] + (
            [a * (-cos_b + sp.sqrt(3) * sin_b)] if sin_b > sp.Rational(1, 2) else []
        )
        cases.append(
            _case(
                f"geom_ambiguous_{i:03d}",
                {"template": "triangle", "givens": {"A": 30, "a": str(a), "b": b}},
                {"ambiguous": len(cs) == 2, "solutions": [{"sides": {"c": {"decimal": _dec(c)}}} for c in cs]},
            )
        )
    for i in range(25):  # right-angled triangles from Pythagorean triples, by Pythagoras and by three sides
        p, q = SINES[i % len(SINES)]
        k = rng.randint(1, 4)
        a, hyp = p * k, q * k
        b = int(sp.sqrt(hyp**2 - a**2))
        givens = {"a": a, "b": b, "right_angle": "C"} if i % 2 else {"a": a, "b": b, "c": hyp}
        cases.append(
            _case(
                f"geom_right_{i:03d}",
                {"template": "triangle", "givens": givens},
                {
                    "solutions": [
                        {
                            "sides": {"c": {"text": str(hyp)}},
                            "angles": {"C": {"text": "90"}},
                            "area": {"text": _text(Fraction(a * b, 2))},
                        }
                    ]
                },
            )
        )
    for i in range(15):  # sectors: arc and area as exact multiples of pi
        r, theta = rng.randint(1, 12), rng.choice([30, 45, 60, 72, 90, 120, 135, 150, 180, 240])
        cases.append(
            _case(
                f"geom_sector_{i:03d}",
                {"template": "circle", "givens": {"r": r, "angle": theta}},
                {
                    "arc": {"text": sp.sstr(sp.Rational(theta, 360) * 2 * sp.pi * r)},
                    "sector": {"text": sp.sstr(sp.Rational(theta, 360) * sp.pi * r * r)},
                },
            )
        )
    for i in range(15):  # coordinates: gradient and midpoint
        x1, y1, x2, y2 = (rng.randint(-9, 9) for _ in range(4))
        if x1 == x2:
            x2 += 1
        cases.append(
            _case(
                f"geom_coordinates_{i:03d}",
                {"template": "coordinates", "givens": {"p1": [x1, y1], "p2": [x2, y2]}},
                {
                    "gradient": {"text": _text(Fraction(y2 - y1, x2 - x1))},
                    "midpoint": [{"text": _text(Fraction(x1 + x2, 2))}, {"text": _text(Fraction(y1 + y2, 2))}],
                    "distance": {"decimal": _dec(sp.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2))},
                },
            )
        )
    for i in range(15):  # transformations of a triangle by construction
        points = [[rng.randint(-5, 5), rng.randint(-5, 5)] for _ in range(3)]
        kind = ("reflection", "rotation", "enlargement", "translation", "reflection")[i % 5]
        if kind == "reflection" and i % 2:
            spec: dict[str, Any] = {"kind": "reflection", "line": "y = x"}
            image = [[py, px] for px, py in points]
        elif kind == "reflection":
            spec = {"kind": "reflection", "line": "y = 1"}
            image = [[px, 2 - py] for px, py in points]
        elif kind == "rotation":
            spec = {"kind": "rotation", "angle": 90, "centre": [0, 0], "direction": "clockwise"}
            image = [[py, -px] for px, py in points]
        elif kind == "enlargement":
            spec = {"kind": "enlargement", "scale": 2, "centre": [1, 1]}
            image = [[1 + 2 * (px - 1), 1 + 2 * (py - 1)] for px, py in points]
        else:
            spec = {"kind": "translation", "vector": [3, -2]}
            image = [[px + 3, py - 2] for px, py in points]
        cases.append(
            _case(
                f"geom_transform_{i:03d}",
                {"template": "transformation", "givens": {"points": points, "transformation": spec}},
                {"image": [[{"text": str(ix)}, {"text": str(iy)}] for ix, iy in image]},
            )
        )
    return cases  # fmt: skip


def _errors_last(cases: list[Case]) -> list[Case]:
    """Refusal cases after the others, so a sample of a set's first cases exercises results."""
    return [c for c in cases if "error" not in c["expect"]] + [c for c in cases if "error" in c["expect"]]


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The M12.a sets by tool name (stage S2)."""
    built = {
        "math_differentiate": differentiate_cases(rng),
        "math_integrate": integrate_cases(rng),
        "math_check_answer": answer_cases(rng),
        "stats_compute": stats_cases(rng),
        "math_plot_points": plot_cases(rng),
        "geom_figure": geometry_cases(rng),
    }
    return {name: _errors_last(cases) for name, cases in built.items()}
