"""M24 core/API integration; synthetic local records only."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_core.contracts import validate
from api_harness import start_core, stop_core
from test_m10a_profiles import Api, student
from test_m10d_deletion_export import _settings
from test_m10d_records import _session


def cur35_local_report(tmp_path: Path):
    async def run():
        runtime = await start_core(tmp_path, settings=_settings())
        api = Api(runtime)
        try:
            first = await api.add(student("Synthetic First"))
            second = await api.add(student("Synthetic Second"))
            token = (await api.unlock(first)).json()["profile_token"]
            session, turn = await _session(api, runtime, token)
            report = await api.call(
                "POST",
                "/v1/problem-reports",
                {
                    "session_id": session,
                    "turn_ids": [turn],
                    "category": "confusing",
                    "note": "",
                    "allow_support_export": False,
                },
                profile=token,
            )
            assert report.status_code == 200, report.text
            assert report.json()["category"] == "confusing" and not report.json()["allow_support_export"]
            assert len((await api.call("GET", "/v1/problem-reports", profile=token)).json()) == 1
            other = (await api.unlock(second)).json()["profile_token"]
            assert (await api.call("GET", "/v1/problem-reports", profile=other)).json() == []
            assert (await api.call("GET", "/v1/adult/problem-reports", profile=other)).status_code == 404
        finally:
            await stop_core(runtime)

    asyncio.run(run())


def test_ops_help_api_offline(tmp_path: Path):
    async def run():
        from agent_core.config import Settings

        runtime = await start_core(tmp_path, settings=Settings(build_stage="S2"), stage="S2")
        try:
            response = await runtime.get("/v1/help")
            assert response.status_code == 200
            validate("api/commands#/$defs/HelpReply", response.json())
            # Keys into the app's catalogues, never English text from the core (OPS-23, LOC-01, D93).
            usb = next(a for a in response.json()["articles"] if a["id"] == "usb")
            assert usb["title_key"] == "help.article.usb.title" and "title" not in usb
            sections = await runtime.get("/v1/settings/sections")
            assert sections.status_code == 200 and len(sections.json()["sections"]) == 12
            validate("api/commands#/$defs/SettingsSections", sections.json())
        finally:
            await stop_core(runtime)

    asyncio.run(run())


def test_ops_catalogue_import_defers_safety_to_next_turn(tmp_path: Path):
    from agent_core.api.packs import PackDesk
    from agent_core.config import Environment
    from agent_core.config.operations import DevicePolicy
    from signing_service.hierarchy import dev_signer, dev_trust

    async def run():
        runtime = await start_core(tmp_path, worker=False)
        try:
            policy = DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust())
            runtime.core.pack_desk = PackDesk(
                tmp_path,
                Environment.DEV,
                "1.0.0",
                lambda _: None,
                trust=dev_trust(),
                channel="stable",
                operations=policy,
            )
            at = "2026-10-16T00:00:00Z"
            signed = dev_signer().sign(
                "safety_configuration",
                {
                    "sequence": 1,
                    "channel": "stable",
                    "issued_at": at,
                    "entries": [
                        {
                            "entry_id": "entry_synthetic",
                            "target_kind": "tool",
                            "target": "math_solve",
                            "action": "disable",
                            "reason_code": "synthetic",
                            "incident_id": "inc_synthetic",
                            "lift_when": None,
                        }
                    ],
                },
                now=at,
            )
            reply = await runtime.post("/v1/operations/catalogue", {"safety_configuration": signed})
            assert reply.status_code == 200 and reply.json()["safety_adopted"]
            validate("api/commands#/$defs/CatalogueImportReply", reply.json())
            assert policy.decision("tool", "math_solve").action == "allow"
            policy.turn_boundary({})
            assert policy.decision("tool", "math_solve").action == "disable"
        finally:
            await stop_core(runtime)

    asyncio.run(run())


def test_ops_damaged_pack_still_emits_failure(tmp_path: Path):
    import pytest
    from agent_core.api.packs import PackDesk
    from agent_core.config import Environment
    from agent_core.config.operations import DevicePolicy
    from agent_core.store.packs import PackRejectedError
    from signing_service.hierarchy import dev_trust

    events = []
    desk = PackDesk(
        tmp_path,
        Environment.DEV,
        "1.0.0",
        events.append,
        trust=dev_trust(),
        operations=DevicePolicy(tmp_path, Environment.DEV, "stable", "1.0.0", dev_trust()),
    )
    damaged = tmp_path / "bad.janapack"
    damaged.write_bytes(b"synthetic damaged pack")
    with pytest.raises(PackRejectedError):
        desk.install_source({"path": str(damaged)}, "job_synthetic")
    assert events[-1]["state"] == "failed"
