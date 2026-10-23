"""Contract fixtures must exercise the selected conditional's union, including required referenced fields."""

from jana_tools.codegen import CONTRACTS
from jana_tools.codegen.sources import NAMESPACE, load_contracts
from jana_tools.fixtures import synth


def test_science_conditional_union_generates_a_complete_ok_result():
    generator = synth(load_contracts(CONTRACTS))
    name = NAMESPACE + "tools/science-compute#/$defs/EquilibriumResult"
    node, base = generator.resolve(name, name.split("#")[0])
    value = generator.gen(node, base)
    assert value["status"] == "ok"
    assert "constant" in value
    assert generator.validator({"$ref": name}).is_valid(value)
    assert not generator.validator({"$ref": name}).is_valid({"status": "ok"})
