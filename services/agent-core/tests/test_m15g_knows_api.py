"""M15 G90: the "What your tutor knows" page over the local API (LRN-36, MEM-09, MEM-14, LRN-37, UXS-28, PRV-10).

The learner view, answering a review item pinned to the versions shown, "This isn't right" on a note and on a
misconception, and a preference edit, against the real core and its learner databases. Replies are validated against
the proposed contract additions (`g90_contract`). Adversarial cases: another profile's ids, malformed and foreign ids,
stale versions, deleted notes, no token and a stale adult token. Every learner and note is synthetic."""

from __future__ import annotations

import contextlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.learner.service import Learner
from agent_core.store.ids import new_ulid
from api_harness import start_core, stop_core
from g90_contract import endpoints, g90_errors
from learner_harness import START_MS, Clock
from memory_harness import all_text, run
from test_m10a_profiles import Api, student
from test_m15e_memory import SPEED, TOPIC, World, act

GRAVITY = "mc.phy.o.gravity_sign_flipped"
AVERAGING = "mc.phy.o.average_of_speeds"
FALL = "kc.phy.o.motion.free_fall"


def world_on(learner: Learner) -> World:
    """The memory tests' synthetic learner, writing real events into the core's open learner database."""
    clock = Clock()
    sid = new_ulid(clock.now)
    learner.conn.execute("INSERT INTO sessions (session_id, mode, subject, topic_id, started_at) VALUES (?,"
                         " 'practice', 'physics', ?, ?)", (sid, TOPIC, START_MS))  # fmt: skip
    return World(learner, clock, sid)


def floats(value: Any) -> Iterator[float]:
    if isinstance(value, float):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from floats(v)
    elif isinstance(value, list):
        for v in value:
            yield from floats(v)


class Page:
    """One student's page over the API, opened with their profile token (there is no adult token, D86)."""

    def __init__(self, r: Any, api: Api, profile: str, token: str | None) -> None:
        self.r, self.api, self.profile, self.token = r, api, profile, token

    @property
    def learner(self) -> Learner:
        learner: Learner = self.r.core.records.learner
        return learner

    async def view(self, *, profile: str | None = None, token: str | None = None, headers: dict | None = None) -> Any:
        return await self.api.call("GET", f"/v1/profiles/{profile or self.profile}/knows",
                                   profile=token, headers=headers)  # fmt: skip

    async def mine(self) -> dict[str, Any]:
        reply = await self.view(token=self.token)
        assert reply.status_code == 200, reply.text
        body: dict[str, Any] = reply.json()
        assert g90_errors("KnowsView", body) == [], g90_errors("KnowsView", body)
        return body

    async def send(self, method: str, path: str, body: Any = None, *, token: str | bool | None = True,
                   headers: dict | None = None, profile: str | None = None) -> Any:  # fmt: skip
        """A command on this page: with the student's own token (`token=True`), another token, or none."""
        held = self.token if token is True else token or None
        return await self.api.call(method, f"/v1/profiles/{profile or self.profile}{path}", body,
                                   profile=held if isinstance(held, str) else None, headers=headers)  # fmt: skip


async def opened(tmp_path: Path, names: tuple[str, ...] = ("Ama",)) -> tuple[Any, list[Page]]:
    """A core with these students; the first is unlocked (its learner database is the open one), the rest locked."""
    r = await start_core(tmp_path, settings=Settings(api_command_burst_per_s=1000), worker=False)
    api = Api(r)
    profiles = [await api.add(student(name)) for name in names]
    token = (await api.unlock(profiles[0])).json()["profile_token"]
    return r, [Page(r, api, p, token if i == 0 else None) for i, p in enumerate(profiles)]


@contextlib.contextmanager
def locked_world(r: Any, profile: str) -> Iterator[World]:
    """A closed profile's learner database, written through the runtime's short-lived desk."""
    with r.runtime.knows(profile) as desk:
        assert desk is not None and r.core.records_profile != profile
        yield world_on(desk.source.learner)


def contradiction(w: World, old: str = "Converts kilometres per hour to metres per second",
                  new: str = "Converts speeds by dividing by 36 instead of 3.6") -> tuple[str, str]:  # fmt: skip
    """An active note and a Reflector contradiction of it: (the note, the review item's pending note)."""
    kept = w.add(old)
    applied = w.reflect(act("contradiction", new, w.practise(SPEED), target=kept))
    assert applied.pending_review, applied
    return kept, applied.pending_review[0]


