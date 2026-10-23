"""Hackathon integration: actual Token Factory configuration against network-free provider stubs."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from agent_core.config import Settings
from agent_core.providers.scripted import ScriptedProvider
from agent_core.router.config import load
from agent_core.router.core import Router
from agent_core.router.online import cloud_models
from cloud_gateway.config import load_config
from cloud_gateway.custody import KeychainSecrets, secret_source
from cloud_gateway.providers.nebius import SCHEMA_NOTICE, prepare_body
from gateway_stubs import FAKE_KEYS, Device, Output, gateway_config, harness

ROOT = Path(__file__).resolve().parents[3]


def test_nebius_contract_prompt_is_exact_and_idempotent() -> None:
    schema = {"type": "object", "required": ["answer"], "properties": {"answer": {"type": "string"}}}
    body = {"messages": [{"role": "user", "content": "Synthetic question"}],
            "response_format": {"type": "json_schema", "json_schema": {"schema": schema}}}
    result = prepare_body(body)
    assert len(body["messages"]) == 1
    assert result["response_format"] == body["response_format"]
    assert result["messages"][0]["content"].startswith(SCHEMA_NOTICE)
    assert '"required":["answer"]' in result["messages"][0]["content"]
    assert prepare_body(result) == result


def test_nebius_required_tool_phase_uses_supported_auto_without_mutation() -> None:
    body = {"tool_choice": "required", "messages": [], "tools": [{"type": "function"}]}
    assert prepare_body(body) == {**body, "tool_choice": "auto"}
    assert body["tool_choice"] == "required"
    named = {**body, "tool_choice": {"type": "function", "function": {"name": "math_solve"}}}
    assert prepare_body(named) == named


@pytest.mark.parametrize("environment", ["dev", "staging", "pilot", "production"])
def test_nebius_key_is_server_environment_only(environment: str) -> None:
    source = secret_source(
        load_config(environment=environment),
        {"NEBIUS_API_KEY": "fake-nebius-key", "JANA_DEV_GEMINI_API_KEY": "fake-gemini-key"},
        KeychainSecrets(system="Plan9"),
    )
    key = source.get("nebius_api_key")
    assert key is not None and key.reveal() == "fake-nebius-key"
    assert "fake-nebius-key" not in repr(source.get("nebius_api_key"))
    assert "fake-nebius-key" not in repr(source) and "fake-gemini-key" not in repr(source)
    assert source.get("admin_token") is None
    assert (source.get("gemini_api_key") is not None) == (environment == "dev")


def test_nebius_models_prices_and_capabilities_agree() -> None:
    config = load_config()
    assert config.slots == {"primary": "nebius"}
    provider = config.providers["nebius"]
    assert provider.base_url == "https://api.tokenfactory.nebius.com/v1/"
    assert provider.models["fast-model"].id == "nvidia/nemotron-3-super-120b-a12b"
    assert provider.models["strong-model"].id == "nvidia/Nemotron-3-Ultra-550b-a55b"
    assert provider.models["small-model"].id == "nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B"
    assert config.study_model == "primary/strong-model"
    for alias, capabilities in cloud_models().items():
        price = config.prices[provider.models[alias].id]
        assert capabilities["price_in_per_mtok"] == price.input
        assert capabilities["price_out_per_mtok"] == price.output
        assert capabilities["vision"] is False


def test_nebius_request_uses_real_routing_key_and_header_only_secret(tmp_path: Path) -> None:
    async def run() -> None:
        defaults = load_config()
        h = harness(gateway_config(
            tmp_path,
            slots=dict(defaults.slots),
            providers={"nebius": defaults.providers["nebius"].model_dump()},
            prices={key: value.model_dump() for key, value in defaults.prices.items()},
        ))
        device = Device()
        await device.login(h.client)
        h.stubs["nebius"].say(Output(text="What can you subtract from both sides?"))
        request = {
            "model": "primary/fast-model",
            "messages": [{"role": "user", "content": "Help me solve 2x + 3 = 11."}],
            "reasoning_effort": "low",
            "max_tokens": 256,
        }
        # The device contract refuses caller-supplied storage settings before any provider call.
        refused = await device.chat(h.client, {**request, "store": True})
        assert refused.status_code == 400 and not h.stubs["nebius"].seen
        response = await device.chat(h.client, request)
        assert response.status_code == 200, response.text
        sent = h.stubs["nebius"].seen[-1]
        assert sent.url == "https://api.tokenfactory.nebius.com/v1/chat/completions"
        assert sent.model == "nvidia/nemotron-3-super-120b-a12b"
        assert sent.body["reasoning_effort"] == "low" and sent.body["max_tokens"] == 256
        assert sent.body["store"] is False
        assert sent.headers["authorization"] == f"Bearer {FAKE_KEYS['nebius_api_key']}"
        assert FAKE_KEYS["nebius_api_key"] not in response.text
        assert FAKE_KEYS["nebius_api_key"] not in str(sent.body)
        await h.client.aclose()

    asyncio.run(run())


def test_nebius_router_prefers_super_and_ultra_but_respects_online_switch() -> None:
    async def run() -> None:
        config = load(ROOT / "services/agent-core/agent_core/router/router.yaml")
        local = ScriptedProvider([], installed_models=["qwen3-vl-8b"])
        router = Router(config, Settings(), {"primary": ScriptedProvider([], kind="cloud"), "local": local},
                        hardware_class="mid", cloud_on=lambda role: True)
        for role, alias in (("coach", "fast-model"), ("diagnoser", "fast-model"),
                            ("solver", "strong-model"), ("checker", "strong-model")):
            _, candidates, _ = await router.candidates(role)
            assert str(candidates[0]) == f"cloud:primary/{alias}"
        router.cloud_on = lambda role: False
        _, candidates, _ = await router.candidates("coach")
        assert candidates and all(candidate.locality == "local" for candidate in candidates)

    asyncio.run(run())
