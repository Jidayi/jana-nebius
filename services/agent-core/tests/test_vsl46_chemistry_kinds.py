"""The organic and A level chemistry kinds in the engine (VSL-06, VSL-07, VSL-46): each resolves through its contract
schema with tool-checked or pack-traced figures, part ids from the params' own ids, declared build layers and generated
alt text, and refuses duplicate ids, broken references, reversed ranges, inconsistent units, unsupported models and
out-of-pack ids. chem_organic (VER-33) is not in the worker yet, so organic_structure resolves here against a stand-in
that returns contract-valid results; with the real worker it fails closed (`visual_resolution_failed`)."""

import json
import math
from fractions import Fraction
from functools import cache
from typing import Any

import pytest
from agent_core.assets.chemistry_kinds import configuration
from agent_core.assets.generated.visual_catalogue import VISUAL_CATALOGUE
from agent_core.assets.resolvers import ResolutionError, resolver
from agent_core.assets.visual_kinds import View, layers_of, parts_of
from agent_core.assets.visuals import FREEFORM, Resolver, VisualContext, VisualError, kind_param_errors, validate
from agent_core.contracts import document
from agent_core.contracts import errors as contract_errors
from agent_core.engine.tool_drawings import checked
from jana_tools import REPO_ROOT
from jana_tools.visual_fixtures import FIXTURES, _conventions, _library, science_assets

KINDS = (
    "organic_structure", "reaction_mechanism", "energy_levels", "orbital_boxes", "maxwell_boltzmann",
    "born_haber_cycle", "concentration_time", "spectrum_chart",
)  # fmt: skip
FIXTURES_DIR = REPO_ROOT / "packages" / "renderers" / "fixtures" / "visuals"
MECHANISM = "dgm.chm.mechanism_electrophilic_addition.v1"
SPECTRUM = "dgm.chm.spectrum_ethanol_ir.v1"


# --- a stand-in for chem_organic (VER-33): contract-valid results for the curated but-2-ene names ----------------


def _molecule(points: list[tuple[float, float]]) -> str:
    """A skeletal drawing: four carbons, three bonds, the middle one double; atom and bond ids as data-part."""
    ink = 'stroke="var(--color-diagram-stroke)" stroke-width="1.5"'
    bonds = [(0, 1, "b1"), (1, 2, "b2"), (2, 3, "b3")]
    lines = []
    for a, b, bid in bonds:
        (x1, y1), (x2, y2) = points[a], points[b]
        lines.append(f'<line data-part="{bid}" x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" {ink}/>')
    (x1, y1), (x2, y2) = points[1], points[2]
    lines.append(f'<line x1="{x1}" y1="{y1 + 8}" x2="{x2}" y2="{y2 + 8}" {ink}/>')
    atoms = [f'<circle data-part="a{n + 1}" cx="{x}" cy="{y}" r="3" fill="var(--color-diagram-stroke)"/>'
             for n, (x, y) in enumerate(points)]  # fmt: skip
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 160">{"".join(lines + atoms)}</svg>'


BUT_2_ENE = {
    "(E)-but-2-ene": {"canonical_smiles": "C/C=C/C", "points": [(30, 110), (70, 60), (130, 60), (170, 10)]},
    "(Z)-but-2-ene": {"canonical_smiles": "C/C=C\\C", "points": [(30, 110), (70, 60), (130, 60), (170, 110)]},
}


def _organic(args: dict[str, Any]) -> dict[str, Any]:
    names = [i["value"] for i in args["inputs"]]
    if any(n not in BUT_2_ENE for n in names):
        return {"status": "unknown", "reason": "unknown_name"}
    structures = [
        {
            "canonical_smiles": BUT_2_ENE[n]["canonical_smiles"],
            "formula": "C4H8",
            "functional_groups": ["alkene"],
            "svg": _molecule(BUT_2_ENE[n]["points"]),
            "atom_ids": ["a1", "a2", "a3", "a4"],
            "bond_ids": ["b1", "b2", "b3"],
        }
        for n in names
    ]
    value: dict[str, Any] = {"status": "ok", "structures": structures}
    if args["task"] == "compare":
        value["relationship"] = "same" if names[0] == names[1] else "stereoisomers"
    assert contract_errors("tools/science-compute#/$defs/OrganicResult", value) == []
    return value


