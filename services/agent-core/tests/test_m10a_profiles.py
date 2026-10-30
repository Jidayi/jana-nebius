"""M10.a: profiles, family settings and student preferences over the local API (API-04, API-28, DAT-14, DAT-15,
SEC-19, TCH-13, D86, D87). Synthetic profiles; no real student data."""

import asyncio
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from agent_core.store.settings import KEYS
from api_harness import STATEMENT, ask, cli, start_core, stop_core

LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


def student(name: str, age_band: str = "13_15") -> dict:
    return {"display_name": name, "avatar": "disc-teal", "level": "O", "subjects": ["physics"], "age_band": age_band}


class Api:
    """A thin client: the launch token always, plus a profile token when given. There is no other token (D86)."""

    def __init__(self, r) -> None:
        self.r = r

    async def call(self, method: str, path: str, body=None, profile: str | None = None, headers: dict | None = None):
        sent = self.r.headers(mutating=method != "GET")
        if method != "GET":
            sent["idempotency-key"] = cli()
        if profile:
            sent["x-profile-token"] = profile
        sent.update(headers or {})
        return await self.r.client.request(method, f"{self.r.base}{path}", headers=sent,
                                           content=None if body is None else json.dumps(body))  # fmt: skip

    async def add(self, body: dict) -> str:
        """Add a student (launch token only, D86)."""
        reply = await self.call("POST", "/v1/profiles", body)
        assert reply.status_code == 200, reply.text
        return reply.json()["profile_id"]

    async def unlock(self, profile_id: str):
        """A tap in the picker (UXS-09): no PIN."""
        return await self.call("POST", f"/v1/profiles/{profile_id}/open", {}, headers={"x-profile-open-intent": "user"})

    async def token(self, profile_id: str) -> str:
        reply = await self.unlock(profile_id)
        assert reply.status_code == 200, reply.text
        return str(reply.json()["profile_token"])


def code(reply) -> str:
    return reply.json()["error"]["code"]


def with_api(tmp_path: Path, scenario):
    async def go():
        r = await start_core(tmp_path, worker=False)
        try:
            return await scenario(Api(r), r)
        finally:
            await stop_core(r)

    return run(go())


# --- API-04 ----------------------------------------------------------------------------------------------------------


def test_profile_recovery_never_evicts_an_active_window(tmp_path: Path):
    async def scenario(api: Api, r):
        a, b = await api.add(student("Older")), await api.add(student("Newer"))
        old = await api.token(a)
        current = await api.token(b)
        # Background recovery carries no picker intent and cannot replace either another profile or another
        # window on the same profile. Neither failed attempt invalidates the current token.
        for target in (a, b):
            refused = await api.call("POST", f"/v1/profiles/{target}/open", {})
            assert refused.status_code == 401
            assert code(refused) == "profile_token_expired"
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=current)).status_code == 200
        assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=old)).status_code == 401
        # Explicit switching still works, and recovery is available once no grant remains (idle lock/restart).
        replacement = await api.token(a)
        assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=replacement)).status_code == 200
        r.runtime.directory.tokens.revoke()
        assert (await api.call("POST", f"/v1/profiles/{a}/open", {})).status_code == 200

    with_api(tmp_path, scenario)


def api04_cross_profile_404(tmp_path: Path):
    async def scenario(api: Api, r):
        a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
        token_a = (await api.unlock(a)).json()["profile_token"]
        assert (
            await api.call(
                "POST",
                "/v1/sessions",
                {
                    "client_session_id": cli(),
                    "mode": "guided",
                    "subject": "physics",
                    "level": "O",
                    "origin": {"kind": "ask", "ref": None},
                },
            )
        ).status_code == 401
        created = await api.call(
            "POST",
            "/v1/sessions",
            {
                "client_session_id": cli(),
                "mode": "guided",
                "subject": "physics",
                "level": "O",
                "origin": {"kind": "ask", "ref": None},
            },
            profile=token_a,
        )
        session_a = created.json()["session_id"]
        assert (await api.call("GET", f"/v1/sessions/{session_a}/snapshot", profile=token_a)).status_code == 200
        token_b = (await api.unlock(b)).json()["profile_token"]
        # Unlocking B ended A's token, and with B's token every route to A's data looks like a missing resource.
        assert (await api.call("GET", "/v1/sessions", profile=token_a)).status_code == 401
        for path in (f"/v1/sessions/{session_a}/snapshot", f"/v1/sessions/{session_a}/events",
                     f"/v1/profiles/{a}/settings", f"/v1/profiles/{a}/memory"):  # fmt: skip
            assert (await api.call("GET", path, profile=token_b)).status_code == 404, path
        assert (await api.call("GET", "/v1/sessions", profile=token_b)).json()["sessions"] == []
        assert (await api.call("POST", f"/v1/sessions/{session_a}/turns", ask(STATEMENT), profile=token_b)
                ).status_code == 404  # fmt: skip

    with_api(tmp_path, scenario)


