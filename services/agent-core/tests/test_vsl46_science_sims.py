"""The S3 simulations of the installed O level subjects in the engine (VSL-08a, VSL-46, VSL-47, D114): each resolves
through its contract schema with tool-checked starting readouts, refuses a preset it does not have or a value outside
its sliders, and its predict scenario resolves from the Coach's note alone (`{"predict": id}`) without giving the
result away."""

import pytest
from agent_core.assets.generated.sim_presets import SIM_PRESETS
from agent_core.assets.generated.sim_scenarios import SIM_SCENARIOS
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, validate
from agent_core.contracts import errors as contract_errors
from jana_tools.visual_fixtures import _call

SUBJECTS = {"phy": "physics", "chm": "chemistry", "mth": "mathematics"}
S3_KINDS = {"gas_laws_sim", "function_transform_sim", "electrolysis_sim", "rates_sim", "equilibrium_sim"}
CONVENTIONS = {
    "physics": {"phy.kelvin_offset": "273"},
    "chemistry": {
        "chem.faraday": "96500",
        "chem.vm": "24",
        "chem.ar_cu": "64",
        "chem.ar_pb": "207",
        "chem.ar_br": "80",
    },
}


def _context(subject: str) -> VisualContext:
    return VisualContext(subject, "O", "S3", conventions=CONVENTIONS.get(subject, {}))


def _resolve(subject: str, request: dict) -> dict:
    ctx = _context(subject)
    resolved, _ = validate(request, ctx, Resolver(resolver(_call("vsl46"), ctx.conventions)))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    return resolved


def test_vsl47_predict_only_request_resolves():
    # The Coach's switch-representation note names only the scenario; its starting values fill every required field.
    for scenario in SIM_SCENARIOS.values():
        if scenario["kind"] not in S3_KINDS:
            continue
        request = {"spec_version": 1, "type": scenario["kind"], "params": {"predict": scenario["id"]}}
        resolved = _resolve(SUBJECTS[scenario["subject"]], request)
        assert resolved["status"] == "ok", scenario["id"]
        assert "after you predict" in resolved["alt"]["summary"], scenario["id"]
        assert resolved["numbers_from"], scenario["id"]


def test_vsl46_gas_laws_sim_resolution():
    request = {
        "spec_version": 1,
        "type": "gas_laws_sim",
        "params": {
            "amount_mol": 0.008,
            "temperature_k": 300,
            "volume_m3": 0.0002,
            "control": "volume",
            "preset_id": "sim.phy.gas_syringe.v1",
        },
    }
    resolved = _resolve("physics", request)
    labels = resolved["computed"]["labels"]
    # p = nRT/V = 0.008 * 8.314 * 300 / 0.0002 Pa = 99.8 kPa, from math_evaluate; 300 K is 27 °C by the pack's offset.
    assert (labels["out.pressure"], labels["out.celsius"]) == ("99.8", "27")
    assert "99.8 kPa" in resolved["alt"]["summary"]
    # A flask cannot change volume; an unknown preset or a temperature off the slider is refused, not clamped.
    for change in (
        {"preset_id": "sim.phy.gas_sealed_flask.v1"},
        {"preset_id": "sim.phy.made_up.v1"},
        {"temperature_k": 900},
    ):
        bad = {**request, "params": {**request["params"], **change}}
        with pytest.raises(VisualError) as error:
            _resolve("physics", bad)
        assert error.value.code == "visual_resolution_failed", change


def test_vsl46_function_transform_sim_resolution():
    slider = {"min": -4, "max": 4, "step": 0.5, "value": 0}
    request = {
        "spec_version": 1,
        "type": "function_transform_sim",
        "params": {
            "expression": "x^2",
            "x_range": [-6, 6],
            "parameters": {
                "a": {**slider, "value": 2},
                "b": {**slider, "value": 1},
                "c": {**slider, "value": -1},
                "d": slider,
            },
        },
    }
    resolved = _resolve("mathematics", request)
    # y = 2(x - 1)^2: the parent's turning point (0, 0) goes to (1, 0), from math_evaluate.
    assert resolved["computed"]["labels"] == {"out.point_x": "1", "out.point_y": "0"}
    assert resolved["computed"]["x0"] == 0
    # ln x has no point at 0, so the tracked point is the parent's (1, 0).
    log = {**request, "params": {**request["params"], "expression": "ln(x)", "x_range": [0.5, 6]}}
    assert _resolve("mathematics", log)["computed"]["x0"] == 1
    # The slider object `d` is not SVG path data; an expression the client cannot parse, b = 0 or a value off the
    # slider's steps fails closed.
    for change in (
        {"expression": "x^2 + import(os)"},
        {"parameters": {**request["params"]["parameters"], "b": {**slider, "value": 0}}},
        {"parameters": {**request["params"]["parameters"], "c": {**slider, "value": 0.25}}},
    ):
        bad = {**request, "params": {**request["params"], **change}}
        with pytest.raises(VisualError) as error:
            _resolve("mathematics", bad)
        assert error.value.code == "visual_resolution_failed", change