def _call(prefix: str):
    from jana_tools.visual_fixtures import _call as worker

    real = worker(prefix)
    count = {"n": 0}

    def call(tool: str, args: dict[str, Any]) -> dict[str, Any]:
        if tool != "chem_organic":
            return real(tool, args)
        assert contract_errors("tools/science-compute#/$defs/OrganicArgs", args) == []
        count["n"] += 1
        return {"value": _organic(args), "check": {"check_id": f"chk_stub_{prefix}_{count['n']}", "function": tool}}

    return call


# --- context: the A level chemistry session the fixtures resolve in ------------------------------------------------


def _context(**knowns: str) -> VisualContext:
    diagrams, presets, assets, own = _sources()
    values = {}
    for c in own:
        try:
            values[f"pack:pack.chm.o/conventions/{c['key']}"] = Fraction(str(c["value"]))
        except ValueError:
            continue
    return VisualContext(
        "chemistry",
        "A",
        "S3",
        knowns={k: Fraction(v) for k, v in knowns.items()},
        pack_values=values,
        diagrams=diagrams,
        presets=presets,
        conventions={c["key"]: str(c["value"]) for c in own},
        science_assets=assets,
    )


@cache
def _sources() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    diagrams, presets, problems = _library(REPO_ROOT)
    assets, more = science_assets(REPO_ROOT)
    assert problems + more == []
    return diagrams, presets, assets, _conventions(REPO_ROOT)["chm"]


def _resolve(kind: str, params: dict[str, Any], **extra: Any) -> dict[str, Any]:
    knowns = extra.pop("knowns", {})
    request = {"spec_version": 1, "type": kind, "params": params, **extra}
    if knowns:
        request["numbers_from"] = list(knowns)
    ctx = _context(**knowns)
    resolved, _ = validate(request, ctx, Resolver(resolver(checked(_call(kind[:8])), ctx.conventions)))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    return resolved


def _fixture(fid: str) -> dict[str, Any]:
    fx = next(f for f in FIXTURES if f.id == fid)
    return {"kind": fx.request["type"], "params": fx.request["params"], **{k: v for k, v in fx.request.items()
            if k in ("ref", "steps")}, "knowns": fx.givens}  # fmt: skip


def _refused(kind: str, params: dict[str, Any], code: str, **extra: Any) -> None:
    with pytest.raises(VisualError) as error:
        _resolve(kind, params, **extra)
    assert error.value.code == code, (kind, params, error.value)


BUT_2_ENE_REQUEST = {
    "task": "compare",
    "inputs": [{"kind": "name", "value": "(E)-but-2-ene"}, {"kind": "name", "value": "(Z)-but-2-ene"}],
    "representation": "skeletal",
    "highlight_groups": ["alkene"],
}


def vsl06_but2ene_isomers():
    # E and Z but-2-ene side by side: two structures with identical atom counts and formula from the tool, each labelled
    # by its own name, and the tool's relationship (stereoisomers, not the same compound) said in the alt text.
    resolved = _resolve("organic_structure", BUT_2_ENE_REQUEST)
    computed = resolved["computed"]
    first, second = computed["structures"]
    assert first["formula"] == second["formula"] == "C4H8"
    assert len(first["atom_ids"]) == len(second["atom_ids"]) and len(first["bond_ids"]) == len(second["bond_ids"])
    assert first["canonical_smiles"] != second["canonical_smiles"]
    assert computed["relationship"] == "stereoisomers"
    assert computed["labels"]["mol_1"] == "(E)-but-2-ene" and computed["labels"]["mol_2"] == "(Z)-but-2-ene"
    focusable = [p["id"] for p in resolved["parts"] if p["focusable"]]
    assert focusable == ["mol_1", "mol_1.fg_alkene", "mol_2", "mol_2.fg_alkene"]
    atoms = [p["id"] for p in resolved["parts"] if p["role"] == "atom"]
    assert atoms == [f"mol_{n}.a{k}" for n in (1, 2) for k in range(1, 5)]
    assert "stereoisomers" in resolved["alt"]["summary"] and "(E)-but-2-ene (C4H8)" in resolved["alt"]["summary"]
    assert any(c.startswith("chk_") for c in resolved["numbers_from"])
    # The same request with the same name twice is the same compound, drawn twice.
    same = {**BUT_2_ENE_REQUEST, "inputs": [BUT_2_ENE_REQUEST["inputs"][0]] * 2}
    assert _resolve("organic_structure", same)["computed"]["relationship"] == "same"
    # The engine's tool call sanitises the tool's drawing as library SVG (VSL-23): a script, or a part that is none of
    # the tool's atom or bond ids, refuses it before the resolver sees it.
    good = {"value": _organic(BUT_2_ENE_REQUEST), "check": {"check_id": "chk_stub", "function": "chem_organic"}}
    svg = good["value"]["structures"][0]["svg"]
    for bad in (svg.replace("</svg>", "<script>x()</script></svg>"), svg.replace('data-part="a4"', 'data-part="z9"')):

        def tool(name: str, args: dict[str, Any], bad: str = bad) -> dict[str, Any]:
            st = {**good["value"]["structures"][0], "svg": bad}
            return {**good, "value": {**good["value"], "structures": [st]}}

        with pytest.raises(ResolutionError, match="not one the client may draw"):
            checked(tool)("chem_organic", {})


