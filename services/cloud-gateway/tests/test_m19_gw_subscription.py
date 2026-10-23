"""The gateway serves the cloud tier only under a current subscription (BIZ-07, D70, SEC-20, SEC-21): registration
needs the signed entitlement, a subscription holds a bounded number of device credentials, credentials stop at the
end of the subscription's period, quotas are the subscription's, and the unauthenticated routes refuse oversized
bodies before reading them. Every licence, subscription and key here is a test value."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path

from agent_core.providers.errors import classify_http
from gateway_stubs import FAKE_KEYS, LICENCE, Clock, Device, Output, entitlement, gateway_config, harness
from signing_service.hierarchy import dev_signer
from signing_service.keys import Purpose

CHAT = {"model": "primary/fast-model", "messages": [{"role": "user", "content": "Hello"}]}
END = 1_798_761_600.0  # 2027-01-01T00:00:00Z, the end of the stubs' subscription period


def test_sec21_registration_needs_a_signed_entitlement(tmp_path: Path) -> None:
    """A licence id alone, an unsigned or altered entitlement, or one signed by a key that is not a licence key
    registers nothing (SEC-21, D70)."""

    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        bare = await h.client.post("/v1/devices", json={"public_key": device.public_key(), "licence_id": LICENCE})
        assert bare.status_code == 403
        altered = {**entitlement("sub_a"), "subscription_id": "sub_other"}
        assert (await device.register(h.client, document=altered)).status_code == 403
        unsigned = {k: v for k, v in entitlement("sub_a").items() if k != "signature"}
        assert (await device.register(h.client, document=unsigned)).status_code == 403
        content_key = dev_signer(Purpose.CONTENT).sign("content_pack", {k: v for k, v in unsigned.items()})
        assert (await device.register(h.client, document=content_key)).status_code == 403
        lapsed = entitlement("sub_a", period=("2026-01-01T00:00:00.000Z", "2026-06-01T00:00:00.000Z"))
        assert (await device.register(h.client, document=lapsed)).status_code == 403
        assert (await device.register(h.client)).status_code == 201

    asyncio.run(main())


def test_sec21_devices_per_subscription_bounded(tmp_path: Path) -> None:
    """A subscription holds at most `devices_per_subscription` live credentials: minting more is refused, the same
    device registering again keeps its credential, and a revoked key never registers again."""

    async def main() -> None:
        h = harness(gateway_config(tmp_path, devices_per_subscription=2))
        first, second, third = (Device(subscription="sub_family") for _ in range(3))
        assert (await first.register(h.client)).status_code == 201
        assert (await second.register(h.client)).status_code == 201
        assert (await third.register(h.client)).status_code == 409
        kept = first.credential_id
        assert (await first.register(h.client)).status_code == 201 and first.credential_id == kept
        admin = {"Authorization": f"Bearer {FAKE_KEYS['admin_token']}"}
        revoke = f"/admin/v1/credentials/{second.credential_id}/revoke"
        assert (await h.client.post(revoke, headers=admin)).status_code == 204
        assert (await second.register(h.client)).status_code == 403  # a revoked key stays revoked
        assert (await third.register(h.client)).status_code == 201  # the portal's revocation freed the slot

    asyncio.run(main())


def test_biz07_credentials_end_with_the_subscription(tmp_path: Path) -> None:
    """At the end of the subscription's period the credential's tokens stop and no new token is issued; the next
    period's entitlement renews the same credential (BIZ-07, D70)."""

    async def main() -> None:
        clock = Clock()
        h = harness(gateway_config(tmp_path), clock)
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text="Hi."))
        assert (await device.chat(h.client, CHAT)).status_code == 200
        clock.now = END + 1
        refused = await device.chat(h.client, CHAT)
        assert refused.status_code == 401 and classify_http(401, refused.json()) == "auth"
        assert (await device.challenge(h.client)).status_code == 401
        kept = device.credential_id
        renewal = entitlement(device.subscription, period=("2027-01-01T00:00:00.000Z", "2027-05-01T00:00:00.000Z"))
        assert (await device.register(h.client, document=renewal)).status_code == 201
        assert device.credential_id == kept
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text="Hi again."))
        assert (await device.chat(h.client, CHAT)).status_code == 200

    asyncio.run(main())


