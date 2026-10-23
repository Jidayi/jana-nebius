"""Synthetic gateway drills. These never use a real provider or student payload."""

from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest
from agent_core.config import Settings
from cloud_gateway.operations import GatewayOperations, OperationsPolicy
from gateway_stubs import Device, FakeSecrets, gateway_config, harness


def policy():
    c = Settings()
    return OperationsPolicy(
        probe_interval_s=c.ops_probe_interval_s,
        window_s=c.ops_probe_window_s,
        failure_share=c.ops_probe_failure_share,
        latency_multiple=c.ops_probe_latency_multiple,
        latency_objective_s=c.ops_first_words_p95_s,
        healthy_s=c.ops_failback_healthy_s,
        qualified_providers=frozenset({"gemini", "openai_compat"}),
        cost_history_days=c.ops_cost_history_days,
        cost_multiple=c.ops_cost_multiple,
        metadata_retention_days=c.ops_metadata_retention_days,
    )


def test_policy_ops12_global_cloud_off(tmp_path: Path):
    async def run():
        h = harness(gateway_config(tmp_path))
        app = h.client._transport.app
        try:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="https://gateway.test"
            ) as client:
                d = Device()
                await d.register(client)
                await d.login(client)
                endpoint = "/admin/v1/operations/switch"
                payload = {
                    "kind": "global",
                    "target": "*",
                    "disabled": True,
                    "actor": "drill-operator",
                    "reason": "synthetic",
                    "incident_id": "inc-drill",
                }
                assert (await client.post(endpoint, json=payload)).status_code == 401
                response = await client.post(
                    endpoint, json=payload, headers={"authorization": "Bearer " + FakeSecrets().values["admin_token"]}
                )
                assert response.status_code == 200
                body = {"model": "primary/fast-model", "messages": [{"role": "user", "content": "synthetic"}]}
                for _ in range(5):
                    reply = await d.chat(client, body)
                    assert reply.status_code == 503 and reply.json()["error"]["code"] == "provider_unavailable"
                assert all(not p.seen for p in h.stubs.values())
                assert app.state.gateway.operations.audit()[0]["actor"] == "drill-operator"
        finally:
            await app.state.gateway.providers.aclose()
            app.state.gateway.store.close()
            await h.client.aclose()

    asyncio.run(run())


def test_policy_ops20_failover_drill(tmp_path: Path):
    cfg = policy()
    ops = GatewayOperations(tmp_path, cfg)
    assert ops.choose("gemini", "openai_compat", "model", "lic", 0) == "gemini"
    ops.probe("gemini", False, 0, 0)
    ops.probe("openai_compat", True, 1, 0)
    assert ops.choose("gemini", "openai_compat", "model", "lic", 1) == "openai_compat"
    ops.probe("openai_compat", False, 0, 1)
    assert ops.choose("gemini", "openai_compat", "model", "lic", 2) is None
    for at in range(
        cfg.window_s + cfg.probe_interval_s,
        cfg.window_s + cfg.healthy_s + 2 * cfg.probe_interval_s,
        cfg.probe_interval_s,
    ):
        ops.probe("gemini", True, 1, at)
        ops.probe("openai_compat", True, 1, at)
    assert ops.choose("gemini", "openai_compat", "model", "lic", at) == "gemini"
    for kind, target in (("provider", "gemini"), ("model", "model"), ("licence", "lic")):
        ops.switch(kind, target, True, "operator", "drill", "inc-drill", at)
        assert ops.blocked("gemini", "model", "lic")
        ops.switch(kind, target, False, "operator", "recovered", "inc-drill", at)
    with pytest.raises(ValueError):
        ops.switch("unknown", "x", True, "operator", "", "", at)
    assert len(GatewayOperations(tmp_path, cfg).audit()) == 6


def test_ops_cost_metadata_groups_and_daily_spike(tmp_path: Path):
    c = Settings()
    cfg = policy()
    alerts = []
    ops = GatewayOperations(tmp_path, cfg, alerts=lambda kind, detail: alerts.append((kind, detail)))
    now = 1792108800.0
    for day in range(c.ops_cost_history_days, 0, -1):
        ops.record_cost(now - day * 86400, "gemini", "model", "coach", "lic_synthetic", 1, 0, 1, 1.0)
    ops.record_cost(now, "gemini", "model", "coach", "lic_synthetic", 3, 0, 3, 3.0)
    assert any(kind == "ops19_daily_spike" for kind, _ in alerts)
    grouped = ops.cost_groups(now)
    assert grouped[0]["provider"] == "gemini" and grouped[0]["cost_usd"] == 3.0
    assert set(grouped[0]) == {
        "day",
        "provider",
        "model",
        "role",
        "licence_id",
        "tokens_in",
        "tokens_cached",
        "tokens_out",
        "cost_usd",
    }
