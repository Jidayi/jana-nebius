"""Stub provider servers and a device-side client for the gateway tests. No test reaches a real provider.

Each stub is an httpx transport handler that records every request and replays provider-shaped replies (Gemini's
REST API or an OpenAI-compatible endpoint) for a scripted model output, so the same conformance checks can run
against either adapter. The keys here are obviously fake and never match a provider key pattern."""

from __future__ import annotations

import base64
import json
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx
from cloud_gateway.app import create_app
from cloud_gateway.auth import signed_message
from cloud_gateway.config import GatewayConfig, load_config
from cloud_gateway.custody import Secret
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from signing_service.hierarchy import dev_signer, dev_trust
from signing_service.keys import Purpose

AUDIENCE = "gateway.test"
LICENCE = "lic_school_one"
PERIOD = ("2026-09-01T00:00:00.000Z", "2027-01-01T00:00:00.000Z")  # holds the harness clock's default time


def licence_keys() -> dict[str, str]:
    """The test hierarchy's licence intermediate, as the gateway's `entitlement_keys`."""
    signer = dev_signer(Purpose.LICENCE)
    return {signer.key_id: dev_trust().certificates[signer.key_id].public_key}


def entitlement(subscription: str, licence: str = LICENCE, period: tuple[str, str] = PERIOD) -> dict[str, Any]:
    """A subscription entitlement signed by the test licence key, as the checkout hands it to the device (D70)."""
    document = {"kind": "cloud_tier_subscription", "subscription_id": subscription, "licence_id": licence,
                "period_start": period[0], "period_end": period[1], "seats": 1, "allowance_tokens": 1_800_000,
                "plan": "jana_online", "band": "nigeria", "billing": "month", "features": ["cloud_tier"], "limits": {},
                "created_at": period[0]}  # fmt: skip
    return dev_signer(Purpose.LICENCE).sign("licence_file", document, now=period[0])


FAKE_KEYS = {
    "nebius_api_key": "stub-nebius-key-not-real",
    "gemini_api_key": "stub-gemini-key-not-real",
    "openai_api_key": "stub-openai-key-not-real",
    "admin_token": "stub-admin-token-not-real",
}


@dataclass
class Output:
    """What the stub model says next."""

    text: str = ""
    tool: tuple[str, dict[str, Any]] | None = None
    error: tuple[int, dict[str, Any]] | None = None
    fail_mid_stream: bool = False
    usage: tuple[int, int, int] = (40, 12, 8)  # input, output, cached


@dataclass
class Seen:
    """A provider request, normalised so the same assertions hold for every provider."""

    url: str
    headers: dict[str, str]
    body: dict[str, Any]
    model: str
    stream: bool
    system: str
    user_texts: list[str]
    tool_results: list[tuple[str, Any]]
    replayed_calls: list[dict[str, Any]]
    schema: dict[str, Any] | None
    tools: list[str]


@dataclass
class StubProvider:
    kind: str
    outputs: list[Output] = field(default_factory=list)
    seen: list[Seen] = field(default_factory=list)

    def say(self, *outputs: Output) -> None:
        self.outputs.extend(outputs)

    def _next(self) -> Output:
        return self.outputs.pop(0) if self.outputs else Output(text="ok")

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        seen = self._normalise(request, body)
        self.seen.append(seen)
        out = self._next()
        if out.error is not None:
            return httpx.Response(out.error[0], json=out.error[1])
        if seen.stream:
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"}, stream=_ByteStream(self._sse(seen, out))
            )
        return httpx.Response(200, json=self._reply(seen, out))

    # --- per provider ---

    def _normalise(self, request: httpx.Request, body: dict[str, Any]) -> Seen:
        if self.kind == "gemini":
            return _gemini_seen(request, body)
        return _openai_seen(request, body)

    def _reply(self, seen: Seen, out: Output) -> dict[str, Any]:
        return _gemini_reply(seen, out) if self.kind == "gemini" else _openai_reply(seen, out)

    def _sse(self, seen: Seen, out: Output) -> list[bytes]:
        return _gemini_sse(seen, out) if self.kind == "gemini" else _openai_sse(seen, out)


class _ByteStream(httpx.AsyncByteStream):
    def __init__(self, events: list[bytes]) -> None:
        self.events = events

    async def __aiter__(self):  # type: ignore[override]
        for event in self.events:
            if event == b"!fail":
                raise httpx.ReadError("connection reset by stub")
            yield event


