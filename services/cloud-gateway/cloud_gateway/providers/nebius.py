"""Nebius Token Factory: OpenAI-compatible inference with completion storage disabled.

The gateway owns the API key and resolves model aliases; devices never receive it. Keep the public, global
base URL in configuration: public endpoint regions may change. API reference checked 2026-10-23:
https://docs.tokenfactory.nebius.com/api-reference/inference/create-chat-completion
"""

from __future__ import annotations

import json
from typing import Any

from cloud_gateway.providers.base import ProviderRequest
from cloud_gateway.providers.openai_compat import OpenAICompatAdapter

SCHEMA_NOTICE = "Jana required output contract."


def prepare_body(body: dict[str, Any]) -> dict[str, Any]:
    """Normalize Token Factory's supported tool choice and reinforce, without duplicating, the output contract."""
    # The public Ultra endpoint rejects `required` (live 2026-10-23). Its documented `auto` selection returns
    # native calls. Jana still requires an executed, validated tool result before it accepts a computed plan.
    if body.get("tool_choice") == "required":
        body = {**body, "tool_choice": "auto"}
    response_format = body.get("response_format") or {}
    messages = body.get("messages") or []
    if response_format.get("type") != "json_schema" or any(
        message.get("role") == "system" and str(message.get("content", "")).startswith(SCHEMA_NOTICE)
        for message in messages
    ):
        return body
    schema = (response_format.get("json_schema") or {}).get("schema")
    if not isinstance(schema, dict):
        return body
    instruction = (
        SCHEMA_NOTICE + " When returning a final answer rather than calling a tool, return exactly one JSON object "
        "matching this schema. Use the exact property names, types and enum values; include every "
        "required property. Do not invent identifiers or properties. JSON Schema:\n"
        + json.dumps(schema, ensure_ascii=False, separators=(",", ":"))
    )
    return {**body, "messages": [{"role": "system", "content": instruction}, *messages]}


class NebiusAdapter(OpenAICompatAdapter):
    def _body(self, request: ProviderRequest, stream: bool) -> dict[str, Any]:
        body = super()._body(request, stream)
        body["store"] = False
        # Token Factory's generic JSON-schema parameter alone did not constrain Nemotron's nested diagnosis
        # schema in live testing (2026-10-23). Supply the same contract in the prompt, as its JSON guide recommends;
        # the engine still validates the full output and withholds malformed results.
        return prepare_body(body)

    def __repr__(self) -> str:
        return f"NebiusAdapter(base_url={self.spec.base_url!r})"
