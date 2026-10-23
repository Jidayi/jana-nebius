"""Gateway duties around each model call: minimisation (MDL-25, PRV-25), quotas and spend alerts (SEC-20)."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from agent_core.providers.errors import classify_http
from gateway_stubs import Clock, Device, Output, gateway_config, harness

CHAT: dict[str, Any] = {"model": "primary/fast-model", "messages": [{"role": "user", "content": "Hello"}]}


def test_profile_data_is_refused_before_any_provider(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        leaks = [
            {**CHAT, "messages": [{"role": "user", "content": "I am prf_7Hq2xk9 and stuck"}]},
            {**CHAT, "metadata": {"display_name": "Someone"}},
            {**CHAT, "messages": [{"role": "user", "content": [{"type": "text", "text": "see prf_ab12cd"}]}]},
        ]
        for body in leaks:
            reply = await device.chat(h.client, body)
            assert reply.status_code == 422 and reply.json()["error"]["code"] == "minimisation"
        token = await h.client.post(
            "/v1/chat/completions", json=CHAT, headers={**device.headers(), "X-Profile-Token": "abc"}
        )
        assert token.status_code == 422
        missing = await h.client.post(
            "/v1/chat/completions", json=CHAT, headers={"Authorization": f"Bearer {device.token}"}
        )
        assert missing.status_code == 400 and missing.json()["error"]["code"] == "pseudonym_required"
        assert not h.stubs["gemini"].seen

    asyncio.run(main())


def test_only_allow_listed_fields_and_the_pseudonym_reach_a_provider(tmp_path: Path) -> None:
    """Fields the chat contract does not list (a device-chosen `user`, `metadata`) refuse the request before any
    provider (D39); of a body the contract accepts, a participant `name` and every device header stay behind."""

    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        headers = {**device.headers(), "X-Device-Id": "device-123", "User-Agent": "jana-desktop/1.0"}
        outside = {**CHAT, "user": "device-chosen-user", "metadata": {"school": "Somewhere"}}
        refused = await h.client.post("/v1/chat/completions", json=outside, headers=headers)
        assert refused.status_code == 400 and classify_http(400, refused.json()) == "format_error"
        assert not h.stubs["gemini"].seen and not h.stubs["openai_compat"].seen
        body = {"messages": [{"role": "user", "content": "Hi", "name": "Learner_Name"}], "temperature": 0.1}
        for model in ("primary/fast-model", "fallback/fast-model"):
            reply = await h.client.post("/v1/chat/completions", json={**body, "model": model}, headers=headers)
            assert reply.status_code == 200, reply.text
        gemini, openai = h.stubs["gemini"].seen[-1], h.stubs["openai_compat"].seen[-1]
        for seen in (gemini, openai):
            sent = json.dumps(seen.body) + json.dumps(seen.headers)
            for leaked in (
                "Learner_Name",
                "device-chosen-user",
                "Somewhere",
                "device-123",
                "jana-desktop",
                device.token,
                device.credential_id,
            ):
                assert leaked not in sent
        assert device.pseudonym not in json.dumps(gemini.body)  # Gemini has no end-user field
        assert openai.body["user"] == device.pseudonym and openai.body["temperature"] == 0.1

    asyncio.run(main())


def test_device_rate_limit_reads_as_quota(tmp_path: Path) -> None:
    async def main() -> None:
        clock = Clock()
        config = gateway_config(tmp_path, quotas={"device_requests_per_minute": 6, "device_burst": 2})
        h = harness(config, clock)
        device = Device()
        await device.login(h.client)
        assert [(await device.chat(h.client, CHAT)).status_code for _ in range(2)] == [200, 200]
        limited = await device.chat(h.client, CHAT)
        assert limited.status_code == 429 and classify_http(429, limited.json()) == "quota_or_billing"
        assert int(limited.headers["Retry-After"]) >= 1
        clock.now += 10
        assert (await device.chat(h.client, CHAT)).status_code == 200
        other = Device()
        await other.login(h.client)
        assert (await other.chat(h.client, CHAT)).status_code == 200  # per device, not global

    asyncio.run(main())


def test_spend_caps_per_device_and_per_subscription_month(tmp_path: Path) -> None:
    """The device's daily cap, and the subscription's monthly allowance shared by its devices across days, which
    resets at the next allowance month of the paid period (BIZ-07, D33); there is no per-school cap (D100)."""

    async def main() -> None:
        # One stub reply costs (32 + 0.8 + 48) / 1e6 USD = 0.0000808 at the test prices. A tiny allowance set
        # directly (BIZ-18) makes the one-seat allowance 0.0002 USD a month; the device's daily cap is 0.00015 USD.
        clock = Clock()  # 2026-09-21, in the stubs' paid period from 2026-09-01
        config = gateway_config(
            tmp_path,
            quotas={"device_burst": 1000, "licence_burst": 1000, "device_daily_spend_usd": 0.00015},
            tier={"allowance_usd_per_student_month": 0.0002},
        )
        h = harness(config, clock)
        alone, first, second = Device(), Device(subscription="sub_month"), Device(subscription="sub_month")
        await alone.login(h.client)
        assert [(await alone.chat(h.client, CHAT)).status_code for _ in range(3)] == [200, 200, 429]
        capped = await alone.chat(h.client, CHAT)
        assert classify_http(429, capped.json()) == "quota_or_billing" and "device" in capped.json()["error"]["message"]
        await first.login(h.client)
        assert [(await first.chat(h.client, CHAT)).status_code for _ in range(3)] == [200, 200, 429]  # the day's cap
        clock.now += 86400  # the next day: the daily cap resets, the month's spend does not
        await second.login(h.client)
        assert (await second.chat(h.client, CHAT)).status_code == 200
        over = await second.chat(h.client, CHAT)  # the month's allowance (3 x 0.0000808 > 0.0002)
        assert over.status_code == 429 and "monthly allowance" in over.json()["error"]["message"]
        assert classify_http(429, over.json()) == "quota_or_billing"
        assert "school" not in json.dumps(config.quotas.model_dump())
        clock.now = datetime(2026, 10, 1, 0, 30, tzinfo=UTC).timestamp()  # the paid period's next month
        await second.login(h.client)
        assert (await second.chat(h.client, CHAT)).status_code == 200

    asyncio.run(main())


def test_allowance_month_outlives_the_request_metadata(tmp_path: Path) -> None:
    """OBS-22, D33: request metadata is kept 30 days while an allowance month can last 31, and the allowance still
    holds for the whole month, because it is enforced from the month's own running total, never from request rows;
    that total goes once its month is over."""
    from cloud_gateway.store import GatewayStore, day_of
    from cloud_gateway.tier import allowance_window

    async def main() -> None:
        october = datetime(2026, 10, 1, 0, 30, tzinfo=UTC).timestamp()  # month 2 of the period: 31 days
        clock = Clock(october)
        config = gateway_config(
            tmp_path,
            quotas={"device_burst": 1000, "licence_burst": 1000, "device_daily_spend_usd": 1.0},
            tier={"allowance_usd_per_student_month": 0.0002},
        )
        assert config.metadata_retention_days == 30
        h = harness(config, clock)
        spender, other = Device(subscription="sub_long_month"), Device(subscription="sub_other")
        await spender.login(h.client)
        statuses = [(await spender.chat(h.client, CHAT)).status_code for _ in range(4)]
        assert statuses[-1] == 429 and statuses.count(200) == 3  # the month's allowance is used up on its first day
        start, end = allowance_window(datetime(2026, 9, 1, tzinfo=UTC).timestamp(), october)
        assert (end - start) / 86400 == 31
        clock.now = datetime(2026, 10, 31, 23, 0, tzinfo=UTC).timestamp()  # 30.9 days on, the same allowance month
        await other.login(h.client)
        assert (await other.chat(h.client, CHAT)).status_code == 200  # a served call runs the hourly purge
        store = GatewayStore(config.storage_dir)
        try:
            assert store.spend(day_of(october)) == 0.0  # the first day's request metadata is gone (30 days)
            assert store.allowance_spend("sub_long_month", start) > 0  # the month's running total is not
        finally:
            store.close()
        await spender.login(h.client)
        refused = await spender.chat(h.client, CHAT)
        assert refused.status_code == 429 and "monthly allowance" in refused.json()["error"]["message"]
        clock.now = datetime(2026, 11, 1, 1, 0, tzinfo=UTC).timestamp()  # the next allowance month
        await spender.login(h.client)
        assert (await spender.chat(h.client, CHAT)).status_code == 200
        store = GatewayStore(config.storage_dir)
        try:
            assert store.allowance_spend("sub_long_month", start) == 0.0  # the finished month's total is purged
        finally:
            store.close()

    asyncio.run(main())


def test_spend_anomaly_alerts_once(tmp_path: Path) -> None:
    async def main() -> None:
        clock = Clock()
        config = gateway_config(
            tmp_path,
            quotas={
                "device_burst": 1000,
                "licence_burst": 1000,
                "anomaly_multiple": 3,
                "anomaly_min_usd": 0.0002,
                "anomaly_trailing_days": 3,
            },
        )
        h = harness(config, clock)
        device = Device()
        for _ in range(3):  # three ordinary days: one call a day
            await device.login(h.client)
            assert (await device.chat(h.client, CHAT)).status_code == 200
            clock.now += 86400
        await device.login(h.client)
        for _ in range(8):  # today: eight calls, well over three times the trailing mean
            assert (await device.chat(h.client, CHAT)).status_code == 200
        kinds = [kind for kind, _ in h.alerts]
        assert kinds.count("device_spend_anomaly") == 1 and kinds.count("licence_spend_anomaly") == 1
        detail = dict(h.alerts[0][1])
        assert detail["licence_id"] == "lic_school_one" and device.credential_id not in json.dumps(detail)

    asyncio.run(main())


def test_unknown_slot_or_alias_is_model_not_found(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path, slots={"primary": "gemini"}))
        device = Device()
        await device.login(h.client)
        for model in ("fallback/fast-model", "primary/huge-model", "gemini-stub-pro", None):
            reply = await device.chat(h.client, {**CHAT, "model": model})
            assert reply.status_code == 404 and classify_http(404, reply.json()) == "model_not_found"

    asyncio.run(main())


def test_mid_stream_failure_ends_without_done(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        h.stubs["gemini"].say(Output(text="This will be cut off", fail_mid_stream=True))
        reply = await device.chat(h.client, {**CHAT, "stream": True})
        assert reply.status_code == 200
        assert "[DONE]" not in reply.text and '"error"' in reply.text
        h.stubs["gemini"].say(Output(error=(503, {"error": {"status": "UNAVAILABLE"}})))
        early = await device.chat(h.client, {**CHAT, "stream": True})
        assert early.status_code == 503 and classify_http(503, early.json()) == "overloaded"

    asyncio.run(main())


def test_malformed_request_is_a_classified_error(tmp_path: Path) -> None:
    async def main() -> None:
        h = harness(gateway_config(tmp_path))
        device = Device()
        await device.login(h.client)
        reply = await device.chat(h.client, {**CHAT, "tools": [1]})
        assert reply.status_code == 400 and classify_http(400, reply.json()) == "format_error"
        assert not h.stubs["gemini"].seen

    asyncio.run(main())
