"""Golden sets for the physics checkers (VER-16, VER-17; M12.b; A level mechanics VER-31, M26.a), built by
construction like golden.py.

Expected answers come from the construction, never from the checkers: lens and mirror cases start from a chosen
object and image distance and derive the focal length; refraction cases from angles with known exact sines; circuits
from series and parallel combination rules applied to chosen resistances; projectiles from a chosen landing speed or
flight time, so every expected value is a hand-verifiable fraction. Every case is synthetic."""

from __future__ import annotations

import random
from fractions import Fraction
from typing import Any

import sympy as sp

SEED = 20261011
# Golden sets of S2 tools built early (the default stage in golden.py is S1).
STAGES = {"phys_optics": "S2", "phys_circuit": "S2", "phys_projectile": "S2"}


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> dict[str, Any]:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _errors_last(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expected refusals after the answered cases (the offline check runs each set's first cases end to end)."""
    return sorted(cases, key=lambda case: "error" in case["expect"])


def _text(value: Fraction | int) -> str:
    value = Fraction(value)
    return str(value.numerator) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _number(value: Fraction) -> int | str:
    """A terminating fraction as an argument: an integer, or a decimal string."""
    if value.denominator == 1:
        return int(value)
    text = f"{float(value):.10f}".rstrip("0")
    assert Fraction(text) == value, value
    return text


# --- phys_optics ------------------------------------------------------------------------------------------------

OPTIC_KIND = {"converging_lens": "lens", "diverging_lens": "lens", "concave_mirror": "mirror",
              "convex_mirror": "mirror", "plane_mirror": "mirror"}  # fmt: skip


def _signed(optic: str, convention: str, d_o: Fraction, d_i: Fraction, f: Fraction) -> dict[str, str]:
    """Distances with real positive (d_i > 0 real), mapped to the convention by its definition: cartesian measures
    along the incident light from the optic, so the object is negative and a mirror's real image and concave focus
    are negative too."""
    if convention == "real_is_positive":
        return {"object_distance": _text(d_o), "image_distance": _text(d_i), "focal_length": _text(f)}
    mirror = -1 if OPTIC_KIND[optic] == "mirror" else 1
    return {"object_distance": _text(-d_o), "image_distance": _text(mirror * d_i), "focal_length": _text(mirror * f)}


def _image_case(case_id: str, optic: str, convention: str, d_o: int, f: int, origin: str = "constructed"
                ) -> dict[str, Any]:  # fmt: skip
    """Object distance and real-is-positive focal length chosen first; d_i follows from 1/d_i = 1/f - 1/d_o."""
    d_i = 1 / (Fraction(1, f) - Fraction(1, d_o))
    magnification = abs(d_i) / d_o
    real = d_i > 0
    size = "same_size" if magnification == 1 else ("magnified" if magnification > 1 else "diminished")
    signed = _signed(optic, convention, Fraction(d_o), d_i, Fraction(f))
    expect = {
        "image": "formed",
        "object_distance": {"text": signed["object_distance"]},
        "image_distance": {"text": signed["image_distance"]},
        "focal_length": {"text": signed["focal_length"]},
        "magnification": {"text": _text(magnification)},
        "nature": {"type": "real" if real else "virtual", "orientation": "inverted" if real else "upright",
                   "size": size},
        "sign_convention": {"value": convention, "source": "pack"},
    }  # fmt: skip
    args = {"optic": optic, "focal_length": abs(f), "object_distance": d_o, "object_height": 2,
            "sign_convention": convention, "sign_convention_source": "pack"}  # fmt: skip
    return _case(case_id, args, expect, origin)


def optics_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases = []
    for convention in ("real_is_positive", "cartesian"):  # VER-16 acceptance: an object at 2f, in both conventions
        cases.append(_image_case(f"optics_doc_two_f_{convention}", "converging_lens", convention, 20, 10, "hand"))
    cases += [
        _case("optics_doc_at_focus", {"optic": "converging_lens", "focal_length": 10, "object_distance": 10,
              "sign_convention": "cartesian"}, {"image": "at_infinity"}, "hand"),
        _case("optics_doc_no_convention", {"optic": "converging_lens", "focal_length": 10, "object_distance": 20},
              {"status": "unknown", "reason": "convention_missing"}, "hand"),
        _case("optics_plane_mirror", {"optic": "plane_mirror", "object_distance": "7.5", "sign_convention":
              "real_is_positive"}, {"image_distance": {"text": "-15/2"}, "magnification": {"text": "1"},
              "nature": {"type": "virtual", "orientation": "upright", "size": "same_size"}}, "hand"),
        _case("optics_doc_snell", {"task": "refraction", "n1": 1, "angle1": 45, "angle2": 30},
              {"n2": {"text": sp.sstr(sp.sin(sp.pi / 4) / sp.sin(sp.pi / 6))}, "bends": "towards_normal"}, "hand"),
        _case("optics_snell_angle", {"task": "refraction", "n1": 1, "angle1": 60, "n2": 2},
              {"angle2": {"text": sp.sstr(sp.asin(sp.sqrt(3) / 4) * 180 / sp.pi)}}, "hand"),
        _case("optics_snell_back", {"task": "refraction", "n1": 2, "angle1": 30, "n2": 1},
              {"angle2": {"text": "90"}}, "hand"),
        _case("optics_doc_total_internal_reflection", {"task": "refraction", "n1": "1.5", "angle1": 60, "n2": 1},
              {"case": "total_internal_reflection"}, "hand"),
        _case("optics_doc_critical_angle", {"task": "critical_angle", "n1": 2}, {"critical_angle": {"text": "30"}},
              "hand"),
        _case("optics_critical_to_index", {"task": "critical_angle", "angle1": 45},
              {"n1": {"text": sp.sstr(1 / sp.sin(sp.pi / 4))}}, "hand"),
        _case("optics_critical_water_glass", {"task": "critical_angle", "n1": "1.5", "n2": "0.75"},
              {"critical_angle": {"text": "30"}}, "hand"),
        _case("optics_no_critical_angle", {"task": "critical_angle", "n1": 1, "n2": "1.5"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    # Exact sines: refraction from air into a medium of index sin(i)/sin(r).
    sines = {30: sp.Rational(1, 2), 45: sp.sqrt(2) / 2, 60: sp.sqrt(3) / 2}
    for i, (a1, a2) in enumerate([(45, 30), (60, 30), (60, 45)]):
        expected = sp.sstr(sines[a1] / sines[a2])
        args = {"task": "refraction", "n1": 1, "angle1": a1, "angle2": a2}
        cases.append(_case(f"optics_index_from_angles_{i}", args, {"n2": {"text": expected}}))
    conventions = ("real_is_positive", "cartesian")
    # (optic, focal length sign, object beyond F or inside it, count)
    groups = [
        ("converging_lens", 1, True, 24),
        ("converging_lens", 1, False, 16),
        ("diverging_lens", -1, True, 16),
        ("concave_mirror", 1, True, 16),
        ("concave_mirror", 1, False, 8),
        ("convex_mirror", -1, True, 16),
    ]
    for optic, sign, beyond, count in groups:
        for i in range(count):
            f = rng.randint(2, 30)
            d_o = rng.randint(f + 1, 3 * f) if beyond else rng.randint(1, f - 1)
            where = "beyond" if beyond else "inside"
            cases.append(_image_case(f"optics_{optic}_{where}_{i:03d}", optic, conventions[i % 2], d_o, sign * f))
    return _errors_last(cases)


# --- phys_circuit -----------------------------------------------------------------------------------------------


def _series(*rs: Fraction) -> Fraction:
    return sum(rs, Fraction(0))


def _parallel(*rs: Fraction) -> Fraction:
    return 1 / sum((1 / r for r in rs), Fraction(0))


def circuit_cases(rng: random.Random) -> list[dict[str, Any]]:
    def resistor(cid: str, r: int) -> dict[str, Any]:
        return {"id": cid, "kind": "resistor", "resistance": r}

    cases = [
        # VER-16 acceptance: 6 Ω parallel 3 Ω, in series with 4 Ω, across 12 V: 2 A exactly.
        _case("circuit_doc_parallel_pair", {"components": [{"id": "B", "kind": "cell", "emf": 12}, resistor("R1", 6),
              resistor("R2", 3), resistor("R3", 4)], "network": {"series": ["B", {"parallel": ["R1", "R2"]}, "R3"]}},
              {"equivalent_resistance": {"text": "6"}, "total_current": {"text": "2"},
               "components": {"R1": {"current": {"text": "2/3"}}, "R2": {"current": {"text": "4/3"}},
                              "R3": {"pd": {"text": "8"}}}}, "hand"),
        _case("circuit_doc_short_circuit", {"components": [{"id": "B", "kind": "cell", "emf": 6},
              {"id": "S", "kind": "switch", "state": "closed"}], "network": {"series": ["B", "S"]}}, {"error": 4},
              "hand"),
        _case("circuit_open_switch", {"components": [{"id": "B", "kind": "cell", "emf": 6}, resistor("R", 3),
              {"id": "S", "kind": "switch", "state": "open"}], "network": {"series": ["B", "R", "S"]}},
              {"open_circuit": True, "components": {"S": {"pd": {"text": "6"}}, "R": {"current": {"text": "0"}}}},
              "hand"),
        _case("circuit_parallel_ammeters", {"components": [{"id": "B", "kind": "cell", "emf": 6}, resistor("R", 3),
              {"id": "A1", "kind": "ammeter"}, {"id": "A2", "kind": "ammeter"}],
              "network": {"series": ["B", "R", {"parallel": ["A1", "A2"]}]}}, {"error": 4}, "hand"),
        _case("circuit_ammeter_shorts_resistor", {"components": [{"id": "B", "kind": "cell", "emf": 6},
              resistor("R1", 3), resistor("R2", 9), {"id": "A", "kind": "ammeter"}],
              "network": {"series": ["B", "R1", {"parallel": ["R2", "A"]}]}},
              {"components": {"A": {"reading": {"text": "2"}}, "R2": {"current": {"text": "0"}}}}, "hand"),
    ]  # fmt: skip
    for i in range(30):  # a parallel pair in series with a third resistor, ideal cell
        r1, r2, r3, emf = rng.randint(1, 12), rng.randint(1, 12), rng.randint(1, 12), rng.choice([3, 6, 9, 12, 24])
        pair = _parallel(Fraction(r1), Fraction(r2))
        total = _series(pair, Fraction(r3))
        current = emf / total
        expect = {"equivalent_resistance": {"text": _text(total)}, "total_current": {"text": _text(current)},
                  "components": {"R3": {"current": {"text": _text(current)}},
                                 "R1": {"current": {"text": _text(current * pair / r1)},
                                        "pd": {"text": _text(current * pair)}},
                                 "B": {"power": {"text": _text(emf * current)}}}}  # fmt: skip
        args = {
            "components": [
                {"id": "B", "kind": "cell", "emf": emf},
                resistor("R1", r1),
                resistor("R2", r2),
                resistor("R3", r3),
            ],
            "network": {"series": ["B", {"parallel": ["R1", "R2"]}, "R3"]},
        }
        cases.append(_case(f"circuit_pair_series_{i:03d}", args, expect))
    for i in range(25):  # series resistors with a cell of internal resistance
        rs = [rng.randint(1, 20) for _ in range(rng.randint(1, 4))]
        emf, internal = rng.choice([Fraction(3, 2), Fraction(6), Fraction(9), Fraction(12)]), rng.choice([0, 1, 2])
        current = emf / (sum(rs) + internal)
        cell = {"id": "B", "kind": "cell", "emf": _number(emf), "internal_resistance": internal}
        parts = [resistor(f"R{k}", r) for k, r in enumerate(rs)]
        expect = {"equivalent_resistance": {"text": _text(sum(rs))}, "total_current": {"text": _text(current)},
                  "components": {"B": {"pd": {"text": _text(emf - current * internal)}}}}  # fmt: skip
        args = {"components": [cell, *parts], "network": {"series": ["B", *(p["id"] for p in parts)]}}
        cases.append(_case(f"circuit_series_internal_{i:03d}", args, expect))
    for i in range(25):  # networks without a cell: the equivalent resistance between the ends
        a, b, c, d = (rng.randint(1, 30) for _ in range(4))
        shape = i % 3
        if shape == 0:
            network: dict[str, Any] = {"parallel": ["R1", "R2", "R3"]}
            total = _parallel(Fraction(a), Fraction(b), Fraction(c))
        elif shape == 1:
            network = {"parallel": ["R1", {"series": ["R2", "R3"]}]}
            total = _parallel(Fraction(a), _series(Fraction(b), Fraction(c)))
        else:
            network = {"series": [{"parallel": ["R1", "R2"]}, {"parallel": ["R3", "R4"]}]}
            total = _series(_parallel(Fraction(a), Fraction(b)), _parallel(Fraction(c), Fraction(d)))
        ids = ["R1", "R2", "R3"] + (["R4"] if shape == 2 else [])
        components = [resistor(cid, r) for cid, r in zip(ids, (a, b, c, d), strict=False)]
        cases.append(_case(f"circuit_equivalent_{i:03d}", {"components": components, "network": network},
                           {"equivalent_resistance": {"text": _text(total)}}))  # fmt: skip
    for i in range(20):  # the netlist form, with an ammeter in series and a voltmeter across the lamp
        r, lamp, emf = rng.randint(1, 10), rng.randint(1, 10), rng.choice([2, 4, 6, 12])
        current = Fraction(emf, r + lamp)
        components = [{"id": "B", "kind": "battery", "emf": emf}, resistor("R", r),
                      {"id": "L", "kind": "lamp", "resistance": lamp}, {"id": "A", "kind": "ammeter"},
                      {"id": "V", "kind": "voltmeter"}]  # fmt: skip
        connections = [
            {"from": "B.pos", "to": "A.a"},
            {"from": "A.b", "to": "R.a"},
            {"from": "R.b", "to": "L.a"},
            {"from": "L.b", "to": "B.neg"},
            {"from": "V.a", "to": "L.a"},
            {"from": "V.b", "to": "L.b"},
        ]
        expect = {"equivalent_resistance": {"text": str(r + lamp)},
                  "components": {"A": {"reading": {"text": _text(current)}},
                                 "V": {"reading": {"text": _text(current * lamp)}},
                                 "L": {"power": {"text": _text(current**2 * lamp)}}}}  # fmt: skip
        cases.append(_case(f"circuit_netlist_meters_{i:03d}", {"components": components, "connections": connections},
                           expect))  # fmt: skip
    for i in range(5):  # two cells in series, each with internal resistance
        emf, internal, load = Fraction(3, 2), Fraction(rng.choice([1, 2])), Fraction(rng.randint(1, 10))
        current = 2 * emf / (load + 2 * internal)
        cells = [{"id": f"B{k}", "kind": "cell", "emf": "1.5", "internal_resistance": int(internal)} for k in (1, 2)]
        args = {"components": [*cells, {"id": "L", "kind": "lamp", "resistance": int(load)}],
                "network": {"series": ["B1", "B2", "L"]}}  # fmt: skip
        expect = {"equivalent_resistance": {"text": _text(load)}, "total_current": {"text": _text(current)},
                  "components": {"B1": {"power_internal": {"text": _text(current**2 * internal)}}}}  # fmt: skip
        cases.append(_case(f"circuit_two_cells_{i:03d}", args, expect))
    return _errors_last(cases)


# --- phys_projectile --------------------------------------------------------------------------------------------


def projectile_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases = [
        # VER-17 acceptance: thrown up at 20 m/s with g = 10 m/s², the top is 20 m at 2 s.
        _case("projectile_doc_vertical", {"motion": "vertical", "speed": 20, "direction": "up", "g": 10,
              "g_source": "question", "points": 5}, {"time_to_max_height": {"text": "2"}, "max_height": {"text": "20"},
              "time_of_flight": {"text": "4"}, "positive_direction": "up"}, "hand"),
        _case("projectile_doc_default_g", {"motion": "vertical", "speed": 0, "height": "4.903325"},
              {"time_of_flight": {"text": "1"}, "g": {"text": sp.sstr(sp.Rational("9.80665"))}}, "hand"),
        _case("projectile_horizontal_units", {"motion": "horizontal", "speed": "72 km/h", "height": "45 m", "g": 10,
              "g_source": "pack"}, {"time_of_flight": {"text": "3"}, "range": {"text": "60"}}, "hand"),
        _case("projectile_no_direction", {"motion": "vertical", "speed": 5}, {"error": 4}, "hand"),
        _case("projectile_horizontal_on_ground", {"motion": "horizontal", "speed": 5, "g": 10, "g_source": "item"},
              {"error": 4}, "hand"),
        _case("projectile_wrong_unit", {"motion": "horizontal", "speed": "5 m", "height": 5}, {"error": 4}, "hand"),
    ]  # fmt: skip
    gs = [(Fraction(10), "question"), (Fraction(98, 10), "pack")]
    for i in range(40):  # thrown up from the ground: T = 2u/g, H = u²/(2g)
        u = rng.randint(1, 40)
        g, source = gs[i % 2]
        expect = {"time_of_flight": {"text": _text(2 * u / g)}, "max_height": {"text": _text(u * u / (2 * g))},
                  "time_to_max_height": {"text": _text(u / g)}, "range": {"text": "0"}}  # fmt: skip
        args = {"motion": "vertical", "speed": u, "direction": "up", "g": _number(g), "g_source": source}
        cases.append(_case(f"projectile_up_ground_{i:03d}", args, expect))
    for i in range(30):  # from a height h, landing speed v chosen first: h = (v² - u²)/(2g), T = (u ± v)/g
        g = Fraction(10)
        u, extra = rng.randint(0, 20), rng.randint(1, 20)
        v = u + extra
        h = Fraction(v * v - u * u) / (2 * g)
        up = i % 2 == 0 and u > 0
        flight = (u + v) / g if up else (v - u) / g
        top = h + (Fraction(u * u) / (2 * g) if up else 0)
        args = {"motion": "vertical", "speed": u, "height": _number(h), "g": 10, "g_source": "question"}
        if u > 0:
            args["direction"] = "up" if up else "down"
        expect = {"time_of_flight": {"text": _text(flight)}, "max_height": {"text": _text(top)},
                  "landing": {"speed": {"text": str(v)}}}  # fmt: skip
        cases.append(_case(f"projectile_vertical_height_{i:03d}", args, expect))
    for i in range(30):  # horizontal launch: flight time chosen first, h = g T²/2, range u T
        g, source = gs[i % 2]
        t = Fraction(rng.randint(1, 8), 2)
        u = rng.randint(1, 30)
        h = g * t * t / 2
        args = {"motion": "horizontal", "speed": u, "height": _number(h), "g": _number(g), "g_source": source,
                "points": rng.choice([2, 11, 21])}  # fmt: skip
        expect = {"time_of_flight": {"text": _text(t)}, "range": {"text": _text(u * t)},
                  "max_height": {"text": _text(h)}, "landing": {"vy": {"text": _text(-g * t)}}}  # fmt: skip
        cases.append(_case(f"projectile_horizontal_{i:03d}", args, expect))
    return _errors_last(cases)


# --- math_solve with quantities and units (VER-17) --------------------------------------------------------------


def quantity_cases(rng: random.Random) -> list[dict[str, Any]]:
    cases = [
        _case("solve_doc_quantities_kmh", {"equations": ["v = u + a*t"], "unknowns": ["v"], "units": {"v": "m/s"},
              "quantities": {"u": "72 km/h", "a": "2 m/s^2", "t": "5 s"}},
              {"solutions": [{"v": {"text": "30", "unit": "m s⁻¹"}}]}, "hand"),
        _case("solve_doc_dimension_mismatch", {"equations": ["s = u"], "unknowns": ["s"], "units": {"s": "m"},
              "quantities": {"u": "20 m/s"}}, {"error": 4}, "hand"),
        _case("solve_quantities_vertical", {"equations": ["s = u*t - 1/2*g*t^2"], "unknowns": ["t"],
              "units": {"t": "s"}, "quantities": {"s": "20 m", "u": "20 m/s"}, "positive_direction": "up",
              "constants": [{"symbol": "g", "value": 10, "unit": "m/s^2", "source": "question"}]},
              {"solutions": [{"t": {"text": "2", "unit": "s"}}], "positive_direction": "up"}, "hand"),
        _case("solve_quantities_missing_unit", {"equations": ["s = u*t"], "unknowns": ["s"],
              "quantities": {"u": "20 m/s", "t": "2 s"}}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(20):  # v = u + a t with u in km/h and v asked for in km/h: v = u + 3.6 a t
        u_kmh, a, t = rng.choice([18, 36, 54, 72, 90]), rng.randint(1, 5), rng.randint(1, 10)
        v = Fraction(u_kmh) + Fraction(18, 5) * a * t
        args = {
            "equations": ["v = u + a*t"],
            "unknowns": ["v"],
            "units": {"v": "km/h"},
            "quantities": {"u": f"{u_kmh} km/h", "a": f"{a} m/s^2", "t": f"{t} s"},
            "positive_direction": "forwards",
        }
        cases.append(_case(f"solve_quantities_kmh_{i:03d}", args, {"solutions": [{"v": {"text": _text(v)}}]}))
    for i in range(10):  # v² = u² + 2 a s from rest, distance in cm
        a, s_cm = rng.choice([2, 8, 18]), rng.choice([100, 400, 900])
        v_squared = 2 * a * Fraction(s_cm, 100)
        root = sp.sqrt(sp.Rational(v_squared.numerator, v_squared.denominator))
        args = {"equations": ["v^2 = u^2 + 2*a*s"], "unknowns": ["v"], "units": {"v": "m/s"}, "domain": "positive",
                "quantities": {"u": "0 m/s", "a": f"{a} m/s^2", "s": f"{s_cm} cm"}}  # fmt: skip
        cases.append(
            _case(f"solve_quantities_from_rest_{i:03d}", args, {"solutions": [{"v": {"text": sp.sstr(root)}}]})
        )
    return cases


# --- phys_mechanics (VER-31) ------------------------------------------------------------------------------------
#
# A level mechanics, built by construction: angles come from Pythagorean triples (tan a = 3/4 gives sin a = 3/5), so
# components are rational; collisions from chosen velocities and e solved by Cramer's rule, with the kinetic energy
# loss from its own closed form; equilibrium from moments about the other support; connected particles from the
# equation of the particle the checker does not use; work-energy cases from a chosen final speed. Irrational answers
# (surds, pi) are compared by their 6 significant figure decimal, computed here from the closed form.

TRIPLES = [(3, 4, 5), (4, 3, 5), (5, 12, 13), (12, 5, 13), (8, 15, 17), (7, 24, 25)]  # opposite, adjacent, hypotenuse
G_SOURCES = [(Fraction(10), "question"), (Fraction(49, 5), "pack")]
G10: dict[str, Any] = {"g": 10, "g_source": "question"}


def _ratio(value: Fraction | int) -> int | str:
    """A rational argument: an integer or "p/q" (the checker reads both exactly)."""
    value = Fraction(value)
    return int(value) if value.denominator == 1 else f"{value.numerator}/{value.denominator}"


def _t(value: Fraction | int) -> dict[str, str]:
    return {"text": _text(value)}


def _sf6(expr: Any) -> dict[str, str]:
    """The decimal of an irrational closed form, rounded half away from zero to 6 significant figures."""
    from decimal import ROUND_HALF_UP, Decimal

    value = Decimal(str(sp.N(sp.sympify(expr), 50)))
    rounded = value.quantize(Decimal(1).scaleb(value.adjusted() - 5), rounding=ROUND_HALF_UP)
    assert -4 <= rounded.adjusted() < 12, expr
    return {"decimal": format(rounded, "f")}


def _gravity(g: Fraction, source: str) -> dict[str, Any]:
    return {"g": _number(g), "g_source": source}


def _projectile_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "projectile_angle"}
    cases = [
        # VER-31 projectiles at an angle: 20 m/s at 30 degrees with g = 10 lands after 2 s, 20 sqrt 3 m away.
        _case("mech_doc_projectile_30", {**task, "speed": 20, "angle": 30, **G10},
              {"time_of_flight": _t(2), "max_height": _t(5), "range": {"text": sp.sstr(20 * sp.sqrt(3))},
               "positive_direction": "up"}, "hand"),
        _case("mech_projectile_default_g", {**task, "speed": "19.6133", "angle": 30},
              {"time_of_flight": _t(2), "g": {"text": sp.sstr(sp.Rational("9.80665"))}}, "hand"),
        _case("mech_projectile_sin_angle", {**task, "speed": 50, "sin_angle": "0.6", **G10},
              {"time_of_flight": _t(6), "range": _t(240), "max_height": _t(45)}, "hand"),
        _case("mech_projectile_wall", {**task, "speed": 25, "tan_angle": "3/4", "height": 20,
              "horizontal_distance": 40, **G10}, {"at_distance": {"time": _t(2), "y": _t(30)},
              "time_of_flight": _t(4), "range": _t(80)}, "hand"),
        _case("mech_projectile_into_ground", {**task, "speed": 10, "angle": -10, **G10}, {"error": 4}, "hand"),
        _case("mech_projectile_after_landing", {**task, "speed": 20, "angle": 30, "time": 3, **G10}, {"error": 4},
              "hand"),
        _case("mech_projectile_angle_out_of_range", {**task, "speed": 20, "angle": 95, **G10}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(10):  # tan a = opposite/adjacent from a triple, u = n * hypotenuse: rational components
        a, b, c = rng.choice(TRIPLES)
        n = rng.randint(1, 6)
        g, source = G_SOURCES[(i // 2) % 2]
        ux, uy = Fraction(b * n), Fraction(a * n)
        args = {**task, "speed": c * n, "tan_angle": _ratio(Fraction(a, b)), **_gravity(g, source)}
        if i % 2 == 0:  # from the ground: T = 2 u sin a / g, H = (u sin a)^2 / 2g, R = 2 u^2 sin a cos a / g
            expect = {"time_of_flight": _t(2 * uy / g), "max_height": _t(uy * uy / (2 * g)),
                      "range": _t(2 * ux * uy / g), "landing": {"speed": _t(c * n)}}  # fmt: skip
        else:  # from a height: the flight time is chosen, h = g T^2/2 - u_y T
            flight = 2 * uy / g + Fraction(rng.randint(1, 4), 2)
            h = g * flight * flight / 2 - uy * flight
            t = flight / 2
            args |= {"height": _ratio(h), "time": _ratio(t)}
            expect = {"time_of_flight": _t(flight), "range": _t(ux * flight), "max_height": _t(h + uy * uy / (2 * g)),
                      "at_time": {"y": _t(h + uy * t - g * t * t / 2), "vy": _t(uy - g * t)}}  # fmt: skip
        cases.append(_case(f"mech_projectile_triple_{i:03d}", args, expect))
    for i, degrees in enumerate((30, 45, 60, 30, 45, 60)):  # whole degrees: R = u^2 sin 2a / g
        u = rng.randint(10, 30)
        angle = sp.pi * degrees / 180
        expect = {"time_of_flight": _sf6(2 * u * sp.sin(angle) / 10), "max_height": _sf6((u * sp.sin(angle)) ** 2 / 20),
                  "range": _sf6(u**2 * sp.sin(2 * angle) / 10)}  # fmt: skip
        cases.append(_case(f"mech_projectile_degrees_{i:03d}", {**task, "speed": u, "angle": degrees, **G10}, expect))
    return cases


def _moments_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "moments"}
    cases = [
        # A uniform 6 m beam of mass 10 kg on supports at its ends, with 50 N at 1 m from A: moments about D.
        _case("mech_doc_moments", {**task, "length": 6, "beam_mass": 10, "loads": [{"id": "P", "distance": 1,
              "force": 50}], "supports": [{"id": "C", "distance": 0}, {"id": "D", "distance": 6}], **G10},
              {"supports": {"C": {"reaction": _t(Fraction(275, 3))}, "D": {"reaction": _t(Fraction(175, 3))}},
               "equilibrium": True}, "hand"),
        # A non-uniform rod hung from two strings: its centre of mass from moments about A.
        _case("mech_moments_centre_of_mass", {**task, "length": 4, "loads": [{"id": "G", "distance": "?",
              "force": 80}], "supports": [{"id": "A", "distance": 0, "reaction": 30},
              {"id": "B", "distance": 4, "reaction": 50}]}, {"loads": {"G": {"distance": _t(Fraction(5, 2))}},
              "solved": ["x_G"]}, "hand"),
        _case("mech_moments_given_balanced", {**task, "length": 4, "loads": [{"id": "P", "distance": 1, "force": 30}],
              "supports": [{"id": "A", "distance": 0, "reaction": 20}, {"id": "B", "distance": 3, "reaction": 10}]},
              {"equilibrium": True}, "hand"),
        _case("mech_moments_given_unbalanced", {**task, "length": 4, "loads": [{"id": "P", "distance": 1,
              "force": 30}], "supports": [{"id": "A", "distance": 0, "reaction": 15},
              {"id": "B", "distance": 3, "reaction": 15}]}, {"equilibrium": False,
              "moment_about_A": _t(15)}, "hand"),
        _case("mech_moments_three_supports", {**task, "length": 6, "loads": [{"id": "P", "distance": 3,
              "force": 50}], "supports": [{"id": "C", "distance": 1}, {"id": "D", "distance": 4},
              {"id": "E", "distance": 5}]}, {"status": "unknown", "reason": "underdetermined"}, "hand"),
        _case("mech_moments_negative_reaction", {**task, "length": 6, "loads": [{"id": "P", "distance": 6,
              "force": 100}], "supports": [{"id": "C", "distance": 0}, {"id": "D", "distance": 3}]}, {"error": 4},
              "hand"),
        _case("mech_moments_off_the_beam", {**task, "length": 6, "beam_weight": 100, "loads": [{"id": "P",
              "distance": "?", "force": 50}], "supports": [{"id": "C", "distance": 1, "reaction": 0},
              {"id": "D", "distance": 5}]}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(8):  # supports either side of the midpoint, loads between them: moments about C give R_D
        length = rng.randint(4, 12)
        c = rng.randint(0, length // 2 - 1)
        d = rng.randint(length // 2 + 1, length)
        g, source = G_SOURCES[i % 2]
        weight = rng.randint(20, 300)
        x1, x2 = rng.randint(c, d), Fraction(rng.randint(2 * c, 2 * d), 2)
        f1, m2 = rng.randint(10, 200), rng.randint(1, 20)
        moment_c = weight * (Fraction(length, 2) - c) + f1 * (x1 - c) + m2 * g * (x2 - c)
        r_d = moment_c / (d - c)
        r_c = weight + f1 + m2 * g - r_d
        args = {**task, "length": length, "beam_weight": weight, "supports": [{"id": "C", "distance": c},
                {"id": "D", "distance": d}], "loads": [{"id": "P", "distance": x1, "force": f1},
                {"id": "Q", "distance": _ratio(x2), "mass": m2}], **_gravity(g, source)}  # fmt: skip
        expect = {"supports": {"C": {"reaction": _t(r_c)}, "D": {"reaction": _t(r_d)}},
                  "loads": {"Q": {"force": _t(m2 * g)}}, "equilibrium": True}  # fmt: skip
        cases.append(_case(f"mech_moments_two_supports_{i:03d}", args, expect))
    for i in range(4):  # on the point of tilting about D: R_C = 0 and P (x - d) = W (d - L/2)
        half = rng.randint(2, 6)
        length = 2 * half
        d = rng.randint(half + 1, length - 1)
        x = rng.randint(d + 1, length)
        weight = rng.randint(20, 200)
        load = Fraction(weight * (d - half), x - d)
        unknown_force = i % 2 == 0
        p_load = {"id": "P", "distance": "?" if not unknown_force else x, "force": "?" if unknown_force else
                  _ratio(load)}  # fmt: skip
        args = {**task, "length": length, "beam_weight": weight, "loads": [p_load],
                "supports": [{"id": "C", "distance": 0, "reaction": 0}, {"id": "D", "distance": d}]}  # fmt: skip
        expect = {"loads": {"P": {"force": _t(load), "distance": _t(x)}},
                  "supports": {"D": {"reaction": _t(weight + load)}}}  # fmt: skip
        cases.append(_case(f"mech_moments_tilting_{i:03d}", args, expect))
    return cases


def _incline_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "incline_friction"}
    cases = [
        # 2 kg on a 30 degree slope, mu = 0.2: it slides with a = g (sin 30 - 0.2 cos 30).
        _case("mech_doc_incline_slides", {**task, "mass": 2, "angle": 30, "mu": "0.2", **G10},
              {"slides": True, "direction": "down_slope", "acceleration": _sf6(10 * (sp.Rational(1, 2) -
               sp.Rational(1, 5) * sp.sqrt(3) / 2))}, "hand"),
        # A pull of 50 N at tan b = 3/4 above a slope of tan a = 3/4: R = 40 - 30, up the slope 40 - 30 - mu R.
        _case("mech_incline_pull_at_angle", {**task, "mass": 5, "tan_angle": "3/4", "mu": "0.5", "applied_force": 50,
              "applied_tan_angle": "3/4", **G10}, {"normal_reaction": _t(10), "direction": "up_slope",
              "acceleration": _t(1), "friction_direction": "down_slope"}, "hand"),
        _case("mech_incline_no_mu", {**task, "mass": 5, "tan_angle": "3/4", **G10},
              {"status": "unknown", "reason": "underdetermined"}, "hand"),
        _case("mech_incline_impossible_acceleration", {**task, "mass": 5, "tan_angle": "3/4", "acceleration": 8,
              "direction": "down_slope", **G10}, {"error": 4}, "hand"),
        _case("mech_incline_lifted_off", {**task, "mass": 1, "tan_angle": "3/4", "mu": "0.5", "applied_force": 50,
              "applied_angle": 60, **G10}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(8):  # released from rest: slides when mu < tan a
        a, b, c = rng.choice(TRIPLES)
        m = rng.randint(1, 10)
        g, source = G_SOURCES[i % 2]
        mu = Fraction(rng.randint(0, 12), 10)
        sin, cos = Fraction(a, c), Fraction(b, c)
        slides = mu < Fraction(a, b)
        expect = {"normal_reaction": _t(m * g * cos), "slides": slides,
                  "acceleration": _t(g * (sin - mu * cos) if slides else 0),
                  "friction": _t(mu * m * g * cos if slides else m * g * sin),
                  "direction": "down_slope" if slides else "none"}  # fmt: skip
        args = {**task, "mass": m, "tan_angle": _ratio(Fraction(a, b)), "mu": _number(mu), **_gravity(g, source)}
        cases.append(_case(f"mech_incline_released_{i:03d}", args, expect))
    for i in range(3):  # pushed up the slope by P parallel to it, mu = 1/4 on a 3-4-5 slope, g = 10
        m = rng.randint(2, 8)
        push = rng.choice([0, 1, 2]) * 10 * m  # P = 0, 10m or 20m newtons
        along, limit = Fraction(push) - 6 * m, Fraction(2 * m)  # m g sin a = 6m, mu m g cos a = 2m
        if abs(along) <= limit:
            expect = {"slides": False, "acceleration": _t(0), "friction": _t(abs(along))}
        else:
            expect = {"slides": True, "direction": "up_slope" if along > 0 else "down_slope",
                      "acceleration": _t((abs(along) - limit) / m)}  # fmt: skip
        args = {**task, "mass": m, "tan_angle": "3/4", "mu": "0.25", "applied_force": push, **G10}
        cases.append(_case(f"mech_incline_pushed_{i:03d}", args, expect))
    for i in range(3):  # mu from the acceleration down the slope: mu chosen first, a = g (sin a - mu cos a)
        a, b, c = rng.choice(TRIPLES)
        mu = Fraction(a, b) * Fraction(rng.randint(1, 4), 5)
        accel = 10 * (Fraction(a, c) - mu * Fraction(b, c))
        args = {**task, "mass": rng.randint(1, 9), "tan_angle": _ratio(Fraction(a, b)), "acceleration": _ratio(accel),
                "direction": "down_slope", **G10}  # fmt: skip
        cases.append(_case(f"mech_incline_find_mu_{i:03d}", args, {"mu": _t(mu), "slides": True}))
    return cases


def _connected_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "connected_particles"}
    cases = [
        # 3 kg and 5 kg over a pulley, g = 10: a = 2g/8, T = 2 m1 m2 g / (m1 + m2); after 2 s, 5 m/s and 5 m.
        _case("mech_doc_connected_hanging", {**task, "arrangement": "hanging", "mass_a": 3, "mass_b": 5, "time": 2,
              **G10}, {"acceleration": _t(Fraction(5, 2)), "tension": _t(Fraction(75, 2)), "moving": "b_descends",
              "after_time": {"speed": _t(5), "distance": _t(5)}}, "hand"),
        _case("mech_connected_equal_masses", {**task, "arrangement": "hanging", "mass_a": 4, "mass_b": 4, **G10},
              {"moving": "at_rest", "tension": _t(40), "force_on_pulley": _t(80)}, "hand"),
        _case("mech_connected_rough_no_mu", {**task, "arrangement": "table", "mass_a": 4, "mass_b": 1,
              "surface": "rough", **G10}, {"status": "unknown", "reason": "underdetermined"}, "hand"),
        _case("mech_connected_hanging_with_mu", {**task, "arrangement": "hanging", "mass_a": 4, "mass_b": 1,
              "mu": "0.2", **G10}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(5):  # two particles hanging: a = |m_B - m_A| g / (m_A + m_B), T = 2 m_A m_B g / (m_A + m_B)
        m_a, m_b = rng.sample(range(1, 11), 2)
        g, source = G_SOURCES[i % 2]
        tension = Fraction(2 * m_a * m_b) * g / (m_a + m_b)
        expect = {
            "acceleration": _t(abs(m_b - m_a) * g / (m_a + m_b)),
            "tension": _t(tension),
            "force_on_pulley": _t(2 * tension),
            "moving": "b_descends" if m_b > m_a else "a_descends",
        }
        args = {**task, "arrangement": "hanging", "mass_a": m_a, "mass_b": m_b, **_gravity(g, source)}
        cases.append(_case(f"mech_connected_hanging_{i:03d}", args, expect))  # fmt: skip
    for i in range(4):  # A on a rough table, B hanging: the tension from A's equation, T - mu m_A g = m_A a
        m_a, m_b = rng.randint(1, 10), rng.randint(1, 10)
        mu = Fraction(rng.randint(0, 8), 10)
        g, source = G_SOURCES[i % 2]
        accel = max(Fraction(0), (m_b - mu * m_a) * g / (m_a + m_b))
        tension = m_a * (accel + mu * g) if accel > 0 else m_b * g
        expect = {"acceleration": _t(accel), "tension": _t(tension), "normal_reaction": _t(m_a * g),
                  "moving": "b_descends" if accel > 0 else "at_rest"}  # fmt: skip
        args = {**task, "arrangement": "table", "mass_a": m_a, "mass_b": m_b, "mu": _number(mu),
                **_gravity(g, source)}  # fmt: skip
        cases.append(_case(f"mech_connected_table_{i:03d}", args, expect))
    for i in range(4):  # A on a rough slope, B hanging over a pulley at the top
        a, b, c = rng.choice(TRIPLES)
        sin, cos = Fraction(a, c), Fraction(b, c)
        m_a, m_b = rng.randint(1, 10), rng.randint(1, 10)
        mu = Fraction(rng.randint(0, 5), 10)
        g = Fraction(10)
        up = (m_b - m_a * sin - mu * m_a * cos) * g / (m_a + m_b)  # B descends
        down = (m_a * sin - m_b - mu * m_a * cos) * g / (m_a + m_b)  # A slides down
        if up > 0:
            expect = {
                "moving": "b_descends",
                "acceleration": _t(up),
                "tension": _t(m_a * (up + g * sin + mu * g * cos)),
            }
        elif down > 0:
            expect = {"moving": "a_descends", "acceleration": _t(down), "tension": _t(m_b * (g + down))}
        else:
            expect = {"moving": "at_rest", "acceleration": _t(0), "tension": _t(m_b * g)}
        args = {**task, "arrangement": "incline", "tan_angle": _ratio(Fraction(a, b)), "mass_a": m_a, "mass_b": m_b,
                "mu": _number(mu), **G10}  # fmt: skip
        cases.append(_case(f"mech_connected_incline_{i:03d}", args, expect))
    return cases


def _energy_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "work_energy_power"}
    work = {**task, "part": "work_energy"}
    power = {**task, "part": "power"}
    cases = [
        # A 1000 kg car from 10 to 20 m/s over 300 m against 500 N: F d = 150 000 + 150 000.
        _case("mech_doc_driving_force", {**work, "find": "driving_force", "mass": 1000, "initial_speed": 10,
              "final_speed": 20, "distance": 300, "resistance": 500}, {"driving_force": _t(1000),
              "ke_change": _t(150000), "work_against_resistance": _t(150000)}, "hand"),
        _case("mech_work_force_at_angle", {**work, "find": "final_speed", "mass": 5, "initial_speed": 0,
              "driving_force": 50, "force_angle": 60, "distance": 10}, {"final_speed": _t(10),
              "work_by_driving_force": _t(250)}, "hand"),
        # P = F v: 30 kW at 20 m/s against 600 N, 1200 kg: F = 1500 N, a = 900 / 1200.
        _case("mech_doc_power_acceleration", {**power, "power": "30 kW", "speed": 20, "mass": 1200,
              "resistance": 600}, {"driving_force": _t(1500), "acceleration": _t(Fraction(3, 4))}, "hand"),
        _case("mech_power_max_speed_level", {**power, "power": 24000, "resistance": 800},
              {"speed": _t(30), "at_maximum_speed": True}, "hand"),
        _case("mech_efficiency_from_energies", {**task, "part": "efficiency", "input": "500 J",
              "useful_output": "400 J"}, {"efficiency": _t(Fraction(4, 5)), "percent": _t(80), "wasted": _t(100)},
              "hand"),
        _case("mech_efficiency_useful_power", {**task, "part": "efficiency", "input": "2 kW", "efficiency": "0.35"},
              {"useful_output": _t(700)}, "hand"),
        _case("mech_power_only", {**power, "power": 5000}, {"status": "unknown", "reason": "underdetermined"},
              "hand"),
        _case("mech_efficiency_over_one", {**task, "part": "efficiency", "input": 100, "useful_output": 120},
              {"error": 4}, "hand"),
        _case("mech_energy_runs_out", {**work, "find": "final_speed", "mass": 2, "initial_speed": 3,
              "height_gain": 5, **G10}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(4):  # final speed chosen first; the driving force (or the resistance) then balances the energy
        m, u, v = rng.randint(1, 20), rng.randint(0, 10), rng.randint(1, 15)
        h, d = rng.randint(-10, 10), rng.randint(5, 50)
        g, source = G_SOURCES[i % 2]
        needed = (Fraction(m * (v * v - u * u), 2) + m * g * h) / d  # net force along the motion
        args = {**work, "find": "final_speed", "mass": m, "initial_speed": u, "height_gain": h, "distance": d,
                **_gravity(g, source)}  # fmt: skip
        if needed >= 0:
            resistance = rng.randint(0, 50)
            args |= {"driving_force": _ratio(needed + resistance), "resistance": resistance}
        else:
            args |= {"resistance": _ratio(-needed)}
        expect = {"final_speed": _t(v), "gpe_change": _t(m * g * h), "ke_final": _t(Fraction(m * v * v, 2))}
        cases.append(_case(f"mech_energy_final_speed_{i:03d}", args, expect))
    for i in range(6):  # speeding up and climbing: the driving force or the resistance from W_F - W_R = dKE + dGPE
        m, u = rng.randint(100, 1500), rng.randint(0, 10)
        v, h, d = u + rng.randint(1, 10), rng.randint(0, 20), rng.randint(50, 500)
        resistance = rng.randint(0, 800)
        force = (Fraction(m * (v * v - u * u), 2) + 10 * m * h) / d + resistance
        args = {**work, "mass": m, "initial_speed": u, "final_speed": v, "height_gain": h, "distance": d, **G10}
        if i % 2 == 0:
            args |= {"find": "driving_force", "resistance": resistance}
            expect = {"driving_force": _t(force), "gpe_change": _t(10 * m * h)}
        else:
            args |= {"find": "resistance", "driving_force": _ratio(force)}
            expect = {"resistance": _t(resistance), "work_against_resistance": _t(resistance * d)}
        cases.append(_case(f"mech_energy_force_{i:03d}", args, expect))
    for i in range(3):  # maximum speed up a slope of sin a = 1/k: v = P / (R + m g sin a)
        m, k, resistance = rng.randint(500, 1500), rng.choice([10, 20, 25, 50]), rng.randint(100, 900)
        watts = rng.randint(10, 60) * 1000
        args = {**power, "power": watts, "mass": m, "resistance": resistance, "sin_angle": f"1/{k}", **G10}
        cases.append(_case(f"mech_power_max_speed_slope_{i:03d}", args,
                           {"speed": _t(Fraction(watts) / (resistance + Fraction(10 * m, k))),
                            "acceleration": _t(0)}))  # fmt: skip
    return cases


def _momentum_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "momentum_impulse"}
    collide = {**task, "part": "collision"}
    cases = [
        # 2 kg at 5 m/s meets 3 kg at -2 m/s, e = 1/2: v_A = -1.3, v_B = 2.2.
        _case("mech_doc_collision", {**collide, "mass_a": 2, "mass_b": 3, "velocity_a": 5, "velocity_b": -2,
              "restitution": "0.5"}, {"final_velocity_a": _t(Fraction(-13, 10)), "final_velocity_b":
              _t(Fraction(11, 5)), "direction_a": "negative", "impulse_on_b": _t(Fraction(63, 5))}, "hand"),
        _case("mech_collision_elastic_swap", {**collide, "mass_a": 4, "mass_b": 4, "velocity_a": 6, "velocity_b": 0,
              "restitution": 1}, {"final_velocity_a": _t(0), "final_velocity_b": _t(6), "ke_loss": _t(0)}, "hand"),
        _case("mech_collision_coalesce", {**collide, "mass_a": 3, "mass_b": 1, "velocity_a": 4, "velocity_b": 0,
              "restitution": 0}, {"final_velocity_a": _t(3), "final_velocity_b": _t(3), "ke_loss": _t(6)}, "hand"),
        _case("mech_doc_impulse_bounce", {**task, "part": "impulse", "mass": "0.2", "initial_velocity": 10,
              "final_velocity": -8, "time": "0.05"}, {"impulse": _t(Fraction(-18, 5)), "average_force": _t(-72)},
              "hand"),
        _case("mech_collision_underdetermined", {**collide, "mass_a": 2, "mass_b": 3, "velocity_a": 5,
              "velocity_b": 1}, {"status": "unknown", "reason": "underdetermined"}, "hand"),
        _case("mech_collision_no_approach", {**collide, "mass_a": 2, "mass_b": 3, "velocity_a": 5, "velocity_b": 6,
              "restitution": "0.5"}, {"error": 4}, "hand"),
        _case("mech_collision_energy_gained", {**collide, "mass_a": 1, "mass_b": 1, "velocity_a": 4, "velocity_b": 0,
              "final_velocity_a": -2}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(8):  # Cramer's rule on m_A v_A + m_B v_B = p and v_B - v_A = e (u_A - u_B)
        m_a, m_b = rng.randint(1, 6), rng.randint(1, 6)
        u_a = rng.randint(1, 8)
        u_b = rng.randint(-6, u_a - 1)
        e = Fraction(rng.randint(0, 10), 10)
        p, s = m_a * u_a + m_b * u_b, e * (u_a - u_b)
        v_a = (p - m_b * s) / (m_a + m_b)
        v_b = v_a + s
        loss = Fraction(m_a * m_b, 2 * (m_a + m_b)) * (1 - e * e) * (u_a - u_b) ** 2  # its own closed form
        args = {**collide, "mass_a": m_a, "mass_b": m_b, "velocity_a": u_a, "velocity_b": u_b}
        if i < 6:
            args["restitution"] = _number(e)
            expect = {"final_velocity_a": _t(v_a), "final_velocity_b": _t(v_b), "ke_loss": _t(loss)}
        else:  # e from the velocity of A after impact
            args["final_velocity_a"] = _ratio(v_a)
            expect = {"restitution": _t(e), "final_velocity_b": _t(v_b)}
        cases.append(_case(f"mech_collision_{i:03d}", args, expect))
    for i in range(3):  # a force F for t seconds: v = u + F t / m
        m, u = rng.randint(1, 10), rng.randint(-10, 10)
        force, t = rng.randint(-50, 50), Fraction(rng.randint(1, 20), 10)
        args = {**task, "part": "impulse", "mass": m, "initial_velocity": u, "force": force, "time": _number(t)}
        cases.append(_case(f"mech_impulse_{i:03d}", args, {"impulse": _t(force * t),
                                                           "final_velocity": _t(u + force * t / m)}))  # fmt: skip
    return cases


def _circular_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "circular_motion"}
    cone = {**task, "part": "conical_pendulum"}
    cases = [
        # A 3 kg mass on a 2 m radius once every 4 s: omega = pi/2, v = pi, a = pi^2/2.
        _case("mech_doc_circular_period", {**task, "radius": 2, "period": 4, "mass": 3},
              {"angular_speed": {"text": sp.sstr(sp.pi / 2)}, "speed": {"text": sp.sstr(sp.pi)},
               "force": _sf6(3 * sp.pi**2 / 2)}, "hand"),
        _case("mech_circular_frequency", {**task, "radius": "0.5", "frequency": 2},
              {"angular_speed": {"text": sp.sstr(4 * sp.pi)}, "acceleration": _sf6(8 * sp.pi**2)}, "hand"),
        # Conical pendulum, l = 5 m and r = 3 m: cos a = 4/5, omega^2 = g / (l cos a) = 10/4.
        _case("mech_conical_from_radius", {**cone, "length": 5, "radius": 3, "mass": 2, **G10},
              {"tension": _t(25), "angular_speed": _sf6(sp.sqrt(sp.Rational(5, 2))), "depth": _t(4)}, "hand"),
        _case("mech_conical_from_omega", {**cone, "length": 2, "angular_speed": 5, "mass": 1, **G10},
              {"tension": _t(50), "depth": _t(Fraction(2, 5))}, "hand"),
        _case("mech_circular_radius_only", {**task, "radius": 3}, {"status": "unknown", "reason": "underdetermined"},
              "hand"),
        _case("mech_conical_too_slow", {**cone, "length": 1, "angular_speed": 2, **G10}, {"error": 4}, "hand"),
        _case("mech_circular_inconsistent", {**task, "radius": 2, "speed": 3, "angular_speed": 2}, {"error": 4},
              "hand"),
    ]  # fmt: skip
    for i in range(5):  # radius and speed: omega = v / r, a = v^2 / r, F = m v^2 / r
        r, v, m = Fraction(rng.randint(1, 20), 2), rng.randint(1, 30), rng.randint(1, 10)
        args = {**task, "radius": _number(r), "speed": v, "mass": m}
        expect = {"angular_speed": _t(v / r), "acceleration": _t(v * v / r), "force": _t(m * v * v / r),
                  "period": {"text": sp.sstr(2 * sp.pi * sp.Rational(r.numerator, r.denominator) / v)}}  # fmt: skip
        cases.append(_case(f"mech_circular_speed_{i:03d}", args, expect))
    for i in range(4):  # conical pendulum at tan a = opposite/adjacent to the vertical: T = m g / cos a
        a, b, c = rng.choice(TRIPLES)
        length, m = rng.randint(1, 4), rng.randint(1, 5)
        cos = Fraction(b, c)
        args = {**cone, "length": length, "tan_angle": _ratio(Fraction(a, b)), "mass": m, **G10}
        expect = {"tension": _t(10 * m / cos), "radius": _t(length * Fraction(a, c)),
                  "acceleration": _t(Fraction(10 * a, b)),  # g tan a
                  "angular_speed": _sf6(sp.sqrt(sp.Rational(10 * c, length * b)))}  # fmt: skip
        cases.append(_case(f"mech_conical_{i:03d}", args, expect))
    return cases


def _shm_mech(rng: random.Random) -> list[dict[str, Any]]:
    task = {"task": "shm"}
    cases = [
        # A = 0.1 m, T = 2 s: omega = pi; at x = 0.06 m, v = pi sqrt(0.01 - 0.0036) = 0.08 pi.
        _case("mech_doc_shm", {**task, "amplitude": "0.1", "period": 2, "displacement": "0.06"},
              {"angular_frequency": {"text": "pi"}, "max_speed": {"text": sp.sstr(sp.pi / 10)},
               "at_displacement": {"speed": {"text": sp.sstr(2 * sp.pi / 25)}}}, "hand"),
        _case("mech_shm_from_extreme", {**task, "amplitude": "0.2", "period": 6, "time": 1, "start": "extreme"},
              {"at_time": {"displacement": _t(Fraction(1, 10))}}, "hand"),
        _case("mech_shm_from_centre", {**task, "amplitude": "0.2", "period": 12, "time": 1, "start": "centre"},
              {"at_time": {"displacement": _t(Fraction(1, 10))}}, "hand"),
        _case("mech_shm_from_maxima", {**task, "max_speed": 2, "max_acceleration": 8},
              {"angular_frequency": _t(4), "amplitude": _t(Fraction(1, 2))}, "hand"),
        _case("mech_shm_energy", {**task, "amplitude": "0.05", "angular_frequency": 10, "mass": "0.4"},
              {"energy": _t(Fraction(1, 20)), "max_force": _t(2)}, "hand"),
        _case("mech_shm_time_without_start", {**task, "amplitude": "0.1", "period": 2, "time": "0.5"},
              {"status": "unknown", "reason": "ambiguous"}, "hand"),
        _case("mech_shm_amplitude_only", {**task, "amplitude": "0.1"},
              {"status": "unknown", "reason": "underdetermined"}, "hand"),
        _case("mech_shm_beyond_amplitude", {**task, "amplitude": "0.1", "angular_frequency": 3,
              "displacement": "0.2"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(5):  # A = 5k cm and x = 3k cm: v = omega sqrt(A^2 - x^2) = 4k cm times omega
        k, omega = rng.randint(1, 4), rng.randint(1, 12)
        amplitude, x = Fraction(5 * k, 100), Fraction(3 * k, 100) * rng.choice([1, -1])
        args = {**task, "amplitude": _number(amplitude), "angular_frequency": omega, "displacement": _number(x)}
        expect = {
            "max_speed": _t(amplitude * omega),
            "max_acceleration": _t(amplitude * omega**2),
            "at_displacement": {"speed": _t(Fraction(4 * k, 100) * omega), "acceleration": _t(-omega * omega * x)},
        }
        cases.append(_case(f"mech_shm_displacement_{i:03d}", args, expect))  # fmt: skip
    for i in range(3):  # a quarter period from the extreme: x = 0 and v = -A omega = -2 pi A / T
        size, period = rng.randint(1, 5), rng.randint(1, 8)
        args = {**task, "amplitude": size, "period": period, "start": "extreme",
                "time": _number(Fraction(period, 4))}  # fmt: skip
        velocity = -sp.Integer(2 * size) * sp.pi / period
        expect = {"at_time": {"displacement": _t(0), "velocity": {"text": sp.sstr(velocity)}}, "period": _t(period)}
        cases.append(_case(f"mech_shm_quarter_{i:03d}", args, expect))
    return cases


def mechanics_cases(rng: random.Random) -> list[dict[str, Any]]:
    """The A level mechanics golden set (VER-31), every topic of the requirement."""
    cases = (_projectile_mech(rng) + _moments_mech(rng) + _incline_mech(rng) + _connected_mech(rng)
             + _energy_mech(rng) + _momentum_mech(rng) + _circular_mech(rng) + _shm_mech(rng))  # fmt: skip
    return _errors_last(cases)
