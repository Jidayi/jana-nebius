"""M6.c and M6.d: the curriculum map, the pack builder and verification before load (CUR-01 to CUR-05, CUR-07,
CUR-08, CUR-19 to CUR-24). Mutated packs are copies of the S1 source with one seeded fault each; every record and
diagram in them is invented test data."""

from __future__ import annotations

import copy
import json
import re
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.contracts import validate
from agent_core.store.catalogue import available, catalogue, coverage_gaps
from agent_core.store.packs import (
    TABLES,
    PackShelf,
    from_document,
    read_pack,
    table_sha256,
    to_document,
    verify,
    write_pack,
)
from pack_builder import pipeline
from pack_builder import source as tree
from pack_builder.build import BuildError
from pack_builder.build import build as _build
from signing_service.keys import DEV_KEY_ID, dev_key

REPO = Path(__file__).resolve().parents[3]
SOURCE = REPO / "content" / "curriculum" / "phy" / "o"
S1_TOPIC = "cur.phy.o.motion_forces_and_energy.motion"  # the S1 slice's one topic (TABLE CUR-01a)
REVIEWED_AT = "2026-10-09T10:00:00.000Z"
# The tests edit a copy of the source tree by table, as the M6 files grouped them.
GROUPS = {"map.yaml": ("curriculum_nodes", "kcs", "conventions"), "items.yaml": ("items",),
          "misconceptions.yaml": ("misconceptions",), "worked_examples.yaml": ("worked_examples",)}  # fmt: skip


def build(source: Path, out: Path, **kw: Any) -> Any:
    """A build signed with the development key, as the signing service signs it."""
    kw.setdefault("key", dev_key())
    kw.setdefault("key_id", DEV_KEY_ID)
    return _build(source, out, **kw)


def _copy(tmp_path: Path) -> Path:
    """A copy of the S1 slice of the physics source: the motion KCs and the records published with them. The pack
    now holds the whole O level syllabus; these tests seed faults in the S1 records they were written against."""
    target = tmp_path / "src" / "phy" / "o"
    shutil.copytree(SOURCE, target)
    shutil.copytree(tree.ref_dir(SOURCE), tree.ref_dir(target))
    _, found = tree.read_pack(target)
    kcs = [copy.deepcopy(k.record) for k in found["kcs"] if k.record["node_id"] == S1_TOPIC]
    s1 = {kc["id"] for kc in kcs}
    for located in found["mock_papers"]:  # the mock papers draw on topics the slice leaves out
        located.path.unlink()
    for table in ("items", "worked_examples", "misconceptions", "lessons"):
        for located in found[table]:
            record = located.record
            if not _shipping(record) or not set(record["kc_ids"]) & s1:
                located.path.unlink()
    _prune(target, s1)
    for kc in kcs:
        kc["prerequisites"] = [e for e in kc["prerequisites"] if e["kc_id"] in s1]
        kc["misconception_ids"] = [m for m in kc["misconception_ids"] if (target / "misconceptions" / f"{m}.yaml")
                                   .is_file()]  # fmt: skip
    tree.write_table(target, "kcs", kcs)
    return target


def _shipping(record: dict[str, Any]) -> bool:
    """A record students have: published or banked, or a verified new version of a published record (an edit, CUR-19)
    whose published version stays live until the next release."""
    status = record["review"]["status"]
    edited = status == "verified" and "published" in record["authoring"]["history"]
    return status in ("published", "in_eval_bank") or edited


def _as_released(target: Path) -> Path:
    """The source as the next release publishes it: every banked record becomes published (AUT-33), and so does a
    verified edit of a published record once it is banked (CUR-22 never holds it out), so a new version waiting in
    the pipeline counts as its published version does (CUR-19)."""
    _, found = tree.read_pack(target)
    for table in ("items", "worked_examples", "misconceptions", "lessons"):
        for located in found[table]:
            record = located.record
            if record["review"]["status"] != "published" and _shipping(record):
                banked = ["in_eval_bank"] if record["review"]["status"] == "verified" else []
                history = [*record["authoring"]["history"], *banked, "published"]
                tree.save_record(target, table, {**record, "review": {**record["review"], "status": "published"},
                                                 "authoring": {**record["authoring"], "history": history}})  # fmt: skip
    return target


