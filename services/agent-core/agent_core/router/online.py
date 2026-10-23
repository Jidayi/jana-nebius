"""The cloud tier for one session (ARC-12, MDL-24 to MDL-26, MDL-29, BIZ-07).

`cloud_session` gives a session's router what the cloud tier needs: one gateway provider per configured slot
(`primary`, `fallback`), each with its own per-session pseudonym and the session's redaction terms; the connectivity
state the router reads before choosing a cloud candidate; and the cost budget metered on the device. The engine wires
these into its router; the connectivity layer itself (`agent_core.net.layer.OnlineLayer`) is the device's."""

from __future__ import annotations

import datetime
import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.net.layer import OnlineLayer
from agent_core.net.redaction import Redactor
from agent_core.providers.gateway import GatewayProvider, cloud_capabilities
from agent_core.router.budget import CloudBudget, MemorySpend, SpendStore

MODELS_FILE = Path(__file__).with_name("cloud_models.json")
SLOTS = ("primary", "fallback")

__all__ = ["SLOTS", "CloudSession", "OnlineLayer", "cloud_models", "cloud_session"]


@cache
def cloud_models(path: Path = MODELS_FILE) -> dict[str, dict[str, Any]]:
    models: dict[str, dict[str, Any]] = json.loads(path.read_text())["models"]
    return models


@dataclass
class CloudSession:
    providers: dict[str, GatewayProvider]
    budget: CloudBudget
    network: Callable[[], str]


def today() -> str:
    return datetime.datetime.now(datetime.UTC).date().isoformat()


def cloud_session(
    layer: OnlineLayer,
    settings: Settings,
    *,
    profile_id: str | None,
    terms: Iterable[str] = (),
    spend: SpendStore | None = None,
    allowance_tokens: int | None = None,
    on_reminder: Callable[[str, float], None] | None = None,
) -> CloudSession:
    models = cloud_models()
    caps = {m: cloud_capabilities(int(v["context"]), int(v["max_output"]), bool(v["vision"]))
            for m, v in models.items()}  # fmt: skip
    prices = {m: (float(v["price_in_per_mtok"]), float(v["price_out_per_mtok"])) for m, v in models.items()}
    redactor = Redactor(terms)
    providers = {
        slot: GatewayProvider(
            layer.client,
            lambda: layer.host_for("cloud_tier"),
            slot,
            token=layer.credential.token,
            caps=caps,
            prices=prices,
            redactor=redactor,
            profile_id=profile_id,
            on_network_failure=layer.network_failure,
        )
        for slot in SLOTS
    }
    budget = CloudBudget(settings.cloud_budget_session_usd, settings.cloud_budget_student_day_usd,
                         tuple(settings.cloud_budget_reminders), spend or MemorySpend(), today,
                         allowance_tokens=allowance_tokens, on_reminder=on_reminder)  # fmt: skip
    return CloudSession(providers, budget, lambda: layer.connectivity.state)
