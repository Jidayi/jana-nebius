"""The gateway's HTTP API (`/v1`, minor version in the `Jana-Gateway-Version` header, ARC-29).

Device credentials and tokens (SEC-21):
  POST /v1/devices                                  {public_key, entitlement, licence_id?} -> 201 {credential_id}
  POST /v1/auth/challenge                           {credential_id} -> {nonce, expires_in}
  POST /v1/auth/token                               {credential_id, nonce, signature} -> {access_token, expires_in}
  POST /admin/v1/credentials/{credential_id}/revoke licence portal, admin bearer secret -> 204
Model calls (ARC-12, MDL-25, MDL-26, SEC-20, OBS-22):
  POST /v1/chat/completions                         OpenAI chat-completions body, model "<slot>/<alias>"
Cloud voice (VOC-28, `cloud_gateway.voice`):
  WS /v1/voice/realtime                             the Realtime wire subset (VOC-25) plus the device voice tunnel
Probes (ARC-08, OBS-22):
  GET /v1/ping -> 204;  GET /v1/status -> {status: ok | degraded | outage}

Every device-facing body is read through the gateway contract and every reply built through its models (D39):
`DeviceRegistration`, `ChallengeRequest`, `TokenRequest` and `ChatCompletionRequest` in; `DeviceRegistered`,
`Challenge`, `AccessToken`, `GatewayStatus` and `GatewayError` out. The checks keep their order of meaning: a body
too large (413), a refused credential (401), a profile field or id (422 minimisation, MDL-25) and an unknown model
(404) answer as before; a chat body the contract does not accept then answers 400 before any provider sees it.

Per request the gateway records metadata only (store.RequestRecord). Nothing here logs or stores a body, a client
address or a pseudonym."""

from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cloud_gateway import minimise
from cloud_gateway.auth import Authenticator, AuthError, RegistrationError, Session
from cloud_gateway.config import GatewayConfig, ModelSpec
from cloud_gateway.contracts import errors as contract_errors
from cloud_gateway.contracts.cloud.gateway import (
    AccessToken,
    Challenge,
    ChallengeRequest,
    ChatCompletionRequest,
    DeviceRegistered,
    GatewayStatus,
    TokenRequest,
)
from cloud_gateway.custody import SecretSource, secret_source
from cloud_gateway.errors import DeviceError, auth_error, device_error, error_body, gateway_quota
from cloud_gateway.health import UpstreamHealth, evaluate_objectives
from cloud_gateway.inference_budget import InferenceBudget
from cloud_gateway.operations import GatewayOperations
from cloud_gateway.providers import ClientFactory, Providers, default_client
from cloud_gateway.providers.base import ProviderAdapter, ProviderRequest, StreamPart, UpstreamError, Usage
from cloud_gateway.quotas import AlertSink, Quotas, cost_usd, log_alert
from cloud_gateway.store import GatewayStore, RequestRecord

VERSION = "1.1"
FEATURE = "cloud_tier"
PSEUDONYM_HEADER = "x-session-pseudonym"
CONTRACT = "cloud/gateway#/$defs/"
log = logging.getLogger("cloud_gateway")


def _error(error: DeviceError) -> JSONResponse:
    return JSONResponse(error.body(), status_code=error.status, headers=error.headers())


def _plain_error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(error_body(code, message), status_code=status)


def _conforms(definition: str, body: dict[str, Any]) -> bool:
    return not contract_errors(CONTRACT + definition, body)


def _upstream(raised: Exception) -> UpstreamError:
    """An adapter failure as one classified error. Anything unexpected is logged by type only, never with a
    traceback or message that could carry request or reply text (OBS-22)."""
    if isinstance(raised, UpstreamError):
        return raised
    log.error("adapter failure %s", type(raised).__name__)
    malformed = isinstance(raised, (TypeError, KeyError, AttributeError, ValueError))
    return UpstreamError("format_error" if malformed else "bad_response", type(raised).__name__)


@dataclass
class _Call:
    session: Session
    device_hash: str
    provider: str
    adapter: ProviderAdapter
    model: ModelSpec
    started: float
    role: str = "unspecified"
    feature: str = FEATURE