def _prune(target: Path, s1: set[str]) -> None:
    """Keep the slice self-contained (every referenced id exists, CUR-25): misconceptions keep only slice KCs and
    probes, items drop part misconception ids outside the slice, and a record that still names a missing id (a
    diagnostic distractor, a lesson block) leaves the slice; repeated until nothing changes."""
    while True:
        _, found = tree.read_pack(target)
        known = {r.record["id"] for t in ("items", "worked_examples", "misconceptions") for r in found[t]}
        changed = False
        for located in found["misconceptions"]:
            record = copy.deepcopy(located.record)
            record["kc_ids"] = [k for k in record["kc_ids"] if k in s1]
            record["probe_item_ids"] = [i for i in record["probe_item_ids"] if i in known]
            if record != located.record:
                tree.save_record(target, "misconceptions", record)
                changed = True
        for located in found["items"]:
            record = copy.deepcopy(located.record)
            record["kc_ids"] = [k for k in record["kc_ids"] if k in s1]
            for part in record["parts"]:
                if "misconception_ids" in part:
                    part["misconception_ids"] = [m for m in part["misconception_ids"] if m in known]
            named = [o["misconception_id"] for p in record["parts"] for o in p["answer"].get("options", [])
                     if "misconception_id" in o]  # fmt: skip
            example = record["solution"].get("worked_example_id")
            if any(m not in known for m in named) or (example is not None and example not in known):
                located.path.unlink()
                changed = True
            elif record != located.record:
                tree.save_record(target, "items", record)
                changed = True
        for table in ("worked_examples", "lessons"):
            for located in found[table]:
                text = json.dumps({k: v for k, v in located.record.items() if k not in ("id", "kc_ids")})
                if any(ref not in known for ref in re.findall(r'"((?:itm|wex|mc)\.[a-z0-9_.]+)"', text)):
                    located.path.unlink()
                    changed = True
        if not changed:
            return


def _edit(source: Path, filename: str, change: Callable[[dict[str, Any]], None]) -> None:
    if filename == "pack.yaml":
        path = source / filename
        data = yaml.safe_load(path.read_text())
        change(data)
        path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return
    _, found = tree.read_pack(source)
    data = {table: [copy.deepcopy(r.record) for r in found[table]] for table in GROUPS[filename]}
    change(data)
    for table in GROUPS[filename]:
        tree.write_table(source, table, data.get(table, []))


def _problems(source: Path, tmp_path: Path, **kw: Any) -> str:
    with pytest.raises(BuildError) as failed:
        build(source, tmp_path / "out", **kw)
    return "\n".join(failed.value.problems)


def _by_id(records: list[dict[str, Any]], rid: str) -> dict[str, Any]:
    return next(r for r in records if r["id"] == rid)


# --- CUR-01 ---------------------------------------------------------------------------------------------------------


