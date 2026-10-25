"""Golden sets for the A level algebra of `math_simplify` (version 2) and `math_solve` (version 4) (VER-30; VER-29),
built by construction like the other sets in `golden.py` and with their own seed, so every other set is unchanged.

Expected answers never come from the checkers under test. Partial fractions come from constants chosen over chosen
factors, recombined into the question. Series coefficients are computed independently with Fraction arithmetic: the
generalised binomial coefficients of k(a + bx)^n, the known Maclaurin coefficients of e^kx, sin kx, cos kx and
ln(1 + kx), Cauchy products of those lists, and the sum of two geometric series for a fraction split as
A/(1 - ax) + B/(1 + bx). Complex numbers come from chosen Gaussian integers (products, quotients and powers by
integer arithmetic) and from chosen moduli and special angles; complex roots from chosen conjugate pairs and real
roots, expanded into the polynomial. Newton-Raphson and fixed-point iterates are computed with Fraction arithmetic
while the values stay small fractions and with Decimal at 70 digits after that (and for roots and exponentials),
from functions with chosen roots; sign-change checks evaluate polynomials with chosen roots exactly at the ends of
chosen intervals. SymPy is used only to write the questions and the exact forms of chosen values. Every case is
synthetic; each set says `review: pending` until two subject teachers have authored and reviewed it."""

from __future__ import annotations

import math
import random
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from typing import Any

import sympy as sp

from .golden_accounting import _case, _errors_last

Case = dict[str, Any]
Number = Fraction | Decimal
SEED = 20261030
x = sp.Symbol("x", real=True)
EXACT_LIMIT = 10**30  # the tool keeps an iterate exact while its numerator and denominator are at most this
DIVERGED = 10**12  # and stops an iteration whose iterate grows beyond this
ERROR = {"error": 4}  # DOMAIN_ERROR


def _plain(expr: sp.Basic) -> str:
    """A plain-maths rendering our grammar reads: ** as ^, explicit products."""
    return sp.sstr(expr).replace("**", "^")


def _q(value: Fraction) -> sp.Rational:
    return sp.Rational(value.numerator, value.denominator)


def _text(value: Fraction | int) -> dict[str, str]:
    return {"text": str(Fraction(value))}


def _small(value: Fraction) -> bool:
    return max(abs(value.numerator), value.denominator) <= EXACT_LIMIT


def _dp(value: Number, dp: int) -> str:
    """`dp` places, half away from zero; a negative value keeps its sign even when it rounds to 0 (as the tool)."""
    if isinstance(value, Fraction):
        whole, rest = divmod(abs(value.numerator) * 10**dp, value.denominator)
        digits = str(whole + (2 * rest >= value.denominator)).rjust(dp + 1, "0")
        return ("-" if value < 0 else "") + (f"{digits[:-dp]}.{digits[-dp:]}" if dp else digits)
    return format(value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP), "f")


def _sf(value: float, sf: int) -> str:
    d = Decimal(repr(value))
    return format(d.quantize(Decimal(1).scaleb(d.adjusted() - sf + 1), rounding=ROUND_HALF_UP), "f")


def _dec(value: Number) -> Decimal:
    return Decimal(value.numerator) / Decimal(value.denominator) if isinstance(value, Fraction) else value


# --- math_simplify: partial fractions -------------------------------------------------------------------------------

Part = tuple[sp.Expr, int, sp.Expr]  # (factor, power, numerator)


def _pf_case(
    case_id: str,
    parts: list[Part],
    quotient: sp.Expr = sp.S.Zero,
    *,
    scale: int = 1,
    written: dict[sp.Expr, sp.Expr] | None = None,
    factored: bool = True,
    origin: str = "constructed",
) -> Case:
    """The question N/D for Q + sum n/f^p, with D written factor by factor (a factor may be written negated, as
    1 - 2x for 2x - 1) or expanded, and the whole fraction scaled top and bottom by `scale`."""
    multiplicity: dict[sp.Expr, int] = {}
    for factor, power, _ in parts:
        multiplicity[factor] = max(multiplicity.get(factor, 0), power)
    den = sp.Mul(*(f**k for f, k in multiplicity.items()))
    target = quotient + sp.Add(*(n / f**p for f, p, n in parts))
    numerator = sp.expand(sp.cancel(target * den)) * scale
    written = written or {}
    sign = 1
    pieces = []
    for factor, k in sorted(multiplicity.items(), key=lambda fk: sp.sstr(fk[0])):
        shown = written.get(factor, factor)
        if shown != factor:
            sign *= (-1) ** k
        pieces.append(f"({_plain(shown)})" + (f"^{k}" if k > 1 else ""))
    if factored:
        den_text = (f"{scale}" if scale != 1 else "") + "".join(pieces)
        numerator = numerator * sign
    else:
        den_text = _plain(sp.expand(den * scale))
    expression = f"({_plain(sp.expand(numerator))})/({den_text})"
    terms = sorted(parts, key=lambda p: (sp.degree(p[0], x), sp.sstr(p[0]), p[1]))
    expect: dict[str, Any] = {
        "status": "ok",
        "form": "partial_fractions",
        "proper": quotient == 0,
        "terms": [
            {"numerator": {"text": sp.sstr(sp.expand(n))}, "factor": {"text": sp.sstr(f)}, "power": p}
            for f, p, n in terms
        ],
    }
    if quotient != 0:
        expect["quotient"] = {"text": sp.sstr(quotient)}
    return _case(case_id, {"expression": expression, "form": "partial_fractions"}, expect, origin)


def _linear(rng: random.Random, taken: set[Fraction]) -> sp.Expr:
    """A primitive linear factor p x + q (p > 0) whose root is not yet taken."""
    while True:
        p = rng.choice([1, 1, 1, 2, 3])
        q = rng.randint(-6, 6)
        if math.gcd(p, abs(q)) == 1 and Fraction(-q, p) not in taken:
            taken.add(Fraction(-q, p))
            return sp.Integer(p) * x + q


def _nonzero(rng: random.Random, low: int = -5, high: int = 5) -> int:
    return rng.choice([n for n in range(low, high + 1) if n])


