"""Golden sets for the chemistry checkers (VER-18 to VER-21; M12.c), built by construction like golden.py.

Expected answers never come from the checkers: formulae are assembled from chosen ions with their atom counts known
by construction, and masses summed here from an O level relative atomic mass table passed to the tool as the pack's
convention (plus a few hand-keyed standard atomic weights for the default-table cases); equations come from reaction
families whose coefficients follow from a formula in n; mole chains, neutralisation volumes, titration equivalence
points and enthalpy changes are computed here in exact fractions from chosen values, and pH values to two decimal
places with Python's decimal logarithm. Every case is synthetic; each set says `review: pending`."""

from __future__ import annotations

import random
from decimal import ROUND_HALF_UP, Decimal, getcontext
from fractions import Fraction
from math import gcd
from typing import Any

import sympy as sp

SEED = 20261013
Case = dict[str, Any]
# O level relative atomic masses as a pack states them (synthetic convention for the golden cases).
AR = {"H": "1", "Li": "7", "C": "12", "N": "14", "O": "16", "F": "19", "Na": "23", "Mg": "24", "Al": "27", "P": "31",
      "S": "32", "Cl": "35.5", "K": "39", "Ca": "40", "Mn": "55", "Fe": "56", "Cu": "63.5", "Zn": "65", "Br": "80",
      "Ag": "108", "I": "127", "Ba": "137", "Pb": "207"}  # fmt: skip
# Hand-keyed standard atomic weights (CIAAW abridged) for the default-table cases.
STANDARD = {"H": "1.0080", "C": "12.011", "N": "14.007", "O": "15.999", "Na": "22.990", "S": "32.06", "Cl": "35.45"}
CATIONS = [("Li", 1), ("Na", 1), ("K", 1), ("Ag", 1), ("Mg", 2), ("Ca", 2), ("Ba", 2), ("Cu", 2), ("Zn", 2),
           ("Fe", 2), ("Pb", 2), ("Al", 3), ("Fe", 3)]  # fmt: skip
# anion text, its atoms, its charge
ANIONS = [("Cl", {"Cl": 1}, 1), ("Br", {"Br": 1}, 1), ("I", {"I": 1}, 1), ("OH", {"O": 1, "H": 1}, 1),
          ("NO3", {"N": 1, "O": 3}, 1), ("O", {"O": 1}, 2), ("SO4", {"S": 1, "O": 4}, 2),
          ("CO3", {"C": 1, "O": 3}, 2), ("PO4", {"P": 1, "O": 4}, 3)]  # fmt: skip


def _case(case_id: str, args: dict[str, Any], expect: dict[str, Any], origin: str = "constructed") -> Case:
    return {"id": case_id, "args": args, "expect": expect, "origin": origin}


def _text(value: Fraction | int) -> str:
    value = Fraction(value)
    return sp.sstr(sp.Rational(value.numerator, value.denominator))


def _decimal(value: Fraction) -> str:
    """A terminating fraction as a decimal string (the tool's `shown`)."""
    places = 0
    while (value * 10**places).denominator != 1:
        places += 1
    return format(Decimal(value.numerator) / Decimal(value.denominator), "f") if places else str(int(value))


def _number(value: Fraction) -> str:
    return _decimal(value)


def _pack(*elements: str, table: dict[str, str] = AR, source: str = "pack") -> list[dict[str, str]]:
    return [{"symbol": f"Ar({e})", "value": table[e], "source": source} for e in dict.fromkeys(elements)]


def _mass(counts: dict[str, int], table: dict[str, str] = AR) -> Fraction:
    return sum((Fraction(table[e]) * n for e, n in counts.items()), Fraction(0))


def _formula(parts: list[tuple[str, int]]) -> str:
    return "".join(e + (str(n) if n > 1 else "") for e, n in parts)


def _round_dp(value: Decimal, dp: int) -> str:
    return str(value.quantize(Decimal(1).scaleb(-dp), rounding=ROUND_HALF_UP))


def _sf(value: Fraction, sf: int) -> str:
    d = Decimal(value.numerator) / Decimal(value.denominator)
    if d == 0:
        return "0"
    return format(d.quantize(Decimal(1).scaleb(d.adjusted() - sf + 1), rounding=ROUND_HALF_UP), "f")


def _errors_last(cases: list[Case]) -> list[Case]:
    return [c for c in cases if "error" not in c["expect"]] + [c for c in cases if "error" in c["expect"]]


# --- chem_molar_mass (VER-18) ---------------------------------------------------------------------------------------


