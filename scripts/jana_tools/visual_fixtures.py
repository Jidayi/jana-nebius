"""Canonical visual fixtures, resolved by the engine (VSL-03, VSL-13, VSL-29, VSL-31, VSL-35).

Each fixture is a synthetic request (our own example values, never a past paper) resolved through the engine's one
validator (`agent_core.assets.visuals.validate`) with the real verification tools run in process as build checks
(`chk_build_fx_…`, CUR-20), the pack conventions in `content/curriculum/ref/` (sign conventions, g, proton numbers),
the template presets and library diagrams of the content tree (through the diagram pipeline of VSL-34), and the
heart test fixture of the renderer package. The resolved specs are what the client renderers are tested and
golden-rendered against, and what the UI gallery shows; nothing in them is hand-written, so every number a fixture
shows traces to a check, a known or pack data.

    python -m jana_tools visual-fixtures [--write]

writes (or, without --write, checks) packages/renderers/fixtures/visuals/*.json, the simulation fidelity table
packages/renderers/fixtures/sim_fidelity.json (VSL-31: tool readouts at each declared sample point) and the visual
viewer's gallery states in packages/ui/gallery/states/."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

FIXTURES_DIR = Path("packages") / "renderers" / "fixtures"
VISUALS_DIR = FIXTURES_DIR / "visuals"
LIBRARY_DIR = FIXTURES_DIR / "library"
SCIENCE_DIR = FIXTURES_DIR / "science"
FIDELITY = FIXTURES_DIR / "sim_fidelity.json"
CATALOGUE = FIXTURES_DIR / "catalogue.json"
GALLERY_DIR = Path("packages") / "ui" / "gallery" / "states"
GALLERY_PREFIX = "visual-viewer."
CURRICULUM = Path("content") / "curriculum"
SUBJECT_CODES = {"mathematics": "mth", "physics": "phy", "chemistry": "chm", "biology": "bio", "accounting": "acc"}


@dataclass
class Fixture:
    id: str
    subject: str
    request: dict[str, Any]
    givens: dict[str, str] = field(default_factory=dict)  # kn_ id -> the question's given value
    checks: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # earlier checks the request cites
    modes: tuple[str, ...] = ("shown", "hidden")
    stage: str = "S2"
    level: str = "O"  # the A level kinds (VSL-07) are advertised only in A level sessions


def req(kind: str, params: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {"spec_version": 1, "type": kind, "params": params, **extra}


FIXTURES: list[Fixture] = [
    Fixture(
        "function-graph",
        "mathematics",
        req(
            "function_graph",
            {
                "curves": [{"id": "f", "expr": "x^2 - 4*x + 3", "label": "y = x² \u2212 4x + 3"}],
                "x_range": [-1, 5],
                "y_range": [-2, 8],
                "marks": ["roots", "turning_points"],
                "axis_labels": {"x": "x", "y": "y"},
            },
            steps=[{"highlight": ["f"]}, {"highlight": ["f.root1", "f.root2"]}, {"highlight": ["f.min"]}],
        ),
    ),
    Fixture(
        "number-line",
        "mathematics",
        req(
            "number_line",
            {"variable": "x", "intervals": [{"id": "sol", "from": "4", "to": "inf", "from_closed": False}]},
            numbers_from=["chk_build_fx_number_line_c1"],
        ),
        checks=[("math_solve", {"equations": ["2*x - 3 = 5"], "unknowns": ["x"]})],
    ),
    Fixture(
        "geometry-figure",
        "mathematics",
        req(
            "geometry_figure",
            {},
            ref="dgm.mth.geometry_right_triangle.v1",
            steps=[{"highlight": ["side_a", "side_b"]}, {"highlight": ["side_c"]}],
        ),
    ),
    Fixture(
        "unit-circle",
        "mathematics",
        req("unit_circle", {"angle_deg": 30, "show": ["sin", "cos", "tan"]}, numbers_from=["kn_angle"]),
        {"kn_angle": "30"},
    ),
    Fixture(
        "venn-diagram",
        "mathematics",
        req(
            "venn_diagram",
            {
                "sets": [{"id": "A", "label": "Football"}, {"id": "B", "label": "Netball"}],
                "regions": [
                    {"id": "A", "value": "7"},
                    {"id": "AB", "value": "4"},
                    {"id": "B", "value": "5"},
                    {"id": "none", "value": "2"},
                ],
                "universal_label": "Class",
            },
            numbers_from=["kn_ra", "kn_rab", "kn_rb", "kn_rnone"],
            steps=[{"highlight": ["region_AB"]}],
        ),
        {"kn_ra": "7", "kn_rab": "4", "kn_rb": "5", "kn_rnone": "2"},
    ),
    Fixture(
        "statistics-chart",
        "mathematics",
        req(
            "statistics_chart",
            {
                "chart": "bar",
                "categories": [
                    {"id": "mon", "label": "Mon", "value": "12"},
                    {"id": "tue", "label": "Tue", "value": "9"},
                    {"id": "wed", "label": "Wed", "value": "15"},
                ],
                "axis_labels": {"y": "Books"},
            },
            numbers_from=["kn_mon", "kn_tue", "kn_wed"],
        ),
        {"kn_mon": "12", "kn_tue": "9", "kn_wed": "15"},
    ),
    Fixture(
        "statistics-histogram",
        "mathematics",
        req(
            "statistics_chart",
            {
                "chart": "histogram",
                "classes": [
                    {"id": "c1", "lower": "0", "upper": "10", "frequency": "4"},
                    {"id": "c2", "lower": "10", "upper": "30", "frequency": "12"},
                    {"id": "c3", "lower": "30", "upper": "40", "frequency": "6"},
                ],
            },
            numbers_from=["kn_c1", "kn_c2", "kn_c3", "kn_b0", "kn_b10", "kn_b30", "kn_b40"],
        ),
        {"kn_c1": "4", "kn_c2": "12", "kn_c3": "6", "kn_b0": "0", "kn_b10": "10", "kn_b30": "30", "kn_b40": "40"},
    ),
    Fixture(
        "matrix-table",
        "mathematics",
        req(
            "matrix_table",
            {"table": "matrix", "name": "A", "rows": [["2", "1"], ["3", "4"]]},
            numbers_from=["kn_m2", "kn_m1", "kn_m3", "kn_m4"],
        ),
        {"kn_m2": "2", "kn_m1": "1", "kn_m3": "3", "kn_m4": "4"},
    ),
    Fixture(
        "bearing-diagram",
        "mathematics",
        req(
            "bearing_diagram",
            {"from": "P", "to": "Q", "bearing": "65", "distance": "8 km", "show": ["back_bearing"]},
            numbers_from=["kn_brg", "kn_dist"],
        ),
        {"kn_brg": "65", "kn_dist": "8"},
    ),
    Fixture(
        "free-body",
        "physics",
        req(
            "free_body",
            {
                "object": "block",
                "surface": {"incline_deg": 30, "kind": "incline"},
                "forces": [
                    {"id": "W", "name": "weight", "magnitude": "49 N", "direction_deg": 270},
                    {"id": "R", "name": "normal reaction", "magnitude": "42.4 N", "direction_deg": 120},
                    {"id": "F", "name": "friction", "magnitude": "24.5 N", "direction_deg": 30},
                ],
            },
            numbers_from=["kn_fw", "kn_fr", "kn_ff"],
            steps=[
                {"highlight": ["W"], "board_step": "stp_01"},
                {"highlight": ["W"], "add": [{"element": "components_of", "of": "W"}], "board_step": "stp_02"},
                {"highlight": ["W.parallel", "F"], "board_step": "stp_03"},
            ],
        ),
        {"kn_fw": "49", "kn_fr": "42.4", "kn_ff": "24.5"},
    ),
    Fixture(
        "motion-graph",
        "physics",
        req(
            "motion_graph",
            {
                "graph": "velocity_time",
                "points": [
                    {"id": "A", "t": "0", "value": "0"},
                    {"id": "B", "t": "4", "value": "12"},
                    {"id": "C", "t": "10", "value": "12"},
                    {"id": "D", "t": "14", "value": "0"},
                ],
                "gradient": [{"id": "g1", "from": "A", "to": "B"}],
                "shade": [{"id": "area", "from": "A", "to": "D"}],
                "units": {"t": "s", "value": "m/s"},
            },
            numbers_from=["kn_v0", "kn_v4", "kn_12", "kn_10", "kn_14"],
            steps=[{"highlight": ["g1"]}, {"highlight": ["area"]}],
        ),
        {"kn_v0": "0", "kn_v4": "4", "kn_12": "12", "kn_10": "10", "kn_14": "14"},
    ),
    Fixture(
        "circuit",
        "physics",
        req(
            "circuit",
            {},
            ref="dgm.phy.circuit_series_two_lamps.v1",
            steps=[{"highlight": ["A1", "A1.reading"]}, {"highlight": ["V1", "V1.reading"]}],
        ),
    ),
    Fixture("circuit-parallel", "physics", req("circuit", {}, ref="dgm.phy.circuit_parallel_resistors.v1")),
    Fixture(
        "ray-diagram",
        "physics",
        req(
            "ray_diagram",
            {},
            ref="dgm.phy.ray_converging_beyond_2f.v1",
            steps=[
                {"highlight": ["ray.parallel"]},
                {"highlight": ["ray.focal"]},
                {"highlight": ["ray.centre", "image"]},
            ],
        ),
    ),
    Fixture("ray-magnifier", "physics", req("ray_diagram", {}, ref="dgm.phy.ray_converging_inside_f.v1")),
    Fixture(
        "wave-diagram",
        "physics",
        req(
            "wave_diagram",
            {
                "wave": "transverse",
                "wavelength": "2.0 m",
                "amplitude": "0.5 m",
                "cycles": 2,
                "markers": ["wavelength", "amplitude", "crest", "trough"],
            },
            numbers_from=["kn_lambda", "kn_amp"],
        ),
        {"kn_lambda": "2.0", "kn_amp": "0.5"},
    ),
    Fixture(
        "library-refraction",
        "physics",
        req("library_diagram", {"sequence": "through_the_block"}, ref="dgm.phy.refraction_glass_block.v1"),
    ),
    Fixture(
        "library-titration",
        "chemistry",
        req(
            "library_diagram",
            {},
            ref="dgm.chm.titration_apparatus.v1",
            steps=[{"highlight": ["burette"]}, {"highlight": ["solution", "white_tile"]}],
        ),
        modes=("shown", "hidden", "quiz"),
    ),
    Fixture(
        "library-heart",
        "biology",
        req("library_diagram", {"sequence": "blood_flow"}, ref="dgm.bio.heart.v1"),
        modes=("shown", "hidden", "quiz"),
    ),
    Fixture(
        "projectile-sim",
        "physics",
        req("projectile_sim", {"mode": "horizontal", "speed": 12, "height": 20}),
        modes=("shown",),
    ),
    Fixture(
        "circuit-sim",
        "physics",
        req(
            "circuit_sim",
            {
                "emf": 6,
                "resistors": [{"id": "R1", "resistance": 4}, {"id": "R2", "resistance": 2}],
                "arrangement": "series",
                "switch_closed": True,
            },
        ),
        modes=("shown",),
    ),
    Fixture(
        "balanced-equation",
        "chemistry",
        req(
            "balanced_equation",
            {
                "reactants": [{"formula": "H2", "state": "g"}, {"formula": "O2", "state": "g"}],
                "products": [{"formula": "H2O", "state": "l"}],
            },
            steps=[{"highlight": ["r1", "p1"]}, {"highlight": ["atoms.H"]}],
        ),
    ),
    Fixture(
        "particle-diagram", "chemistry", req("particle_diagram", {"mode": "reaction", "equation": "H2 + Cl2 -> HCl"})
    ),
    Fixture("particle-states", "chemistry", req("particle_diagram", {"mode": "state", "state": "liquid"})),
    Fixture(
        "electron-shells",
        "chemistry",
        req("electron_shells", {"element": "Na", "charge": 1}, steps=[{"highlight": ["shell_2"]}]),
    ),
    Fixture(
        "periodic-table",
        "chemistry",
        req(
            "periodic_table",
            {
                "highlight": {"kind": "elements", "values": ["Na", "Cl"]},
                "show_relative_mass": True,
                "trend": "reactivity_halogens",
            },
        ),
    ),
    Fixture(
        "titration-curve",
        "chemistry",
        req(
            "titration_curve",
            {
                "analyte": {"formula": "HCl", "kind": "acid", "strength": "strong", "concentration": "0.100 mol dm^-3"},
                "titrant": {
                    "formula": "NaOH",
                    "kind": "base",
                    "strength": "strong",
                    "concentration": "0.100 mol dm^-3",
                },
                "analyte_volume": "25.0 cm^3",
                "indicator": "phenolphthalein",
                "marks": ["equivalence_point", "half_equivalence", "start_ph"],
            },
            steps=[{"highlight": ["equivalence"]}],
        ),
    ),
    Fixture(
        "energy-profile",
        "chemistry",
        req(
            "energy_profile",
            {
                "reaction": "exothermic",
                "reactants": "CH4 + 2O2",
                "products": "CO2 + 2H2O",
                "activation_energy": "250 kJ/mol",
                "enthalpy_change": "-890 kJ/mol",
                "catalysed": True,
            },
            numbers_from=["kn_ea", "kn_dh"],
        ),
        {"kn_ea": "250", "kn_dh": "-890"},
    ),
    Fixture(
        "titration-sim",
        "chemistry",
        req(
            "titration_sim",
            {
                "acid": {"formula": "HCl", "concentration": 0.1},
                "base": {"formula": "NaOH", "concentration": 0.1},
                "acid_volume": 25,
                "indicator": "phenolphthalein",
            },
        ),
        modes=("shown",),
    ),
    # Predict, observe, explain (VSL-47): the scenario sets the starting values, so the request names only the scenario
    # and the required fields it replaces.
    Fixture(
        "circuit-sim-predict",
        "physics",
        req(
            "circuit_sim",
            {
                "emf": 6,
                "resistors": [{"id": "R1", "resistance": 10}],
                "arrangement": "series",
                "predict": "poe.phy.circuit_series_to_parallel.v1",
            },
        ),
        modes=("shown",),
    ),
    Fixture(
        "titration-sim-predict",
        "chemistry",
        req(
            "titration_sim",
            {
                "acid": {"formula": "HCl", "concentration": 0.1},
                "base": {"formula": "NaOH", "concentration": 0.1},
                "acid_volume": 25,
                "indicator": "phenolphthalein",
                "predict": "poe.chm.titration_double_strength_alkali.v1",
            },
        ),
        modes=("shown",),
    ),
    # The S3 simulations of the installed O level subjects (VSL-08a, VSL-46), each free and with its predict scenario.
    Fixture(
        "gas-laws-sim",
        "physics",
        req(
            "gas_laws_sim",
            {
                "amount_mol": 0.008,
                "temperature_k": 300,
                "volume_m3": 0.0002,
                "control": "volume",
                "preset_id": "sim.phy.gas_syringe.v1",
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "gas-laws-sim-predict",
        "physics",
        req(
            "gas_laws_sim",
            {
                "amount_mol": 0.008,
                "temperature_k": 300,
                "volume_m3": 0.0002,
                "control": "volume",
                "preset_id": "sim.phy.gas_syringe.v1",
                "predict": "poe.phy.gas_heated_flask.v1",
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "function-transform-sim",
        "mathematics",
        req(
            "function_transform_sim",
            {
                "expression": "x^3 - 3*x",
                "x_range": [-5, 5],
                "parameters": {
                    "a": {"min": -3, "max": 3, "step": 0.5, "value": 1},
                    "b": {"min": -2, "max": 2, "step": 0.5, "value": 1},
                    "c": {"min": -4, "max": 4, "step": 1, "value": 0},
                    "d": {"min": -4, "max": 4, "step": 1, "value": 0},
                },
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "function-transform-sim-predict",
        "mathematics",
        req("function_transform_sim", {"predict": "poe.mth.function_shift_left.v1"}),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "electrolysis-sim",
        "chemistry",
        req(
            "electrolysis_sim",
            {
                "preset_id": "sim.chm.electrolysis_copper_sulfate.v1",
                "electrolyte": "copper(II) sulfate",
                "phase": "aqueous",
                "electrodes": "inert",
                "current_a": 2,
                "duration_s": 1800,
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "electrolysis-sim-predict",
        "chemistry",
        req("electrolysis_sim", {"predict": "poe.chm.electrolysis_brine_cathode.v1"}),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "rates-sim",
        "chemistry",
        req(
            "rates_sim",
            {
                "temperature_k": 298,
                "concentration_mol_l": 1,
                "activation_energy_j_mol": 60000,
                "pre_exponential_s": 300000000,
                "catalysed_activation_energy_j_mol": 45000,
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "rates-sim-predict",
        "chemistry",
        req("rates_sim", {"predict": "poe.chm.rates_hotter_same_amount.v1"}),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "equilibrium-sim",
        "chemistry",
        req(
            "equilibrium_sim",
            {
                "reaction": {
                    "species": [
                        {"id": "N2", "formula": "N2", "state": "gas", "coefficient": 1, "side": "reactant"},
                        {"id": "H2", "formula": "H2", "state": "gas", "coefficient": 3, "side": "reactant"},
                        {"id": "NH3", "formula": "NH3", "state": "gas", "coefficient": 2, "side": "product"},
                    ]
                },
                "initial_concentrations": [
                    {"species_id": "N2", "value": 1},
                    {"species_id": "H2", "value": 3},
                    {"species_id": "NH3", "value": 0},
                ],
                "temperature_k": 723,
                "reference_temperature_k": 723,
                "reference_kc": 0.05,
                "forward_enthalpy_j_mol": -92000,
                "volume_l": 1,
                "forward_rate_constant": 0.02,
                "controls": ["temperature", "volume", "catalyst"],
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "equilibrium-sim-predict",
        "chemistry",
        req("equilibrium_sim", {"predict": "poe.chm.equilibrium_catalyst.v1"}),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "population-sim",
        "biology",
        req(
            "population_sim",
            {"model": "logistic", "initial_prey": 20, "growth_rate": 0.8, "carrying_capacity": 500, "duration": 8},
        ),
        modes=("shown",),
        stage="S3",
    ),
    Fixture(
        "population-sim-predator-prey",
        "biology",
        req(
            "population_sim",
            {
                "model": "predator_prey",
                "initial_prey": 40,
                "initial_predator": 9,
                "growth_rate": 1,
                "predation_rate": 0.1,
                "predator_death_rate": 1.5,
                "conversion_rate": 0.075,
                "duration": 30,
            },
        ),
        modes=("shown",),
        stage="S3",
    ),
    # The A level graphs (VSL-07, VSL-46): every figure on them is computed, so a request cites nothing but its data.
    Fixture(
        "exponential-curve",
        "physics",
        req(
            "exponential_curve",
            {
                "initial": 800,
                "constant": 0.2,
                "mode": "decay",
                "time_range": [0, 20],
                "time_unit": "s",
                "quantity_unit": "Bq",
                "mark": "half_life",
            },
            steps=[{"highlight": ["curve"]}, {"highlight": ["half_life"]}],
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "exponential-curve-charge",
        "physics",
        req(
            "exponential_curve",
            {
                "initial": 6,
                "constant": 0.5,
                "mode": "charge",
                "time_range": [0, 10],
                "time_unit": "s",
                "quantity_unit": "V",
                "mark": "time_constant",
            },
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "distribution-curve",
        "mathematics",
        req(
            "distribution_curve",
            {"distribution": "normal", "parameters": {"mean": 50, "sd": 10}, "interval": [40, 65], "tail": "between"},
            steps=[{"highlight": ["mean"]}, {"highlight": ["shade"]}],
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "distribution-curve-binomial",
        "mathematics",
        req(
            "distribution_curve",
            {"distribution": "binomial", "parameters": {"n": 20, "p": 0.3}, "interval": [0, 4], "tail": "less_than"},
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "distribution-curve-poisson",
        "biology",
        req(
            "distribution_curve",
            {"distribution": "poisson", "parameters": {"lambda": 3.5}, "interval": [6, 6], "tail": "greater_than"},
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "data-plot",
        "physics",
        req(
            "data_plot",
            {
                "points": [
                    {"id": "p0", "x": 0, "y": 0},
                    {"id": "p1", "x": 1, "y": 2.1},
                    {"id": "p2", "x": 2, "y": 3.9},
                    {"id": "p3", "x": 3, "y": 6.2},
                    {"id": "p4", "x": 4, "y": 8.0},
                    {"id": "p5", "x": 5, "y": 9.9},
                ],
                "x_label": "Load",
                "y_label": "Extension",
                "x_unit": "N",
                "y_unit": "cm",
                "fit": "linear",
                "show_gradient": True,
            },
            numbers_from=[
                "kn_d0",
                "kn_d1",
                "kn_d2",
                "kn_d3",
                "kn_d4",
                "kn_d5",
                "kn_e1",
                "kn_e2",
                "kn_e3",
                "kn_e4",
                "kn_e5",
            ],
            steps=[{"highlight": ["fit"]}, {"highlight": ["gradient"]}, {"highlight": ["intercept"]}],
        ),
        {
            "kn_d0": "0",
            "kn_d1": "1",
            "kn_d2": "2",
            "kn_d3": "3",
            "kn_d4": "4",
            "kn_d5": "5",
            "kn_e1": "2.1",
            "kn_e2": "3.9",
            "kn_e3": "6.2",
            "kn_e4": "8.0",
            "kn_e5": "9.9",
        },
        stage="S3",
    ),
    Fixture(
        "journal-entry",
        "accounting",
        req(
            "journal_entry",
            {
                "date": "1 March",
                "lines": [
                    {"id": "l1", "account": "Purchases", "side": "debit", "amount": "500"},
                    {"id": "l2", "account": "Cash", "side": "credit", "amount": "500"},
                ],
                "narration": "Goods bought for cash",
                "currency": "$",
            },
            numbers_from=["kn_500"],
        ),
        {"kn_500": "500"},
    ),
    Fixture(
        "t-account",
        "accounting",
        req(
            "t_account",
            {
                "accounts": [
                    {"id": "cash", "name": "Cash", "type": "asset"},
                    {"id": "capital", "name": "Capital", "type": "equity"},
                    {"id": "rent", "name": "Rent", "type": "expense"},
                ],
                "entries": [
                    {"id": "e1", "debit": "cash", "credit": "capital", "amount": "500"},
                    {"id": "e2", "debit": "rent", "credit": "cash", "amount": "120"},
                ],
                "currency": "$",
            },
            numbers_from=["kn_500", "kn_120"],
            steps=[{"highlight": ["cash.e1", "capital.e1"]}, {"highlight": ["cash.balance_cd"]}],
        ),
        {"kn_500": "500", "kn_120": "120"},
    ),
    Fixture(
        "trial-balance",
        "accounting",
        req(
            "trial_balance",
            {
                "as_at": "31 March",
                "source": "from_question",
                "balances": [
                    {"account": "Cash", "side": "debit", "amount": "380"},
                    {"account": "Capital", "side": "credit", "amount": "500"},
                    {"account": "Rent", "side": "debit", "amount": "120"},
                ],
                "currency": "$",
            },
            numbers_from=["kn_380", "kn_500", "kn_120"],
        ),
        {"kn_380": "380", "kn_500": "500", "kn_120": "120"},
    ),
    Fixture(
        "financial-statements",
        "accounting",
        req(
            "financial_statements",
            {
                "statement": "income_statement",
                "business": "A. Trader",
                "period_end": "year ended 31 December",
                "trial_balance": [
                    {"account": "Sales", "role": "revenue", "credit": "9000"},
                    {"account": "Purchases", "role": "purchases", "debit": "5000"},
                    {"account": "Rent", "role": "expense", "debit": "1200"},
                    {"account": "Capital", "role": "capital", "credit": "4000"},
                    {"account": "Bank", "role": "bank", "debit": "6800"},
                ],
                "adjustments": [{"kind": "closing_inventory", "amount": "800"}],
                "currency": "$",
            },
            numbers_from=["kn_9000", "kn_5000", "kn_1200", "kn_4000", "kn_6800", "kn_800"],
        ),
        {
            "kn_9000": "9000",
            "kn_5000": "5000",
            "kn_1200": "1200",
            "kn_4000": "4000",
            "kn_6800": "6800",
            "kn_800": "800",
        },
    ),
    Fixture(
        "bank-reconciliation",
        "accounting",
        req(
            "bank_reconciliation",
            {
                "cash_book_balance": "1200",
                "bank_statement_balance": "1450",
                "cash_book": [{"id": "c1", "direction": "out", "amount": "300", "details": "cheque", "ref": "101"}],
                "bank_statement": [{"id": "s1", "direction": "out", "amount": "50", "details": "bank charges"}],
                "currency": "$",
            },
            numbers_from=["kn_1200", "kn_1450", "kn_300", "kn_50"],
        ),
        {"kn_1200": "1200", "kn_1450": "1450", "kn_300": "300", "kn_50": "50"},
    ),
    Fixture(
        "break-even-chart",
        "accounting",
        req(
            "break_even_chart",
            {
                "fixed_costs": "2000",
                "variable_cost_per_unit": "6",
                "selling_price": "10",
                "output_units": 800,
                "chart_max_units": 1000,
                "currency": "$",
            },
            numbers_from=["kn_fc", "kn_vc", "kn_sp"],
            steps=[{"highlight": ["break_even"]}, {"highlight": ["margin_of_safety"]}],
        ),
        {"kn_fc": "2000", "kn_vc": "6", "kn_sp": "10"},
    ),
    Fixture(
        "probability-tree",
        "mathematics",
        req(
            "probability_tree",
            {
                "branches": [
                    {
                        "id": "R",
                        "label": "red",
                        "p": "3/5",
                        "then": [{"id": "R", "label": "red", "p": "3/5"}, {"id": "B", "label": "blue", "p": "2/5"}],
                    },
                    {
                        "id": "B",
                        "label": "blue",
                        "p": "2/5",
                        "then": [{"id": "R", "label": "red", "p": "3/5"}, {"id": "B", "label": "blue", "p": "2/5"}],
                    },
                ]
            },
            numbers_from=["kn_red", "kn_blue"],
            steps=[{"highlight": ["b_R", "b_R_B"]}, {"highlight": ["o_R_B"]}],
        ),
        {"kn_red": "3/5", "kn_blue": "2/5"},
    ),
    Fixture(
        "transformation-grid",
        "mathematics",
        req(
            "transformation_grid",
            {
                "object": [
                    {"label": "A", "x": 1, "y": 1},
                    {"label": "B", "x": 3, "y": 1},
                    {"label": "C", "x": 1, "y": 2},
                ],
                "transformation": {"kind": "reflection", "line": "y = x"},
                "grid": [-5, 5],
            },
            steps=[{"highlight": ["mirror"]}, {"highlight": ["image"]}],
        ),
    ),
    Fixture(
        "motion-diagram",
        "physics",
        req(
            "motion_diagram",
            {
                "axis": "horizontal",
                "initial_velocity": "2 m/s",
                "acceleration": "1 m/s^2",
                "interval": "1 s",
                "marks": 5,
                "show": ["velocity", "acceleration"],
            },
            numbers_from=["kn_vu", "kn_ra", "kn_dt"],
        ),
        {"kn_vu": "2", "kn_ra": "1", "kn_dt": "1"},
    ),
    # Template presets from the content tree (VSL-29): each validates and renders its golden image.
    Fixture("preset-cyclic-quad", "mathematics", req("geometry_figure", {}, ref="dgm.mth.geometry_cyclic_quad.v1")),
    Fixture(
        "preset-angle-at-centre", "mathematics", req("geometry_figure", {}, ref="dgm.mth.geometry_angle_at_centre.v1")
    ),
    Fixture(
        "preset-tangent-radius", "mathematics", req("geometry_figure", {}, ref="dgm.mth.geometry_tangent_radius.v1")
    ),
    Fixture(
        "preset-parallel-lines",
        "mathematics",
        req(
            "geometry_figure",
            {},
            ref="dgm.mth.geometry_parallel_lines.v1",
            steps=[{"highlight": ["a", "e"]}, {"highlight": ["c", "e"]}, {"highlight": ["d", "e"]}],
        ),
    ),
    Fixture(
        "library-mirror",
        "physics",
        req("library_diagram", {"sequence": "law_of_reflection"}, ref="dgm.phy.plane_mirror_reflection.v1"),
    ),
    Fixture(
        "library-resistance",
        "physics",
        req("library_diagram", {"sequence": "set_up"}, ref="dgm.phy.measuring_resistance.v1"),
    ),
    # The organic and A level chemistry kinds (VSL-06, VSL-07, VSL-46), in A level sessions.
    Fixture(
        "energy-levels",
        "chemistry",
        req(
            "energy_levels",
            {
                "levels": [
                    {"id": "n1", "energy_ev": -13.6, "label": "n = 1"},
                    {"id": "n2", "energy_ev": -3.4, "label": "n = 2"},
                    {"id": "n3", "energy_ev": -1.51, "label": "n = 3"},
                    {"id": "ninf", "energy_ev": 0, "label": "n = \u221e"},
                ],
                "transitions": [{"from": "n3", "to": "n2"}, {"from": "n2", "to": "n1"}, {"from": "n1", "to": "ninf"}],
                "show_photon_energy": True,
            },
            numbers_from=["kn_e1", "kn_e2", "kn_e3", "kn_e4"],
            steps=[{"highlight": ["tr_n3_n2"]}],
        ),
        {"kn_e1": "-13.6", "kn_e2": "-3.4", "kn_e3": "-1.51", "kn_e4": "0"},
        stage="S3",
        level="A",
    ),
    Fixture(
        "orbital-boxes",
        "chemistry",
        req("orbital_boxes", {"element": "S", "charge": 0}, steps=[{"highlight": ["sub_3p"]}]),
        stage="S3",
        level="A",
    ),
    Fixture(
        "maxwell-boltzmann",
        "chemistry",
        req(
            "maxwell_boltzmann",
            {"temperatures_k": [300, 500], "activation_energy_j_mol": 10000, "energy_max_j_mol": 20000},
            numbers_from=["kn_t1", "kn_t2", "kn_ea"],
        ),
        {"kn_t1": "300", "kn_t2": "500", "kn_ea": "10000"},
        stage="S3",
        level="A",
    ),
    Fixture(
        "born-haber-cycle",
        "chemistry",
        req(
            "born_haber_cycle",
            {
                "compound": "NaCl",
                "steps": [
                    {"id": "at_na", "kind": "atomisation", "enthalpy_kj_mol": 107, "coefficient": 1, "orientation": 1},
                    {"id": "at_cl", "kind": "atomisation", "enthalpy_kj_mol": 122, "coefficient": 1, "orientation": 1},
                    {"id": "ie_na", "kind": "ionisation", "enthalpy_kj_mol": 496, "coefficient": 1, "orientation": 1},
                    {
                        "id": "ea_cl",
                        "kind": "electron_affinity",
                        "enthalpy_kj_mol": -349,
                        "coefficient": 1,
                        "orientation": 1,
                    },
                    {"id": "lattice", "kind": "lattice", "coefficient": 1, "orientation": 1},
                    {
                        "id": "formation",
                        "kind": "formation",
                        "enthalpy_kj_mol": -411,
                        "coefficient": 1,
                        "orientation": -1,
                    },
                ],
                "unknown_step": "lattice",
            },
            numbers_from=["kn_atna", "kn_atcl", "kn_ie", "kn_ea", "kn_fm"],
            steps=[{"highlight": ["step_lattice"]}],
        ),
        {"kn_atna": "107", "kn_atcl": "122", "kn_ie": "496", "kn_ea": "-349", "kn_fm": "-411"},
        stage="S3",
        level="A",
    ),
    Fixture(
        "concentration-time",
        "chemistry",
        req(
            "concentration_time",
            {
                "mode": "first_order",
                "species": [{"id": "N2O5", "label": "N2O5", "initial": 0.5, "rate_constant": 0.0115}],
                "time_unit": "s",
                "concentration_unit": "mol/L",
                "time_range": [0, 300],
                "show_initial_tangent": True,
            },
            numbers_from=["kn_c0", "kn_kr"],
        ),
        {"kn_c0": "0.5", "kn_kr": "0.0115"},
        stage="S3",
        level="A",
    ),
    # The exothermic ammonia equilibrium heated at fixed volume: an illustrative response with no measured time scale.
    Fixture(
        "concentration-time-equilibrium",
        "chemistry",
        req(
            "concentration_time",
            {
                "mode": "qualitative_equilibrium",
                "species": [
                    {"id": "N2", "label": "N2", "role": "reactant", "initial_plateau": 0.3, "final_plateau": 0.4},
                    {"id": "H2", "label": "H2", "role": "reactant", "initial_plateau": 0.6, "final_plateau": 0.8},
                    {"id": "NH3", "label": "NH3", "role": "product", "initial_plateau": 0.8, "final_plateau": 0.6},
                ],
                "time_unit": "min",
                "concentration_unit": "relative",
                "time_range": [0, 100],
                "event": {
                    "at": 40,
                    "change": "temperature_increase",
                    "forward_enthalpy_kj_mol": -92,
                    "reaction": {
                        "species": [
                            {"id": "N2", "formula": "N2", "state": "gas", "coefficient": 1, "side": "reactant"},
                            {"id": "H2", "formula": "H2", "state": "gas", "coefficient": 3, "side": "reactant"},
                            {"id": "NH3", "formula": "NH3", "state": "gas", "coefficient": 2, "side": "product"},
                        ]
                    },
                },
            },
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "spectrum-chart",
        "chemistry",
        req(
            "spectrum_chart",
            {"spectrum_id": "dgm.chm.spectrum_ethanol_ir.v1", "type": "infrared", "peaks": ["o_h", "c_o"]},
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "reaction-mechanism",
        "chemistry",
        req(
            "reaction_mechanism",
            {
                "diagram_id": "dgm.chm.mechanism_electrophilic_addition.v1",
                "sequence_id": "electrophilic_addition",
                "step": 1,
            },
            ref="dgm.chm.mechanism_electrophilic_addition.v1",
        ),
        modes=("shown", "hidden", "quiz"),
        stage="S3",
        level="A",
    ),
]

# VSL-05: the Biology kinds, from the renderer package's library and science-asset fixtures (no Biology pack is
# installed yet). Punnett probabilities come from math_evaluate; a gel's sizes and a microscope question's lengths are
# the question's givens.
TALL_SHORT = [
    {"symbol": "T", "phenotype": "tall", "dominance": "dominant"},
    {"symbol": "t", "phenotype": "short", "dominance": "recessive"},
]
CLOTTING = [
    {"symbol": "H", "phenotype": "normal clotting", "dominance": "dominant"},
    {"symbol": "h", "phenotype": "haemophilia", "dominance": "recessive"},
]
GEL_SIZES = {"kn_bp1000": "1000", "kn_bp750": "750", "kn_bp500": "500", "kn_bp250": "250", "kn_bp100": "100"}


def _person(pid: str, generation: int, sex: str, phenotype: str, carrier: bool | None = None) -> dict[str, Any]:
    return {"id": pid, "generation": generation, "sex": sex, "phenotype": phenotype, "carrier": carrier}


FIXTURES += [
    Fixture(
        "punnett-square",
        "biology",
        req(
            "punnett_square",
            {"cross": "monohybrid", "parent1": "Tt", "parent2": "Tt", "alleles": TALL_SHORT},
            steps=[{"highlight": ["parent1", "parent2"]}, {"highlight": ["cell_2_2"]}],
        ),
        stage="S3",
    ),
    Fixture(
        "punnett-sex-linked",
        "biology",
        req(
            "punnett_square",
            {
                "cross": "sex_linked",
                "parent1": "XHXh",
                "parent2": "XHY",
                "alleles": CLOTTING,
                "show": ["gametes", "genotype_ratio", "phenotype_ratio", "probabilities"],
            },
        ),
        stage="S3",
    ),
    Fixture(
        "food-web",
        "biology",
        req(
            "food_web",
            {
                "organisms": [
                    {"id": "grass", "label": "Grass", "trophic_level": 1},
                    {"id": "rabbit", "label": "Rabbit", "trophic_level": 2},
                    {"id": "grasshopper", "label": "Grasshopper", "trophic_level": 2},
                    {"id": "mouse", "label": "Mouse", "trophic_level": 2},
                    {"id": "frog", "label": "Frog", "trophic_level": 3},
                    {"id": "fox", "label": "Fox", "trophic_level": 3},
                    {"id": "hawk", "label": "Hawk", "trophic_level": 4},
                ],
                "links": [
                    {"from": "grass", "to": "rabbit"},
                    {"from": "grass", "to": "grasshopper"},
                    {"from": "grass", "to": "mouse"},
                    {"from": "grasshopper", "to": "frog"},
                    {"from": "rabbit", "to": "fox"},
                    {"from": "mouse", "to": "fox"},
                    {"from": "frog", "to": "hawk"},
                    {"from": "mouse", "to": "hawk"},
                ],
            },
            steps=[{"highlight": ["org.grass"]}, {"highlight": ["link.grass.mouse", "link.mouse.hawk"]}],
        ),
        stage="S3",
    ),
    Fixture(
        "cycle-diagram",
        "biology",
        req(
            "cycle_diagram",
            {"cycle_id": "dgm.bio.carbon_cycle.v1", "start_stage": "air"},
            steps=[{"highlight": ["stage.plants", "link.air.plants"]}, {"highlight": ["stage.decomposers"]}],
        ),
        stage="S3",
    ),
    Fixture(
        "classification-key",
        "biology",
        req(
            "classification_key",
            {"key_id": "dgm.bio.vertebrate_key.v1"},
            steps=[{"highlight": ["node.q_feathers"]}, {"highlight": ["group.mammals"]}],
        ),
        stage="S3",
    ),
    Fixture(
        "pedigree-chart",
        "biology",
        req(
            "pedigree_chart",
            {
                "individuals": [
                    _person("grandfather", 1, "male", "unaffected", True),
                    _person("grandmother", 1, "female", "unaffected", True),
                    _person("aunt", 2, "female", "unaffected"),
                    _person("uncle", 2, "male", "affected"),
                    _person("father", 2, "male", "unaffected"),
                    _person("mother", 2, "female", "unaffected", False),
                    _person("daughter", 3, "female", "unknown"),
                    _person("son", 3, "male", "unaffected"),
                ],
                "parents": [
                    {"child": "aunt", "parent1": "grandfather", "parent2": "grandmother"},
                    {"child": "uncle", "parent1": "grandfather", "parent2": "grandmother"},
                    {"child": "father", "parent1": "grandfather", "parent2": "grandmother"},
                    {"child": "daughter", "parent1": "father", "parent2": "mother"},
                    {"child": "son", "parent1": "father", "parent2": "mother"},
                ],
            },
            steps=[{"highlight": ["ind.grandfather", "ind.grandmother"]}, {"highlight": ["ind.uncle"]}],
        ),
        stage="S3",
        level="A",
    ),
    Fixture(
        "gel-electrophoresis",
        "biology",
        req(
            "gel_electrophoresis",
            {
                "ladder_bp": [1000, 750, 500, 250, 100],
                "lanes": [
                    {"id": "scene", "label": "Crime scene", "fragments_bp": [750, 250]},
                    {"id": "suspect_a", "label": "Suspect A", "fragments_bp": [500, 250, 100]},
                    {"id": "suspect_b", "label": "Suspect B", "fragments_bp": [250, 750]},
                ],
                "migration": "log_size",
            },
            numbers_from=list(GEL_SIZES),
            steps=[{"highlight": ["lane.scene.b1", "lane.suspect_b.b1"]}],
        ),
        GEL_SIZES,
        stage="S3",
        level="A",
    ),
    Fixture(
        "microscope-view",
        "biology",
        req(
            "microscope_view",
            {
                "diagram_id": "dgm.bio.onion_cells.v1",
                "image_length_mm": 25,
                "actual_length_um": 250,
                "show_scale": True,
                "lengths_from": "kn_drawn",
            },
            ref="dgm.bio.onion_cells.v1",
            numbers_from=["kn_drawn", "kn_actual"],
            steps=[{"highlight": ["nucleus"]}, {"highlight": ["magnification"]}],
        ),
        {"kn_drawn": "25", "kn_actual": "250"},
        modes=("shown", "hidden", "quiz"),
        stage="S3",
    ),
    Fixture(
        "diagram-comparison",
        "biology",
        req(
            "diagram_comparison",
            {"left_ref": "dgm.bio.plant_cell.v1", "right_ref": "dgm.bio.animal_cell.v1", "pair_id": "plant_animal"},
            ref="dgm.bio.plant_cell.v1",
            steps=[{"highlight": ["left.nucleus", "right.nucleus"]}],
        ),
        modes=("shown", "hidden", "quiz"),
        stage="S3",
    ),
]

# VSL-31: the sample points each simulation's readouts must match its tool at, to 3 significant figures.
FIDELITY_POINTS: dict[str, list[dict[str, Any]]] = {
    "projectile_sim": [
        {"mode": "horizontal", "speed": 12, "height": 20},
        {"mode": "horizontal", "speed": 5, "height": 45},
        {"mode": "horizontal", "speed": 30, "height": 80},
        {"mode": "vertical", "speed": 15, "height": 0},
        {"mode": "vertical", "speed": 20, "height": 10},
        {"mode": "vertical", "speed": 8, "height": 35},
    ],
    "circuit_sim": [
        {"emf": 6, "arrangement": "series", "R1": 4, "R2": 2},
        {"emf": 12, "arrangement": "parallel", "R1": 3, "R2": 6},
        {"emf": 9, "arrangement": "series", "R1": 10, "R2": 20, "R3": 30},
        {"emf": 1.5, "arrangement": "parallel", "R1": 5, "R2": 5, "R3": 10},
        {"emf": 24, "arrangement": "series", "R1": 100},
    ],
    "gas_laws_sim": [
        {"amount_mol": 0.00411, "temperature": 293, "volume": 100},
        {"amount_mol": 0.00411, "temperature": 313, "volume": 100},
        {"amount_mol": 0.008, "temperature": 300, "volume": 200},
        {"amount_mol": 0.008, "temperature": 300, "volume": 50},
        {"amount_mol": 0.02, "temperature": 600, "volume": 500},
        {"amount_mol": 0.001, "temperature": 100, "volume": 20},
    ],
    "function_transform_sim": [
        {"expression": "x^2", "a": 1, "b": 1, "c": 3, "d": 0, "x": [-6, -3, 0, 2.5]},
        {"expression": "x^2", "a": -2, "b": 0.5, "c": -1, "d": 4, "x": [-4, 0, 1, 5]},
        {"expression": "x^3 - 3*x", "a": 0.5, "b": 2, "c": 1, "d": -2, "x": [-3, -1.5, 0.5, 2]},
        {"expression": "sqrt(x)", "a": 3, "b": 1, "c": 2, "d": 1, "x": [-2, 0, 2, 7]},
        {"expression": "2^x", "a": 1, "b": -1, "c": 0, "d": -3, "x": [-3, 0, 1.5, 4]},
    ],
    "electrolysis_sim": [
        {"preset_id": "sim.chm.electrolysis_brine.v1", "current": 1, "time": 600},
        {"preset_id": "sim.chm.electrolysis_lead_bromide.v1", "current": 2.5, "time": 1200},
        {"preset_id": "sim.chm.electrolysis_copper_sulfate.v1", "current": 2, "time": 1800},
        {"preset_id": "sim.chm.electrolysis_copper_refining.v1", "current": 0.5, "time": 3600},
        {"preset_id": "sim.chm.electrolysis_dilute_sulfuric_acid.v1", "current": 5, "time": 300},
    ],
    "rates_sim": [
        {"a": 8200000, "ea": 50000, "temperature": 293, "concentration": 0.5, "time": 60},
        {"a": 8200000, "ea": 50000, "temperature": 313, "concentration": 0.5, "time": 60},
        {"a": 8200000, "ea": 35000, "temperature": 293, "concentration": 0.5, "time": 30},
        {"a": 300000000, "ea": 60000, "temperature": 373, "concentration": 2, "time": 5},
        {"a": 300000000, "ea": 60000, "temperature": 273, "concentration": 0.1, "time": 3000},
    ],
    # Equilibrium: H2 + I2 = 2HI (Kc 54 at 698 K, -9.5 kJ/mol) and N2 + 3H2 = 2NH3 (Kc 0.05 at 723 K, -92 kJ/mol), at
    # and away from the reference temperature, with and without a catalyst, and with the gases compressed.
    "equilibrium_sim": [
        {"reaction": "hi", "temperature": 698, "volume": 1, "catalyst": False},
        {"reaction": "hi", "temperature": 698, "volume": 1, "catalyst": True},
        {"reaction": "hi", "temperature": 850, "volume": 1, "catalyst": False},
        {"reaction": "haber", "temperature": 723, "volume": 1, "catalyst": False},
        {"reaction": "haber", "temperature": 623, "volume": 1, "catalyst": False},
        {"reaction": "haber", "temperature": 723, "volume": 0.5, "catalyst": True},
    ],
    # Population: logistic growth towards, and down to, its carrying capacity (the closed form at the end of a run), and
    # Lotka-Volterra cycles (the equilibrium and the conserved quantity the model must keep).
    "population_sim": [
        {"model": "logistic", "prey": 20, "rate": 0.8, "capacity": 500, "time": 5},
        {"model": "logistic", "prey": 20, "rate": 0.8, "capacity": 500, "time": 10},
        {"model": "logistic", "prey": 900, "rate": 0.3, "capacity": 400, "time": 6},
        {"model": "logistic", "prey": 5, "rate": 1.5, "capacity": 2000, "time": 4},
        {"model": "predator_prey", "prey": 40, "predator": 9, "a": 1, "b": 0.1, "c": 1.5, "d": 0.075, "time": 30},
        {"model": "predator_prey", "prey": 10, "predator": 5, "a": 0.5, "b": 0.02, "c": 0.4, "d": 0.01, "time": 60},
        {"model": "predator_prey", "prey": 80, "predator": 3, "a": 2, "b": 0.5, "c": 0.8, "d": 0.02, "time": 20},
    ],
    "titration_sim": [
        {"acid_concentration": 0.1, "base_concentration": 0.1, "acid_volume": 25},
        {"acid_concentration": 0.2, "base_concentration": 0.1, "acid_volume": 20},
        {"acid_concentration": 0.05, "base_concentration": 0.1, "acid_volume": 30},
    ],
}


# The reactions the equilibrium fidelity points use (the client model's setup shape).
EQUILIBRIUM_REACTIONS: dict[str, dict[str, Any]] = {
    "hi": {
        "species": [
            {"id": "H2", "formula": "H2", "state": "gas", "coefficient": 1, "side": "reactant"},
            {"id": "I2", "formula": "I2", "state": "gas", "coefficient": 1, "side": "reactant"},
            {"id": "HI", "formula": "HI", "state": "gas", "coefficient": 2, "side": "product"},
        ],
        "initial": {"H2": 1, "I2": 1, "HI": 0},
        "reference_temperature_k": 698,
        "reference_kc": 54,
        "forward_enthalpy_j_mol": -9500,
        "volume_l": 1,
        "forward_rate_constant": 0.05,
    },
    "haber": {
        "species": [
            {"id": "N2", "formula": "N2", "state": "gas", "coefficient": 1, "side": "reactant"},
            {"id": "H2", "formula": "H2", "state": "gas", "coefficient": 3, "side": "reactant"},
            {"id": "NH3", "formula": "NH3", "state": "gas", "coefficient": 2, "side": "product"},
        ],
        "initial": {"N2": 1, "H2": 3, "NH3": 0},
        "reference_temperature_k": 723,
        "reference_kc": 0.05,
        "forward_enthalpy_j_mol": -92000,
        "volume_l": 1,
        "forward_rate_constant": 0.02,
    },
}


# --- context: conventions, presets and the library ------------------------------------------------------------------


def _conventions(root: Path) -> dict[str, list[dict[str, Any]]]:
    out = {}
    for path in sorted((root / CURRICULUM / "ref").glob("*/conventions.yaml")):
        out[path.parent.name.split("-")[0]] = yaml.safe_load(path.read_text()) or []
    return out


def _library(root: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], list[str]]:
    """Library entries (with their pipeline-checked SVG) and presets from the content tree and the renderer
    package's test fixtures; problems if any entry fails the diagram pipeline (VSL-34)."""
    from agent_core.config import Settings
    from agent_core.store.svg import normalise
    from pack_builder.diagrams import diagram_problems, diagram_svg

    settings = Settings()
    diagrams: dict[str, dict[str, Any]] = {}
    presets: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    pack_dirs = sorted(p.parent for p in (root / CURRICULUM).glob("*/*/pack.yaml"))
    for pack_dir in pack_dirs:
        pack_id = (yaml.safe_load((pack_dir / "pack.yaml").read_text()) or {}).get("pack_id")
        for path in sorted((pack_dir / "diagrams").glob("*.yaml")):
            entry = yaml.safe_load(path.read_text())
            svg, missing = diagram_svg(pack_dir, entry)
            found = missing + diagram_problems(entry, svg, settings)
            problems += found
            if not found and svg is not None:
                diagrams[entry["id"]] = {**entry, "svg": svg}
        for path in sorted((pack_dir / "presets").glob("*.yaml")):
            preset = yaml.safe_load(path.read_text())
            presets[preset["id"]] = {**preset, "pack_id": pack_id}
    for path in sorted((root / LIBRARY_DIR).glob("*.json")):
        entry = json.loads(path.read_text())
        svg_path = root / LIBRARY_DIR / Path(entry["svg_path"]).name
        svg = normalise(svg_path.read_text()) if svg_path.is_file() else None
        found = diagram_problems(entry, svg, settings) + (
            [] if svg else [f"{entry['id']}: no drawing at {svg_path.name}"]
        )
        problems += found
        if not found and svg is not None:
            diagrams[entry["id"]] = {**entry, "svg": svg}
    return diagrams, presets, problems