class Gateway:
    def __init__(
        self,
        config: GatewayConfig,
        secrets: SecretSource,
        clock: Callable[[], float],
        client_factory: ClientFactory,
        alerts: AlertSink,
    ) -> None:
        self.config = config
        self.secrets = secrets
        self.clock = clock
        self.alerts = alerts
        self.store = GatewayStore(config.storage_dir)
        self.auth = Authenticator(config, self.store, clock)
        bounded = (config.quotas.deployment_daily_spend_usd is not None
                   or config.quotas.deployment_total_spend_usd is not None
                   or config.quotas.deployment_budget_expires_at is not None)
        self.inference_budget = InferenceBudget(config, self.store, clock) if bounded else None
        self.providers = Providers(config, secrets, client_factory, budget=self.inference_budget)
        self.quotas = Quotas(config, self.store, alerts)
        self.operations = GatewayOperations(config.storage_dir, config.operations, alerts=alerts)
        self.health = UpstreamHealth(config.objectives)
        self.store.purge(clock(), config.metadata_retention_days)
        self._purged_hour = int(clock() // 3600)

    async def json_body(self, request: Request, limit: int | None = None) -> dict[str, Any] | JSONResponse:
        """The JSON object body, read no further than `limit` bytes (the declared length is checked first, then the
        stream as it arrives), so an oversized body is refused before it is held in memory (MDL-23)."""
        cap = limit if limit is not None else self.config.max_request_bytes
        declared = request.headers.get("content-length")
        if declared is not None and (not declared.isdigit() or int(declared) > cap):
            return _error(device_error("payload_too_large"))
        chunks: list[bytes] = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > cap:
                return _error(device_error("payload_too_large"))
            chunks.append(chunk)
        raw = b"".join(chunks)
        try:
            body = json.loads(raw or b"{}")
        except ValueError:
            return _plain_error(400, "invalid_request", "The body is not JSON.")
        if not isinstance(body, dict):
            return _plain_error(400, "invalid_request", "The body must be a JSON object.")
        return body

    def finish(self, call: _Call, status: int, outcome: str, usage: Usage, cost: float | None = None) -> None:
        """Record one upstream call. `cost` is given for services not priced per token (speech by the minute or
        character, VOC-28); otherwise it comes from the model's token price."""
        now = self.clock()
        if cost is None:
            cost = cost_usd(self.config.prices.get(call.model.id), usage)
        record = RequestRecord(
            at=now,
            device_hash=call.device_hash,
            licence_id=call.session.licence_id,
            feature=call.feature,
            model=call.model.id,
            tokens_in=usage.input_tokens,
            tokens_out=usage.output_tokens,
            tokens_cached=usage.cached_tokens,
            latency_ms=int((now - call.started) * 1000),
            status=status,
            outcome=outcome,
            cost_usd=cost,
        )
        self.store.record(record)
        self.quotas.spent(call.session.account, call.session.period_start, now, cost)
        self.operations.record_cost(
            now,
            call.provider,
            call.model.id,
            call.role,
            call.session.licence_id,
            usage.input_tokens,
            usage.cached_tokens,
            usage.output_tokens,
            cost,
        )
        self.health.record(now, outcome)
        log.info(
            "request licence=%s device=%s feature=%s model=%s status=%d outcome=%s tokens_in=%d tokens_out=%d "
            "latency_ms=%d cost_usd=%.6f", record.licence_id, record.device_hash, call.feature, record.model, status,
            outcome, record.tokens_in, record.tokens_out, record.latency_ms, cost,
        )  # fmt: skip
        self.quotas.check_anomaly(call.device_hash, call.session.licence_id, now)
        hour = int(now // 3600)
        if hour != self._purged_hour:
            self._purged_hour = hour
            self.store.purge(now, self.config.metadata_retention_days)

    async def chat(self, request: Request) -> Response:
        started = self.clock()
        try:
            session = self.auth.authenticate(request.headers.get("authorization"))
        except AuthError as exc:
            return _error(auth_error(str(exc)))
        if self.operations.blocked("", "", session.licence_id):
            return _plain_error(503, "provider_unavailable", "Cloud service is unavailable; continue locally.")
        if not minimise.valid_pseudonym(request.headers.get(PSEUDONYM_HEADER)):
            return _plain_error(400, "pseudonym_required", "X-Session-Pseudonym must be a random session pseudonym.")
        body = await self.json_body(request)
        if isinstance(body, JSONResponse):
            return body
        refused = minimise.refusal(request.headers, body)
        if refused:
            return _plain_error(422, "minimisation", f"Refused: {refused}.")
        resolved = self.providers.resolve(body.get("model"))
        if resolved is None:
            return _error(device_error("model_not_found"))
        if not _conforms("ChatCompletionRequest", body):
            return _plain_error(400, "invalid_request", "The request does not match the gateway's chat contract.")
        asked = ChatCompletionRequest.model_validate(body)
        provider, adapter, model = resolved
        fallback = self.providers.resolve("fallback/" + str(body.get("model", "")).split("/")[-1])
        chosen = self.operations.choose(
            provider, fallback[0] if fallback else None, model.id, session.licence_id, started
        )
        if chosen is None:
            return _plain_error(503, "provider_unavailable", "Cloud service is unavailable; continue locally.")
        if chosen != provider and fallback is not None:
            provider, adapter, model = fallback
            if self.operations.blocked(provider, model.id, session.licence_id):
                return _plain_error(503, "provider_unavailable", "Cloud service is unavailable; continue locally.")
        # Quotas and spend are the subscription's, shared by its credentials (SEC-20, BIZ-07): a new credential adds
        # no headroom. The day's hash of the account stands for "the device" in the metadata (OBS-22).
        device_hash = self.store.device_hash(session.account, started)
        over = self.quotas.refusal(session.account, device_hash, session.licence_id, started,
                                   period_start=session.period_start, seats=session.seats)  # fmt: skip
        if over is not None:
            return _error(gateway_quota(over[0], over[1]))
        role = request.headers.get("x-jana-role", "unspecified")
        if role not in {
            "coach",
            "solver",
            "checker",
            "router",
            "reflection",
            "vision",
            "title",
            "compaction",
            "input_guard",
            "rule_matcher",
        }:
            role = "unspecified"
        call = _Call(session, device_hash, provider, adapter, model, started, role)
        upstream = ProviderRequest(model, minimise.forwarded(body), request.headers[PSEUDONYM_HEADER])
        if asked.stream:
            include_usage = bool(asked.stream_options is not None and asked.stream_options.include_usage)
            return await self._stream(call, upstream, include_usage)
        try:
            reply = await adapter.complete(upstream)
        except Exception as raised:  # every failure becomes one classified reply
            failure = _upstream(raised)
            error = device_error(failure.reason, failure.retry_after_s, failure.param)
            self.finish(call, error.status, failure.reason, Usage())
            return _error(error)
        self.finish(call, 200, "ok", reply.usage)
        return JSONResponse(reply.body)

    async def _stream(self, call: _Call, upstream: ProviderRequest, include_usage: bool) -> Response:
        parts = call.adapter.stream(upstream)
        try:
            first = await anext(parts)
        except StopAsyncIteration:
            self.finish(call, 502, "bad_response", Usage())
            return _error(device_error("bad_response"))
        except Exception as raised:
            failure = _upstream(raised)
            error = device_error(failure.reason, failure.retry_after_s, failure.param)
            self.finish(call, error.status, failure.reason, Usage())
            return _error(error)

        async def events() -> AsyncIterator[bytes]:
            usage, outcome, last = Usage(), "ok", None
            try:
                part: StreamPart | None = first
                while part is not None:
                    if part.chunk is not None:
                        last = part.chunk
                        yield b"data: " + json.dumps(part.chunk, separators=(",", ":")).encode() + b"\n\n"
                    if part.usage is not None:
                        usage = part.usage
                    part = await anext(parts, None)
                if include_usage:
                    tail = {"id": (last or {}).get("id", "chatcmpl"), "object": "chat.completion.chunk",
                            "created": (last or {}).get("created", int(time.time())),
                            "model": (last or {}).get("model", call.model.id), "choices": [],
                            "usage": usage.openai()}  # fmt: skip
                    yield b"data: " + json.dumps(tail, separators=(",", ":")).encode() + b"\n\n"
                yield b"data: [DONE]\n\n"
            except Exception as raised:
                failure = _upstream(raised)
                # Mid-stream failure: an error event and no [DONE]; the device discards the partial candidate and
                # regenerates locally (ARC-12).
                outcome = failure.reason
                payload = device_error(failure.reason, failure.retry_after_s).body()
                yield b"data: " + json.dumps(payload).encode() + b"\n\n"
            finally:
                await parts.aclose()
                self.finish(call, 200, outcome, usage)

        return StreamingResponse(
            events(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"}
        )

    def admin_ok(self, authorization: str | None) -> bool:
        secret = self.secrets.get("admin_token")
        if secret is None or not authorization or not authorization.startswith("Bearer "):
            return False
        return hmac.compare_digest(authorization.removeprefix("Bearer ").encode(), secret.reveal().encode())


class _VersionHeader:
    """Adds the minor version header to every response (ARC-29), without buffering streamed replies."""

    def __init__(self, app: ASGIApp, budget_enabled: bool = False) -> None:
        self.app = app
        self.budget_enabled = budget_enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                message["headers"] = [
                    *message.get("headers", []), (b"jana-gateway-version", VERSION.encode()),
                    (b"x-jana-inference-budget", b"enabled" if self.budget_enabled else b"disabled"),
                ]
            await send(message)

        await self.app(scope, receive, with_header)


def _file_logging(config: GatewayConfig) -> None:
    if config.log_path is None:
        return
    config.log_path.parent.mkdir(parents=True, exist_ok=True)
    target = str(config.log_path.resolve())
    if any(isinstance(h, logging.FileHandler) and h.baseFilename == target for h in log.handlers):
        return
    handler = logging.FileHandler(target)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)


def create_app(
    config: GatewayConfig,
    *,
    secrets: SecretSource | None = None,
    clock: Callable[[], float] = time.time,
    client_factory: ClientFactory = default_client,
    alerts: AlertSink = log_alert,
    speech: Any = None,
) -> FastAPI:
    """`speech` is cloud voice's `SpeechStack` (or a factory taking the gateway); by default it is built from
    `voice_google` when voice is switched on."""
    _file_logging(config)
    gw = Gateway(config, secrets if secrets is not None else secret_source(config), clock, client_factory, alerts)

    async def probe_providers() -> None:
        policy = config.operations
        if policy is None:
            return
        while True:
            for name in policy.qualified_providers:
                adapter = gw.providers.adapters.get(name)
                spec = config.providers.get(name)
                if adapter is None or spec is None or not spec.models:
                    continue
                model = next(iter(spec.models.values()))
                started = clock()
                try:
                    await asyncio.wait_for(
                        adapter.complete(
                            ProviderRequest(
                                model,
                                {"messages": [{"role": "user", "content": "Reply with OK."}]},
                                "synthetic-ops-probe",
                            )
                        ),
                        timeout=policy.latency_objective_s * policy.latency_multiple,
                    )
                    ok = True
                except Exception:
                    ok = False
                gw.operations.probe(name, ok, max(0.0, clock() - started), clock())
            await asyncio.sleep(policy.probe_interval_s)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async def objectives() -> None:
            while True:
                await asyncio.sleep(config.objectives.check_interval_s)
                evaluate_objectives(gw.store, config.objectives, clock(), alerts)

        async def study_expiry() -> None:
            while True:
                await asyncio.sleep(15)
                app.state.study.sweep()

        study_task = asyncio.create_task(study_expiry())
        task = asyncio.create_task(objectives())
        probe_task = asyncio.create_task(probe_providers())
        try:
            yield
        finally:
            task.cancel()
            study_task.cancel()
            probe_task.cancel()
            await asyncio.gather(task, probe_task, study_task, return_exceptions=True)
            for key in list(app.state.study.buffers):
                app.state.study.drop(key)
            for connection in list(app.state.voice.live.values()):
                await connection.close()
            await app.state.voice.stack.aclose()
            await gw.providers.aclose()
            gw.store.close()

    app = FastAPI(title="Jana cloud gateway", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.gateway = gw
    from cloud_gateway.study import add_routes as study_routes

    app.state.study = study_routes(app, gw)
    from cloud_gateway.voice import add_routes as voice_routes

    app.state.voice = voice_routes(app, gw, speech)
    from cloud_gateway.ask import add_routes as ask_routes

    app.state.ask = ask_routes(app, gw)  # Ask anything (STU-20)

    app.add_middleware(_VersionHeader, budget_enabled=gw.inference_budget is not None)

    @app.post("/v1/devices", status_code=201)
    async def register(request: Request) -> Response:
        body = await gw.json_body(request, config.max_auth_request_bytes)
        if isinstance(body, JSONResponse):
            return body
        try:
            credential_id = gw.auth.register(body)
        except RegistrationError as exc:
            return _plain_error(exc.status, "registration", str(exc))
        return JSONResponse(DeviceRegistered(credential_id=credential_id).model_dump(), status_code=201)

    @app.post("/v1/auth/challenge")
    async def challenge(request: Request) -> Response:
        body = await gw.json_body(request, config.max_auth_request_bytes)
        if isinstance(body, JSONResponse):
            return body
        if not _conforms("ChallengeRequest", body):  # a credential id that cannot exist is a refused credential
            return _error(auth_error("the challenge request does not match its contract"))
        asked = ChallengeRequest.model_validate(body)
        try:
            nonce, ttl = gw.auth.challenge(asked.credential_id)
        except AuthError as exc:
            return _error(auth_error(str(exc)))
        return JSONResponse(Challenge(nonce=nonce, expires_in=ttl).model_dump())

    @app.post("/v1/auth/token")
    async def token(request: Request) -> Response:
        body = await gw.json_body(request, config.max_auth_request_bytes)
        if isinstance(body, JSONResponse):
            return body
        if not _conforms("TokenRequest", body):
            return _error(auth_error("the token request does not match its contract"))
        asked = TokenRequest.model_validate(body)
        try:
            access, ttl = gw.auth.token(asked.credential_id, asked.nonce, asked.signature)
        except AuthError as exc:
            return _error(auth_error(str(exc)))
        granted = AccessToken.model_validate({"access_token": access, "token_type": "Bearer", "expires_in": ttl})
        return JSONResponse(granted.model_dump())

    @app.post("/admin/v1/credentials/{credential_id}/revoke")
    async def revoke(credential_id: str, request: Request) -> Response:
        if not gw.admin_ok(request.headers.get("authorization")):
            return _error(auth_error("admin authorisation required"))
        if not gw.auth.revoke(credential_id):
            return _plain_error(404, "not_found", "Unknown credential.")
        return Response(status_code=204)

    @app.post("/admin/v1/operations/switch")
    async def operations_switch(request: Request) -> Response:
        if not gw.admin_ok(request.headers.get("authorization")):
            return _error(auth_error("admin authorisation required"))
        body = await gw.json_body(request, config.max_auth_request_bytes)
        if isinstance(body, JSONResponse):
            return body
        try:
            if set(body) != {"kind", "target", "disabled", "actor", "reason", "incident_id"}:
                raise ValueError("invalid fields")
            gw.operations.switch(
                body["kind"],
                body["target"],
                body["disabled"],
                body["actor"],
                body["reason"],
                body["incident_id"],
                clock(),
            )
        except (ValueError, TypeError, AttributeError):
            return _plain_error(400, "invalid_request", "Invalid operations switch.")
        return JSONResponse({"applied": True})

    @app.post("/v1/chat/completions")
    async def chat(request: Request) -> Response:
        return await gw.chat(request)

    @app.get("/v1/ping")
    async def ping() -> Response:
        return Response(status_code=204, headers={"Cache-Control": "no-store"})

    @app.get("/v1/status")
    async def status() -> Response:
        body = GatewayStatus(status=gw.health.status(clock())).model_dump()
        return JSONResponse(body, headers={"Cache-Control": "no-store"})

    return app
