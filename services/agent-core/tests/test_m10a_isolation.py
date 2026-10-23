"""M10.a: isolation between profiles, the family settings with no PIN or adult token, secrets at rest and
single-purpose keys (TCH-01, TCH-13, DAT-14, SEC-17, SEC-32, D86, D87). Synthetic profiles and canaries; no real
student data."""

import asyncio
import json
from pathlib import Path

from agent_core.config import Settings
from agent_core.providers.llama import LlamaServerProvider
from agent_core.store.exports import ExportError, open_as_recipient, open_with_passphrase
from api_harness import STATEMENT, ask, cli, start_core, stop_core
from jana_tools.fakes.llama_server import FakeLlamaServer
from test_m10a_profiles import Api, code, student
from test_m10d_deletion_export import PASSPHRASE, STUDY, SUPPORT, _settings

LOOP = asyncio.new_event_loop()
NOTICE = "2026-10.d1"  # the shipped notice versions (content/agent/notices)
CANARY_A = "A tram qq9amaq leaves the depot at 4 m/s and speeds up for 5 s at 2 m/s^2. How fast is it then?"
CANARY_B = "A kite kk7kofi climbs 24 m in 8 s. What is its average speed upwards?"


def run(coro):
    return LOOP.run_until_complete(coro)


def with_api(tmp_path: Path, scenario, worker: bool = True, settings: Settings | None = None, provider=None):
    async def go():
        r = await start_core(tmp_path, worker=worker, settings=settings or _settings(), provider=provider)
        try:
            return await scenario(Api(r), r)
        finally:
            await stop_core(r)

    return run(go())


async def _turn(api: Api, r, token: str, text: str = STATEMENT, session: str | None = None) -> str:
    if session is None:
        body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                "origin": {"kind": "ask", "ref": None}}  # fmt: skip
        session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
    intent = "ask" if text.endswith("?") else "answer"
    await api.call("POST", f"/v1/sessions/{session}/turns", ask(text, intent), profile=token)
    for _ in range(600):
        entry = r.core.sessions.get(session)
        if entry is not None and (entry.task is None or entry.task.done()):
            break
        await asyncio.sleep(0.05)
    return session


# --- TCH-01 ----------------------------------------------------------------------------------------------------------


def tch01_permission_matrix_enforced(tmp_path: Path):
    async def scenario(api: Api, r):
        a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
        token_a = (await api.unlock(a)).json()["profile_token"]
        session = await _turn(api, r, token_a, CANARY_A)
        # Nobody reads a conversation without the student's own token: there is no adult or staff role (D86).
        for path in ("/v1/sessions", f"/v1/sessions/{session}/snapshot", f"/v1/sessions/{session}/events"):
            assert (await api.call("GET", path)).status_code in (401, 404), path
        assert code(await api.call("POST", f"/v1/profiles/{a}/archive-authorizations",
                                   {"session_ids": [session], "include_attachments": False, "confirmed": True})
                    ) in ("profile_token_expired", "not_found")  # fmt: skip
        # Family operations use launch authority; learner operations remain restricted to their profile.
        assert (await api.call("POST", "/v1/profiles", student("Esi"), profile=token_a)).status_code == 200
        assert (
            await api.call("PATCH", "/v1/connectivity", {"features": {"downloads": True}}, profile=token_a)
        ).status_code == 200
        assert (await api.call("DELETE", f"/v1/profiles/{b}", profile=token_a)).status_code == 404
        # And never crosses into another profile.
        assert (await api.call("GET", f"/v1/profiles/{b}/settings", profile=token_a)).status_code == 404

    with_api(tmp_path, scenario)


def tch01_no_teacher_role(tmp_path: Path):
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY
    from pack_builder.roles import ROLES

    endpoints = json.dumps(ENDPOINTS_BY_KEY)
    assert "/v1/profiles" in endpoints  # the table is really there
    for word in ("teacher", "/classes", "/hub", "staff", "school-admin", "safeguarding"):
        assert word not in endpoints, word
    assert not [r for r in ROLES if "teacher" in r or "staff" in r]

    async def scenario(api: Api, r):
        for path in ("/v1/teacher", "/v1/classes", "/v1/hub/pair", "/v1/staff/login", "/v1/school/admin"):
            assert (await api.call("GET", path)).status_code == 404, path
        staff = await api.r.client.post(f"{api.r.base}/v1/profiles", headers={
            **api.r.headers(mutating=True), "x-staff-token": "staff-1", "x-teacher-token": "t-1"},
            content=json.dumps(student("Esi")))  # fmt: skip
        assert staff.status_code == 200  # launch credentials permit creation; extra role headers add no powers
        profile = staff.json()["profile_id"]
        assert (
            code(await api.call("GET", f"/v1/profiles/{profile}/settings", headers={"x-staff-token": "staff-1"}))
            == "profile_token_expired"
        )

    with_api(tmp_path, scenario, worker=False)