def vsl46_science_kind_contracts():
    """Every contracted S3 science kind of this module's subject (the chemistry kinds): its catalogue schema has no
    free-form drawing field; its canonical fixture validates against the kind schema and the resolved envelope,
    with traced figures, parts and build layers; positive params resolve; and its resolver refuses each negative
    case (VSL-46: duplicate ids, invalid references, reversed ranges, inconsistent units, unsupported models and
    out-of-pack ids)."""
    catalogue = {k["kind"]: k for k in VISUAL_CATALOGUE["kinds"]}
    for kind in KINDS:
        entry = catalogue[kind]
        assert entry["schema"] == f"contracts/visuals/kinds/{kind}.schema.json", kind
        schema = document(f"visuals/kinds/{kind}")
        assert not _property_names(schema) & FREEFORM, kind
        assert entry["levels"] == (["O", "A"] if kind == "organic_structure" else ["A"]), kind
    # The canonical fixtures (organic_structure has none until chem_organic ships; it resolves above and below).
    fixtures = [json.loads(p.read_text()) for p in sorted(FIXTURES_DIR.glob("*.json"))]
    seen = set()
    for f in fixtures:
        if f["kind"] not in KINDS:
            continue
        seen.add(f["kind"])
        spec = f["spec"]
        assert kind_param_errors(f["kind"], spec["params"]) == [], f["id"]
        assert contract_errors("visuals/visual-spec#/$defs/resolved", spec) == [], f["id"]
        # Template and graph kinds build in layers that add every part once (VSL-41: shown when the request asks for
        # a build); a mechanism builds by its library sequence instead.
        if f["kind"] != "reaction_mechanism":
            view = View(f["kind"], spec["params"], spec.get("computed", {}), spec.get("steps", []), None, "en")
            layers = layers_of(view, parts_of(view))
            layered = [p for layer in layers for p in layer["part_ids"]]
            assert sorted(layered) == sorted(p["id"] for p in spec["parts"] if p["focusable"]), f["id"]
        assert spec["alt"]["summary"] and "{" not in spec["alt"]["summary"], f["id"]
        if catalogue[f["kind"]]["numbers_rule"] in ("N2", "N3"):
            assert spec["numbers_from"], f["id"]
    assert seen == set(KINDS) - {"organic_structure"}
    assert _resolve("organic_structure", BUT_2_ENE_REQUEST)["status"] == "ok"
    for kind, params, code, extra in NEGATIVE:
        _refused(kind, params, code, **extra)