# --- Gemini shape ---


def _gemini_seen(request: httpx.Request, body: dict[str, Any]) -> Seen:
    path = request.url.path
    model, _, method = path.rsplit("/", 1)[-1].partition(":")
    system = " ".join(p.get("text", "") for p in (body.get("systemInstruction") or {}).get("parts", []))
    user_texts, results, calls = [], [], []
    for content in body.get("contents", []):
        for part in content.get("parts", []):
            if content["role"] == "user" and "text" in part:
                user_texts.append(part["text"])
            if "functionResponse" in part:
                results.append((part["functionResponse"]["name"], part["functionResponse"]["response"]))
            if "functionCall" in part:
                calls.append(
                    {
                        "name": part["functionCall"]["name"],
                        "args": part["functionCall"]["args"],
                        "signature": part.get("thoughtSignature"),
                    }
                )
    generation = body.get("generationConfig") or {}
    tools = [d["name"] for t in body.get("tools", []) for d in t.get("functionDeclarations", [])]
    return Seen(
        str(request.url),
        dict(request.headers),
        body,
        model,
        method.startswith("streamGenerateContent"),
        system,
        user_texts,
        results,
        calls,
        generation.get("responseJsonSchema"),
        tools,
    )


def _gemini_usage(out: Output) -> dict[str, int]:
    return {
        "promptTokenCount": out.usage[0],
        "candidatesTokenCount": out.usage[1],
        "cachedContentTokenCount": out.usage[2],
        "totalTokenCount": out.usage[0] + out.usage[1],
    }


def _gemini_parts(out: Output) -> list[dict[str, Any]]:
    if out.tool is not None:
        return [{"functionCall": {"name": out.tool[0], "args": out.tool[1]}, "thoughtSignature": "c2lnLXN0dWI="}]
    return [{"text": out.text}]


def _gemini_reply(seen: Seen, out: Output) -> dict[str, Any]:
    return {
        "candidates": [{"content": {"role": "model", "parts": _gemini_parts(out)}, "finishReason": "STOP"}],
        "usageMetadata": _gemini_usage(out),
        "modelVersion": seen.model,
        "responseId": secrets.token_hex(6),
    }