# --- the view ---------------------------------------------------------------------------------------------------------


def prv11_knows_page_complete(tmp_path: Path) -> None:
    async def scenario() -> None:
        r, (page,) = await opened(tmp_path)
        try:
            w = world_on(page.learner)
            w.practise(SPEED, hints=1)
            w.practise(FALL, "correct")
            w.mistake(GRAVITY, FALL, "probe")
            mine = w.add("Wants to practise vectors before the mock", role="student_request")
            kept, pending = contradiction(w)
            w.learner.record("correction", {"target": "preference", "target_id": "representation",
                                            "action": "override", "value": "diagram", "actor_role": "student"},
                             source="student")  # fmt: skip
            import re
            import time

            from agent_core.engine.knows import RECORD_CATEGORIES
            from agent_core.learner.planner import Block, Plan
            from jana_tools import REPO_ROOT

            r.runtime.planner()._generate(
                Plan("normal", (Block("main", (SPEED,), 10, "prerequisite"),), 0, ("physics",)), int(time.time() * 1000)
            )
            schema = (REPO_ROOT / "contracts/data/schema.sql").read_text()
            projections = set(re.findall(r"-- PROJECTION:.*?CREATE TABLE (\w+)", schema, re.S))
            assert set(RECORD_CATEGORIES) == projections, "new learner-model tables must be disclosed"
            expected = {
                kind: w.conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608 - fixed registry names
                for table, kind in RECORD_CATEGORIES.items()
            }
            assert all(expected.values()), expected
            body = await page.mine()
            assert {row["kind"]: row["count"] for row in body["records"]} == expected
            assert body["plan_reason"] == "prerequisite"
            latest = r.runtime.planner()._generate(
                Plan("normal", (Block("main", (SPEED,), 10, "mock_follow_up"),), 0, ("physics",)),
                int(time.time() * 1000),
            )
            assert (await page.mine())["plan_reason"] == "mock_follow_up"
            w.conn.execute("UPDATE study_plans SET status='done' WHERE plan_id=?", (latest,))
            assert (await page.mine())["plan_reason"] is None
            w.conn.execute("UPDATE study_plans SET status='proposed', day='2000-01-01'")
            assert (await page.mine())["plan_reason"] is None
            assert body["profile_id"] == page.profile and "viewer" not in body
            assert list(floats(body)) == [], "no probability (or any other decimal) reaches the page"
            assert body["about"] == {"level": "O", "subjects": ["physics"], "exam_date": None}
            bands = {k["kc_id"]: (k["state"], k["band"]) for k in body["kcs"]}
            assert bands[SPEED] == ("learning", "learning") and bands[FALL][1] == "learning"
            assert body["misconceptions"] == [{"misconception_id": GRAVITY, "name": GRAVITY, "status": "active"}]
            assert body["preferences"] == [{"key": "representation", "value": "diagram", "source": "override"}]
            notes = {n["note_id"]: n for n in body["notes"]}
            assert set(notes) == {f"mem_{mine}", f"mem_{kept}"}, "a pending note is a review item, not a note"
            assert notes[f"mem_{mine}"]["source"] == "student" and notes[f"mem_{kept}"]["source"] == "reflector"
            assert not any(n["flagged"] for n in notes.values())
            (review,) = body["reviews"]
            assert review["review_id"] == f"rvw_{pending}" and review["kind"] == "replace"
            assert review["pending"]["note_id"] == f"mem_{pending}" and review["pending"]["status"] == "pending_review"
            assert review["target"]["note_id"] == f"mem_{kept}"
            versions = (review["pending_version"], review["target_version"])
            assert versions == (w.note(pending).last_event_id, w.note(kept).last_event_id)
            assert body["memory_saving"] is True
            assert body["sharing"] == {"backup": False, "devices": False, "parent_view": False, "cloud_tutor": False}
        finally:
            await stop_core(r)

    run(scenario())