def api04_no_adult_token(tmp_path: Path):
    """No endpoint accepts or requires an adult token, and opening a family profile needs no PIN (D86)."""
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    assert [k for k, e in ENDPOINTS_BY_KEY.items() if "adult" in e["auth"] or "adult_required" in e["errors"]] == []
    assert [k for k in ENDPOINTS_BY_KEY if "/v1/adult" in k or "unlock" in k or "pin" in k.split("/")[-1]] == []

    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        opened = await api.unlock(a)
        assert opened.status_code == 200 and set(opened.json()) == {"profile_token", "expires_in_s"}
        token = opened.json()["profile_token"]
        for path in ("/v1/adult/unlock", "/v1/adult/initialize", "/v1/adult/recover", "/v1/adult/pin",
                     f"/v1/profiles/{a}/unlock", f"/v1/profiles/{a}/reset-pin"):  # fmt: skip
            assert (await api.call("POST", path, {"pin": "24680"})).status_code in (404, 405), path
        # An adult token header is never read: a profile-scoped call without the profile token still answers 401,
        # and beside a profile token it adds nothing (the answer policy stays unsettable).
        body = {
            "client_session_id": cli(),
            "mode": "guided",
            "subject": "physics",
            "level": "O",
            "origin": {"kind": "ask", "ref": None},
        }
        refused = await api.call("POST", "/v1/sessions", body, headers={"x-adult-token": "at_anything"})
        assert refused.status_code == 401
        forged = await api.call("GET", f"/v1/profiles/{a}/settings", headers={"x-adult-token": "at_anything"})
        assert forged.status_code == 401
        policy = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"solution_policy": "never"}, profile=token,
                                headers={"x-adult-token": "at_anything"})  # fmt: skip
        assert policy.status_code == 422 and code(policy) == "validation_failed"
        assert (await r.client.post(f"{r.base}/v1/profiles", json=student("Unauthenticated"))).status_code == 401

    with_api(tmp_path, scenario)


# --- API-28 ----------------------------------------------------------------------------------------------------------


def api28_no_adult_elevation(tmp_path: Path):
    """Adding, restoring and opening need the launch token only; removing needs that profile's own token; a family
    profile accepts no PIN (D86, D87)."""

    async def scenario(api: Api, r):
        with_pin = await api.call("POST", "/v1/profiles", {**student("Ama"), "pin": "1234"})
        assert with_pin.status_code == 422 and code(with_pin) == "validation_failed"
        a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
        listed = (await api.call("GET", "/v1/profiles")).json()["profiles"]
        assert [p["profile_id"] for p in listed] == [a, b] and not [k for p in listed for k in p if "pin" in k]
        token_a = (await api.unlock(a)).json()["profile_token"]
        assert code(await api.call("PATCH", f"/v1/profiles/{a}", {"pin": "1234"}, profile=token_a)) == (
            "validation_failed")  # fmt: skip
        assert (await api.call("POST", f"/v1/profiles/{a}/open", {"pin": "1234"})).status_code == 422
        # Removing a profile takes its own token: none, or another profile's, does not remove it.
        assert (await api.call("DELETE", f"/v1/profiles/{b}")).status_code in (401, 404)
        assert (await api.call("DELETE", f"/v1/profiles/{b}", profile=token_a)).status_code == 404
        token_b = (await api.unlock(b)).json()["profile_token"]
        removed = await api.call("DELETE", f"/v1/profiles/{b}", profile=token_b)
        assert removed.status_code == 200, removed.text
        assert [p["profile_id"] for p in (await api.call("GET", "/v1/profiles")).json()["profiles"]] == [a]
        device = r.runtime.stores.device
        assert device.execute("SELECT 1 FROM sqlite_schema WHERE name='adult_pin'").fetchone() is None

    with_api(tmp_path, scenario)


