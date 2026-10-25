"""Golden set for the A level statistics checker `stats_distribution` (VER-30; VER-29), built by construction like
`golden.py` and with its own seed, so every other set is unchanged.

Expected answers never come from the checker under test, and use none of its numerics (it sums with SymPy and
evaluates erf, erfinv and the incomplete beta function with mpmath):
- binomial probabilities are exact Fraction sums of C(n, r) p^r q^(n - r) here; Poisson ones are e^(-lambda) times an
  exact Fraction sum, with e^lambda from Python's `decimal` at 60 digits;
- the normal distribution function is the Maclaurin series of erf in `decimal` at 60 digits (pi by Machin's formula),
  and its inverse is bisection on that series; the table convention reads z to 2 places and Phi(z) to 4 by its rule;
- PMCC critical values for an even n integrate the null density (1 - s^2)^((n - 4) / 2) exactly as a polynomial and
  bisect in Fractions; other sizes use the printed table values (hand cases);
- regression lines come from a chosen exact line plus residuals constructed orthogonal to 1 and to the explanatory
  variable, so least squares returns the chosen gradient and intercept exactly; Spearman's coefficient from a chosen
  rank permutation; correlation sums from the definitions.

Every case is synthetic; the set says `review: pending` until two subject teachers have authored and reviewed it."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal, localcontext
from fractions import Fraction
from math import comb
from typing import Any

import sympy as sp

Case = dict[str, Any]
SEED = 20261030
DIGITS = 60
DOMAIN_ERROR = 4


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> Case:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _errors_last(cases: list[Case]) -> list[Case]:
    """Expected refusals after the answered cases (the offline check runs each set's first cases end to end)."""
    return sorted(cases, key=lambda case: "error" in case["expect"])


def _text(value: Fraction | int) -> str:
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _arg(value: Fraction) -> int | str:
    """A terminating fraction as an argument (integer or decimal string), any other as "a/b"."""
    if value.denominator == 1:
        return int(value)
    den = value.denominator
    while den % 2 == 0:
        den //= 2
    while den % 5 == 0:
        den //= 5
    if den != 1:
        return _text(value)
    with localcontext() as ctx:
        ctx.prec = DIGITS
        text = format(Decimal(value.numerator) / Decimal(value.denominator), "f")
    assert Fraction(text) == value, value
    return text


# --- decimals, independent of the checker ------------------------------------------------------------------------


def _decimal(value: Fraction | Decimal) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DIGITS
        if isinstance(value, Fraction):
            return Decimal(value.numerator) / Decimal(value.denominator)
        return +value


def _sf(value: Fraction | Decimal, sf: int) -> str:
    """Half away from zero to `sf` significant figures, written as the worker writes decimals (standard form below
    1e-4 and from 1e12)."""
    d = _decimal(value)
    if d == 0:
        return "0"
    rounded = d.quantize(Decimal(1).scaleb(d.adjusted() - sf + 1), rounding=ROUND_HALF_UP)
    if rounded.adjusted() < -4 or rounded.adjusted() >= 12:
        return f"{format(rounded.scaleb(-rounded.adjusted()), 'f')}e{rounded.adjusted()}"
    return format(rounded, "f")


def _dp(value: Decimal, dp: int) -> Fraction:
    return Fraction(value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP))


def _pi() -> Decimal:
    """pi = 16 arctan(1/5) - 4 arctan(1/239) (Machin)."""

    def arctan_inverse(k: int) -> Decimal:
        total, power, n, sign = Decimal(0), Decimal(1) / k, 1, 1
        while power > Decimal(10) ** -(DIGITS + 5):
            total += sign * power / n
            power /= k * k
            n, sign = n + 2, -sign
        return total

    with localcontext() as ctx:
        ctx.prec = DIGITS + 10
        return 16 * arctan_inverse(5) - 4 * arctan_inverse(239)


PI = _pi()


def _phi(z: Fraction | Decimal) -> Decimal:
    """Phi(z) = (1 + erf(z / sqrt 2)) / 2, erf by its Maclaurin series."""
    with localcontext() as ctx:
        ctx.prec = DIGITS + 20
        x = _decimal(z) / Decimal(2).sqrt() if isinstance(z, Fraction) else z / Decimal(2).sqrt()
        total, term, n = Decimal(0), x, 0  # term = (-1)^n x^(2n+1) / n!
        while abs(term) > Decimal(10) ** -(DIGITS + 15) or n < 3:
            total += term / (2 * n + 1)
            n += 1
            term = -term * x * x / n
        erf = 2 / PI.sqrt() * total
        return (1 + erf) / 2


def _phi_inverse(q: Fraction) -> Decimal:
    """z with Phi(z) = q, by bisection."""
    target = _decimal(q)
    low, high = Decimal(-9), Decimal(9)
    with localcontext() as ctx:
        ctx.prec = DIGITS
        for _ in range(170):
            middle = (low + high) / 2
            if _phi(middle) < target:
                low = middle
            else:
                high = middle
        return (low + high) / 2


def _phi_table(z: Fraction) -> Fraction:
    """The printed table: z to 2 decimal places, Phi(|z|) to 4, Phi(-z) = 1 - Phi(z)."""
    z2 = _dp(_decimal(z), 2)
    read = _dp(_phi(abs(z2)), 4)
    return read if z2 >= 0 else 1 - read


PERCENTAGE_POINTS = {Fraction(p) for p in ("0.5", "0.4", "0.3", "0.2", "0.15", "0.1", "0.05", "0.025", "0.02", "0.01",
                                           "0.005", "0.0025", "0.001", "0.0005")}  # fmt: skip


def _z_table(q: Fraction) -> Fraction:
    z = _phi_inverse(q)
    return _dp(z, 4 if min(q, 1 - q) in PERCENTAGE_POINTS else 2)