def test_vsl46_electrolysis_sim_resolution():
    request = {
        "spec_version": 1,
        "type": "electrolysis_sim",
        "params": {
            "preset_id": "sim.chm.electrolysis_copper_refining.v1",
            "electrolyte": "Copper(II) sulfate",
            "phase": "aqueous",
            "electrodes": "copper",
            "current_a": 0.5,
            "duration_s": 3600,
        },
    }
    resolved = _resolve("chemistry", request)
    labels = resolved["computed"]["labels"]
    # 1800 C moves 1800 / 96500 mol of electrons: 0.597 g of copper on the cathode, the same off the anode.
    assert (labels["out.charge"], labels["out.cathode_mass"], labels["out.anode_mass"]) == ("1800", "0.597", "-0.597")
    assert resolved["computed"]["constants"] == {"faraday": 96500.0, "vm_cm3": 24000.0, "molar_mass": {"Cu": 64.0}}
    # Both half-equations went through chem_balance, and every amount through math_evaluate.
    assert len(resolved["numbers_from"]) >= 6
    for change in (
        {"electrodes": "inert"},
        {"phase": "molten"},
        {"current_a": 50},
        {"preset_id": "sim.chm.made_up.v1"},
    ):
        bad = {**request, "params": {**request["params"], **change}}
        with pytest.raises(VisualError) as error:
            _resolve("chemistry", bad)
        assert error.value.code == "visual_resolution_failed", change


def test_vsl46_rates_sim_resolution():
    request = {
        "spec_version": 1,
        "type": "rates_sim",
        "params": {
            "temperature_k": 293,
            "concentration_mol_l": 0.5,
            "activation_energy_j_mol": 50000,
            "pre_exponential_s": 8200000,
            "catalysed_activation_energy_j_mol": 35000,
        },
    }
    resolved = _resolve("chemistry", request)
    labels = resolved["computed"]["labels"]
    # k = 8.2e6 exp(-50000 / (8.314 * 293)) = 0.00999 per second; the run is all but over at ln(10^6) / k = 1380 s.
    assert (labels["out.rate_constant"], labels["out.rate"], labels["end.time"]) == ("0.00999", "0.00500", "1380")
    for change in ({"catalysed_activation_energy_j_mol": 60000}, {"temperature_k": 500}, {"concentration_mol_l": 5}):
        bad = {**request, "params": {**request["params"], **change}}
        with pytest.raises(VisualError) as error:
            _resolve("chemistry", bad)
        assert error.value.code == "visual_resolution_failed", change


def test_vsl46_equilibrium_sim_resolution():
    from jana_tools.visual_fixtures import FIXTURES

    params = next(f for f in FIXTURES if f.id == "equilibrium-sim").request["params"]
    request = {"spec_version": 1, "type": "equilibrium_sim", "params": params}
    resolved = _resolve("chemistry", request)
    labels = resolved["computed"]["labels"]
    # N2 + 3H2 = 2NH3 from 1 and 3 mol/dm3, Kc 0.05: one admissible extent from math_solve, x = 0.292.
    assert (labels["eq.c_N2"], labels["eq.c_H2"], labels["eq.c_NH3"], labels["out.kc"]) == (
        "0.708",
        "2.13",
        "0.583",
        "0.0500",
    )
    # Cooler favours the exothermic forward reaction (van't Hoff): more ammonia at 623 K.
    cooler = _resolve("chemistry", {**request, "params": {**params, "temperature_k": 623}})
    assert cooler["computed"]["labels"]["eq.c_NH3"] == "0.997"
    for change in (
        {"temperature_k": 1000},
        {"initial_concentrations": [{"species_id": "O2", "value": 1}, {"species_id": "N2", "value": 1}]},
    ):
        bad = {**request, "params": {**params, **change}}
        with pytest.raises(VisualError) as error:
            _resolve("chemistry", bad)
        assert error.value.code == "visual_resolution_failed", change


def test_vsl46_presets_are_the_renderers():
    import json

    from jana_tools import REPO_ROOT

    source = json.loads((REPO_ROOT / "packages/renderers/src/sims/presets.json").read_text())
    assert SIM_PRESETS == {p["id"]: p for p in source["presets"]}
