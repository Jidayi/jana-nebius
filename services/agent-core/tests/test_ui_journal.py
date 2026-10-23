"""Synthetic UI cache: real local profile API, ownership, corruption and close cleanup."""

from __future__ import annotations

import asyncio
import copy
from pathlib import Path

import pytest
from agent_core.contracts import errors
from api_harness import cli, start_core, stop_core
from test_m10a_profiles import Api, student


def test_journal_cache_api_ownership_bounds_corruption_and_close(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            a, b = await api.add(student("Cache A")), await api.add(student("Cache B"))
            token = await api.token(a)
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
                profile=token,
            )
            sid = created.json()["session_id"]
            path = f"/v1/sessions/{sid}/journal"
            empty = await api.call("GET", path, profile=token)
            assert empty.json() == {"snapshot": None, "envelopes": []}
            snapshot = (await api.call("GET", f"/v1/sessions/{sid}/snapshot", profile=token)).json()
            body = {"snapshot": snapshot, "envelopes": []}
            saved = await api.call("PUT", path, body, profile=token)
            assert saved.status_code == 204, saved.text
            assert errors("api/commands#/$defs/ClientJournal", body) == []
            assert (await api.call("GET", path, profile=token)).json() == body
            files = list(tmp_path.rglob(f"{sid}.json"))
            assert len(files) == 1 and files[0].parent.name == "ui-journals"
            wrong = copy.deepcopy(body)
            wrong["snapshot"]["session"]["session_id"] = "ses_" + "0" * 26
            assert (await api.call("PUT", path, wrong, profile=token)).status_code == 422
            wrong = copy.deepcopy(body)
            wrong["snapshot"]["messages"] = [{}] * 51
            assert (await api.call("PUT", path, wrong, profile=token)).status_code == 422
            assert (await api.call("GET", path)).status_code == 401
            # A corrupt disposable file cannot block opening the authoritative snapshot.
            files[0].write_text("{broken")
            assert (await api.call("GET", path, profile=token)).json() == empty.json()
            assert not files[0].exists()
            assert (await api.call("PUT", path, body, profile=token)).status_code == 204
            # Switching clears the previous profile's cache, and the new token cannot read its session.
            other = await api.token(b)
            assert not files[0].exists()
            assert (await api.call("GET", path, profile=other)).status_code == 404
            token = await api.token(a)
            assert (await api.call("GET", path, profile=token)).json() == empty.json()
            assert (await api.call("PUT", path, body, profile=token)).status_code == 204
            assert (await api.call("POST", f"/v1/profiles/{a}/close", {}, profile=token)).status_code == 204
            assert not files[0].exists()
        finally:
            await stop_core(r)

    asyncio.run(scenario())


@pytest.mark.parametrize("active", [True, False])
def uia06_journal_deleted_with_profile(tmp_path: Path, active: bool) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, worker=False)
        try:
            api = Api(r)
            profiles = [await api.add(student("Erase cache")), await api.add(student("Keep cache"))]
            paths: list[Path] = []
            records: list[bytes] = []
            for index, profile in enumerate(profiles):
                token = await api.token(profile)
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
                    profile=token,
                )
                sid = created.json()["session_id"]
                snapshot = (await api.call("GET", f"/v1/sessions/{sid}/snapshot", profile=token)).json()
                snapshot["session"]["title"] = f"JOURNAL-{'ERASE' if index == 0 else 'KEEP'}-CANARY"
                assert (
                    await api.call(
                        "PUT",
                        f"/v1/sessions/{sid}/journal",
                        {
                            "snapshot": snapshot,
                            "envelopes": [],
                        },
                        profile=token,
                    )
                ).status_code == 204
                path = next(tmp_path.rglob(f"{sid}.json"))
                paths.append(path)
                records.append(path.read_bytes())
            current = profiles[0] if active else profiles[1]
            token = await api.token(current)
            # Older crash leftovers must be erased too; the other profile's cache is outside this deletion.
            for path, raw in zip(paths, records, strict=True):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            if not active:
                refused = await api.call("DELETE", f"/v1/profiles/{profiles[0]}", profile=token)
                assert refused.status_code == 404
                assert paths[0].exists()  # another profile's token cannot delete it
                token = await api.token(profiles[0])
                for path, raw in zip(paths, records, strict=True):
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(raw)
            deleted = await api.call("DELETE", f"/v1/profiles/{profiles[0]}", profile=token)
            assert deleted.status_code == 200 and deleted.json()["deleted"] is True, deleted.text
            assert not paths[0].exists()
            assert paths[1].read_bytes() == records[1]
            assert not (tmp_path / "profiles" / profiles[0][4:]).exists()
            files = (path for path in tmp_path.rglob("*") if path.is_file())
            assert not any(b"JOURNAL-ERASE-CANARY" in path.read_bytes() for path in files)
        finally:
            await stop_core(r)

    asyncio.run(scenario())
