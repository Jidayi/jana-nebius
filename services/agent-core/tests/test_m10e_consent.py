"""M10.e: consent per scope, who may consent, online feature switches and notice versions (PRV-05, PRV-06, PRV-12,
API-28, ARC-11, DAT-18). Synthetic profiles; the DPIA reference is a test value."""

import asyncio
import json
import re
import socket
from pathlib import Path

from agent_core.config import Settings
from agent_core.store import consents as store
from api_harness import STATEMENT, ask, cli, start_core, stop_core
from jana_tools import REPO_ROOT
from test_m10a_profiles import Api, code, student

LOOP = asyncio.new_event_loop()
NOTICE = "2026-10.d1"


def run(coro):
    return LOOP.run_until_complete(coro)


def _settings(dpia: str = "dpia-test-1") -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), consent_dpia_ref=dpia)


def with_api(tmp_path: Path, scenario, settings: Settings | None = None, worker: bool = False):
    async def go():
        r = await start_core(tmp_path, settings=settings or _settings(), worker=worker)
        try:
            return await scenario(Api(r), r)
        finally:
            await stop_core(r)

    return run(go())


async def _consents(api: Api, profile: str, token: str) -> dict:
    return {c["scope"]: c for c in (await api.call("GET", f"/v1/profiles/{profile}/consents", profile=token)).json()}


def _checkout(r, profile: str, scope: str = "cloud_tier") -> None:
    """A prior checkout's guardian grant; real signed checkout API coverage lives in test_m19b_api."""
    with r.runtime.directory.open_learner(profile) as conn:
        store.grant(conn, scope, "guardian", "Parent", NOTICE, r.core.settings.consent_dpia_ref, r.core.clock_ms())


# --- API-28, PRV-05, PRV-06 ------------------------------------------------------------------------------------------


