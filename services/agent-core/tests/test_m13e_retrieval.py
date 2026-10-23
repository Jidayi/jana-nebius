"""M13.e: the pack search index, topic-first curriculum retrieval and the knowledge tools (CUR-30, MEM-21, TOL-21,
TOL-29).

Packs are built from the repository's own content sources and signed with the development content key, then loaded
the way the device loads them (signature and every table hash verified). The KC named in TOL-29's acceptance does not
exist in the physics pack, so `tol29_*` add it, with one linked misconception, as a synthetic test fixture. The
embedder here is a test double (feature-hashed word counts), not an embedding model.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import socket
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.engine.knowledge_tools import KnowledgeTools
from agent_core.retrieval.embedding import EmbeddingModel
from agent_core.retrieval.index import KnowledgeIndex, terms
from agent_core.retrieval.knowledge import PACK_NOTE
from agent_core.retrieval.passages import derive
from agent_core.store import packs
from agent_core.store.packs import read_pack, table_sha256, write_pack
from agent_core.tools.executor import ToolCall, ToolExecutor
from agent_core.tools.spec import SessionCtx
from agent_core.tools.specs import registry
from agent_core.tools.spill import SpillStore
from jana_tools import REPO_ROOT
from pack_builder.build import build, load_source
from signing_service.hierarchy import dev_signer

DEV = Environment.DEV
SIGNED_AT = "2026-10-12T09:00:00.000Z"
CURRICULUM = REPO_ROOT / "content" / "curriculum"
SUBJECTS = ("phy", "chm", "acc", "mth")
# The physics pack's version as its source states it: every passage and lookup cites it.
PHY_VERSION = str(load_source(CURRICULUM / "phy" / "o").pack["version"])
SPEC_KC = "kc.phy.o.kinematics.acceleration_from_velocities"  # TOL-29's acceptance example
FIXTURE_PREREQUISITES = [
    {"kc_id": "kc.phy.o.motion.distance_or_displacement", "strength": "required"},
    {"kc_id": "kc.phy.o.motion.acceleration_from_change", "strength": "helpful"},
]

Tables = dict[str, list[dict[str, Any]]]


def run(coro: Any) -> Any:
    return asyncio.run(coro)


class HashingEmbedder:
    """A test double for an embedding model: each word adds one to a hashed dimension. Deterministic and offline."""

    def __init__(self, model_id: str = "test-hashing", version: str = "1", dimensions: int = 64) -> None:
        self._model = EmbeddingModel(model_id, version, dimensions)

    @property
    def model(self) -> EmbeddingModel:
        return self._model

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        out = []
        for text in texts:
            vector = [0.0] * self._model.dimensions
            for word in terms(text):
                vector[int(hashlib.sha256(word.encode()).hexdigest(), 16) % self._model.dimensions] += 1.0
            out.append(vector)
        return out


@contextmanager
def search_contract() -> Iterator[None]:
    """The content-pack contract's tables, search tables included (D79), for the block."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(packs, "TABLES", packs.contract_tables())
        yield


def _sign(manifest: dict[str, Any]) -> dict[str, Any]:
    return dev_signer().sign("content_pack", manifest, now=SIGNED_AT)


def _signed_pack(path: Path, pack: dict[str, Any], tables: Tables) -> Path:
    """A pack written and signed as the signing service signs one, from a source's pack fields and tables."""
    manifest = {**{k: v for k, v in pack.items() if k != "retired_ids"}, "schema_version": "1.0.0",
                "tables": [{"name": t, "sha256": table_sha256(t, rows), "rows": len(rows)}
                           for t, rows in tables.items()], "retired_ids": []}  # fmt: skip
    write_pack(path, _sign(manifest), tables)
    return path


@pytest.fixture(scope="module")
def sources() -> list[tuple[dict[str, Any], Tables]]:
    """The four O level sources as (pack fields, record tables): the content the device would index."""
    out = []
    for subject in SUBJECTS:
        source = load_source(CURRICULUM / subject / "o")
        out.append((dict(source.pack), {t: list(rows) for t, rows in source.tables.items()}))
    return out


@pytest.fixture(scope="module")
def all_packs(sources: list[tuple[dict[str, Any], Tables]]) -> KnowledgeIndex:
    return KnowledgeIndex.from_tables(sources)