def test_proposed_endpoints_are_served_and_owned() -> None:
    """Every proposed endpoint names its definitions, needs the profile token, and owns a stage."""
    defs = {e["path"]: e for e in endpoints()}
    assert set(defs) == {
        "/v1/profiles/{profile_id}/knows",
        "/v1/profiles/{profile_id}/memory/reviews/{review_id}",
        "/v1/profiles/{profile_id}/memory/{note_id}/dispute",
        "/v1/profiles/{profile_id}/misconceptions/{misconception_id}/correction",
        "/v1/profiles/{profile_id}/preferences/{key}",
    }
    for entry in defs.values():
        assert entry["auth"] == ["launch", "profile"]
        assert entry["stage"] == "S2" and entry["response"] == "KnowsView"
    assert "review_changed" in defs["/v1/profiles/{profile_id}/memory/reviews/{review_id}"]["errors"]


# --- MEM-27 on the served page (called by `mem27_flagged_note_visible_not_prompted`) ---------------------------------


def served_flags(tmp_path: Path, fine: str, poisoned: tuple[str, ...]) -> None:
    """The served view marks every note that fails the render check and lists it, for the student and for the adult;
    a live turn's prompt carries the fine note and none of the flagged ones; "This isn't right" on a flagged note
    deletes it, erases its text and tells the open session."""
    from api_harness import STATEMENT
    from engine_harness import tutor
    from memory_harness import SAFE, core_with_reflector, requests_of, system_of
    from test_m15e_engine import _frames, _profile, _scripted, _seeded_note, _turn

    provider = _scripted([tutor(SAFE), tutor(SAFE)])

    async def scenario() -> None:
        r = await core_with_reflector(tmp_path, provider)
        try:
            api, profile = await _profile(r)
            kept = _seeded_note(r, fine)
            flagged = [_seeded_note(r, text) for text in poisoned]
            reply = await api.call("GET", f"/v1/profiles/{profile}/knows")
            body = reply.json()
            assert reply.status_code == 200 and g90_errors("KnowsView", body) == []
            marks = {n["note_id"]: n["flagged"] for n in body["notes"]}
            assert marks == {f"mem_{kept}": False, **{f"mem_{f}": True for f in flagged}}
            assert {n["text"] for n in body["notes"]} == {fine, *poisoned}, "listed with their text, to be deleted"
            as_adult = (await api.call("GET", f"/v1/profiles/{profile}/knows")).json()
            assert "viewer" not in as_adult and as_adult["notes"] == body["notes"]
            session = await r.session()
            await _turn(r, session, STATEMENT)
            prompt = system_of(requests_of(provider, "coach")[-1])
            assert fine in prompt and not [t for t in poisoned if t in prompt], "flagged notes never reach a prompt"
            target = flagged[0]
            gone = await api.call("POST", f"/v1/profiles/{profile}/memory/mem_{target}/dispute")
            assert gone.status_code == 200, gone.text
            assert f"mem_{target}" not in {n["note_id"] for n in gone.json()["notes"]}
            assert [f["event"]["note_id"] for f in _frames(r, session, "memory.forgotten")] == [f"mem_{target}"]
            assert poisoned[0] not in all_text(r.runtime.learner.conn), "its text is erased (LRN-37)"
            events = r.runtime.learner.conn.execute(
                "SELECT type, json_extract(payload, '$.action') FROM events WHERE json_extract(payload, '$.note_id')"
                " = ? OR json_extract(payload, '$.target_id') = ? ORDER BY seq",
                (target, target),
            ).fetchall()
            assert [e for e in events if e[0] != "note_written"] == [("correction", "dispute"), ("note_deleted", None)]
        finally:
            await stop_core(r)

    run(scenario())


# --- MEM-09 over the API: answers pinned to the versions shown -------------------------------------------------------


