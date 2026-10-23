"""M12.c: the chemistry checkers of verification breadth (VER-18, VER-19, VER-20, VER-21), with the stoichiometry
chain's provenance (VER-02, G18) and the titration curve resolved from `chem_acid_base` (VSL-13, G31).

The acceptance tests call the real worker server code in process; the golden sets run in full, and every new tool's
results carry a schema-valid check record."""

import io
import json
from functools import cache

import pytest
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, validate
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.tools.catalogue import visible_tools
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.spec import SessionCtx
from agent_core.tools.specs import M12_CHEMISTRY_TOOLS, registry
from jana_tools import golden
from tool_worker.functions import FUNCTIONS
from tool_worker.server import Limits, Server

CHECK = "chk_01JZ0000000000000000000013"
O_LEVEL = {"H": "1", "C": "12", "O": "16", "Na": "23", "S": "32", "Cl": "35.5", "Cu": "63.5"}


def pack(*elements: str) -> list[dict]:
    """O level relative atomic masses as a pack's conventions state them (synthetic)."""
    return [{"symbol": f"Ar({e})", "value": O_LEVEL[e], "source": "pack"} for e in elements]


def call(name: str, args: dict, check_id: str = CHECK) -> dict:
    """One call through the real server code, in process: the reply's `result` (or `error`)."""
    out = io.BytesIO()
    server = Server(FUNCTIONS, out, Limits())
    hello = {"protocol": {"major": 1, "minor": 0}, "host_version": "t", "placement": "device"}
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "h", "method": "worker.hello", "params": hello}).encode())
    params = {"call_id": "c", "name": name, "version": FUNCTIONS[name].version, "args": args, "check_id": check_id,
              "deadline_ms": 15000}  # fmt: skip
    server.handle_line(json.dumps({"jsonrpc": "2.0", "id": "1", "method": "fn.call", "params": params}).encode())
    server.serve(io.BytesIO(b""))
    reply = next(r for r in (json.loads(line) for line in out.getvalue().splitlines()) if r.get("id") == "1")
    return reply.get("result") or {"error": reply["error"]}


def valid(result: dict) -> dict:
    assert contract_errors("tools/worker-protocol#/$defs/FnCallResult", result) == [], result
    return result


@cache
def _chemistry_golden() -> dict[str, list[tuple[dict, object]]]:
    sets = golden.load()
    return {name: [(c, golden.run(c, name)) for c in sets[name]["cases"]] for name in sorted(M12_CHEMISTRY_TOOLS)}


# --- acceptance ------------------------------------------------------------------------------------------------------


def ver18_hydrate_molar_mass():
    result = valid(call("chem_molar_mass", {"formula": "CuSO4·5H2O", "constants": pack("Cu", "S", "O", "H")}))
    value = result["value"]
    assert value["molar_mass"]["shown"] == "249.5" and value["molar_mass"]["text"] == "499/2"
    assert value["counts"] == {"Cu": 1, "S": 1, "O": 9, "H": 10}
    # Four working lines, one per element, in order of first appearance, each citing this check.
    assert [w["label"] for w in result["working"]] == ["Cu", "S", "O", "H"]
    assert [w["value"] for w in result["working"]] == ["63.5", "32", "144", "10"]
    assert {w["check_id"] for w in result["working"]} == {CHECK}
    assert [c["source"] for c in result["check"]["constants"]] == ["pack"] * 4 and "warnings" not in result
    # The grammar: brackets, charges, state symbols; an ambiguous charge is refused with its position.
    assert call("chem_molar_mass", {"formula": "Fe2(SO4)3"})["value"]["counts"] == {"Fe": 2, "S": 3, "O": 12}
    ion = call("chem_molar_mass", {"formula": "SO4^2-(aq)"})["value"]
    assert (ion["charge"], ion["state"]) == (-2, "aq")
    assert call("chem_molar_mass", {"formula": "Cu2+"})["error"]["data"]["position"] == 3
    # With no convention stated, the standard atomic weights of the chemistry default table, visibly.
    default = valid(call("chem_molar_mass", {"formula": "CuSO4·5H2O"}))
    assert default["value"]["molar_mass"]["shown"] == "249.677"  # 63.546 + 32.06 + 9 * 15.999 + 10 * 1.0080
    assert {c["source"] for c in default["check"]["constants"]} == {"default"}
    assert [w["code"] for w in default["warnings"]] == ["convention_default_used"]