# --- TCH-13 ----------------------------------------------------------------------------------------------------------


def tch13_no_adult_pin(tmp_path: Path):
    """No screen, route or store asks for, holds or checks an adult PIN, a recovery code or a student PIN, and no
    endpoint takes an adult token (D86)."""
    from agent_core.contracts.api.commands import CreateProfile, Profile, ProfileSummary, UpdateProfile
    from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY

    assert [k for k, e in ENDPOINTS_BY_KEY.items() if "adult" in e["auth"]] == []
    assert not [k for k in ENDPOINTS_BY_KEY if "/v1/adult" in k or "pin" in k.split("/")[-1] or "recover" in k]
    for model in (CreateProfile, UpdateProfile, Profile, ProfileSummary):
        assert not [f for f in model.model_fields if "pin" in f], model.__name__

    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        assert (await api.unlock(a)).status_code == 200  # a tap, nothing else
        for path in (f"/v1/profiles/{a}/reset-pin", "/v1/adult/pin", "/v1/adult/unlock", "/v1/adult/recover",
                     "/v1/adult/initialize"):  # fmt: skip
            assert (await api.call("POST", path, {"pin": "71904268"})).status_code in (404, 405), path
        device = r.runtime.stores.device
        tables = {row[0] for row in device.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        assert "adult_pin" not in tables
        columns = {row[1] for row in device.execute("PRAGMA table_info(profiles_index)")}
        assert not [c for c in columns if "pin" in c], columns
        assert set(r.runtime.directory.keys.secrets) <= {"jana.install"}  # no PIN or recovery secret is held

    with_api(tmp_path, scenario, worker=False)


def tch13_removed_keys_rejected(tmp_path: Path):
    async def scenario(api: Api, r):
        a = await api.add(student("Ama"))
        token = (await api.unlock(a)).json()["profile_token"]
        before = (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json()
        connectivity = (await api.call("GET", "/v1/connectivity")).json()
        for removed in ("solution_policy", "study_hours", "homework_hours", "allowed_modes", "locked_keys",
                        "transcript_retention_days", "photo_retention_days"):  # fmt: skip
            reply = await api.call("PATCH", f"/v1/profiles/{a}/settings", {removed: 1}, profile=token)
            assert reply.status_code == 422 and code(reply) == "validation_failed", removed
            mixed = await api.call("PATCH", f"/v1/profiles/{a}/settings", {removed: 1, "text_scale": 1.5},
                                   profile=token)  # fmt: skip
            assert code(mixed) == "validation_failed", removed
            switched = await api.call("PATCH", "/v1/connectivity", {"features": {removed: True}})
            assert code(switched) == "validation_failed", removed
        assert (await api.call("GET", f"/v1/profiles/{a}/settings", profile=token)).json() == before
        assert (await api.call("GET", "/v1/connectivity")).json() == connectivity

    with_api(
        tmp_path, scenario, worker=False, settings=_settings().model_copy(update={"api_command_burst_per_s": 1000})
    )


def tch13_off_always_on_needs_consent(tmp_path: Path):
    """From an open profile every switch and consent goes off in one step; a paused consent comes back on with no
    guardian step; a minor's first switch-on of a data-sending feature without checkout consent stays off (D86, D87)."""
    settings = _settings().model_copy(update={"consent_dpia_ref": "dpia-test-1"})

    async def scenario(api: Api, r):
        minor = await api.add(student("Ama"))
        token = (await api.unlock(minor)).json()["profile_token"]
        on = await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": True, "downloads": True}},
                            profile=token)  # fmt: skip
        assert on.status_code == 200, on.text
        first = await api.call("PUT", f"/v1/profiles/{minor}/consents/cloud_tier",
                               {"action": "on", "notice_version": NOTICE}, profile=token)  # fmt: skip
        assert first.status_code == 403 and code(first) == "guardian_consent_required"
        consents = (await api.call("GET", f"/v1/profiles/{minor}/consents", profile=token)).json()
        assert next(c for c in consents if c["scope"] == "cloud_tier")["effective"] is False
        # The research study: the guardian agrees on the study screen; then the student pauses and resumes it.
        granted = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use",
                                 {"action": "on", "notice_version": NOTICE, "guardian_agreed": True},
                                 profile=token)  # fmt: skip
        assert granted.json()["method"] == "in_app_guardian" and granted.json()["effective"] is True
        paused = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "pause"},
                                profile=token)  # fmt: skip
        assert paused.json()["paused"] is True and paused.json()["granted"] is True
        assert paused.json()["effective"] is False
        resumed = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "on"},
                                 profile=token)  # fmt: skip
        assert resumed.json()["paused"] is False and resumed.json()["effective"] is True
        assert resumed.json()["granted_at"] == granted.json()["granted_at"]  # the same consent, not a new grant
        # Everything goes off in one step each, with no PIN.
        off = await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": False, "downloads": False}},
                             profile=token)  # fmt: skip
        assert off.status_code == 200 and not any(f["enabled"] for f in off.json()["features"].values())
        withdrawn = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "withdraw"},
                                   profile=token)  # fmt: skip
        assert withdrawn.json()["granted"] is False
        again = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use",
                               {"action": "on", "notice_version": NOTICE}, profile=token)  # fmt: skip
        assert code(again) in ("guardian_consent_required", "validation_failed")  # a new grant needs the guardian

    with_api(tmp_path, scenario, worker=False, settings=settings)