def test_review_answer_pinned_to_versions(tmp_path: Path) -> None:
    async def scenario() -> None:
        r, (page,) = await opened(tmp_path)
        try:
            w = world_on(page.learner)
            kept, pending = contradiction(w)
            shown = (await page.mine())["reviews"][0]
            path = f"/memory/reviews/{shown['review_id']}"
            answer = {"accept": True, "pending_version": shown["pending_version"],
                      "target_version": shown["target_version"]}  # fmt: skip
            events = page.learner.conn.execute("SELECT count(*) FROM events").fetchone()

            # A version that was never shown: refused, nothing written, and the item comes back as it is.
            stale = await page.send("POST", path, {**answer, "pending_version": new_ulid()})
            assert stale.status_code == 409 and stale.json()["error"]["code"] == "review_changed"
            assert stale.json()["error"]["details"]["review"] == shown
            assert page.learner.conn.execute("SELECT count(*) FROM events").fetchone() == events

            # The note it would replace moves on (the Reflector updates its own note): the old answer is refused and
            # the item is shown again with the current text.
            w.reflect(act("update", "Converts km/h to m/s by dividing by 3.6", w.practise(SPEED), target=kept))
            moved = await page.send("POST", path, answer)
            assert moved.status_code == 409, moved.text
            current = moved.json()["error"]["details"]["review"]
            assert current["target"]["text"] == "Converts km/h to m/s by dividing by 3.6"
            assert current["target_version"] != shown["target_version"]
            assert g90_errors("ReviewItem", current) == []
            assert w.note(kept).status == "active" and w.note(pending).status == "pending_review"

            # Malformed bodies are 422 and write nothing.
            for bad in ({"accept": "yes", **{k: v for k, v in answer.items() if k != "accept"}},
                        {**answer, "target_version": "not-a-version"}, {**answer, "extra": 1}, []):  # fmt: skip
                assert (await page.send("POST", path, bad)).status_code == 422, bad

            # The current versions: accepted. The pending note is active, the old one gone and its text erased.
            fresh = {"accept": True, "pending_version": current["pending_version"],
                     "target_version": current["target_version"]}  # fmt: skip
            key = new_ulid()
            done = await page.api.r.client.post(f"{r.base}/v1/profiles/{page.profile}{path}", json=fresh,
                                                headers={**r.headers(True), "idempotency-key": f"cli_{key}",
                                                         "x-profile-token": page.token})  # fmt: skip
            assert done.status_code == 200, done.text
            assert g90_errors("KnowsView", done.json()) == []
            assert done.json()["reviews"] == []
            assert [n["note_id"] for n in done.json()["notes"]] == [f"mem_{pending}"]
            assert "dividing by 3.6" not in all_text(page.learner.conn), "the replaced note's text is erased"
            deleted = page.learner.conn.execute("SELECT source FROM events WHERE type = 'note_deleted'").fetchall()
            assert deleted == [("student",)]
            # The same request again returns the stored reply (API-31); a new one finds no item.
            again = await page.api.r.client.post(f"{r.base}/v1/profiles/{page.profile}{path}", json=fresh,
                                                 headers={**r.headers(True), "idempotency-key": f"cli_{key}",
                                                          "x-profile-token": page.token})  # fmt: skip
            assert again.status_code == 200 and again.json() == done.json()
            assert (await page.send("POST", path, fresh)).status_code == 404

            # Rejecting a contradiction deletes the pending note and leaves the old one.
            other, pending2 = contradiction(w, "Draws the forces before writing any equation",
                                            "Writes the equations before drawing the forces")  # fmt: skip
            item = next(i for i in (await page.mine())["reviews"] if i["review_id"] == f"rvw_{pending2}")
            no = await page.send("POST", f"/memory/reviews/{item['review_id']}", {
                "accept": False, "pending_version": item["pending_version"],
                "target_version": item["target_version"]})  # fmt: skip
            assert no.status_code == 200 and f"mem_{other}" in {n["note_id"] for n in no.json()["notes"]}
            assert "before drawing the forces" not in all_text(page.learner.conn), "the rejected text is erased"
        finally:
            await stop_core(r)

    run(scenario())


# --- isolation: another profile, foreign and malformed ids ------------------------------------------------------------