@pytest.fixture(scope="module")
def physics(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The physics pack built and signed as released today (the bundled contract has no search tables yet)."""
    out = tmp_path_factory.mktemp("built")
    return build(CURRICULUM / "phy" / "o", out, sign_with=_sign).pack_path


@pytest.fixture(scope="module")
def fixture_pack(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The physics pack plus a synthetic topic holding TOL-29's example KC, two prerequisite edges into the motion
    KCs and two linked misconceptions (one listed on the KC, one naming the KC), signed with the development key."""
    source = load_source(CURRICULUM / "phy" / "o")
    tables = {t: list(rows) for t, rows in source.tables.items()}
    tables["curriculum_nodes"].append({"id": "cur.phy.o.kinematics", "code": "PHY-O-09", "kind": "topic",
                                       "parent_id": "cur.phy.o", "title": "Kinematics (test fixture)", "order": 9,
                                       "subject": "phy", "level": "o", "status": "active"})  # fmt: skip
    tables["kcs"].append({"id": SPEC_KC, "code": "PHY-O-09.K01", "node_id": "cur.phy.o.kinematics",
                          "statement": "Find an acceleration from a starting velocity, a final velocity and a time",
                          "kind": "procedural", "tools": [], "exam_weight": 0.1,
                          "prerequisites": FIXTURE_PREREQUISITES,
                          "misconception_ids": ["mc.phy.o.final_velocity_over_time"], "skill_ids": [],
                          "version": "0.1.0", "status": "active"})  # fmt: skip
    tables["misconceptions"].append({"id": "mc.phy.o.fixture_adds_velocities", "kc_ids": [SPEC_KC],
                                     "student_name": "Adding the velocities (fixture)",
                                     "description": "Adds the two velocities before dividing by the time.",
                                     "signatures": [{"kind": "answer_transform", "expression": "(u+v)/t"}],
                                     "fix": {"strategy": "counterexample", "text": {"en": "Subtract the start."}},
                                     "probe_item_ids": [], "severity": "low", "version": "0.1.0"})  # fmt: skip
    folder = tmp_path_factory.mktemp("fixture")
    return _signed_pack(folder / "pack.phy.o-0.1.0.pack", dict(source.pack), tables)


def _executor(index: KnowledgeIndex, tmp_path: Path) -> ToolExecutor:
    settings = Settings()
    executor = ToolExecutor(registry(), settings, SpillStore(tmp_path / "spill"))
    KnowledgeTools(index, settings).bind(executor.host_executors)
    return executor


def _call(executor: ToolExecutor, name: str, args: dict[str, Any], role: str) -> dict[str, Any]:
    session = SessionCtx(role=role, subject="physics", stage="S1")
    return run(executor.run_one(ToolCall("call_test_1", name, args), role, session))


# --- CUR-30 ------------------------------------------------------------------------------------------------------


def cur30_embedding_mismatch_fallback(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    built_with = HashingEmbedder("test-hashing", "1")
    with search_contract():
        built = build(CURRICULUM / "phy" / "o", tmp_path / "out", sign_with=_sign, embedder=built_with)
        manifest, tables = read_pack(built.pack_path)
    assert manifest["embedding_model"] == {"id": "test-hashing", "version": "1", "dimensions": 64}
    assert {t["name"] for t in manifest["tables"]} >= {"search_fts", "search_vectors"}
    assert len(tables["search_vectors"]) == len(tables["search_fts"]) > 0
    query = "acceleration from the gradient of a velocity-time graph"
    keyword_only = KnowledgeIndex.from_tables([(manifest, tables)])
    expected = [h.passage.id for h in keyword_only.search(query, limit=5)]

    caplog.set_level(logging.WARNING, logger="agent_core.retrieval.index")
    other = KnowledgeIndex.from_tables([(manifest, tables)], embedder=HashingEmbedder("test-hashing", "2"))
    assert other.packs["pack.phy.o"].vectors_used is False
    assert [h.passage.id for h in other.search(query, limit=5)] == expected  # keyword only
    assert other.mismatches and "test-hashing@1" in other.mismatches[0] and "test-hashing@2" in other.mismatches[0]
    assert any("searching by keyword only" in r.getMessage() for r in caplog.records)

    same = KnowledgeIndex.from_tables([(manifest, tables)], embedder=built_with)
    assert same.packs["pack.phy.o"].vectors_used is True and same.mismatches == []
    assert same.search(query, limit=5)  # the fused ranking still answers


def test_search_tables_are_derived_by_the_build(tmp_path: Path, physics: Path) -> None:
    """The build writes `search_fts` (and no vectors without an embedder); a pack without the tables is indexed from
    its verified records with the same passages."""
    with search_contract():
        built = build(CURRICULUM / "phy" / "o", tmp_path / "out", sign_with=_sign)
        manifest, tables = read_pack(built.pack_path)
        assert packs.verify(built.pack_path, DEV) == manifest
    assert "embedding_model" not in manifest and "search_vectors" not in tables
    assert tables["search_fts"] == [p.record() for p in derive(tables)]
    # A pack built before the search tables (D79) carries none: it is indexed from its verified records alike.
    older = {name: rows for name, rows in tables.items() if name not in ("search_fts", "search_vectors")}
    with_table = KnowledgeIndex.from_tables([(manifest, tables)])
    derived = KnowledgeIndex.from_tables([(manifest, older)])
    assert with_table.passages == derived.passages


def test_index_loads_only_verified_packs(tmp_path: Path, physics: Path) -> None:
    folder = tmp_path / "packs"
    folder.mkdir()
    good = folder / physics.name
    good.write_bytes(physics.read_bytes())
    manifest, tables = read_pack(physics)
    tables["misconceptions"][0] = {**tables["misconceptions"][0], "description": "changed after signing"}
    write_pack(folder / "pack.chm.o-0.1.0.pack", {**manifest, "pack_id": "pack.chm.o"}, tables)
    index = KnowledgeIndex.load(sorted(folder.glob("*.pack")), DEV)
    assert list(index.packs) == ["pack.phy.o"]
    assert [name for name, _ in index.rejected] == ["pack.chm.o-0.1.0.pack"]


# --- MEM-21 ------------------------------------------------------------------------------------------------------


def mem21_topic_scoped(all_packs: KnowledgeIndex) -> None:
    """For every topic, retrieval with the words of every KC of every subject returns only the topic's passages or
    passages about a KC listed as a prerequisite of one of its KCs."""
    index = all_packs
    topics = index.topics()
    assert len(topics) >= 30 and {t.split(".")[1] for t in topics} == set(SUBJECTS)
    queries = [k.statement for k in index.kcs.values()][::3]
    returned = 0
    for topic in topics:
        mine = set(index.kcs_in_topic(topic))
        needs = index.prerequisite_kcs(topic)
        for query in queries:
            for hit in index.search(query, topic_ids=[topic], limit=8):
                p = hit.passage
                assert topic in p.topic_ids or needs & set(p.kc_ids), (topic, query, p.id)
                returned += 1
        for hit in index.grounding([topic], queries[0], 4000):
            p = hit.passage
            assert p.kind in ("lesson", "misconception")
            assert topic in p.topic_ids or needs & set(p.kc_ids), (topic, p.id)
        assert mine
    assert returned > 1000


def test_grounding_reaches_the_coach_prompt(all_packs: KnowledgeIndex, tmp_path: Path) -> None:
    """Bound to an engine, the index offers the knowledge tools and grounds tier 5 with the topic's passages, each
    cited by pack id, version and passage id (MEM-21)."""
    from engine_harness import close, make_engine

    async def scenario() -> tuple[bool, bool, tuple[Any, ...]]:
        engine, _ = await make_engine(tmp_path, {}, worker=False)
        spec = engine.deps.registry.specs["content_search"]
        session = SessionCtx(role="coach", subject="physics", stage="S1")
        before = engine.deps.executor.available(spec, session)
        engine.bind_knowledge(all_packs)
        after = engine.deps.executor.available(spec, session)
        engine.state.practice = {"item": {"id": "itm.phy.o.motion.0001", "kc_ids": ["kc.phy.o.motion.average_speed"]}}
        passages = engine._prompt_base()["passages"]
        await close(engine)
        return before, after, passages

    before, after, passages = run(scenario())
    assert before is False and after is True
    assert passages and all(p.id.startswith(f"pack.phy.o@{PHY_VERSION}:") for p in passages)
    for p in passages:
        found = all_packs.passage("pack.phy.o", p.id.split(":", 1)[1])
        assert found is not None and "cur.phy.o.motion_forces_and_energy" in found.topic_ids
        assert found.kind in ("lesson", "misconception")


# --- TOL-21 ------------------------------------------------------------------------------------------------------


def tol21_results_cite_pack(physics: Path, tmp_path: Path) -> None:
    index = KnowledgeIndex.load([physics], DEV)
    executor = _executor(index, tmp_path)
    _, tables = read_pack(physics)
    records = {r["id"]: (t, r) for t in ("lessons", "worked_examples", "misconceptions", "items") for r in tables[t]}
    settings = Settings()
    queries = [
        "average speed of a runner",
        "deceleration is negative",
        "area under a velocity-time graph",
        "convert km/h to m/s",
        "free fall under gravity",
        "choose an equation of uniform acceleration",
    ]
    cited = 0
    for query in queries:
        result = _call(executor, "content_search", {"query": query}, "coach")
        assert result["status"] == "ok", result
        data = result["data"]
        assert data["note"] == PACK_NOTE and 0 < data["count"] <= settings.content_search_max_results
        for passage in data["results"]:
            assert index.packs[passage["pack_id"]].version == passage["version"] == PHY_VERSION
            resolved = index.passage(passage["pack_id"], passage["passage_id"])
            assert resolved is not None and resolved.kind == passage["kind"]
            assert resolved.record_id in records  # the record is in the signed pack file
            cited += 1
    assert cited >= len(queries)
    none = _call(executor, "content_search", {"query": "photosynthesis chlorophyll stomata"}, "coach")
    assert none["status"] == "ok" and none["data"]["count"] == 0  # the Coach's "not sure" path
    kinds = _call(executor, "content_search", {"query": "average speed", "kinds": ["misconception"], "limit": 2},
                  "coach")  # fmt: skip
    assert [p["kind"] for p in kinds["data"]["results"]] == ["misconception", "misconception"]


# --- TOL-29 ------------------------------------------------------------------------------------------------------


def tol29_lookup_by_kc(fixture_pack: Path, tmp_path: Path) -> None:
    index = KnowledgeIndex.load([fixture_pack], DEV)
    _, tables = read_pack(fixture_pack)
    record = next(k for k in tables["kcs"] if k["id"] == SPEC_KC)
    result = _call(_executor(index, tmp_path), "curriculum_lookup", {"kc_id": SPEC_KC}, "diagnoser")
    assert result["status"] == "ok", result
    data = result["data"]
    cite = {"pack_id": "pack.phy.o", "version": PHY_VERSION}
    assert [n["id"] for n in data["nodes"]] == ["cur.phy.o.kinematics"]
    assert [k["id"] for k in data["kcs"]] == [SPEC_KC]
    graph = {(SPEC_KC, p["kc_id"], p["strength"]) for p in record["prerequisites"]}
    assert {(e["kc_id"], e["requires"], e["strength"]) for e in data["prerequisites"]} == graph
    linked = set(record["misconception_ids"]) | {m["id"] for m in tables["misconceptions"] if SPEC_KC in m["kc_ids"]}
    assert {m["id"] for m in data["misconceptions"]} == linked == {"mc.phy.o.final_velocity_over_time",
                                                                   "mc.phy.o.fixture_adds_velocities"}  # fmt: skip
    for entry in [*data["nodes"], *data["kcs"], *data["prerequisites"], *data["misconceptions"]]:
        assert {k: entry[k] for k in cite} == cite
    narrowed = _call(_executor(index, tmp_path), "curriculum_lookup", {"query": SPEC_KC, "include": "misconceptions"},
                     "diagnoser")["data"]  # fmt: skip
    assert set(narrowed) == {"note", "misconceptions", "count"}
    assert {m["id"] for m in narrowed["misconceptions"]} == linked


def tol29_unknown_id_not_substituted(fixture_pack: Path, tmp_path: Path) -> None:
    index = KnowledgeIndex.load([fixture_pack], DEV)
    executor = _executor(index, tmp_path)
    typo = "kc.phy.o.kinematics.acceleration_from_velocity"
    result = _call(executor, "curriculum_lookup", {"kc_id": typo}, "diagnoser")
    assert result["status"] == "error" and result["error"]["code"] == "invalid_args"
    detail = result["error"]["message"]
    assert SPEC_KC in detail  # a suggestion
    suggested = detail.split("did you mean: ", 1)[1].split(", ")
    assert 1 <= len(suggested) <= Settings().curriculum_lookup_max_suggestions
    assert "data" not in result
    statements = [k["statement"] for k in read_pack(fixture_pack)[1]["kcs"]]
    assert not any(s in json.dumps(result) for s in statements)  # no record of another KC
    unknown_node = _call(executor, "curriculum_lookup", {"node_id": "cur.phy.o.optics"}, "diagnoser")
    assert unknown_node["error"]["code"] == "invalid_args"
    nothing = _call(executor, "curriculum_lookup", {"query": "photosynthesis chlorophyll"}, "diagnoser")
    assert nothing["status"] == "ok" and nothing["data"]["count"] == 0
    both = _call(executor, "curriculum_lookup", {"kc_id": SPEC_KC, "query": "speed"}, "diagnoser")
    assert both["error"]["code"] == "invalid_args"


# Golden lookups over the physics pack: (arguments, the node ids, KC ids and misconception ids expected).
GOLDEN: list[tuple[dict[str, Any], list[str], list[str], list[str]]] = [
    ({"kc_id": "kc.phy.o.motion.average_speed"}, ["cur.phy.o.motion_forces_and_energy.motion"],
     ["kc.phy.o.motion.average_speed"], ["mc.phy.o.average_of_speeds", "mc.phy.o.rest_time_left_out",
                                         "mc.phy.o.time_over_distance"]),
    ({"query": "kc.phy.o.motion.free_fall", "include": "nodes"}, ["cur.phy.o.motion_forces_and_energy.motion"],
     ["kc.phy.o.motion.free_fall"], []),
    ({"node_id": "cur.phy.o.motion_forces_and_energy.mass_and_weight"},
     ["cur.phy.o.motion_forces_and_energy.mass_and_weight"],
     ["kc.phy.o.mass_weight.mass_or_weight", "kc.phy.o.mass_weight.weight_from_mass"],
     ["mc.phy.o.balance_types_confused", "mc.phy.o.mass_changes_with_g", "mc.phy.o.mass_weight_roles_swapped",
      "mc.phy.o.mass_weight_units_swapped", "mc.phy.o.no_mass_in_space", "mc.phy.o.planet_g_mismatched",
      "mc.phy.o.planet_g_ratio_inverted", "mc.phy.o.weight_given_as_mass_number",
      "mc.phy.o.weight_grams_not_converted", "mc.phy.o.weight_mass_divided_by_g",
      "mc.phy.o.weight_same_on_every_planet"]),
]  # fmt: skip


def tol29_offline_read_only(physics: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_core.store.local import open_local

    stores = open_local(tmp_path / "data", app_version="0.0.0", now_ms=1)
    learner = stores.learner_path
    stores.learner.close()
    stores.device.close()
    before = {p: p.read_bytes() for p in (learner, physics)}

    def no_network(*args: Any, **kwargs: Any) -> Any:
        raise OSError("network disabled for this test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    index = KnowledgeIndex.load([physics], DEV)
    executor = _executor(index, tmp_path)
    for args, nodes, kcs, misconceptions in GOLDEN:
        result = _call(executor, "curriculum_lookup", args, "diagnoser")
        assert result["status"] == "ok", (args, result)
        data = result["data"]
        assert [n["id"] for n in data.get("nodes", [])] == nodes, args
        assert [k["id"] for k in data.get("kcs", [])] == kcs, args
        assert sorted(m["id"] for m in data.get("misconceptions", [])) == misconceptions, args
    query = _call(executor, "curriculum_lookup", {"query": "velocity-time graph gradient"}, "diagnoser")
    assert query["status"] == "ok" and 0 < query["data"]["count"] <= Settings().curriculum_lookup_max_candidates
    assert all(p.read_bytes() == data for p, data in before.items())  # no side effect on the learner store or pack
    spec = registry().specs["curriculum_lookup"]
    assert spec.meta.risk == "read" and not spec.meta.side_effects and not spec.meta.uses_network
