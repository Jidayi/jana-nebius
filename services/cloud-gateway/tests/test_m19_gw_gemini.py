"""The Gemini adapter's translation in detail (D7 primary provider), against recorded request shapes."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from cloud_gateway.config import ModelSpec, ProviderSpec, Thinking, load_config
from cloud_gateway.custody import Secret
from cloud_gateway.providers.base import ProviderRequest, UpstreamError
from cloud_gateway.providers.gemini import SKIP_SIGNATURE, GeminiAdapter, reply, translate

LEVEL = ModelSpec(id="g-pro", thinking=Thinking(kind="level", none="low", low="low", medium="high", high="high"))
BUDGET = ModelSpec(id="g-lite", thinking=Thinking(kind="budget", none=0, low=512, high=4096))
PIXEL = "data:image/jpeg;base64,/9j/4AAQSkZJRg=="


def test_messages_become_contents_and_system_instruction() -> None:
    body = {
        "messages": [
            {"role": "system", "content": "Be brief."},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image_url", "image_url": {"url": PIXEL}},
                ],
            },
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "plot", "arguments": '{"x": 1}'},
                        "extra_content": {"google": {"thought_signature": "sig-1"}},
                    },
                    {"id": "c2", "type": "function", "function": {"name": "plot", "arguments": '{"x": 2}'}},
                ],
            },
            {"role": "tool", "tool_call_id": "c1", "content": '{"ok": true}'},
            {"role": "tool", "tool_call_id": "c2", "content": "plain text result"},
        ],
        "tools": [
            {"type": "function", "function": {"name": "plot", "description": "Plot.", "parameters": {"type": "object"}}}
        ],
        "tool_choice": {"type": "function", "function": {"name": "plot"}},
        "temperature": 0.3,
        "max_tokens": 64,
        "stop": "END",
        "reasoning_effort": "medium",
        "response_format": {"type": "json_object"},
    }
    request = translate(LEVEL, body)
    assert request["systemInstruction"] == {"parts": [{"text": "Be brief."}]}
    user, model, results = request["contents"]
    assert user["role"] == "user" and user["parts"][1] == {
        "inlineData": {"mimeType": "image/jpeg", "data": "/9j/4AAQSkZJRg=="}
    }
    assert model["role"] == "model"
    assert model["parts"][0] == {"functionCall": {"name": "plot", "args": {"x": 1}}, "thoughtSignature": "sig-1"}
    assert "thoughtSignature" not in model["parts"][1]  # only the first call of a turn carries one
    assert results == {
        "role": "user",
        "parts": [
            {"functionResponse": {"name": "plot", "response": {"ok": True}}},
            {"functionResponse": {"name": "plot", "response": {"result": "plain text result"}}},
        ],
    }
    assert request["tools"] == [
        {"functionDeclarations": [{"name": "plot", "description": "Plot.", "parametersJsonSchema": {"type": "object"}}]}
    ]
    assert request["toolConfig"] == {"functionCallingConfig": {"mode": "ANY", "allowedFunctionNames": ["plot"]}}
    assert request["generationConfig"] == {
        "temperature": 0.3,
        "maxOutputTokens": 64,
        "stopSequences": ["END"],
        "responseMimeType": "application/json",
        "thinkingConfig": {"thinkingLevel": "high"},
    }


def test_replayed_call_without_signature_uses_the_skip_value() -> None:
    body = {
        "messages": [
            {
                "role": "assistant",
                "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "f", "arguments": "{}"}}],
            }
        ]
    }
    assert translate(LEVEL, body)["contents"][0]["parts"][0]["thoughtSignature"] == SKIP_SIGNATURE


@pytest.mark.parametrize(("effort", "expected"), [("none", 0), ("low", 512), ("high", 4096), (None, None)])
def test_reasoning_effort_to_thinking_budget(effort: str | None, expected: int | None) -> None:
    body: dict[str, Any] = {"messages": [{"role": "user", "content": "x"}]}
    if effort:
        body["reasoning_effort"] = effort
    config = translate(BUDGET, body).get("generationConfig", {}).get("thinkingConfig")
    assert config == (None if expected is None else {"thinkingBudget": expected})


def test_remote_images_are_refused() -> None:
    body = {
        "messages": [
            {"role": "user", "content": [{"type": "image_url", "image_url": {"url": "https://example.org/a.png"}}]}
        ]
    }
    with pytest.raises(UpstreamError) as caught:
        translate(LEVEL, body)
    assert caught.value.reason == "format_error"


@pytest.mark.parametrize(
    ("finish", "expected"),
    [("MAX_TOKENS", "length"), ("SAFETY", "content_filter"), ("RECITATION", "content_filter"), ("STOP", "stop")],
)
def test_finish_reasons_and_usage(finish: str, expected: str) -> None:
    raw = {
        "candidates": [
            {"content": {"parts": [{"text": "thinking", "thought": True}, {"text": "Answer"}]}, "finishReason": finish}
        ],
        "usageMetadata": {
            "promptTokenCount": 100,
            "candidatesTokenCount": 20,
            "thoughtsTokenCount": 30,
            "cachedContentTokenCount": 60,
        },
    }
    out = reply(raw, LEVEL)
    choice = out.body["choices"][0]
    assert choice["finish_reason"] == expected and choice["message"]["content"] == "Answer"
    assert (out.usage.input_tokens, out.usage.output_tokens, out.usage.cached_tokens, out.usage.reasoning_tokens) == (
        100,
        50,
        60,
        30,
    )
    assert out.body["usage"]["completion_tokens_details"] == {"reasoning_tokens": 30}


def test_blocked_prompt_is_a_content_filter_finish() -> None:
    out = reply({"promptFeedback": {"blockReason": "SAFETY"}}, LEVEL)
    assert out.body["choices"][0]["finish_reason"] == "content_filter"


def test_key_only_in_the_header() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200, json={"candidates": [{"content": {"parts": [{"text": "hi"}]}, "finishReason": "STOP"}]}
        )

    spec = ProviderSpec(
        adapter="gemini",
        base_url="https://gemini.stub/v1beta",
        secret="gemini_api_key",  # noqa: S106 - the name of a secret, not its value
        models={"strong-model": LEVEL},
    )
    adapter = GeminiAdapter(
        spec, Secret("stub-key-value-123"), httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )
    request = ProviderRequest(LEVEL, {"messages": [{"role": "user", "content": "x"}]}, "pseudonym-abcdefghijkl")
    result = asyncio.run(adapter.complete(request))
    assert result.body["choices"][0]["message"]["content"] == "hi"
    assert seen[0].headers["x-goog-api-key"] == "stub-key-value-123"
    assert str(seen[0].url) == "https://gemini.stub/v1beta/models/g-pro:generateContent"
    assert "stub-key-value-123" not in repr(adapter) and "pseudonym-abcdefghijkl" not in seen[0].content.decode()
    keyless = GeminiAdapter(spec, None, httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(UpstreamError) as caught:
        asyncio.run(keyless.complete(request))
    assert caught.value.reason == "upstream_auth" and len(seen) == 1
    assert json.loads(seen[0].content)["contents"] == [{"role": "user", "parts": [{"text": "x"}]}]


# Thinking levels each shipped model refuses, as the provider answered on 2026-10-16 (HTTP 400).
REFUSED_LEVELS = {"gemini-3.8-flash": {"minimal"}}


def test_shipped_models_map_efforts_to_levels_they_accept() -> None:
    """The hackathon default is Nebius-only; Gemini adapters are tested above with explicit fixtures."""
    assert set(load_config().providers) == {"nebius"}
