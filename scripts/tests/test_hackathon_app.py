"""Network-free checks of the full-app host; no provider key or paid inference."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from agent_core.api.core import CoreService
from agent_core.config import Settings
from agent_core.engine.assembly import _pin
from agent_core.store import subscription
from agent_core.store.keystore import FileKeyStore
from cloud_gateway.store import GatewayStore
from jana_tools import REPO_ROOT
from jana_tools import hackathon_app as host


@pytest.mark.parametrize(
    "url",
    [
        "http://localhost/v1/ping",
        "https://example.com/v1/ping",
        "https://localhost:444/v1/ping",
        "https://user:password@localhost/v1/ping",
        "https://localhost/private",
    ],
)
def test_transport_refuses_other_destinations(url: str) -> None:
    async def run() -> None:
        seen = []

        async def reply(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(204)

        async with httpx.AsyncClient(transport=host.GatewayHop(8081, httpx.MockTransport(reply))) as client:
            with pytest.raises(httpx.ConnectError):
                await client.get(url)
        assert not seen

    asyncio.run(run())


def test_transport_streaming_auth_and_compatibility() -> None:
    async def run() -> None:
        seen = []

        async def reply(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            assert request.url == "http://127.0.0.1:8081/v1/chat/completions"
            assert request.headers["authorization"] == "Bearer synthetic-device-token"
            body = json.loads(await request.aread())
            assert body["tool_choice"] == "auto"
            assert body["messages"][0]["content"].startswith("Jana required output contract.")
            assert int(request.headers["content-length"]) == len(request.content)
            return httpx.Response(200, content=b'data: {"choices":[]}\n\ndata: [DONE]\n\n')

        body = {
            "messages": [],
            "tool_choice": "required",
            "response_format": {"type": "json_schema", "json_schema": {"schema": {"type": "object"}}},
        }
        async with httpx.AsyncClient(transport=host.GatewayHop(8081, httpx.MockTransport(reply))) as client:
            async with client.stream(
                "POST",
                "https://localhost/v1/chat/completions",
                json=body,
                headers={"authorization": "Bearer synthetic-device-token"},
            ) as response:
                assert b"[DONE]" in await response.aread()
        assert len(seen) == 1 and body["tool_choice"] == "required"

    asyncio.run(run())


def test_study_is_online_only_and_speech_is_not_billed() -> None:
    settings = host.settings_for_browser(Settings(study_offline_enabled=True))
    assert settings.study_workspace_enabled
    assert not settings.study_offline_enabled and not settings.cloud_voice_enabled
    assert settings.study_batch_char_limit == 16000


def test_local_model_pin_keeps_cloud_candidates() -> None:
    data = {
        "tiers": {
            "fast": ["local:old", "cloud:primary/fast-model"],
            "strong": ["cloud:primary/strong-model", "local:old"],
        }
    }
    _pin(data, "nvidia-nemotron-nano-4b")
    assert data["tiers"]["fast"] == ["local:nvidia-nemotron-nano-4b", "cloud:primary/fast-model"]
    assert data["tiers"]["strong"] == ["local:nvidia-nemotron-nano-4b", "cloud:primary/strong-model"]


def test_sponsor_never_grants_consent_and_restart_keeps_credential(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = tmp_path / "gateway.toml"
    original = (REPO_ROOT / "services/cloud-gateway/deploy/nebius-dev.toml").read_text()
    config.write_text(original.replace('"/tmp/jana-nebius-gateway"', json.dumps(str(tmp_path / "gateway"))))
    monkeypatch.setenv("JANA_NEBIUS_GATEWAY_CONFIG", str(config))

    async def available(_port: int) -> None:
        pass

    monkeypatch.setattr(host, "check_gateway", available)

    async def launch(ended: bool = False) -> tuple[str, bytes]:
        runtime = host.SponsoredRuntime(
            host.settings_for_browser(Settings()), REPO_ROOT / "content/agent", REPO_ROOT / "skills", tmp_path / "app"
        )
        runtime.open_stores("0.0.0")
        online = runtime.attach_online()
        assert runtime.directory is not None
        profiles = runtime.directory.summaries()["profiles"]
        if not profiles:
            runtime.directory.create(
                {
                    "display_name": "Synthetic QA",
                    "avatar": "disc-teal",
                    "level": "O",
                    "subjects": ["mathematics"],
                    "age_band": "18_plus",
                }
            )
        core = SimpleNamespace(clock_ms=online.clock_ms, on_profile_created=[], closers=[], components={})
        await host.connect(runtime, cast(CoreService, core))
        held = subscription.load(online.device)
        assert held["allowance_tokens"] == host.monthly_allowance_tokens(runtime.gateway)
        assert held["consent_needed"] and not online.features_on()
        assert held.get("ended_at") is None or ended
        for profile in runtime.directory.summaries()["profiles"]:
            with runtime.directory.open_learner(profile["profile_id"]) as conn:
                assert conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 0
        identity = online.credential.credential_id()
        assert identity is not None
        public = online.credential.public_key()
        if ended:
            held["ended_at"] = online.clock_ms()
            subscription.save(online.device, held, online.clock_ms())
            await host.connect(runtime, cast(CoreService, core))
            assert subscription.load(online.device)["ended_at"] == held["ended_at"]
        for close in core.closers:
            await close()
        await online.client.close()
        await runtime.close()
        return identity, public

    async def run() -> None:
        first = await launch()
        assert await launch(ended=True) == first
        store = GatewayStore(tmp_path / "gateway")
        assert store._db.execute("SELECT count(*) FROM credentials").fetchone()[0] == 1
        assert store._db.execute("SELECT count(*) FROM credentials WHERE revoked_at IS NOT NULL").fetchone()[0] == 0
        store.close()
        assert isinstance(host.SponsoredRuntime(Settings(), Path(), Path(), tmp_path / "app").key_store(), FileKeyStore)

    asyncio.run(run())