def api28_student_preference_permissions(tmp_path: Path):
    async def scenario(api: Api, r):
        a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
        token_a = (await api.unlock(a)).json()["profile_token"]
        saved = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"memory_saving": False}, profile=token_a)
        assert saved.status_code == 200 and saved.json()["memory_saving"] is False
        assert (await api.call("PATCH", f"/v1/profiles/{b}/settings", {"memory_saving": False}, profile=token_a)
                ).status_code == 404  # fmt: skip
        mixed = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"text_scale": 1.25, "solution_policy": "never"},
                               profile=token_a)  # fmt: skip
        assert code(mixed) == "validation_failed"
        after = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token_a)).json()
        assert after["text_scale"] == 1.0 and "solution_policy" not in after
        minutes = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"daily_minutes": 30}, profile=token_a)
        assert code(minutes) == "validation_failed"

    with_api(tmp_path, scenario)


def api28_settings_patch_keys(tmp_path: Path):
    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        grown = await api.add(student("Esi", age_band="18_plus"))
        token = (await api.unlock(a)).json()["profile_token"]
        prefs = {
            "low_power": True,
            "text_scale": 1.5,
            "locale": "fr",
            "memory_saving": False,
            "notifications": True,
            "reduced_motion": True,
            "read_aloud": True,
            "easy_read": True,
            "extra_time_percent": 25,
            "theme": "dark",
            "character_shortcuts": False,
        }
        patched = await api.call("PATCH", f"/v1/profiles/{a}/settings", prefs, profile=token)
        assert patched.status_code == 200 and {k: patched.json()[k] for k in prefs} == prefs
        assert code(await api.call("PATCH", f"/v1/profiles/{a}/settings", {"solution_policy": "never"},
                                   profile=token)) == "validation_failed"  # fmt: skip
        for removed in ("study_hours", "allowed_modes", "locked_keys", "retention_days", "daily_minutes", "backup",
                        "cloud_model_tier", "language"):  # fmt: skip
            assert code(await api.call("PATCH", f"/v1/profiles/{a}/settings", {removed: 1}, profile=token)) == (
                "validation_failed"), removed  # fmt: skip
        assert code(await api.call("PATCH", f"/v1/profiles/{a}/settings", {"solution_policy": "always"},
                                   profile=token)) == "validation_failed"  # fmt: skip
        token = (await api.unlock(grown)).json()["profile_token"]
        own = await api.call("PATCH", f"/v1/profiles/{grown}/settings", {"solution_policy": "never"}, profile=token)
        assert own.status_code == 422 and code(own) == "validation_failed"  # D87: fixed at every age

    with_api(tmp_path, scenario)


# --- DAT-15 ----------------------------------------------------------------------------------------------------------


def test_open_profile_reads_its_own_age_band(tmp_path: Path):
    """The open profile's record carries its age band with its own token (PRV-06, API-28, D93), so the study screen
    knows whether the guardian agrees; the profile list keeps to name and avatar, and another profile's record is
    404."""
    from agent_core.contracts import errors

    async def scenario(api: Api, r):
        minor = await api.add(student("Ama"))
        grown = await api.add(student("Esi", age_band="18_plus"))
        token = await api.token(minor)
        own = await api.call("GET", f"/v1/profiles/{minor}", profile=token)
        assert own.status_code == 200 and errors("api/commands#/$defs/Profile", own.json()) == []
        assert (own.json()["display_name"], own.json()["age_band"]) == ("Ama", "13_15")
        assert (await api.call("GET", f"/v1/profiles/{grown}", profile=token)).status_code == 404
        assert (await api.call("GET", f"/v1/profiles/{minor}")).status_code in (401, 404)  # no profile token
        listed = (await api.call("GET", "/v1/profiles")).json()["profiles"]
        assert all(set(p) == {"profile_id", "display_name", "avatar"} for p in listed)
        corrected = await api.call("PATCH", f"/v1/profiles/{minor}", {"age_band": "18_plus"}, profile=token)
        assert corrected.json()["age_band"] == "18_plus"
        assert (await api.call("GET", f"/v1/profiles/{minor}", profile=token)).json()["age_band"] == "18_plus"

    with_api(tmp_path, scenario)


