"""M20.f over the local API: crash reports wait for "Send this report?" and the student's own support share (OBS-17,
OBS-18, D85, D86). Crash records, students and sessions are synthetic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.contracts import errors as contract_errors
from agent_core.store import egress as egress_store
from api_harness import STATEMENT, start_core, stop_core
from net_harness import enable, layer
from test_m10a_profiles import Api, code, student
from test_m10d_deletion_export import _session_with_turn
from test_m10e_consent import _settings
from test_m20f_crashes import _store


def run(coro: Any) -> Any:
    return asyncio.new_event_loop().run_until_complete(coro)


async def _core(tmp_path: Path) -> Any:
    r = await start_core(tmp_path, settings=_settings(), worker=False)
    online = layer(tmp_path, device=r.runtime.stores.device)
    r.core.online = r.runtime.online = online
    r.core.crashes = _store(tmp_path)
    return r


def _crash(r: Any, name: str = "") -> str:
    frame = {"file": "agent_core/engine/turn.py", "line": 10, "function": "run"}
    # A log tail line that names a student never reaches the record (only diagnostic lines are kept, OBS-19); a name
    # in a record's detail is what the redaction scanner still has to refuse.
    tail = [f"hello {name}"] if name else ['{"event": "turn.start"}']
    detail = {"tool": f"hello {name}"} if name else {}
    record = r.core.crashes.record("core", "exception", [frame], error_type="RuntimeError", log_tail=tail,
                                   detail=detail)  # fmt: skip
    assert not name or name not in json.dumps(record["log_tail"])
    return str(record["crash_id"])


def test_crash_reports_wait_for_send_or_dismiss(tmp_path: Path) -> None:
    """With `crash_reports` off nothing is listed and Send answers `feature_disabled`; with it on each waiting report is
    listed exactly as it would be sent, Send queues that report, Don't send drops it, and each is decided once; a report
    the redaction scanner refuses (it names a student) is never listed. The launch token is enough (D86)."""

    async def scenario() -> None:
        r = await _core(tmp_path)
        api = Api(r)
        try:
            await api.add(student("Kwabena"))
            sent, dropped, named = _crash(r), _crash(r), _crash(r, "Kwabena")
            assert (await api.call("GET", "/v1/crash-reports")).json() == {"reports": []}  # off: nothing asks
            off = await api.call("POST", f"/v1/crash-reports/{sent}/send")
            assert off.status_code == 403 and code(off) == "feature_disabled"
            enable(r.core.online, "crash_reports")
            listed = (await api.call("GET", "/v1/crash-reports")).json()
            assert contract_errors("api/commands#/$defs/CrashReportList", listed) == []
            assert sorted(rep["crash_id"] for rep in listed["reports"]) == sorted([sent, dropped])  # not `named`
            assert (await api.call("POST", f"/v1/crash-reports/{named}/send")).status_code == 404
            assert (await api.call("POST", f"/v1/crash-reports/{sent}/upload")).status_code == 404  # no such action
            assert (await api.call("POST", f"/v1/crash-reports/{sent}/send")).status_code == 204
            assert (await api.call("POST", f"/v1/crash-reports/{dropped}/dismiss")).status_code == 204
            queued = [item for item in egress_store.pending(r.core.online.device, "crash_reports")]
            assert len(queued) == 1
            report = next(rep for rep in listed["reports"] if rep["crash_id"] == sent)
            assert json.loads(queued[0].payload) == report  # exactly the report that was shown
            assert (await api.call("GET", "/v1/crash-reports")).json() == {"reports": []}  # each decided once
            assert (await api.call("POST", f"/v1/crash-reports/{sent}/send")).status_code == 404
        finally:
            await r.core.online.stop()
            await stop_core(r)

    run(scenario())


def test_support_share_is_the_students_own_per_session_action(tmp_path: Path) -> None:
    """Only the open profile's own token records "Let support see this session", only for its own session; another
    profile's session is not found, and no token at all is refused."""

    async def scenario() -> None:
        r = await _core(tmp_path)
        api = Api(r)
        try:
            ama, kofi = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = await api.token(ama)
            session = await _session_with_turn(api, r, token, STATEMENT)
            assert (await api.call("POST", f"/v1/sessions/{session}/support-share")).status_code == 401
            shared = await api.call("POST", f"/v1/sessions/{session}/support-share", profile=token)
            assert shared.status_code == 204, shared.text
            assert (await api.call("POST", f"/v1/sessions/{session}/support-share", profile=token)).status_code == 204
            other = await api.token(kofi)
            refused = await api.call("POST", f"/v1/sessions/{session}/support-share", profile=other)
            assert refused.status_code == 404
            with r.runtime.directory.open_learner(ama) as conn:
                rows = conn.execute("SELECT session_id, included_at FROM support_shares").fetchall()
            with r.runtime.directory.open_learner(kofi) as conn:
                assert conn.execute("SELECT count(*) FROM support_shares").fetchone()[0] == 0
            assert rows == [(session.removeprefix("ses_"), None)]
        finally:
            await r.core.online.stop()
            await stop_core(r)

    run(scenario())