def _salt(rng: random.Random) -> tuple[str, dict[str, int]]:
    """A neutral ionic formula from a chosen cation and anion, with its atom counts."""
    (metal, plus), (anion, atoms, minus) = rng.choice(CATIONS), rng.choice(ANIONS)
    lcm = plus * minus // gcd(plus, minus)
    n_metal, n_anion = lcm // plus, lcm // minus
    counts: dict[str, int] = {metal: n_metal}
    for element, count in atoms.items():
        counts[element] = counts.get(element, 0) + count * n_anion
    group = anion if n_anion == 1 else (f"({anion}){n_anion}" if len(atoms) > 1 or anion == "OH" else
                                        f"{anion}{n_anion}")  # fmt: skip
    return f"{metal}{n_metal if n_metal > 1 else ''}{group}", counts


def molar_mass_cases(rng: random.Random) -> list[Case]:
    hydrate = {"Cu": 1, "S": 1, "O": 9, "H": 10}
    cases = [
        _case("mm_doc_hydrate", {"formula": "CuSO4·5H2O", "constants": _pack("Cu", "S", "O", "H")},
              {"counts": hydrate, "molar_mass": {"text": "499/2", "shown": "249.5"},
               "lines": [{"element": "Cu", "count": 1, "ar": "63.5", "subtotal": "63.5"},
                         {"element": "S", "count": 1, "ar": "32", "subtotal": "32"},
                         {"element": "O", "count": 9, "ar": "16", "subtotal": "144"},
                         {"element": "H", "count": 10, "ar": "1", "subtotal": "10"}]}, "hand"),
        _case("mm_doc_pack_chlorine", {"formula": "NaCl", "constants": [{"symbol": "ar_na", "value": "23",
              "source": "pack"}, {"symbol": "ar_cl", "value": "35.5", "source": "pack"}]},
              {"molar_mass": {"shown": "58.5"}}, "hand"),
        _case("mm_question_beats_pack", {"formula": "HCl", "constants": [
              {"symbol": "Ar(Cl)", "value": "35.5", "source": "pack"}, {"symbol": "Ar(Cl)", "value": "35",
              "source": "question"}, {"symbol": "Ar(H)", "value": "1", "source": "pack"}]},
              {"molar_mass": {"shown": "36"}}, "hand"),
        _case("mm_ion_charge", {"formula": "SO4^2-", "constants": _pack("S", "O")},
              {"charge": -2, "counts": {"S": 1, "O": 4}, "molar_mass": {"shown": "96"}}, "hand"),
        _case("mm_superscript_ion", {"formula": "NH₄⁺", "constants": _pack("N", "H")},
              {"charge": 1, "molar_mass": {"shown": "18"}}, "hand"),
        _case("mm_state_symbol", {"formula": "C3H8(g)", "constants": _pack("C", "H")},
              {"state": "g", "molar_mass": {"shown": "44"}}, "hand"),
        _case("mm_square_brackets", {"formula": "K4[Fe(CN)6]", "constants": _pack("K", "Fe", "C", "N")},
              {"counts": {"K": 4, "Fe": 1, "C": 6, "N": 6}, "molar_mass": {"shown": "368"}}, "hand"),
        _case("mm_no_standard_weight", {"formula": "TcO2"}, {"status": "unknown", "reason": "convention_missing"},
              "hand"),
        _case("mm_ambiguous_charge", {"formula": "Cu2+"}, {"error": 3}, "hand"),
        _case("mm_unknown_element", {"formula": "XyO"}, {"error": 3}, "hand"),
        _case("mm_leading_number", {"formula": "2H2O"}, {"error": 3}, "hand"),
        _case("mm_unclosed_bracket", {"formula": "Ca(OH2"}, {"error": 3}, "hand"),
        _case("mm_electron", {"formula": "e-"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i, (formula, counts) in enumerate(
        [
            ("H2O", {"H": 2, "O": 1}),
            ("CO2", {"C": 1, "O": 2}),
            ("NaCl", {"Na": 1, "Cl": 1}),
            ("H2SO4", {"H": 2, "S": 1, "O": 4}),
            ("NH3", {"N": 1, "H": 3}),
            ("C2H5OH", {"C": 2, "H": 6, "O": 1}),
        ]
    ):
        mass = _mass(counts, STANDARD)  # no convention stated: the standard atomic weights, with a warning
        cases.append(_case(f"mm_default_table_{i}", {"formula": formula}, {"molar_mass": {"text": _text(mass)}},
                           "hand"))  # fmt: skip
    for i in range(70):  # ionic compounds, some hydrated
        formula, counts = _salt(rng)
        if i % 3 == 0:
            water = rng.randint(1, 10)
            formula += f"·{water}H2O"
            counts = {**counts, "H": counts.get("H", 0) + 2 * water, "O": counts.get("O", 0) + water}
        args = {"formula": formula, "constants": _pack(*counts)}
        mass = _mass(counts)
        cases.append(_case(f"mm_salt_{i:03d}", args, {"counts": counts, "molar_mass": {"text": _text(mass),
                           "shown": _decimal(mass)}}))  # fmt: skip
    for i in range(25):  # hydrocarbons and alcohols
        n = rng.randint(1, 12)
        family = i % 3
        parts = (
            [("C", n), ("H", 2 * n + 2)]
            if family == 0
            else ([("C", n), ("H", 2 * n)] if family == 1 else [("C", n), ("H", 2 * n + 1), ("O", 1), ("H", 1)])
        )
        if family == 1 and n == 1:
            parts = [("C", 2), ("H", 4)]
        counts: dict[str, int] = {}
        for element, count in parts:
            counts[element] = counts.get(element, 0) + count
        formula = _formula(parts)
        cases.append(_case(f"mm_organic_{i:03d}", {"formula": formula, "constants": _pack("C", "H", "O")},
                           {"counts": counts, "molar_mass": {"text": _text(_mass(counts))}}))  # fmt: skip
    return _errors_last(cases)


# --- chem_balance (VER-19) ------------------------------------------------------------------------------------------


def _reduce(values: list[int]) -> list[int]:
    divisor = 0
    for v in values:
        divisor = gcd(divisor, v)
    return [v // divisor for v in values]


def _families(n: int) -> list[tuple[str, str, list[int]]]:
    """Reaction families whose smallest coefficients follow from n: (name, equation, coefficients)."""
    alkane = _formula([("C", n), ("H", 2 * n + 2)])
    out = [("alkane", f"{alkane} + O2 -> CO2 + H2O", _reduce([2, 3 * n + 1, 2 * n, 2 * n + 2]))]
    if n >= 2:
        out.append(("alkene", f"{_formula([('C', n), ('H', 2 * n)])} + O2 -> CO2 + H2O",
                    _reduce([2, 3 * n, 2 * n, 2 * n])))  # fmt: skip
        alcohol = _formula([("C", n), ("H", 2 * n + 1)]) + "OH"
        out.append(("alcohol", f"{alcohol} + O2 -> CO2 + H2O", _reduce([2, 3 * n, 2 * n, 2 * n + 2])))
    return out


METALS = {1: ["Na", "K", "Li"], 2: ["Mg", "Ca", "Zn"], 3: ["Al"]}


def balance_cases(rng: random.Random) -> list[Case]:
    doc = "C3H8 + O2 -> CO2 + H2O"
    cases = [
        _case("bal_doc_propane", {"equation": doc}, {"status": "balanced", "coefficients": [1, 5, 3, 4],
              "atom_counts": [{"element": "C", "reactants": 3, "products": 3},
                              {"element": "H", "reactants": 8, "products": 8},
                              {"element": "O", "reactants": 10, "products": 10}]}, "hand"),
        _case("bal_doc_not_lowest_terms", {"equation": doc, "coefficients": [2, 10, 6, 8]},
              {"coefficients": [1, 5, 3, 4], "student": {"balanced": True, "verdict": "not_lowest_terms",
                                                         "factor": 2}}, "hand"),
        _case("bal_doc_written_claim", {"equation": "2C3H8 + 10O2 → 6CO2 + 8H2O"},
              {"student": {"verdict": "not_lowest_terms"}}, "hand"),
        _case("bal_correct_claim", {"equation": "C3H8 + 5O2 -> 3CO2 + 4H2O"}, {"student": {"verdict": "correct"}},
              "hand"),
        _case("bal_unbalanced_claim", {"equation": "C3H8 + 5O2 -> 3CO2 + 3H2O"},
              {"student": {"balanced": False, "verdict": "not_balanced", "unbalanced": ["H", "O"]}}, "hand"),
        _case("bal_half_coefficient", {"equation": "H2 + 1/2 O2 -> H2O"},
              {"coefficients": [2, 1, 2], "student": {"verdict": "not_lowest_terms", "factor": "1/2"}}, "hand"),
        _case("bal_ionic", {"equation": "Fe^3+ + OH^- -> Fe(OH)3"}, {"coefficients": [1, 3, 1],
              "charge": {"reactants": 0, "products": 0}}, "hand"),
        _case("bal_half_equation", {"equation": "Cu^2+ + e- -> Cu"}, {"coefficients": [1, 2, 1]}, "hand"),
        _case("bal_ionic_precipitate", {"equation": "Ag+ + Cl- -> AgCl(s)"}, {"coefficients": [1, 1, 1]}, "hand"),
        _case("bal_redox_ions", {"equation": "Fe^2+ + Cl2 -> Fe^3+ + Cl-"}, {"coefficients": [2, 1, 2, 2]}, "hand"),
        _case("bal_reversible", {"equation": "N2 + H2 <=> NH3"}, {"coefficients": [1, 3, 2], "reversible": True},
              "hand"),
        _case("bal_unspaced", {"equation": "H2+O2=H2O"}, {"coefficients": [2, 1, 2]}, "hand"),
        _case("bal_two_reactions", {"equation": "H2 + O2 -> H2O + H2O2"},
              {"status": "unknown", "reason": "several_independent_reactions"}, "hand"),
        _case("bal_cannot_balance", {"equation": "NaCl -> Na2O"}, {"error": 4}, "hand"),
        _case("bal_spectator_species", {"equation": "H2O -> H2 + O2 + N2"}, {"error": 4}, "hand"),
        _case("bal_two_arrows", {"equation": "H2 -> H -> H2"}, {"error": 3}, "hand"),
        _case("bal_wrong_count", {"equation": doc, "coefficients": [1, 5, 3]}, {"error": 4}, "hand"),
    ]  # fmt: skip
    families = [f for n in range(1, 13) for f in _families(n)]
    for i, (name, equation, coefficients) in enumerate(families):
        cases.append(_case(f"bal_{name}_{i:03d}", {"equation": equation}, {"coefficients": coefficients}))
        k = rng.randint(2, 4)
        cases.append(_case(f"bal_{name}_multiple_{i:03d}", {"equation": equation,
                           "coefficients": [c * k for c in coefficients]},
                           {"student": {"verdict": "not_lowest_terms", "factor": k}}))  # fmt: skip
        wrong = list(coefficients)
        wrong[rng.randrange(len(wrong))] += rng.randint(1, 3)
        cases.append(_case(f"bal_{name}_wrong_{i:03d}", {"equation": equation, "coefficients": wrong},
                           {"student": {"balanced": False, "verdict": "not_balanced"}}))  # fmt: skip
    for i in range(20):  # metal + hydrochloric acid -> chloride + hydrogen; metal + oxygen -> oxide
        valency = rng.choice([1, 2, 3])
        metal = rng.choice(METALS[valency])
        salt = f"{metal}Cl{valency if valency > 1 else ''}"
        cases.append(_case(f"bal_metal_acid_{i:03d}", {"equation": f"{metal} + HCl -> {salt} + H2"},
                           {"coefficients": _reduce([2, 2 * valency, 2, valency])}))  # fmt: skip
        oxide = _formula([(metal, 2 if valency % 2 else 1), ("O", valency if valency % 2 else valency // 2)])
        expected = _reduce([4, valency, 2]) if valency % 2 else _reduce([2, valency // 2, 2])
        cases.append(_case(f"bal_metal_oxide_{i:03d}", {"equation": f"{metal} + O2 -> {oxide}"},
                           {"coefficients": expected}))  # fmt: skip
    return _errors_last(cases)


# --- chem_stoichiometry (VER-20) ------------------------------------------------------------------------------------


def stoichiometry_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("stoich_doc_sodium_chloride", {"steps": [
            {"id": "n", "op": "amount_from_concentration", "concentration": "0.5 mol dm^-3", "volume": "250 cm^3"},
            {"id": "m", "op": "mass_from_amount", "species": "NaCl", "amount": "@n"}],
            "constants": _pack("Na", "Cl"), "sf": 3},
            {"result": {"value": {"text": "117/16", "unit": "g"}, "rounded": "7.31"},
             "steps": [{"value": {"text": "1/8", "unit": "mol"}}, {"rounded": "7.31"}]}, "hand"),
        _case("stoich_gas_default_volume", {"steps": [{"id": "v", "op": "gas_volume_from_amount", "amount": "0.25"}]},
              {"result": {"value": {"text": "6", "unit": "dm³"}}}, "hand"),
        _case("stoich_gas_stated_volume", {"steps": [{"id": "n", "op": "amount_from_gas_volume",
              "volume": "1120 cm^3"}], "constants": [{"symbol": "Vm", "value": "22.4", "unit": "dm^3/mol",
              "source": "question"}]}, {"result": {"value": {"text": "1/20"}}}, "hand"),
        _case("stoich_limiting_and_yield", {"equation": "2Mg + O2 -> 2MgO", "steps": [
              {"id": "l", "op": "limiting_reagent", "amounts": {"Mg": "0.5", "O2": "0.2"}, "product": "MgO"},
              {"id": "y", "op": "percentage_yield", "actual": "0.3", "theoretical": "@l"}]},
              {"steps": [{"limiting": "O2", "value": {"text": "2/5"}}, {"value": {"text": "75"}}]}, "hand"),
        _case("stoich_electrolysis_copper", {"steps": [{"id": "e", "op": "electrolysis", "current": "2 A",
              "time": "965 s", "electrons": 2, "species": "Cu"}], "constants": [
              {"symbol": "F", "value": 96500, "unit": "C/mol", "source": "question"}, *_pack("Cu")]},
              {"result": {"value": {"text": "127/200", "unit": "g"}}}, "hand"),
        _case("stoich_electrolysis_no_faraday", {"steps": [{"id": "e", "op": "electrolysis", "current": "2 A",
              "time": "10 min", "electrons": 1}]}, {"status": "unknown", "reason": "convention_missing"}, "hand"),
        _case("stoich_atom_economy", {"equation": "CaCO3 -> CaO + CO2", "steps": [{"id": "a", "op": "atom_economy",
              "product": "CaO"}], "constants": _pack("Ca", "C", "O")}, {"result": {"value": {"text": "56"}}}, "hand"),
        _case("stoich_purity", {"steps": [{"id": "p", "op": "purity", "pure_mass": "4.5 g", "sample_mass": "5.0 g"}]},
              {"result": {"value": {"text": "90"}}}, "hand"),
        _case("stoich_bare_volume", {"steps": [{"id": "n", "op": "amount_from_concentration", "concentration": "0.5",
              "volume": "250"}]}, {"error": 4}, "hand"),
        _case("stoich_no_equation", {"steps": [{"id": "r", "op": "mole_ratio", "from": "H2", "to": "H2O",
              "amount": 1}]}, {"error": 4}, "hand"),
        _case("stoich_wrong_dimension", {"steps": [{"id": "n", "op": "amount_from_mass", "species": "NaCl",
              "mass": "2 mol"}], "constants": _pack("Na", "Cl")}, {"error": 4}, "hand"),
        _case("stoich_unbalanced_written", {"equation": "Mg + O2 -> 2MgO", "steps": [{"id": "r", "op": "mole_ratio",
              "from": "Mg", "to": "MgO", "amount": 1}]}, {"error": 4}, "hand"),
        _case("stoich_cited_mass_differs", {"steps": [{"id": "m", "op": "mass_from_amount", "species": "NaCl",
              "amount": 1}], "constants": _pack("Na", "Cl"), "cites": [{"check_id": "chk_01JZ0000000000000000000009",
              "check": "chem_molar_mass", "formula": "NaCl", "molar_mass": "58.44"}]}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(40):  # mass of a fuel -> moles -> moles of CO2 -> mass of CO2 (combustion family)
        n = rng.randint(1, 8)
        _, equation, coefficients = _families(n)[0]
        fuel = _formula([("C", n), ("H", 2 * n + 2)])
        fuel_mass = Fraction(12 * n + 2 * n + 2) * Fraction(rng.randint(1, 40), 10)
        moles = fuel_mass / (12 * n + 2 * n + 2)
        co2 = moles * coefficients[2] / coefficients[0]
        args = {"equation": equation, "constants": _pack("C", "H", "O"), "steps": [
            {"id": "a", "op": "amount_from_mass", "species": fuel, "mass": f"{_number(fuel_mass)} g"},
            {"id": "b", "op": "mole_ratio", "from": fuel, "to": "CO2", "amount": "@a"},
            {"id": "c", "op": "mass_from_amount", "species": "CO2", "amount": "@b"}]}  # fmt: skip
        cases.append(
            _case(
                f"stoich_combustion_{i:03d}",
                args,
                {
                    "steps": [
                        {"value": {"text": _text(moles)}},
                        {"value": {"text": _text(co2)}},
                        {"value": {"text": _text(co2 * 44)}},
                    ],
                    "coefficients": [str(c) for c in coefficients],
                },
            )
        )
    for i in range(25):  # titration-style: concentration from an amount and a volume in cm³
        amount = Fraction(rng.randint(1, 50), 1000)
        volume_cm3 = rng.choice([10, 20, 25, 40, 50, 100, 200, 250, 500])
        args = {"steps": [{"id": "c", "op": "concentration_from_amount", "amount": f"{_number(amount)} mol",
                           "volume": f"{volume_cm3} cm^3"}]}  # fmt: skip
        cases.append(
            _case(
                f"stoich_concentration_{i:03d}",
                args,
                {"result": {"value": {"text": _text(amount * 1000 / volume_cm3), "unit": "mol dm⁻³"}}},
            )
        )
    for i in range(20):  # gas volumes at r.t.p. with the pack's 24 dm³ stated
        mass = Fraction(rng.randint(1, 200), 10)
        gas, molar = rng.choice([("CO2", 44), ("O2", 32), ("N2", 28), ("H2", 2), ("CH4", 16)])
        args = {"constants": [*_pack(*{"CO2": "CO", "O2": "O", "N2": "N", "H2": "H", "CH4": "CH"}[gas]),
                              {"symbol": "molar_volume", "value": "24", "unit": "dm^3/mol", "source": "pack"}],
                "steps": [{"id": "n", "op": "amount_from_mass", "species": gas, "mass": f"{_number(mass)} g"},
                          {"id": "v", "op": "gas_volume_from_amount", "amount": "@n"}]}  # fmt: skip
        cases.append(_case(f"stoich_gas_{i:03d}", args, {"result": {"value": {"text": _text(mass / molar * 24)}}}))
    for i in range(15):  # percentage yield from masses
        theoretical = Fraction(rng.randint(10, 100))
        actual = theoretical * Fraction(rng.randint(10, 100), 100)
        args = {"steps": [{"id": "y", "op": "percentage_yield", "actual": f"{_number(actual)} g",
                           "theoretical": f"{_number(theoretical)} g"}], "sf": 3}  # fmt: skip
        expected = actual / theoretical * 100
        cases.append(_case(f"stoich_yield_{i:03d}", args, {"result": {"value": {"text": _text(expected)},
                           "rounded": _sf(expected, 3)}}))  # fmt: skip
    return _errors_last(cases)


# --- chem_acid_base (VER-21) ----------------------------------------------------------------------------------------

STRONG_ACIDS = [("HCl", 1), ("HNO3", 1), ("H2SO4", 2)]
STRONG_BASES = [("NaOH", 1), ("KOH", 1), ("Ca(OH)2", 2)]


def _ph(concentration: Fraction) -> Decimal:
    getcontext().prec = 40
    return -(Decimal(concentration.numerator) / Decimal(concentration.denominator)).log10()


def acid_base_cases(rng: random.Random) -> list[Case]:
    doc = {"task": "titration_curve", "acid": "HCl", "acid_concentration": "0.100 mol/dm^3",
           "acid_volume": "25.0 cm^3", "base": "NaOH", "base_concentration": "0.100 mol/dm^3",
           "at_volumes": ["25.0 cm^3"]}  # fmt: skip
    cases = [
        _case("ab_doc_titration_equivalence", doc, {"equivalence": {"volume": {"text": "25"}, "ph": {"text": "7",
              "rounded": "7.00"}}, "at": [{"volume": {"text": "25"}, "ph": {"rounded": "7.00"}}],
              "start_ph": {"text": "1"}}, "hand"),
        _case("ab_doc_strong_acid_ph", {"acid": "HCl", "acid_concentration": "0.1 M"}, {"ph": {"text": "1"},
              "poh": {"text": "13"}}, "hand"),
        _case("ab_sulfuric_acid", {"acid": "H2SO4", "acid_concentration": "0.05 M"}, {"ph": {"text": "1"}}, "hand"),
        _case("ab_calcium_hydroxide", {"base": "Ca(OH)2", "base_concentration": "0.005 M"},
              {"ph": {"text": "12"}, "oh": {"text": "1/100"}}, "hand"),
        _case("ab_from_ph", {"ph": 3}, {"h": {"text": "1/1000"}, "oh": {"text": "1/100000000000"}}, "hand"),
        _case("ab_stated_kw", {"base": "NaOH", "base_concentration": "0.01 M", "constants": [
              {"symbol": "Kw", "value": "1.0e-14", "source": "pack"}]}, {"ph": {"text": "12"}}, "hand"),
        _case("ab_weak_acid", {"acid": "CH3COOH", "acid_concentration": "0.1 M"},
              {"status": "unknown", "reason": "weak_acid_or_base"}, "hand"),
        _case("ab_strength_unstated", {"acid": "H2C2O4", "acid_concentration": "0.1 M"},
              {"status": "unknown", "reason": "strength_unknown"}, "hand"),
        _case("ab_base_in_flask", {"task": "titration_curve", "analyte": "base", "base": "NaOH",
              "base_concentration": "0.2 M", "base_volume": "20 cm^3", "acid": "HCl", "acid_concentration": "0.1 M"},
              {"equivalence": {"volume": {"text": "40"}}, "start_ph": {"rounded": "13.30"}}, "hand"),
        _case("ab_sulfuric_titre", {"acid": "H2SO4", "acid_concentration": "0.1 M", "acid_volume": "20 cm^3",
              "base": "NaOH", "base_concentration": "0.2 M"}, {"solved": "base_volume", "ratio": {"acid": "1",
              "base": "2"}, "base": {"volume": {"text": "20"}}, "neutral": True}, "hand"),
        _case("ab_excess_reported", {"acid": "HCl", "acid_concentration": "0.1 M", "acid_volume": "25 cm^3",
              "base": "NaOH", "base_concentration": "0.1 M", "base_volume": "20 cm^3"},
              {"neutral": False, "excess": {"of": "acid", "ions": {"text": "1/2000"}}}, "hand"),
        _case("ab_two_unknowns", {"acid": "HCl", "acid_concentration": "0.1 M", "base": "NaOH",
              "base_concentration": "0.1 M"}, {"error": 4}, "hand"),
        _case("ab_basicity_mismatch", {"acid": "H2SO4", "basicity": 1, "acid_concentration": "0.1 M"}, {"error": 4},
              "hand"),
        _case("ab_bare_volume", {"acid": "HCl", "acid_concentration": "0.1", "acid_volume": "25", "base": "NaOH",
              "base_concentration": "0.1"}, {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(30):  # pH of a strong acid or base at a chosen concentration
        kind = "acid" if i % 2 == 0 else "base"
        formula, ions = rng.choice(STRONG_ACIDS if kind == "acid" else STRONG_BASES)
        concentration = Fraction(rng.randint(1, 99), 10 ** rng.randint(1, 4))
        free = concentration * ions
        ph = _ph(free) if kind == "acid" else 14 + Decimal(free.numerator).log10() - Decimal(free.denominator).log10()
        args = {kind: formula, f"{kind}_concentration": f"{_number(concentration)} mol/dm^3"}
        cases.append(_case(f"ab_ph_{kind}_{i:03d}", args, {"ph": {"rounded": _round_dp(ph, 2)}}))
    for i in range(30):  # neutralisation: solve the base volume, then the acid concentration
        acid, basicity = rng.choice(STRONG_ACIDS)
        base, acidity = rng.choice(STRONG_BASES)
        ca, va = Fraction(rng.randint(5, 20), 100), rng.choice([10, 20, 25])
        cb = Fraction(rng.randint(5, 20), 100)
        vb = ca * va * basicity / (cb * acidity)
        args = {"acid": acid, "acid_concentration": f"{_number(ca)} M", "acid_volume": f"{va} cm^3", "base": base,
                "base_concentration": f"{_number(cb)} M"}  # fmt: skip
        cases.append(_case(f"ab_titre_{i:03d}", args, {"solved": "base_volume",
                           "base": {"volume": {"text": _text(vb)}}, "neutral": True}))  # fmt: skip
        titre = Fraction(rng.randint(100, 400), 10)
        args = {"acid": acid, "acid_volume": f"{_number(titre)} cm^3", "base": base, "base_volume": "25.0 cm^3",
                "base_concentration": f"{_number(cb)} M"}  # fmt: skip
        found = cb * 25 * acidity / (titre * basicity)
        cases.append(_case(f"ab_acid_concentration_{i:03d}", args, {"solved": "acid_concentration",
                           "acid": {"concentration": {"text": _text(found)}}}))  # fmt: skip
    for i in range(25):  # titration curves: the equivalence volume and the pH before any titrant
        acid, basicity = rng.choice(STRONG_ACIDS)
        base, acidity = rng.choice(STRONG_BASES)
        ca, va, cb = (
            Fraction(rng.choice([5, 10, 20]), 100),
            rng.choice([10, 20, 25]),
            Fraction(rng.choice([5, 10, 20]), 100),
        )
        veq = ca * va * basicity / (cb * acidity)
        args = {"task": "titration_curve", "acid": acid, "acid_concentration": f"{_number(ca)} M",
                "acid_volume": f"{va} cm^3", "base": base, "base_concentration": f"{_number(cb)} M",
                "points": rng.choice([11, 21, 41])}  # fmt: skip
        cases.append(
            _case(
                f"ab_curve_{i:03d}",
                args,
                {
                    "equivalence": {"volume": {"text": _text(veq)}, "ph": {"text": "7"}},
                    "start_ph": {"rounded": _round_dp(_ph(ca * basicity), 2)},
                },
            )
        )
    return _errors_last(cases)


# --- chem_energetics (VER-21) ---------------------------------------------------------------------------------------


def energetics_cases(rng: random.Random) -> list[Case]:
    cases = [
        _case("en_doc_calorimetry_exothermic", {"mass": "50 g", "specific_heat": "4.2 J/(g K)",
              "specific_heat_source": "question", "temperature_change": "6.0 K", "amount": "0.025 mol"},
              {"q": {"text": "1260"}, "delta_h": {"text": "-252/5", "rounded": "-50.4"}, "nature": "exothermic",
               "sign_convention": "exothermic_negative"}, "hand"),
        _case("en_doc_calorimetry_endothermic", {"mass": "50 g", "initial_temperature": "21.0 °C",
              "final_temperature": "19.0 °C", "amount": "0.01 mol", "constants": [
              {"symbol": "c", "value": "4.2", "unit": "J/(g*K)", "source": "pack"}]},
              {"delta_h": {"text": "42"}, "nature": "endothermic"}, "hand"),
        _case("en_celsius_change", {"mass": 100, "specific_heat": "4.18", "temperature_change": "5 °C"},
              {"q": {"text": "2090"}, "nature": "exothermic"}, "hand"),
        _case("en_fuel_mass", {"mass": "200 g", "specific_heat": "4.2", "temperature_change": 23, "fuel_mass": "0.46 g",
              "formula": "C2H5OH", "constants": _pack("C", "H", "O")}, {"amount": {"text": "1/100"},
              "delta_h": {"text": "-1932"}}, "hand"),
        _case("en_bond_energies_hcl", {"broken": [{"bond": "H-H", "count": 1, "energy": 436},
              {"bond": "Cl-Cl", "count": 1, "energy": 242}], "formed": [{"bond": "H-Cl", "count": 2,
              "energy": 431}]}, {"delta_h": {"text": "-184"}, "nature": "exothermic"}, "hand"),
        _case("en_no_specific_heat", {"mass": 50, "temperature_change": 3, "amount": "0.01"},
              {"status": "unknown", "reason": "convention_missing"}, "hand"),
        _case("en_no_mass", {"specific_heat": "4.2", "temperature_change": 3}, {"error": 4}, "hand"),
        _case("en_mixed_units", {"mass": 50, "specific_heat": "4.2", "initial_temperature": "20 °C",
              "final_temperature": "300 K"}, {"error": 4}, "hand"),
        _case("en_no_bonds_formed", {"task": "bond_energies", "broken": [{"bond": "H-H", "energy": 436}]},
              {"error": 4}, "hand"),
    ]  # fmt: skip
    for i in range(60):  # calorimetry with chosen mass, c, ΔT and amount
        mass = rng.choice([25, 50, 100, 150, 200, 250])
        c, source = rng.choice([("4.2", "question"), ("4.18", "pack"), ("4.2", "item")])
        change = Fraction(rng.randint(-40, 60), 2) or Fraction(1, 2)
        amount = Fraction(rng.randint(1, 100), 1000)
        heat = mass * Fraction(c) * change
        delta_h = -heat / amount / 1000
        args = {"mass": f"{mass} g", "specific_heat": c, "specific_heat_source": source,
                "temperature_change": f"{_number(change)} K", "amount": f"{_number(amount)} mol"}  # fmt: skip
        nature = "exothermic" if delta_h < 0 else "endothermic"
        cases.append(
            _case(
                f"en_calorimetry_{i:03d}",
                args,
                {
                    "q": {"text": _text(heat)},
                    "delta_h": {"text": _text(delta_h), "rounded": _sf(delta_h, 3)},
                    "nature": nature,
                },
            )
        )
    for i in range(40):  # bond energies: Σ broken - Σ formed
        bonds = ["C-H", "C-C", "C=O", "O=O", "O-H", "H-H", "N≡N", "N-H", "Cl-Cl", "H-Cl", "C-O", "C=C"]
        broken = [{"bond": b, "count": rng.randint(1, 6), "energy": rng.randint(150, 950)}
                  for b in rng.sample(bonds, rng.randint(1, 3))]  # fmt: skip
        formed = [{"bond": b, "count": rng.randint(1, 6), "energy": rng.randint(150, 950)}
                  for b in rng.sample(bonds, rng.randint(1, 3))]  # fmt: skip
        delta_h = sum(b["count"] * b["energy"] for b in broken) - sum(b["count"] * b["energy"] for b in formed)
        nature = "exothermic" if delta_h < 0 else ("endothermic" if delta_h > 0 else "thermoneutral")
        cases.append(_case(f"en_bonds_{i:03d}", {"broken": broken, "formed": formed},
                           {"delta_h": {"text": str(delta_h)}, "nature": nature}))  # fmt: skip
    return _errors_last(cases)


def sets(rng: random.Random) -> dict[str, list[Case]]:
    """The M12.c sets by tool name (stage S2)."""
    return {
        "chem_molar_mass": molar_mass_cases(rng),
        "chem_balance": balance_cases(rng),
        "chem_stoichiometry": stoichiometry_cases(rng),
        "chem_acid_base": acid_base_cases(rng),
        "chem_energetics": energetics_cases(rng),
    }