def test_theme_kept_per_profile_and_applied_on_next_launch(tmp_path: Path):
    """DSN-05, D91: the theme is a student preference like the others: written with the profile token, stored with a
    `setting_change` event, returned with the effective settings and still there after the core restarts. The default
    is "Match this computer"; a value outside the three is refused by the API."""

    async def first_run():
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = await api.token(a)
            assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()["theme"] == "system"
            for bad in ("high_contrast", "Dark", True):
                refused = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"theme": bad}, profile=token)
                assert refused.status_code == 422 and code(refused) == "validation_failed", bad
            patched = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"theme": "dark"}, profile=token)
            assert patched.status_code == 200 and patched.json()["theme"] == "dark", patched.text
            assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()["theme"] == "dark"
            other = await api.token(b)
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()["theme"] == "system"
            return a, b
        finally:
            await stop_core(r)

    async def next_launch(a: str, b: str):
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            token = await api.token(a)
            assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()["theme"] == "dark"
            other = await api.token(b)
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()["theme"] == "system"
        finally:
            await stop_core(r)

    a, b = run(first_run())
    run(next_launch(a, b))
    stored: list[tuple[list[Any], list[Any]]] = []
    for learner in sorted(tmp_path.glob("profiles/*/learner.db")):
        conn = sqlite3.connect(learner)
        try:
            rows = conn.execute("SELECT key, value, source FROM settings WHERE key = 'theme'").fetchall()
            sql = "SELECT payload FROM events WHERE type = 'setting_change'"
            stored.append((rows, [json.loads(p) for (p,) in conn.execute(sql)]))
        finally:
            conn.close()
    # Ama's database holds the stored value and its event; every other profile's (Kofi's included) has neither.
    change = {"setting": "theme", "old_value": "system", "new_value": "dark", "actor_role": "student"}
    assert len(stored) >= 2 and sorted(len(rows) for rows, _ in stored) == [0] * (len(stored) - 1) + [1]
    for rows, changes in stored:
        assert (rows == [("theme", '"dark"', "student")]) == (change in changes)