# Each science asset kind's definition in the contract (content schema 1.6).
ASSET_DEFINITIONS = {"cycle": "Cycle", "classification_key": "Key", "spectrum": "Spectrum", "enzyme": "Enzyme",
                     "osmosis": "Osmosis"}  # fmt: skip


def science_assets(root: Path) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """The renderer package's science asset fixtures (content schema 1.6 `science_assets`, VSL-46): each definition
    checked against its kind's contract, and a full record (one carrying its sources) against the asset contract;
    problems if one fails."""
    from agent_core.contracts import errors as contract_errors

    assets: dict[str, dict[str, Any]] = {}
    problems: list[str] = []
    for path in sorted((root / SCIENCE_DIR).glob("*.json")):
        asset = json.loads(path.read_text())
        definition = f"content/science-assets#/$defs/{ASSET_DEFINITIONS.get(asset['kind'], 'Asset')}"
        found = [f"{asset['id']}: {e}" for e in contract_errors(definition, asset["definition"])]
        if "sources" in asset:
            found += [f"{asset.get('id')}: {e}" for e in contract_errors("content/science-assets#/$defs/Asset", asset)]
        problems += found
        if not found:
            assets[asset["id"]] = {**asset, "pack_id": asset.get("pack_id", "pack.renderers.fixtures")}
    return assets, problems


