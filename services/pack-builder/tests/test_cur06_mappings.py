"""CUR-06 (D113): board mappings are mapping facts only. The build refuses text in a code, a point named twice on one
record, a subtopic code outside its topic's and a KC scheme the map does not use; every shipped source passes. The
seeded records are invented test data."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from pack_builder.build import load_source
from pack_builder.curriculum import mapping_problems

REPO = Path(__file__).resolve().parents[3]
CURRICULUM = REPO / "content" / "curriculum"


def _point(code: str, scheme: str = "board_1234", coverage: str = "full") -> dict[str, str]:
    return {"scheme": scheme, "code": code, "coverage": coverage}


def _records() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = [
        {"id": "cur.phy.o", "kind": "subject", "parent_id": None},
        {"id": "cur.phy.o.waves", "kind": "topic", "parent_id": "cur.phy.o", "external_mappings": [_point("3")]},
        {"id": "cur.phy.o.waves.sound", "kind": "subtopic", "parent_id": "cur.phy.o.waves",
         "external_mappings": [_point("3.2")]},
        {"id": "cur.phy.o.waves.sound.echo", "kind": "subtopic", "parent_id": "cur.phy.o.waves.sound",
         "external_mappings": [_point("3.2.1", coverage="partial")]},
        {"id": "cur.phy.o.space", "kind": "topic", "parent_id": "cur.phy.o"},
        {"id": "cur.phy.o.space.orbits", "kind": "subtopic", "parent_id": "cur.phy.o.space",
         "external_mappings": [_point("7.1")]},
    ]  # fmt: skip
    kcs = [{"id": "kc.phy.o.sound.echo_distance", "node_id": "cur.phy.o.waves.sound",
            "external_mappings": [_point("3.2", coverage="partial")]}]  # fmt: skip
    return nodes, kcs


def cur06_mapping_facts_checked() -> None:
    nodes, kcs = _records()
    # Codes under their topic's (or under a topic with no mapping in that scheme) and a KC in a used scheme pass.
    assert mapping_problems(nodes, kcs) == []

    def fault(change: Any) -> list[str]:
        n, k = copy.deepcopy(nodes), copy.deepcopy(kcs)
        change(n, k)
        return mapping_problems(n, k)

    text = fault(lambda n, k: n[2].update(external_mappings=[_point("Describe the speed of sound")]))
    assert text[0] == ("cur.phy.o.waves.sound: board_1234 code 'Describe the speed of sound' is not a code (CUR-06: "
                       "no board text)")  # fmt: skip
    twice = fault(lambda n, k: n[1]["external_mappings"].append(_point("3", coverage="partial")))
    assert twice == ["cur.phy.o.waves: maps board_1234 3 twice"]
    outside = fault(lambda n, k: n[2].update(external_mappings=[_point("4.1")]))
    assert outside == ["cur.phy.o.waves.sound: board_1234 code 4.1 is not under its topic's (3)"]
    # A nested subtopic is checked against its topic, not its parent subtopic.
    nested = fault(lambda n, k: n[3].update(external_mappings=[_point("30.1")]))
    assert nested == ["cur.phy.o.waves.sound.echo: board_1234 code 30.1 is not under its topic's (3)"]
    # A cycle of subtopics (map_problems reports it) ends the walk to the topic instead of looping.
    assert fault(lambda n, k: n[2].update(parent_id="cur.phy.o.waves.sound.echo")) == []
    unused = fault(lambda n, k: k[0].update(external_mappings=[_point("1", scheme="other_99")]))
    assert unused == ["kc.phy.o.sound.echo_distance: maps other_99, a scheme the map does not use"]

    # Every shipped subject source passes, and every subject with a map is mapped to at least one board syllabus.
    sources = sorted(p.parent for p in CURRICULUM.glob("*/*/map.yaml"))
    assert sources
    for path in sources:
        tables = load_source(path).tables
        assert mapping_problems(tables["curriculum_nodes"], tables["kcs"]) == [], path
        assert any(n.get("external_mappings") for n in tables["curriculum_nodes"]), f"{path}: no board mapping"