def test_theme_migration_keeps_stored_settings(tmp_path: Path):
    """DAT-12, D91: a learner database from before the theme key keeps every stored setting, then accepts `theme` and
    only its three values."""
    from agent_core.store.sqlite import MIGRATIONS, open_database

    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", [m for m in MIGRATIONS["learner"] if m.version <= 4])
    insert = ("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at)"
              " VALUES (?, ?, 'student', NULL, ?, 1)")  # fmt: skip
    conn.execute(insert, ("speech_rate", "1.25", "000000000000001-00000"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("theme", '"dark"', "000000000000002-00000"))
    conn.close()
    conn, applied = open_database(path, "learner")
    try:
        # Every step after v4 runs, the theme step (v5) first.
        assert [step.version for step in applied] == [m.version for m in MIGRATIONS["learner"] if m.version >= 5]
        assert conn.execute("SELECT key, value FROM settings").fetchall() == [("speech_rate", "1.25")]
        conn.execute(insert, ("theme", '"dark"', "000000000000002-00000"))
        for bad in ('"high_contrast"', '"Dark"', "1"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE settings SET value = ? WHERE key = 'theme'", (bad,))
    finally:
        conn.close()


def test_character_shortcuts_kept_per_profile_and_applied_on_next_launch(tmp_path: Path):
    """LOC-12, D92: character-key shortcuts on or off is a student preference: written with the profile token, stored
    with a `setting_change` event, returned with the effective settings and still there after the core restarts. The
    keys are on by default; anything but a boolean is refused by the API."""

    async def first_run():
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = await api.token(a)
            settings = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
            assert settings["character_shortcuts"] is True
            for bad in ("off", 0, None):
                refused = await api.call(
                    "PATCH", f"/v1/profiles/{a}/settings", {"character_shortcuts": bad}, profile=token
                )
                assert refused.status_code == 422 and code(refused) == "validation_failed", bad
            patched = await api.call(
                "PATCH", f"/v1/profiles/{a}/settings", {"character_shortcuts": False}, profile=token
            )
            assert patched.status_code == 200 and patched.json()["character_shortcuts"] is False, patched.text
            other = await api.token(b)
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()["character_shortcuts"]
            return a, b
        finally:
            await stop_core(r)

    async def next_launch(a: str, b: str):
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            token = await api.token(a)
            settings = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
            assert settings["character_shortcuts"] is False
            other = await api.token(b)
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()["character_shortcuts"]
        finally:
            await stop_core(r)

    a, b = run(first_run())
    run(next_launch(a, b))
    stored: list[tuple[list[Any], list[Any]]] = []
    for learner in sorted(tmp_path.glob("profiles/*/learner.db")):
        conn = sqlite3.connect(learner)
        try:
            rows = conn.execute("SELECT key, value, source FROM settings WHERE key = 'character_shortcuts'").fetchall()
            sql = "SELECT payload FROM events WHERE type = 'setting_change'"
            stored.append((rows, [json.loads(p) for (p,) in conn.execute(sql)]))
        finally:
            conn.close()
    # Ama's database holds the stored value and its event; every other profile's has neither.
    change = {"setting": "character_shortcuts", "old_value": True, "new_value": False, "actor_role": "student"}
    assert len(stored) >= 2 and sorted(len(rows) for rows, _ in stored) == [0] * (len(stored) - 1) + [1]
    for rows, changes in stored:
        assert (rows == [("character_shortcuts", "false", "student")]) == (change in changes)


def test_character_shortcuts_migration_keeps_stored_settings(tmp_path: Path):
    """DAT-12, D92: a learner database from before the key keeps every stored setting, then accepts
    `character_shortcuts` as a JSON boolean only."""
    from agent_core.store.sqlite import MIGRATIONS, open_database

    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", [m for m in MIGRATIONS["learner"] if m.version <= 5])
    insert = ("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at)"
              " VALUES (?, ?, 'student', NULL, ?, 1)")  # fmt: skip
    conn.execute(insert, ("theme", '"dark"', "000000000000001-00000"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("character_shortcuts", "false", "000000000000002-00000"))
    conn.close()
    conn, applied = open_database(path, "learner")
    try:
        assert [step.version for step in applied] == [m.version for m in MIGRATIONS["learner"] if m.version >= 6]
        assert conn.execute("SELECT key, value FROM settings").fetchall() == [("theme", '"dark"')]
        conn.execute(insert, ("character_shortcuts", "false", "000000000000002-00000"))
        for bad in ('"false"', "0", "null"):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE settings SET value = ? WHERE key = 'character_shortcuts'", (bad,))
    finally:
        conn.close()


def test_prm03_tutor_identity_kept_per_profile(tmp_path: Path):
    """PRM-02, PRM-03, D47, D99: the tutor's name and avatar are student preferences of each profile: Jana and the
    default avatar until chosen, written with the profile token, checked against the PRV-03 name rules, stored with a
    `setting_change` event and still there after the core restarts; another profile keeps the defaults."""

    async def first_run():
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = await api.token(a)
            settings = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
            assert (settings["tutor_name"], settings["tutor_avatar"]) == ("Jana", "avatar.jana")
            for bad in ({"tutor_name": ""}, {"tutor_name": "   "}, {"tutor_name": "x" * 41},
                        {"tutor_name": "Line\nbreak"}, {"tutor_name": 7}, {"tutor_avatar": "brand.mark"},
                        {"tutor_avatar": "avatar.owl"}, {"tutor_avatar": "avatar.default"}):  # fmt: skip
                refused = await api.call("PATCH", f"/v1/profiles/{a}/settings", bad, profile=token)
                assert refused.status_code == 422 and code(refused) == "validation_failed", bad
            chosen = {"tutor_name": " Nova ", "tutor_avatar": "avatar.orbit"}
            patched = await api.call("PATCH", f"/v1/profiles/{a}/settings", chosen, profile=token)
            assert patched.status_code == 200, patched.text
            assert (patched.json()["tutor_name"], patched.json()["tutor_avatar"]) == ("Nova", "avatar.orbit")
            other = await api.token(b)
            assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=other)).json()["tutor_name"] == "Jana"
            return a
        finally:
            await stop_core(r)

    async def next_launch(a: str):
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            token = await api.token(a)
            settings = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
            assert (settings["tutor_name"], settings["tutor_avatar"]) == ("Nova", "avatar.orbit")
        finally:
            await stop_core(r)

    run(next_launch(run(first_run())))
    names = []
    for learner in sorted(tmp_path.glob("profiles/*/learner.db")):
        conn = sqlite3.connect(learner)
        try:
            names += conn.execute("SELECT value FROM settings WHERE key = 'tutor_name'").fetchall()
        finally:
            conn.close()
    assert names == [('"Nova"',)]


def test_prm03_session_prompts_use_the_open_profiles_tutor_name(tmp_path: Path):
    """PRM-03, D99, D101: a session of the open profile builds its Coach prompts with the name that profile chose, read
    at each build so a rename applies from the next request; another profile keeps the default, Jana (D47)."""
    from agent_core.engine.state import SessionState
    from agent_core.prompts.builder import Message, PromptSession, build_prompt

    def coach_soul(r) -> str:
        engine = r.runtime.engine(SessionState(f"ses_{len(r.runtime.engines)}"))
        deps = engine.deps
        session = PromptSession(**engine._prompt_base(), transcript=(Message("user", "hi"),))
        build = build_prompt("coach", deps.family, session, [], set(), set(deps.registry.specs), deps.assets,
                             deps.settings)  # fmt: skip
        return build.tiers[0].text.splitlines()[0]

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = await api.token(a)
            assert coach_soul(r) == "I am Jana, the student's tutor."
            patched = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"tutor_name": "Nova"}, profile=token)
            assert patched.status_code == 200, patched.text
            assert coach_soul(r) == "I am Nova, the student's tutor."
            await api.token(b)  # switching opens the other profile's learner database
            assert coach_soul(r) == "I am Jana, the student's tutor."
        finally:
            await stop_core(r)

    run(scenario())


