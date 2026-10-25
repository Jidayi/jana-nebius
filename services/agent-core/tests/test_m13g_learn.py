"""M13.g: the subject map and the lesson player over the local API (UXS-22, UXS-23; LRN-09, LRN-34, CUR-03, CUR-11,
LRN-17 subset, ASM-02, VSL-36).

Against the real core with packs built from the repository's curriculum sources (our own wording, CUR-02) and signed
with the development key. Replies are validated against the command contract (D78, `m13g_contract`). A full
lesson plays with no model and no network; the map carries each KC's state from the mastery projection; check items
never carry their keys; quick checks are marked by the deterministic marker; the position is kept per lesson version
and per profile. Adversarial cases: foreign and malformed ids, parts that are not the item's, answers of the wrong
kind, positions past the lesson's end or for another version, and no profile token. Every learner is synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.store.pack_store import PackStore
from agent_core.store.packs import TABLES, write_pack
from agent_core.store.sqlite import transaction
from api_harness import cli, start_core, stop_core
from jana_tools import REPO_ROOT
from jana_tools.harness.egress import offline_run
from m13g_contract import endpoints, m13g_errors
from m20_fixtures import content_pack
from pack_builder.build import load_source
from test_m10a_profiles import Api, student

SETTINGS = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), api_command_burst_per_s=1000)
LESSON = "les.phy.o.motion.speed_and_acceleration"
SPEED = "kc.phy.o.motion.average_speed"
CHANGE = "kc.phy.o.motion.acceleration_from_change"
SOURCES: dict[str, dict[str, list[dict[str, Any]]]] = {}


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


def source(subject: str) -> dict[str, list[dict[str, Any]]]:
    if subject not in SOURCES:
        SOURCES[subject] = load_source(REPO_ROOT / "content" / "curriculum" / subject / "o").tables
    return SOURCES[subject]


def install(data_dir: Path, subject: str, *, damaged: bool = False) -> Path:
    """A development-signed pack of one subject's sources, installed through the pack store (the tutor reads
    installed packs only, SEC-13); `damaged` edits a table of the installed file afterwards, so the pack no longer
    verifies (CUR-08)."""
    tables = source(subject)
    # A pack without the search tables (D79), as packs built before them are: valid without an embedding model.
    written = {t: list(tables.get(t, [])) for t in TABLES if t not in ("search_fts", "search_vectors")}
    incoming = data_dir / "incoming" / f"pack.{subject}.o-0.1.0.pack"
    incoming.parent.mkdir(parents=True, exist_ok=True)
    signed = content_pack(incoming, f"pack.{subject}.o", "0.1.0", tables=written)
    store = PackStore(data_dir / "packs", Environment.DEV)
    store.install(incoming)
    path = store.active_path(f"pack.{subject}.o")
    if damaged:
        path.unlink()
        write_pack(path, signed, {**written, "kcs": written["kcs"][1:]})
    return path


class Client:
    def __init__(self, r: Any, token: str | None = None) -> None:
        self.r, self.api, self.token = r, Api(r), token

    async def get(self, path: str) -> Any:
        return await self.api.call("GET", path, profile=self.token)

    async def send(self, method: str, path: str, body: Any) -> Any:
        return await self.api.call(method, path, body, profile=self.token)

    async def ok(self, method: str, path: str, body: Any = None, definition: str | None = None) -> dict[str, Any]:
        reply = await (self.get(path) if method == "GET" else self.send(method, path, body))
        assert reply.status_code == 200, reply.text
        found: dict[str, Any] = reply.json()
        if definition is not None:
            assert m13g_errors(definition, found) == [], m13g_errors(definition, found)
        return found


def key_answer(item: dict[str, Any]) -> dict[str, Any]:
    """The item's own key as a student answer (the test reads the source record; the reply never carries it)."""
    parts = []
    for part in item["parts"]:
        key = part["answer"]
        if key["kind"] == "numeric":
            parts.append({"part_id": part["id"], "kind": "numeric", "value": key["value"], "unit": key["unit"]})
        elif key["kind"] == "mcq":
            right = next(o["id"] for o in key["options"] if o["correct"])
            parts.append({"part_id": part["id"], "kind": "mcq", "option_id": right})
    return {"parts": parts}


