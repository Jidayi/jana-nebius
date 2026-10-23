"""Follow-through recipes checked at pack build (ASM-06, CUR-15) and the content-pack fields they use (`quantities`,
`follow_through`). Items here are synthetic or copies of pack items changed for the test."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.contracts import document
from agent_core.contracts import errors as contract_errors
from jsonschema import Draft202012Validator
from pack_builder import follow_through
from pack_builder.build import categorised_problems, load_source

REPO = Path(__file__).resolve().parents[3]
PHY = REPO / "content" / "curriculum" / "phy" / "o"


def _numeric(value: str, unit: str | None = "J") -> dict[str, Any]:
    return {"kind": "numeric", "value": value, "unit": unit, "unit_policy": "equivalent" if unit else "none",
            "tolerance": {"mode": "relative", "value": 0.01}, "check_id": "chk_build_test_key"}  # fmt: skip


def _item(expression: str = "sqrt(2*E/n)", symbols: dict[str, str] | None = None, **part_b: Any) -> dict[str, Any]:
    b = {
        "id": "b",
        "prompt": "Speed?",
        "marks": 2,
        "answer": _numeric("6", "m/s"),
        "hints": [],
        "ecf": True,
        "uses_parts": ["a"],
        "follow_through": {"expression": expression, "symbols": symbols or {"E": "a"}},
    }
    return {"id": "itm.phy.o.energy.9901", "type": "structured", "quantities": {"m": "2", "v": "3", "n": "0.5"},
            "parts": [{"id": "a", "prompt": "Energy?", "marks": 2, "answer": _numeric("9"), "hints": []},
                      {**b, **part_b}]}  # fmt: skip


def test_recipe_reproducing_the_key_passes() -> None:
    assert follow_through.problems([_item()]) == []
    assert follow_through.problems([_item("(2*E/n)^(1/2)")]) == []


def test_recipe_problems() -> None:
    assert "not the key 6" in "".join(follow_through.problems([_item("2*E/n")]))
    assert "cannot be evaluated" in "".join(follow_through.problems([_item("sqrt(2*E/mass)")]))
    assert "not an earlier numeric part" in "".join(follow_through.problems([_item(symbols={"E": "c"})]))
    assert "not an earlier numeric part" in "".join(follow_through.problems([_item(uses_parts=[])]))
    assert "ecf: true" in "".join(follow_through.problems([_item(ecf=False)]))
    plain = _item()
    del plain["parts"][1]["follow_through"]
    assert follow_through.problems([plain]) == []


def test_contract_validates_the_marking_fields() -> None:
    part = _item()["parts"][1]
    part["hints"] = [{"rung": n, "text": {"en": f"Hint {n}."}} for n in range(1, 6)]
    assert contract_errors("content/content-pack#/$defs/ItemPart", part) == []
    bad = copy.deepcopy(part)
    bad["follow_through"]["symbols"] = {"E": "part a"}
    assert contract_errors("content/content-pack#/$defs/ItemPart", bad)
    quantities = {"type": "object", "additionalProperties": False, "properties": {"quantities": document(
        "content/content-pack")["$defs"]["Item"]["properties"]["quantities"]}}  # fmt: skip
    assert not list(Draft202012Validator(quantities).iter_errors({"quantities": _item()["quantities"]}))
    for wrong in ({"m": "2 kg"}, {"2m": "2"}, {"m": 2}):  # a number in the stem's unit, under a symbol, as text
        assert list(Draft202012Validator(quantities).iter_errors({"quantities": wrong})), wrong


def test_build_reports_a_recipe_that_misses_its_key() -> None:
    """The pack build runs the recipe check with the marker check (a seeded fault on a copy of a pack item)."""
    source = load_source(PHY)
    first = next(i for i in source.tables["items"] if i["id"] == "itm.phy.o.atom.0001")
    item = copy.deepcopy(first)
    second = copy.deepcopy(item["parts"][0])
    second.update(id="b", prompt="How many nucleons are not neutrons?", ecf=True, uses_parts=["a"],
                  follow_through={"expression": "A + N", "symbols": {"N": "a"}})  # fmt: skip
    second["answer"] = {**second["answer"], "value": "95"}
    item.update(id="itm.phy.o.atom.0999", type="structured", quantities={"A": "241", "Z": "95"},
                parts=[item["parts"][0], second])  # fmt: skip
    source.tables["items"].append(item)
    grouped, _ = categorised_problems(source, Settings())
    found = [p for p in grouped["verify"] if "follow-through" in p]
    assert found and "itm.phy.o.atom.0999 part b" in found[0] and "not the key 95" in found[0], grouped["validate"]
    # The build's contract validation takes the item's quantities and recipe (D90); a quantity is a plain number.
    assert not [p for p in grouped["validate"] if "itm.phy.o.atom.0999" in p], grouped["validate"]
    assert contract_errors("content/content-pack#/$defs/Item", item) == []
    assert contract_errors("content/content-pack#/$defs/Item", {**item, "quantities": {"A": "241 u", "Z": "95"}})
