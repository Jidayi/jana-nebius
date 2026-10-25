"""Provider adapters behind one interface, chosen by config (MDL-26)."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx

from cloud_gateway.config import GatewayConfig, ModelSpec, ProviderSpec
from cloud_gateway.custody import Secret, SecretSource
from cloud_gateway.providers.base import ProviderAdapter
from cloud_gateway.providers.gemini import GeminiAdapter
from cloud_gateway.providers.nebius import NebiusAdapter
from cloud_gateway.providers.openai_compat import OpenAICompatAdapter
from cloud_gateway.providers.vertex import VertexAdapter

if TYPE_CHECKING:
    from cloud_gateway.inference_budget import InferenceBudget

ClientFactory = Callable[[str, ProviderSpec], httpx.AsyncClient]
ADAPTERS: dict[str, Callable[[ProviderSpec, Secret | None, httpx.AsyncClient], ProviderAdapter]] = {
    "gemini": GeminiAdapter,
    "vertex": VertexAdapter,
    "openai_compat": OpenAICompatAdapter,
    "nebius": NebiusAdapter,
}


def default_client(name: str, spec: ProviderSpec) -> httpx.AsyncClient:
    # TLS with certificate validation, no redirects, no proxy or netrc credentials from the environment (SEC-31).
    return httpx.AsyncClient(follow_redirects=False, trust_env=False)


class Providers:
    """The configured adapters by provider name, and slot/alias resolution for device model ids."""

    def __init__(
        self,
        config: GatewayConfig,
        secrets: SecretSource,
        client_factory: ClientFactory = default_client,
        *,
        budget: InferenceBudget | None = None,
    ) -> None:
        self.config = config
        self.adapters: dict[str, ProviderAdapter] = {
            name: ADAPTERS[spec.adapter](spec, secrets.get(spec.secret), client_factory(name, spec))
            for name, spec in config.providers.items()
            if name in config.slots.values()
        }
        if budget is not None:
            from cloud_gateway.inference_budget import BudgetedAdapter

            self.adapters = {name: BudgetedAdapter(adapter, budget) for name, adapter in self.adapters.items()}

    def resolve(self, model: object) -> tuple[str, ProviderAdapter, ModelSpec] | None:
        """`<slot>/<alias>` to the provider name, its adapter and the concrete model, or None if not configured."""
        if not isinstance(model, str) or model.count("/") != 1:
            return None
        slot, alias = model.split("/")
        provider = self.config.slots.get(slot)
        if provider is None or provider not in self.adapters:
            return None
        spec = self.config.providers[provider].models.get(alias)
        return (provider, self.adapters[provider], spec) if spec else None

    async def aclose(self) -> None:
        for adapter in self.adapters.values():
            await adapter.aclose()
