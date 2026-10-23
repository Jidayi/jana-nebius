"""Golden sets for the physics checkers (VER-16, VER-17; M12.b), built by construction like golden.py.

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