def test_prm03_tutor_defaults_are_the_identity_files():
    """D47: the configured defaults of the tutor's name and avatar are the identity file's."""
    from agent_core.assets.agent import load_identity
    from agent_core.config import Settings

    identity = load_identity(Path(__file__).resolve().parents[3] / "content" / "agent" / "soul")
    assert (Settings().tutor_name, Settings().tutor_avatar) == (identity["tutor_name"], identity["avatar_id"])


def test_prm03_tutor_identity_migration_keeps_stored_settings(tmp_path: Path):
    """DAT-12, D99: a learner database from before the keys keeps every stored setting, then accepts `tutor_name` as
    a JSON string of 1 to 40 characters and `tutor_avatar` as an avatar id only (D103: one of the six characters
    since migration 8)."""
    from agent_core.store.sqlite import MIGRATIONS, open_database

    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", [m for m in MIGRATIONS["learner"] if m.version <= 6])
    insert = ("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at)"
              " VALUES (?, ?, 'student', NULL, ?, 1)")  # fmt: skip
    conn.execute(insert, ("character_shortcuts", "false", "000000000000001-00000"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("tutor_name", '"Nova"', "000000000000002-00000"))
    conn.close()
    conn, applied = open_database(path, "learner")
    try:
        assert [step.version for step in applied] == [m.version for m in MIGRATIONS["learner"] if m.version >= 7]
        assert conn.execute("SELECT key, value FROM settings").fetchall() == [("character_shortcuts", "false")]
        conn.execute(insert, ("tutor_name", '"Nova"', "000000000000002-00000"))
        conn.execute(insert, ("tutor_avatar", '"avatar.ray"', "000000000000003-00000"))
        for key, bad in (("tutor_name", '""'), ("tutor_name", "7"), ("tutor_name", '"' + "x" * 41 + '"'),
                         ("tutor_avatar", '"brand.mark"'), ("tutor_avatar", '"avatar.owl"')):  # fmt: skip
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE settings SET value = ? WHERE key = ?", (bad, key))
    finally:
        conn.close()


def test_d103_characters_migration_reads_old_avatars_as_jana(tmp_path: Path):
    """DAT-12, D103, G119: a learner database at migration 7 with an avatar from before the six characters
    (avatar.default, avatar.disc_N) reads it as avatar.jana after migration 8, keeps a character id and every other
    row as it was, and then accepts `faster_tutor` and `wake_word` as booleans only; `study_notes` gains `private`."""
    from agent_core.store.sqlite import MIGRATIONS, open_database

    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", [m for m in MIGRATIONS["learner"] if m.version <= 7])
    insert = ("INSERT INTO settings (key, value, source, set_by_event_id, hlc, updated_at)"
              " VALUES (?, ?, 'student', NULL, ?, 1)")  # fmt: skip
    conn.execute(insert, ("tutor_avatar", '"avatar.disc_3"', "000000000000001-00000"))
    conn.execute(insert, ("tutor_name", '"Nova"', "000000000000002-00000"))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("faster_tutor", "true", "000000000000003-00000"))
    conn.close()
    conn, applied = open_database(path, "learner")
    try:
        assert [step.version for step in applied] == [m.version for m in MIGRATIONS["learner"] if m.version >= 8]
        assert dict(conn.execute("SELECT key, value FROM settings").fetchall()) == {
            "tutor_avatar": '"avatar.jana"', "tutor_name": '"Nova"'}  # fmt: skip
        conn.execute(insert, ("faster_tutor", "true", "000000000000003-00000"))
        conn.execute(insert, ("wake_word", "false", "000000000000004-00000"))
        for key, bad in (("faster_tutor", '"yes"'), ("wake_word", "1"), ("tutor_avatar", '"avatar.default"')):
            with pytest.raises(sqlite3.IntegrityError):
                conn.execute("UPDATE settings SET value = ? WHERE key = ?", (bad, key))
        assert "private" in {row[1] for row in conn.execute("PRAGMA table_info(study_notes)")}
    finally:
        conn.close()