def partial_fraction_cases(rng: random.Random) -> list[Case]:
    cases = [
        _pf_case("pf_hand_two_linear", [(x - 1, 1, sp.Rational(4, 3)), (x + 2, 1, sp.Rational(5, 3))], origin="hand"),
        _pf_case("pf_hand_improper", [(x - 1, 1, sp.Integer(1))], x, origin="hand"),
        _pf_case(
            "pf_hand_repeated_and_quadratic",
            [(x - 1, 1, sp.Rational(-1, 2)), (x - 1, 2, sp.Rational(1, 2)), (x**2 + 1, 1, x / 2)],
            origin="hand",
        ),
        _pf_case(
            "pf_hand_written_one_minus",
            [(2 * x - 1, 1, sp.Rational(-11, 3)), (x + 1, 1, sp.Rational(-2, 3))],
            written={2 * x - 1: 1 - 2 * x},
            origin="hand",
        ),
    ]
    for i in range(12):  # two distinct linear factors x - a, x - b
        taken: set[Fraction] = set()
        f1, f2 = _linear(rng, taken), _linear(rng, taken)
        parts = [(f1, 1, sp.Integer(_nonzero(rng))), (f2, 1, sp.Integer(_nonzero(rng)))]
        cases.append(_pf_case(f"pf_two_linear_{i:03d}", parts, factored=i % 2 == 0))
    for i in range(6):  # a factor written negated, and a common factor top and bottom
        taken = set()
        f1, f2 = _linear(rng, taken), _linear(rng, taken)
        parts = [(f1, 1, sp.Rational(_nonzero(rng), 2)), (f2, 1, sp.Rational(_nonzero(rng), 2))]
        written = {f1: sp.expand(-f1)} if i % 2 else {}
        cases.append(_pf_case(f"pf_scaled_{i:03d}", parts, scale=2, written=written))
    for i in range(8):  # a repeated linear factor and a second linear factor
        taken = set()
        f1, f2 = _linear(rng, taken), _linear(rng, taken)
        parts = [
            (f1, 1, sp.Integer(_nonzero(rng))),
            (f1, 2, sp.Integer(_nonzero(rng))),
            (f2, 1, sp.Integer(_nonzero(rng))),
        ]
        cases.append(_pf_case(f"pf_repeated_{i:03d}", parts, factored=i % 2 == 0))
    for i in range(8):  # an irreducible quadratic factor x^2 + k and a linear factor
        taken = set()
        f1 = _linear(rng, taken)
        quadratic = x**2 + rng.randint(1, 5)
        top = _nonzero(rng) * x + rng.randint(-4, 4)
        parts = [(f1, 1, sp.Integer(_nonzero(rng))), (quadratic, 1, top)]
        cases.append(_pf_case(f"pf_quadratic_{i:03d}", parts, factored=i % 2 == 1))
    for i in range(8):  # improper: a polynomial quotient as well
        taken = set()
        f1, f2 = _linear(rng, taken), _linear(rng, taken)
        quotient = rng.randint(1, 3) * x + rng.randint(-4, 4) if i % 2 else sp.Integer(_nonzero(rng))
        parts = [(f1, 1, sp.Integer(_nonzero(rng))), (f2, 1, sp.Integer(_nonzero(rng)))]
        cases.append(_pf_case(f"pf_improper_{i:03d}", parts, quotient, factored=i % 3 != 0))
    return cases


# --- math_simplify: series ------------------------------------------------------------------------------------------


def _binomial_coefficient(n: Fraction, r: int) -> Fraction:
    out = Fraction(1)
    for j in range(r):
        out = out * (n - j) / (j + 1)
    return out


def _root(value: int, degree: int) -> int:
    guess = round(abs(value) ** (1 / degree))
    for candidate in (guess - 1, guess, guess + 1):
        if candidate >= 0 and candidate**degree == abs(value):
            return candidate if value >= 0 else -candidate
    raise ValueError(f"{value} is not a perfect power of degree {degree}")


def _rational_power(a: Fraction, n: Fraction) -> Fraction:
    """a^n exactly, for a chosen as a perfect power of n's denominator."""
    base = Fraction(_root(a.numerator, n.denominator), _root(a.denominator, n.denominator))
    return base**n.numerator


def _cauchy(a: list[Fraction], b: list[Fraction]) -> list[Fraction]:
    return [sum((a[j] * b[k - j] for j in range(k + 1)), Fraction(0)) for k in range(min(len(a), len(b)))]


def _series_expect(coefficients: list[Fraction], order: int, about: Fraction = Fraction(0)) -> dict[str, Any]:
    return {
        "status": "ok",
        "form": "series",
        "about": _text(about),
        "order": order,
        "terms": [{"power": k, "coefficient": _text(c)} for k, c in enumerate(coefficients[: order + 1]) if c],
    }