def _gemini_sse(seen: Seen, out: Output) -> list[bytes]:
    if out.tool is not None:
        pieces = [
            {
                "candidates": [{"content": {"role": "model", "parts": _gemini_parts(out)}, "finishReason": "STOP"}],
                "usageMetadata": _gemini_usage(out),
                "modelVersion": seen.model,
            }
        ]
    else:
        third = max(1, len(out.text) // 3)
        chunks = [out.text[:third], out.text[third : 2 * third], out.text[2 * third :]]
        pieces = [
            {"candidates": [{"content": {"role": "model", "parts": [{"text": c}]}}], "modelVersion": seen.model}
            for c in chunks
        ]
        pieces[-1]["candidates"][0]["finishReason"] = "STOP"
        pieces[-1]["usageMetadata"] = _gemini_usage(out)
    events = [b"data: " + json.dumps(p).encode() + b"\r\n\r\n" for p in pieces]
    if out.fail_mid_stream:
        events = [*events[:1], b"!fail"]
    return events


# --- OpenAI shape ---


def _openai_seen(request: httpx.Request, body: dict[str, Any]) -> Seen:
    system = " ".join(m["content"] for m in body.get("messages", []) if m["role"] == "system")
    user_texts = []
    for m in body.get("messages", []):
        if m["role"] == "user":
            content = m["content"]
            user_texts += [content] if isinstance(content, str) else [p["text"] for p in content if p.get("text")]
    names = {c["id"]: c["function"]["name"] for m in body.get("messages", []) for c in m.get("tool_calls") or []}
    results = [
        (names.get(m["tool_call_id"], ""), json.loads(m["content"]))
        for m in body.get("messages", [])
        if m["role"] == "tool"
    ]
    calls = [
        {"name": c["function"]["name"], "args": json.loads(c["function"]["arguments"]), "signature": None}
        for m in body.get("messages", [])
        for c in m.get("tool_calls") or []
    ]
    schema = ((body.get("response_format") or {}).get("json_schema") or {}).get("schema")
    tools = [t["function"]["name"] for t in body.get("tools", [])]
    return Seen(
        str(request.url),
        dict(request.headers),
        body,
        body["model"],
        bool(body.get("stream")),
        system,
        user_texts,
        results,
        calls,
        schema,
        tools,
    )


def _openai_usage(out: Output) -> dict[str, Any]:
    return {
        "prompt_tokens": out.usage[0],
        "completion_tokens": out.usage[1],
        "total_tokens": out.usage[0] + out.usage[1],
        "prompt_tokens_details": {"cached_tokens": out.usage[2]},
    }


def _openai_reply(seen: Seen, out: Output) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant", "content": out.text or None}
    finish = "stop"
    if out.tool is not None:
        message["tool_calls"] = [
            {
                "id": "call_stub1",
                "type": "function",
                "function": {"name": out.tool[0], "arguments": json.dumps(out.tool[1])},
            }
        ]
        finish = "tool_calls"
    return {
        "id": "chatcmpl-stub",
        "object": "chat.completion",
        "created": 1,
        "model": seen.model,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": _openai_usage(out),
    }


def _openai_sse(seen: Seen, out: Output) -> list[bytes]:
    def chunk(delta: dict[str, Any], finish: str | None = None) -> dict[str, Any]:
        return {
            "id": "chatcmpl-stub",
            "object": "chat.completion.chunk",
            "created": 1,
            "model": seen.model,
            "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
        }

    if out.tool is not None:
        args = json.dumps(out.tool[1])
        half = len(args) // 2
        pieces = [
            chunk(
                {
                    "role": "assistant",
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_stub1",
                            "type": "function",
                            "function": {"name": out.tool[0], "arguments": args[:half]},
                        }
                    ],
                }
            ),
            chunk({"tool_calls": [{"index": 0, "function": {"arguments": args[half:]}}]}),
            chunk({}, "tool_calls"),
        ]
    else:
        third = max(1, len(out.text) // 3)
        pieces = [
            chunk({"role": "assistant", "content": out.text[:third]}),
            chunk({"content": out.text[third : 2 * third]}),
            chunk({"content": out.text[2 * third :]}),
            chunk({}, "stop"),
        ]
    if (seen.body.get("stream_options") or {}).get("include_usage"):
        pieces.append(
            {
                "id": "chatcmpl-stub",
                "object": "chat.completion.chunk",
                "created": 1,
                "model": seen.model,
                "choices": [],
                "usage": _openai_usage(out),
            }
        )
    events = [b"data: " + json.dumps(p).encode() + b"\n\n" for p in pieces] + [b"data: [DONE]\n\n"]
    if out.fail_mid_stream:
        events = [*events[:1], b"!fail"]
    return events


# --- gateway and device ---


class FakeSecrets:
    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(FAKE_KEYS if values is None else values)

    def get(self, name: str) -> Secret | None:
        value = self.values.get(name)
        return Secret(value) if value else None


PROVIDERS = {
    "nebius": {
        "adapter": "nebius",
        "base_url": "https://nebius.stub/v1",
        "secret": "nebius_api_key",
        "models": {
            "strong-model": {"id": "nebius-stub-ultra"},
            "fast-model": {"id": "nebius-stub-super"},
            "small-model": {"id": "nebius-stub-nano"},
        },
    },
    "gemini": {
        "adapter": "gemini",
        "base_url": "https://gemini.stub/v1beta",
        "secret": "gemini_api_key",
        "models": {
            "strong-model": {"id": "gemini-stub-pro", "thinking": {"kind": "level", "low": "low", "high": "high"}},
            "fast-model": {"id": "gemini-stub-flash"},
            "small-model": {"id": "gemini-stub-lite", "thinking": {"kind": "budget", "none": 0, "high": 2048}},
        },
    },
    "openai_compat": {
        "adapter": "openai_compat",
        "base_url": "https://openai.stub/v1",
        "secret": "openai_api_key",
        "pseudonym_field": "user",
        "models": {
            "strong-model": {"id": "oa-stub-strong"},
            "fast-model": {"id": "oa-stub-fast"},
            "small-model": {"id": "oa-stub-small"},
        },
    },
}
PRICES = {
    model["id"]: {"input": 1.0, "cached_input": 0.1, "output": 4.0}
    for provider in PROVIDERS.values()
    for model in provider["models"].values()  # type: ignore[attr-defined]
}


def gateway_config(storage: Path, slots: dict[str, str] | None = None, **overrides: Any) -> GatewayConfig:
    values: dict[str, Any] = {
        "environment": "staging",
        "audience_host": AUDIENCE,
        "storage_dir": storage,
        "licences": [LICENCE, "lic_school_two"],
        "entitlement_keys": licence_keys(),
        "slots": slots or {"primary": "gemini", "fallback": "openai_compat"},
        "providers": PROVIDERS,
        "study_model": "primary/fast-model",
        "prices": PRICES,
        "quotas": {"device_burst": 1000, "licence_burst": 10000},
    }
    values.update(overrides)
    return load_config(None, **values)


class Clock:
    def __init__(self, now: float = 1_790_000_000.0) -> None:
        self.now = now

    def __call__(self) -> float:
        return self.now


@dataclass
class Harness:
    client: httpx.AsyncClient
    stubs: dict[str, StubProvider]
    clock: Clock
    config: GatewayConfig
    alerts: list[tuple[str, dict[str, object]]]


def harness(config: GatewayConfig, clock: Clock | None = None, secrets: FakeSecrets | None = None) -> Harness:
    stubs = {kind: StubProvider(kind) for kind in PROVIDERS}
    clock = clock or Clock()
    alerts: list[tuple[str, dict[str, object]]] = []

    def client_factory(name: str, spec: Any) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(stubs[spec.adapter].handler))

    app = create_app(
        config,
        secrets=secrets or FakeSecrets(),
        clock=clock,
        client_factory=client_factory,
        alerts=lambda kind, detail: alerts.append((kind, detail)),
    )
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"https://{AUDIENCE}")
    return Harness(client, stubs, clock, config, alerts)


