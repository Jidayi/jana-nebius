"""MDL-26: one conformance suite for every provider adapter, run through the gateway against stub providers.

The suite speaks only the device's protocol (OpenAI chat completions with a `<slot>/<alias>` model) and checks the
replies with the device's own parser and error classifier from agent_core, so a provider passes only if the device
cannot tell which provider served it."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from agent_core.providers.base import EffortRecord, FinalTurn
from agent_core.providers.errors import classify_http
from agent_core.providers.openai_compat import assemble_stream, parse_reply
from gateway_stubs import Device, Harness, Output, gateway_config, harness, sse_payloads

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "check_answer",
            "description": "Check a worked answer.",
            "parameters": {"type": "object", "properties": {"answer": {"type": "string"}}, "required": ["answer"]},
        },
    }
]
SCHEMA = {
    "type": "object",
    "properties": {"hint": {"type": "string"}},
    "required": ["hint"],
    "additionalProperties": False,
}
# Upstream failure -> the reason the device must classify from the gateway's reply.
FAILURES = [
    (
        (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "You exceeded your current quota."}}),
        "quota_or_billing",
    ),
    (
        (429, {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message": "Too many requests, slow down."}}),
        "rate_limit",
    ),
    ((503, {"error": {"code": 503, "status": "UNAVAILABLE", "message": "The model is overloaded."}}), "overloaded"),
    ((500, {"error": {"code": 500, "status": "INTERNAL", "message": "Internal error."}}), "server_error"),
    (
        (
            400,
            {
                "error": {
                    "code": 400,
                    "status": "INVALID_ARGUMENT",
                    "message": "The input token count exceeds the maximum number of tokens allowed.",
                }
            },
        ),
        "context_overflow",
    ),
    (
        (403, {"error": {"code": 403, "status": "PERMISSION_DENIED", "message": "Permission denied on the key."}}),
        "server_error",
    ),  # our provider key, not the device's credential: never 401 to the device
    ((404, {"error": {"code": 404, "status": "NOT_FOUND", "message": "models/x is not found."}}), "model_not_found"),
]


def _cost(_: Any) -> float:
    return 0.0


async def _events(text: str) -> AsyncIterator[dict[str, Any]]:
    for payload in sse_payloads(text):
        if payload != "[DONE]":
            yield payload


async def conformance(h: Harness, slot: str) -> str:
    """The suite for the provider behind one slot; returns the provider name that served it."""
    provider = h.config.slots[slot]
    stub = h.stubs[provider]
    expected_model = h.config.providers[provider].models["strong-model"].id
    device = Device()
    await device.login(h.client)
    model = f"{slot}/strong-model"
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": "You are a patient tutor."},
        {"role": "user", "content": "What is 3 times 4?"},
    ]

    # 1. Plain text reply.
    stub.say(Output(text="Twelve."))
    reply = await device.chat(h.client, {"model": model, "messages": messages, "temperature": 0.2, "max_tokens": 50})
    assert reply.status_code == 200, reply.text
    turn = parse_reply(reply.json(), model, EffortRecord(), _cost, 1)
    assert turn.text == "Twelve." and turn.finish_reason == "stop" and not turn.tool_calls
    assert (turn.usage.input, turn.usage.output, turn.usage.cache_read) == (40, 12, 8)
    seen = stub.seen[-1]
    assert seen.model == expected_model and not seen.stream
    assert seen.system == "You are a patient tutor." and seen.user_texts == ["What is 3 times 4?"]
    assert "stub-" in json.dumps(seen.headers) and "key=" not in seen.url  # the key is a header, never in the URL

    # 2. Tool call round trip.
    stub.say(Output(tool=("check_answer", {"answer": "12"})), Output(text="Correct."))
    first = await device.chat(h.client, {"model": model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"})
    assert first.status_code == 200, first.text
    called = parse_reply(first.json(), model, EffortRecord(), _cost, 1)
    assert called.finish_reason == "tool_calls"
    assert [(c.name, c.arguments) for c in called.tool_calls] == [("check_answer", {"answer": "12"})]
    assert stub.seen[-1].tools == ["check_answer"]
    assistant = first.json()["choices"][0]["message"]
    follow_up = [
        *messages,
        assistant,
        {"role": "tool", "tool_call_id": assistant["tool_calls"][0]["id"], "content": '{"correct": true}'},
    ]
    second = await device.chat(h.client, {"model": model, "messages": follow_up, "tools": TOOLS})
    assert second.status_code == 200, second.text
    assert second.json()["choices"][0]["message"]["content"] == "Correct."
    assert stub.seen[-1].tool_results == [("check_answer", {"correct": True})]
    assert [(c["name"], c["args"]) for c in stub.seen[-1].replayed_calls] == [("check_answer", {"answer": "12"})]

    # 3. Streamed text.
    stub.say(Output(text="Three groups of four make twelve."))
    streamed = await device.chat(
        h.client, {"model": model, "messages": messages, "stream": True, "stream_options": {"include_usage": True}}
    )
    assert streamed.status_code == 200 and streamed.headers["content-type"].startswith("text/event-stream")
    assert sse_payloads(streamed.text)[-1] == "[DONE]"
    chunks = [c async for c in assemble_stream(_events(streamed.text), model, EffortRecord(), _cost, time.monotonic())]
    final = chunks[-1]
    assert isinstance(final, FinalTurn)
    assert final.turn.text == "Three groups of four make twelve." and final.turn.finish_reason == "stop"
    assert final.turn.usage.input == 40 and final.turn.usage.output == 12
    assert stub.seen[-1].stream and stub.seen[-1].model == expected_model

    # 4. Structured output.
    stub.say(Output(text='{"hint": "Count in fours."}'))
    structured = await device.chat(
        h.client,
        {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "hint", "strict": True, "schema": SCHEMA},
            },
        },
    )
    assert structured.status_code == 200, structured.text
    assert json.loads(structured.json()["choices"][0]["message"]["content"]) == {"hint": "Count in fours."}
    assert stub.seen[-1].schema == SCHEMA

    # 5. Error classification, as the device classifies the gateway's reply.
    for (status, body), reason in FAILURES:
        stub.say(Output(error=(status, body)))
        failed = await device.chat(h.client, {"model": model, "messages": messages})
        assert classify_http(failed.status_code, failed.json()) == reason, (status, body, failed.text)
        assert "stub-" not in failed.text  # no key in an error
    return provider


def _run(config_slots: dict[str, str], tmp: Path) -> dict[str, str]:
    async def main() -> dict[str, str]:
        h = harness(gateway_config(tmp, config_slots))
        return {slot: await conformance(h, slot) for slot in ("primary", "fallback")}

    return asyncio.run(main())


@pytest.mark.parametrize("provider", ["gemini", "openai_compat", "nebius"])
def test_conformance_per_adapter(provider: str, tmp_path: Path) -> None:
    other = "openai_compat" if provider == "gemini" else "gemini"
    served = _run({"primary": provider, "fallback": other}, tmp_path)
    assert served["primary"] == provider


def mdl26_provider_swap(tmp_path: Path) -> None:
    """The same suite passes with the primary and fallback providers swapped in config only, and a device request
    for primary/strong-model reaches the adapter the config names."""
    as_decided = _run({"primary": "gemini", "fallback": "openai_compat"}, tmp_path / "a")
    swapped = _run({"primary": "openai_compat", "fallback": "gemini"}, tmp_path / "b")
    assert as_decided == {"primary": "gemini", "fallback": "openai_compat"}
    assert swapped == {"primary": "openai_compat", "fallback": "gemini"}