def api28_consent_switch_per_profile(tmp_path: Path):
    async def scenario(api: Api, r):
        minor = await api.add(student("Ama"))
        grown = await api.add(student("Esi", age_band="18_plus"))
        token = (await api.unlock(minor)).json()["profile_token"]
        for scope in store.shipped_scopes():
            alone = await api.call("PUT", f"/v1/profiles/{minor}/consents/{scope}",
                                   {"action": "on", "notice_version": NOTICE}, profile=token)  # fmt: skip
            expected = "validation_failed" if scope == "research_use" else "guardian_consent_required"
            assert code(alone) == expected, scope
            if scope != "research_use":
                _checkout(r, minor, scope)
            granted = await api.call(
                "PUT",
                f"/v1/profiles/{minor}/consents/{scope}",
                {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
                profile=token,
            )
            assert granted.status_code == 200 and granted.json()["granted_by_role"] == "guardian", granted.text
            withdrawn = await api.call("PUT", f"/v1/profiles/{minor}/consents/{scope}", {"action": "withdraw"},
                                       profile=token)  # fmt: skip
            assert withdrawn.json()["granted"] is False
        telemetry = await api.call(
            "PUT",
            f"/v1/profiles/{minor}/consents/telemetry",
            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
            profile=token,
        )
        assert telemetry.status_code == 422 and code(telemetry) == "scope_not_profile"
        token = (await api.unlock(grown)).json()["profile_token"]
        own = await api.call(
            "PUT",
            f"/v1/profiles/{grown}/consents/cloud_tier",
            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
            profile=token,
        )
        assert own.status_code == 200 and own.json()["granted_by_role"] == "student_18_plus"
        await api.call("PUT", f"/v1/profiles/{grown}/consents/cloud_tier", {"action": "withdraw"}, profile=token)
        # The device switch writes one row per profile under 18 and none for the 18+ profile.
        assert (await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": True}})
                ).status_code == 200  # fmt: skip
        rows = {}
        for profile in (minor, grown):
            with r.runtime.directory.open_learner(profile) as conn:
                rows[profile] = conn.execute("SELECT granted_by_role FROM consents WHERE scope = 'cloud_tier' AND"
                                             " withdrawn_at IS NULL").fetchall()  # fmt: skip
        assert rows[minor] == [] and rows[grown] == [], "a device switch does not mint profile consent"
        state = (await api.call("GET", "/v1/connectivity")).json()
        assert state["features"]["cloud_tier"]["enabled"] is True

    with_api(tmp_path, scenario)


def prv06_minor_cannot_self_consent(tmp_path: Path):
    async def scenario(api: Api, r):
        for band in ("under_13", "13_15", "16_17"):
            profile = await api.add(student(f"Kid {band}", age_band=band))
            token = (await api.unlock(profile)).json()["profile_token"]
            for scope in store.shipped_scopes():
                reply = await api.call("PUT", f"/v1/profiles/{profile}/consents/{scope}",
                                       {"action": "on", "notice_version": NOTICE}, profile=token)  # fmt: skip
                assert code(reply) == (
                    "validation_failed" if scope == "research_use" else "guardian_consent_required"
                ), (
                    band,
                    scope,
                )
            assert all(not c["granted"] for c in (await _consents(api, profile, token)).values())
        # The removed school route does not exist: no consent method other than adult attestation is accepted.
        assert "school" not in json.dumps(json.loads((REPO_ROOT / "services" / "agent-core" / "agent_core" / "contracts"
                                                      / "schemas" / "api" / "commands.schema.json").read_text())
                                          ["$defs"]["ConsentSwitch"])  # fmt: skip

    with_api(tmp_path, scenario)


def prv05_scopes_independent(tmp_path: Path):
    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        scopes = store.shipped_scopes()
        for scope in scopes:
            if scope != "research_use":
                _checkout(r, profile, scope)
            await api.call(
                "PUT",
                f"/v1/profiles/{profile}/consents/{scope}",
                {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
                profile=token,
            )
            granted = {s for s, c in (await _consents(api, profile, token)).items() if c["granted"]}
            assert granted == set(scopes[: scopes.index(scope) + 1]), scope
        for scope in scopes:
            await api.call("PUT", f"/v1/profiles/{profile}/consents/{scope}", {"action": "withdraw"}, profile=token)
            granted = {s for s, c in (await _consents(api, profile, token)).items() if c["granted"]}
            assert granted == set(scopes[scopes.index(scope) + 1 :]), scope
        # With every scope refused the tutor still works.
        body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                "origin": {"kind": "ask", "ref": None}}  # fmt: skip
        session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
        assert (await api.call("POST", f"/v1/sessions/{session}/turns", ask(STATEMENT), profile=token)
                ).status_code == 202  # fmt: skip
        await r.wait_idle(session, timeout=60)
        snapshot = (await api.call("GET", f"/v1/sessions/{session}/snapshot", profile=token)).json()
        assert any(m["role"] == "tutor" and m["status"] == "complete" for m in snapshot["messages"])

    with_api(tmp_path, scenario, worker=True)


def _outbox(r) -> list:
    return r.runtime.stores.device.execute(
        "SELECT kind, feature, destination, profile_id, delivered_at FROM outbox ORDER BY created_at"
    ).fetchall()


def prv05_pause_is_not_withdrawal(tmp_path: Path):
    """A pause stops processing at once and is undone from the profile with no guardian step; only a withdrawal sends
    anything to a destination (D87)."""

    async def scenario(api: Api, r):
        minor = await api.add(student("Ama"))
        token = (await api.unlock(minor)).json()["profile_token"]
        await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use",
                       {"action": "on", "guardian_agreed": True, "notice_version": NOTICE}, profile=token)  # fmt: skip
        paused = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "pause"},
                                profile=token)  # fmt: skip
        with r.runtime.directory.open_learner(minor) as conn:
            in_force = next(c for c in store.states(conn, set()) if c["scope"] == "research_use")["effective"]
        folder = tmp_path / "usb"
        folder.mkdir()
        export = await api.call("POST", "/v1/exports", {"kind": "research_export", "profile_ids": [minor],
                                                        "destination": {"kind": "file", "path": str(folder)}},
                                profile=token)  # fmt: skip
        after_pause = _outbox(r)
        resumed = await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "on"},
                                 profile=token)  # fmt: skip
        await api.call("PUT", f"/v1/profiles/{minor}/consents/research_use", {"action": "withdraw"}, profile=token)
        return paused.json(), in_force, export, after_pause, resumed.json(), _outbox(r), minor

    paused, in_force, export, after_pause, resumed, after_withdrawal, minor = with_api(tmp_path, scenario)
    assert paused["paused"] and paused["granted"] and not paused["effective"] and not in_force
    assert export.status_code >= 400  # nothing is processed under a paused consent
    assert after_pause == []  # a pause sends nothing
    assert resumed["effective"] and resumed["granted_by_role"] == "guardian"  # the same grant, no guardian step
    assert [(k, d, p) for k, _, d, p, _ in after_withdrawal] == [("consent_withdrawal", "research_use", minor[4:])]


def prv05_withdrawal_delivered(tmp_path: Path):
    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": True}})
        _checkout(r, profile)
        await api.call(
            "PUT",
            f"/v1/profiles/{profile}/consents/research_use",
            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
            profile=token,
        )
        await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": False}})
        await api.call("PUT", f"/v1/profiles/{profile}/consents/cloud_tier", {"action": "withdraw"}, profile=token)
        await api.call("PUT", f"/v1/profiles/{profile}/consents/research_use", {"action": "withdraw"}, profile=token)
        return profile, _outbox(r), await _consents(api, profile, token)

    profile, outbox, consents = with_api(tmp_path, scenario)
    assert [(k, d, p) for k, _, d, p, _ in outbox] == [
        ("consent_withdrawal", "cloud_tier", profile[4:]),
        ("consent_withdrawal", "research_use", profile[4:]),
    ]
    assert all(row[4] is None for row in outbox)  # pending until the outbox delivers it (DAT-11)
    assert not consents["cloud_tier"]["granted"] and not consents["research_use"]["granted"]