def _property_names(schema: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(schema, dict):
        names |= set(schema.get("properties", {}))
        for value in schema.values():
            names |= _property_names(value)
    elif isinstance(schema, list):
        for value in schema:
            names |= _property_names(value)
    return names


LEVELS = {
    "levels": [
        {"id": "n1", "energy_ev": -13.6, "label": "n = 1"},
        {"id": "n2", "energy_ev": -3.4, "label": "n = 2"},
    ],
    "transitions": [{"from": "n2", "to": "n1"}],
    "show_photon_energy": True,
}
LEVEL_KNOWNS = {"knowns": {"kn_e1": "-13.6", "kn_e2": "-3.4"}}
MB = {"temperatures_k": [300, 500], "activation_energy_j_mol": 10000, "energy_max_j_mol": 20000}
MB_KNOWNS = {"knowns": {"kn_t1": "300", "kn_t2": "500", "kn_ea": "10000"}}
CYCLE_STEPS = [
    {"id": "at_na", "kind": "atomisation", "enthalpy_kj_mol": 107, "coefficient": 1, "orientation": 1},
    {"id": "at_cl", "kind": "atomisation", "enthalpy_kj_mol": 122, "coefficient": 1, "orientation": 1},
    {"id": "ie_na", "kind": "ionisation", "enthalpy_kj_mol": 496, "coefficient": 1, "orientation": 1},
    {"id": "ea_cl", "kind": "electron_affinity", "enthalpy_kj_mol": -349, "coefficient": 1, "orientation": 1},
    {"id": "lattice", "kind": "lattice", "coefficient": 1, "orientation": 1},
    {"id": "formation", "kind": "formation", "enthalpy_kj_mol": -411, "coefficient": 1, "orientation": -1},
]
CYCLE = {"compound": "NaCl", "steps": CYCLE_STEPS, "unknown_step": "lattice"}
CYCLE_KNOWNS = {"knowns": {"kn_aa": "107", "kn_bb": "122", "kn_cc": "496", "kn_dd": "-349", "kn_ff": "-411"}}
FIRST_ORDER = {
    "mode": "first_order",
    "species": [{"id": "A", "label": "A", "initial": 0.5, "rate_constant": 0.0115}],
    "time_unit": "s",
    "concentration_unit": "mol/L",
    "time_range": [0, 300],
}
FIRST_KNOWNS = {"knowns": {"kn_c0": "0.5", "kn_kr": "0.0115"}}
DATA = {
    "mode": "data",
    "species": [
        {"id": "A", "label": "A", "points": [{"time": 0, "concentration": 0.5}, {"time": 60, "concentration": 0.25}]}
    ],
    "time_unit": "s",
    "concentration_unit": "mol/L",
    "time_range": [0, 120],
}
DATA_KNOWNS = {"knowns": {"kn_t0": "0", "kn_t60": "60", "kn_c5": "0.5", "kn_c25": "0.25"}}
HABER = {
    "species": [
        {"id": "N2", "formula": "N2", "state": "gas", "coefficient": 1, "side": "reactant"},
        {"id": "H2", "formula": "H2", "state": "gas", "coefficient": 3, "side": "reactant"},
        {"id": "NH3", "formula": "NH3", "state": "gas", "coefficient": 2, "side": "product"},
    ]
}


def _equilibrium(change: str, plateaus: dict[str, tuple[float, float]], **event: Any) -> dict[str, Any]:
    roles = {"N2": "reactant", "H2": "reactant", "NH3": "product"}
    return {
        "mode": "qualitative_equilibrium",
        "species": [{"id": sid, "label": sid, "role": roles[sid], "initial_plateau": a, "final_plateau": b}
                    for sid, (a, b) in plateaus.items()],
        "time_unit": "min",
        "concentration_unit": "relative",
        "time_range": [0, 100],
        "event": {"at": 40, "change": change, "reaction": HABER, **event},
    }  # fmt: skip


HEATED = _equilibrium(
    "temperature_increase", {"N2": (0.3, 0.4), "H2": (0.6, 0.8), "NH3": (0.8, 0.6)}, forward_enthalpy_kj_mol=-92
)
MECHANISM_PARAMS = {"diagram_id": MECHANISM, "sequence_id": "electrophilic_addition", "step": 0}
FAILED, INVALID = "visual_resolution_failed", "visual_param_invalid"
NEGATIVE: list[tuple[str, dict[str, Any], str, dict[str, Any]]] = [
    # energy_levels: a transition to a level that is not drawn, a repeated level id, a quantity in place of a number.
    ("energy_levels", {**LEVELS, "transitions": [{"from": "n2", "to": "n9"}]}, FAILED, LEVEL_KNOWNS),
    ("energy_levels", {**LEVELS, "levels": [LEVELS["levels"][0]] * 2}, FAILED, LEVEL_KNOWNS),
    ("energy_levels", {**LEVELS, "transitions": [{"from": "n2", "to": "n2"}]}, FAILED, LEVEL_KNOWNS),
    ("energy_levels", {**LEVELS, "levels": [{**LEVELS["levels"][0], "energy_ev": "-13.6 eV"}, LEVELS["levels"][1]]},
     INVALID, LEVEL_KNOWNS),
    # orbital_boxes: an element the pack has no proton number for, a charge leaving no electrons, a charge off the
    # schema's range.
    ("orbital_boxes", {"element": "Xx", "charge": 0}, FAILED, {}),
    ("orbital_boxes", {"element": "H", "charge": 1}, FAILED, {}),
    ("orbital_boxes", {"element": "S", "charge": 9}, INVALID, {}),
    # maxwell_boltzmann: Ea off the energy axis (a reversed range), a repeated temperature, a zero temperature, a
    # negative activation energy.
    ("maxwell_boltzmann", {**MB, "energy_max_j_mol": 5000}, FAILED, MB_KNOWNS),
    ("maxwell_boltzmann", {**MB, "temperatures_k": [300, 300]}, FAILED, {"knowns": {"kn_t1": "300", "kn_ea": "10000"}}),
    ("maxwell_boltzmann", {**MB, "temperatures_k": [0]}, INVALID, {}),
    ("maxwell_boltzmann", {**MB, "activation_energy_j_mol": -1}, INVALID, {}),
    # born_haber_cycle: an unknown step that is not a step, two steps without an enthalpy, a repeated step id, no
    # lattice step, a zero coefficient, an orientation other than +1 or -1.
    ("born_haber_cycle", {**CYCLE, "unknown_step": "missing"}, FAILED, CYCLE_KNOWNS),
    ("born_haber_cycle", {**CYCLE, "steps": [*CYCLE_STEPS[:-1], {k: v for k, v in CYCLE_STEPS[-1].items()
                                                                  if k != "enthalpy_kj_mol"}]}, FAILED, CYCLE_KNOWNS),
    ("born_haber_cycle", {**CYCLE, "steps": [{k: v for k, v in s.items() if k != "enthalpy_kj_mol"}
                                             for s in CYCLE_STEPS]}, FAILED, {}),
    ("born_haber_cycle", {**CYCLE, "steps": [*CYCLE_STEPS, CYCLE_STEPS[0]]}, FAILED, CYCLE_KNOWNS),
    ("born_haber_cycle", {**CYCLE, "steps": [s for s in CYCLE_STEPS if s["kind"] != "lattice"], "unknown_step":
                          "formation"}, FAILED, CYCLE_KNOWNS),
    ("born_haber_cycle", {**CYCLE, "steps": [{**CYCLE_STEPS[0], "coefficient": 0}, *CYCLE_STEPS[1:]]}, INVALID,
     CYCLE_KNOWNS),
    ("born_haber_cycle", {**CYCLE, "steps": [{**CYCLE_STEPS[0], "orientation": 0}, *CYCLE_STEPS[1:]]}, INVALID,
     CYCLE_KNOWNS),
    # concentration_time: a reversed time range, points back in time, a fitted tangent from data, a rate constant in
    # data mode, a zero first-order rate constant, a first-order product, a duplicate species id.
    ("concentration_time", {**FIRST_ORDER, "time_range": [300, 0]}, FAILED, FIRST_KNOWNS),
    ("concentration_time", {**DATA, "species": [{**DATA["species"][0], "points": DATA["species"][0]["points"][::-1]}]},
     FAILED, DATA_KNOWNS),
    ("concentration_time", {**DATA, "show_initial_tangent": True}, FAILED, DATA_KNOWNS),
    ("concentration_time", {**DATA, "species": [{**DATA["species"][0], "rate_constant": 0.1}]}, INVALID, DATA_KNOWNS),
    ("concentration_time", {**FIRST_ORDER, "species": [{**FIRST_ORDER["species"][0], "rate_constant": 0}]}, INVALID,
     {"knowns": {"kn_c0": "0.5", "kn_k0": "0"}}),
    ("concentration_time", {**FIRST_ORDER, "species": [{**FIRST_ORDER["species"][0], "role": "product"}]}, FAILED,
     FIRST_KNOWNS),
    ("concentration_time", {**FIRST_ORDER, "species": FIRST_ORDER["species"] * 2}, FAILED, FIRST_KNOWNS),
    # concentration_time, qualitative: the change outside the time shown, plateaus moving against Le Chatelier, an
    # unbalanced reaction, a species not in the reaction, a pressure change (needs a compression ratio), measured
    # units on an illustrative graph, a catalyst that moves a plateau.
    ("concentration_time", {**HEATED, "event": {**HEATED["event"], "at": 150}}, FAILED, {}),
    ("concentration_time", _equilibrium("temperature_increase", {"N2": (0.3, 0.2), "H2": (0.6, 0.8), "NH3": (0.8, 0.6)},
                                        forward_enthalpy_kj_mol=-92), FAILED, {}),
    ("concentration_time", {**HEATED, "event": {**HEATED["event"], "reaction": {"species": [
        *HABER["species"][:2], {**HABER["species"][2], "coefficient": 1}]}}}, FAILED, {}),
    ("concentration_time", {**HEATED, "species": [*HEATED["species"], {**HEATED["species"][0], "id": "O2"}]}, FAILED,
     {}),
    ("concentration_time", _equilibrium("pressure_increase", {"N2": (0.3, 0.2), "NH3": (0.8, 0.9)}), FAILED, {}),
    ("concentration_time", {**HEATED, "concentration_unit": "mol/L"}, INVALID, {}),
    ("concentration_time", _equilibrium("catalyst", {"N2": (0.3, 0.3), "NH3": (0.8, 0.7)}), FAILED, {}),
    # spectrum_chart: a spectrum not in the installed packs, the wrong spectrum type, a peak the spectrum lacks.
    ("spectrum_chart", {"spectrum_id": "dgm.chm.spectrum_made_up.v1", "type": "infrared"}, FAILED, {}),
    ("spectrum_chart", {"spectrum_id": SPECTRUM, "type": "mass"}, FAILED, {}),
    ("spectrum_chart", {"spectrum_id": SPECTRUM, "type": "infrared", "peaks": ["c_n"]}, FAILED, {}),
    # reaction_mechanism: a diagram that is not installed, a sequence it lacks, a step past its end, a diagram_id
    # other than the ref, a diagram outside chemistry.
    ("reaction_mechanism", {**MECHANISM_PARAMS, "diagram_id": "dgm.chm.made_up.v1"}, "visual_ref_missing",
     {"ref": "dgm.chm.made_up.v1"}),
    ("reaction_mechanism", {**MECHANISM_PARAMS, "sequence_id": "nucleophilic_substitution"}, FAILED,
     {"ref": MECHANISM}),
    ("reaction_mechanism", {**MECHANISM_PARAMS, "step": 2}, FAILED, {"ref": MECHANISM}),
    ("reaction_mechanism", {**MECHANISM_PARAMS, "diagram_id": "dgm.chm.titration_apparatus.v1"}, FAILED,
     {"ref": MECHANISM}),
    ("reaction_mechanism", {**MECHANISM_PARAMS, "diagram_id": "dgm.bio.heart.v1"}, INVALID, {"ref": MECHANISM}),
    # organic_structure: a name outside the curated table, a group the tool did not find, a comparison of one.
    ("organic_structure", {**BUT_2_ENE_REQUEST, "inputs": [{"kind": "name", "value": "but-2-yne"}] * 2}, FAILED, {}),
    ("organic_structure", {**BUT_2_ENE_REQUEST, "highlight_groups": ["ketone"]}, FAILED, {}),
    ("organic_structure", {**BUT_2_ENE_REQUEST, "inputs": BUT_2_ENE_REQUEST["inputs"][:1]}, INVALID, {}),
]  # fmt: skip


def vsl46_equilibrium_response_fidelity():
    # The exothermic ammonia equilibrium heated at fixed volume: product down, reactants up, with no jump at the change
    # and the response labelled illustrative (no time scale is derived from an equilibrium constant).
    resolved = _resolve("concentration_time", HEATED)
    computed = resolved["computed"]
    assert computed["moves"] == {"N2": "rises", "H2": "rises", "NH3": "falls"}
    assert computed["illustrative"] is True
    assert "time scale is not measured" in resolved["alt"]["summary"]
    for sp in HEATED["species"]:
        before, *after = computed["curves"][f"sp_{sp['id']}"]
        assert before == [[0, sp["initial_plateau"]], [40, sp["initial_plateau"]]]
        assert after[0][0] == [40.0, pytest.approx(sp["initial_plateau"])]  # continuous at the change
        assert after[-1][-1][1] == pytest.approx(sp["final_plateau"], abs=0.01)
    # A catalyst leaves every plateau where it was.
    catalysed = _resolve("concentration_time", _equilibrium("catalyst", {"N2": (0.3, 0.3), "NH3": (0.8, 0.8)}))
    assert catalysed["computed"]["moves"] == {"N2": "unchanged", "NH3": "unchanged"}
    # Adding a reactant: it jumps at the change and is partly used up; the product rises.
    added = _resolve("concentration_time", _equilibrium("add_species", {"N2": (0.3, 0.5), "NH3": (0.8, 0.9)},
                                                        species_id="N2"))  # fmt: skip
    n2 = added["computed"]["curves"]["sp_N2"]
    assert n2[1][0][1] == pytest.approx(0.7) and n2[-1][-1][1] == pytest.approx(0.5, abs=0.01)


# --- resolver figures ----------------------------------------------------------------------------------------------


def test_energy_levels_photons():
    resolved = _resolve("energy_levels", LEVELS, **LEVEL_KNOWNS)
    assert resolved["computed"]["labels"]["tr_n2_n1"] == "10.2 eV"
    assert resolved["computed"]["transitions"] == [{"id": "tr_n2_n1", "direction": "emission", "energy_ev": 10.2}]
    upward = _resolve("energy_levels", {**LEVELS, "transitions": [{"from": "n1", "to": "n2"}]}, **LEVEL_KNOWNS)
    assert upward["computed"]["transitions"][0]["direction"] == "absorption"
    # A level energy no known traces is refused (VSL-12).
    _refused("energy_levels", LEVELS, "visual_untraced_number")


def test_orbital_configurations():
    # Hund's rule in 3p, the Cr and Cu exceptions, 4s emptied before 3d in a cation, an anion filling on.
    resolved = _resolve("orbital_boxes", {"element": "S", "charge": 0})
    assert resolved["computed"]["labels"]["configuration"] == "1s2 2s2 2p6 3s2 3p4"
    assert resolved["computed"]["unpaired"] == 2
    assert resolved["numbers_from"] == ["pack:pack.chm.o/conventions/chem.z_s"]
    assert {k: v for k, v in configuration(24, 0).items() if k in ("4s", "3d")} == {"4s": 1, "3d": 5}
    assert {k: v for k, v in configuration(29, 1).items() if k in ("4s", "3d")} == {"4s": 0, "3d": 10}
    assert {k: v for k, v in configuration(26, 2).items() if k in ("4s", "3d")} == {"4s": 0, "3d": 6}
    assert configuration(17, -1)["3p"] == 6
    calcium = _resolve("orbital_boxes", {"element": "Ca", "charge": 2})
    assert [s["id"] for s in calcium["computed"]["subshells"]][-1] == "4s"  # the emptied 4s box is still drawn
    assert calcium["computed"]["labels"]["configuration"] == "1s2 2s2 2p6 3s2 3p6"


def test_maxwell_boltzmann_tail_is_the_curve():
    resolved = _resolve("maxwell_boltzmann", MB, **MB_KNOWNS)
    computed = resolved["computed"]
    for n, t in enumerate(MB["temperatures_k"], 1):
        x = MB["activation_energy_j_mol"] / (8.314 * t)
        expected = math.erfc(math.sqrt(x)) + 2 * math.sqrt(x / math.pi) * math.exp(-x)
        assert computed["fractions"][f"tail_{n}"] == pytest.approx(expected, rel=1e-5)
        points = [q for seg in computed["curves"][f"curve_{n}"] for q in seg]
        peak = max(points, key=lambda q: q[1])
        assert peak[0] == pytest.approx(8.314 * t / 2, rel=0.3)  # the most probable energy is RT/2
    assert (computed["labels"]["tail_1"], computed["labels"]["tail_2"]) == ("0.0456", "0.186")


def test_born_haber_closes():
    resolved = _resolve("born_haber_cycle", CYCLE, **CYCLE_KNOWNS)
    labels = resolved["computed"]["labels"]
    assert labels["step_lattice"] == "-787" and labels["step_at_na"] == "+107"
    assert sum(resolved["computed"]["contributions"].values()) == pytest.approx(0)
    # The unknown in another place: the electron affinity from the lattice enthalpy.
    steps = [{**s, "enthalpy_kj_mol": -787} if s["id"] == "lattice" else s for s in CYCLE_STEPS]
    steps = [{k: v for k, v in s.items() if not (s["id"] == "ea_cl" and k == "enthalpy_kj_mol")} for s in steps]
    knowns = {"knowns": {"kn_aa": "107", "kn_bb": "122", "kn_cc": "496", "kn_ll": "-787", "kn_ff": "-411"}}
    other = _resolve("born_haber_cycle", {**CYCLE, "steps": steps, "unknown_step": "ea_cl"}, **knowns)
    assert other["computed"]["labels"]["step_ea_cl"] == "-349"
    # A halved step: 0.5 x the Cl-Cl bond enthalpy is the atomisation of chlorine.
    halved = [{**s, "enthalpy_kj_mol": 244, "coefficient": 0.5} if s["id"] == "at_cl" else s for s in CYCLE_STEPS]
    knowns = {"knowns": {"kn_aa": "107", "kn_bb": "244", "kn_cc": "496", "kn_dd": "-349", "kn_ff": "-411"}}
    resolved = _resolve("born_haber_cycle", {**CYCLE, "steps": halved}, **knowns)
    assert resolved["computed"]["labels"]["step_at_cl"] == "0.5 × +244"
    assert resolved["computed"]["labels"]["step_lattice"] == "-787"


def test_concentration_time_modes():
    resolved = _resolve("concentration_time", {**FIRST_ORDER, "show_initial_tangent": True}, **FIRST_KNOWNS)
    labels = resolved["computed"]["labels"]
    assert labels["sp_A.half_life"] == "t½ = 60.3 s" and labels["sp_A.tangent"] == "0.00575 mol/L/s"
    assert resolved["computed"]["half_lives"]["sp_A"] == pytest.approx(math.log(2) / 0.0115, rel=1e-5)
    tangent = [q for seg in resolved["computed"]["tangents"]["sp_A"] for q in seg]
    assert tangent[0] == [0.0, 0.5] and tangent[-1][1] == pytest.approx(0, abs=1e-9)
    data = _resolve("concentration_time", DATA, **DATA_KNOWNS)
    assert data["computed"]["curves"]["sp_A"] == [[[0, 0.5], [60, 0.25]]]
    assert "check_ids" in data["computed"] and data["computed"]["check_ids"] == []
    # A data point no known traces is refused.
    untraced = {"kn_t0": "0", "kn_t60": "60", "kn_c5": "0.5"}
    _refused("concentration_time", DATA, "visual_untraced_number", knowns=untraced)


def test_spectrum_and_mechanism_from_the_pack():
    resolved = _resolve("spectrum_chart", {"spectrum_id": SPECTRUM, "type": "infrared", "peaks": ["c_o"]})
    assert resolved["computed"]["labels"] == {"peak_c_o": "1050 cm⁻¹, C-O"}
    assert resolved["numbers_from"] == [f"pack:pack.renderers.fixtures/science_assets/{SPECTRUM}"]
    mechanism = _resolve("reaction_mechanism", MECHANISM_PARAMS, ref=MECHANISM)
    assert mechanism["steps"] == [{"highlight": ["ethene", "hydrogen_bromide"]}]
    assert mechanism["alt"]["steps"][0].startswith("Step 1: The pi bond")
    assert "step 1 of 2" in mechanism["alt"]["summary"]


def test_kinds_are_a_level_only():
    # VSL-07: the A level kinds are not advertised in an O level session; organic_structure is at both levels.
    for kind, params in (
        ("orbital_boxes", {"element": "S", "charge": 0}),
        ("spectrum_chart", {"spectrum_id": SPECTRUM, "type": "infrared"}),
    ):
        ctx = _context()
        ctx.level = "O"
        with pytest.raises(VisualError) as error:
            validate({"spec_version": 1, "type": kind, "params": params}, ctx, None)
        assert error.value.code == "visual_kind_not_enabled"
    ctx = _context()
    ctx.level = "O"
    resolved, _ = validate({"spec_version": 1, "type": "organic_structure", "params": BUT_2_ENE_REQUEST}, ctx,
                           Resolver(resolver(_call("olevel"))))  # fmt: skip
    assert resolved["status"] == "ok"
