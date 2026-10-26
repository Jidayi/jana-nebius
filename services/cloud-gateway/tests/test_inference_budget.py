"""Real SQLite budget enforcement under concurrent sends, crashes, midnight and metadata purge. No paid calls."""

from __future__ import annotations

import asyncio
import base64
from collections.abc import AsyncGenerator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from cloud_gateway.config import load_config
from cloud_gateway.inference_budget import BudgetedAdapter, InferenceBudget, input_token_bound
from cloud_gateway.providers.base import ProviderReply, ProviderRequest, StreamPart, UpstreamError, Usage
from cloud_gateway.store import GatewayStore
from gateway_stubs import Device, Output, gateway_config, harness

NOW = 1792716361.0  # 2026-10-23T00:46:01Z


def config(**quotas):
    return load_config(quotas={"deployment_total_spend_usd": 1.0, **quotas})


def request(**body) -> ProviderRequest:
    model = load_config().providers["nebius"].models["fast-model"]
    return ProviderRequest(
        model,
        {"messages": [{"role": "user", "content": "Help me with algebra."}], "max_tokens": 64, **body},
        "fake-session-pseudonym",
    )


@dataclass
class Adapter:
    usage: Usage = field(default_factory=lambda: Usage(100, 20))
    fail: bool = False
    sends: int = 0

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.sends += 1
        if self.fail:
            raise UpstreamError("timeout")
        return ProviderReply({"choices": [{"message": {"content": "A hint."}}]}, self.usage)

    async def stream(self, request: ProviderRequest) -> AsyncGenerator[StreamPart]:
        self.sends += 1
        yield StreamPart({"choices": [{"delta": {"content": "A hint."}}]})
        if self.fail:
            raise UpstreamError("network_unavailable")
        yield StreamPart(None, self.usage)

    async def aclose(self) -> None:
        pass


@pytest.mark.parametrize("limit", ["deployment_daily_spend_usd", "deployment_total_spend_usd"])
def test_zero_cap_blocks_before_provider_send(tmp_path: Path, limit: str) -> None:
    store = GatewayStore(tmp_path)
    adapter = Adapter()
    bounded = BudgetedAdapter(adapter, InferenceBudget(config(**{limit: 0}), store, lambda: NOW))
    with pytest.raises(UpstreamError, match="budget exhausted"):
        asyncio.run(bounded.complete(request()))
    assert adapter.sends == 0
    store.close()


def test_parallel_connections_cannot_spend_the_same_headroom(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    limited = config(deployment_total_spend_usd=0.003, deployment_max_output_tokens=1024)
    InferenceBudget(limited, store, lambda: NOW)
    store.close()

    def reserve(_: int) -> bool:
        connection = GatewayStore(tmp_path)
        try:
            budget = InferenceBudget(limited, connection, lambda: NOW)
            budget.reserve(request(max_tokens=1024))
            return True
        except UpstreamError:
            return False
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(reserve, range(8))) == 1


