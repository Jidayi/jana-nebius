"""Deployment-wide inference caps at the provider boundary, shared by tutor, Study, Ask and probes.

Every request reserves a conservative text-byte or configured image-context bound in SQLite before the adapter. Output
tokens (including reasoning) are explicitly bounded. A successful response with usage replaces the reservation
with actual cost; missing usage, failures, cancellations and crashes retain the bound until operator reconciliation.
No prompt, reply, account identifier or credential is stored here. Daily aggregate counters survive metadata purge;
unresolved calls remain held across midnight. This ledger covers inference, not external hosting/voice/search fees.
"""

from __future__ import annotations

import base64
import copy
import json
import math
import secrets
from collections.abc import AsyncGenerator, Callable
from dataclasses import replace
from typing import Any

from cloud_gateway.config import GatewayConfig
from cloud_gateway.providers.base import (
    ProviderAdapter,
    ProviderReply,
    ProviderRequest,
    StreamPart,
    UpstreamError,
    Usage,
)
from cloud_gateway.quotas import cost_usd
from cloud_gateway.store import GatewayStore, day_of

MICROS = 1_000_000
SCHEMA = """
CREATE TABLE IF NOT EXISTS inference_budget_days (day TEXT PRIMARY KEY, spent_micros INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS inference_budget_pending (id TEXT PRIMARY KEY, reserved_micros INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS inference_budget_state (singleton INTEGER PRIMARY KEY CHECK(singleton=1));
"""


def input_token_bound(request: ProviderRequest) -> int:
    """Text bytes plus a configured vision route's full context; never count base64 as text tokens."""
    body = copy.deepcopy(request.body)
    images = 0
    for message in body.get("messages", []):
        content = message.get("content")
        for part in content if isinstance(content, list) else []:
            if part.get("type") == "text":
                continue
            if part.get("type") != "image_url" or request.model.image_input_token_bound is None:
                raise UpstreamError("format_error", "model has no bounded image input")
            images += 1
            url = (part.get("image_url") or {}).get("url", "")
            prefix = "data:image/jpeg;base64,"
            if images > 1 or not isinstance(url, str) or not url.startswith(prefix) or len(url) > 2_666_700:
                raise UpstreamError("format_error", "expected one bounded JPEG image")
            try:
                data = base64.b64decode(url[len(prefix) :], validate=True)
            except ValueError:
                raise UpstreamError("format_error", "invalid image encoding") from None
            if not data.startswith(b"\xff\xd8\xff") or len(data) > 2_000_000:
                raise UpstreamError("format_error", "invalid bounded JPEG image")
            part["image_url"] = {"url": "[bounded image]"}
    return (
        2 * len(json.dumps(body, ensure_ascii=False).encode())
        + 4096
        + 256 * len(body.get("messages", []))
        + images * (request.model.image_input_token_bound or 0)
    )


def micros(usd: float) -> int:
    if not math.isfinite(usd) or usd < 0:
        raise ValueError("budget amount must be finite and nonnegative")
    return math.ceil(usd * MICROS)


