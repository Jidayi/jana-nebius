"""Run the original app against the owner's local, budgeted Nebius gateway.

Development host only. The original consent, first-use, egress ledger, profile,
assessment and Study paths remain in use. This adapter never reads a provider key.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from pathlib import Path

import httpx
from agent_core.api.__main__ import main
from agent_core.api.core import CoreService
from agent_core.config import Settings
from agent_core.engine.assembly import AppRuntime
from agent_core.net.credentials import ID_REF
from agent_core.net.layer import OnlineLayer
from agent_core.router.hardware import TutorPath
from agent_core.store import subscription as subscriptions
from agent_core.store.keystore import FileKeyStore, KeyStore, MemoryKeyStore
from cloud_gateway.config import GatewayConfig, load_config
from cloud_gateway.providers.nebius import prepare_body
from cloud_gateway.store import GatewayStore
from cloud_gateway.tier import monthly_allowance_tokens

HOST = "localhost"
log = logging.getLogger(__name__)


class GatewayHop(httpx.AsyncBaseTransport):
    """A virtual HTTPS service name mapped only to a literal loopback gateway.

    Used behind the existing egress admission checks, never for external services.
    The actual provider connection remains HTTPS in the private gateway.
    """

    def __init__(self, port: int, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not 1 <= port <= 65535:
            raise ValueError("invalid local gateway port")
        self.port = port
        self.inner = transport or httpx.AsyncHTTPTransport(trust_env=False)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if (
            request.url.scheme != "https"
            or request.url.host != HOST
            or request.url.port not in (None, 443)
            or request.url.username
            or request.url.password
            or not request.url.path.startswith("/v1/")
        ):
            raise httpx.ConnectError("Refused a destination outside the local gateway", request=request)
        url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        headers = dict(request.headers)
        headers["host"] = f"127.0.0.1:{self.port}"
        if request.method == "POST" and request.url.path == "/v1/chat/completions":
            # Apply the same idempotent provider compatibility rules as the gateway.
            # This also supports an owner's gateway that predates a host restart.
            body = prepare_body(json.loads(await request.aread()))
            headers.pop("content-length", None)
            forwarded = httpx.Request(request.method, url, headers=headers, json=body, extensions=request.extensions)
        else:
            forwarded = httpx.Request(
                request.method, url, headers=headers, stream=request.stream, extensions=request.extensions
            )
        response = await self.inner.handle_async_request(forwarded)
        if response.status_code >= 400:
            # The gateway's fixed error codes never contain prompts or credentials.
            await response.aread()
            try:
                error = response.json().get("error", {})
                log.warning(
                    f"local_gateway status={response.status_code} code={error.get('code')} param={error.get('param')}"
                )
            except (ValueError, AttributeError):
                log.warning(f"local_gateway status={response.status_code}")
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def gateway_config() -> GatewayConfig:
    path = os.environ.get("JANA_NEBIUS_GATEWAY_CONFIG")
    if not path:
        raise ValueError("Set JANA_NEBIUS_GATEWAY_CONFIG to the approved gateway configuration")
    config = load_config(Path(path))
    if (
        config.environment != "dev"
        or config.audience_host != HOST
        or config.slots.get("primary") != "nebius"
        or config.quotas.deployment_total_spend_usd is None
        or config.quotas.deployment_daily_spend_usd is None
        or config.quotas.deployment_budget_expires_at is None
    ):
        raise ValueError("The browser host requires a local Nebius gateway with daily, total and expiry limits")
    return config


class SponsoredRuntime(AppRuntime):
    def key_store(self) -> KeyStore:
        if self.release:
            raise ValueError("The local hackathon key store is development-only")
        if self.keys is None or isinstance(self.keys, MemoryKeyStore):
            self.keys = FileKeyStore(self.data_root.parent / f".{self.data_root.name}-keys", self.data_root)
        return self.keys

    def attach_online(self) -> OnlineLayer:
        layer = super().attach_online()
        if self.release:
            raise ValueError("The local hackathon adapter is not a release deployment")
        self.gateway = gateway_config()
        self.gateway_port = int(os.environ.get("JANA_NEBIUS_GATEWAY_PORT", "8081"))
        layer.hosts = {service: HOST for service in ("gateway",)}
        # Downloads/updates/voice keep their original implementations, but no such
        # external service is connected by this local inference adapter.
        layer.client._client = httpx.AsyncClient(
            transport=GatewayHop(self.gateway_port), trust_env=False, follow_redirects=False, timeout=180
        )
        return layer

    def tutor_path(self) -> TutorPath:
        # Before first-use acceptance the original engine must be able to show its
        # notice. No inference is admitted until cloud_tier_on() becomes true.
        if self.online and self.stores and self.online.cloud_effective(self.public_profile(), self.stores.learner):
            return "online"
        return super().tutor_path()

    def tutor_unavailable(self) -> bool:
        if self.tutor_path() == "online":
            return False
        if "local" not in self.providers and not self.school_server_reachable():
            return True
        return super().tutor_unavailable()


def settings_for_browser(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            # Expose the imported visual tutoring, local parent views and history
            # in the development app. This is not a release-acceptance claim.
            "build_stage": "S3",
            "study_workspace_enabled": True,
            "study_offline_enabled": False,
            "study_neural_speech_enabled": True,
            "study_batch_char_limit": 16000,
            "consent_dpia_ref": "local-synthetic-hackathon-notice",
            "cloud_voice_enabled": False,
        }
    )


async def check_gateway(port: int) -> None:
    """Fail closed unless the already-running gateway advertises its persistent cap."""
    async with httpx.AsyncClient(trust_env=False) as probe:
        reply = await probe.get(f"http://127.0.0.1:{port}/v1/ping", timeout=3)
        if reply.status_code != 204 or reply.headers.get("x-jana-inference-budget") != "enabled":
            raise ValueError("Start the approved budgeted gateway before the browser host")


async def connect(runtime: AppRuntime, core: CoreService) -> None:
    if not isinstance(runtime, SponsoredRuntime) or runtime.online is None or runtime.directory is None:
        raise ValueError("The hackathon host requires its own local runtime")
    online = runtime.online
    await check_gateway(runtime.gateway_port)
    expires = runtime.gateway.quotas.deployment_budget_expires_at
    assert expires is not None
    end_ms = int(expires.timestamp() * 1000)
    if end_ms <= core.clock_ms():
        raise ValueError("The approved inference period has expired")
    store = GatewayStore(runtime.gateway.storage_dir)
    public = online.credential.public_key()
    credential = "dcr_" + secrets.token_urlsafe(18)
    # Provision only the app host's public key. Native challenge signing and token
    # renewal still authenticate every gateway call. No provider secret is read.
    held = online.device.execute("SELECT value FROM app_settings WHERE key='hackathon_sponsor'").fetchone()
    account = json.loads(held[0]) if held else "sub_hackathon_" + secrets.token_hex(12)
    if not held:
        online.device.execute(
            "INSERT INTO app_settings VALUES ('hackathon_sponsor',?,?)", (json.dumps(account), core.clock_ms())
        )
    state, credential = store.bind_credential(
        credential,
        public,
        "lic_hackathon",
        account,
        expires.timestamp(),
        time.time(),
        runtime.gateway.devices_per_subscription,
    )
    if state not in {"added", "renewed"}:
        store.close()
        raise ValueError("The local gateway credential could not be provisioned")
    online.keys.put(ID_REF, credential.encode())
    online.credential.forget_token()
    now = core.clock_ms()
    plan = runtime.gateway.plans.paid["jana_online"]
    entitlement = subscriptions.Entitlement(
        account,
        now,
        end_ms,
        100,
        monthly_allowance_tokens(runtime.gateway),
        "lic_hackathon",
        features=tuple(plan.features),
        limits=plan.limits.model_dump(exclude_none=True),
    )

    def sponsor(_profile_id: str | None = None) -> None:
        assert runtime.directory is not None
        known = [p["profile_id"] for p in runtime.directory.summaries()["profiles"]]
        if not known:
            return
        old = subscriptions.load(online.device)
        # Ending access is sticky; a restart never silently turns it back on.
        if old.get("ended_at") is not None:
            return
        waiting = set(old.get("consent_needed", []))
        waiting.update(p for p in known if p not in old.get("profiles", []))
        record = subscriptions.record(
            entitlement, known, known, [p for p in known if p not in waiting], "hackathon_sponsor"
        )
        subscriptions.save(online.device, record, now)
        # Only the native subscription consent command turns the feature on and
        # writes profile consent. Creating a profile never authorizes inference.

    sponsor()
    core.on_profile_created.append(sponsor)
    # No local scripted or downloaded model is substituted for live cloud calls.
    runtime.providers.pop("local", None)
    if runtime.link is not None:
        runtime.link = None
    core.readiness = "ready"
    core.components["runtime"] = "ok"

    async def close() -> None:
        # The app's private device key survives a normal restart. Keep its bounded
        # credential renewable; first-use consent and the gateway expiry still apply.
        store.close()

    core.closers.append(close)


if __name__ == "__main__":
    raise SystemExit(
        asyncio.run(
            main(runtime_factory=SponsoredRuntime, settings_transform=settings_for_browser, before_ready=connect)
        )
    )