# --- DAT-14 ----------------------------------------------------------------------------------------------------------


def dat14_no_cross_profile_leak(tmp_path: Path):
    async def scenario(api: Api, r):
        a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
        await _turn(api, r, (await api.unlock(a)).json()["profile_token"], CANARY_A)
        token_b = (await api.unlock(b)).json()["profile_token"]
        provider = r.runtime.providers["local"]
        provider.requests = []  # keep the prompts of profile B's turn (the development provider discards them)
        session_b = await _turn(api, r, token_b, CANARY_B)
        views = [await api.call("GET", path, profile=token_b) for path in (
            "/v1/sessions", f"/v1/sessions/{session_b}/snapshot", f"/v1/profiles/{b}/settings",
            f"/v1/profiles/{b}/consents")]  # fmt: skip
        folder = tmp_path / "usb"
        folder.mkdir()
        exported = await api.call("POST", "/v1/exports", {"kind": "profile_archive", "profile_ids": [b],
                                                          "passphrase": PASSPHRASE,
                                                          "destination": {"kind": "file", "path": str(folder)}},
                                  profile=token_b)  # fmt: skip
        archive = next(folder.iterdir()).read_bytes()
        r.runtime.traces.flush()
        traces_b = [t for t in r.runtime.traces.records() if t.get("profile_ref") == b]
        prompts = list(provider.requests)
        assert prompts, "profile B's turn prompted the model"
        return views, exported, archive, traces_b, prompts

    views, exported, archive, traces_b, prompts = with_api(tmp_path, scenario)
    assert exported.status_code == 202
    for text in [v.text for v in views] + [open_with_passphrase(archive, PASSPHRASE).decode("latin-1"),
                                           json.dumps(traces_b), json.dumps(prompts)]:  # fmt: skip
        assert "qq9amaq" not in text
    assert any("kk7kofi" in v.text for v in views)


def dat14_kv_cache_cleared(tmp_path: Path):
    async def scenario():
        async with FakeLlamaServer(["qwen3-vl-8b", "gemma-4-12b"]) as server:
            provider = LlamaServerProvider(server.url, server.api_key)
            r = await start_core(tmp_path, worker=False, provider=provider)
            api = Api(r)
            try:
                a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
                await api.unlock(a)
                provider.used.add("gemma-4-12b")  # profile A's prompts reached this model's slots
                assert server.erased == []
                await api.unlock(b)  # the switch
                after_switch = list(server.erased)
                token_b = (await api.unlock(b)).json()["profile_token"]
                await api.call("POST", f"/v1/profiles/{b}/close", profile=token_b)
                return after_switch, list(server.erased)
            finally:
                await stop_core(r)

    after_switch, after_lock = run(scenario())
    assert after_switch == [("gemma-4-12b", 0), ("gemma-4-12b", 1)]
    assert len(after_lock) == 4  # a lock clears them again