def test_d103_old_avatar_reads_and_writes_as_jana(tmp_path: Path):
    """D103, G119: an avatar id outside the six, wherever it comes from (an identity file, a profile archive or an
    internal write), reads and is written as avatar.jana; a character id is kept."""
    from agent_core.assets.agent import load_identity
    from agent_core.store.settings import tutor_avatar

    assert [tutor_avatar(v) for v in ("avatar.default", "avatar.disc_3", None, 7, "avatar.kite")] == [
        "avatar.jana", "avatar.jana", "avatar.jana", "avatar.jana", "avatar.kite"]  # fmt: skip
    soul = tmp_path / "soul"
    soul.mkdir()
    (soul / "IDENTITY.yaml").write_text("tutor_name: Jana\navatar_id: avatar.default\nlocale: en\n"
                                        "reading_level: standard\n")  # fmt: skip
    assert load_identity(soul)["avatar_id"] == "avatar.jana"


def test_d103_faster_tutor_and_wake_word_preferences(tmp_path: Path):
    """UXS-03, MDL-05, VOC-49, D103: `faster_tutor` (off by default) and `wake_word` (off; retired by D126 and
    ignored, kept so stored profiles and history stay valid) are student preferences of the profile, written with its
    settings patch and recorded as `setting_change` events; the router's faster-tutor switch reads the stored choice."""

    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        token = await api.token(a)
        settings = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
        assert (settings["faster_tutor"], settings["wake_word"]) == (False, False)  # wake word off by default (D125)
        for bad in ({"faster_tutor": "yes"}, {"wake_word": 1}):
            refused = await api.call("PATCH", f"/v1/profiles/{a}/settings", bad, profile=token)
            assert refused.status_code == 422 and code(refused) == "validation_failed", bad
        patched = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"faster_tutor": True, "wake_word": True},
                                 profile=token)  # fmt: skip
        assert patched.status_code == 200, patched.text
        assert (patched.json()["faster_tutor"], patched.json()["wake_word"]) == (True, True)
        rows = r.runtime.learner.conn.execute(
            "SELECT payload FROM events WHERE type = 'setting_change' ORDER BY seq").fetchall()  # fmt: skip
        assert {json.loads(p)["setting"] for (p,) in rows} >= {"faster_tutor", "wake_word"}
        assert r.runtime.faster_tutor_preference() is True

    with_api(tmp_path, scenario)


def prm03_one_tutor_per_profile(tmp_path: Path):
    """PRM-03, D103: changing the character and the name re-skins and renames the same tutor: the profile's memory
    notes and learner model are unchanged and no second tutor identity is created (one name and one character row)."""

    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        token = await api.token(a)
        conn = r.runtime.learner.conn
        conn.execute(
            "INSERT OR REPLACE INTO preferences (key, value, confidence, last_event_seq)"
            " VALUES ('unprompted_help', 'false', 1.0, 0)"
        )  # a learner-model row the re-skin must keep
        tables = ("notes", "kc_mastery", "learner_misconceptions", "review_cards", "preferences", "study_notes")

        def memory() -> dict[str, list[tuple]]:
            return {t: conn.execute(f"SELECT * FROM {t}").fetchall() for t in tables}  # noqa: S608 (fixed names)

        before = memory()
        assert before["preferences"]
        for patch in ({"tutor_avatar": "avatar.prism", "tutor_name": "Prism"}, {"tutor_name": "Nova"},
                      {"tutor_avatar": "avatar.pebble"}):  # fmt: skip
            reply = await api.call("PATCH", f"/v1/profiles/{a}/settings", patch, profile=token)
            assert reply.status_code == 200, reply.text
        assert memory() == before, "memory notes and the learner model stay"
        rows = conn.execute("SELECT key, value FROM settings WHERE key IN ('tutor_name', 'tutor_avatar')").fetchall()
        assert sorted(rows) == [("tutor_avatar", '"avatar.pebble"'), ("tutor_name", '"Nova"')], "one tutor"
        effective = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
        assert (effective["tutor_name"], effective["tutor_avatar"]) == ("Nova", "avatar.pebble")

    with_api(tmp_path, scenario)