def cur01_availability_matches_stage(tmp_path: Path) -> None:
    settings = Settings()
    assert [(c.subject, c.level, c.scope) for c in catalogue("S1")] == [("phy", "o", "one topic")]
    assert {(c.subject, c.level) for c in catalogue("S2")} == {("mth", "o"), ("phy", "o"), ("chm", "o"), ("acc", "o")}
    assert len(catalogue("S3")) == 10
    # The published S1 pack meets its coverage target and is shown; with too few published records per KC it is
    # listed but hidden until it does.
    built = build(_as_released(_copy(tmp_path / "s1")), tmp_path / "out")
    _, tables = read_pack(built.pack_path)
    assert coverage_gaps("S1", tables, settings) == []
    assert [(a.subject, a.level) for a in available("S1", {"pack.phy.o": tables}, settings)] == [("phy", "o")]
    short = copy.deepcopy(tables)
    short["items"] = short["items"][: len(short["items"]) // 3]
    assert coverage_gaps("S1", short, settings)
    assert available("S1", {"pack.phy.o": short}, settings) == []
    # A pack that meets the S1 target (published records, enough per KC) is shown.
    full = copy.deepcopy(tables)
    full["kcs"] = full["kcs"][:1]
    kc = full["kcs"][0]["id"]
    published = {"status": "published", "reviewers": []}
    full["items"] = [{"id": f"i{n}", "kc_ids": [kc], "review": published} for n in range(15)]
    full["worked_examples"] = [{"id": f"w{n}", "kc_ids": [kc], "review": published} for n in range(2)]
    full["misconceptions"] = [{"id": f"m{n}", "kc_ids": [kc], "review": published} for n in range(2)]
    full["lessons"] = [{"id": "l0", "review": published}]
    assert [(a.subject, a.level) for a in available("S1", {"pack.phy.o": full}, settings)] == [("phy", "o")]
    assert available("S1", {"pack.mth.o": full}, settings) == []  # not produced in S1, whatever is installed


# --- CUR-02, CUR-03, CUR-04, CUR-05 ---------------------------------------------------------------------------------


def cur02_id_patterns_and_no_reuse(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    _edit(source, "map.yaml", lambda d: d["kcs"].append({**d["kcs"][0], "code": "PHY-O-02.01.K09"}))
    _edit(source, "items.yaml", lambda d: d["items"][0].update(id="itm.phy.o.motion.12"))
    _edit(source, "misconceptions.yaml", lambda d: d["misconceptions"][0].update(id="mc.chm.o.stray"))
    problems = _problems(source, tmp_path)
    assert "kc.phy.o.motion.distance_or_displacement: duplicate id" in problems
    assert "itm.phy.o.motion.12: $.id: 'itm.phy.o.motion.12' does not match" in problems
    # A retired id is never reused, whether retired in the source or in an earlier version.
    source = _copy(tmp_path / "again")
    _edit(source, "pack.yaml", lambda d: d.update(retired_ids=["wex.phy.o.motion.0001"]))
    assert "wex.phy.o.motion.0001: reuses a retired id" in _problems(source, tmp_path)
    source = _copy(tmp_path / "third")
    problems = _problems(source, tmp_path, retired=["itm.phy.o.motion.0003"])
    assert "itm.phy.o.motion.0003: reuses a retired id" in problems
    # Ids of another subject in this pack are refused too (the contract pattern allows any subject).
    source = _copy(tmp_path / "fourth")
    _edit(source, "misconceptions.yaml", lambda d: d["misconceptions"][0].update(id="mc.chm.o.stray"))
    assert "mc.chm.o.stray: not a mc id of phy.o" in _problems(source, tmp_path)


def cur03_map_structure_valid(tmp_path: Path) -> None:
    assert build(_copy(tmp_path / "s1"), tmp_path / "ok").manifest["pack_id"] == "pack.phy.o"

    def fault(change: Callable[[dict[str, Any]], None]) -> str:
        source = _copy(tmp_path / f"case{len(list(tmp_path.iterdir()))}")
        _edit(source, "map.yaml", change)
        return _problems(source, tmp_path)

    def cycle(d: dict[str, Any]) -> None:
        nodes = d["curriculum_nodes"]
        _by_id(nodes, "cur.phy.o.motion_forces_and_energy.density").update(
            parent_id="cur.phy.o.motion_forces_and_energy.momentum"
        )
        _by_id(nodes, "cur.phy.o.motion_forces_and_energy.momentum").update(
            parent_id="cur.phy.o.motion_forces_and_energy.density"
        )

    assert "the map has a cycle" in fault(cycle)
    space = "cur.phy.o.space_physics"
    orphan = fault(lambda d: _by_id(d["curriculum_nodes"], space).update(parent_id="cur.phy.o.gone"))
    assert "cur.phy.o.space_physics: orphan" in orphan
    on_subject = fault(lambda d: d["kcs"][0].update(node_id="cur.phy.o"))
    assert "hangs only from a topic or subtopic, not a subject" in on_subject
    weights = fault(lambda d: _by_id(d["curriculum_nodes"], "cur.phy.o.waves").update(exam_weight=0.2))
    assert "topic exam weights sum to 1.030" in weights
    # Within the tolerance is accepted.
    source = _copy(tmp_path / "within")
    _edit(source, "map.yaml", lambda d: _by_id(d["curriculum_nodes"], "cur.phy.o.waves").update(exam_weight=0.185))
    build(source, tmp_path / "within-out")


def cur04_kc_minimum_content(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    _edit(source, "map.yaml", lambda d: d["kcs"][0].update(statement="Distance and displacement are different things"))
    _edit(source, "map.yaml", lambda d: d["kcs"][1].update(statement="Calculate " + "x" * 130))
    problems = _problems(source, tmp_path)
    assert "kc.phy.o.motion.distance_or_displacement: the statement does not start with an observable verb" in (
        problems
    )
    assert "kc.phy.o.motion.average_speed: the statement has 140 characters (under 140)" in problems
    # A published pack (pilot channel) needs a published item and worked example for every KC.
    source = _copy(tmp_path / "pilot")
    _edit(source, "pack.yaml", lambda d: d.update(channel="pilot"))

    def unpublish(d: dict[str, Any]) -> None:
        for table in ("items", "worked_examples"):
            for record in d.get(table, []):
                if "kc.phy.o.motion.choose_equation" in record.get("kc_ids", []):
                    record["review"] = {**record["review"], "status": "verified"}

    _edit(source, "items.yaml", unpublish)
    _edit(source, "worked_examples.yaml", unpublish)
    problems = _problems(source, tmp_path)
    assert "kc.phy.o.motion.choose_equation: no published item assesses it" in problems
    assert "kc.phy.o.motion.choose_equation: no published worked example shows it" in problems


def cur05_prereq_graph_acyclic_resolved(tmp_path: Path) -> None:
    def fault(change: Callable[[dict[str, Any]], None]) -> str:
        source = _copy(tmp_path / f"case{len(list(tmp_path.iterdir()))}")
        _edit(source, "map.yaml", change)
        return _problems(source, tmp_path)

    def cycle(d: dict[str, Any]) -> None:
        _by_id(d["kcs"], "kc.phy.o.motion.distance_or_displacement")["prerequisites"] = [
            {"kc_id": "kc.phy.o.motion.free_fall", "strength": "helpful"}
        ]

    assert "prerequisite cycle: " in fault(cycle)
    unknown = fault(lambda d: d["kcs"][2]["prerequisites"].append({"kc_id": "kc.phy.o.motion.nowhere",
                                                                    "strength": "required"}))  # fmt: skip
    assert "prerequisite kc.phy.o.motion.nowhere is not a known KC" in unknown

    def retired(d: dict[str, Any]) -> None:
        _by_id(d["kcs"], "kc.phy.o.motion.choose_equation")["status"] = "retired"

    assert "prerequisite kc.phy.o.motion.choose_equation is retired" in fault(retired)

    def cross(d: dict[str, Any]) -> None:
        d["kcs"][8]["prerequisites"].append({"kc_id": "kc.mth.o.algebra.rearrange_linear", "strength": "required"})

    assert "is in pack.mth.o, not declared" in fault(cross)
    # Declared in the manifest's depends_on_packs, the cross-pack edge is accepted.
    source = _copy(tmp_path / "declared")
    _edit(source, "map.yaml", cross)
    _edit(source, "pack.yaml", lambda d: d.update(depends_on_packs=[{"pack_id": "pack.mth.o", "min_version": "0.1.0"}]))
    build(source, tmp_path / "declared-out")


# --- CUR-07, CUR-08 -------------------------------------------------------------------------------------------------


def cur07_pack_contract_roundtrip(tmp_path: Path) -> None:
    built = build(_copy(tmp_path / "s1"), tmp_path / "out")
    document = json.loads(built.json_path.read_text())
    validate("content/content-pack", document)
    manifest, tables = read_pack(built.pack_path)
    assert to_document(manifest, tables) == document
    hashes = {t["name"]: t["sha256"] for t in manifest["tables"]}
    assert {name: table_sha256(name, records) for name, records in tables.items()} == hashes
    # SQLite -> JSON -> SQLite: the same table hashes, and a file that verifies like the original.
    again = tmp_path / "again.pack"
    write_pack(again, *from_document(json.loads(json.dumps(document))))
    manifest2, tables2 = read_pack(again)
    assert manifest2 == manifest
    assert {name: table_sha256(name, records) for name, records in tables2.items()} == hashes
    verify(again, Environment.DEV)
    # Every contract table is written, except search vectors, which need an embedding model (CUR-30, D79).
    assert set(TABLES) - {"search_vectors"} == set(tables)


def _tampered(original: Path, target: Path, table: str) -> Path:
    shutil.copy(original, target)
    conn = sqlite3.connect(target)
    row_id, record = conn.execute(f"SELECT id, record FROM {table} ORDER BY id LIMIT 1").fetchone()  # noqa: S608
    flipped = record.replace('"', "'", 1) if table == "never" else _flip_one_byte(record)
    conn.execute(f"UPDATE {table} SET record = ? WHERE id = ?", (flipped, row_id))  # noqa: S608
    conn.commit()
    conn.close()
    return target


def _flip_one_byte(text: str) -> str:
    """Change one character inside a JSON string value, keeping the JSON valid."""
    index = text.index('":"') + 3
    swapped = "B" if text[index] != "B" else "C"
    return text[:index] + swapped + text[index + 1 :]


def cur08_tampered_pack_rejected(tmp_path: Path) -> None:
    built = build(_copy(tmp_path / "s1"), tmp_path / "out")
    shelf = PackShelf(Environment.DEV)
    assert shelf.install(built.pack_path)
    good = shelf.manifest("pack.phy.o")
    candidates = ["manifest", *(t["name"] for t in good["tables"] if t["rows"])]  # type: ignore[index]
    for table in candidates:
        bad = _tampered(built.pack_path, tmp_path / f"bad-{table}.pack", table)
        assert not shelf.install(bad), table
        assert shelf.active["pack.phy.o"][0] == built.pack_path  # the previous version stays active
        assert shelf.rejected[-1][0] == bad
    # A pack signed with a key nobody trusts, or with the test root in a production build, is refused too.
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    foreign = build(
        _copy(tmp_path / "s1b"), tmp_path / "foreign", key=Ed25519PrivateKey.generate(), key_id="key_dev_test"
    )
    assert not shelf.install(foreign.pack_path)
    assert not PackShelf(Environment.PRODUCTION).install(built.pack_path)
    # The refusal carries the message key the adult's pack screen shows (G51).
    from agent_core.store.packs import DAMAGED_MESSAGE_KEY, PackRejectedError, list_packs

    assert PackRejectedError.message_key == DAMAGED_MESSAGE_KEY == "pack.damaged"
    # The pack list (API-29) verifies each installed file as it lists it: a damaged one says so, and the screen shows
    # `pack.damaged` for it; a file too damaged to read is still listed by its name.
    shelf_dir = tmp_path / "installed"
    shelf_dir.mkdir()
    shutil.copy(built.pack_path, shelf_dir / "pack.phy.o.pack")
    _tampered(built.pack_path, shelf_dir / "pack.chm.o.pack", candidates[-1])
    (shelf_dir / "pack.bio.o.pack").write_bytes(b"not a pack")
    listed = [(p["pack_id"], p["signature_ok"]) for p in list_packs(shelf_dir, Environment.DEV)]
    # By file name: the unreadable file, the tampered copy (its manifest still names pack.phy.o), the good pack.
    assert listed == [("pack.bio.o", False), ("pack.phy.o", False), ("pack.phy.o", True)]


# --- CUR-19, CUR-20, CUR-21 -----------------------------------------------------------------------------------------


def cur19_pipeline_no_skips(tmp_path: Path) -> None:
    walks = list(pipeline.paths(limit=14))
    assert walks
    for walk in walks:
        # Every way to published passes verified, then in_eval_bank, in that order, after the last return to drafted
        # (D65: there is no approval state).
        restart = len(walk) - 1 - walk[::-1].index("drafted")
        tail = walk[restart:]
        assert tail.index("verified") < tail.index("in_eval_bank") < tail.index("published")
    # A record whose history skips a state, or claims published without the gates, fails the build.
    for history in (
        ["drafted", "in_eval_bank", "published"],
        ["drafted", "verified", "published"],
        ["drafted", "verified", "in_review", "approved", "in_eval_bank", "published"],
    ):
        source = _copy(tmp_path / f"h{len(history)}{history[1]}")

        def forge(d: dict[str, Any], history: list[str] = history) -> None:
            item = d["items"][0]
            item["authoring"]["history"] = history
            item["review"] = {"status": "published", "reviewers": []}

        _edit(source, "items.yaml", forge)
        assert "is not a pipeline step" in _problems(source, tmp_path)
    # Reaching verified requires this build's verification to pass.
    source = _copy(tmp_path / "unverified")
    _edit(source, "items.yaml", lambda d: d["items"][0]["parts"][0]["answer"].update(value="9.0"))
    assert "reached verified without passing tool verification" in _problems(source, tmp_path)


def cur20_wrong_key_fails_build(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    _edit(source, "items.yaml", lambda d: d["items"][1]["parts"][0]["answer"].update(value="2.5"))
    problems = _problems(source, tmp_path)
    assert ("itm.phy.o.motion.0002 part a: key 2.5 does not match math_evaluate result 2.0 "
            "(chk_build_phy_k_0002_a)") in problems  # fmt: skip
    # A number in a solution step that no check produced fails too, as does a wrong worked-example answer.
    source = _copy(tmp_path / "step")
    _edit(source, "items.yaml", lambda d: d["items"][0]["solution"]["steps"][2].update(latex="v = 7.5\\ \\text{m/s}"))
    _edit(source, "worked_examples.yaml",
          lambda d: d["worked_examples"][1]["final_answer"].update(latex="3.5\\ \\text{m/s}^2"))  # fmt: skip
    problems = _problems(source, tmp_path)
    assert "itm.phy.o.motion.0001: solution step 3 shows 7.5" in problems
    assert "wex.phy.o.motion.0002: final answer 3.5\\ \\text{m/s}^2 does not show math_evaluate result" in problems
    # Every check record names the tool and its version.
    report = json.loads(build(_copy(tmp_path / "s1"), tmp_path / "ok").report_path.read_text())
    assert report["checks"] and all(c["function"] and c["function_version"] for c in report["checks"])
    assert all(c["check_id"].startswith("chk_build_") for c in report["checks"])


def cur20_hint_leak_fails_build(tmp_path: Path) -> None:
    source = _copy(tmp_path)

    def leak(d: dict[str, Any]) -> None:
        d["items"][1]["parts"][0]["hints"][2]["text"]["en"] = "Divide 12 by 6.0 to get 2.0 m/s²."

    _edit(source, "items.yaml", leak)
    assert "itm.phy.o.motion.0002 part a: hint 3 gives away the final answer 2.0" in _problems(source, tmp_path)
    # Rung 5 is the full step and may state the answer (the shipped item does).
    build(_copy(tmp_path / "s1"), tmp_path / "ok")


# --- CUR-23, CUR-24 -------------------------------------------------------------------------------------------------

# An imported diagram, as a full library entry (VSL-22) on one of our own drawings; only its licence fields matter here.
DIAGRAM = {
    **yaml.safe_load((SOURCE / "diagrams" / "dgm.phy.plane_mirror_reflection.v1.yaml").read_text()),
    "id": "dgm.phy.motion_strip.v1",
    "title": "Ticker-tape strip for steady acceleration",
    "licence": "CC-BY-4.0",
    "attribution": "Synthetic Test Source, test diagram set",
    "sources": [{"title": "Synthetic test diagram set", "url": "https://example.org/test-diagrams",
                 "licence": "CC-BY-4.0", "attribution": "Synthetic Test Source", "modifications": "Recoloured",
                 "retrieved": "2026-10-01"}],
}  # fmt: skip


def cur23_licence_gate(tmp_path: Path) -> None:
    def with_source(licence: str, table: str = "items") -> str:
        source = _copy(tmp_path / f"{table}-{licence}")

        def add(d: dict[str, Any]) -> None:
            ids = ("itm.phy.o.motion.0001", "mc.phy.o.final_velocity_over_time")
            record = next(r for r in d[table] if r["id"] in ids)
            record["provenance"] = {**record["provenance"], "origin": "adapted", "sources": [
                {**DIAGRAM["sources"][0], "licence": licence}]}  # type: ignore[index]  # fmt: skip

        _edit(source, f"{table}.yaml", add)
        return _problems(source, tmp_path)

    # Share-alike, non-commercial and no-derivatives sources never reach items, misconceptions or other records.
    for licence in ("CC-BY-SA-4.0", "CC-BY-NC-4.0", "CC-BY-ND-4.0"):
        assert "itm.phy.o.motion.0001" in with_source(licence)
    assert "mc.phy.o.final_velocity_over_time" in with_source("CC-BY-SA-3.0", "misconceptions")
    # A share-alike diagram is allowed as a separate asset; a non-commercial one is not.
    source = _copy(tmp_path / "diagram-sa")
    sa = {**copy.deepcopy(DIAGRAM), "licence": "CC-BY-SA-4.0"}
    sa["sources"][0]["licence"] = "CC-BY-SA-4.0"  # type: ignore[index]
    tree.write_table(source, "diagrams", [sa])
    build(source, tmp_path / "diagram-sa-out")
    nc = copy.deepcopy(sa)
    nc["sources"][0]["licence"] = "CC-BY-NC-4.0"  # type: ignore[index]
    tree.write_table(source, "diagrams", [nc])
    assert "dgm.phy.motion_strip.v1" in _problems(source, tmp_path)


def cur24_attribution_generated(tmp_path: Path) -> None:
    source = _copy(tmp_path)
    tree.write_table(source, "diagrams", [DIAGRAM])
    # A diagram ships (and is credited) once the contract carries drawings: build under the visual additions.
    from test_m17_diagrams import visual_contract

    with visual_contract():
        built = build(source, tmp_path / "out")
        page = built.credits_path.read_text()
        report = json.loads(built.report_path.read_text())
    assert [c["title"] for c in report["credits"]] == ["Synthetic test diagram set"]
    for field in ("Synthetic test diagram set", "https://example.org/test-diagrams", "CC-BY-4.0",
                  "Synthetic Test Source", "Recoloured", "2026-10-01"):  # fmt: skip
        assert field in page
    # Removing the attribution from the imported diagram fails the build.
    for missing in ("attribution", "sources"):
        broken = copy.deepcopy(DIAGRAM)
        if missing == "attribution":
            broken["attribution"] = ""
        else:
            del broken["sources"][0]["attribution"]  # type: ignore[attr-defined]
        tree.write_table(source, "diagrams", [broken])
        assert "dgm.phy.motion_strip.v1" in _problems(source, tmp_path)
    # A pack of our own work says so on its credits page.
    assert "our own original work" in build(_copy(tmp_path / "s1"), tmp_path / "own").credits_path.read_text()


# --- ASM-03 (pulled forward) ----------------------------------------------------------------------------------------


def asm03_unknown_marker_rejected(tmp_path: Path) -> None:
    source = _copy(tmp_path)

    def short_text(d: dict[str, Any]) -> None:
        item = d["items"][0]
        item["type"] = "short_text"
        item["parts"][0]["answer"] = {"kind": "short_text", "model_answer": "Speed is distance over time.",
                                      "concept_sets": [{"mark_point_id": "B1", "any_of": ["distance"]}]}  # fmt: skip

    _edit(source, "items.yaml", short_text)
    assert "itm.phy.o.motion.0001: no marker for item type short_text in this build" in _problems(source, tmp_path)


# --- VER-12 ---------------------------------------------------------------------------------------------------------


def ver12_default_table_and_pack_constants(tmp_path: Path) -> None:
    from tool_worker.functions.maths import math_evaluate
    from tool_worker.registry import CallContext

    context = CallContext("t", "chk_01JZ0000000000000000000000", {}, {}, lambda: False, settings={})
    value, extras = math_evaluate({"expression": "g * 2", "constants": [{"symbol": "g", "source": "default"}]}, context)
    assert value["exact"]["decimal"].startswith("19.6133")
    assert extras["constants"] == [{"symbol": "g", "value": "9.80665", "source": "default", "unit": "m/s^2"}]
    assert [(w["code"], "table 1" in w["message"]) for w in extras["warnings"]] == [("convention_default_used", True)]
    # No default exists for other constants: the check is unknown, never a guessed value.
    value, extras = math_evaluate({"expression": "R * 2", "constants": [{"symbol": "R", "source": "default"}]}, context)
    assert value == {"status": "unknown", "reason": "convention_missing"}

    # A pack item whose check needs g takes the pack's stated value; without it the build fails.
    def needs_g(d: dict[str, Any]) -> None:
        d["items"][3]["checks"]["chk_build_phy_k_0004_a"]["args"] = {
            "expression": "1/2*g*2.0^2", "sf": 3, "constants": [{"symbol": "g", "source": "pack"}]}  # fmt: skip

    source = _copy(tmp_path / "stated")
    _edit(source, "items.yaml", needs_g)
    build(source, tmp_path / "stated-out")  # phy.g = 9.8 in the pack: 19.6 m as keyed

    source = _copy(tmp_path / "unstated")
    _edit(source, "items.yaml", needs_g)
    _edit(source, "map.yaml", lambda d: d.update(conventions=[c for c in d["conventions"] if c["key"] != "phy.g"]))
    problems = _problems(source, tmp_path)
    assert "itm.phy.o.motion.0004: chk_build_phy_k_0004_a needs a constant that neither" in problems

    # M12: the physics checkers resolve g the same way, in a worker call and in a pack build.
    from tool_worker.functions.projectile import phys_projectile

    drop = {"motion": "vertical", "speed": 0, "height": "19.6"}
    value, extras = phys_projectile(drop, context)  # no g stated anywhere: the tool default, visibly
    assert extras["constants"][0]["source"] == "default" and value["g"]["text"] == "196133/20000"
    assert [(w["code"], "table 1" in w["message"]) for w in extras["warnings"]] == [("convention_default_used", True)]

    def projectile_needs_g(d: dict[str, Any]) -> None:  # the time of a 19.6 m drop is 2.0 s with the pack's g
        d["items"][3]["checks"]["chk_build_phy_k_0004_a"] = {
            "tool": "phys_projectile", "args": {**drop, "constants": [{"symbol": "g", "source": "pack"}]}}  # fmt: skip

    source = _copy(tmp_path / "projectile-stated")
    _edit(source, "items.yaml", projectile_needs_g)
    build(source, tmp_path / "projectile-out")
    source = _copy(tmp_path / "projectile-unstated")
    _edit(source, "items.yaml", projectile_needs_g)
    _edit(source, "map.yaml", lambda d: d.update(conventions=[c for c in d["conventions"] if c["key"] != "phy.g"]))
    problems = _problems(source, tmp_path / "projectile")
    assert "itm.phy.o.motion.0004: chk_build_phy_k_0004_a needs a constant that neither" in problems