def item_record(subject: str, item_id: str) -> dict[str, Any]:
    return next(i for i in source(subject)["items"] if i["id"] == item_id)


def mastery(r: Any, kc_id: str, status: str, fading: int | None = None) -> None:
    """Put a KC in a TABLE LRN-09a state in the open learner database's mastery projection."""
    conn = r.runtime.learner.conn
    with transaction(conn):
        conn.execute("INSERT OR REPLACE INTO kc_mastery (kc_id, status, p_mastery, fading_stage, last_event_seq)"
                     " VALUES (?, ?, 0.5, ?, 0)", (kc_id, status, fading))  # fmt: skip


def check_ids(items: list[dict[str, Any]]) -> list[str]:
    return [i["item_id"] for i in items]


# --- UXS-23: a full lesson with no model and no network ---------------------------------------------------------------


def uxs23_lesson_offline_no_model(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        r = await start_core(tmp_path, settings=SETTINGS)
        r.runtime.providers.clear()  # the content-only class: no tutor model at all
        r.core.readiness = "degraded"
        try:
            c = Client(r)
            with offline_run() as egress:
                lesson = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
                assert [b["type"] for b in lesson["blocks"]] == ["prior_knowledge", "idea", "worked_example",
                                                                 "guided_step", "quick_check", "common_mistakes",
                                                                 "exit_check", "summary"]  # fmt: skip
                assert lesson["position"] is None
                for index, block in enumerate(lesson["blocks"]):
                    for item in block.get("items", []):
                        body = {"client_attempt_id": cli(), "item_id": item["item_id"],
                                "answer": key_answer(item_record("phy", item["item_id"])), "time_ms": 9000}  # fmt: skip
                        marked = await c.ok("POST", f"/v1/lessons/{LESSON}/checks", body, "LessonCheckResult")
                        assert marked["verdict"] == "correct", marked
                        assert all(p["check_ids"] for p in marked["parts"]), "every numeric verdict names its checks"
                    saved = await c.ok(
                        "PUT",
                        f"/v1/lessons/{LESSON}/position",
                        {"block_index": index, "lesson_version": lesson["version"]},
                        "LessonPosition",
                    )
                    assert saved["block_index"] == index
                again = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
                assert again["position"]["block_index"] == len(lesson["blocks"]) - 1
            assert egress.attempts == []
        finally:
            await stop_core(r)

    run(scenario())


def wrong_answer(item: dict[str, Any]) -> dict[str, Any]:
    """An answer the key marks wrong: a wrong option, or a value no key here has."""
    parts = []
    for part in item["parts"]:
        key = part["answer"]
        if key["kind"] == "numeric":
            parts.append({"part_id": part["id"], "kind": "numeric", "value": "1.5", "unit": key["unit"]})
        elif key["kind"] == "mcq":
            wrong = next(o["id"] for o in key["options"] if not o["correct"])
            parts.append({"part_id": part["id"], "kind": "mcq", "option_id": wrong})
    return {"parts": parts}


STEP_LESSON = "les.mth.o.number.percentage_change"


def test_teaching_entry_keeps_step_positions_and_assessment_records(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "mth")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            ordinary = await c.ok("GET", f"/v1/lessons/{STEP_LESSON}", definition="LessonView")
            await c.ok("PUT", f"/v1/lessons/{STEP_LESSON}/position", {
                "block_index": 2, "lesson_version": ordinary["version"],
            })
            conn = r.runtime.learner.conn
            before = (list(conn.execute("SELECT * FROM attempts")), list(conn.execute("SELECT * FROM kc_mastery")))
            with offline_run() as egress:
                teaching = await c.ok("GET", f"/v1/lessons/{STEP_LESSON}?teaching=true", definition="LessonView")
            assert egress.attempts == []
            assert teaching["position"]["block_index"] == 2
            assert teaching["blocks"][:len(ordinary["blocks"])] == ordinary["blocks"]
            assert teaching["blocks"][-1]["type"] == "worked_example"
            assert teaching["blocks"][-1]["worked_example"]["faded_steps"] == []
            after = (list(conn.execute("SELECT * FROM attempts")), list(conn.execute("SELECT * FROM kc_mastery")))
            assert after == before
            again = await c.ok("GET", f"/v1/lessons/{STEP_LESSON}", definition="LessonView")
            assert again["blocks"] == ordinary["blocks"]
        finally:
            await stop_core(r)
    run(scenario())


def uxs23_step_retry_then_shown(tmp_path: Path) -> None:
    """A step-shape lesson (TABLE CUR-11b, D110) with no model and no network: a first miss gets feedback and no why
    or working, the second miss shows the step with its checked working, a correct answer carries the why; nothing
    records an attempt or moves mastery."""

    async def scenario() -> None:
        install(tmp_path, "mth")
        r = await start_core(tmp_path, settings=SETTINGS)
        r.runtime.providers.clear()  # the content-only class
        r.core.readiness = "degraded"
        conn = r.runtime.learner.conn
        try:
            c = Client(r)
            with offline_run() as egress:
                lesson = await c.ok("GET", f"/v1/lessons/{STEP_LESSON}", definition="LessonView")
                kinds = [b["type"] for b in lesson["blocks"]]
                assert kinds == ["step"] * 5 + ["check"]
                assert lesson["blocks"][0]["action"] == "try_first"
                assert [len(b["items"]) for b in lesson["blocks"]] == [1] * 5 + [3]
                assert "why" not in json.dumps(lesson["blocks"]), "a step's why reaches the student only after it"
                before = (conn.execute("SELECT count(*) FROM attempts").fetchone()[0],
                          conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0])  # fmt: skip

                async def answer(item_id: str, given: dict[str, Any], attempt: int | None) -> dict[str, Any]:
                    body = {"client_attempt_id": cli(), "item_id": item_id, "answer": given, "time_ms": 4000,
                            **({"attempt": attempt} if attempt is not None else {})}  # fmt: skip
                    return await c.ok("POST", f"/v1/lessons/{STEP_LESSON}/checks", body, "LessonCheckResult")

                first = lesson["blocks"][0]["items"][0]["item_id"]
                record = item_record("mth", first)
                missed = await answer(first, wrong_answer(record), None)
                assert missed["verdict"] == "incorrect" and missed["explanation"] is None
                again = await answer(first, wrong_answer(record), 2)
                assert again["verdict"] == "incorrect"
                shown = again["explanation"]
                assert shown["shown"] is True and shown["why"] and shown["names"]
                assert [s["latex"] for s in shown["working"]] == [s["latex"] for s in record["solution"]["steps"]]
                right = await answer(first, key_answer(record), 3)
                assert right["verdict"] == "correct" and right["explanation"]["shown"] is False
                assert right["explanation"]["why"] == shown["why"]
                for block in lesson["blocks"]:
                    for item in block["items"]:
                        marked = await answer(item["item_id"], key_answer(item_record("mth", item["item_id"])), 1)
                        assert marked["verdict"] == "correct", marked
                        explained = marked["explanation"]
                        assert explained["working"] and (explained["why"] is None) == (block["type"] == "check")
                after = (conn.execute("SELECT count(*) FROM attempts").fetchone()[0],
                         conn.execute("SELECT count(*) FROM kc_mastery").fetchone()[0])  # fmt: skip
                assert after == before, "lesson answers record no attempt, so a shown step never counts"
                refused = await c.send("POST", f"/v1/lessons/{STEP_LESSON}/checks",
                                       {"client_attempt_id": cli(), "item_id": first, "answer": key_answer(record),
                                        "time_ms": 1, "attempt": 0})  # fmt: skip
                assert refused.status_code == 422 and refused.json()["error"]["code"] == "validation_failed"
            assert egress.attempts == []
        finally:
            await stop_core(r)

    run(scenario())