@dataclass
class Device:
    """What the device does (SEC-21): an Ed25519 key, registration, challenge, signature, token."""

    key: Ed25519PrivateKey = field(default_factory=Ed25519PrivateKey.generate)
    credential_id: str = ""
    token: str = ""
    pseudonym: str = field(default_factory=lambda: secrets.token_urlsafe(18))
    # Each test device has its own subscription unless a test shares one between devices.
    subscription: str = field(default_factory=lambda: "sub_" + secrets.token_hex(6))

    def public_key(self) -> str:
        return base64.b64encode(self.key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()

    async def register(self, client: httpx.AsyncClient, licence: str = LICENCE,
                       document: dict[str, Any] | None = None) -> httpx.Response:  # fmt: skip
        body = {"public_key": self.public_key(), "entitlement": document or entitlement(self.subscription, licence)}
        reply = await client.post("/v1/devices", json=body)
        if reply.status_code == 201:
            self.credential_id = reply.json()["credential_id"]
        return reply

    async def challenge(self, client: httpx.AsyncClient) -> httpx.Response:
        return await client.post("/v1/auth/challenge", json={"credential_id": self.credential_id})

    def sign(self, nonce: str, audience: str = AUDIENCE) -> str:
        return base64.b64encode(self.key.sign(signed_message(base64.b64decode(nonce), audience))).decode()

    async def exchange(self, client: httpx.AsyncClient, nonce: str, audience: str = AUDIENCE) -> httpx.Response:
        body = {"credential_id": self.credential_id, "nonce": nonce, "signature": self.sign(nonce, audience)}
        reply = await client.post("/v1/auth/token", json=body)
        if reply.status_code == 200:
            self.token = reply.json()["access_token"]
        return reply

    async def login(self, client: httpx.AsyncClient) -> None:
        if not self.credential_id:
            assert (await self.register(client)).status_code == 201
        challenge = await self.challenge(client)
        assert challenge.status_code == 200, challenge.text
        assert (await self.exchange(client, challenge.json()["nonce"])).status_code == 200

    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}", "X-Session-Pseudonym": self.pseudonym}

    async def chat(self, client: httpx.AsyncClient, body: dict[str, Any]) -> httpx.Response:
        return await client.post("/v1/chat/completions", json=body, headers=self.headers())


def sse_payloads(text: str) -> list[Any]:
    """Every `data:` payload of an SSE reply, `[DONE]` as the string."""
    out: list[Any] = []
    for block in text.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data: "):
                data = line[6:]
                out.append(data if data == "[DONE]" else json.loads(data))
    return out