def _numbers(value: Any) -> list[Fraction]:
    """Every figure in a tool result, as the validator compares claims with (VSL-12)."""
    from pack_builder.verify import Check

    check = Check("chk_build_x", "", 0, "", "", value)
    out = []
    for d in check.numbers():
        try:
            out.append(Fraction(str(d)))
        except (ValueError, ArithmeticError):
            continue
    return out


def _call(prefix: str) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    from pack_builder.verify import run_check

    counter = {"n": 0}

    def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        counter["n"] += 1
        check_id = f"chk_build_fx_{prefix}_{counter['n']}"
        check = run_check(check_id, {"tool": tool, "args": json.loads(json.dumps(args))})
        return {"value": check.value, "check": {"check_id": check_id, "function": check.function}}

    return call


def resolve_fixture(
    fx: Fixture,
    diagrams: dict[str, dict[str, Any]],
    presets: dict[str, dict[str, Any]],
    conventions: dict[str, list[dict[str, Any]]],
    science: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    from agent_core.assets.resolvers import resolver
    from agent_core.assets.visuals import Resolver, VisualContext, validate
    from pack_builder.verify import run_check

    code = SUBJECT_CODES[fx.subject]
    pack_id = f"pack.{code}.o"
    own = conventions.get(code, [])
    pack_values: dict[str, Fraction] = {}
    for c in own:
        try:
            pack_values[f"pack:{pack_id}/conventions/{c['key']}"] = Fraction(str(c["value"]))
        except (ValueError, ZeroDivisionError):
            continue
    slug = re.sub(r"[^a-z0-9]", "_", fx.id)
    check_values: dict[str, list[Fraction]] = {}
    for n, (tool, args) in enumerate(fx.checks, 1):
        check_id = f"chk_build_fx_{slug}_c{n}"
        check_values[check_id] = _numbers(run_check(check_id, {"tool": tool, "args": args}).value)
    ctx = VisualContext(
        fx.subject,
        fx.level,
        fx.stage,
        check_values=check_values,
        knowns={k: Fraction(v) for k, v in fx.givens.items()},
        pack_values=pack_values,
        diagrams=diagrams,
        presets=presets,
        conventions={c["key"]: str(c["value"]) for c in own},
        science_assets=dict(science or {}),
    )
    resolved, _ = validate(fx.request, ctx, Resolver(resolver(_call(slug), ctx.conventions)))
    return resolved


def claims(resolved: dict[str, Any]) -> list[str]:
    """The figures a fixture may show: its traced claim numbers and its computed labels (the oracle list the
    renderer tests hold every drawn number to)."""
    from agent_core.assets.visual_kinds import claim_numbers

    out = [written for written, _ in claim_numbers(resolved["type"], resolved["params"])]

    def walk(node: Any) -> None:
        # Everything in `computed` came from a traced tool result or pack data (its check ids and pack references
        # are in numbers_from); the drawing (svg) is the library's, not figures.
        if isinstance(node, dict):
            for key, value in node.items():
                if key not in ("svg", "check_ids", "pack_refs", "parts"):
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)
        elif isinstance(node, str):
            out.extend(re.findall(r"-?\d+(?:\.\d+)?(?:/\d+)?", node))
        elif isinstance(node, int | float) and not isinstance(node, bool):
            out.append(repr(node) if isinstance(node, float) else str(node))

    walk(resolved.get("computed", {}))
    return sorted(set(out))