def test_knows_profile_isolation(tmp_path: Path) -> None:
    async def scenario() -> None:
        r, (ama, kofi) = await opened(tmp_path, ("Ama", "Kofi"))
        try:
            w = world_on(ama.learner)
            kept, pending = contradiction(w)
            w.mistake(GRAVITY, FALL, "probe")
            shown = (await ama.mine())["reviews"][0]
            answer = {"accept": True, "pending_version": shown["pending_version"],
                      "target_version": shown["target_version"]}  # fmt: skip
            cases = (
                ("POST", f"/memory/reviews/{shown['review_id']}", answer),
                ("POST", f"/memory/mem_{kept}/dispute", None),
                ("POST", f"/misconceptions/{GRAVITY}/correction", {"action": "dispute"}),
                ("PATCH", "/preferences/pace", {"value": "short"}),
            )

            def ama_state() -> Any:
                with r.runtime.directory.open_learner(ama.profile) as conn:
                    return all_text(conn), conn.execute("SELECT count(*) FROM events").fetchone()

            before = ama_state()
            # No token at all: 404 everywhere.
            assert (await ama.view(token=None)).status_code == 401
            for method, path, body in cases:
                assert (await ama.send(method, path, body, token=None)).status_code == 401, path
            # Kofi unlocks (Ama is locked): his token on Ama's page is 404 everywhere, as if it did not exist (API-04).
            kofi.token = (await kofi.api.unlock(kofi.profile)).json()["profile_token"]
            assert r.core.records_profile == kofi.profile
            assert (await ama.view(token=kofi.token)).status_code == 404
            for method, path, body in cases:
                reply = await ama.send(method, path, body, token=kofi.token)
                assert reply.status_code == 404 and reply.json()["error"]["code"] == "not_found", (path, reply.text)
                # Ama's ids on Kofi's own page find nothing either.
                mine = await kofi.send(method, path, body)
                assert mine.status_code == 404 or path == "/preferences/pace", (path, mine.text)
            assert ama_state() == before, "nothing was written to Ama's database"
            assert (await kofi.mine())["reviews"] == [] and (await kofi.mine())["notes"] == []
            # Ama unlocks again: malformed and foreign-prefixed ids find nothing, and write nothing.
            ama.token = (await ama.api.unlock(ama.profile)).json()["profile_token"]
            for path in (f"/memory/{kept}/dispute", f"/memory/ses_{kept}/dispute", "/memory/mem_%27%20OR%201/dispute",
                         f"/memory/mem_{kept.lower()}/dispute", f"/memory/mem_{kept}X/dispute"):  # fmt: skip
                assert (await ama.send("POST", path)).status_code == 404, path
            assert (await ama.send("POST", f"/memory/reviews/mem_{pending}", answer)).status_code == 404
            assert (await ama.send("POST", f"/memory/reviews/rvw_{new_ulid()}", answer)).status_code == 404
            assert ama_state() == before, "nothing was written"
            gone = await ama.send("POST", f"/memory/mem_{kept}/dispute")
            assert gone.status_code == 200
            assert (await ama.send("POST", f"/memory/mem_{kept}/dispute")).status_code == 404, "already deleted"
            # A pending note is answered through its review item, never disputed directly.
            assert (await ama.send("POST", f"/memory/mem_{pending}/dispute")).status_code == 404
        finally:
            await stop_core(r)

    run(scenario())


# --- MEM-14, PRV-10: another profile's page (no adult token, D86) ----------------------------------------------------