def ver19_balance_golden():
    balanced = valid(call("chem_balance", {"equation": "C3H8 + O2 → CO2 + H2O"}))["value"]
    assert balanced["coefficients"] == [1, 5, 3, 4] and balanced["equation"] == "C3H8 + 5O2 → 3CO2 + 4H2O"
    assert all(row["reactants"] == row["products"] for row in balanced["atom_counts"])
    doubled = call("chem_balance", {"equation": "C3H8 + O2 -> CO2 + H2O", "coefficients": [2, 10, 6, 8]})["value"]
    assert doubled["student"]["balanced"] is True and doubled["student"]["verdict"] == "not_lowest_terms"
    assert doubled["student"]["factor"] == 2
    wrong = call("chem_balance", {"equation": "C3H8 + 5O2 -> 3CO2 + 3H2O"})["value"]["student"]
    assert wrong["verdict"] == "not_balanced" and wrong["unbalanced"] == ["H", "O"]
    # Zero-dimensional: cannot be balanced; more than one dimension: unknown; charge is a row of the matrix.
    impossible = call("chem_balance", {"equation": "NaCl -> Na2O"})["error"]
    assert impossible["code"] == 4 and "cannot be balanced; check the formulas" in impossible["message"]
    several = valid(call("chem_balance", {"equation": "H2 + O2 -> H2O + H2O2"}))
    assert several["value"]["status"] == "unknown" and several["check"]["confidence"] == "undecided"
    assert call("chem_balance", {"equation": "Fe^2+ + Cl2 -> Fe^3+ + Cl-"})["value"]["coefficients"] == [2, 1, 2, 2]
    failures = [c["id"] for c, v in _chemistry_golden()["chem_balance"] if not golden.matches(v, c["expect"])]
    assert failures == []


def ver20_chain_intermediates():
    chain = {"steps": [
        {"id": "n", "op": "amount_from_concentration", "concentration": "0.5 mol dm^-3", "volume": "250 cm^3"},
        {"id": "m", "op": "mass_from_amount", "species": "NaCl", "amount": "@n"}],
        "constants": pack("Na", "Cl"), "sf": 3}  # fmt: skip
    result = valid(call("chem_stoichiometry", chain))
    final = result["value"]["result"]
    assert final["rounded"] == "7.31" and final["value"]["unit"] == "g" and final["value"]["text"] == "117/16"
    # Three intermediate checks before the mass: the volume in dm³, the amount, and the molar mass.
    *intermediates, last = result["working"]
    assert [(w["label"], w["value"], w["unit"]) for w in intermediates] == [
        ("volume in dm³", "0.25", "dm³"), ("n: amount from concentration", "0.125", "mol"),
        ("M(NaCl)", "58.5", "g mol⁻¹")]  # fmt: skip
    assert all(w["check_id"] == CHECK for w in result["working"]) and last["value"] == "7.3125"
    assert [s["value"]["unit"] for s in result["value"]["steps"]] == ["mol", "g"]
    # A volume without its unit is refused rather than guessed.
    bare = {"steps": [{"id": "n", "op": "amount_from_concentration", "concentration": "0.5", "volume": "250"}]}
    assert call("chem_stoichiometry", bare)["error"]["code"] == 4


