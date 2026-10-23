"""PRD-21 under the explicit D86/D87 scope rules. Learners, DPIA and entitlement keys are synthetic."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agent_core.net.policy import EgressRefused, load_policy
from agent_core.store import consents
from api_harness import start_core, stop_core
from net_harness import FakeServices, layer
from signing_service.hierarchy import dev_trust
from test_m10a_profiles import Api, code, student
from test_m10e_consent import NOTICE, _settings
from test_m19b_api import entitlement


@pytest.mark.parametrize("band", ["under_13", "13_15", "16_17"])
@pytest.mark.parametrize("feature", sorted(load_policy().features))
def prd21_minor_needs_guardian_consent(tmp_path: Path, band: str, feature: str) -> None:
    async def scenario() -> None:
        r = await start_core(tmp_path, settings=_settings(), worker=False, stage="S2")
        r.core.entitlement_trust = dev_trust()
        try:
            async with FakeServices(tmp_path) as fake:
                online = layer(tmp_path, fake, device=r.runtime.stores.device)
                r.core.online = r.runtime.online = online
                try:
                    api = Api(r)
                    profile = await api.add(student("Synthetic learner", age_band=band))
                    token = await api.token(profile)
                    row = load_policy().features[feature]
                    before = len(fake.requests)
                    switched = await api.call("PATCH", "/v1/connectivity", {"features": {feature: True}}, profile=token)
                    assert len(fake.requests) == before
                    if not row.shipped:
                        assert switched.status_code >= 400 and feature not in online.features_on()
                        online.connectivity.state = "online"
                        with pytest.raises(EgressRefused, match="stage_not_shipped"):
                            await online.client.send(
                                feature,
                                "POST",
                                f"https://{online.host_for(feature)}/v1/x",
                                row.payload_classes[0],
                                body={"text": "MUST STAY LOCAL"},
                                profile_id=profile,
                            )
                    elif row.consent == "device":
                        # PRV-05a explicitly permits separate, content-free device consent at any age.
                        assert switched.status_code == 200
                        grant = online.device.execute(
                            "SELECT notice_version,dpia_ref FROM device_consents"
                            " WHERE scope=? AND withdrawn_at IS NULL",
                            (feature,),
                        ).fetchall()
                        assert grant == [(NOTICE, r.core.settings.consent_dpia_ref)]
                        assert consents.active(r.runtime.learner.conn, "cloud_tier") is None
                        assert not r.runtime.cloud_tier_on()
                    elif row.consent == "none":
                        assert switched.status_code == 200
                        assert feature in {"downloads", "update_checks"} and row.data_classes == ()
                        assert consents.active(r.runtime.learner.conn, "cloud_tier") is None
                    else:
                        assert feature == "cloud_tier" and switched.status_code == 200
                        online.record_notice(profile, feature, True)  # Notice acceptance cannot manufacture consent.
                        for body in (
                            {"action": "on", "notice_version": NOTICE},
                            {"action": "on", "notice_version": NOTICE, "guardian_agreed": True},
                        ):
                            refused = await api.call(
                                "PUT", f"/v1/profiles/{profile}/consents/{feature}", body, profile=token
                            )
                            assert code(refused) == "guardian_consent_required"
                        assert consents.active(r.runtime.learner.conn, feature) is None
                        assert not r.runtime.cloud_tier_on()
                        unsigned = await api.call(
                            "POST",
                            "/v1/subscription",
                            {
                                "entitlement": {"forged": True},
                                "consents": [{"profile_id": profile, "notice_version": NOTICE}],
                            },
                        )
                        assert unsigned.status_code >= 400 and consents.active(r.runtime.learner.conn, feature) is None
                        signed = entitlement([profile])
                        waiting = await api.call("POST", "/v1/subscription", {"entitlement": signed, "consents": []})
                        assert waiting.status_code == 200 and waiting.json()["state"] == "pending_consent"
                        assert not r.runtime.cloud_tier_on()
                        corrected = await api.call(
                            "PATCH", f"/v1/profiles/{profile}", {"age_band": "16_17"}, profile=token
                        )
                        assert corrected.status_code == 200 and not r.runtime.cloud_tier_on()
                        given = await api.call(
                            "POST",
                            "/v1/subscription",
                            {"entitlement": signed, "consents": [{"profile_id": profile, "notice_version": NOTICE}]},
                        )
                        assert given.status_code == 200 and given.json()["state"] == "active"
                        grant = consents.active(r.runtime.learner.conn, feature)
                        assert grant and (grant[1], grant[2]) == ("guardian", "checkout_guardian")
                        assert r.runtime.cloud_tier_on()
                        for action, effective in (("pause", False), ("on", True), ("withdraw", False)):
                            reply = await api.call(
                                "PUT", f"/v1/profiles/{profile}/consents/{feature}", {"action": action}, profile=token
                            )
                            assert reply.status_code == 200 and r.runtime.cloud_tier_on() is effective
                        again = await api.call(
                            "PUT",
                            f"/v1/profiles/{profile}/consents/{feature}",
                            {"action": "on", "guardian_agreed": True, "notice_version": NOTICE},
                            profile=token,
                        )
                        assert code(again) == "guardian_consent_required" and not r.runtime.cloud_tier_on()
                    assert len(fake.requests) == before, "No consent or switch step sends learner content"
                finally:
                    await online.stop()
        finally:
            await stop_core(r)

    asyncio.run(scenario())