def test_a_closed_profiles_page_opens_only_with_its_own_token(tmp_path: Path) -> None:
    async def scenario() -> None:
        r, (ama, kofi) = await opened(tmp_path, ("Ama", "Kofi"))
        try:
            # Kofi's profile is closed (Ama's database is the open one); an adult token header reaches nothing.
            assert r.core.records_profile == ama.profile
            path = r.runtime.directory.learner_path(kofi.profile)
            with locked_world(r, kofi.profile) as w:
                note = w.add("Checks units qzvadult before the final answer")
                w.mistake(AVERAGING, SPEED)
                w.mistake(AVERAGING, SPEED)
            seen = await kofi.view(headers={"x-adult-token": "obsolete"})
            assert seen.status_code == 401 and "qzvadult" not in seen.text
            assert (await kofi.view(token=ama.token)).status_code == 404
            kofi.token = (await kofi.api.unlock(kofi.profile)).json()["profile_token"]
            seen = await kofi.view(token=kofi.token)
            assert seen.status_code == 200, seen.text
            body = seen.json()
            assert g90_errors("KnowsView", body) == [] and "viewer" not in body
            assert [n["note_id"] for n in body["notes"]] == [f"mem_{note}"]
            assert [m["misconception_id"] for m in body["misconceptions"]] == [AVERAGING]
            # Corrections on his page, with his own token, are recorded as the student's.
            disputed = await kofi.send("POST", f"/misconceptions/{AVERAGING}/correction", {"action": "dispute"},
                                       token=kofi.token, headers={"x-adult-token": "obsolete"})  # fmt: skip
            assert disputed.status_code == 200 and disputed.json()["misconceptions"] == []
            removed = await kofi.send("POST", f"/memory/mem_{note}/dispute", token=kofi.token)
            assert removed.status_code == 200 and removed.json()["notes"] == []
            assert r.core.records_profile == kofi.profile
            with r.runtime.directory.open_learner(kofi.profile) as conn:
                rows = conn.execute("SELECT type, source, json_extract(payload, '$.actor_role') FROM events WHERE"
                                    " type IN ('correction', 'note_deleted') ORDER BY seq").fetchall()  # fmt: skip
                assert rows == [("correction", "student", "student")] * 2 + [("note_deleted", "student", "student")]
            assert b"qzvadult" not in path.read_bytes(), "the note's text is erased from the locked profile's file"
            # An adult token header beside the student's own token changes nothing.
            ama.token = (await ama.api.unlock(ama.profile)).json()["profile_token"]
            both = await ama.send("PATCH", "/preferences/pace", {"value": "short"}, headers={"x-adult-token": "x"})
            assert both.status_code == 200 and "viewer" not in both.json()
            # Without the profile token nothing is reached.
            assert (await kofi.view(headers={"x-adult-token": "adult-not-a-token"})).status_code == 401
            assert (await kofi.send("POST", f"/misconceptions/{AVERAGING}/correction", {"action": "undispute"},
                                    token=None, headers={"x-adult-token": "nope"})).status_code == 401  # fmt: skip
            # A profile id that is no profile on this device.
            assert (await ama.view(profile=f"prf_{new_ulid()}", token=ama.token)).status_code == 404
        finally:
            await stop_core(r)

    run(scenario())


# --- LRN-37 over the API: misconceptions and preferences --------------------------------------------------------------


def test_misconception_and_preference_corrections(tmp_path: Path) -> None:
    async def scenario() -> None:
        r, (page,) = await opened(tmp_path)
        try:
            w = world_on(page.learner)
            w.mistake(AVERAGING, SPEED)
            w.mistake(AVERAGING, SPEED)
            path = f"/misconceptions/{AVERAGING}/correction"
            off = await page.send("POST", path, {"action": "dispute"})
            assert off.status_code == 200 and off.json()["misconceptions"] == []
            assert (await page.send("POST", path, {"action": "dispute"})).status_code == 404, "already disputed"
            back = await page.send("POST", path, {"action": "undispute"})
            assert [m["status"] for m in back.json()["misconceptions"]] == ["active"]
            for bad in ({"action": "delete"}, {}, {"action": "dispute", "x": 1}):
                assert (await page.send("POST", path, bad)).status_code == 422, bad
            assert (await page.send("POST", "/misconceptions/mc.phy.o.unknown/correction",
                                    {"action": "dispute"})).status_code == 404  # fmt: skip
            # Preferences: an override, a refused value, an unknown key, and the override cleared.
            set_ = await page.send("PATCH", "/preferences/unprompted_help", {"value": False})
            assert set_.status_code == 200, set_.text
            assert set_.json()["preferences"] == [{"key": "unprompted_help", "value": False, "source": "override"}]
            for key, value in (("pace", "slow"), ("unprompted_help", "no"), ("representation", True)):
                refused = await page.send("PATCH", f"/preferences/{key}", {"value": value})
                assert refused.status_code == 422, (key, value)
            assert (await page.send("PATCH", "/preferences/bedtime", {"value": "late"})).status_code == 404
            cleared = await page.send("PATCH", "/preferences/unprompted_help", {"value": None})
            assert cleared.json()["preferences"] == []
            rows = page.learner.conn.execute("SELECT payload FROM events WHERE type = 'correction' ORDER BY seq")
            actions = [(json.loads(p)["target"], json.loads(p)["action"]) for (p,) in rows]
            assert actions == [("misconception", "dispute"), ("misconception", "undispute"),
                               ("preference", "override"), ("preference", "clear_override")]  # fmt: skip
        finally:
            await stop_core(r)

    run(scenario())