def test_sec20_quotas_are_per_subscription(tmp_path: Path) -> None:
    """Rate limits and spend caps hold for the subscription, so a second credential of it adds no headroom."""

    async def main() -> None:
        config = gateway_config(tmp_path, quotas={"device_requests_per_minute": 1, "device_burst": 2,
                                                  "licence_burst": 1000})  # fmt: skip
        h = harness(config)
        first, second = Device(subscription="sub_shared"), Device(subscription="sub_shared")
        await first.login(h.client)
        await second.login(h.client)
        assert [(await first.chat(h.client, CHAT)).status_code for _ in range(2)] == [200, 200]
        limited = await second.chat(h.client, CHAT)
        assert limited.status_code == 429 and classify_http(429, limited.json()) == "quota_or_billing"

    asyncio.run(main())


def test_sec21_auth_routes_refuse_large_bodies_unread(tmp_path: Path) -> None:
    """An oversized body on an unauthenticated route is refused from its declared length, and a body that grows
    past the limit while streaming is refused too, before any of it is parsed."""

    async def main() -> None:
        h = harness(gateway_config(tmp_path, max_auth_request_bytes=2048))
        big = b'{"credential_id": "' + b"x" * 4096 + b'"}'
        declared = await h.client.post("/v1/auth/challenge", content=big, headers={"content-type": "application/json"})
        assert declared.status_code == 413

        async def chunks():
            yield b'{"public_key": "'
            for _ in range(8):
                yield base64.b64encode(b"y" * 600)
            yield b'"}'

        streamed = await h.client.post("/v1/devices", content=chunks(), headers={"content-type": "application/json"})
        assert streamed.status_code == 413

    asyncio.run(main())


def test_biz08_monthly_allowance_from_the_price_and_margin() -> None:
    """D33, D121, LIST BIZ-08a formula 5: one student's month may cost the lowest price a covered student's month
    brings in across TABLE BIZ-18a times (1 - margin), and its token allowance is that over the blended price per
    token of the gateway's price table at TABLE BIZ-08b's mix. Set directly, the allowance overrides the prices."""
    from cloud_gateway import tier
    from cloud_gateway.config import load_config

    config = load_config()
    t = config.tier
    # Jana Family in Nigeria for a year: NGN 180,000 / 12 months / 4 students at NGN 1,500 to the dollar.
    assert tier.allowance_basis_usd(config) == 180_000 / 1500 / 12 / 4
    usd = tier.allowance_basis_usd(config) * (1 - t.gross_margin)
    assert tier.monthly_allowance_usd(config) == usd
    cost = tokens = 0.0
    for alias, calls in t.calls_per_turn.items():
        price = config.prices[config.providers[config.slots["primary"]].models[alias].id]
        cached = t.input_tokens_per_call * t.cache_hit_share
        uncached = t.input_tokens_per_call - cached
        cost += calls * (uncached * price.input + cached * price.cached_input + t.output_tokens_per_call * price.output)
        tokens += calls * (t.input_tokens_per_call + t.output_tokens_per_call)
    assert tier.monthly_allowance_tokens(config) == int(usd / (cost / 1e6 / tokens))
    figures = tier.summary(config)
    assert figures["allowance_basis_offer"] == "jana_family/nigeria/year"
    assert figures["allowance_tokens_per_student_month"] == tier.monthly_allowance_tokens(config) > 0
    assert tier.monthly_allowance_usd(load_config(tier={"allowance_usd_per_student_month": 3.0})) == 3.0
    try:
        load_config(tier={"calls_per_turn": {"no-such-model": 1.0}})
    except ValueError as refused:
        assert "usage mix" in str(refused)
    else:
        raise AssertionError("a usage mix naming an unknown model must be refused")


def test_d33_allowance_months_inside_a_prepaid_term() -> None:
    """A term is months prepaid, and the allowance resets each calendar month of it from the period's start; a
    start on the 31st falls on the last day of a shorter month."""
    from datetime import UTC, datetime

    from cloud_gateway.tier import add_months, allowance_window

    def at(*parts: int) -> float:
        return datetime(*parts, tzinfo=UTC).timestamp()

    start = at(2026, 1, 31, 9)
    assert add_months(start, 1) == at(2026, 2, 28, 9) and add_months(start, 3) == at(2026, 4, 30, 9)
    assert allowance_window(start, at(2026, 1, 31, 9)) == (start, at(2026, 2, 28, 9))
    assert allowance_window(start, at(2026, 2, 28, 8)) == (start, at(2026, 2, 28, 9))
    assert allowance_window(start, at(2026, 3, 1)) == (at(2026, 2, 28, 9), at(2026, 3, 31, 9))
    assert allowance_window(start, at(2026, 4, 15)) == (at(2026, 3, 31, 9), at(2026, 4, 30, 9))