# --- SEC-17, SEC-32 --------------------------------------------------------------------------------------------------


def sec17_no_secrets_at_rest_outside_keychain(tmp_path: Path):
    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        await _turn(api, r, token, STATEMENT)
        folder = tmp_path / "usb"
        folder.mkdir()
        await api.call(
            "POST",
            "/v1/exports",
            {
                "kind": "profile_archive",
                "profile_ids": [profile],
                "passphrase": PASSPHRASE,
                "destination": {"kind": "file", "path": str(folder)},
            },
            profile=token,
        )
        await api.call(
            "POST",
            "/v1/exports",
            {
                "kind": "diagnostic_bundle",
                "profile_ids": [profile],
                "destination": {"kind": "file", "path": str(folder)},
            },
            profile=token,
        )
        r.runtime.traces.flush()
        bundle = next(p for p in folder.iterdir() if p.suffix == ".janadiag").read_bytes()
        return [r.token, token, PASSPHRASE], open_as_recipient(bundle, SUPPORT)

    secrets, bundle = with_api(tmp_path, scenario)
    for path in [p for p in tmp_path.rglob("*") if p.is_file() and "usb" not in p.parts]:
        data = path.read_bytes()
        for secret in secrets:
            assert secret.encode() not in data, (path.relative_to(tmp_path), secret[:4])
    for secret in secrets:
        assert secret.encode() not in bundle


def sec32_keys_single_purpose(tmp_path: Path):
    async def scenario(api: Api, r):
        first, second = await api.add(student("Ama")), await api.add(student("Kofi"))
        folder = tmp_path / "usb"
        folder.mkdir()
        sealed = {}
        for kind, profile, extra in (("profile_archive", first, {"passphrase": PASSPHRASE}),
                                     ("profile_archive", second, {"passphrase": "another long passphrase"}),
                                     ("diagnostic_bundle", first, {})):  # fmt: skip
            token = (await api.unlock(profile)).json()["profile_token"]
            await api.call("POST", "/v1/exports", {"kind": kind, "profile_ids": [profile], **extra,
                                                   "destination": {"kind": "file", "path": str(folder)}},
                           profile=token)  # fmt: skip
            newest = max(folder.iterdir(), key=lambda p: p.stat().st_mtime_ns)
            sealed[(kind, profile)] = newest.read_bytes()
            await asyncio.sleep(1.1)  # export file names carry the second
        return sealed, first, second

    sealed, first, second = with_api(tmp_path, scenario, worker=False)
    assert open_with_passphrase(sealed[("profile_archive", first)], PASSPHRASE)
    for blob, attempt in ((sealed[("profile_archive", second)], lambda b: open_with_passphrase(b, PASSPHRASE)),
                          (sealed[("diagnostic_bundle", first)], lambda b: open_with_passphrase(b, PASSPHRASE)),
                          (sealed[("profile_archive", first)], lambda b: open_as_recipient(b, SUPPORT)),
                          (sealed[("diagnostic_bundle", first)], lambda b: open_as_recipient(b, STUDY))):  # fmt: skip
        try:
            attempt(blob)
        except ExportError:
            continue
        raise AssertionError("a key opened an export that is not its own")
    assert open_as_recipient(sealed[("diagnostic_bundle", first)], SUPPORT)


def sec32_no_hub_keys(tmp_path: Path):
    async def scenario(api: Api, r):
        return dict(r.runtime.directory.keys.secrets), [
            dict(zip([d[0] for d in r.runtime.stores.device.execute("SELECT * FROM device").description], row,
                     strict=True)) for row in r.runtime.stores.device.execute("SELECT * FROM device")]  # fmt: skip

    keys, device = with_api(tmp_path, scenario, worker=False)
    assert set(keys) <= {"jana.install"}  # there are no role or hub credentials
    names = " ".join(device[0]).lower() if device else ""
    for word in ("hub", "class_", "teacher", "school", "staff", "enrol", "pairing"):
        assert word not in names, word
    assert device and device[0]["install_kind"] == "family"
