"""M10.a security fixes: an idled-out profile never leaks into the next one opened, an age band edited by the student
never unlocks guardian consents, and the request ledger stays scoped to the open profile (SEC-19, DAT-14, PRV-05,
ARC-10). Synthetic profiles; no real student data."""

import asyncio
import sqlite3
from pathlib import Path

from agent_core.config import Settings
from api_harness import cli, start_core, stop_core
from test_m10a_profiles import Api, code, student

LOOP = asyncio.new_event_loop()
CANARY_TITLE = "CANARY-zz4ada-TITLE"


def run(coro):
    return LOOP.run_until_complete(coro)


def _session_body() -> dict:
    return {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
            "origin": {"kind": "ask", "ref": None}}  # fmt: skip


def _learner_dbs(data_dir: Path) -> dict[str, sqlite3.Connection]:
    out = {}
    for path in sorted(data_dir.glob("profiles/*/learner.db")):
        conn = sqlite3.connect(path)
        row = conn.execute("SELECT profile_id FROM profile").fetchone()
        out[f"prf_{row[0]}" if row else str(path)] = conn
    return out


def test_sec19_idle_lock_does_not_carry_sessions_into_next_profile(tmp_path: Path):
    """A profile token that idles out unloads its profile; opening another profile never inherits its sessions, and
    nothing of the first profile is written into the second one's learner database (SEC-19, DAT-14)."""

    async def go():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            a = await api.add(student("Ada"))
            b = await api.add(student("Bea"))
            token_a = (await api.unlock(a)).json()["profile_token"]
            reply = await api.call("POST", "/v1/sessions", _session_body(), profile=token_a)
            session = reply.json()["session_id"]
            r.core.sessions[session].meta["title"] = CANARY_TITLE
            book = r.core.directory.tokens
            base = book.clock()
            book.clock = lambda: base + r.core.settings.profile_auto_lock_s + 60
            assert code(await api.call("GET", "/v1/sessions", profile=token_a)) == "profile_token_expired"
            assert session not in r.core.sessions  # the idle lock unloaded A's sessions
            token_b = (await api.unlock(b)).json()["profile_token"]
            assert all(e.profile_id == b for e in r.core.sessions.values())
            listed = (await api.call("GET", "/v1/sessions", profile=token_b)).json()
            assert CANARY_TITLE not in str(listed)
        finally:
            await stop_core(r)
        dbs = _learner_dbs(tmp_path)
        assert (
            dbs[b].execute("SELECT count(*) FROM checkpoints WHERE state LIKE ?", (f"%{CANARY_TITLE}%",)).fetchone()[0]
            == 0
        )
        assert (
            dbs[a].execute("SELECT count(*) FROM checkpoints WHERE state LIKE ?", (f"%{CANARY_TITLE}%",)).fetchone()[0]
            == 1
        )

    run(go())


def test_sec19_unlock_forgets_every_loaded_profile(tmp_path: Path):
    """Even when no token of the previous profile survives, opening a profile unloads whatever another profile left
    in memory, judged by who owns the loaded sessions rather than by the token book (SEC-19)."""

    async def go():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            a = await api.add(student("Ada"))
            b = await api.add(student("Bea"))
            token_a = (await api.unlock(a)).json()["profile_token"]
            session = (await api.call("POST", "/v1/sessions", _session_body(), profile=token_a)).json()["session_id"]
            r.core.directory.tokens.grants.clear()  # the token vanished without a lock (expiry nobody presented)
            await api.unlock(b)
            assert session not in r.core.sessions
            assert r.core.records_profile == b
        finally:
            await stop_core(r)

    run(go())


def test_dat14_persist_refuses_another_profiles_session(tmp_path: Path):
    """The core never writes a session into a learner database that is not its profile's (DAT-14)."""

    async def go():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            a = await api.add(student("Ada"))
            b = await api.add(student("Bea"))
            token_a = (await api.unlock(a)).json()["profile_token"]
            session = (await api.call("POST", "/v1/sessions", _session_body(), profile=token_a)).json()["session_id"]
            entry = r.core.sessions[session]
            await api.unlock(b)
            entry.meta["title"] = CANARY_TITLE
            r.core.persist(entry)  # a stale reference to A's session, while B's database is open
            assert session not in r.core.store.load_all()
        finally:
            await stop_core(r)
        dbs = _learner_dbs(tmp_path)
        assert (
            dbs[b].execute("SELECT count(*) FROM checkpoints WHERE state LIKE ?", (f"%{CANARY_TITLE}%",)).fetchone()[0]
            == 0
        )

    run(go())


def _consent(reply) -> dict:
    assert reply.status_code == 200, reply.text
    return {k: reply.json()[k] for k in ("granted", "granted_by_role", "method")}


