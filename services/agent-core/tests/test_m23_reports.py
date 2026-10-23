"""The local report API and explicit diagnostic export (synthetic profiles)."""

from __future__ import annotations

import asyncio
import json
import socket

from agent_core.store.exports import open_as_recipient
from api_harness import start_core, stop_core
from test_m10a_profiles import Api, student
from test_m10d_deletion_export import SUPPORT, _settings
from test_m10d_records import _session


def prv22_report_local_only(tmp_path, monkeypatch):
    async def scenario():
        runtime = await start_core(tmp_path, settings=_settings())
        api = Api(runtime)
        try:
            profile = await api.add(student("Synthetic learner"))
            token = await api.token(profile)
            session, turn = await _session(api, runtime, token)

            def no_network(*args, **kwargs):
                raise AssertionError("saving a problem report opened a network connection")

            monkeypatch.setattr(socket.socket, "connect", no_network)
            body = {
                "session_id": session,
                "turn_ids": [turn],
                "category": "unsafe",
                "note": "LOCAL-CANARY",
                "allow_support_export": False,
            }
            saved = await api.call("POST", "/v1/problem-reports", body, profile=token)
            assert saved.status_code == 200, saved.text
            assert saved.json()["turn_ids"] == [turn]
            assert (await api.call("GET", "/v1/problem-reports", profile=token)).json() == [saved.json()]
            assert runtime.runtime.stores.device.execute("SELECT count(*) FROM outbox").fetchone()[0] == 0
        finally:
            await stop_core(runtime)

    asyncio.run(scenario())


def uxs44_report_stays_local(tmp_path, monkeypatch):
    prv22_report_local_only(tmp_path, monkeypatch)


def test_support_export_requires_report_authorization(tmp_path):
    async def scenario():
        runtime = await start_core(tmp_path, settings=_settings())
        api = Api(runtime)
        try:
            profile = await api.add(student("Synthetic learner"))
            token = await api.token(profile)
            session, turn = await _session(api, runtime, token)
            ids = []
            for allowed in (False, True):
                body = {
                    "session_id": session,
                    "turn_ids": [turn],
                    "category": "incorrect",
                    "note": "ALLOWED-CANARY" if allowed else "PRIVATE-CANARY",
                    "allow_support_export": allowed,
                }
                saved = await api.call("POST", "/v1/problem-reports", body, profile=token)
                assert saved.status_code == 200, saved.text
                ids.append(saved.json()["report_id"])
            base = {
                "kind": "diagnostic_bundle",
                "profile_ids": [profile],
                "destination": {"kind": "file", "path": str(tmp_path)},
            }
            denied = await api.call("POST", "/v1/exports", {**base, "report_ids": ids}, profile=token)
            assert denied.status_code == 422
            response = await api.call("POST", "/v1/exports", {**base, "report_ids": [ids[1]]}, profile=token)
            assert response.status_code == 202, response.text
            blob = next(tmp_path.glob("*.janadiag")).read_bytes()
            value = json.loads(open_as_recipient(blob, SUPPORT))
            assert value["problem_reports"][0]["turn_ids"] == [turn]
            assert "ALLOWED-CANARY" in json.dumps(value) and "PRIVATE-CANARY" not in json.dumps(value)
            assert "conversations" not in value
        finally:
            await stop_core(runtime)

    asyncio.run(scenario())


def prv21_safety_config_disables_feature(tmp_path):
    from agent_core.config.environments import Environment
    from agent_core.config.operations import DevicePolicy
    from net_harness import enable, layer
    from signing_service.hierarchy import dev_signer, dev_trust

    online = layer(tmp_path)
    enable(online, "telemetry")
    trust = [dev_trust()]
    # The device's one reader of the signed safety configuration (OPS-10, D92), as the USB kit reaches it.
    config = DevicePolicy(tmp_path, Environment.DEV, "pilot", "1.0.0", lambda: trust[0])
    unsigned = {
        "sequence": 1,
        "channel": "pilot",
        "issued_at": "2026-10-16T00:00:00Z",
        "entries": [
            {
                "entry_id": "synthetic-entry",
                "target_kind": "online_feature",
                "target": "telemetry",
                "action": "force_off",
                "reason_code": "unsafe",
                "incident_id": "INC-1",
                "lift_when": None,
            }
        ],
    }
    document = dev_signer().sign("safety_configuration", unsigned)
    usb = tmp_path / "usb"
    usb.mkdir()
    (usb / "safety-configuration.json").write_text(json.dumps(document))
    assert config.adopt_folder(usb)["safety"]
    config.apply_online(online)
    assert "telemetry" in online.features_on()  # accepted, applied at the next turn boundary
    config.turn_boundary({})
    config.apply_online(online)
    assert "telemetry" not in online.features_on()
    enable(online, "telemetry")
    assert "telemetry" not in online.features_on()
    changed = {**document, "sequence": 2}
    (usb / "safety-configuration.json").write_text(json.dumps(changed))
    assert not config.adopt_folder(usb)["safety"]
    assert not config.adopt_safety(document)
    # Revoking the signing key never discards a restriction already accepted.
    trust[0] = trust[0].with_revoked([dev_signer().key_id])
    config.turn_boundary({})
    config.apply_online(online)
    assert "telemetry" not in online.features_on()
    asyncio.run(online.stop())