def ver21_titration_equivalence():
    args = {
        "task": "titration_curve",
        "acid": "HCl",
        "acid_concentration": "0.100 mol dm^-3",
        "acid_volume": "25.0 cm^3",
        "base": "NaOH",
        "base_concentration": "0.100 mol dm^-3",
        "at_volumes": ["25.0 cm^3"],
        "constants": [{"symbol": "Kw", "value": "1.0e-14", "source": "pack"}],
    }
    value = valid(call("chem_acid_base", args))["value"]
    assert value["equivalence"]["volume"]["text"] == "25" and value["equivalence"]["ph"]["rounded"] == "7.00"
    assert value["at"] == [{"volume": value["equivalence"]["volume"], "ph": value["equivalence"]["ph"]}]
    assert value["points"][value["equivalence_index"]] == [25.0, 7.0]
    assert value["start_ph"]["text"] == "1" and value["end_ph"]["rounded"] == "12.52"
    # The steep rise is drawn through the equivalence point, and pH never falls as base is added.
    phs = [p[1] for p in value["points"]]
    assert phs == sorted(phs) and any(4 < p < 7 for p in phs) and any(7 < p < 10 for p in phs)
    # pH of the strong acid and base themselves, exactly; a weak acid is unknown here (A level).
    assert call("chem_acid_base", {"acid": "HCl", "acid_concentration": "0.1 M"})["value"]["ph"]["text"] == "1"
    assert call("chem_acid_base", {"base": "NaOH", "base_concentration": "0.01 M"})["value"]["ph"]["text"] == "12"
    weak = call("chem_acid_base", {"acid": "CH3COOH", "acid_concentration": "0.1 M"})
    assert weak["value"] == {"status": "unknown", "reason": "weak_acid_or_base"}
    # The neutralisation volume, from the mole ratio of the acid's basicity.
    titre = call("chem_acid_base", {"acid": "H2SO4", "acid_concentration": "0.1 M", "acid_volume": "20 cm^3",
                                    "base": "NaOH", "base_concentration": "0.2 M"})["value"]  # fmt: skip
    assert titre["base"]["volume"]["text"] == "20" and titre["ratio"] == {"acid": "1", "base": "2"}


def ver21_calorimetry_sign():
    warming = {"mass": "50 g", "specific_heat": "4.2 J/(g K)", "specific_heat_source": "question",
               "temperature_change": "6.0 K", "amount": "0.025 mol"}  # fmt: skip
    result = valid(call("chem_energetics", warming))["value"]
    assert result["q"]["text"] == "1260"  # Q = m c ΔT = 50 * 4.2 * 6.0 J
    assert result["delta_h"]["text"] == "-252/5" and result["delta_h"]["rounded"] == "-50.4"  # -1.26 kJ / 0.025 mol
    assert (result["nature"], result["sign_convention"]) == ("exothermic", "exothermic_negative")
    cooling = call("chem_energetics", {**warming, "temperature_change": "-2.0 K"})["value"]
    assert cooling["delta_h"]["text"] == "84/5" and cooling["nature"] == "endothermic"
    # Readings in °C give the same change; no stated specific heat capacity is unknown, never a guessed value.
    readings = {k: v for k, v in warming.items() if k != "temperature_change"}
    by_readings = call(
        "chem_energetics", {**readings, "initial_temperature": "19.5 °C", "final_temperature": "25.5 °C"}
    )
    assert by_readings["value"]["delta_h"] == result["delta_h"]
    missing = call("chem_energetics", {"mass": "50 g", "temperature_change": 6, "amount": "0.025 mol"})
    assert missing["value"]["reason"] == "convention_missing"
    # Bond energies: broken minus formed, negative when more is given out.
    bonds = call("chem_energetics", {"broken": [{"bond": "H-H", "energy": 436}, {"bond": "Cl-Cl", "energy": 242}],
                                     "formed": [{"bond": "H-Cl", "count": 2, "energy": 431}]})["value"]  # fmt: skip
    assert bonds["delta_h"]["text"] == "-184" and bonds["nature"] == "exothermic"


# --- exit evidence pulled into M12 (G18, G31) ------------------------------------------------------------------------


