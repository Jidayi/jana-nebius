"""M13.a: KC migrations replay learner data (CUR-10). The learners, logs, KCs and the split are synthetic."""

from __future__ import annotations

import math
import random
from dataclasses import replace
from typing import Any

import pytest
from agent_core.learner.kc_migrations import KcMigrations, MigrationError
from agent_core.learner.mastery import KcEvidence, MasteryParams, kc_probability
from agent_core.learner.projections import Projector
from agent_core.learner.service import Learner
from agent_core.store.events import StoredEvent
from agent_core.store.pack_index import PackIndex
from learner_harness import KCS, Clock, Session, random_log
from test_m6e_marking_mastery import _reference_replay

OLD = KCS[0]
NEW = ("kc.phy.o.kinematics.speed_average", "kc.phy.o.kinematics.speed_instantaneous")
WEIGHTS = (0.7, 0.3)
SPLIT = {"from_kc_id": OLD, "from_version": "1.4.0", "to_version": "2.0.0",
         "to": [{"kc_id": NEW[0], "weight": WEIGHTS[0]}, {"kc_id": NEW[1], "weight": WEIGHTS[1]}]}  # fmt: skip
SUBJECT = {"phy": "physics", "mth": "mathematics"}


def _index(rows: list[dict[str, Any]]) -> PackIndex:
    """The content index of the installed major version, as the runtime builds it from the verified packs."""
    manifest = {"pack_id": "pack.phy.o", "version": "2.0.0"}
    return PackIndex.from_tables([(manifest, {"kcs": [], "kc_migrations": rows})])


def _by_hand(events: list[StoredEvent]) -> list[StoredEvent]:
    """The recorded log as the new map reads it, rewritten here independently of the implementation: an attempt's
    weight on the old KC is shared by the split's weights, and an error blamed on it goes to the larger part."""
    out = []
    for event in events:
        payload = dict(event.payload)
        if event.type == "attempt":
            tags = []
            for tag in payload["kc_ids"]:
                if tag["kc_id"] == OLD:
                    tags += [{"kc_id": kc, "weight": tag["weight"] * w} for kc, w in zip(NEW, WEIGHTS, strict=True)]
                else:
                    tags.append(tag)
            payload["kc_ids"] = tags
        if event.type == "verdict" and payload.get("first_error_kc") == OLD:
            payload["first_error_kc"] = NEW[0]
        out.append(replace(event, payload=payload))
    return out


def _probabilities(learner: Learner, params: MasteryParams) -> tuple[dict[str, float], dict[str, float]]:
    theta = dict(learner.conn.execute("SELECT subject, theta FROM subject_ability"))
    now = {}
    for kc, succ, fail in learner.conn.execute("SELECT kc_id, succ_w, fail_w FROM kc_mastery"):
        now[kc] = kc_probability(theta[SUBJECT[kc.split(".")[1]]], KcEvidence(succ, fail), params)
    return now, theta


def cur10_kc_split_migration_replay() -> None:
    params = MasteryParams()
    checked = 0
    for seed in range(30):
        recorded = random_log(seed, sessions=4)  # recorded while the old pack, with the unsplit KC, was installed
        attempts_before = dict(recorded.conn.execute("SELECT kc_id, attempts FROM kc_mastery"))
        events = list(recorded.log.merged())
        # The new major version is installed: its migrations change the projections' parameters, so they are stale
        # and rebuilt from the event log through the split.
        learner = Learner(recorded.log, Projector(recorded.conn, params, _index([SPLIT])))
        assert set(learner.projector.stale()) == {p.name for p in learner.projector.projections}
        learner.projector.ensure_current()
        got, theta = _probabilities(learner, params)
        expected, expected_theta = _reference_replay(_by_hand(events), params)
        assert OLD not in got, "no mastery stays on the retired KC"
        assert set(expected) <= set(got)  # a KC with only a mastery check has a row and no observation
        for subject, value in expected_theta.items():
            assert math.isclose(theta[subject], value, abs_tol=1e-9), (seed, subject)
        for kc, value in expected.items():
            assert math.isclose(got[kc], value, abs_tol=1e-9), (seed, kc)
        # No student loses evidence: every opportunity on the old KC now counts on each part of it.
        if OLD in attempts_before:
            checked += 1
            after = dict(learner.conn.execute("SELECT kc_id, attempts FROM kc_mastery"))
            assert after[NEW[0]] == after[NEW[1]] == attempts_before[OLD]
            rows = learner.conn.execute("SELECT kc_ids FROM attempts").fetchall()
            assert all(OLD not in r[0] for r in rows), "attempt rows name the new KCs"
        # Evidence still tagged with the old KC (from a device on the old pack) folds onto the new KCs as it arrives,
        # exactly as a rebuild would.
        clock = Clock(max(e.stamp.physical for e in events) + 86_400_000)
        learner.log.clock.wall_ms = clock
        Session(random.Random(seed + 1000), learner, clock).run(3)
        folded = learner.projector.checksum()
        learner.projector.rebuild()
        assert learner.projector.checksum() == folded, seed
    assert checked >= 10, "enough logs carry evidence on the split KC"


def test_cur10_chains_merges_and_cycles() -> None:
    """A later split of a split KC is followed to the end; a merge adds weights; a cycle is refused."""
    later = {"from_kc_id": NEW[0], "from_version": "2.0.0", "to_version": "3.0.0",
             "to": [{"kc_id": "kc.phy.o.kinematics.speed_a", "weight": 0.5},
                    {"kc_id": "kc.phy.o.kinematics.speed_b", "weight": 0.5}]}  # fmt: skip
    chained = KcMigrations.from_rows([SPLIT, later])
    assert dict(chained.targets[OLD]) == pytest.approx(
        {"kc.phy.o.kinematics.speed_a": 0.35, "kc.phy.o.kinematics.speed_b": 0.35, NEW[1]: 0.3}
    )
    merge = [{"from_kc_id": KCS[1], "from_version": "1.0.0", "to_version": "2.0.0",
              "to": [{"kc_id": KCS[2], "weight": 1.0}]}]  # fmt: skip
    merged = KcMigrations.from_rows(merge)
    assert merged.weighted([{"kc_id": KCS[1], "weight": 0.5}, {"kc_id": KCS[2], "weight": 0.5}]) == [
        {"kc_id": KCS[2], "weight": 1.0}
    ]
    cycle = [{**SPLIT, "to": [{"kc_id": NEW[0], "weight": 1.0}]},
             {"from_kc_id": NEW[0], "from_version": "2.0.0", "to_version": "3.0.0",
              "to": [{"kc_id": OLD, "weight": 1.0}]}]  # fmt: skip
    with pytest.raises(MigrationError):
        KcMigrations.from_rows(cycle)
    with pytest.raises(MigrationError):
        KcMigrations.from_rows([{**SPLIT, "to": [{"kc_id": NEW[0], "weight": 0.6}]}])


def test_cur10_per_kc_events_count_for_each_part() -> None:
    """A mastery check on the old KC counts for each new KC; an unrelated event is read unchanged."""
    migrations = KcMigrations.from_rows([SPLIT])
    learner = random_log(3, sessions=1)
    event = next(iter(learner.log.merged()))
    check = replace(event, type="mastery_check", payload={"kc_id": OLD, "check_state": "passed", "item_index": 3})
    assert [e.payload["kc_id"] for e in migrations.event(check)] == list(NEW)
    assert migrations.event(event) == [event]
