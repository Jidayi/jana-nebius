"""M10.d: saved questions and problem reports, and the data rights offline (API-28, PRV-10). Synthetic data only."""

import asyncio
import socket
from pathlib import Path

from agent_core.contracts.api.endpoints import ENDPOINTS_BY_KEY
from agent_core.memory.write import NOTES_WRITER
from agent_core.store.ids import new_ulid
from api_harness import STATEMENT, ask, cli, start_core, stop_core
from test_m10a_profiles import Api, code, student
from test_m10d_deletion_export import PASSPHRASE, _settings

LOOP = asyncio.new_event_loop()


def run(coro):
    return LOOP.run_until_complete(coro)


async def _session(api: Api, r, token: str) -> tuple[str, str]:
    body = {"client_session_id": cli(), "mode": "guided", "subject": "physics", "level": "O",
            "origin": {"kind": "ask", "ref": None}}  # fmt: skip
    session = (await api.call("POST", "/v1/sessions", body, profile=token)).json()["session_id"]
    await api.call("POST", f"/v1/sessions/{session}/turns", ask(STATEMENT), profile=token)
    for _ in range(600):
        entry = r.core.sessions.get(session)
        if entry is not None and (entry.task is None or entry.task.done()):
            break
        await asyncio.sleep(0.05)
    snapshot = (await api.call("GET", f"/v1/sessions/{session}/snapshot", profile=token)).json()
    turn = next(m["turn_id"] for m in snapshot["messages"] if m["role"] == "tutor")
    return session, turn


def api28_saved_lists_lifecycle(tmp_path: Path):
    async def first():
        r = await start_core(tmp_path, settings=_settings())
        api = Api(r)
        try:
            a, b = await api.add(student("Ama")), await api.add(student("Kofi"))
            token = (await api.unlock(a)).json()["profile_token"]
            session, turn = await _session(api, r, token)
            saved = await api.call("POST", "/v1/saved-questions", {"session_id": session, "turn_id": turn},
                                   profile=token)  # fmt: skip
            assert saved.status_code == 200, saved.text
            snapshot = saved.json()["snapshot"]
            assert snapshot["problem"] == STATEMENT and snapshot["reason"] == "student_requested"
            forged = await api.call("POST", "/v1/saved-questions", {"session_id": session, "turn_id": turn,
                                                                    "board": [{"latex": "x", "reason": "y"}]},
                                    profile=token)  # fmt: skip
            assert code(forged) == "validation_failed"  # the client never supplies the snapshot
            report = await api.call(
                "POST",
                "/v1/problem-reports",
                {
                    "session_id": session,
                    "turn_ids": [turn],
                    "category": "confusing",
                    "note": "odd step",
                    "allow_support_export": False,
                },
                profile=token,
            )
            assert report.status_code == 200, report.text
            sorted_ = await api.call("PATCH", f"/v1/saved-questions/{saved.json()['question_id']}",
                                     {"status": "sorted"}, profile=token)  # fmt: skip
            assert sorted_.json()["status"] == "sorted"
            adult_view = await api.call("GET", "/v1/adult/problem-reports", headers={"x-adult-token": "obsolete"})
            assert adult_view.status_code == 404 and "odd step" not in adult_view.text  # no adult route (D86)
            token_b = (await api.unlock(b)).json()["profile_token"]
            assert (await api.call("GET", "/v1/saved-questions", profile=token_b)).json() == []
            assert (await api.call("GET", "/v1/problem-reports", profile=token_b)).json() == []
            assert (await api.call("DELETE", f"/v1/saved-questions/{saved.json()['question_id']}",
                                   profile=token_b)).status_code == 404  # fmt: skip
            return a, saved.json()["question_id"]
        finally:
            await stop_core(r)

    profile, question = run(first())

    async def after_restart():
        r = await start_core(tmp_path, settings=_settings())
        api = Api(r)
        try:
            assert (await api.call("POST", "/v1/adult/unlock", {"pin": "24680"})).status_code == 404
            token = (await api.unlock(profile)).json()["profile_token"]
            kept = (await api.call("GET", "/v1/saved-questions", profile=token)).json()
            reports = (await api.call("GET", "/v1/problem-reports", profile=token)).json()
            r.runtime.retention_pass(now_ms=r.core.clock_ms() + 91 * 86_400_000)  # past the retention period
            after_retention = (await api.call("GET", "/v1/saved-questions", profile=token)).json()
            await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)
            return kept, reports, after_retention
        finally:
            await stop_core(r)

    kept, reports, after_retention = run(after_restart())
    assert [q["question_id"] for q in kept] == [question] and len(reports) == 1  # both survive a restart
    assert after_retention == []
    assert not (tmp_path / "profiles" / profile[4:]).exists()  # and go with the profile
    assert not [k for k in ENDPOINTS_BY_KEY if "saved-questions" in k and ("send" in k or "share" in k)]


def prv10_rights_offline(tmp_path: Path):
    attempts: list = []
    real_connect = socket.socket.connect

    def guarded(self, address):
        host = address[0] if isinstance(address, tuple) else address
        if isinstance(host, str) and host not in ("127.0.0.1", "::1", "localhost") and not host.startswith("/"):
            attempts.append(host)
            raise OSError("network disabled for this test")
        return real_connect(self, address)

    async def scenario():
        r = await start_core(tmp_path, settings=_settings())
        api = Api(r)
        try:
            profile = await api.add(student("Ama"))
            token = (await api.unlock(profile)).json()["profile_token"]
            session, _ = await _session(api, r, token)
            r.core.records.learner.record("note_written", {"note_id": new_ulid(), "text": "Mixes up"
                                                           " distance and displacement", "status": "active",
                                                           "source_event_ids": [new_ulid()]},
                                          source="reflector", writer=NOTES_WRITER)  # fmt: skip
            # Access
            assert (await api.call("GET", f"/v1/profiles/{profile}/settings", profile=token)).status_code == 200
            assert (await api.call("GET", f"/v1/profiles/{profile}/consents", profile=token)).status_code == 200
            notes = (await api.call("GET", f"/v1/profiles/{profile}/memory", profile=token)).json()["notes"]
            assert [n["text"] for n in notes] == ["Mixes up distance and displacement"]
            # Correction
            assert (await api.call("PATCH", f"/v1/profiles/{profile}/settings", {"memory_saving": False},
                                   profile=token)).status_code == 200  # fmt: skip
            assert (await api.call("DELETE", f"/v1/memory/{notes[0]['note_id']}", profile=token)).status_code == 204
            assert (await api.call("GET", f"/v1/profiles/{profile}/memory", profile=token)).json()["notes"] == []
            # Portability
            folder = tmp_path / "usb"
            folder.mkdir()
            exported = await api.call("POST", "/v1/exports", {"kind": "profile_archive", "profile_ids": [profile],
                                                              "passphrase": PASSPHRASE,
                                                              "destination": {"kind": "file", "path": str(folder)}},
                                      profile=token)  # fmt: skip
            assert exported.status_code == 202 and list(folder.iterdir())
            # Deletion
            assert (await api.call("DELETE", f"/v1/profiles/{profile}", profile=token)).status_code == 200
            assert session
        finally:
            await stop_core(r)

    socket.socket.connect = guarded
    try:
        run(scenario())
    finally:
        socket.socket.connect = real_connect
    assert attempts == []