def ver02_chain_inputs_from():
    """A stoichiometry result lists the chem_balance and chem_molar_mass checks it consumed."""
    balance_id, mass_id, chain_id = "chk_01JZ00000000000000000000B1", "chk_01JZ00000000000000000000M1", CHECK
    balanced = valid(call("chem_balance", {"equation": "C3H8 + O2 -> CO2 + H2O"}, balance_id))
    molar = valid(call("chem_molar_mass", {"formula": "CO2", "constants": pack("C", "O")}, mass_id))
    chain = {
        "equation": "C3H8 + O2 -> CO2 + H2O",
        "constants": pack("C", "H", "O"),
        "steps": [{"id": "a", "op": "amount_from_mass", "species": "C3H8", "mass": "4.4 g"},
                  {"id": "b", "op": "mole_ratio", "from": "C3H8", "to": "CO2", "amount": "@a"},
                  {"id": "c", "op": "mass_from_amount", "species": "CO2", "amount": "@b"}],
        "cites": [{"check_id": balanced["check"]["check_id"], "check": "chem_balance",
                   "coefficients": balanced["value"]["coefficients"]},
                  {"check_id": molar["check"]["check_id"], "check": "chem_molar_mass", "formula": "CO2",
                   "molar_mass": molar["value"]["molar_mass"]["shown"]}],
    }  # fmt: skip
    result = valid(call("chem_stoichiometry", chain, chain_id))
    assert result["check"]["inputs_from"] == [balance_id, mass_id]
    assert result["value"]["result"]["value"]["text"] == "66/5"  # 0.1 mol propane gives 0.3 mol, 13.2 g of CO2
    by_label = {w["label"]: w["check_id"] for w in result["working"]}
    assert by_label["ratio C3H8 : CO2"] == balance_id and by_label["M(CO2)"] == mass_id
    assert by_label["M(C3H8)"] == chain_id  # not cited: computed and checked in this call
    # A cited check that disagrees with the recomputation is refused; one the chain never used is not listed.
    wrong = {**chain, "cites": [{**chain["cites"][1], "molar_mass": "44.01"}]}
    assert call("chem_stoichiometry", wrong)["error"]["data"]["reason"] == "cited_check_differs"
    unused = {**chain, "steps": chain["steps"][:1]}
    assert "inputs_from" not in valid(call("chem_stoichiometry", unused))["check"]


def vsl13_titration_points_traced():
    """A titration_curve resolved spec contains points only from chem_acid_base results whose check ids are listed."""
    tool_check = "chk_01JZ00000000000000000000T1"
    calls: list[tuple[str, dict]] = []

    def worker(tool: str, args: dict) -> dict:
        calls.append((tool, args))
        return call(tool, args, tool_check)

    acid = {"formula": "HCl", "kind": "acid", "strength": "strong", "concentration": "0.100 mol dm^-3"}
    base = {"formula": "NaOH", "kind": "base", "strength": "strong", "concentration": "0.100 mol dm^-3"}
    request = {
        "spec_version": 1,
        "type": "titration_curve",
        "params": {"analyte": acid, "titrant": base, "analyte_volume": "25.0 cm^3", "marks": ["equivalence_point"]},
    }
    context = VisualContext("chemistry", "O", "S2")
    resolve = Resolver(resolver(worker))
    resolved, _ = validate(request, context, resolve)
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    assert [tool for tool, _ in calls] == ["chem_acid_base"]
    tool_result = call("chem_acid_base", calls[0][1], tool_check)["value"]
    computed = resolved["computed"]
    assert computed["points"] == tool_result["points"] and computed["check_ids"] == [tool_check]
    assert computed["equivalence"]["volume"]["text"] == "25" and computed["equivalence"]["ph"]["text"] == "7"
    assert tool_check in resolved["numbers_from"]
    # Deterministic and cached: the same request resolves to the same bytes with no second tool call.
    again, _ = validate(json.loads(json.dumps(request)), context, resolve)
    assert json.dumps(again, sort_keys=True) == json.dumps(resolved, sort_keys=True) and len(calls) == 1
    # Points with no check record, or an undecided tool, never reach a resolved spec.
    untraced = Resolver(resolver(lambda tool, args: {"value": tool_result}))
    with pytest.raises(VisualError) as raised:
        validate(request, context, untraced)
    assert raised.value.code == "visual_resolution_failed"
    weak = {**request, "params": {**request["params"], "analyte": {**acid, "formula": "CH3COOH", "strength": "weak"}}}
    with pytest.raises(VisualError) as raised:
        validate(weak, context, Resolver(resolver(worker)))
    assert raised.value.code == "visual_resolution_failed"


# --- supporting checks -----------------------------------------------------------------------------------------------