# --- simulation fidelity (VSL-31) ------------------------------------------------------------------------------------


def fidelity(conventions: dict[str, list[dict[str, Any]]]) -> dict[str, Any]:
    def dec(value: dict[str, Any]) -> str:
        return str(Decimal(str(value["decimal"])).normalize())

    from agent_core.assets.generated.sim_presets import SIM_PRESETS
    from agent_core.assets.resolvers import GAS_CONSTANT, _molar_mass, _transformed
    from pack_builder.verify import run_check

    g = next(str(c["value"]) for c in conventions["phy"] if c["key"] == "phy.g")
    out: dict[str, Any] = {
        "$comment": "VSL-31: tool readouts at each simulation's declared sample points (generated).",
        "g": float(g),
    }
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["projectile_sim"], 1):
        args: dict[str, Any] = {
            "motion": p["mode"],
            "speed": p["speed"],
            "height": p["height"],
            "g": g,
            "g_source": "pack",
        }
        if p["mode"] == "vertical":
            args["direction"] = "up"
        v = run_check(f"chk_build_fid_projectile_{n}", {"tool": "phys_projectile", "args": args}).value
        rows.append(
            {
                "params": p,
                "tool": "phys_projectile",
                "readouts": {
                    "out.time": dec(v["time_of_flight"]),
                    "out.range": dec(v["range"]),
                    "out.max_height": dec(v["max_height"]),
                },
            }
        )
    out["projectile_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["circuit_sim"], 1):
        ids = sorted(k for k in p if re.fullmatch(r"R\d", k))
        components = [{"id": "B", "kind": "battery", "emf": p["emf"]}] + [
            {"id": r, "kind": "resistor", "resistance": p[r]} for r in ids
        ]
        group = {"parallel": ids} if p["arrangement"] == "parallel" and len(ids) > 1 else {"series": ids}
        v = run_check(
            f"chk_build_fid_circuit_{n}",
            {"tool": "phys_circuit", "args": {"components": components, "network": {"series": ["B", group]}}},
        ).value
        readouts = {"out.current": dec(v["total_current"]), "out.resistance": dec(v["equivalent_resistance"])}
        readouts |= {f"out.pd_{r}": dec(v["components"][r]["pd"]) for r in ids}
        rows.append({"params": p, "tool": "phys_circuit", "readouts": readouts})
    out["circuit_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["titration_sim"], 1):
        end = (
            Fraction(str(p["acid_concentration"]))
            * Fraction(str(p["acid_volume"]))
            / Fraction(str(p["base_concentration"]))
        )
        at = [Fraction(0), end / 2, end, end * Fraction(3, 2)]
        args = {
            "task": "titration_curve",
            "analyte": "acid",
            "acid": "HCl",
            "acid_strength": "strong",
            "base": "NaOH",
            "base_strength": "strong",
            "acid_concentration": f"{p['acid_concentration']} mol dm^-3",
            "acid_volume": f"{p['acid_volume']} cm^3",
            "base_concentration": f"{p['base_concentration']} mol dm^-3",
            "at_volumes": [f"{float(v):g} cm^3" for v in at],
        }
        v = run_check(f"chk_build_fid_titration_{n}", {"tool": "chem_acid_base", "args": args}).value
        samples = [
            {"volume": float(a["volume"]["decimal"]), "out.ph": str(Decimal(a["ph"]["decimal"]).normalize())}
            for a in v["at"]
        ]
        rows.append(
            {
                "params": p,
                "tool": "chem_acid_base",
                "samples": samples,
                "end_point": str(Decimal(v["equivalence"]["volume"]["decimal"]).normalize()),
            }
        )
    out["titration_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["gas_laws_sim"], 1):
        # p = nRT/V in kPa, with V in cm³ (the model's R; VSL-46: ideal gas, SI units).
        expression = f"{p['amount_mol']}*{GAS_CONSTANT}*{p['temperature']}/({p['volume']}*10^(-6))/1000"
        v = run_check(f"chk_build_fid_gas_{n}", {"tool": "math_evaluate", "args": {"expression": expression}}).value
        rows.append({"params": p, "tool": "math_evaluate", "readouts": {"out.pressure": dec(v["exact"])}})
    out["gas_laws_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["function_transform_sim"], 1):
        # y = a f(b(x + c)) + d at sample x values, and the tracked point from x0 = 0.
        curve = _transformed(p["expression"], p)
        samples = []
        for k, x in enumerate(p["x"], 1):
            at = re.sub(r"(?<![a-z])x(?![a-z])", f"({x})", curve)
            v = run_check(
                f"chk_build_fid_function_{n}_{k}", {"tool": "math_evaluate", "args": {"expression": at}}
            ).value
            samples.append({"x": x, "y": dec(v["exact"])})
        f0 = re.sub(r"(?<![a-z])x(?![a-z])", "(0)", p["expression"])
        point = f"({p['a']})*({f0})+({p['d']})"
        v = run_check(f"chk_build_fid_function_{n}_y0", {"tool": "math_evaluate", "args": {"expression": point}}).value
        u = run_check(
            f"chk_build_fid_function_{n}_x0",
            {"tool": "math_evaluate", "args": {"expression": f"0/({p['b']})-({p['c']})"}},
        ).value
        rows.append(
            {
                "params": p,
                "tool": "math_evaluate",
                "samples": samples,
                "readouts": {"out.point_x": dec(u["exact"]), "out.point_y": dec(v["exact"])},
            }
        )
    out["function_transform_sim"] = rows
    # electrolysis_sim: Q = It and each electrode's amount, from the pack's Faraday constant, molar volume and Ar.
    chm = {c["key"]: str(c["value"]) for c in conventions["chm"]}
    molar_mass: dict[str, float] = {}
    out["electrolysis_constants"] = {
        "faraday": float(chm["chem.faraday"]),
        "vm_cm3": float(chm["chem.vm"]) * 1000,
        "molar_mass": molar_mass,
    }
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["electrolysis_sim"], 1):
        preset = SIM_PRESETS[p["preset_id"]]
        readouts = {}
        for side in ("cathode", "anode"):
            product = preset[side]
            moles = f"{p['current']}*{p['time']}/({product['electrons']}*{chm['chem.faraday']})"
            if product["measure"] == "gas":
                expression, key = f"{moles}*{chm['chem.vm']}*1000", f"out.{side}_gas"
            else:
                sign = "-" if product["measure"] == "dissolves" else ""
                expression, key = f"{sign}{moles}*{_molar_mass(product['formula'], chm)}", f"out.{side}_mass"
                mass = run_check(
                    f"chk_build_fid_electrolysis_{n}_{side}_mr",
                    {"tool": "math_evaluate", "args": {"expression": _molar_mass(product["formula"], chm)}},
                )
                molar_mass[product["formula"]] = float(mass.value["exact"]["decimal"])
            v = run_check(
                f"chk_build_fid_electrolysis_{n}_{side}", {"tool": "math_evaluate", "args": {"expression": expression}}
            )
            readouts[key] = dec(v.value["exact"])
        rows.append({"params": p, "tool": "math_evaluate", "readouts": readouts})
    out["electrolysis_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["rates_sim"], 1):
        # k = A exp(-Ea/RT) and the product c0 (1 - exp(-kt)) at time t (simplified first order).
        k = f"{p['a']}*exp(-{p['ea']}/({GAS_CONSTANT}*{p['temperature']}))"
        product = f"{p['concentration']}*(1-exp(-{k}*{p['time']}))"
        readouts = {}
        for key, expression in (("out.rate_constant", k), ("out.product", product)):
            v = run_check(
                f"chk_build_fid_rates_{n}_{key[4:]}", {"tool": "math_evaluate", "args": {"expression": expression}}
            )
            readouts[key] = dec(v.value["exact"])
        rows.append({"params": p, "tool": "math_evaluate", "readouts": readouts})
    out["rates_sim"] = rows
    out["equilibrium_reactions"] = EQUILIBRIUM_REACTIONS
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["equilibrium_sim"], 1):
        # Kc at T by van't Hoff (math_evaluate), then the extent from the mixture (math_solve; gases scaled to the
        # volume), and the equilibrium concentrations from that one extent.
        r = EQUILIBRIUM_REACTIONS[p["reaction"]]
        kc = (
            f"{r['reference_kc']}*exp(-({r['forward_enthalpy_j_mol']})/{GAS_CONSTANT}"
            f"*(1/{p['temperature']}-1/{r['reference_temperature_k']}))"
        )
        kv = run_check(f"chk_build_fid_equilibrium_{n}_kc", {"tool": "math_evaluate", "args": {"expression": kc}}).value
        start = {sp["id"]: r["initial"][sp["id"]] * r["volume_l"] / p["volume"] for sp in r["species"]}
        top = [
            f"({start[sp['id']]}+{sp['coefficient']}*x)^{sp['coefficient']}"
            for sp in r["species"]
            if sp["side"] == "product"
        ]
        bottom = [
            f"({start[sp['id']]}-{sp['coefficient']}*x)^{sp['coefficient']}"
            for sp in r["species"]
            if sp["side"] == "reactant"
        ]
        hi = min(start[sp["id"]] / sp["coefficient"] for sp in r["species"] if sp["side"] == "reactant")
        equation = f"{'*'.join(top)} = ({kv['exact']['decimal']})*{'*'.join(bottom)}"
        sv = run_check(
            f"chk_build_fid_equilibrium_{n}",
            {"tool": "math_solve", "args": {"equations": [equation], "unknowns": ["x"]}},
        ).value
        roots = [
            Decimal(s["x"]["decimal"]) for s in sv["solutions"] if "x" in s and 0 <= float(s["x"]["decimal"]) <= hi
        ]
        if len(roots) != 1:
            raise ValueError(f"equilibrium fidelity point {n}: {len(roots)} admissible extents")
        readouts = {"out.kc": dec(kv["exact"])}
        for sp in r["species"]:
            sign = 1 if sp["side"] == "product" else -1
            readouts[f"out.c_{sp['id']}"] = str(
                (Decimal(str(start[sp["id"]])) + sign * sp["coefficient"] * roots[0]).normalize()
            )
        rows.append({"params": p, "tool": "math_solve", "readouts": readouts})
    out["equilibrium_sim"] = rows
    rows = []
    for n, p in enumerate(FIDELITY_POINTS["population_sim"], 1):
        if p["model"] == "logistic":
            # N(t) = K N0 / (N0 + (K - N0) e^(-rt)), the logistic equation's closed form.
            n0, k = p["prey"], p["capacity"]
            expressions = {"out.prey": f"{k}*{n0}/({n0}+({k}-{n0})*exp(-{p['rate']}*{p['time']}))"}
        else:
            # The equilibrium (c/d, a/b) and dx - c ln x + by - a ln y, constant along every trajectory.
            x, y = p["prey"], p["predator"]
            expressions = {
                "eq.prey": f"{p['c']}/{p['d']}",
                "eq.predator": f"{p['a']}/{p['b']}",
                "conserved": f"{p['d']}*{x}-{p['c']}*ln({x})+{p['b']}*{y}-{p['a']}*ln({y})",
            }
        readouts = {}
        for key, expression in expressions.items():
            v = run_check(
                f"chk_build_fid_population_{n}_{key.replace('.', '_')}",
                {"tool": "math_evaluate", "args": {"expression": expression}},
            )
            readouts[key] = format(Decimal(dec(v.value["exact"])), "f")  # 20, not 2E+1
        rows.append({"params": p, "tool": "math_evaluate", "readouts": readouts})
    out["population_sim"] = rows
    return out


# --- gallery states ---------------------------------------------------------------------------------------------------


def gallery_states(fixtures: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """One VisualViewer state per fixture and label mode (vsl03_core_fixture_coverage), plus reduced motion and the
    words fallback of a spec that fails client validation (UIA-20)."""
    states: dict[str, dict[str, Any]] = {}
    for fid, fx in fixtures.items():
        for mode in fx["modes"]:
            variant = fid if mode == "shown" else f"{fid}-{mode}"
            payload = {**fx["spec"], "labels": mode}
            state_id = f"{GALLERY_PREFIX}canonical.{variant}"
            states[state_id] = {
                "id": state_id,
                "title": f"Visual: {fid.replace('-', ' ')} ({mode} labels)",
                "component": "VisualViewer",
                "state": "canonical",
                "variant": variant,
                "payload": payload,
                "payloadContract": "https://jana.dev/contracts/visuals/visual-spec#/$defs/resolved",
                "context": {"theme": "light"},
                "placements": ["conversation"],
            }
    motion = fixtures["projectile-sim"]["spec"]
    states[f"{GALLERY_PREFIX}reduced-motion"] = {
        "id": f"{GALLERY_PREFIX}reduced-motion",
        "title": "Visual: a simulation under reduced motion",
        "component": "VisualViewer",
        "state": "reduced-motion",
        "payload": motion,
        "payloadContract": "https://jana.dev/contracts/visuals/visual-spec#/$defs/resolved",
        "context": {"theme": "light", "reducedMotion": True},
        "placements": ["conversation"],
    }
    broken = {**fixtures["free-body"]["spec"], "params": {"object": "block", "forces": []}}
    states[f"{GALLERY_PREFIX}error-final"] = {
        "id": f"{GALLERY_PREFIX}error-final",
        "title": "Visual: a spec the client refuses, shown in words",
        "note": "Its params fail the free_body schema on the client (UIA-20), so the viewer shows the words fallback.",
        "component": "VisualViewer",
        "state": "error-final",
        "payload": broken,
        "payloadContract": None,
        "context": {"theme": "light"},
        "placements": ["conversation"],
        "expectText": [broken["alt"]["summary"]],
    }
    return states


def catalogue(stage: str = "S2") -> dict[str, Any]:
    """The register's kinds up to `stage`, for the client tests (VSL-02, VSL-03): kind, renderer, channel, group."""
    from agent_core.assets.generated.visual_catalogue import VISUAL_CATALOGUE

    order = ("S1", "S2", "S3", "S4", "S5")
    keep = ("kind", "renderer", "stage", "priority", "group", "channel", "subjects", "numbers_rule")
    kinds = [
        {k: row[k] for k in keep if k in row}
        for row in VISUAL_CATALOGUE["kinds"]
        if order.index(row["stage"]) <= order.index(stage)
    ]
    return {
        "$comment": "Generated from registers/visual-catalogue.json for the client tests.",
        "stage": stage,
        "kinds": kinds,
    }


def _dump(value: Any) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def generate(root: Path = REPO_ROOT) -> tuple[dict[Path, str], list[str]]:
    """Every generated file (path relative to the root -> text), and the problems found on the way."""
    diagrams, presets, problems = _library(root)
    science, found = science_assets(root)
    problems += found
    conventions = _conventions(root)
    files: dict[Path, str] = {}
    resolved: dict[str, dict[str, Any]] = {}
    for fx in FIXTURES:
        try:
            spec = resolve_fixture(fx, diagrams, presets, conventions, science)
        except Exception as error:
            problems.append(f"{fx.id}: {type(error).__name__}: {error}")
            continue
        record = {
            "id": fx.id,
            "kind": spec["type"],
            "subject": fx.subject,
            "modes": list(fx.modes),
            "spec": spec,
            "claims": claims(spec),
        }
        resolved[fx.id] = record
        files[VISUALS_DIR / f"{fx.id}.json"] = _dump(record)
    files[FIDELITY] = _dump(fidelity(conventions))
    files[CATALOGUE] = _dump(catalogue())
    if "projectile-sim" in resolved and "free-body" in resolved:
        for state_id, state in gallery_states(resolved).items():
            files[GALLERY_DIR / f"{state_id}.json"] = _dump(state)
    return files, problems


def stale(root: Path = REPO_ROOT) -> list[str]:
    files, problems = generate(root)
    out = list(problems)
    for rel, text in files.items():
        path = root / rel
        if not path.is_file() or path.read_text() != text:
            out.append(f"{rel}: stale (run python -m jana_tools visual-fixtures --write)")
    have = {p.relative_to(root) for p in (root / VISUALS_DIR).glob("*.json")}
    have |= {p.relative_to(root) for p in (root / GALLERY_DIR).glob(f"{GALLERY_PREFIX}*.json")}
    out += [f"{rel}: not generated by any fixture" for rel in sorted(have - set(files))]
    return out


def write(root: Path = REPO_ROOT) -> list[str]:
    files, problems = generate(root)
    if problems:
        return problems
    for path in [*(root / VISUALS_DIR).glob("*.json"), *(root / GALLERY_DIR).glob(f"{GALLERY_PREFIX}*.json")]:
        if path.relative_to(root) not in files:
            path.unlink()
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text)
    return []