def test_no_consent_without_a_dpia_reference(tmp_path: Path):
    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        refused = await api.call(
            "PUT",
            f"/v1/profiles/{profile}/consents/cloud_tier",
            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
            profile=token,
        )
        switch = await api.call("PATCH", "/v1/connectivity", {"features": {"telemetry": True}})
        downloads = await api.call("PATCH", "/v1/connectivity", {"features": {"downloads": True}})
        return refused, switch, downloads

    refused, switch, downloads = with_api(tmp_path, scenario, settings=_settings(dpia=""))
    assert code(refused) == "feature_disabled" and code(switch) == "feature_disabled"
    assert downloads.status_code == 200  # downloads carry no consent scope


# --- PRV-12 ----------------------------------------------------------------------------------------------------------


def prv12_notice_versions_resolve(tmp_path: Path):
    shipped = store.load_notices(REPO_ROOT / "content" / "agent" / "notices" / "notices.json")
    assert set(store.shipped_scopes()) | set(store.DEVICE_SCOPES) <= set(shipped)

    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        unknown = await api.call(
            "PUT",
            f"/v1/profiles/{profile}/consents/research_use",
            {"action": "on", "guardian_agreed": True, "notice_version": "1999-01"},
            profile=token,
        )
        assert code(unknown) == "validation_failed"
        await api.call(
            "PATCH",
            "/v1/connectivity",
            {"features": {"cloud_tier": True, "telemetry": True, "crash_reports": True}},
        )
        await api.call(
            "PUT",
            f"/v1/profiles/{profile}/consents/research_use",
            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
            profile=token,
        )
        with r.runtime.directory.open_learner(profile) as conn:
            rows = conn.execute("SELECT scope, notice_version FROM consents").fetchall()
        rows += r.runtime.stores.device.execute("SELECT scope, notice_version FROM device_consents").fetchall()
        return rows

    rows = with_api(tmp_path, scenario)
    assert len(rows) == 3  # device switches record device consent; they do not record paid profile consent
    for scope, version in rows:
        assert version in shipped[scope], (scope, version)


# --- DAT-18 ----------------------------------------------------------------------------------------------------------


def dat18_matches_arc07_features():
    from agent_core.store.generated.schema import DATABASES

    spec = (REPO_ROOT / "docs" / "specification" / "architecture.md").read_text()
    table = spec.split("\nTABLE ARC-07a", 1)[1].split("\n\n", 2)[1]
    arc07 = {m[0]: m[1] for m in re.findall(r"^\| `([a-z_]+)`[^|]*\| (S\d)", table, re.M)}
    data_model = (REPO_ROOT / "docs" / "specification" / "data-model.md").read_text()
    dat18 = set(re.findall(r"\| `([a-z_]+)`(?:, `[a-z_]+`)? \|", data_model.split("TABLE DAT-18a", 1)[1]
                           .split("Acceptance:", 1)[0]))  # fmt: skip
    check = DATABASES["device"].split("CREATE TABLE online_features", 1)[1].split(")),", 1)[0]
    stored = set(re.findall(r"'([a-z_]+)'", check))
    assert arc07 == store.FEATURES and stored == set(arc07)
    assert {f for f in dat18 if f in stored} == {f for f in arc07 if f not in ("downloads", "update_checks")} | (
        {"downloads"} & dat18)  # fmt: skip


def dat18_zero_egress_by_default(tmp_path: Path):
    """Every online feature off: a scripted session (several turns, a switch of profile, settings and an export) makes
    no outbound connection."""
    attempts: list = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            attempts.append(host)
            raise OSError("network disabled for this test")
        return real_connect(self, address)

    async def scenario(api: Api, r):
        profile = await api.add(student("Ama"))
        token = (await api.unlock(profile)).json()["profile_token"]
        body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
                "origin": {"kind": "ask", "ref": None}}  # fmt: skip
        session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
        for text, intent in (
            (STATEMENT, "ask"),
            ("I'm stuck", "stuck"),
            ("s = 20 m", "answer"),
            ("s = 10 m", "answer"),
        ):
            await api.call("POST", f"/v1/sessions/{session}/turns", ask(text, intent), profile=token)
            await r.wait_idle(session, timeout=60)
        await api.call("PATCH", f"/v1/profiles/{profile}/settings", {"text_scale": 1.25}, profile=token)
        assert all(not f["enabled"] for f in (await api.call("GET", "/v1/connectivity")).json()["features"].values())

    socket.socket.connect = guarded
    try:
        with_api(tmp_path, scenario, worker=True)
    finally:
        socket.socket.connect = real_connect
    assert attempts == []