def _exp(lam: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DIGITS + 20
        return _decimal(lam).exp()


def _number(value: Fraction | Decimal, sf: int, exact: str | None = None) -> dict[str, str]:
    out = {"decimal": _sf(value, sf)}
    if exact is not None and len(exact) <= 80:
        out["text"] = exact
    return out


def _with_sf(rng: random.Random, args: dict[str, Any]) -> tuple[dict[str, Any], int]:
    sf = rng.choice([3, 4, 4, 5, None])
    return (args if sf is None else {**args, "sf": sf}), (4 if sf is None else sf)


# --- binomial and Poisson ----------------------------------------------------------------------------------------

SYMBOLS = {"eq": "=", "le": "<=", "lt": "<", "ge": ">=", "gt": ">"}
PROBABILITIES = ["0.3", "0.25", "1/6", "0.45", "0.6", "0.15", "0.7", "1/3", "0.05", "0.85", "0.4", "0.2"]
RELATIONS = ["eq", "le", "lt", "ge", "gt", "between"]


def _interval(relation: str, k: int, k2: int, top: int | None) -> tuple[int, int | None, str]:
    if relation == "between":
        return k, k2, f"P({k} <= X <= {k2})"
    reading = f"P(X {SYMBOLS[relation]} {k})"
    return {"eq": (k, k), "le": (0, k), "lt": (0, k - 1), "ge": (k, top), "gt": (k + 1, top)}[relation] + (reading,)


def _binomial_probability(n: int, p: Fraction, low: int, high: int) -> Fraction:
    return sum((comb(n, r) * p**r * (1 - p) ** (n - r) for r in range(max(low, 0), min(high, n) + 1)), Fraction(0))


def binomial_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(26):
        n = rng.randint(5, 40)
        p_text = rng.choice(PROBABILITIES)
        p = Fraction(p_text)
        relation = RELATIONS[i % len(RELATIONS)]
        k = rng.randint(1, n - 1)
        k2 = rng.randint(k, n)
        low, high, reading = _interval(relation, k, k2, n)
        top = n if high is None else high
        total = _binomial_probability(n, p, low, top)
        args, sf = _with_sf(rng, {"task": "binomial", "n": n, "p": p_text, "relation": relation, "k": k}
                            | ({"k2": k2} if relation == "between" else {}))  # fmt: skip
        expect = {"task": "binomial", "n": n, "p": _text(p), "event": reading,
                  "interval": [max(low, 0), min(top, n)] if max(low, 0) <= min(top, n) else None,
                  "probability": _number(total, sf, _text(total)), "mean": {"text": _text(n * p)},
                  "variance": {"text": _text(n * p * (1 - p))}}  # fmt: skip
        cases.append(_case(f"stats_distribution_binomial_{i:03d}", args, expect))
    return cases


def _poisson_sum(lam: Fraction, low: int, high: int) -> Fraction:
    total, term = Fraction(0), Fraction(1)
    for r in range(high + 1):
        if r:
            term = term * lam / r
        if r >= low:
            total += term
    return total


def _poisson_probability(lam: Fraction, low: int, high: int | None) -> tuple[Decimal, str]:
    """The probability (60 digits) and its exact form, written as SymPy writes e^(-lambda) times a rational."""
    e = sp.exp(-sp.Rational(lam.numerator, lam.denominator))
    with localcontext() as ctx:
        ctx.prec = DIGITS + 20
        if high is None:
            below = _poisson_sum(lam, 0, low - 1) if low > 0 else Fraction(0)
            value = 1 - _decimal(below) / _exp(lam)
            exact = 1 - e * sp.Rational(below.numerator, below.denominator)
        else:
            inside = _poisson_sum(lam, low, high) if low <= high else Fraction(0)
            value = _decimal(inside) / _exp(lam)
            exact = e * sp.Rational(inside.numerator, inside.denominator)
    return value, sp.sstr(exact)


LAMBDAS = ["2", "3.5", "1.2", "4", "6", "0.8", "5.5", "2.5", "10", "7"]


def poisson_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(20):
        lam_text = rng.choice(LAMBDAS)
        lam = Fraction(lam_text)
        relation = RELATIONS[i % len(RELATIONS)]
        k = rng.randint(1, int(lam) + 6)
        k2 = k + rng.randint(0, 5)
        low, high, reading = _interval(relation, k, k2, None)
        value, exact = _poisson_probability(lam, low, high)
        args, sf = _with_sf(rng, {"task": "poisson", "lambda": lam_text, "relation": relation, "k": k}
                            | ({"k2": k2} if relation == "between" else {}))  # fmt: skip
        expect = {"task": "poisson", "lambda": _text(lam), "event": reading, "probability": _number(value, sf, exact),
                  "mean": {"text": _text(lam)}, "variance": {"text": _text(lam)}}  # fmt: skip
        cases.append(_case(f"stats_distribution_poisson_{i:03d}", args, expect))
    return cases


# --- the normal distribution ---------------------------------------------------------------------------------------


def normal_probability_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(24):
        mean = Fraction(rng.randint(10, 200))
        sd = Fraction(rng.choice([2, 4, 5, 8, 10, 12, 15, 20]))
        tables = i % 3 == 2
        relation = ["lt", "gt", "between", "le", "ge"][i % 5]
        z = Fraction(rng.randint(-250, 250), 100)
        x = mean + z * sd
        args: dict[str, Any] = {
            "task": "normal",
            "mean": _arg(mean),
            "sd": _arg(sd),
            "relation": relation,
            "x": _arg(x),
        }
        cdf = _phi_table if tables else _phi
        if relation == "between":
            z2 = z + Fraction(rng.randint(20, 300), 100)
            x2 = mean + z2 * sd
            args["x2"] = _arg(x2)
            value: Fraction | Decimal = _decimal(cdf(z2)) - _decimal(cdf(z))
            reading = f"P({_text(x)} < X < {_text(x2)})"
            zs: Any = [{"text": _text(_dp(_decimal(z), 2) if tables else z)},
                       {"text": _text(_dp(_decimal(z2), 2) if tables else z2)}]  # fmt: skip
        else:
            below = relation in ("lt", "le")
            value = _decimal(cdf(z)) if below else 1 - _decimal(cdf(z))
            reading = f"P(X {SYMBOLS[relation]} {_text(x)})"
            zs = {"text": _text(_dp(_decimal(z), 2) if tables else z)}
        if tables:
            args["normal_values"] = "tables"
        args, sf = _with_sf(rng, args)
        probability = _number(value, sf)
        if tables:  # a table reading is exact
            probability["text"] = _text(Fraction(value) if isinstance(value, Decimal) else value)
        expect = {"task": "normal", "event": reading, "z": zs, "probability": probability}
        cases.append(_case(f"stats_distribution_normal_{i:03d}", args, expect))
    return cases


def normal_inverse_cases(rng: random.Random) -> list[Case]:
    cases = []
    points = sorted(PERCENTAGE_POINTS - {Fraction(1, 2)})
    for i in range(24):
        kind = ["value", "value", "mean", "sd", "mean_and_sd", "value"][i % 6]
        tables = i % 4 == 3
        mean = Fraction(rng.randint(20, 120))
        sd = Fraction(rng.choice([3, 4, 5, 6, 8, 10, 12, 25]))
        p = rng.choice(points) if tables or rng.random() < 0.5 else Fraction(rng.randint(2, 98), 100)
        tail = rng.choice(["below", "above"])
        q = p if tail == "below" else 1 - p
        z: Fraction | Decimal = _z_table(q) if tables else _phi_inverse(q)
        extra = {"normal_values": "tables"} if tables else {}
        if kind == "value":
            if i % 12 == 5:
                tail = "central"
                z = _z_table((1 + p) / 2) if tables else _phi_inverse((1 + p) / 2)
            args = {"task": "normal", "find": "value", "mean": _arg(mean), "sd": _arg(sd), "probability": _arg(p),
                    "tail": tail, **extra}  # fmt: skip
            args, sf = _with_sf(rng, args)
            dz = _decimal(z) if isinstance(z, Fraction) else z
            if tail == "central":
                expect: dict[str, Any] = {"lower": _number(_decimal(mean) - dz * _decimal(sd), sf),
                                          "upper": _number(_decimal(mean) + dz * _decimal(sd), sf)}  # fmt: skip
            else:
                expect = {"x": _number(_decimal(mean) + dz * _decimal(sd), sf)}
            if tables:
                assert isinstance(z, Fraction)
                expect["z"] = {"text": _text(z)}
                if tail != "central":
                    expect["x"]["text"] = _text(mean + z * sd)
        elif kind == "mean":
            # Chosen mean and sd; x is the value a table z gives exactly, or a rounded x for the calculator.
            x = mean + (z if isinstance(z, Fraction) else _dp(z, 2)) * sd
            args = {"task": "normal", "find": "mean", "sd": _arg(sd), "x": _arg(x), "probability": _arg(p),
                    "tail": tail, **extra}  # fmt: skip
            args, sf = _with_sf(rng, args)
            dz = _decimal(z) if isinstance(z, Fraction) else z
            expect = {"mean": _number(_decimal(x) - dz * _decimal(sd), sf)}
            if tables:
                expect["mean"]["text"] = _text(mean)
        elif kind == "sd":
            if abs(_decimal(z) if isinstance(z, Fraction) else z) < Decimal("0.01"):
                p, tail, q = Fraction(1, 10), "above", Fraction(9, 10)
                z = _z_table(q) if tables else _phi_inverse(q)
            x = mean + (z if isinstance(z, Fraction) else _dp(z, 2)) * sd
            args = {"task": "normal", "find": "sd", "mean": _arg(mean), "x": _arg(x), "probability": _arg(p),
                    "tail": tail, **extra}  # fmt: skip
            args, sf = _with_sf(rng, args)
            dz = _decimal(z) if isinstance(z, Fraction) else z
            expect = {"sd": _number((_decimal(x) - _decimal(mean)) / dz, sf)}
            if tables:
                expect["sd"]["text"] = _text(sd)
        else:
            p1, p2 = rng.choice(points), rng.choice(points)
            q1, q2 = p1, 1 - p2  # P(X < x1) = p1 and P(X > x2) = p2
            z1 = _z_table(q1) if tables else _phi_inverse(q1)
            z2 = _z_table(q2) if tables else _phi_inverse(q2)
            r1, r2 = (z1, z2) if tables else (_dp(z1, 2), _dp(z2, 2))
            x1, x2 = mean + r1 * sd, mean + r2 * sd
            args = {"task": "normal", "find": "mean_and_sd", "conditions": [
                {"x": _arg(x1), "probability": _arg(p1), "tail": "below"},
                {"x": _arg(x2), "probability": _arg(p2), "tail": "above"}], **extra}  # fmt: skip
            args, sf = _with_sf(rng, args)
            d1, d2 = (_decimal(z1), _decimal(z2)) if tables else (z1, z2)
            with localcontext() as ctx:
                ctx.prec = DIGITS
                sigma = (_decimal(x2) - _decimal(x1)) / (d2 - d1)
                mu = _decimal(x1) - d1 * sigma
            expect = {"mean": _number(mu, sf), "sd": _number(sigma, sf)}
            if tables:
                expect["mean"]["text"], expect["sd"]["text"] = _text(mean), _text(sd)
        expect = {"task": "normal", "find": kind, **expect}
        cases.append(_case(f"stats_distribution_normal_inverse_{i:03d}", args, expect))
    return cases


# --- hypothesis tests -------------------------------------------------------------------------------------------------


def _discrete_test(n: int | None, p: Fraction | None, lam: Fraction | None, alternative: str, alpha: Fraction,
                   x: int) -> dict[str, Any]:  # fmt: skip
    """Critical region, actual significance level and decision, from tail sums built here."""
    tail = alpha / 2 if alternative == "two_sided" else alpha

    def at_most(c: int) -> Decimal:
        if c < 0:
            return Decimal(0)
        if n is not None and p is not None:
            return _decimal(_binomial_probability(n, p, 0, c))
        assert lam is not None
        with localcontext() as ctx:
            ctx.prec = DIGITS + 20
            return _decimal(_poisson_sum(lam, 0, c)) / _exp(lam)

    def at_least(c: int) -> Decimal:
        if n is not None and c > n:
            return Decimal(0)
        with localcontext() as ctx:
            ctx.prec = DIGITS + 20
            return 1 - at_most(c - 1)

    t = _decimal(tail)
    region: dict[str, Any] = {}
    actual = Decimal(0)
    if alternative in ("less", "two_sided"):
        c = -1
        while at_most(c + 1) <= t:
            c += 1
        region["lower"] = None if c < 0 else {"x_max": c, "probability": at_most(c)}
        actual += at_most(c) if c >= 0 else 0
    if alternative in ("greater", "two_sided"):
        top = n if n is not None else 4 * int(lam or 0) + 60
        c = top + 1
        while c - 1 >= 0 and at_least(c - 1) <= t:
            c -= 1
        region["upper"] = None if c > top else {"x_min": c, "probability": at_least(c)}
        actual += at_least(c) if c <= top else 0
    mean = n * p if n is not None and p is not None else lam
    assert mean is not None
    lower = alternative == "less" or (alternative == "two_sided" and x < mean)
    tail_probability = at_most(x) if lower else at_least(x)
    return {"region": region, "actual": actual, "lower": lower, "tail_probability": tail_probability,
            "reject": tail_probability <= t, "compare_with": tail}  # fmt: skip


def _region_expect(region: dict[str, Any], sf: int) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for side, held in region.items():
        if held is None:
            out[side] = None
        else:
            key = "x_max" if side == "lower" else "x_min"
            out[side] = {key: held[key], "probability": {"decimal": _sf(held["probability"], sf)}}
    return out


def discrete_test_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(24):
        binomial = i % 3 != 2
        alternative = ["less", "greater", "two_sided"][i % 3 if binomial else (i // 3) % 3]
        alpha_text = rng.choice(["0.05", "0.1", "0.01", "5%", "2.5%", "10%"])
        alpha = Fraction(alpha_text[:-1]) / 100 if alpha_text.endswith("%") else Fraction(alpha_text)
        if binomial:
            n = rng.randint(8, 50)
            p_text = rng.choice(["0.3", "0.25", "0.4", "0.5", "0.2", "1/6", "0.35", "0.6"])
            p = Fraction(p_text)
            x = rng.randint(0, n)
            found = _discrete_test(n, p, None, alternative, alpha, x)
            args: dict[str, Any] = {"task": "hypothesis_test", "test": "binomial", "n": n, "p": p_text}
            h0 = f"p = {_text(p)}"
        else:
            lam_text = rng.choice(["2", "3", "4.5", "6", "8", "1.5", "10"])
            lam = Fraction(lam_text)
            x = rng.randint(0, 2 * int(lam) + 6)
            found = _discrete_test(None, None, lam, alternative, alpha, x)
            args = {"task": "hypothesis_test", "test": "poisson", "lambda": lam_text}
            h0 = f"lambda = {_text(lam)}"
        args |= {"alternative": alternative, "significance_level": alpha_text, "observed": x}
        args, sf = _with_sf(rng, args)
        expect = {"task": "hypothesis_test", "h0": h0, "significance_level": _text(alpha),
                  "critical_region": _region_expect(found["region"], sf),
                  "actual_significance_level": {"decimal": _sf(found["actual"], sf)}, "observed": x,
                  "tail": "lower" if found["lower"] else "upper",
                  "tail_probability": {"decimal": _sf(found["tail_probability"], sf)},
                  "compare_with": _text(found["compare_with"]), "in_critical_region": found["reject"],
                  "conclusion": "reject_h0" if found["reject"] else "do_not_reject_h0"}  # fmt: skip
        cases.append(_case(f"stats_distribution_test_discrete_{i:03d}", args, expect))
    return cases


def normal_mean_test_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(10):
        mu0 = Fraction(rng.randint(20, 500))
        sd = Fraction(rng.choice([2, 3, 4, 5, 6, 8, 10, 12]))
        root = rng.choice([1, 2, 3, 4, 5, 6, 8, 10])
        n = root * root
        alternative = ["less", "greater", "two_sided"][i % 3]
        alpha = rng.choice([Fraction(1, 20), Fraction(1, 100), Fraction(1, 10)])
        z = Fraction(rng.randint(5, 300), 100) * (-1 if alternative == "less" or (i % 2 and i % 3 == 2) else 1)
        se = sd / root
        xbar = mu0 + z * se
        tail = alpha / 2 if alternative == "two_sided" else alpha
        critical = _phi_inverse(1 - tail)
        lower = alternative == "less" or (alternative == "two_sided" and z < 0)
        p_value = _phi(z) if lower else 1 - _phi(z)
        reject = (-_decimal(z) >= critical) if lower else (_decimal(z) >= critical)
        args, sf = _with_sf(rng, {"task": "hypothesis_test", "test": "normal_mean", "mean": _arg(mu0), "sd": _arg(sd),
                                  "n": n, "sample_mean": _arg(xbar), "alternative": alternative,
                                  "significance_level": _arg(alpha)})  # fmt: skip
        expect = {"task": "hypothesis_test", "test": "normal_mean", "standard_error": {"text": _text(se)},
                  "critical_z": _number(critical, sf), "z": {"text": _text(z)},
                  "tail_probability": _number(p_value, sf), "compare_with": _text(tail),
                  "in_critical_region": reject,
                  "conclusion": "reject_h0" if reject else "do_not_reject_h0"}  # fmt: skip
        cases.append(_case(f"stats_distribution_test_normal_{i:03d}", args, expect))
    return cases


def _r_critical_even(n: int, tail: Fraction) -> Fraction:
    """For even n: the r with P(R >= r) = tail under rho = 0, where R has density proportional to (1 - s^2)^m,
    m = (n - 4) / 2; the polynomial integrates exactly and r is found by bisection in Fractions."""
    m = (n - 4) // 2
    coefficients = [Fraction(comb(m, j) * (-1) ** j, 2 * j + 1) for j in range(m + 1)]

    def antiderivative(s: Fraction) -> Fraction:
        return sum((c * s ** (2 * j + 1) for j, c in enumerate(coefficients)), Fraction(0))

    whole = 2 * antiderivative(Fraction(1))
    low, high = Fraction(0), Fraction(1)
    for _ in range(64):
        middle = (low + high) / 2
        if (antiderivative(Fraction(1)) - antiderivative(middle)) / whole > tail:
            low = middle
        else:
            high = middle
    return (low + high) / 2


def correlation_test_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(12):
        n = rng.choice([4, 6, 8, 10, 12, 14, 16, 20, 30])
        alternative = ["greater", "less", "two_sided"][i % 3]
        alpha = rng.choice([Fraction(1, 20), Fraction(1, 40), Fraction(1, 100), Fraction(1, 10)])
        tail = alpha / 2 if alternative == "two_sided" else alpha
        critical = _r_critical_even(n, tail)
        r = Fraction(rng.randint(5, 99), 100) * (-1 if alternative == "less" or (alternative == "two_sided" and i % 2)
                                                  else 1)  # fmt: skip
        given = i % 4 == 3  # the table value given with the call
        args, sf = _with_sf(rng, {"task": "hypothesis_test", "test": "pmcc", "r": _arg(r), "n": n,
                                  "alternative": alternative, "significance_level": _arg(alpha)})  # fmt: skip
        if given:
            critical = _dp(_decimal(critical), 4)
            args["critical_value"] = _arg(critical)
        if alternative == "greater":
            reject = r >= critical
        elif alternative == "less":
            reject = r <= -critical
        else:
            reject = abs(r) >= critical
        expect = {"task": "hypothesis_test", "test": "pmcc", "n": n, "h1": {"greater": "rho > 0", "less": "rho < 0",
                  "two_sided": "rho != 0"}[alternative], "critical_value": {"decimal": _sf(critical, sf)},
                  "critical_value_source": "item" if given else "computed", "in_critical_region": reject,
                  "conclusion": "reject_h0" if reject else "do_not_reject_h0"}  # fmt: skip
        cases.append(_case(f"stats_distribution_test_pmcc_{i:03d}", args, expect))
    return cases


# --- correlation and regression --------------------------------------------------------------------------------------


def _symmetric_design(rng: random.Random) -> list[tuple[Fraction, Fraction]]:
    """Explanatory values in pairs c - d, c + d (and maybe c itself) with residuals equal within each pair and summing
    to zero: the residuals are then orthogonal to 1 and to the explanatory variable, so least squares returns the
    chosen line exactly. Returns (value, residual) pairs, shuffled."""
    pairs = rng.randint(2, 5)
    centre = Fraction(rng.randint(8, 30))
    offsets = rng.sample(range(1, 8), pairs)
    scale = Fraction(1, rng.choice([1, 2, 4, 5]))
    middle = rng.random() < 0.5
    residuals = [Fraction(rng.randint(-4, 4)) * scale for _ in range(pairs - 1)]
    centre_residual = Fraction(2 * rng.randint(-2, 2)) * scale if middle else Fraction(0)
    residuals.append(-(2 * sum(residuals, Fraction(0)) + centre_residual) / 2)
    design = [(centre + sign * d, r) for d, r in zip(offsets, residuals, strict=True) for sign in (-1, 1)]
    if middle:
        design.append((centre, centre_residual))
    rng.shuffle(design)
    return design


def _sums(x: list[Fraction], y: list[Fraction]) -> tuple[Fraction, Fraction, Fraction]:
    n = len(x)
    sxx = sum((a * a for a in x), Fraction(0)) - sum(x) ** 2 / n
    syy = sum((b * b for b in y), Fraction(0)) - sum(y) ** 2 / n
    sxy = sum((a * b for a, b in zip(x, y, strict=True)), Fraction(0)) - sum(x) * sum(y) / n
    return sxx, syy, sxy


def _r(sxx: Fraction, syy: Fraction, sxy: Fraction) -> Decimal:
    with localcontext() as ctx:
        ctx.prec = DIGITS
        size = (_decimal(sxy * sxy / (sxx * syy))).sqrt()
        return size if sxy >= 0 else -size


def _ranks(values: list[Fraction]) -> list[Fraction]:
    """Rank 1 for the smallest; a tied value takes the mean of the ranks it spans: (below + 1 + below + equal) / 2."""
    return [Fraction(2 * sum(1 for w in values if w < v) + sum(1 for w in values if w == v) + 1, 2) for v in values]


def regression_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(18):
        on_x = i % 3 != 2
        design = _symmetric_design(rng)
        n = len(design)
        ex = [v for v, _ in design]
        gradient = Fraction(rng.randint(-30, 30), rng.choice([1, 2, 4, 5, 10]))
        if gradient == 0:
            gradient = Fraction(3, 2)
        intercept = Fraction(rng.randint(-50, 50), rng.choice([1, 2, 5]))
        response = [intercept + gradient * a + e for a, e in design]
        x, y = (ex, response) if on_x else (response, ex)
        predict = [Fraction(rng.randint(int(min(ex)), int(max(ex)))), max(ex) + rng.randint(1, 10)]
        sxx, syy, sxy = _sums(x, y)
        use_sums = i % 4 == 1
        args: dict[str, Any] = {"task": "regression", "line": "y_on_x" if on_x else "x_on_y"}
        if use_sums:
            args["sums"] = {"n": n, "sum_x": _arg(sum(x, Fraction(0))), "sum_y": _arg(sum(y, Fraction(0))),
                            "sum_x2": _arg(sum((a * a for a in x), Fraction(0))),
                            "sum_y2": _arg(sum((b * b for b in y), Fraction(0))),
                            "sum_xy": _arg(sum((a * b for a, b in zip(x, y, strict=True)), Fraction(0)))}  # fmt: skip
            args["explanatory_range"] = [_arg(min(ex)), _arg(max(ex))]
        else:
            args["x_values"], args["y_values"] = [_arg(a) for a in x], [_arg(b) for b in y]
        args["predict"] = [_arg(v) for v in predict]
        args, sf = _with_sf(rng, args)
        names = ("y", "x") if on_x else ("x", "y")
        line = sp.Rational(intercept.numerator, intercept.denominator) + sp.Rational(
            gradient.numerator, gradient.denominator
        ) * sp.Symbol(names[1])
        equation = f"{names[0]} = {sp.sstr(line)}"
        estimates = [_text(intercept + gradient * v) for v in predict]
        expect = {"task": "regression", "n": n, "equation": equation, "a": _number(intercept, sf, _text(intercept)),
                  "b": _number(gradient, sf, _text(gradient)), "r": {"decimal": _sf(_r(sxx, syy, sxy), sf)},
                  "predictions": [{"at": _text(predict[0]), "estimate": {"text": estimates[0]},
                                   "reliability": "interpolation"},
                                  {"at": _text(predict[1]), "estimate": {"text": estimates[1]},
                                   "reliability": "extrapolation"}]}  # fmt: skip
        cases.append(_case(f"stats_distribution_regression_{i:03d}", args, expect))
    return cases


def correlation_cases(rng: random.Random) -> list[Case]:
    cases = []
    for i in range(16):
        n = rng.randint(5, 12)
        ties = i % 4 == 3
        x = [Fraction(v) for v in sorted(rng.sample(range(10, 90), n))]
        order = list(range(n))
        rng.shuffle(order)
        y = [Fraction(50 + 3 * order[j] + rng.randint(0, 2)) for j in range(n)]  # y's ranks follow `order`
        if ties:
            j = rng.randint(0, n - 2)
            x[j + 1] = x[j]
            t = order.index(0)
            y[t] = y[order.index(1)]
        args: dict[str, Any] = {
            "task": "correlation",
            "x_values": [_arg(a) for a in x],
            "y_values": [_arg(b) for b in y],
        }
        if ties:
            args["tie_method"] = "formula"
        args, sf = _with_sf(rng, args)
        sxx, syy, sxy = _sums(x, y)
        rx, ry = _ranks(x), _ranks(y)
        d2 = sum(((a - b) ** 2 for a, b in zip(rx, ry, strict=True)), Fraction(0))
        rs = 1 - 6 * d2 / (n * (n * n - 1))
        expect = {"task": "correlation", "n": n, "sxx": {"text": _text(sxx)}, "syy": {"text": _text(syy)},
                  "sxy": {"text": _text(sxy)}, "r": {"decimal": _sf(_r(sxx, syy, sxy), sf)},
                  "spearman": {"rs": _number(rs, sf, _text(rs)), "ranks_x": [_text(r) for r in rx],
                               "ranks_y": [_text(r) for r in ry], "sum_d2": _text(d2), "ties": ties,
                               "tie_method": "formula"}}  # fmt: skip
        cases.append(_case(f"stats_distribution_correlation_{i:03d}", args, expect))
    return cases


# --- hand cases: textbook-style examples, unknowns and refusals ------------------------------------------------------


def hand_cases() -> list[Case]:
    def hand(name: str, args: dict[str, Any], expect: dict[str, Any]) -> Case:
        return _case(f"stats_distribution_hand_{name}", args, expect, "hand")

    tables = {"normal_values": "tables"}
    pmcc = {"task": "hypothesis_test", "test": "pmcc"}
    cases = [
        # Cumulative binomial table: B(20, 0.3), P(X <= 3) = 0.1071; B(10, 0.5), P(X = 5) = 63/256.
        hand(
            "binomial_table",
            {"task": "binomial", "n": 20, "p": "0.3", "relation": "le", "k": 3, "sf": 4},
            {"probability": {"decimal": "0.1071"}, "mean": {"text": "6"}, "variance": {"text": "21/5"}},
        ),
        hand(
            "binomial_half",
            {"task": "binomial", "n": 10, "p": "0.5", "relation": "eq", "k": 5},
            {"probability": {"text": "63/256", "decimal": "0.2461"}},
        ),
        # A fair die thrown 12 times: P(at least two sixes) = 1 - (5/6)^12 - 12 (1/6)(5/6)^11.
        hand(
            "binomial_dice",
            {"task": "binomial", "n": 12, "p": "1/6", "relation": "ge", "k": 2, "sf": 4},
            {
                "probability": {
                    "text": _text(1 - Fraction(5, 6) ** 12 - 12 * Fraction(1, 6) * Fraction(5, 6) ** 11),
                    "decimal": "0.6187",
                }
            },
        ),
        # Cumulative Poisson table: Po(2), P(X <= 3) = 0.8571; Po(4.5), P(X = 4) = 0.1898.
        hand(
            "poisson_table",
            {"task": "poisson", "lambda": 2, "relation": "le", "k": 3, "sf": 4},
            {"probability": {"text": "19*exp(-2)/3", "decimal": "0.8571"}},
        ),
        hand(
            "poisson_point",
            {"task": "poisson", "lambda": "4.5", "relation": "eq", "k": 4, "sf": 4},
            {"probability": {"decimal": "0.1898"}},
        ),
        # N(50, 4^2): P(X < 53) = Phi(0.75) = 0.7734 from the table; Phi(1.96) = 0.9750.
        hand(
            "normal_table",
            {"task": "normal", "mean": 50, "variance": 16, "relation": "lt", "x": 53, **tables},
            {"z": {"text": "3/4"}, "probability": {"text": "3867/5000", "decimal": "0.7734"}},
        ),
        hand(
            "normal_196",
            {"task": "normal", "mean": 0, "sd": 1, "relation": "lt", "x": "1.96", "sf": 4},
            {"probability": {"decimal": "0.9750"}},
        ),
        hand("normal_z", {"task": "normal", "find": "z", "mean": 100, "sd": 15, "x": 130}, {"z": {"text": "2"}}),
        # Percentage points: the upper 5% point is 1.6449 in the table, 1.645 (4 s.f.) by calculator.
        hand(
            "percentage_point_table",
            {"task": "normal", "find": "value", "mean": 0, "sd": 1, "probability": "0.05", "tail": "above", **tables},
            {"x": {"text": "16449/10000"}},
        ),
        hand(
            "percentage_point",
            {"task": "normal", "find": "value", "mean": 0, "sd": 1, "probability": "0.025", "tail": "above", "sf": 4},
            {"x": {"decimal": "1.960"}},
        ),
        # Two-tailed binomial test, H0: p = 0.3, n = 20, 5%: critical region X <= 1 or X >= 11.
        hand(
            "binomial_test_region",
            {
                "task": "hypothesis_test",
                "test": "binomial",
                "n": 20,
                "p": "0.3",
                "alternative": "two_sided",
                "significance_level": "5%",
                "sf": 4,
            },
            {
                "critical_region": {
                    "lower": {"x_max": 1, "probability": {"decimal": "0.007637"}},
                    "upper": {"x_min": 11, "probability": {"decimal": "0.01714"}},
                },
                "actual_significance_level": {"decimal": "0.02478"},
            },
        ),
        # Poisson test, H0: lambda = 6 against lambda > 6 at 5%: critical region X >= 11, P = 0.0426.
        hand(
            "poisson_test_region",
            {
                "task": "hypothesis_test",
                "test": "poisson",
                "lambda": 6,
                "alternative": "greater",
                "significance_level": "0.05",
                "observed": 11,
                "sf": 3,
            },
            {
                "critical_region": {"upper": {"x_min": 11, "probability": {"decimal": "0.0426"}}},
                "conclusion": "reject_h0",
            },
        ),
        # Lower tail with no critical region: P(X = 0) = 0.7^5 = 0.168 > 0.05.
        hand(
            "binomial_test_empty",
            {
                "task": "hypothesis_test",
                "test": "binomial",
                "n": 5,
                "p": "0.3",
                "alternative": "less",
                "significance_level": "0.05",
                "observed": 0,
            },
            {"critical_region": {"lower": None}, "conclusion": "do_not_reject_h0"},
        ),
        # A known-sd normal test: x bar = 51.8 from 16 values, sigma = 4, H1: mu > 50 at 5%: z = 1.8 > 1.6449.
        hand(
            "normal_mean_test",
            {
                "task": "hypothesis_test",
                "test": "normal_mean",
                "mean": 50,
                "sd": 4,
                "n": 16,
                "sample_mean": "51.8",
                "alternative": "greater",
                "significance_level": "0.05",
                **tables,
            },
            {"z": {"text": "9/5"}, "critical_z": {"text": "16449/10000"}, "conclusion": "reject_h0"},
        ),
        # PMCC critical values as printed (4 d.p.), one-tail levels.
        *[
            hand(
                f"pmcc_table_n{n}_{_text(a).replace('/', 'over')}",
                {**pmcc, "r": "0.5", "n": n, "alternative": "greater", "significance_level": _arg(a), "sf": 4},
                {"critical_value": {"decimal": value}},
            )
            for n, a, value in [
                (5, Fraction(1, 20), "0.8054"),
                (7, Fraction(1, 40), "0.7545"),
                (9, Fraction(1, 100), "0.7498"),
                (11, Fraction(1, 20), "0.5214"),
                (15, Fraction(1, 20), "0.4409"),
                (13, Fraction(1, 40), "0.5529"),
                (10, Fraction(1, 20), "0.5494"),
                (12, Fraction(1, 100), "0.6581"),
            ]
        ],
        hand(
            "spearman_table",
            {
                "task": "hypothesis_test",
                "test": "spearman",
                "r": "0.75",
                "n": 8,
                "alternative": "greater",
                "significance_level": "0.05",
                "critical_value": "0.6429",
            },
            {"critical_value_source": "item", "conclusion": "reject_h0"},
        ),
        # Spearman without ties: ranks (1..5) against (2, 1, 4, 3, 5): sum d^2 = 4, rs = 1 - 24/120 = 4/5.
        hand(
            "spearman_no_ties",
            {
                "task": "correlation",
                "measure": "spearman",
                "x_values": [3, 5, 7, 9, 11],
                "y_values": [20, 10, 40, 30, 50],
            },
            {"spearman": {"rs": {"text": "4/5"}, "sum_d2": "4", "ties": False}},
        ),
        # Tied ranks: x = 1, 2, 2, 4, 5 takes ranks 1, 2.5, 2.5, 4, 5; the PMCC of the ranks.
        hand(
            "spearman_ties",
            {
                "task": "correlation",
                "measure": "spearman",
                "x_values": [1, 2, 2, 4, 5],
                "y_values": [1, 2, 3, 4, 5],
                "tie_method": "pmcc_of_ranks",
            },
            {
                "spearman": {
                    "ranks_x": ["1", "5/2", "5/2", "4", "5"],
                    "rs": {"decimal": "0.9747"},
                    "tie_method": "pmcc_of_ranks",
                }
            },
        ),  # rs = 9.5 / sqrt(9.5 x 10) = sqrt(0.95)
        # Regression from summary statistics: n = 10, Sxx = 82.5 and Sxy = 60, so b = 8/11 and a = 12 - 5.5 b = 8.
        hand(
            "regression_sums",
            {"task": "regression", "sums": {"n": 10, "sum_x": 55, "sum_y": 120, "sum_x2": 385, "sum_xy": 720}},
            {"b": {"text": "8/11"}, "a": {"text": "8"}, "equation": "y = 8*x/11 + 8"},
        ),
        hand(
            "regression_unknown_range",
            {
                "task": "regression",
                "sums": {"n": 10, "sum_x": 55, "sum_y": 120, "sum_x2": 385, "sum_xy": 720},
                "predict": [4],
            },
            {"predictions": [{"at": "4", "estimate": {"text": "120/11"}, "reliability": "unknown_range"}]},
        ),
        # A variance that is not a square: N(20, 7), P(X > 23) = 1 - Phi(3 / sqrt 7) = 0.1284.
        hand(
            "normal_surd_sd",
            {"task": "normal", "mean": 20, "variance": 7, "relation": "gt", "x": 23, "sf": 4},
            {"sd": "sqrt(7)", "z": {"text": "3*sqrt(7)/7"}, "probability": {"decimal": "0.1284"}},
        ),
        # Undetermined input: unknown with its reason, never a number.
        hand(
            "unknown_sd",
            {"task": "normal", "find": "sd", "mean": 50, "x": 50, "probability": "0.5", "tail": "below"},
            {"status": "unknown", "reason": "underdetermined"},
        ),
        hand(
            "unknown_spearman",
            {
                "task": "hypothesis_test",
                "test": "spearman",
                "r": "0.6",
                "n": 10,
                "alternative": "greater",
                "significance_level": "0.05",
            },
            {"status": "unknown", "reason": "critical_value_needed"},
        ),
        hand(
            "unknown_conditions",
            {
                "task": "normal",
                "find": "mean_and_sd",
                "conditions": [
                    {"x": 40, "probability": "0.1", "tail": "below"},
                    {"x": 40, "probability": "0.9", "tail": "above"},
                ],
            },
            {"status": "unknown", "reason": "underdetermined"},
        ),
    ]
    errors = [
        ("p_above_one", {"task": "binomial", "n": 10, "p": "1.2", "relation": "le", "k": 3}),
        ("lambda_zero", {"task": "poisson", "lambda": 0, "relation": "eq", "k": 1}),
        ("k_not_whole", {"task": "poisson", "lambda": 2, "relation": "le", "k": "2.5"}),
        ("between_reversed", {"task": "binomial", "n": 10, "p": "0.4", "relation": "between", "k": 6, "k2": 3}),
        ("sd_negative", {"task": "normal", "mean": 10, "sd": -2, "relation": "lt", "x": 12}),
        (
            "sd_opposite_side",
            {"task": "normal", "find": "sd", "mean": 50, "x": 60, "probability": "0.7", "tail": "above"},
        ),
        ("variance_zero", {"task": "normal", "mean": 10, "variance": 0, "relation": "lt", "x": 12}),
        (
            "conditions_contradict",
            {
                "task": "normal",
                "find": "mean_and_sd",
                "conditions": [
                    {"x": 40, "probability": "0.1", "tail": "below"},
                    {"x": 45, "probability": "0.9", "tail": "above"},
                ],
            },
        ),
        (
            "level_too_large",
            {
                "task": "hypothesis_test",
                "test": "binomial",
                "n": 10,
                "p": "0.5",
                "alternative": "less",
                "significance_level": "0.7",
            },
        ),
        (
            "level_percent_ambiguous",
            {
                "task": "hypothesis_test",
                "test": "binomial",
                "n": 10,
                "p": "0.5",
                "alternative": "less",
                "significance_level": 5,
            },
        ),
        (
            "observed_above_n",
            {
                "task": "hypothesis_test",
                "test": "binomial",
                "n": 10,
                "p": "0.5",
                "alternative": "greater",
                "significance_level": "0.05",
                "observed": 11,
            },
        ),
        ("r_above_one", {**pmcc, "r": "1.2", "n": 10, "alternative": "greater", "significance_level": "0.05"}),
        (
            "sums_inconsistent",
            {
                "task": "correlation",
                "sums": {"n": 5, "sum_x": 15, "sum_y": 15, "sum_x2": 55, "sum_y2": 46, "sum_xy": 60},
            },
        ),
        ("pairs_unequal", {"task": "correlation", "x_values": [1, 2, 3], "y_values": [1, 2]}),
        ("x_all_equal", {"task": "regression", "x_values": [2, 2, 2], "y_values": [1, 2, 3]}),
        (
            "spearman_from_sums",
            {
                "task": "correlation",
                "measure": "spearman",
                "sums": {"n": 5, "sum_x": 15, "sum_y": 15, "sum_x2": 55, "sum_y2": 55, "sum_xy": 50},
            },
        ),
    ]
    return cases + [hand(name, args, {"error": DOMAIN_ERROR}) for name, args in errors]


def statistics_cases(rng: random.Random) -> list[Case]:
    cases = (binomial_cases(rng) + poisson_cases(rng) + normal_probability_cases(rng) + normal_inverse_cases(rng)
             + discrete_test_cases(rng) + normal_mean_test_cases(rng) + correlation_test_cases(rng)
             + correlation_cases(rng) + regression_cases(rng) + hand_cases())  # fmt: skip
    return _errors_last(cases)


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The VER-30 statistics set by name (stage S3)."""
    return {"stats_distribution": statistics_cases(rng)}