def test_research_export_checks_assent_and_school_approval(tmp_path):
    from agent_core.contracts import errors
    from test_m10d_deletion_export import STUDY

    async def scenario():
        runtime = await start_core(tmp_path, settings=_settings())
        api = Api(runtime)
        try:
            profile = await api.add(student("PRIVATE-CANARY"))
            token = await api.token(profile)
            with runtime.runtime.directory.open_learner(profile) as conn:
                conn.execute(
                    "INSERT INTO consents (consent_id, scope, granted_by_role, granted_by_label, "
                    "notice_version, dpia_ref, method, granted_at) VALUES "
                    "('synthetic', 'research_use', 'guardian', 'Synthetic guardian', 'v1', "
                    "'test-dpia', 'in_app_guardian', 1)"
                )
            body = {
                "kind": "research_export",
                "profile_ids": [profile],
                "destination": {"kind": "file", "path": str(tmp_path)},
            }
            denied = await api.call("POST", "/v1/exports", body, profile=token)
            assert denied.status_code == 422
            approval = {
                "student_assent": True,
                "school_approval_ref": "synthetic-school-approval",
                "protocol_ref": "synthetic-registered-protocol",
            }
            for bad in ({**approval, "student_assent": False}, {**approval, "school_approval_ref": ""}):
                response = await api.call("POST", "/v1/exports", {**body, "research_approval": bad}, profile=token)
                assert response.status_code == 422
            assert not errors("api/commands#/$defs/CreateExport", {**body, "research_approval": approval})
            response = await api.call("POST", "/v1/exports", {**body, "research_approval": approval}, profile=token)
            assert response.status_code == 202, response.text
            exported = json.loads(open_as_recipient(next(tmp_path.glob("*.janaresearch")).read_bytes(), STUDY))
            assert "PRIVATE-CANARY" not in json.dumps(exported)
        finally:
            await stop_core(runtime)

    asyncio.run(scenario())


def test_pilot_profile_needs_registered_protocol_clearance(tmp_path):
    import pytest
    from agent_core.config.environments import Environment
    from agent_core.config.pilot import COUNTRY_FIELDS, require_country
    from signing_service.hierarchy import dev_signer, dev_trust

    country = {
        "country": "XX",
        "locale": "en-XX",
        "currency_code": "XXX",
        "currency_symbol": "X",
        "issued_at": "2026-10-16T00:00:00Z",
        "items": {k: "synthetic-ref" for k in COUNTRY_FIELDS},
    }
    path = tmp_path / "pilot-country.json"

    def save(value):
        path.write_text(json.dumps(dev_signer().sign("pilot_country", value)))

    save(country)
    with pytest.raises(ValueError):
        require_country(str(path), Environment.DEV, dev_trust())
    clearance = {
        "protocol_id": "synthetic-pilot",
        "registered_at": "2026-10-01T00:00:00Z",
        "baseline_at": "2026-10-02T00:00:00Z",
        "starts_at": "2026-10-03T00:00:00Z",
        "analysis_sha256": "a" * 64,
        "approval_ref": "synthetic-owner-approval",
    }
    save({**country, "pilot_clearance": clearance})
    assert require_country(str(path), Environment.DEV, dev_trust())["country"] == "XX"
    save({**country, "pilot_clearance": {**clearance, "registered_at": clearance["baseline_at"]}})
    with pytest.raises(ValueError):
        require_country(str(path), Environment.DEV, dev_trust())


def test_pilot_control_configuration_selects_the_profile_gate():
    from agent_core.config import Settings
    from agent_core.config.pilot import control_errors, deployment_settings
    from agent_core.contracts import errors

    message = {
        "type": "control.config",
        "data_dir": "/synthetic",
        "content_root": "/synthetic/content",
        "skills_root": "/synthetic/skills",
        "release": True,
        "pilot_country_file": "/synthetic/pilot-country.json",
    }
    assert not control_errors(message)
    assert control_errors({**message, "pilot_country_file": 1})
    assert control_errors({**message, "unknown_field": "refused"})
    assert not errors("control/control#/$defs/ToCore", message)
    settings = deployment_settings(Settings(), message)
    assert settings.environment == "pilot" and settings.pilot_country_file == message["pilot_country_file"]