def _maclaurin(kind: str, k: Fraction, count: int) -> list[Fraction]:
    """The first `count` Maclaurin coefficients of e^kx, sin kx, cos kx or ln(1 + kx)."""
    out = []
    for j in range(count):
        if kind == "exp":
            out.append(k**j / math.factorial(j))
        elif kind == "sin":
            out.append(Fraction((-1) ** ((j - 1) // 2)) * k**j / math.factorial(j) if j % 2 else Fraction(0))
        elif kind == "cos":
            out.append(Fraction((-1) ** (j // 2)) * k**j / math.factorial(j) if j % 2 == 0 else Fraction(0))
        else:
            out.append(Fraction((-1) ** (j + 1)) * k**j / j if j else Fraction(0))
    return out


def _kx(k: Fraction) -> str:
    return _plain(_q(k) * x)


BINOMIAL_POWERS = {
    Fraction(-1): [1, 2, 3, -2],
    Fraction(-2): [1, 2, 3, -1],
    Fraction(-3): [1, 2],
    Fraction(1, 2): [1, 4, 9, Fraction(1, 4)],
    Fraction(-1, 2): [1, 4, 9, Fraction(1, 4)],
    Fraction(1, 3): [1, 8, 27],
    Fraction(-1, 3): [1, 8],
    Fraction(3, 2): [1, 4],
    Fraction(-3, 2): [1, 4],
}


def _binomial_case(rng: random.Random, i: int) -> Case:
    n = rng.choice(sorted(BINOMIAL_POWERS))
    a = Fraction(rng.choice(BINOMIAL_POWERS[n]))
    b = Fraction(rng.choice([1, -1, 2, -2, 3, -3, Fraction(1, 2), Fraction(-1, 2)]))
    k = rng.choice([1, 1, 2, 3])
    order = rng.randint(2, 4)
    scale = k * _rational_power(a, n)
    coefficients = [scale * _binomial_coefficient(n, r) * (b / a) ** r for r in range(order + 1)]
    linear = _plain(_q(a) + _q(b) * x)
    if n.denominator == 1 and n < 0:
        m = -n.numerator
        expression = f"{k}/({linear})" + (f"^{m}" if m > 1 else "")
    elif n == Fraction(1, 2) and k == 1:
        expression = f"sqrt({linear})"
    elif n == Fraction(-1, 2):
        expression = f"{k}/sqrt({linear})"
    else:
        expression = f"{k}({linear})^({n})"
    expect = _series_expect(coefficients, order)
    expect["binomial"] = {"n": _text(n), "a": _text(a), "b": _text(b), "natural": False}
    expect["validity"] = {"all_real": False, "radius": _text(abs(a / b))}
    return _case(f"series_binomial_{i:03d}", {"expression": expression, "form": "series", "order": order}, expect)


def series_cases(rng: random.Random) -> list[Case]:
    half = Fraction(1, 2)
    cases = [
        _case(
            "series_hand_sqrt_one_plus_x",
            {"expression": "sqrt(1+x)", "form": "series", "order": 3},
            {
                **_series_expect([Fraction(1), half, Fraction(-1, 8), Fraction(1, 16)], 3),
                "binomial": {"n": _text(half), "natural": False},
                "validity": {"radius": _text(1)},
            },
            "hand",
        ),
        _case(
            "series_hand_reciprocal_square",
            {"expression": "1/(2+3x)^2", "form": "series", "order": 3},
            {
                **_series_expect([Fraction(1, 4), Fraction(-3, 4), Fraction(27, 16), Fraction(-27, 8)], 3),
                "validity": {"radius": _text(Fraction(2, 3))},
            },
            "hand",
        ),
        _case(
            "series_hand_sin_three_terms",
            {"expression": "sin(x)", "form": "series", "terms": 3},
            {**_series_expect(_maclaurin("sin", Fraction(1), 6), 5), "validity": {"all_real": True}},
            "hand",
        ),
        _case(
            "series_hand_natural_power_terminates",
            {"expression": "(1+x)^3", "form": "series", "terms": 6},
            {
                **_series_expect([Fraction(1), Fraction(3), Fraction(3), Fraction(1)], 3),
                "terminates": True,
                "binomial": {"natural": True},
            },
            "hand",
        ),
        _case(
            "series_hand_partial_fraction_expansion",
            {"expression": "(5x+3)/((1+x)(1-2x))", "form": "series", "order": 2},
            {**_series_expect([Fraction(3), Fraction(8), Fraction(14)], 2), "validity": {"radius": _text(half)}},
            "hand",
        ),
        _case(
            "series_hand_ln_about_one",
            {"expression": "ln(x)", "form": "series", "order": 3, "about": 1},
            _series_expect([Fraction(0), Fraction(1), Fraction(-1, 2), Fraction(1, 3)], 3, Fraction(1)),
            "hand",
        ),
    ]
    for i in range(16):
        cases.append(_binomial_case(rng, i))
    kinds = ["exp", "sin", "cos", "ln"]
    for i in range(12):  # the standard Maclaurin series
        kind = kinds[i % 4]
        k = Fraction(rng.choice([1, -1, 2, -2, 3]) if i % 3 else rng.choice([Fraction(1, 2), Fraction(-1, 3)]))
        order = rng.randint(3, 6)
        expression = {
            "exp": f"e^({_kx(k)})",
            "sin": f"sin({_kx(k)})",
            "cos": f"cos({_kx(k)})",
            "ln": f"ln({_plain(1 + _q(k) * x)})",
        }[kind]
        expect = _series_expect(_maclaurin(kind, k, order + 1), order)
        if kind != "ln":
            expect["validity"] = {"all_real": True}
        cases.append(
            _case(
                f"series_maclaurin_{kind}_{i:03d}", {"expression": expression, "form": "series", "order": order}, expect
            )
        )
    for i in range(4):  # the first non-zero terms of sin kx and cos kx
        kind = ("sin", "cos")[i % 2]
        k = Fraction(rng.choice([1, 2, -2, 3]))
        wanted = rng.randint(2, 4)
        coefficients = _maclaurin(kind, k, 2 * wanted + 1)
        order = [j for j, c in enumerate(coefficients) if c][wanted - 1]
        cases.append(
            _case(
                f"series_terms_{kind}_{i:03d}",
                {"expression": f"{kind}({_kx(k)})", "form": "series", "terms": wanted},
                _series_expect(coefficients, order),
            )
        )
    for i in range(6):  # products: e^ax (1 + bx)^-1 and e^ax sin bx, by the Cauchy product
        a, b = Fraction(rng.choice([1, 2, -1])), Fraction(rng.choice([1, -1, 2, -2]))
        order = rng.randint(2, 4)
        if i % 2:
            other = [(-b) ** j for j in range(order + 1)]
            expression = f"e^({_kx(a)})/({_plain(1 + _q(b) * x)})"
            radius: dict[str, Any] = {"radius": _text(abs(1 / b))}
        else:
            other = _maclaurin("sin", b, order + 1)
            expression = f"e^({_kx(a)})sin({_kx(b)})"
            radius = {"all_real": True}
        coefficients = _cauchy(_maclaurin("exp", a, order + 1), other)
        cases.append(
            _case(
                f"series_product_{i:03d}",
                {"expression": expression, "form": "series", "order": order},
                {**_series_expect(coefficients, order), "validity": radius},
            )
        )
    for i in range(6):  # A/(1 - ax) + B/(1 + bx) written as one fraction: two geometric series
        a, b = rng.randint(1, 3), rng.randint(1, 3)
        big_a, big_b = _nonzero(rng, -4, 4), _nonzero(rng, -4, 4)
        numerator = sp.expand(big_a * (1 + b * x) + big_b * (1 - a * x))
        order = rng.randint(2, 4)
        coefficients = [Fraction(big_a * a**k + big_b * (-b) ** k) for k in range(order + 1)]
        expression = f"({_plain(numerator)})/((1 - {a}x)(1 + {b}x))"
        cases.append(
            _case(
                f"series_split_fraction_{i:03d}",
                {"expression": expression, "form": "series", "order": order},
                {**_series_expect(coefficients, order), "validity": {"radius": _text(Fraction(1, max(a, b)))}},
            )
        )
    for i in range(6):  # Taylor series about c: 1/x, sqrt(x), ln(x) about 1, x^3
        kind = ("reciprocal", "sqrt", "ln", "cube")[i % 4]
        order = rng.randint(2, 4)
        if kind == "reciprocal":
            c = Fraction(rng.choice([1, 2, -1, 3]))
            coefficients = [Fraction((-1) ** k) / c ** (k + 1) for k in range(order + 1)]
            expression = "1/x"
        elif kind == "sqrt":
            c = Fraction(rng.choice([1, 4, 9]))
            root = Fraction(_root(c.numerator, 2))
            coefficients = [root * _binomial_coefficient(Fraction(1, 2), k) / c**k for k in range(order + 1)]
            expression = "sqrt(x)"
        elif kind == "ln":
            c = Fraction(1)
            coefficients = [Fraction((-1) ** (k + 1), k) if k else Fraction(0) for k in range(order + 1)]
            expression = "ln(x)"
        else:
            c = Fraction(rng.choice([1, 2, -1]))
            coefficients = [math.comb(3, k) * c ** (3 - k) for k in range(order + 1)]
            expression = "x^3"
        cases.append(
            _case(
                f"series_taylor_{kind}_{i:03d}",
                {"expression": expression, "form": "series", "order": order, "about": str(c)},
                _series_expect(coefficients, order, c),
            )
        )
    return cases


# --- math_simplify: complex numbers ---------------------------------------------------------------------------------


def _gaussian(a: int, b: int) -> str:
    """(a + bi) as a student writes it."""
    if b == 0:
        return f"({a})"
    imaginary = "i" if abs(b) == 1 else f"{abs(b)}i"
    if a == 0:
        return f"({'-' if b < 0 else ''}{imaginary})"
    return f"({a} {'-' if b < 0 else '+'} {imaginary})"


def _gauss_int(rng: random.Random) -> tuple[int, int]:
    return rng.randint(-5, 5), _nonzero(rng, -5, 5)


SPECIAL = [
    Fraction(n, d)
    for n, d in [
        (0, 1),
        (1, 6),
        (1, 4),
        (1, 3),
        (1, 2),
        (2, 3),
        (3, 4),
        (5, 6),
        (1, 1),
        (-1, 6),
        (-1, 4),
        (-1, 3),
        (-1, 2),
        (-2, 3),
        (-3, 4),
        (-5, 6),
    ]
]


def complex_cases(rng: random.Random) -> list[Case]:
    cart = {"form": "cartesian"}
    polar = {"form": "modulus_argument"}
    cases = [
        _case(
            "complex_hand_quotient",
            {"expression": "(1+2i)/(3-i)", **cart},
            {"status": "ok", "real": _text(Fraction(1, 10)), "imaginary": _text(Fraction(7, 10))},
            "hand",
        ),
        _case(
            "complex_hand_i_squared",
            {"expression": "i^2", **cart},
            {"status": "ok", "real": _text(-1), "imaginary": _text(0)},
            "hand",
        ),
        _case(
            "complex_hand_exponential_form",
            {"expression": "2e^(i pi/3)", **cart},
            {"status": "ok", "real": _text(1), "imaginary": {"text": "sqrt(3)"}},
            "hand",
        ),
        _case(
            "complex_hand_three_four",
            {"expression": "3+4i", **polar},
            {"status": "ok", "modulus": _text(5), "argument": {"decimal": _sf(math.atan2(4, 3), 6)}},
            "hand",
        ),
        _case(
            "complex_hand_third_quadrant",
            {"expression": "-1-i", **polar},
            {
                "status": "ok",
                "modulus": {"text": "sqrt(2)"},
                "argument": {"text": "-3*pi/4"},
                "argument_degrees": _text(-135),
                "exponential": {"text": "sqrt(2)*exp(-3*I*pi/4)"},
            },
            "hand",
        ),
        _case(
            "complex_hand_negative_real",
            {"expression": "-2", **polar},
            {"status": "ok", "modulus": _text(2), "argument": {"text": "pi"}},
            "hand",
        ),
    ]
    for i in range(8):  # products (a + bi)(c + di) = (ac - bd) + (ad + bc)i
        (a, b), (c, d) = _gauss_int(rng), _gauss_int(rng)
        cases.append(
            _case(
                f"complex_product_{i:03d}",
                {"expression": f"{_gaussian(a, b)}{_gaussian(c, d)}", **cart},
                {"status": "ok", "real": _text(a * c - b * d), "imaginary": _text(a * d + b * c)},
            )
        )
    for i in range(8):  # quotients: multiply by the conjugate of the denominator
        (a, b), (c, d) = _gauss_int(rng), _gauss_int(rng)
        norm = c * c + d * d
        cases.append(
            _case(
                f"complex_quotient_{i:03d}",
                {"expression": f"{_gaussian(a, b)}/{_gaussian(c, d)}", **cart},
                {
                    "status": "ok",
                    "real": _text(Fraction(a * c + b * d, norm)),
                    "imaginary": _text(Fraction(b * c - a * d, norm)),
                },
            )
        )
    for i in range(4):  # powers by repeated multiplication
        a, b = rng.randint(-3, 3), _nonzero(rng, -3, 3)
        n = rng.choice([2, 3, 4])
        re, im = 1, 0
        for _ in range(n):
            re, im = re * a - im * b, re * b + im * a
        cases.append(
            _case(
                f"complex_power_{i:03d}",
                {"expression": f"{_gaussian(a, b)}^{n}", **cart},
                {"status": "ok", "real": _text(re), "imaginary": _text(im)},
            )
        )
    for i in range(10):  # r(cos t + i sin t) from a chosen modulus and special angle
        r, angle = rng.choice([1, 2, 3, 4, 6]), rng.choice(SPECIAL)
        theta = _q(angle) * sp.pi
        re, im = r * sp.cos(theta), r * sp.sin(theta)
        written = _plain(re) if im == 0 else f"({_plain(im)})i" if re == 0 else f"{_plain(re)} + ({_plain(im)})i"
        expect = {
            "status": "ok",
            "modulus": _text(r),
            "argument": {"text": sp.sstr(theta)},
            "argument_degrees": _text(angle * 180),
        }
        cases.append(_case(f"complex_modulus_argument_{i:03d}", {"expression": written, **polar}, expect))
    for i in range(6):  # Pythagorean moduli in every quadrant: argument from atan2
        p, q, h = rng.choice([(3, 4, 5), (5, 12, 13), (8, 15, 17), (4, 3, 5)])
        sa, sb = rng.choice([(1, 1), (-1, 1), (-1, -1), (1, -1)])
        a, b = sa * p, sb * q
        expect = {"status": "ok", "modulus": _text(h), "argument": {"decimal": _sf(math.atan2(b, a), 6)}}
        cases.append(_case(f"complex_pythagorean_{i:03d}", {"expression": _gaussian(a, b)[1:-1], **polar}, expect))
    for i in range(4):  # the exponential form back to a + bi
        r, angle = rng.choice([1, 2, 4]), rng.choice(SPECIAL[1:])
        theta = _q(angle) * sp.pi
        written = ("" if r == 1 else f"{r}") + f"e^(i*({_plain(theta)}))"
        cases.append(
            _case(
                f"complex_from_exponential_{i:03d}",
                {"expression": written, **cart},
                {
                    "status": "ok",
                    "real": {"text": sp.sstr(r * sp.cos(theta))},
                    "imaginary": {"text": sp.sstr(r * sp.sin(theta))},
                },
            )
        )
    return cases


def simplify_error_cases() -> list[Case]:
    pf, series = {"form": "partial_fractions"}, {"form": "series"}
    return [
        _case("simplify_alevel_error_pf_not_rational", {"expression": "sin(x)/x", **pf}, ERROR, "hand"),
        _case("simplify_alevel_error_pf_no_denominator", {"expression": "x^2 + 1", **pf}, ERROR, "hand"),
        _case("simplify_alevel_error_pf_two_variables", {"expression": "1/((x-1)(y+2))", **pf}, ERROR, "hand"),
        _case("simplify_alevel_error_pf_order", {"expression": "1/(x(x+1))", "order": 2, **pf}, ERROR, "hand"),
        _case("simplify_alevel_error_series_ln_at_zero", {"expression": "ln(x)", "order": 3, **series}, ERROR, "hand"),
        _case(
            "simplify_alevel_error_series_sqrt_at_zero", {"expression": "sqrt(x)", "order": 2, **series}, ERROR, "hand"
        ),
        _case("simplify_alevel_error_series_no_order", {"expression": "e^x", **series}, ERROR, "hand"),
        _case(
            "simplify_alevel_error_series_order_and_terms",
            {"expression": "e^x", "order": 2, "terms": 2, **series},
            ERROR,
            "hand",
        ),
        _case("simplify_alevel_error_zero_argument", {"expression": "0", "form": "modulus_argument"}, ERROR, "hand"),
        _case("simplify_alevel_error_complex_variable", {"expression": "x + 2i", "form": "cartesian"}, ERROR, "hand"),
        _case(
            "simplify_alevel_error_series_on_old_form",
            {"expression": "x + x", "form": "simplest", "order": 2},
            ERROR,
            "hand",
        ),
    ]


# --- math_solve: complex roots --------------------------------------------------------------------------------------


def _root_entry(re: int | Fraction, im: int | Fraction) -> tuple[tuple[Fraction, Fraction], dict[str, str]]:
    return (Fraction(re), Fraction(im)), {"text": sp.sstr(_q(Fraction(re)) + _q(Fraction(im)) * sp.I)}


def _roots_expect(
    roots: list[tuple[int | Fraction, int | Fraction]], name: str, real_coefficients: bool
) -> dict[str, Any]:
    entries = sorted(_root_entry(re, im) for re, im in roots)
    keys = [k for k, _ in entries]
    pairs = [
        [j, k]
        for j in range(len(keys))
        for k in range(j + 1, len(keys))
        if keys[j][1] != 0 and keys[j][0] == keys[k][0] and keys[j][1] == -keys[k][1]
    ]
    return {
        "case": "solutions",
        "domain": "complex",
        "solutions": [{name: e} for _, e in entries],
        "conjugate_pairs": pairs,
        "real_coefficients": real_coefficients,
    }


def _poly_text(coefficients: list[int], name: str) -> str:
    z = sp.Symbol(name)
    degree = len(coefficients) - 1
    return _plain(sp.Add(*(c * z ** (degree - j) for j, c in enumerate(coefficients))))


def _expand(roots: list[tuple[int, int]]) -> list[int]:
    """The monic polynomial's integer coefficients from roots closed under conjugation, by Gaussian arithmetic."""
    coefficients = [(1, 0)]
    for re, im in roots:
        shifted = [*coefficients, (0, 0)]
        for j in range(1, len(shifted)):
            a, b = coefficients[j - 1]
            c, d = shifted[j]
            shifted[j] = (c - (a * re - b * im), d - (a * im + b * re))
        coefficients = shifted
    assert all(b == 0 for _, b in coefficients)
    return [a for a, _ in coefficients]


def complex_root_cases(rng: random.Random) -> list[Case]:
    cplx = {"domain": "complex"}
    cases = [
        _case(
            "croots_hand_quadratic",
            {"equations": ["z^2 - 2z + 5 = 0"], **cplx},
            _roots_expect([(1, -2), (1, 2)], "z", True),
            "hand",
        ),
        _case(
            "croots_hand_cube_roots_of_unity",
            {"equations": ["z^3 = 1"], **cplx},
            {
                "case": "solutions",
                "solutions": [
                    {"z": {"text": "-1/2 - sqrt(3)*I/2"}},
                    {"z": {"text": "-1/2 + sqrt(3)*I/2"}},
                    {"z": {"text": "1"}},
                ],
                "conjugate_pairs": [[0, 1]],
            },
            "hand",
        ),
        _case(
            "croots_hand_quartic",
            {"equations": ["z^4 + 4 = 0"], **cplx},
            _roots_expect([(-1, -1), (-1, 1), (1, -1), (1, 1)], "z", True),
            "hand",
        ),
        _case(
            "croots_hand_square_root_of_2i",
            {"equations": ["z^2 = 2i"], **cplx},
            _roots_expect([(-1, -1), (1, 1)], "z", False),
            "hand",
        ),
        _case(
            "croots_hand_repeated",
            {"equations": ["(z-1)^2 (z^2+1) = 0"], **cplx},
            {
                "case": "solutions",
                "solutions": [{"z": {"text": "-I"}}, {"z": {"text": "I"}}, {"z": {"text": "1", "multiplicity": 2}}],
            },
            "hand",
        ),
    ]
    for i in range(16):  # k z^2 - 2kp z + k(p^2 + q^2) = 0 from p +- qi
        p, q, k = rng.randint(-5, 5), rng.randint(1, 6), rng.choice([1, 1, 2, 3])
        name = rng.choice(["z", "z", "w"])
        coefficients = [k * c for c in _expand([(p, q), (p, -q)])]
        if i % 3 == 2:  # constant term moved to the right-hand side
            equation = f"{_poly_text([*coefficients[:-1], 0], name)} = {-coefficients[-1]}"
        else:
            equation = f"{_poly_text(coefficients, name)} = 0"
        cases.append(
            _case(
                f"croots_quadratic_{i:03d}",
                {"equations": [equation], **cplx},
                _roots_expect([(p, q), (p, -q)], name, True),
            )
        )
    for i in range(10):  # a real root and a conjugate pair
        r, p, q = rng.randint(-4, 4), rng.randint(-3, 3), rng.randint(1, 4)
        roots = [(r, 0), (p, q), (p, -q)]
        cases.append(
            _case(
                f"croots_cubic_{i:03d}",
                {"equations": [f"{_poly_text(_expand(roots), 'z')} = 0"], **cplx},
                _roots_expect(roots, "z", True),
            )
        )
    for i in range(4):  # two conjugate pairs
        while True:
            (p1, q1), (p2, q2) = (rng.randint(-3, 3), rng.randint(1, 3)), (rng.randint(-3, 3), rng.randint(1, 3))
            if (p1, q1) != (p2, q2):
                break
        roots = [(p1, q1), (p1, -q1), (p2, q2), (p2, -q2)]
        cases.append(
            _case(
                f"croots_quartic_{i:03d}",
                {"equations": [f"{_poly_text(_expand(roots), 'z')} = 0"], **cplx},
                _roots_expect(roots, "z", True),
            )
        )
    for i in range(6):  # z^2 - (u + v)z + uv = 0 with Gaussian-integer roots u, v (complex coefficients)
        while True:
            u, v = (rng.randint(-3, 3), _nonzero(rng, -3, 3)), (rng.randint(-3, 3), rng.randint(-3, 3))
            if u != v and u != (v[0], -v[1]):
                break
        s = (u[0] + v[0], u[1] + v[1])
        product = (u[0] * v[0] - u[1] * v[1], u[0] * v[1] + u[1] * v[0])
        equation = f"z^2 - {_gaussian(*s)}z + {_gaussian(*product)} = 0"
        cases.append(
            _case(
                f"croots_complex_coefficients_{i:03d}",
                {"equations": [equation], **cplx},
                _roots_expect([u, v], "z", s[1] == 0 and product[1] == 0),
            )
        )
    return cases


# --- math_solve: numerical methods ----------------------------------------------------------------------------------


def _horner(coefficients: list[int], value: Number) -> Number:
    out: Number = Fraction(0) if isinstance(value, Fraction) else Decimal(0)
    for c in coefficients:
        out = out * value + (c if isinstance(value, Fraction) else Decimal(c))  # type: ignore[operator]
    return out


def _derivative(coefficients: list[int]) -> list[int]:
    degree = len(coefficients) - 1
    return [c * (degree - j) for j, c in enumerate(coefficients[:-1])]


Step = Callable[[Number], "tuple[Number, bool] | str"]


def _iterates(
    step: Step, start: Fraction, steps: int | None, tolerance: Fraction | None
) -> tuple[list[tuple[Number, bool]], str, int | None]:
    """The iterates (value, exact) and why they stopped, by the tool's documented rules; `step` returns the reason
    instead when the method fails there (derivative_zero, undefined)."""
    xs: list[tuple[Number, bool]] = [(start, True)]
    limit = steps if steps is not None else 50
    while True:
        if len(xs) - 1 >= limit:
            return xs, ("steps" if steps is not None else "max_steps"), None
        following = step(xs[-1][0])
        if isinstance(following, str):
            return xs, following, len(xs) - 1
        value, exact = following
        exact = exact and xs[-1][1]
        if not exact and isinstance(value, Fraction):
            value = _dec(value)
        xs.append((value, exact))
        if abs(value) > DIVERGED:
            return xs, "diverged", None
        if tolerance is not None and abs(_dec(value) - _dec(xs[-2][0])) < _dec(tolerance):
            return xs, "tolerance", None


def _iterates_expect(
    xs: list[tuple[Number, bool]], dp: int, first: int, stopped: str, at: int | None, texts: bool = True
) -> dict[str, Any]:
    entries: list[dict[str, Any]] = []
    for n, (value, exact) in enumerate(xs):
        if abs(value) > DIVERGED:
            entries.append({})  # shown to 6 significant figures; any entry matches
            continue
        shown: dict[str, str] = {"decimal": _dp(value, dp)}
        if exact and isinstance(value, Fraction) and (texts or n == 0):
            shown["text"] = str(value)
        entries.append({"n": first + n, "x": shown})
    expect: dict[str, Any] = {"status": "ok", "dp": dp, "iterates": entries, "stopped": stopped}
    if at is not None:
        expect["at"] = first + at
    if stopped == "tolerance":
        expect["root"] = {"decimal": _dp(xs[-1][0], dp)}
    return expect


def _nr_step(coefficients: list[int]) -> Step:
    slope = _derivative(coefficients)

    def step(value: Number) -> tuple[Number, bool] | str:
        fx, dx = _horner(coefficients, value), _horner(slope, value)
        if dx == 0:
            return "derivative_zero"
        following = value - fx / dx  # type: ignore[operator]
        if isinstance(following, Fraction):
            assert isinstance(fx, Fraction) and isinstance(dx, Fraction)
            return following, _small(fx) and _small(dx) and _small(following)
        return following, False

    return step


def _settings(rng: random.Random, i: int) -> tuple[dict[str, Any], int | None, Fraction | None, int, int]:
    dp, first = rng.choice([3, 4, 5, 6]), 1 if i % 4 == 3 else 0
    if i % 3 == 2:
        tolerance = Fraction(1, 10 ** (dp + 1))
        return (
            {"tolerance": str(tolerance), "dp": dp, **({"first_index": 1} if first else {})},
            None,
            tolerance,
            dp,
            first,
        )
    steps = rng.randint(3, 5)
    return {"steps": steps, "dp": dp, **({"first_index": 1} if first else {})}, steps, None, dp, first


def newton_cases(rng: random.Random) -> list[Case]:
    cases = []
    with localcontext() as ctx:
        ctx.prec = 70
        coefficients = [1, 0, -2, -5]
        xs, stopped, at = _iterates(_nr_step(coefficients), Fraction(2), 4, None)
        cases.append(
            _case(
                "nr_hand_newton_cubic",
                {"equations": ["x^3 - 2x - 5 = 0"], "method": "newton_raphson", "start": 2, "steps": 4, "dp": 6},
                {
                    **_iterates_expect(xs, 6, 0, stopped, at),
                    "method": "newton_raphson",
                    "derivative": {"text": "3*x**2 - 2"},
                },
                "hand",
            )
        )

        def exponential(value: Number) -> tuple[Number, bool]:
            v = _dec(value)
            return v - (v.exp() - 3 * v) / (v.exp() - 3), False

        xs, stopped, at = _iterates(exponential, Fraction(0), None, Fraction(1, 10**9))
        cases.append(
            _case(
                "nr_hand_exponential",
                {"equations": ["e^x = 3x"], "method": "newton_raphson", "start": 0, "tolerance": "1e-9", "dp": 8},
                _iterates_expect(xs, 8, 0, stopped, at),
                "hand",
            )
        )
        cases.append(
            _case(
                "nr_hand_derivative_zero",
                {"equations": ["x^2 - 4 = 0"], "method": "newton_raphson", "start": 0, "steps": 3},
                {
                    "status": "ok",
                    "iterates": [{"n": 0, "x": {"decimal": "0.000000", "text": "0"}}],
                    "stopped": "derivative_zero",
                    "at": 0,
                },
                "hand",
            )
        )
        for i in range(18):  # (x - r)(x^2 + px + q), one real root r
            r = _nonzero(rng, -4, 4)
            while True:
                p, q = rng.randint(-3, 3), rng.randint(1, 6)
                if p * p < 4 * q:
                    break
            coefficients = [1, p - r, q - p * r, -q * r]
            start = r + rng.choice([Fraction(1, 2), Fraction(-1, 2), Fraction(1), Fraction(3, 2), Fraction(-1)])
            extra, steps, tolerance, dp, first = _settings(rng, i)
            xs, stopped, at = _iterates(_nr_step(coefficients), start, steps, tolerance)
            args = {
                "equations": [f"{_poly_text(coefficients, 'x')} = 0"],
                "method": "newton_raphson",
                "start": str(start),
                **extra,
            }
            cases.append(_case(f"nr_cubic_{i:03d}", args, _iterates_expect(xs, dp, first, stopped, at)))
        for i in range(4):  # f'(x0) = 0: x0 midway between the roots of a quadratic
            r, s = sorted(rng.sample(range(-6, 7), 2))
            start = Fraction(r + s, 2)
            args = {
                "equations": [f"{_poly_text([1, -(r + s), r * s], 'x')} = 0"],
                "method": "newton_raphson",
                "start": str(start),
                "steps": 3,
                "dp": 4,
            }
            expect = {
                "status": "ok",
                "iterates": [{"n": 0, "x": {"decimal": _dp(start, 4), "text": str(start)}}],
                "stopped": "derivative_zero",
                "at": 0,
            }
            cases.append(_case(f"nr_derivative_zero_{i:03d}", args, expect))
    return cases


def _cbrt(value: Decimal) -> Decimal:
    """The real cube root (a calculator's, negative for a negative number)."""
    if value < 0:
        return -_cbrt(-value)
    return (value.ln() / 3).exp() if value else Decimal(0)


def _real(value: Decimal | str) -> tuple[Number, bool] | str:
    return value if isinstance(value, str) else (value, False)


def _cube_root_step(a: int, b: int) -> Step:
    """x -> cbrt(b - ax)."""
    return lambda value: _real(_cbrt(b - a * _dec(value)))


def _cubic_step(a: int, b: int) -> Step:
    """x -> (b - x^3)/a, exact while the fractions stay small."""

    def step(value: Number) -> tuple[Number, bool] | str:
        if isinstance(value, Fraction):
            following = (b - value**3) / a
            return following, _small(following)
        return (b - value**3) / a, False

    return step


def _square_root_step(p: int, q: int) -> Step:
    """x -> sqrt(px + q), undefined below -q/p."""

    def step(value: Number) -> tuple[Number, bool] | str:
        radicand = p * _dec(value) + q
        return "undefined" if radicand < 0 else (radicand.sqrt(), False)

    return step


def _square_step(p: int, q: int) -> Step:
    """x -> (x^2 - q)/p, exact while the fractions stay small."""

    def step(value: Number) -> tuple[Number, bool] | str:
        if isinstance(value, Fraction):
            following = (value**2 - q) / p
            return following, _small(following)
        return (value**2 - q) / p, False

    return step


def iteration_cases(rng: random.Random) -> list[Case]:
    cases = []
    with localcontext() as ctx:
        ctx.prec = 70

        def cube_root_step(value: Number) -> tuple[Number, bool] | str:
            return _real(_cbrt(2 * _dec(value) + 5))

        xs, stopped, at = _iterates(cube_root_step, Fraction(2), 4, None)
        cases.append(
            _case(
                "iter_hand_cube_root",
                {
                    "equations": ["x^3 - 2x - 5 = 0"],
                    "method": "iteration",
                    "g": "cbrt(2x + 5)",
                    "start": 2,
                    "steps": 4,
                    "dp": 4,
                },
                {
                    **_iterates_expect(xs, 4, 0, stopped, at),
                    "convergence": {"converges": True, "diagram": "staircase", "rearrangement_matches": True},
                },
                "hand",
            )
        )

        def exponential_step(value: Number) -> tuple[Number, bool]:
            return (-_dec(value)).exp(), False

        xs, stopped, at = _iterates(exponential_step, Fraction(1, 2), 6, None)
        cases.append(
            _case(
                "iter_hand_exponential",
                {
                    "equations": ["x = e^(-x)"],
                    "method": "iteration",
                    "g": "e^(-x)",
                    "start": "0.5",
                    "steps": 6,
                    "dp": 4,
                    "first_index": 1,
                },
                {**_iterates_expect(xs, 4, 1, stopped, at), "convergence": {"converges": True, "diagram": "cobweb"}},
                "hand",
            )
        )
        for i in range(12):  # x^3 + ax - b = 0 with root r: x = cbrt(b - ax) and x = (b - x^3)/a, both cobwebs
            r = rng.randint(1, 3)
            while True:
                a = rng.randint(1, 12)
                if a != 3 * r * r:
                    break
            b = r**3 + a * r
            start = r + rng.choice([Fraction(1, 2), Fraction(-1, 2), Fraction(1, 4)])
            extra, steps, tolerance, dp, first = _settings(rng, i)
            equation = f"x^3 + {a}x - {b} = 0" if i % 2 else f"x^3 + {a}x = {b}"
            if i % 2:
                step, g, converges, texts = _cube_root_step(a, b), f"cbrt({b} - {a}x)", a < 3 * r * r, False
            else:
                step, g, converges, texts = _cubic_step(a, b), f"({b} - x^3)/{a}", a > 3 * r * r, True
            if not converges and steps is None:  # a diverging iteration is stopped by steps
                extra = {k: v for k, v in extra.items() if k != "tolerance"} | {"steps": 6}
                steps, tolerance = 6, None
            xs, stopped, at = _iterates(step, start, steps, tolerance)
            expect = {
                **_iterates_expect(xs, dp, first, stopped, at, texts),
                "convergence": {
                    "converges": converges,
                    "diagram": "cobweb",
                    "root": {"decimal": _dp(Fraction(r), dp)},
                    "rearrangement_matches": True,
                },
            }
            args = {"equations": [equation], "method": "iteration", "g": g, "start": str(start), **extra}
            cases.append(_case(f"iter_cubic_{i:03d}", args, expect))
        for i in range(10):  # x^2 - px - q = 0 with roots r > 0 > s: x = sqrt(px + q) and x = (x^2 - q)/p, staircases
            r, s = rng.randint(2, 6), -rng.randint(1, 5)
            p, q = r + s, -r * s
            if p <= 0:
                r, s = -s + 1, s  # keep p = r + s positive
                p, q = r + s, -r * s
            start = r + rng.choice([Fraction(1, 2), Fraction(-1, 2), Fraction(1)])
            extra, steps, tolerance, dp, first = _settings(rng, i)
            if i % 2 == 0:
                step, g, converges, texts = _square_root_step(p, q), f"sqrt({p}x + {q})", True, False
            else:
                step, g, converges, texts = _square_step(p, q), f"(x^2 - {q})/{p}", 2 * r < p, True
                if steps is None:
                    extra = {k: v for k, v in extra.items() if k != "tolerance"} | {"steps": 5}
                    steps, tolerance = 5, None
            xs, stopped, at = _iterates(step, start, steps, tolerance)
            expect = {
                **_iterates_expect(xs, dp, first, stopped, at, texts),
                "convergence": {
                    "converges": converges,
                    "diagram": "staircase",
                    "root": {"decimal": _dp(Fraction(r), dp)},
                },
            }
            args = {
                "equations": [f"{_poly_text([1, -p, -q], 'x')} = 0"],
                "method": "iteration",
                "g": g,
                "start": str(start),
                **extra,
            }
            cases.append(_case(f"iter_quadratic_{i:03d}", args, expect))
    return cases


def sign_change_cases(rng: random.Random) -> list[Case]:
    method = {"method": "sign_change"}
    cases = [
        _case(
            "sign_hand_cubic_to_3dp",
            {"equations": ["x^3 - 2x - 5 = 0"], "interval": ["2.0945", "2.0955"], **method},
            {
                "status": "ok",
                "f_lower": _text(Fraction(-4596731, 8000000000)),
                "f_upper": _text(Fraction(84739871, 8000000000)),
                "sign_change": True,
                "root_located": True,
                "estimate": _text(Fraction(419, 200)),
                "error_bound": _text(Fraction(1, 2000)),
            },
            "hand",
        ),
        _case(
            "sign_hand_asymptote",
            {"equations": ["1/(x - 1) = 0"], "interval": [0, 2], **method},
            {"status": "ok", "sign_change": True, "continuous": False, "root_located": False},
            "hand",
        ),
        _case(
            "sign_hand_exponential",
            {"equations": ["e^x - 3x = 0"], "interval": [0, 1], **method},
            {
                "status": "ok",
                "f_lower": _text(1),
                "sign_change": True,
                "root_located": True,
                "error_bound": _text(Fraction(1, 2)),
            },
            "hand",
        ),
    ]
    for i in range(16):  # (x - r1)(x - r2)(x - r3) on intervals around one root, around two, or ending at one
        roots = sorted(rng.sample(range(-5, 6), 3))
        coefficients = _expand([(r, 0) for r in roots])
        kind = ("one", "one", "two", "end")[i % 4]
        j = rng.randint(0, 2)
        if kind == "one":
            lo = roots[j] - Fraction(rng.randint(1, 9), 10)
            hi = roots[j] + Fraction(rng.randint(1, 9), 10)
        elif kind == "two":
            j = min(j, 1)
            lo, hi = roots[j] - Fraction(1, 2), roots[j + 1] + Fraction(1, 2)
        else:
            lo, hi = Fraction(roots[j]), roots[j] + Fraction(1, 2)
        f_lo, f_hi = _horner(coefficients, lo), _horner(coefficients, hi)
        assert isinstance(f_lo, Fraction) and isinstance(f_hi, Fraction)
        change = f_lo * f_hi < 0
        expect: dict[str, Any] = {
            "status": "ok",
            "interval": [_text(lo), _text(hi)],
            "f_lower": _text(f_lo),
            "f_upper": _text(f_hi),
            "sign_change": change,
            "continuous": True,
            "root_located": change,
        }
        if change:
            expect |= {"estimate": _text((lo + hi) / 2), "error_bound": _text((hi - lo) / 2)}
        if kind == "end":
            expect["root_at_end"] = _text(lo)
        args = {"equations": [f"{_poly_text(coefficients, 'x')} = 0"], "interval": [str(lo), str(hi)], **method}
        cases.append(_case(f"sign_cubic_{kind}_{i:03d}", args, expect))
    return cases


def solve_error_cases() -> list[Case]:
    cplx = {"domain": "complex"}
    nr = {"method": "newton_raphson"}
    return [
        _case(
            "solve_alevel_error_complex_two_equations", {"equations": ["z + w = 1", "z - w = i"], **cplx}, ERROR, "hand"
        ),
        _case("solve_alevel_error_complex_not_polynomial", {"equations": ["e^z = 1"], **cplx}, ERROR, "hand"),
        _case(
            "solve_alevel_error_complex_unknown_i",
            {"equations": ["i^2 = -1"], "unknowns": ["i"], **cplx},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_iteration_without_g",
            {"equations": ["x^3 - 2x - 5 = 0"], "method": "iteration", "start": 2, "steps": 3},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_newton_without_start",
            {"equations": ["x^3 - 2x - 5 = 0"], "steps": 3, **nr},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_newton_without_stop",
            {"equations": ["x^3 - 2x - 5 = 0"], "start": 2, **nr},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_newton_negative_tolerance",
            {"equations": ["x^3 - 2x - 5 = 0"], "start": 2, "tolerance": "-0.001", **nr},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_sign_change_without_interval",
            {"equations": ["x^3 - 2x - 5 = 0"], "method": "sign_change"},
            ERROR,
            "hand",
        ),
        _case("solve_alevel_error_start_without_method", {"equations": ["x^2 = 2"], "start": 1}, ERROR, "hand"),
        _case(
            "solve_alevel_error_method_in_complex_domain",
            {"equations": ["z^2 = 2"], "start": 1, "steps": 2, **nr, **cplx},
            ERROR,
            "hand",
        ),
        _case(
            "solve_alevel_error_two_unknowns",
            {"equations": ["x^2 + y = 2"], "start": 1, "steps": 2, **nr},
            ERROR,
            "hand",
        ),
    ]


# --- sets -----------------------------------------------------------------------------------------------------------


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The VER-30 algebra sets by name (stage S3), refusals last."""
    simplify = partial_fraction_cases(rng) + series_cases(rng) + complex_cases(rng) + simplify_error_cases()
    solve = (
        complex_root_cases(rng)
        + newton_cases(rng)
        + iteration_cases(rng)
        + sign_change_cases(rng)
        + solve_error_cases()
    )
    return {"math_simplify.a_level": _errors_last(simplify), "math_solve.a_level": _errors_last(solve)}
