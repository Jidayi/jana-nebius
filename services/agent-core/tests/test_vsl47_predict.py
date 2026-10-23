"""VSL-47 in the engine: a simulation request that names a predict scenario gets the scenario's starting values (the
model can name the scenario, never change the case it is built on), its description never gives the result away
before the student predicts, and a misconception that survives its fix points the Coach at the scenario built
around its usual guess."""

import json
from types import SimpleNamespace

import pytest
from agent_core.assets.generated.sim_scenarios import SIM_SCENARIOS
from agent_core.assets.resolvers import resolver
from agent_core.assets.visuals import Resolver, VisualContext, VisualError, scenarios_for, validate
from agent_core.contracts import errors as contract_errors
from agent_core.engine.live_flows import _note
from agent_core.engine.tutor_flows import MisconceptionFlow
from jana_tools import REPO_ROOT
from jana_tools.visual_fixtures import _call

CIRCUIT = "poe.phy.circuit_series_to_parallel.v1"
TITRATION = "poe.chm.titration_double_strength_alkali.v1"


def _resolve(subject: str, request: dict) -> dict:
    resolved, _ = validate(request, VisualContext(subject, "O", "S2"), Resolver(resolver(_call("vsl47"))))
    assert contract_errors("visuals/visual-spec#/$defs/resolved", resolved) == []
    return resolved


def vsl47_scenario_sets_starting_values():
    # The request asks for one 4 Ω resistor in parallel at 12 V; the scenario's case (two 10 Ω in series at 6 V) wins.
    request = {
        "spec_version": 1,
        "type": "circuit_sim",
        "params": {
            "emf": 12,
            "resistors": [{"id": "R1", "resistance": 4}],
            "arrangement": "parallel",
            "predict": CIRCUIT,
        },
    }
    resolved = _resolve("physics", request)
    params = resolved["params"]
    assert params["predict"] == CIRCUIT
    assert (params["emf"], params["arrangement"]) == (6, "series")
    assert params["resistors"] == [{"id": "R1", "resistance": 10}, {"id": "R2", "resistance": 10}]
    assert set(params["locked"]) == {"emf", "R1", "R2", "switch"}
    # The starting readouts are still the tool's: 6 V across 20 Ω.
    assert resolved["computed"]["labels"]["out.current"] == "3/10"


def vsl47_description_withholds_the_result():
    titration = {
        "spec_version": 1,
        "type": "titration_sim",
        "params": {
            "acid": {"formula": "HCl", "concentration": 0.1},
            "base": {"formula": "NaOH", "concentration": 0.1},
            "acid_volume": 25,
            "indicator": "phenolphthalein",
            "predict": TITRATION,
        },
    }
    resolved = _resolve("chemistry", titration)
    assert resolved["params"]["base"]["concentration"] == 0.2
    summary = resolved["alt"]["summary"]
    assert "12.5" not in summary and "end point" not in summary and "after you predict" in summary
    # Without a scenario the description gives the end point as before.
    free = _resolve(
        "chemistry", {**titration, "params": {k: v for k, v in titration["params"].items() if k != "predict"}}
    )
    assert "end point is at 25" in free["alt"]["summary"]


def test_vsl47_unknown_or_foreign_scenario_is_refused():
    base = {"emf": 6, "resistors": [{"id": "R1", "resistance": 10}], "arrangement": "series"}
    for predict in ("poe.phy.made_up.v1", TITRATION):
        request = {"spec_version": 1, "type": "circuit_sim", "params": {**base, "predict": predict}}
        with pytest.raises(VisualError) as error:
            validate(request, VisualContext("physics", "O", "S2"), Resolver(resolver(_call("vsl47"))))
        assert error.value.code == "visual_param_invalid"
        assert CIRCUIT in error.value.hint  # the one the model may name instead (VSL-17)


def test_vsl47_scenarios_are_the_renderers():
    source = json.loads((REPO_ROOT / "packages/renderers/src/sims/scenarios.json").read_text())
    assert SIM_SCENARIOS == {s["id"]: s for s in source["scenarios"]}
    for scenario in SIM_SCENARIOS.values():
        subject = scenario["subject"]
        path = REPO_ROOT / "content/curriculum" / subject / "o/misconceptions" / f"{scenario['misconception_id']}.yaml"
        assert path.exists(), scenario["id"]


def vsl47_coach_pointed_at_the_scenario():
    engine = SimpleNamespace(knowledge=None)
    flow = MisconceptionFlow(
        "mc.phy.o.parallel_adding_branch_raises_resistance", "kc.phy.o.circuits.parallel_circuits", 1
    )
    flow.matched(1)
    flow.check_item()
    assert flow.check_answered(correct=False) == "switch_representation"
    note = _note(engine, flow)
    assert f'circuit_sim with params {{"predict": "{CIRCUIT}"}}' in note and "do not tell them the result first" in note
    # Only where the fix did not hold, and only for a misconception a scenario is built around.
    flow.node = "name_and_fix"
    assert "predict" not in _note(engine, flow)
    other = MisconceptionFlow("mc.phy.o.series_current_used_up", "kc.phy.o.circuits.series_circuits", 1)
    other.node = "switch_representation"
    assert "predict" not in _note(engine, other)
    assert [s["id"] for s in scenarios_for("mc.chm.o.acids_titration_values_swapped")] == [TITRATION]
