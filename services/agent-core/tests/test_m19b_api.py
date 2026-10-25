"""M19.b and M19.c through the local API: the egress ledger, online features with their consents, the cloud tier
subscription (D70), the DPIA gate and the cost model (ARC-10, ARC-11, BIZ-07, BIZ-08, PRV-08). Profiles, the
entitlement and every reply are synthetic; the DPIA reference and the signing key are test values."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from agent_core.config.environments import Environment
from agent_core.contracts import errors as contract_errors
from agent_core.net.dpia import release_list, visible_features
from agent_core.net.policy import load_policy
from agent_core.providers.base import Message
from agent_core.providers.gateway import GatewayProvider
from agent_core.store import consents as consent_store
from api_harness import start_core, stop_core
from jana_tools.cost_model import Usage, c_cloud, measure, workbook
from net_harness import HOSTS, FakeServices, enable, layer, telemetry_payload
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose
from test_m10a_profiles import Api, code, student
from test_m10e_consent import NOTICE, _settings

LOOP = asyncio.new_event_loop()
DAY_MS = 86_400_000


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def with_online(tmp_path: Path, scenario: Any, services: bool = False, release: bool = False) -> Any:
    async def go() -> Any:
        r = await start_core(tmp_path, settings=_settings(), worker=False)
        r.core.entitlement_trust = dev_trust()
        try:
            if services:
                async with FakeServices(tmp_path) as fake:
                    online = layer(tmp_path, fake, device=r.runtime.stores.device, release=release)
                    r.core.online = r.runtime.online = online
                    try:
                        return await scenario(Api(r), r, online, fake)
                    finally:
                        await online.stop()
            online = layer(tmp_path, device=r.runtime.stores.device, release=release)
            r.core.online = r.runtime.online = online
            try:
                return await scenario(Api(r), r, online, None)
            finally:
                await online.stop()
        finally:
            await stop_core(r)

    return run(go())


def entitlement(profiles: list[str], *, allowance: int = 1_800_000, seats: int = 2) -> dict[str, Any]:
    document = {"kind": "cloud_tier_subscription", "subscription_id": "sub_test_0001", "licence_id": "lic_test",
                "period_start": "2026-09-01T00:00:00.000Z", "period_end": "2099-01-01T00:00:00.000Z",
                "seats": seats, "allowance_tokens": allowance, "profile_ids": profiles,
                "plan": "jana_online", "band": "nigeria", "billing": "month", "features": ["cloud_tier"], "limits": {},
                "created_at": "2026-10-01T00:00:00.000Z"}  # fmt: skip
    return dev_signer(Purpose.LICENCE).sign("licence_file", document, now="2026-10-01T00:00:00.000Z")


# --- ARC-10 -----------------------------------------------------------------------------------------------------


def arc10_ledger_records_every_request(tmp_path: Path) -> None:
    """Every request that left (probes, credential, model calls, update checks, queued telemetry) has a ledger row
    with time, feature, host, bytes and payload class, and no content anywhere in the ledger."""

    async def scenario(api: Api, r: Any, online: Any, fake: FakeServices) -> Any:
        enable(online, "update_checks", "telemetry", "cloud_tier")
        online.connectivity.features_changed()
        await online.connectivity.check()
        await online.client.send("update_checks", "GET", f"https://{HOSTS['updates']}/v1/ping", "update_check")
        online.outbox.put("telemetry", "telemetry", telemetry_payload(), expires_ms=online.clock_ms() + DAY_MS)
        await online.drain_once()
        gateway = GatewayProvider(online.client, lambda: HOSTS["gateway"], "primary", token=online.credential.token)
        await gateway.complete("fast-model", [Message("user", "What is speed? secret-canary-77")], [])
        rows = online.device.execute("SELECT * FROM egress_ledger").fetchall()
        columns = [d[1] for d in online.device.execute("PRAGMA table_info(egress_ledger)").fetchall()]
        listed = (await api.call("GET", "/v1/connectivity/ledger")).json()
        return rows, columns, listed, len(fake.requests)

    rows, columns, listed, requests = with_online(tmp_path, scenario, services=True)
    assert len(rows) == requests, "one ledger row per request that left"
    assert columns == ["ledger_id", "at", "feature", "destination", "bytes", "payload_class", "profile_id"]
    assert "secret-canary-77" not in json.dumps(rows) and "turns" not in json.dumps(rows)
    assert len(listed["entries"]) == requests and listed["retention_days"] == 90
    assert all(set(e) == {"at", "feature", "destination", "bytes", "payload_class"} for e in listed["entries"])
    assert {e["payload_class"] for e in listed["entries"]} >= {"probe", "update_check", "telemetry_aggregate",
                                                               "service_auth", "cloud_prompt"}  # fmt: skip
    assert contract_errors("api/commands#/$defs/EgressLedger", listed) == []


# --- ARC-11 -----------------------------------------------------------------------------------------------------


async def _token(api: Api, profile: str) -> str:
    return str((await api.unlock(profile)).json()["profile_token"])


def arc11_minor_needs_checkout_consent(tmp_path: Path) -> None:
    """No call on a profile under 18 makes a profile-data feature effective without the guardian's consent from the
    subscription checkout: not the device switches, not the consent switch, not a subscription that lists no consent
    for it, not a corrected age band (D70, D86, PRV-06)."""

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        minor = await api.add(student("Ama"))
        every = {f: True for f in online.shown()}
        kid = await _token(api, minor)
        steps: list[Any] = [(await api.call("PATCH", "/v1/connectivity", {"features": every})).status_code]
        steps.append(code(await api.call("PUT", f"/v1/profiles/{minor}/consents/cloud_tier",
                                         {"action": "on", "notice_version": NOTICE}, profile=kid)))  # fmt: skip
        waiting = await api.call("POST", "/v1/subscription", {"entitlement": entitlement([minor]), "consents": []})
        steps.append(waiting.json()["profiles"])

        def effective() -> bool:
            with r.runtime.directory.open_learner(minor) as conn:
                return bool(online.cloud_effective(minor, conn))

        steps.append(effective())
        await api.call("PATCH", f"/v1/profiles/{minor}", {"age_band": "16_17"}, profile=kid)
        steps.append(effective())
        given = await api.call("POST", "/v1/subscription", {"entitlement": entitlement([minor]),
                                                             "consents": [{"profile_id": minor,
                                                                           "notice_version": NOTICE}]})  # fmt: skip
        steps.append((given.json()["state"], effective()))
        state = (await api.call("GET", f"/v1/profiles/{minor}/consents", profile=kid)).json()
        steps.append(next((c["granted_by_role"], c["method"]) for c in state if c["scope"] == "cloud_tier"))
        return steps

    steps = with_online(tmp_path, scenario)
    assert steps[:2] == [200, "guardian_consent_required"]
    assert steps[2] == [{"profile_id": steps[2][0]["profile_id"], "consent": "needed"}]
    assert steps[3:] == [False, False, ("active", True), ("guardian", "checkout_guardian")]


def arc11_off_always_allowed(tmp_path: Path) -> None:
    """From any open profile, every switch goes off and the profile's own consents pause, resume and withdraw, each in
    one step with no PIN (D86, D87)."""

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        grown = await api.add(student("Esi", age_band="18_plus"))
        minor = await api.add(student("Ama"))
        await api.call(
            "POST",
            "/v1/subscription",
            {
                "entitlement": entitlement([grown, minor]),
                "consents": [
                    {"profile_id": minor, "notice_version": NOTICE},
                    {"profile_id": grown, "notice_version": NOTICE},
                ],
            },
        )
        every = {f: True for f in online.shown()}
        assert (await api.call("PATCH", "/v1/connectivity", {"features": every})).status_code == 200
        # The checkout records the minor's guardian consent; the 18+ student grants their own (D43, API-28).
        own = await api.call("PUT", f"/v1/profiles/{grown}/consents/cloud_tier",
                             {"action": "on", "notice_version": NOTICE}, profile=await _token(api, grown))  # fmt: skip
        assert own.status_code == 200 and own.json()["granted_by_role"] == "student_18_plus", own.text
        results = []
        for profile in (minor, grown):
            token = await _token(api, profile)
            off = await api.call("PATCH", "/v1/connectivity", {"features": {f: False for f in every}}, profile=token)
            results.append((off.status_code, online.features_on()))
            for action in ("pause", "on", "withdraw"):
                reply = await api.call("PUT", f"/v1/profiles/{profile}/consents/cloud_tier", {"action": action},
                                       profile=token)  # fmt: skip
                results.append((action, reply.status_code, reply.json()["paused"], reply.json()["granted"]))
            await api.call("PATCH", "/v1/connectivity", {"features": every}, profile=token)
        return results

    results = with_online(tmp_path, scenario)
    for start in (0, 4):
        assert results[start] == (200, set())
        assert results[start + 1 : start + 4] == [("pause", 200, True, True), ("on", 200, False, True),
                                                  ("withdraw", 200, False, False)]  # fmt: skip


def arc11_consent_required(tmp_path: Path) -> None:
    """A data-sending feature is not in effect without its own current consent: the switch alone does not do it,
    and withdrawing the consent ends it."""

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        grown = await api.add(student("Esi", age_band="18_plus"))
        own = (await api.unlock(grown)).json()["profile_token"]
        await api.call(
            "POST",
            "/v1/subscription",
            {"entitlement": entitlement([grown]), "consents": [{"profile_id": grown, "notice_version": NOTICE}]},
        )
        with r.runtime.directory.open_learner(grown) as conn:
            consent_store.withdraw(conn, "cloud_tier", "student_18_plus", 0)
            switched_without_consent = online.cloud_effective(grown, conn)
        await api.call(
            "PUT",
            f"/v1/profiles/{grown}/consents/cloud_tier",
            {"action": "on", "notice_version": NOTICE},
            profile=own,
        )
        with r.runtime.directory.open_learner(grown) as conn:
            with_consent = online.cloud_effective(grown, conn)
        telemetry = await api.call("PATCH", "/v1/connectivity", {"features": {"telemetry": True}})
        device = online.device.execute("SELECT scope FROM device_consents WHERE withdrawn_at IS NULL").fetchall()
        return switched_without_consent, with_consent, telemetry.status_code, device

    without, with_consent, status, device = with_online(tmp_path, scenario)
    assert without is False and with_consent is True
    assert status == 200 and device == [("telemetry",)], "the switch records the device consent in the same action"


# --- BIZ-07 (D70) ------------------------------------------------------------------------------------------------


def biz07_consent_gate(tmp_path: Path) -> None:
    """The cloud tier cannot be on without a recorded consent: a subscription that names a minor without the
    guardian's consent waits (`pending_consent`), the tier stays off, and it turns on only when the consent is
    recorded; ending the subscription turns it off and withdraws the consent."""

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        minor = await api.add(student("Ama"))
        steps = []
        waiting = await api.call("POST", "/v1/subscription", {"entitlement": entitlement([minor]), "consents": []})
        steps.append((waiting.json()["state"], "cloud_tier" in online.features_on()))
        with r.runtime.directory.open_learner(minor) as conn:
            steps.append(online.cloud_effective(minor, conn))
        given = await api.call(
            "POST",
            "/v1/subscription",
            {"entitlement": {}, "consents": [{"profile_id": minor, "notice_version": NOTICE}]},
        )
        steps.append((given.json()["state"], "cloud_tier" in online.features_on()))
        with r.runtime.directory.open_learner(minor) as conn:
            steps.append((online.cloud_effective(minor, conn), consent_store.active(conn, "cloud_tier")[1]))
        ended = await api.call("DELETE", "/v1/subscription")
        with r.runtime.directory.open_learner(minor) as conn:
            steps.append((ended.json()["state"], online.cloud_effective(minor, conn),
                          consent_store.active(conn, "cloud_tier")))  # fmt: skip
        forged = dict(entitlement([minor]), allowance_tokens=10**12)
        refused = await api.call("POST", "/v1/subscription", {"entitlement": forged, "consents": []})
        steps.append(code(refused))
        steps.append(contract_errors("api/commands#/$defs/CloudSubscription", given.json()))
        return steps

    steps = with_online(tmp_path, scenario)
    assert steps == [("pending_consent", False), False, ("active", True), (True, "guardian"), ("ended", False, None),
                     "validation_failed", []]  # fmt: skip


def test_subscription_apply_validates_its_entitlement_against_the_contract(tmp_path: Path) -> None:
    """`POST /v1/subscription` reads its body through the SubscriptionApply contract (D39): an entitlement missing a
    field the CloudTierEntitlement contract requires, or carrying one it does not list, answers validation_failed
    before anything is verified or stored; the signed one is accepted."""

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        grown = await api.add(student("Kojo"))
        missing = {k: v for k, v in entitlement([grown]).items() if k != "allowance_tokens"}
        extra = {**entitlement([grown]), "discount": "all"}
        replies = [await api.call("POST", "/v1/subscription", {"entitlement": e, "consents": []})
                   for e in (missing, extra)]  # fmt: skip
        stored = (await api.call("GET", "/v1/subscription")).json()["state"]
        good = await api.call("POST", "/v1/subscription", {"entitlement": entitlement([grown]), "consents": []})
        return [code(reply) for reply in replies], stored, good.status_code

    codes, stored, good = with_online(tmp_path, scenario)
    assert codes == ["validation_failed", "validation_failed"] and stored == "none" and good == 200


# --- PRV-08 -----------------------------------------------------------------------------------------------------


def prv08_feature_hidden_without_dpia(tmp_path: Path) -> None:
    """A release build shows only the features whose DPIA is on its signed list; with no list, a forged list or one
    signed under a root release builds do not trust, every feature is hidden and cannot be switched on."""
    policy = load_policy()
    signed = dev_signer(Purpose.CONTENT).sign(
        "dpia_list",
        {"dpia_list_version": 1, "created_at": "2026-10-01T00:00:00.000Z",
         "approved": [{"dpia_id": "DPIA-TEST-01", "gate": "pilot_start"}]},
        now="2026-10-01T00:00:00.000Z",
    )  # fmt: skip
    path = tmp_path / "dpia_list.json"
    path.write_text(json.dumps(signed))
    approved = visible_features(policy, True, Environment.DEV, path, dev_trust())
    assert approved == ["downloads", "update_checks", "telemetry", "crash_reports"]
    assert release_list(Environment.DEV, path, dev_trust()).ref(policy, "telemetry") == "DPIA-TEST-01"
    assert visible_features(policy, True, Environment.PRODUCTION, path, dev_trust()) == []  # test root refused
    forged = {**signed, "approved": [*signed["approved"], {"dpia_id": "X", "gate": "cloud_tier"}]}
    path.write_text(json.dumps(forged))
    assert visible_features(policy, True, Environment.DEV, path, dev_trust()) == []
    assert visible_features(policy, True, Environment.PRODUCTION, tmp_path / "missing.json") == []
    assert visible_features(policy, False, Environment.DEV, tmp_path / "missing.json") is None  # a dev build

    async def scenario(api: Api, r: Any, online: Any, _: Any) -> Any:
        online.visible = approved
        listed = (await api.call("GET", "/v1/connectivity")).json()
        hidden = await api.call("PATCH", "/v1/connectivity", {"features": {"cloud_tier": True}})
        online.visible = []
        none = (await api.call("GET", "/v1/connectivity")).json()
        return listed, code(hidden), none

    listed, hidden, none = with_online(tmp_path, scenario)
    assert sorted(listed["features"]) == sorted(approved) and "cloud_tier" not in listed["features"]
    assert hidden == "validation_failed"
    assert none["features"] == {}


# --- BIZ-08 -----------------------------------------------------------------------------------------------------


def biz08_cost_model_uses_measured_inputs() -> None:
    """C_cloud is computed from measured per-role token counts and the price table, and the review fails when the
    inputs are older than the current model release."""

    def call(role: str, i: int, o: int, cached: int) -> dict[str, Any]:
        return {"role": role, "provider_kind": "cloud", "tokens": {"input": i, "output": o, "cache_read": cached}}

    traces = [{"model_calls": [call("coach", 3000, 250, 1800), call("checker", 2000, 100, 0)]},
              {"model_calls": [call("coach", 3000, 250, 1800)]}]  # fmt: skip
    roles = measure(traces)
    assert roles["coach"].calls_per_turn == 1.0 and roles["coach"].cache_hit == 0.6
    assert roles["checker"].calls_per_turn == 0.5
    usage = Usage(cloud_share=1.0, turns_per_month=200)
    prices = {
        "release": "2026-10",
        "models": {
            "strong-model": {
                "price_in_per_mtok": 1.25,
                "price_out_per_mtok": 10.0,
            }
        },
    }
    # At a stated price (Jana Online's US$6 a month): this checks the cost inputs, not TABLE BIZ-18a, whose lowest
    # per-student month is below this synthetic strong-model floor (that review error is the next test's case).
    book = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, prices=prices,
                    measured_release="2026-10", price_usd=6.0)  # fmt: skip
    p_in, p_out = 1.25e-6, 10e-6
    coach = 1.0 * ((3000 * 0.4 + 3000 * 0.6 * 0.25) * p_in + 250 * p_out)
    checker = 0.5 * (2000 * p_in + 100 * p_out)
    assert abs(book["c_cloud_usd_per_student_month"] - 200 * (coach + checker)) < 1e-12
    assert abs(c_cloud(roles, usage, p_in, p_out, 0.25) - book["c_cloud_usd_per_student_month"]) < 1e-12
    assert book["errors"] == [] and book["price_floor_usd"] > book["c_cloud_usd_per_student_month"]
    stale = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, prices=prices,
                     measured_release="2026-04")  # fmt: skip
    assert stale["errors"] and "older than the current model release" in stale["errors"][0]
    assert workbook([], model="strong-model", usage=usage, cached_multiplier=0.25, prices=prices,
                    measured_release="2026-10")["errors"]  # fmt: skip


def test_biz08_cost_model_reads_the_decided_price_and_margin() -> None:
    """D33, D121, BIZ-08: the cost model's allowance is LIST BIZ-08a formula 5 at the decided price (the lowest a
    covered student's month brings in across TABLE BIZ-18a) and the gross margin of the gateway's Tier configuration,
    not at the price floor or a margin of its own; a decided price below the formula-4 floor fails the review."""
    import jana_tools.cost_model as cost_model
    from cloud_gateway.config import load_config

    call = {"role": "coach", "provider_kind": "cloud", "tokens": {"input": 3000, "output": 250, "cache_read": 1800}}
    traces = [{"model_calls": [call]}]
    usage = Usage(cloud_share=1.0, turns_per_month=200)
    decided = load_config().tier
    assert cost_model.tier() == decided and not hasattr(cost_model, "GROSS_MARGIN")
    assert "gross_margin" not in cost_model.DECLARED  # declared once, by the gateway's key
    book = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, measured_release="2026-10")
    price = cost_model.decided_price()
    assert price == 180_000 / 1500 / 12 / 4  # Jana Family in Nigeria for a year, per student month
    assert (book["price_usd_per_student_month"], book["gross_margin"]) == (price, decided.gross_margin)
    rates = cost_model.load_prices()["models"]["strong-model"]
    p_in, p_out = rates["price_in_per_mtok"] / 1e6, rates["price_out_per_mtok"] / 1e6
    blended = (3000 * p_in + 250 * p_out) / 3250
    assert book["allowance_tokens"] == pytest.approx(price * (1 - decided.gross_margin) / blended)
    at_floor = cost_model.allowance_tokens(book["price_floor_usd"], decided.gross_margin, blended)
    assert book["allowance_tokens"] > at_floor  # the decided price, not the floor
    cheaper = workbook(traces, model="strong-model", usage=usage, cached_multiplier=0.25, measured_release="2026-10",
                       price_usd=0.01)  # fmt: skip
    assert any("below the formula-4 floor" in e for e in cheaper["errors"])


@pytest.mark.parametrize("feature", sorted(load_policy().features))
def dat18_feature_requires_consent(tmp_path: Path, feature: str) -> None:
    """Audit each declared online row at the shipped boundary; no future-stage transport is enabled.

    Downloads/updates carry no learner scope. A device switch is itself the device consent action. Profile
    switches never manufacture consent, and an under-18 profile gets the guardian-consent response.
    """
    row = load_policy().features[feature]

    async def scenario(api: Api, r: Any, online: Any, fake: FakeServices) -> None:
        profile = await api.add(student("Consent audit"))
        token = (await api.unlock(profile)).json()["profile_token"]
        before = len(fake.requests)
        switched = await api.call("PATCH", "/v1/connectivity", {"features": {feature: True}})
        assert len(fake.requests) == before, "a switch must not send learner content"
        if not consent_store.shipped(row.stage):
            assert switched.status_code >= 400 and feature not in online.features_on()
            assert feature not in online.state_view(True)["features"]
            return
        assert switched.status_code == 200, switched.text
        if row.consent == "profile":
            with r.runtime.directory.open_learner(profile) as conn:
                assert consent_store.active(conn, feature) is None
                assert not online.cloud_effective(profile, conn)
            asked = await api.call(
                "PUT",
                f"/v1/profiles/{profile}/consents/{feature}",
                {"action": "on", "notice_version": NOTICE},
                profile=token,
            )
            assert code(asked) == "guardian_consent_required"
            assert not any(
                c["effective"]
                for c in (await api.call("GET", f"/v1/profiles/{profile}/consents", profile=token)).json()
            )
        elif row.consent == "device":
            # There is no supported enabled-without-consent state: the same transaction grants it.
            grants = online.device.execute(
                "SELECT notice_version,dpia_ref FROM device_consents WHERE scope=? AND withdrawn_at IS NULL",
                (feature,),
            ).fetchall()
            assert grants == [(NOTICE, r.core.settings.consent_dpia_ref)]
            await api.call("PATCH", "/v1/connectivity", {"features": {feature: False}})
            assert not online.device.execute(
                "SELECT 1 FROM device_consents WHERE scope=? AND withdrawn_at IS NULL", (feature,)
            ).fetchall()
            assert feature not in online.features_on()
        else:
            assert feature in {"downloads", "update_checks"} and not row.data_classes
        assert len(fake.requests) == before

    with_online(tmp_path, scenario, services=True)
