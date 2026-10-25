"""VER-38 (with VER-32): `chem_equilibrium` through the real fn.call boundary, results validated against the
science-compute contract; invalid input is a domain error and an undecidable case is unknown with no number."""

from __future__ import annotations

from typing import Any

import pytest
from test_ver38_biology import CHECK, call
from tool_worker.contracts.tools.science_compute import EquilibriumResult
from tool_worker.protocol import Code

HI = {"species": [
    {"id": "h2", "formula": "H2", "state": "gas", "coefficient": 1, "side": "reactant"},
    {"id": "i2", "formula": "I2", "state": "gas", "coefficient": 1, "side": "reactant"},
    {"id": "hi", "formula": "HI", "state": "gas", "coefficient": 2, "side": "product"},
]}  # fmt: skip
REVERSED = {"species": [{**s, "side": "product" if s["side"] == "reactant" else "reactant"} for s in HI["species"]]}
# CaCO3(s) <=> CaO(s) + CO2(g): two pure phases, so Kp is the CO2 pressure alone.
LIMESTONE = {"species": [
    {"id": "caco3", "formula": "CaCO3", "state": "solid", "coefficient": 1, "side": "reactant"},
    {"id": "cao", "formula": "CaO", "state": "solid", "coefficient": 1, "side": "product"},
    {"id": "co2", "formula": "CO2", "state": "gas", "coefficient": 1, "side": "product"},
]}  # fmt: skip


def conc(sid: str, value: float, unit: str = "mol/L") -> dict[str, Any]:
    return {"species_id": sid, "quantity": {"value": value, "unit": unit}}


def result(args: dict[str, Any]) -> dict[str, Any]:
    reply = call("chem_equilibrium", args)
    assert "result" in reply, reply
    value: dict[str, Any] = reply["result"]["value"]
    EquilibriumResult.model_validate(value)
    return value


def refused(args: dict[str, Any]) -> str:
    reply = call("chem_equilibrium", args)
    assert "result" not in reply and reply["error"]["code"] == Code.DOMAIN_ERROR, reply
    return str(reply["error"]["message"])


def constant(reaction: dict[str, Any], values: list[dict[str, Any]], basis: str = "Kc", **extra: Any) -> dict[str, Any]:
    return {"task": "constant", "reaction": reaction, "basis": basis, "temperature_k": 731, "values": values, **extra}


def ver38_equilibrium_physical_cases() -> None:
    # H2 + I2 <=> 2HI at 0.10, 0.10 and 0.74 mol/L: Kc = 0.74² / (0.10 x 0.10) = 54.76, with no unit (Δn = 0).
    kc = result(constant(HI, [conc("h2", 0.10), conc("i2", 0.10), conc("hi", 0.74)]))
    assert kc["status"] == "ok" and kc["constant"]["value"] == pytest.approx(54.76, rel=1e-12)
    assert kc["constant"]["unit"] == "no unit (the powers cancel)" and kc["constant"]["check_id"] == CHECK
    # Reversing the reaction inverts K; mol/m3 and amounts in a stated volume are normalised to mol/L.
    reverse = result(constant(REVERSED, [conc("h2", 100, "mol/m3"), conc("i2", 0.2, "mol"), conc("hi", 1.48, "mol")],
                              volume_l=2))  # fmt: skip
    assert reverse["constant"]["value"] == pytest.approx(1 / 54.76, rel=1e-12)
    assert "volume_l" in refused(constant(HI, [conc("h2", 0.1, "mol"), conc("i2", 0.1), conc("hi", 0.74)]))
    # Pure phases have activity 1: Kp of the limestone equilibrium is the CO2 pressure, in Pa^1.
    kp = result(constant(LIMESTONE, [conc("co2", 1.5, "kPa"), conc("caco3", 3, "mol")], basis="Kp"))
    assert kp["constant"] == {"value": 1500.0, "unit": "Pa^1", "check_id": CHECK}
    # Invalid units for the basis, a missing species, an unbalanced reaction: domain errors, no number.
    assert "is not a concentration" in refused(constant(HI, [conc("h2", 0.1, "kPa"), conc("i2", 0.1), conc("hi", 1)]))
    assert "no value for i2" in refused(constant(HI, [conc("h2", 0.1), conc("hi", 0.74)]))
    unbalanced = {"species": [{**s, "coefficient": 1} for s in HI["species"]]}
    assert "not balanced (H, I)" in refused(constant(unbalanced, [conc("h2", 0.1), conc("i2", 0.1), conc("hi", 1)]))
    # A zero reactant concentration has no finite constant: unknown, never infinity.
    zero = result(constant(HI, [conc("h2", 0), conc("i2", 0.1), conc("hi", 0.74)]))
    assert zero == {"status": "unknown", "reason": "no_physical_root"}
    # ICE: 1.0 mol/L each of H2 and I2 with Kc 54.76 -> one admissible extent, x = 0.787 (2x/(1-x) = 7.4).
    ice = result({"task": "extent", "reaction": HI, "basis": "Kc", "temperature_k": 731, "constant": 54.76,
                  "initial": [conc("h2", 1.0), conc("i2", 1.0), conc("hi", 0)]})  # fmt: skip
    assert ice["extent"]["value"] == pytest.approx(7.4 / 9.4, rel=1e-12) and ice["extent"]["unit"] == "mol/L"
    rows = {r["species_id"]: r for r in ice["ice"]}
    assert rows["hi"]["equilibrium"] == pytest.approx(2 * 7.4 / 9.4) and rows["h2"]["change"] < 0
    assert all(r["equilibrium"] >= 0 for r in ice["ice"])
    # The quadratic's other root (x = 7.4 / 5.4 > 1) would make [H2] negative: it is rejected, not reported.
    assert len(ice["ice"]) == 3 and ice["extent"]["value"] < 1
    # Electrode potentials: E°cell = E°cathode - E°anode, never scaled by a coefficient.
    cell = result({"task": "electrode_potential", "electrode_potentials": [
        {"id": "cu", "standard_potential_v": 0.34, "role": "cathode"},
        {"id": "zn", "standard_potential_v": -0.76, "role": "anode"}]})  # fmt: skip
    assert cell["cell_potential"]["value"] == pytest.approx(1.10) and cell["cell_potential"]["unit"] == "V"
    assert "one cathode and one anode" in refused({"task": "electrode_potential", "electrode_potentials": [
        {"id": "cu", "standard_potential_v": 0.34, "role": "cathode"},
        {"id": "ag", "standard_potential_v": 0.80, "role": "cathode"}]})  # fmt: skip