def test_known_usage_settles_once_and_counters_survive_purge_restart_and_midnight(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    clock = [NOW]
    budget = InferenceBudget(config(), store, lambda: clock[0])
    key, bounded = budget.reserve(request())
    assert bounded.body["max_completion_tokens"] == 64 and "max_tokens" not in bounded.body
    held = budget.snapshot()["held_usd"]
    assert held > 0
    budget.settle(key, bounded, Usage(100, 20))
    budget.settle(key, bounded, Usage(100, 20))
    assert budget.snapshot() == {"spent_usd": 0.000048, "today_usd": 0.000048, "held_usd": 0}
    store.purge(NOW + 100 * 86400, 1)
    store.close()
    reopened = GatewayStore(tmp_path)
    clock[0] += 86400
    restricted = InferenceBudget(config(deployment_total_spend_usd=held + 0.000047), reopened, lambda: clock[0])
    assert restricted.snapshot() == {"spent_usd": 0.000048, "today_usd": 0, "held_usd": 0}
    with pytest.raises(UpstreamError, match="budget exhausted"):
        restricted.reserve(request())
    reopened.close()


def test_daily_spend_resets_but_unknown_reservations_do_not(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    clock = [NOW]
    budget = InferenceBudget(config(deployment_daily_spend_usd=0.002), store, lambda: clock[0])
    key, bounded = budget.reserve(request())
    budget.settle(key, bounded, Usage(100, 20))
    clock[0] += 86400
    budget.reserve(request())
    assert budget.snapshot()["today_usd"] == 0
    clock[0] += 86400
    with pytest.raises(UpstreamError, match="budget exhausted"):
        budget.reserve(request())
    store.close()


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("unknown", ["timeout", "missing_usage"])
def test_failures_and_missing_usage_keep_the_upper_bound(tmp_path: Path, stream: bool, unknown: str) -> None:
    store = GatewayStore(tmp_path)
    budget = InferenceBudget(config(), store, lambda: NOW)
    adapter = Adapter(usage=Usage() if unknown == "missing_usage" else Usage(100, 20), fail=unknown == "timeout")
    bounded = BudgetedAdapter(adapter, budget)

    async def run() -> None:
        if stream:
            _ = [part async for part in bounded.stream(request())]
        else:
            await bounded.complete(request())

    if unknown == "timeout":
        with pytest.raises(UpstreamError):
            asyncio.run(run())
    else:
        asyncio.run(run())
    assert adapter.sends == 1
    assert budget.snapshot()["held_usd"] > 0 and budget.snapshot()["spent_usd"] == 0
    store.close()


def test_cancelled_stream_retains_reservation(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    budget = InferenceBudget(config(), store, lambda: NOW)

    async def run() -> None:
        stream = BudgetedAdapter(Adapter(), budget).stream(request())
        await anext(stream)
        await stream.aclose()

    asyncio.run(run())
    assert budget.snapshot()["held_usd"] > 0
    store.close()


def test_completed_stream_releases_unused_reservation(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    budget = InferenceBudget(config(), store, lambda: NOW)

    async def run() -> None:
        return [part async for part in BudgetedAdapter(Adapter(), budget).stream(request())]

    asyncio.run(run())
    assert budget.snapshot()["spent_usd"] == 0.000048 and budget.snapshot()["held_usd"] == 0
    store.close()


def test_approval_expiry_and_output_bound_are_enforced(tmp_path: Path) -> None:
    store = GatewayStore(tmp_path)
    clock = [NOW]
    budget = InferenceBudget(
        config(deployment_budget_expires_at="2026-11-02T00:46:01Z", deployment_max_output_tokens=128),
        store,
        lambda: clock[0],
    )
    _, bounded = budget.reserve(request(max_tokens=64000, max_completion_tokens=8000))
    assert bounded.body["max_completion_tokens"] == 128
    clock[0] += 10 * 86400
    with pytest.raises(UpstreamError, match="period has ended"):
        budget.reserve(request())
    store.close()


def test_all_gateway_provider_paths_share_budget(tmp_path: Path) -> None:
    async def run() -> None:
        h = harness(gateway_config(tmp_path, slots={"primary": "nebius"}, quotas={"deployment_total_spend_usd": 0}))
        device = Device()
        await device.login(h.client)
        response = await device.chat(
            h.client, {"model": "primary/fast-model", "messages": [{"role": "user", "content": "Help."}]}
        )
        assert response.status_code == 429
        assert h.stubs["nebius"].seen == []
        gw = h.client._transport.app.state.gateway
        _, study_adapter, model = gw.providers.resolve(gw.config.study_model)
        with pytest.raises(UpstreamError, match="budget exhausted"):
            await study_adapter.complete(ProviderRequest(model, request().body, "fake-study-session"))
        assert h.stubs["nebius"].seen == []
        await h.client.aclose()

    asyncio.run(run())


def test_gateway_counts_real_stream_usage_and_caps_output(tmp_path: Path) -> None:
    async def run() -> None:
        h = harness(
            gateway_config(
                tmp_path,
                slots={"primary": "nebius"},
                quotas={"deployment_total_spend_usd": 1, "deployment_max_output_tokens": 128},
            )
        )
        device = Device()
        await device.login(h.client)
        h.stubs["nebius"].say(Output(text="A hint."))
        response = await device.chat(
            h.client,
            {"model": "primary/fast-model", "stream": True, "messages": [{"role": "user", "content": "Help."}]},
        )
        assert response.status_code == 200
        assert h.stubs["nebius"].seen[-1].body["max_completion_tokens"] == 128
        gw = h.client._transport.app.state.gateway
        assert gw.inference_budget.snapshot()["held_usd"] == 0
        assert gw.inference_budget.snapshot()["spent_usd"] > 0
        await h.client.aclose()

    asyncio.run(run())


@pytest.mark.parametrize(
    "overrides",
    [{"voice_enabled": True}, {"ask_search": {"url": "https://search.example.invalid", "secret": "fake-search-key"}}],
)
def test_unbudgeted_paid_services_cannot_be_enabled(overrides) -> None:
    with pytest.raises(ValueError, match="does not cover voice or search"):
        load_config(quotas={"deployment_total_spend_usd": 1}, **overrides)


@pytest.mark.parametrize("amount", [float("inf"), float("nan"), -1])
def test_invalid_budget_limits_are_refused(amount: float) -> None:
    with pytest.raises(ValueError):
        config(deployment_total_spend_usd=amount)


@pytest.mark.parametrize(
    "body",
    [
        {"max_tokens": -1},
        {"max_tokens": "100"},
        {"max_tokens": 1.5},
        {"messages": [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "fake-image"}}]}]},
    ],
)
def test_unbounded_inputs_are_refused_before_sending(tmp_path: Path, body: dict) -> None:
    store = GatewayStore(tmp_path)
    adapter = Adapter()
    budget = InferenceBudget(config(), store, lambda: NOW)
    with pytest.raises(UpstreamError):
        asyncio.run(BudgetedAdapter(adapter, budget).complete(request(**body)))
    assert adapter.sends == 0 and budget.snapshot()["held_usd"] == 0
    store.close()


