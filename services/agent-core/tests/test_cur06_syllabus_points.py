"""CUR-06 (D113): syllabus points on the subject map. A KC without its own board mappings takes its node's, a lesson
takes those of the KCs it teaches, and a topic outside the board's syllabus has none. Against the real core with
packs built from the repository's curriculum sources; replies are validated against the command contract. One
physics KC is given its own mapping as test data."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import test_m13g_learn as learn
from api_harness import start_core, stop_core
from test_m13g_learn import CHANGE, LESSON, SETTINGS, SPEED, Client, install, run, source

CAMBRIDGE_4024 = {"scheme": "cambridge_4024", "board": "Cambridge", "syllabus_code": "4024"}
OWN = {"scheme": "cambridge_5054", "code": "1.2", "coverage": "partial"}


def _tiles(reply: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {t["node_id"]: t for s in reply["sections"] for t in s["topics"]}


def cur06_kc_and_lesson_points(tmp_path: Path) -> None:
    physics = copy.deepcopy(source("phy"))
    for kc in physics["kcs"]:
        if kc["id"] == SPEED:
            kc["external_mappings"] = [{"scheme": OWN["scheme"], "code": OWN["code"], "coverage": OWN["coverage"]}]
    kept = learn.SOURCES.get("phy")
    learn.SOURCES["phy"] = physics
    try:
        install(tmp_path, "phy")
    finally:
        learn.SOURCES["phy"] = kept if kept is not None else source("phy")
    install(tmp_path, "mth")
    install(tmp_path, "acc")

    async def scenario() -> None:
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            maths = await c.ok("GET", "/v1/curriculum/cur.mth.o/map", definition="SubjectMap")
            assert maths["syllabuses"] == [CAMBRIDGE_4024]
            tiles = _tiles(maths)
            nodes = {n["id"]: n for n in source("mth")["curriculum_nodes"]}
            for node_id, tile in tiles.items():
                own = nodes[node_id].get("external_mappings") or []
                assert tile["syllabus_points"] == own
                for kc in tile["kcs"]:
                    assert kc["syllabus_points"] == own, "a KC without its own mappings takes its node's"
            # Calculus is beyond the board's O level syllabus: no points, so a syllabus filter hides it.
            beyond = [t for n, t in tiles.items() if n.startswith("cur.mth.o.calculus")]
            assert beyond and all(t["syllabus_points"] == [] for t in beyond)
            assert all(k["syllabus_points"] == [] for t in beyond for k in t["kcs"])
            for section in maths["sections"]:
                assert section["syllabus_points"] == (nodes[section["node_id"]].get("external_mappings") or [])

            physics_map = await c.ok("GET", "/v1/curriculum/cur.phy.o/map", definition="SubjectMap")
            assert [s["scheme"] for s in physics_map["syllabuses"]] == ["cambridge_5054"]
            motion = _tiles(physics_map)["cur.phy.o.motion_forces_and_energy.motion"]
            kcs = {k["kc_id"]: k for k in motion["kcs"]}
            assert kcs[SPEED]["syllabus_points"] == [OWN], "a KC's own mapping wins over its node's"
            assert kcs[CHANGE]["syllabus_points"] == motion["syllabus_points"] != []
            (lesson,) = [les for les in motion["lessons"] if les["lesson_id"] == LESSON]
            expected: list[dict[str, str]] = []
            for kc_id in next(les for les in source("phy")["lessons"] if les["id"] == LESSON)["kc_ids"]:
                for point in kcs[kc_id]["syllabus_points"] if kc_id in kcs else []:
                    if point not in expected:
                        expected.append(point)
            assert lesson["syllabus_points"] == expected and OWN in expected

            # Accounting is mapped to Cambridge 7707 at section level; costing is outside it.
            accounts = await c.ok("GET", "/v1/curriculum/cur.acc.o/map", definition="SubjectMap")
            assert [s["syllabus_code"] for s in accounts["syllabuses"]] == ["7707"]
            sheets = _tiles(accounts)
            assert sheets["cur.acc.o.costing"]["syllabus_points"] == []
            mapped = [t for n, t in sheets.items() if n != "cur.acc.o.costing"]
            assert all(t["syllabus_points"] for t in mapped)
        finally:
            await stop_core(r)

    run(scenario())