# --- UXS-22: the subject map ------------------------------------------------------------------------------------------


def test_subject_map_sections_tiles_and_states(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        install(tmp_path, "acc")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            fresh = await c.ok("GET", "/v1/curriculum/cur.phy.o/map", definition="SubjectMap")
            assert fresh["status"] == "ready" and fresh["subject"] == "physics" and fresh["level"] == "O"
            assert fresh["pack"] == {"pack_id": "pack.phy.o", "version": "0.1.0"}
            # The full Physics map: sections in map order, the motion tile inside motion, forces and energy.
            assert len(fresh["sections"]) > 1
            (section,) = [s for s in fresh["sections"] if s["node_id"] == "cur.phy.o.motion_forces_and_energy"]
            (tile,) = [t for t in section["topics"] if t["node_id"] == "cur.phy.o.motion_forces_and_energy.motion"]
            assert {k["state"] for k in tile["kcs"]} == {"not_started"}
            assert [k["code"] for k in tile["kcs"]] == sorted(k["code"] for k in tile["kcs"])
            assert [les["lesson_id"] for les in tile["lessons"]] == [LESSON]
            assert set(tile["lessons"][0]["kc_ids"]) == {SPEED, CHANGE}

            mastery(r, SPEED, "mastered")
            mastery(r, CHANGE, "moved_on")
            moved = await c.ok("GET", "/v1/curriculum/cur.phy.o/map", definition="SubjectMap")
            motion = next(t for sec in moved["sections"] for t in sec["topics"] if t["node_id"] == tile["node_id"])
            kcs = {k["kc_id"]: (k["state"], k["band"]) for k in motion["kcs"]}
            assert kcs[SPEED] == ("mastered", "secure") and kcs[CHANGE] == ("moved_on", "learning")
            text = json.dumps(moved)
            assert "p_mastery" not in text and "0.5" not in text, "no probability reaches the map"

            # Accounting's KCs hang from its topics: each section is its own tile, in map order.
            accounts = await c.ok("GET", "/v1/curriculum/cur.acc.o/map", definition="SubjectMap")
            codes = [s["code"] for s in accounts["sections"]]
            assert codes == sorted(codes) and codes[0] == "ACC-O-01"
            for section in accounts["sections"]:
                assert [t["node_id"] for t in section["topics"]] == [section["node_id"]]
        finally:
            await stop_core(r)

    run(scenario())


def test_subject_map_without_a_working_pack(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "chm", damaged=True)
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            missing = await c.ok("GET", "/v1/curriculum/cur.mth.o/map", definition="SubjectMap")
            assert missing["status"] == "not_installed" and missing["sections"] == [] and missing["pack"] is None
            damaged = await c.ok("GET", "/v1/curriculum/cur.chm.o/map", definition="SubjectMap")
            assert damaged["status"] == "unverified" and damaged["sections"] == []
            for bad in ("cur.phy", "cur.xyz.o", "cur.phy.o.motion_forces_and_energy", "..%2F..%2Fetc"):
                reply = await c.get(f"/v1/curriculum/{bad}/map")
                assert reply.status_code == 404, (bad, reply.text)
        finally:
            await stop_core(r)

    run(scenario())


# --- UXS-23: the lesson view ------------------------------------------------------------------------------------------


def test_lesson_view_resolves_blocks_and_never_carries_keys(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        install(tmp_path, "acc")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            lesson = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
            blocks = {b["type"]: b for b in lesson["blocks"]}
            example = blocks["worked_example"]["worked_example"]
            assert example["worked_example_id"] == "wex.phy.o.motion.0001" and example["faded_steps"] == []
            assert all(s["reason"] for s in example["steps"]) and example["final_answer"]["check_id"]
            assert check_ids(blocks["quick_check"]["items"]) == ["itm.phy.o.motion.0022", "itm.phy.o.motion.0002"]
            assert {m["misconception_id"] for m in blocks["common_mistakes"]["mistakes"]} == {
                "mc.phy.o.time_over_distance",
                "mc.phy.o.final_velocity_over_time",
            }
            assert all(m["name"] and m["fix"] for m in blocks["common_mistakes"]["mistakes"])
            # The student view of an item has no key: no answer value, no correct flag, no solution, no hints.
            for block in lesson["blocks"]:
                for item in block.get("items", []):
                    record = item_record("phy", item["item_id"])
                    shown = json.dumps(item)
                    assert '"correct"' not in shown and "solution" not in shown and "hints" not in shown
                    assert f'"{record["parts"][0]["answer"]["value"]}"' not in shown
                    assert m13g_errors("PracticeItem", item) == []

            # LRN-17 subset: a KC at fading stage 1 blanks the first step of the example's fading order.
            mastery(r, SPEED, "learning", fading=1)
            mastery(r, CHANGE, "learning", fading=2)
            faded = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
            wex = next(b for b in faded["blocks"] if b["type"] == "worked_example")["worked_example"]
            record = next(w for w in source("phy")["worked_examples"] if w["id"] == wex["worked_example_id"])
            assert wex["faded_steps"] == record["fading_order"][:1]

            # A multiple-choice check: the options without their correct flags, marked against the key.
            acc = next(les for les in source("acc")["lessons"]
                       if any(item_record("acc", i)["type"].startswith("mcq") for b in les["blocks"]
                              for i in b.get("item_ids", [])))  # fmt: skip
            shown = await c.ok("GET", f"/v1/lessons/{acc['id']}", definition="LessonView")
            mcq = next(i for b in shown["blocks"] for i in b.get("items", []) if i["kind"].startswith("mcq"))
            assert all(set(o) == {"id", "label"} for o in mcq["parts"][0]["input"]["options"])
            record = item_record("acc", mcq["item_id"])
            wrong = next(o for o in record["parts"][0]["answer"]["options"] if not o["correct"])
            chosen = {"part_id": record["parts"][0]["id"], "kind": "mcq", "option_id": wrong["id"]}
            body = {"client_attempt_id": cli(), "item_id": mcq["item_id"], "time_ms": 4000,
                    "answer": {"parts": [chosen]}}  # fmt: skip
            marked = await c.ok("POST", f"/v1/lessons/{acc['id']}/checks", body, "LessonCheckResult")
            (part,) = marked["parts"]
            assert marked["verdict"] == "incorrect" and part["marks_awarded"] == 0
            if wrong.get("misconception_id"):
                assert part["category"] == "misconception"
                assert part["misconception"]["misconception_id"] == wrong["misconception_id"]

            for bad in ("les.phy.o.motion.nope", "les.phy", "itm.phy.o.motion.0001"):
                assert (await c.get(f"/v1/lessons/{bad}")).status_code == 404
        finally:
            await stop_core(r)

    run(scenario())


def test_quick_check_refuses_answers_that_do_not_fit(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            path = f"/v1/lessons/{LESSON}/checks"

            def body(item_id: str, parts: list[dict[str, Any]]) -> dict[str, Any]:
                return {"client_attempt_id": cli(), "item_id": item_id, "answer": {"parts": parts}, "time_ms": 1}

            numeric = {"part_id": "a", "kind": "numeric", "value": "1.2", "unit": None}
            not_in_lesson = await c.send("POST", path, body("itm.phy.o.motion.0001", [numeric]))
            assert not_in_lesson.status_code == 404
            other_part = await c.send("POST", path, body("itm.phy.o.motion.0022", [{**numeric, "part_id": "z"}]))
            assert other_part.status_code == 422, other_part.text
            twice = await c.send("POST", path, body("itm.phy.o.motion.0022", [numeric, numeric]))
            assert twice.status_code == 422
            choice = {"part_id": "a", "kind": "mcq", "option_id": "A"}
            wrong_kind = await c.send("POST", path, body("itm.phy.o.motion.0022", [choice]))
            assert wrong_kind.status_code == 422
            malformed = await c.send("POST", path, {"item_id": "itm.phy.o.motion.0022"})
            assert malformed.status_code == 422
            # No worker: a numeric answer with a unit cannot be converted, so it is not marked right by a guess.
            unit = await c.ok("POST", path, body("itm.phy.o.motion.0022", [{**numeric, "unit": "m/s"}]),
                              "LessonCheckResult")  # fmt: skip
            assert unit["verdict"] != "correct"
            bare = await c.ok("POST", path, body("itm.phy.o.motion.0022", [numeric]), "LessonCheckResult")
            assert bare["verdict"] == "partially_correct" and bare["parts"][0]["category"] == "units_missing"
        finally:
            await stop_core(r)

    run(scenario())


def test_lesson_position_bound_to_version_profile_and_table(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            api = Api(r)
            ama = await api.add(student("Ama"))
            kofi = await api.add(student("Kofi"))
            locked = Client(r)
            assert (await locked.get(f"/v1/lessons/{LESSON}")).json()["error"]["code"] == "profile_token_expired"
            assert (await locked.get("/v1/curriculum/cur.phy.o/map")).json()["error"]["code"] == "profile_token_expired"

            c = Client(r, (await api.unlock(ama)).json()["profile_token"])
            lesson = await c.ok("GET", f"/v1/lessons/{LESSON}", definition="LessonView")
            path = f"/v1/lessons/{LESSON}/position"
            for bad in ({"block_index": len(lesson["blocks"]), "lesson_version": lesson["version"]},
                        {"block_index": 1, "lesson_version": "9.9.9"}, {"block_index": -1, "lesson_version": "0.1.0"},
                        {"block_index": True, "lesson_version": "0.1.0"}, {"block_index": 1}):  # fmt: skip
                assert (await c.send("PUT", path, bad)).status_code == 422, bad
            await c.ok("PUT", path, {"block_index": 3, "lesson_version": lesson["version"]}, "LessonPosition")
            assert (await c.ok("GET", f"/v1/lessons/{LESSON}"))["position"]["block_index"] == 3

            # Another profile starts at the beginning: positions are the profile's own (DAT-14).
            other = Client(r, (await api.unlock(kofi)).json()["profile_token"])
            assert (await other.ok("GET", f"/v1/lessons/{LESSON}"))["position"] is None

            # The learner database has the table (D78), so the position is kept there and survives the core.
            conn = r.runtime.learner.conn
            await other.ok("PUT", path, {"block_index": 5, "lesson_version": lesson["version"]}, "LessonPosition")
            row = conn.execute("SELECT block_index, lesson_version FROM lesson_positions WHERE lesson_id = ?",
                               (LESSON,)).fetchone()  # fmt: skip
            assert tuple(row) == (5, lesson["version"])
            assert (await other.ok("GET", f"/v1/lessons/{LESSON}"))["position"]["block_index"] == 5
        finally:
            await stop_core(r)

    run(scenario())


def test_every_lesson_and_map_endpoint_is_served(tmp_path: Path) -> None:
    async def scenario() -> None:
        install(tmp_path, "phy")
        r = await start_core(tmp_path, settings=SETTINGS, worker=False)
        try:
            c = Client(r)
            filled = {"{subject_id}": "cur.phy.o", "{lesson_id}": LESSON}
            numeric = {"part_id": "a", "kind": "numeric", "value": "1.2", "unit": None}
            bodies = {"PUT": {"block_index": 0, "lesson_version": "0.1.0"},
                      "POST": {"client_attempt_id": cli(), "item_id": "itm.phy.o.motion.0022", "time_ms": 1,
                               "answer": {"parts": [numeric]}}}  # fmt: skip
            served = []
            for endpoint in endpoints():
                path = endpoint["path"]
                for slot, value in filled.items():
                    path = path.replace(slot, value)
                method = endpoint["method"]
                reply = await (c.get(path) if method == "GET" else c.send(method, path, bodies[method]))
                assert reply.status_code == 200, (method, path, reply.text)
                definition = endpoint["response"].removeprefix("#/$defs/")
                if definition == "LessonCheckResult":
                    assert m13g_errors(definition, reply.json()) == []
                served.append(f"{method} {endpoint['path']}")
            assert len(served) == 4
        finally:
            await stop_core(r)

    run(scenario())