def test_prv06_corrected_age_band_self_consents(tmp_path: Path):
    """A profile whose band is corrected to 18 or over consents for itself, as a profile added as 18 or over does: the
    product owner chose to trust the corrected band (PRV-06, 2026-10-15). The change itself grants nothing; before it,
    a minor's research grant needs the guardian's agreement."""

    async def go():
        r = await start_core(tmp_path, settings=Settings(consent_dpia_ref="dpia-test"), worker=False)
        api = Api(r)
        try:
            kid = await api.add(student("Kid", "13_15"))
            token = (await api.unlock(kid)).json()["profile_token"]
            on = {"action": "on"}
            alone = await api.call("PUT", f"/v1/profiles/{kid}/consents/research_use", on, profile=token)
            assert code(alone) == "validation_failed"  # a minor's research grant needs the guardian's agreement
            raised = await api.call("PATCH", f"/v1/profiles/{kid}", {"age_band": "18_plus"}, profile=token)
            assert raised.status_code == 200
            listed = await api.call("GET", f"/v1/profiles/{kid}/consents", profile=token)
            assert not any(c.get("granted") for c in listed.json()), "the change grants nothing"
            own = await api.call("PUT", f"/v1/profiles/{kid}/consents/research_use", on, profile=token)
            assert _consent(own) == {"granted": True, "granted_by_role": "student_18_plus", "method": "in_app_notice"}
            # A profile added as 18 or over consents for itself, as PRV-06 says.
            adult = await api.add(student("Grown", "18_plus"))
            token = (await api.unlock(adult)).json()["profile_token"]
            own = await api.call("PUT", f"/v1/profiles/{adult}/consents/research_use", on, profile=token)
            assert _consent(own) == {"granted": True, "granted_by_role": "student_18_plus", "method": "in_app_notice"}
        finally:
            await stop_core(r)

    run(go())


def test_prv06_age_band_lowered_withdraws_self_grants(tmp_path: Path):
    """Moving a profile from 18 or over to a minor band withdraws every scope it granted itself (PRV-06)."""

    async def go():
        r = await start_core(tmp_path, settings=Settings(consent_dpia_ref="dpia-test"), worker=False)
        api = Api(r)
        try:
            adult = await api.add(student("Grown", "18_plus"))
            token = (await api.unlock(adult)).json()["profile_token"]
            own = await api.call("PUT", f"/v1/profiles/{adult}/consents/research_use", {"action": "on"}, profile=token)
            assert _consent(own)["granted"] is True
            lowered = await api.call("PATCH", f"/v1/profiles/{adult}", {"age_band": "16_17"}, profile=token)
            assert lowered.status_code == 200
            states = (await api.call("GET", f"/v1/profiles/{adult}/consents", profile=token)).json()
            research = next(s for s in states if s["scope"] == "research_use")
            assert research["granted"] is False
        finally:
            await stop_core(r)

    run(go())


def test_arc10_ledger_scoped_to_open_profile(tmp_path: Path):
    """Settings -> "What leaves this device" shows the device's rows and the open profile's own, never another
    profile's (ARC-10, DAT-14)."""
    from agent_core.store.egress import ledger_record

    async def go():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            a = await api.add(student("Ada"))
            b = await api.add(student("Bea"))
            device = r.core.directory.device
            now = r.core.clock_ms()
            ledger_record(device, now, "update_checks", "updates.example", 10, "update_check")
            ledger_record(device, now, "cloud_tier", "gateway.example", 111, "cloud_prompt", a)
            ledger_record(device, now, "cloud_tier", "gateway.example", 222, "cloud_prompt", b[4:])
            token_a = (await api.unlock(a)).json()["profile_token"]
            mine = (await api.call("GET", "/v1/connectivity/ledger", profile=token_a)).json()["entries"]
            assert sorted(e["bytes"] for e in mine) == [10, 111]
            launch_only = (await api.call("GET", "/v1/connectivity/ledger")).json()["entries"]
            assert [e["bytes"] for e in launch_only] == [10]
        finally:
            await stop_core(r)

    run(go())


def test_dat09_profile_delete_leaves_no_device_settings(tmp_path: Path):
    """A deleted profile leaves nothing keyed by it in the device's settings: its cloud spend, its place in the
    subscription's covered profiles and its self-raised age band (DAT-09)."""
    from agent_core.store import subscription
    from agent_core.store.egress import SPEND_KEY, DeviceSpend

    async def go():
        r = await start_core(tmp_path, worker=False)
        api = Api(r)
        try:
            a = await api.add(student("Ada"))
            b = await api.add(student("Bea"))
            device = r.core.directory.device
            DeviceSpend(device, a, "sub_x", r.core.clock_ms).add("2026-10-14", 0.5, 100)
            DeviceSpend(device, b, "sub_x", r.core.clock_ms).add("2026-10-14", 0.25, 50)
            subscription.save(device, {"subscription_id": "sub_x", "period_start": 0, "period_end": 1,
                                       "profiles": [a, b], "consent_needed": [a]}, r.core.clock_ms())  # fmt: skip
            token_a = (await api.unlock(a)).json()["profile_token"]
            await api.call("PATCH", f"/v1/profiles/{a}", {"age_band": "18_plus"}, profile=token_a)
            assert (await api.call("DELETE", f"/v1/profiles/{a}", profile=token_a)).status_code == 200
            settings = dict(device.execute("SELECT key, value FROM app_settings").fetchall())
            assert a not in str(settings) and a[4:] not in str(settings)
            assert b in settings[SPEND_KEY] and subscription.load(device)["profiles"] == [b]
        finally:
            await stop_core(r)

    run(go())