def image_request(data: bytes = b"\xff\xd8\xffimage") -> ProviderRequest:
    model = load_config().providers["nebius"].models["vision-model"]
    return ProviderRequest(
        model,
        {
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Transcribe the notes."},
                        {
                            "type": "image_url",
                            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(data).decode()},
                        },
                    ],
                }
            ],
            "max_tokens": 4096,
        },
        "",
    )


def test_images_reserve_full_context_independently_of_compressed_size_and_settle_actual_usage(tmp_path):
    small, large = image_request(), image_request(b"\xff\xd8\xff" + b"x" * 1_999_997)
    assert input_token_bound(small) == input_token_bound(large) > 32768
    store = GatewayStore(tmp_path)
    budget = InferenceBudget(config(), store, lambda: NOW)
    adapter = Adapter()
    asyncio.run(BudgetedAdapter(adapter, budget).complete(large))
    assert adapter.sends == 1 and budget.snapshot()["held_usd"] == 0
    assert 0 < budget.snapshot()["spent_usd"] < 0.001
    store.close()


@pytest.mark.parametrize("bad", ["remote", "multiple", "oversize", "invalid"])
def test_vision_budget_rejects_unbounded_or_external_images_before_sending(tmp_path, bad):
    asked = image_request(b"\xff\xd8\xff" + b"x" * 2_000_000) if bad == "oversize" else image_request()
    parts = asked.body["messages"][0]["content"]
    if bad == "remote":
        parts[1]["image_url"]["url"] = "https://example.org/private.jpg"
    if bad == "multiple":
        parts.append(parts[1].copy())
    if bad == "invalid":
        parts[1]["image_url"]["url"] = "data:image/jpeg;base64,!!!!"
    store = GatewayStore(tmp_path)
    adapter = Adapter()
    budget = InferenceBudget(config(), store, lambda: NOW)
    with pytest.raises(UpstreamError):
        asyncio.run(BudgetedAdapter(adapter, budget).complete(asked))
    assert adapter.sends == 0 and budget.snapshot()["held_usd"] == 0
    store.close()