class InferenceBudget:
    def __init__(self, config: GatewayConfig, store: GatewayStore, clock: Callable[[], float]) -> None:
        self.config, self.store, self.clock = config, store, clock
        self.daily = config.quotas.deployment_daily_spend_usd
        self.total = config.quotas.deployment_total_spend_usd
        # Validate limits before initializing any provider. Round costs up and approved limits down.
        self.daily_micros = math.floor(self.daily * MICROS) if self.daily is not None else None
        self.total_micros = math.floor(self.total * MICROS) if self.total is not None else None
        store._db.executescript(SCHEMA)
        with store._tx() as db:
            if not db.execute("SELECT 1 FROM inference_budget_state").fetchone():
                # Preserve known spend when enabling the ledger on an existing gateway. Only retained records
                # are available at first initialization; enable this cap before the first paid deployment call.
                for day, usd in db.execute("SELECT day,sum(cost_usd) FROM requests GROUP BY day").fetchall():
                    db.execute("INSERT INTO inference_budget_days VALUES (?,?)", (day, micros(usd)))
                db.execute("INSERT INTO inference_budget_state VALUES (1)")

    def reserve(self, request: ProviderRequest) -> tuple[str, ProviderRequest]:
        expires = self.config.quotas.deployment_budget_expires_at
        if expires is not None and self.clock() >= expires.timestamp():
            raise UpstreamError("quota_or_billing", "approved deployment inference period has ended")
        price = self.config.prices.get(request.model.id)
        if price is None:
            raise UpstreamError("quota_or_billing", "no configured price for bounded inference")
        body = dict(request.body)
        limit = self.config.quotas.deployment_max_output_tokens
        for field in ("max_tokens", "max_completion_tokens"):
            if body.get(field) is not None:
                value = body[field]
                if type(value) is not int or value < 0:
                    raise UpstreamError("format_error", "invalid completion token limit")
                limit = min(limit, value)
        body.pop("max_tokens", None)
        body["max_completion_tokens"] = limit
        # UTF-8 bytes bound text-token counts conservatively. Additional framing headroom is reserved per message
        # plus a fixed tool/schema allowance. No cache discount is assumed in the upper bound.
        # Nebius repeats the response schema in a system instruction. Reserve the request's byte size twice so
        # that provider translation cannot add unbudgeted schema tokens.
        input_bound = input_token_bound(replace(request, body=body))
        bound = micros(cost_usd(price, Usage(input_bound, limit)))
        key, day = secrets.token_hex(16), day_of(self.clock())
        with self.store._tx() as db:
            held = db.execute("SELECT coalesce(sum(reserved_micros),0) FROM inference_budget_pending").fetchone()[0]
            spent = db.execute("SELECT coalesce(sum(spent_micros),0) FROM inference_budget_days").fetchone()[0]
            today = db.execute("SELECT spent_micros FROM inference_budget_days WHERE day=?", (day,)).fetchone()
            today_spent = today[0] if today else 0
            if (self.total_micros is not None and spent + held + bound > self.total_micros) or (
                self.daily_micros is not None and today_spent + held + bound > self.daily_micros
            ):
                raise UpstreamError("quota_or_billing", "deployment inference budget exhausted")
            db.execute("INSERT INTO inference_budget_pending VALUES (?,?)", (key, bound))
        return key, replace(request, body=body)

    def settle(self, key: str, request: ProviderRequest, usage: Usage) -> None:
        # An inference request always has input tokens. Missing/invalid counters cannot establish actual spend.
        if usage.input_tokens <= 0 or usage.output_tokens < 0 or not 0 <= usage.cached_tokens <= usage.input_tokens:
            return
        amount = micros(cost_usd(self.config.prices[request.model.id], usage))
        with self.store._tx() as db:
            changed = db.execute("DELETE FROM inference_budget_pending WHERE id=?", (key,)).rowcount
            if changed:
                db.execute(
                    "INSERT INTO inference_budget_days VALUES (?,?) ON CONFLICT(day) "
                    "DO UPDATE SET spent_micros=spent_micros+excluded.spent_micros",
                    (day_of(self.clock()), amount),
                )

    def snapshot(self) -> dict[str, Any]:
        with self.store._lock:
            db = self.store._db
            held = db.execute("SELECT coalesce(sum(reserved_micros),0) FROM inference_budget_pending").fetchone()[0]
            spent = db.execute("SELECT coalesce(sum(spent_micros),0) FROM inference_budget_days").fetchone()[0]
            today = db.execute(
                "SELECT spent_micros FROM inference_budget_days WHERE day=?", (day_of(self.clock()),)
            ).fetchone()
        return {
            "spent_usd": spent / MICROS,
            "today_usd": (today[0] if today else 0) / MICROS,
            "held_usd": held / MICROS,
        }


class BudgetedAdapter:
    """One wrapper for every configured inference adapter; no service can bypass the shared cap."""

    def __init__(self, adapter: ProviderAdapter, budget: InferenceBudget) -> None:
        self.adapter, self.budget = adapter, budget

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        key, bounded = self.budget.reserve(request)
        reply = await self.adapter.complete(bounded)
        self.budget.settle(key, bounded, reply.usage)
        return reply

    async def stream(self, request: ProviderRequest) -> AsyncGenerator[StreamPart]:
        key, bounded = self.budget.reserve(request)
        parts, usage = self.adapter.stream(bounded), None
        try:
            async for part in parts:
                if part.usage is not None:
                    usage = part.usage
                yield part
            if usage is not None:
                self.budget.settle(key, bounded, usage)
        finally:
            await parts.aclose()

    async def aclose(self) -> None:
        await self.adapter.aclose()
