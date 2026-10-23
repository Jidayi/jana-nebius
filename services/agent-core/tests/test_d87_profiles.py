"""D87: tap-to-open profiles, durable upgrades and separate consent pause/withdrawal."""

from __future__ import annotations

import asyncio
from pathlib import Path

from agent_core.config import Settings
from agent_core.store.schema_v1 import DATABASES as V1
from agent_core.store.sqlite import Migration, open_database
from api_harness import start_core, stop_core


def test_existing_profiles_upgrade_without_a_pin(tmp_path: Path) -> None:
    path = tmp_path / "device.db"
    conn, _ = open_database(path, "device", [Migration(1, V1["device"])])
    conn.execute(
        "INSERT INTO profiles_index (profile_id,kind,display_name,avatar,db_file,keystore_ref,pin_hash,created_at)"
        " VALUES ('00000000000000000000000001','student','Ada','disc','profiles/ada/learner.db','old-key',x'0102',1)"
    )
    conn.execute("INSERT INTO online_features (feature,enabled,enabled_by_role) VALUES ('downloads',1,'adult')")
    conn.close()
    conn, applied = open_database(path, "device")
    assert [m.version for m in applied] == [2]
    assert conn.execute("SELECT display_name,db_file FROM profiles_index").fetchone() == (
        "Ada",
        "profiles/ada/learner.db",
    )
    assert "pin_hash" not in {r[1] for r in conn.execute("pragma table_info(profiles_index)")}
    assert conn.execute("SELECT enabled,enabled_by_role FROM online_features").fetchone() == (1, "user")
    assert conn.execute("SELECT 1 FROM sqlite_schema WHERE name='adult_pin'").fetchone() is None
    conn.close()


def test_learner_upgrade_keeps_evidence_and_preferences(tmp_path: Path) -> None:
    path = tmp_path / "learner.db"
    conn, _ = open_database(path, "learner", [Migration(1, V1["learner"])])
    conn.execute(
        "INSERT INTO settings (key,value,source,hlc,updated_at)"
        " VALUES ('solution_policy','\"never\"','adult','1:0:dev',1)"
    )
    conn.execute(
        "INSERT INTO settings (key,value,source,hlc,updated_at) VALUES ('memory_saving','true','student','1:0:dev',1)"
    )
    conn.execute(
        "INSERT INTO events (seq,event_id,profile_id,device_id,origin_seq,hlc,type,schema_version,"
        "source,sync_class,occurred_at,recorded_at,payload)"
        " VALUES (1,'event1','profile1','device1',1,'1:0:dev','attempt','1','engine','local',1,1,'{}')"
    )
    before = conn.execute("SELECT * FROM events").fetchall()
    conn.close()
    conn, _ = open_database(path, "learner")
    assert conn.execute("SELECT * FROM events").fetchall() == before
    assert conn.execute("SELECT key,value FROM settings").fetchall() == [("memory_saving", "true")]
    assert conn.execute("SELECT 1 FROM sqlite_schema WHERE name='support_shares'").fetchone()
    conn.close()


def test_family_profile_and_consent_flow(tmp_path: Path) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, settings=Settings(consent_dpia_ref="dpia-test"), worker=False)
        try:
            reply = await r.post(
                "/v1/profiles",
                {"display_name": "Ada", "avatar": "disc", "level": "O", "subjects": ["physics"], "age_band": "13_15"},
            )
            assert reply.status_code == 200, reply.text
            profile = reply.json()["profile_id"]
            assert "has_pin" not in reply.json()
            opened = await r.post(f"/v1/profiles/{profile}/open", {})
            assert opened.status_code == 200, opened.text
            assert "pin_reset_notice" not in opened.json()
            headers = {"x-profile-token": opened.json()["profile_token"]}
            # Use Running.request to keep the launch token and a fresh idempotency key alongside the profile token.
            from test_m10a_profiles import Api

            api = Api(r)
            token = headers["x-profile-token"]
            switch = f"/v1/profiles/{profile}/consents/research_use"
            denied = await api.call("PUT", switch, {"action": "on"}, profile=token)
            assert denied.status_code == 422, denied.text
            on = await api.call("PUT", switch, {"action": "on", "guardian_agreed": True}, profile=token)
            assert on.status_code == 200 and on.json()["method"] == "in_app_guardian", on.text
            paused = await api.call("PUT", switch, {"action": "pause"}, profile=token)
            assert paused.json()["granted"] and paused.json()["paused"] and not paused.json()["effective"]
            resumed = await api.call("PUT", switch, {"action": "on"}, profile=token)
            assert resumed.json()["effective"] and not resumed.json()["paused"]
            assert (
                r.runtime.stores.device.execute(
                    "SELECT count(*) FROM outbox WHERE kind='consent_withdrawal'"
                ).fetchone()[0]
                == 0
            )
            withdrawn = await api.call("PUT", switch, {"action": "withdraw"}, profile=token)
            assert not withdrawn.json()["granted"]
            assert (
                r.runtime.stores.device.execute(
                    "SELECT count(*) FROM outbox WHERE kind='consent_withdrawal'"
                ).fetchone()[0]
                == 1
            )
            assert (await r.post("/v1/adult/unlock", {"pin": "1234"})).status_code == 404
        finally:
            await stop_core(r)

    asyncio.run(scenario())
