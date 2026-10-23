"""Live Gemini check through the gateway: skipped unless JANA_LIVE_GEMINI=1.

The product owner provides the key; it is never a file in the repository or an environment variable in a release
build. It is read from the OS keychain (macOS Keychain service `jana.cloud-gateway`, account `gemini_api_key`,
via the `security` CLI; on Linux the Secret Service via `secret-tool`) or from the deployment's secret-manager mount
(`JANA_GATEWAY_SECRETS_DIR`, one file per secret). To store it on a Mac:
`security add-generic-password -s jana.cloud-gateway -a gemini_api_key -w` (prompts for the value). For this
check only, a developer's own key in the git-ignored `.env` (`JANA_DEV_GEMINI_API_KEY`, loaded into the shell) is
read too, after the keychain; the gateway under test still runs as staging, which never reads environment keys."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import httpx
import pytest
from cloud_gateway.app import create_app
from cloud_gateway.config import load_config
from cloud_gateway.custody import (
    ChainedSecrets,
    DevEnvironmentSecrets,
    KeychainSecrets,
    MountedSecretFiles,
    SecretSource,
)
from gateway_stubs import AUDIENCE, Device, licence_keys

SKIP_REASON = (
    "live Gemini test: set JANA_LIVE_GEMINI=1; the product owner provides the key through the OS keychain "
    "(macOS Keychain service jana.cloud-gateway, account gemini_api_key, read with the security CLI; Linux Secret "
    "Service via secret-tool) or the deployment's secret manager mount, never a file in the repo or an env var in a "
    "release build"
)
pytestmark = pytest.mark.skipif(os.environ.get("JANA_LIVE_GEMINI") != "1", reason=SKIP_REASON)


def _owner_secrets() -> SecretSource:
    sources: list[SecretSource] = [KeychainSecrets(), DevEnvironmentSecrets(os.environ)]
    mount = os.environ.get("JANA_GATEWAY_SECRETS_DIR")
    if mount:
        sources.insert(0, MountedSecretFiles(Path(mount)))
    return ChainedSecrets(tuple(sources))


def test_gemini_live_round_trip(tmp_path: Path) -> None:
    secrets = _owner_secrets()
    if secrets.get("gemini_api_key") is None:
        pytest.fail("JANA_LIVE_GEMINI=1 but no gemini_api_key (keychain, secrets mount or JANA_DEV_GEMINI_API_KEY)")

    async def main() -> None:
        config = load_config(
            None,
            environment="staging",
            audience_host=AUDIENCE,
            storage_dir=tmp_path,
            entitlement_keys=licence_keys(),  # a test-signed subscription entitlement registers the device (D70)
        )
        app = create_app(config, secrets=secrets)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"https://{AUDIENCE}") as client:
            device = Device()
            assert (await device.register(client)).status_code == 201
            await device.login(client)
            body = {
                "model": "primary/small-model",
                "max_tokens": 200,
                "messages": [{"role": "user", "content": "Reply with the single word: ready"}],
            }
            reply = await device.chat(client, body)
            assert reply.status_code == 200, reply.json()
            assert reply.json()["choices"][0]["message"]["content"]
            streamed = await device.chat(client, {**body, "stream": True})
            assert streamed.status_code == 200 and "data: [DONE]" in streamed.text

    asyncio.run(main())
