"""M33.a over the local API: private session history (UXS-48), the parent summary offline (UXS-33) and the alerts
route (TCH-14), each for the open profile only. Synthetic data only."""

from __future__ import annotations

import asyncio
import socket
from pathlib import Path
from typing import Any

from agent_core.api.screening import ROUTES
from api_harness import STATEMENT, start_core, stop_core
from test_a1_input_routes import _routes
from test_m10a_profiles import Api, code, student
from test_m10d_records import _session
from test_m33a_parents import proposed_errors

LOOP = asyncio.new_event_loop()
DAY_MS = 86_400_000


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


async def _open(tmp_path: Path) -> Any:
    r = await start_core(tmp_path)
    r.core.planner = r.runtime.planner  # as the app wires it (api/__main__.py)
    return r


async def _ended(api: Api, r: Any, token: str) -> str:
    """A session with one tutored turn, ended."""
    session, _ = await _session(api, r, token)
    ended = await api.call("POST", f"/v1/sessions/{session}/end", {}, profile=token)
    assert ended.status_code == 200, ended.text
    return session


def uxs48_history_private(tmp_path: Path):
    """Only the open owner profile can show its retained history; no teacher or staff route is offered."""

    async def scenario() -> None:
        r = await _open(tmp_path)
        api = Api(r)
        try:
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token_a = await api.token(a)
            session = await _ended(api, r, token_a)
            listed = await api.call("GET", "/v1/history", profile=token_a)
            assert listed.status_code == 200, listed.text
            assert proposed_errors("HistoryList", listed.json()) == []
            [entry] = listed.json()["sessions"]
            assert entry["session_id"] == session and entry["transcript"] == "kept"
            assert entry["subject"] == "physics" and entry["duration_ms"] is not None
            opened = (await api.call("GET", f"/v1/history/{session}", profile=token_a)).json()
            assert proposed_errors("HistorySession", opened) == []
            assert opened["messages"][0] == {"role": "student", "turn_id": opened["messages"][0]["turn_id"],
                                             "text": STATEMENT}  # fmt: skip
            assert any(m["role"] == "tutor" and m["part_ids"] for m in opened["messages"])
            # Another profile, and no profile at all, see none of it.
            token_b = await api.token(b)
            assert (await api.call("GET", "/v1/history", profile=token_b)).json()["sessions"] == []
            assert code(await api.call("GET", f"/v1/history/{session}", profile=token_b)) == "not_found"
            assert code(await api.call("GET", "/v1/history")) == "profile_token_expired"
            assert code(await api.call("GET", f"/v1/history/{session}")) == "profile_token_expired"
            # No sharing, sending, teacher or staff route on history.
            built = {key for key in _routes(tmp_path / "built") if "/history" in key or "share" in key.lower()}
            assert {key for key in built if "/history" in key} == {"GET /v1/history", "GET /v1/history/{session_id}"}
            assert not [key for key in built if "history" in key.lower() and "share" in key.lower()]
            for word in ("share", "send", "teacher", "staff", "export"):
                assert (await api.call("POST", f"/v1/history/{session}/{word}", {}, profile=token_a)).status_code == 404
            # During a mock sitting the list stays, but a session does not open (ASM-18).
            r.core.mock_active = lambda: True
            token_a = await api.token(a)
            assert (await api.call("GET", "/v1/history", profile=token_a)).status_code == 200
            assert code(await api.call("GET", f"/v1/history/{session}", profile=token_a)) == "tutor_locked"
        finally:
            await stop_core(r)

    run(scenario())


def uxs48_history_retention(tmp_path: Path):
    """Purged conversation content is unavailable while progress remains."""

    async def scenario() -> None:
        r = await _open(tmp_path)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = await api.token(profile)
            session = await _ended(api, r, token)
            before = (await api.call("GET", "/v1/progress", profile=token)).json()
            kept = (await api.call("GET", f"/v1/history/{session}", profile=token)).json()
            assert kept["messages"]
            events = r.core.records.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0]
            r.runtime.retention_pass(now_ms=r.core.clock_ms() + 91 * DAY_MS)  # past the transcript period
            listed = (await api.call("GET", "/v1/history", profile=token)).json()
            assert [s["transcript"] for s in listed["sessions"]] == ["purged"]
            assert listed["retention_days"] == r.core.settings.retention_transcript_days
            purged = (await api.call("GET", f"/v1/history/{session}", profile=token)).json()
            assert proposed_errors("HistorySession", purged) == []
            assert (purged["messages"], purged["parts"], purged["boards"]) == ([], {}, [])
            assert STATEMENT not in str(purged)
            after = (await api.call("GET", "/v1/progress", profile=token)).json()
            assert after["subjects"] == before["subjects"]
            assert after["time_studied"]["minutes_total"] == before["time_studied"]["minutes_total"]
            assert r.core.records.learner.conn.execute("SELECT count(*) FROM events").fetchone()[0] == events
        finally:
            await stop_core(r)

    run(scenario())


def uxs33_parent_summary_offline(tmp_path: Path):
    """The parent summary and the alerts are read with networking disabled: nothing is dialled but the loopback core.
    (The page and its PDF export are the client's: packages/ui/test/parents.test.tsx.)"""
    attempts: list[str] = []
    real_connect = socket.socket.connect

    def guarded(self: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            attempts.append(host)
            raise OSError("network disabled for this test")
        return real_connect(self, address)

    async def scenario() -> None:
        r = await _open(tmp_path)
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = await api.token(profile)
            await _ended(api, r, token)
            digest = await api.call("GET", "/v1/digests/latest", profile=token)
            assert digest.status_code == 200, digest.text
            assert proposed_errors("ParentDigest", digest.json()) == []
            alerts = await api.call("GET", "/v1/alerts", profile=token)
            assert alerts.status_code == 200 and proposed_errors("AlertList", alerts.json()) == []
            assert code(await api.call("GET", "/v1/digests/latest")) == "profile_token_expired"
        finally:
            await stop_core(r)

    socket.socket.connect = guarded  # type: ignore[method-assign]
    try:
        run(scenario())
    finally:
        socket.socket.connect = real_connect  # type: ignore[method-assign]
    assert attempts == []


def test_tch14_dismiss_route_takes_ids_only(tmp_path: Path):
    """`POST /v1/alerts/{alert_id}/dismiss` is classified as ids only, refuses a body and an unknown alert, and puts the
    open profile's alert away; another profile cannot."""
    from agent_core.engine.tutor_flows import record_wellbeing_shown

    assert "POST /v1/alerts/{alert_id}/dismiss" in ROUTES

    async def scenario() -> None:
        r = await _open(tmp_path)
        api = Api(r)
        try:
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token_a = await api.token(a)
            await _ended(api, r, token_a)
            record_wellbeing_shown(r.core.records.learner.conn, "self_harm", r.core.clock_ms())
            [alert] = (await api.call("GET", "/v1/alerts", profile=token_a)).json()["alerts"]
            assert set(alert) == {"alert_id", "kind", "severity", "created_at", "kc_id"}
            path = f"/v1/alerts/{alert['alert_id']}/dismiss"
            assert code(await api.call("POST", path, {"note": "x"}, profile=token_a)) == "validation_failed"
            token_b = await api.token(b)
            assert code(await api.call("POST", path, {}, profile=token_b)) == "not_found"
            token_a = await api.token(a)
            assert (await api.call("POST", path, {}, profile=token_a)).status_code == 204
            assert (await api.call("GET", "/v1/alerts", profile=token_a)).json() == {"alerts": []}
        finally:
            await stop_core(r)

    run(scenario())