def dat15_canonical_keys_agree():
    from agent_core.contracts.api.commands import Settings, SettingsPatch
    from agent_core.store.generated.schema import DATABASES

    events = json.loads((Path(__file__).parents[1] / "agent_core" / "contracts" / "schemas" / "learning" /
                         "learning-event.schema.json").read_text())  # fmt: skip
    change = set(events["$defs"]["payload_setting_change"]["properties"]["setting"]["enum"])
    check = DATABASES["learner"].split("CREATE TABLE settings", 1)[1].split("value", 1)[0]
    table = {k for k in KEYS if f"'{k}'" in check}
    assert set(Settings.model_fields) == set(SettingsPatch.model_fields) == change == table == set(KEYS)
    for removed in ("backup", "cloud_model_tier", "language"):
        assert removed not in SettingsPatch.model_fields


def dat15_integrity_most_restrictive(tmp_path: Path):
    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        token = (await api.unlock(a)).json()["profile_token"]
        # A write cannot carry the answer policy, alone or inside another patch (PED-09, D87).
        assert code(await api.call("PATCH", f"/v1/profiles/{a}/settings", {"solution_policy": "after_attempt"},
                                   profile=token)) == "validation_failed"  # fmt: skip
        # An active lock (a mock sitting) overrides the stored value and refuses a write that would relax it.
        r.core.locks = lambda profile_id: {"extra_time_percent": 0}
        locked = await api.call("PATCH", f"/v1/profiles/{a}/settings", {"extra_time_percent": 50}, profile=token)
        assert locked.status_code == 423 and code(locked) == "tutor_locked"
        effective = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
        assert "solution_policy" not in effective and effective["extra_time_percent"] == 0

    with_api(tmp_path, scenario)


# --- SEC-19 ----------------------------------------------------------------------------------------------------------


def test_sec19_reopening_rotates_the_profile_token_without_pin_throttling(tmp_path: Path):
    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        tokens = []
        for _ in range(8):
            opened = await api.unlock(a)
            assert opened.status_code == 200
            tokens.append(opened.json()["profile_token"])
        assert len(set(tokens)) == 8
        assert (await api.call("GET", "/v1/sessions", profile=tokens[0])).status_code == 401
        assert (await api.call("GET", "/v1/sessions", profile=tokens[-1])).status_code == 200

    with_api(tmp_path, scenario)


def test_rate_limits_answer_429(tmp_path: Path):
    """API-33: command bursts and turn starts are limited, with retry_after_ms; card answers and cancels are exempt."""
    from agent_core.config import Settings as S

    settings = S(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), api_command_burst_per_s=3,
                 api_turn_starts_per_min=2)  # fmt: skip

    async def scenario():
        r = await start_core(tmp_path, settings=settings, worker=False)
        api = Api(r)
        try:
            replies = [await api.call("POST", "/v1/profiles", student(f"Student {n}")) for n in range(5)]
            limited = [x for x in replies if x.status_code == 429]
            assert limited and limited[0].json()["error"]["retry_after_ms"] > 0
            cancels = [await api.call("POST", "/v1/turns/trn_01M4CANCEL0000000000000000/cancel") for _ in range(5)]
            assert all(c.status_code != 429 for c in cancels)
        finally:
            await stop_core(r)

    run(scenario())


def test_profile_token_passes_the_webview_preflight(tmp_path: Path):
    """CORS permits profile tokens and advertises no adult token header (API-04, D86)."""

    async def scenario():
        r = await start_core(tmp_path, worker=False)
        try:
            reply = await r.client.request("OPTIONS", f"{r.base}/v1/connectivity", headers={
                "origin": "tauri://localhost", "access-control-request-method": "PATCH",
                "access-control-request-headers": "x-profile-token, x-profile-open-intent, idempotency-key",
            })  # fmt: skip
            return reply.headers.get("access-control-allow-headers", "")
        finally:
            await stop_core(r)

    allowed = run(scenario())
    assert "x-adult-token" not in allowed and "x-profile-token" in allowed
    assert "x-profile-open-intent" in allowed