def test_m12c_golden_sets_pass():
    sizes = {name: len(results) for name, results in _chemistry_golden().items()}
    settings = Settings()
    assert all(n >= settings.golden_min_cases_per_tool for n in sizes.values()), sizes
    assert sum(sizes.values()) >= settings.golden_min_cases_per_subject_level
    failures = [
        c["id"] for results in _chemistry_golden().values() for c, v in results if not golden.matches(v, c["expect"])
    ]
    assert failures == []
    for name in M12_CHEMISTRY_TOOLS:
        assert golden.load()[name]["stage"] == "S2" and golden.load()[name]["review"] == "pending"


def test_m12c_check_records_valid():
    for name in sorted(M12_CHEMISTRY_TOOLS):
        for case in golden.load()[name]["cases"][:8]:
            result = call(name, case["args"])
            assert "error" not in result, (name, case["id"], result)
            valid(result)
            assert result["check"]["function"] == name and result["check"]["check_id"] == CHECK
            assert result["check"]["result_sha256"] == golden.result_sha256(result["value"])


def test_m12c_constants_precedence_and_defaults():
    """VER-12 with the chemistry table: question over pack; a default always warns; no default means unknown."""
    entries = [{"symbol": "Ar(Cl)", "value": "35.5", "source": "pack"},
               {"symbol": "ar_cl", "value": "35", "source": "question"}, {"symbol": "Ar(H)", "value": "1",
                                                                         "source": "item"}]  # fmt: skip
    result = call("chem_molar_mass", {"formula": "HCl", "constants": entries})
    assert result["value"]["molar_mass"]["shown"] == "36"
    assert {(c["symbol"], c["source"]) for c in result["check"]["constants"]} == {
        ("Ar(Cl)", "question"),
        ("Ar(H)", "item"),
    }
    gas = call("chem_stoichiometry", {"steps": [{"id": "v", "op": "gas_volume_from_amount", "amount": "0.5 mol"}]})
    assert gas["value"]["result"]["value"]["text"] == "12" and gas["warnings"][0]["code"] == "convention_default_used"
    assert "chemistry defaults table 1" in gas["warnings"][0]["message"]
    faraday = call("chem_stoichiometry", {"steps": [{"id": "e", "op": "electrolysis", "current": "1 A",
                                                     "time": "1 h", "electrons": 2}]})  # fmt: skip
    assert faraday["value"]["reason"] == "convention_missing" and faraday["check"]["confidence"] == "undecided"
    assert call("chem_molar_mass", {"formula": "TcO2"})["value"]["constant"] == "Ar(Tc)"


def test_m12c_tools_offered_early():
    """The S2 chemistry tools ship in the S1 build and are offered to the Solver in a chemistry session."""
    tools = registry()
    assert M12_CHEMISTRY_TOOLS <= set(tools.specs)
    session = SessionCtx(subject="chemistry", level="O", session_id="ses_01JZ0000000000000000000013")
    offered = visible_tools("solver", list(tools.specs), tools, session, lambda spec, ctx: True,
                            REGISTER["roleGrants"], Settings())  # fmt: skip
    assert M12_CHEMISTRY_TOOLS <= {s.name for s in offered}


def inp08_chem_entry_golden():
    """Conditions from the composer are inert text metadata and survive the checker round trip."""
    source = "CaCO3(s) ->[heat] CaO(s) + CO2(g)"
    result = valid(call("chem_balance", {"equation": source}))
    assert result["value"]["coefficients"] == [1, 1, 1]
    assert result["value"]["equation"] == "CaCO3(s) →[heat] CaO(s) + CO2(g)"
    assert [s["formula"] for s in result["value"]["species"]] == ["CaCO3(s)", "CaO(s)", "CO2(g)"]
    # A coefficient claim stays distinct from the checker's computed balancing result.
    claimed = valid(call("chem_balance", {"equation": "2CaCO3(s) ->[heat] CaO(s) + CO2(g)"}))
    assert claimed["value"]["student"]["verdict"] == "not_balanced"
    assert claimed["value"]["student"]["equation"] == "2CaCO3(s) →[heat] CaO(s) + CO2(g)"
    assert valid(call("chem_balance", {"equation": result["value"]["equation"]}))["value"] == result["value"]
