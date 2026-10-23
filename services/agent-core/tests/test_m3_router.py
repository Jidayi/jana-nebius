"""M3: provider interface, llama-server adapter, router, retry and fallback, normalisation, structured output and
the router trace (MDL-01 to MDL-03, MDL-05, MDL-07 to MDL-10, MDL-13 to MDL-15, MDL-30; MDL-18 and MDL-20 subsets)."""

import asyncio
import copy
import json
import os
import random
from pathlib import Path

import pytest
import yaml
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.contracts import validator
from agent_core.engine import turn_scope
from agent_core.providers.base import (
    AssistantTurn,
    FinalTurn,
    Message,
    ModelCapabilities,
    ProviderError,
    TextDelta,
    ToolCall,
    ToolCallDelta,
    ToolSchema,
)
from agent_core.providers.errors import REASONS, classify_http, classify_transport
from agent_core.providers.gguf import read_header, write_header
from agent_core.providers.llama import LlamaServerProvider
from agent_core.providers.openai_compat import UNPARSED
from agent_core.providers.scripted import CloudProviderStub, ScriptedProvider, default_capabilities
from agent_core.router import Hooks, Router, RouterError
from agent_core.router.capabilities import layered
from agent_core.router.config import RouterConfigError, load
from agent_core.router.fit import GB, choose_context, hardware_class, launch_arguments
from agent_core.router.normalise import normalise, salvage
from agent_core.router.recovery import Backoff, actions
from agent_core.router.structured import CORRECTION, decode_schema
from agent_core.router.trace import CONTRACT as TRACE_ITEM
from jana_tools import REPO_ROOT
from jana_tools.cassettes import load as load_cassettes
from jana_tools.fakes import FakeLlamaServer

ROUTER_YAML = REPO_ROOT / "services" / "agent-core" / "agent_core" / "router" / "router.yaml"
FIXTURES = Path(__file__).parent / "fixtures"
SOLVE = ToolSchema(
    "math_solve",
    "Solves equations exactly.",
    {
        "type": "object",
        "properties": {"equations": {"type": "array", "items": {"type": "string"}}},
        "required": ["equations"],
    },
)


def reply(
    content: str = "",
    calls: list[tuple[str, str, str]] = (),
    reasoning: str | None = None,
    finish: str = "stop",
    model: str = "m",
) -> dict:
    message: dict = {"role": "assistant", "content": content}
    if reasoning:
        message["reasoning_content"] = reasoning
    if calls:
        message["tool_calls"] = [
            {"id": i, "type": "function", "function": {"name": n, "arguments": a}} for i, n, a in calls
        ]
        finish = "tool_calls"
    return {
        "model": model,
        "choices": [{"message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 11, "completion_tokens": 7},
    }


def config(**changes) -> dict:
    data = yaml.safe_load(ROUTER_YAML.read_text())
    for path, value in changes.items():
        node = data
        *parents, last = path.split("__")
        for part in parents:
            node = node[part]
        node[last] = value
    return data


def router(local, cloud=None, data: dict | None = None, **kwargs) -> Router:
    providers = {"local": local}
    if cloud is not None:
        providers["cloud"] = cloud
    kwargs.setdefault("sleep", _no_sleep)
    return Router(load(data or config()), Settings(), providers, **kwargs)


async def _no_sleep(_: float) -> None:
    return None


def local(script, models=("qwen3-vl-8b", "gemma-4-12b"), **kw) -> ScriptedProvider:
    return ScriptedProvider(script, kind="local", installed_models=list(models), **kw)


def run(coro):
    async def scoped():
        with turn_scope("t-test"):
            return await coro

    return asyncio.run(scoped())


# --- MDL-01 ------------------------------------------------------------------------------------------------


async def _conformance(provider, model: str, steps_for) -> None:
    """The provider conformance suite: the same checks for every provider."""
    steps_for([{"reply": reply("Speed is distance over time.", model=model)}])
    turn = await provider.complete(model, [Message("user", "What is speed?")], [])
    assert isinstance(turn, AssistantTurn) and turn.text == "Speed is distance over time."
    assert turn.finish_reason == "stop" and turn.served_by and turn.usage.input >= 0 and turn.cost_usd >= 0
    assert turn.tool_calls == [] and turn.reasoning is None

    steps_for([{"reply": reply("", [("c1", "math_solve", '{"equations": ["x+1=2"]}')], model=model)}])
    turn = await provider.complete(model, [Message("user", "Solve x+1=2.")], [SOLVE])
    assert turn.finish_reason == "tool_calls"
    assert turn.tool_calls == [ToolCall("c1", "math_solve", {"equations": ["x+1=2"]})]

    steps_for([{"reply": reply("The answer is 84.", reasoning="12 times 7 is 84.", model=model)}])
    chunks = [c async for c in provider.stream(model, [Message("user", "12*7?")], [])]
    assert isinstance(chunks[-1], FinalTurn) and sum(isinstance(c, FinalTurn) for c in chunks) == 1
    final = chunks[-1].turn
    assert "".join(c.text for c in chunks if isinstance(c, TextDelta)) == final.text == "The answer is 84."
    assert final.reasoning == "12 times 7 is 84." and "12 times 7" not in final.text

    steps_for([{"reply": reply("", [("c2", "math_solve", '{"equations": ["2x=4"]}')], model=model)}])
    chunks = [c async for c in provider.stream(model, [Message("user", "Solve 2x=4.")], [SOLVE])]
    assert any(isinstance(c, ToolCallDelta) for c in chunks)
    assert chunks[-1].turn.tool_calls == [ToolCall("c2", "math_solve", {"equations": ["2x=4"]})]

    steps_for(
        [{"error": {"status": 429, "headers": {"Retry-After": "3"}}, "status": 429, "headers": {"Retry-After": "3"}}]
    )
    with pytest.raises(ProviderError) as raised:
        await provider.complete(model, [Message("user", "x")], [])
    assert raised.value.reason == "rate_limit" and raised.value.retry_after_s == 3

    caps = await provider.capabilities(model)
    assert isinstance(caps, ModelCapabilities) and caps.locality == ("cloud" if provider.kind == "cloud" else "local")
    assert caps.context_window > 0


def mdl01_provider_conformance():
    async def scenario() -> None:
        for kind in ("local", "cloud"):  # the scripted local provider and the fake cloud provider
            provider = ScriptedProvider([], kind=kind)
            await _conformance(provider, "scripted-model", lambda steps, p=provider: p.script.extend(steps))
        async with FakeLlamaServer(["qwen3-1.7b"]) as server:  # the llama-server adapter over loopback HTTP
            llama = LlamaServerProvider(server.url, server.api_key)
            await _conformance(llama, "qwen3-1.7b", lambda steps: server.script.extend(steps))
            assert all(r["chat_template_kwargs"] == {"enable_thinking": False} for r in server.requests)
            # Tool schemas go out grammar-friendly: a list of types is sent as the equivalent anyOf.
            mixed = {"type": "object", "properties": {"v": {"type": ["number", "string"], "maxLength": 9}}}
            server.script.append({"reply": reply("ok", model="qwen3-1.7b")})
            await llama.complete("qwen3-1.7b", [Message("user", "x")], [ToolSchema("t", "", mixed)])
            sent = server.requests[-1]["tools"][0]["function"]["parameters"]["properties"]["v"]
            assert sent == {"anyOf": [{"type": "number"}, {"type": "string"}]}
            await llama.close()
        # The S1 cloud provider is a stub: disabled and network-free.
        with pytest.raises(ProviderError, match="network_unavailable"):
            await CloudProviderStub().complete("any", [Message("user", "x")], [])

    asyncio.run(scenario())


@pytest.mark.skipif("JANA_LLAMA_URL" not in os.environ, reason="needs a running llama-server (device lab, nightly)")
def test_llama_server_conformance_live():
    """The same suite against a real llama-server: JANA_LLAMA_URL, JANA_LLAMA_KEY, JANA_LLAMA_MODEL."""

    async def scenario() -> None:
        provider = LlamaServerProvider(os.environ["JANA_LLAMA_URL"], os.environ["JANA_LLAMA_KEY"])
        model = os.environ["JANA_LLAMA_MODEL"]
        assert model in await provider.installed() and await provider.ready(model)
        turn = await provider.complete(model, [Message("user", "Use the tool to solve 2x = 6.")], [SOLVE])
        assert turn.tool_calls and turn.tool_calls[0].name == "math_solve"
        chunks = [c async for c in provider.stream(model, [Message("user", "Say hello.")], [])]
        assert isinstance(chunks[-1], FinalTurn) and chunks[-1].turn.text
        await provider.close()

    asyncio.run(scenario())


def test_cassettes_replay():
    """Recorded real small-model replies replay through the adapter and normalisation (M3 exit evidence)."""

    async def scenario() -> None:
        cassettes = load_cassettes()
        assert len(cassettes) >= 12 and all("not student data" in c["provenance"] for c in cassettes)
        for cassette in cassettes:
            async with FakeLlamaServer([cassette["model"]]) as server:
                provider = LlamaServerProvider(server.url, server.api_key)
                server.script.extend([{"reply": cassette["reply"]}, {"events": cassette["events"]}])
                request = cassette["request"]
                tools = [
                    ToolSchema(t["function"]["name"], "", t["function"]["parameters"]) for t in request.get("tools", [])
                ]
                messages = [Message(m["role"], m["content"]) for m in request["messages"]]
                plain = await provider.complete(cassette["model"], messages, tools)
                streamed = [c async for c in provider.stream(cassette["model"], messages, tools)][-1].turn
                await provider.close()
            for turn in (plain, streamed):
                normal = normalise(turn, {t.name for t in tools}, "call_x")
                assert "<think" not in normal.turn.text and "</think" not in normal.turn.text, cassette["scenario"]
                if "cut_off" in cassette["scenario"] and "tool_call" in cassette["scenario"]:
                    # A call cut off by the length limit reaches the engine's repair pipeline (truncated_args).
                    assert [UNPARSED in c.arguments for c in normal.turn.tool_calls] == [True], cassette["scenario"]
                if cassette["scenario"].startswith("tool_call."):
                    assert [c.name for c in normal.turn.tool_calls] == ["math_solve"], cassette["scenario"]
                if cassette["scenario"].startswith("thinking"):
                    assert normal.turn.reasoning, cassette["scenario"]
            assert normalise(plain, set(), "a").turn.text == normalise(streamed, set(), "a").turn.text

    asyncio.run(scenario())


# --- MDL-02 ------------------------------------------------------------------------------------------------


def mdl02_cross_provider_strip():
    hidden_reasoning = "PRIVATE-REASONING-7731"
    history = [
        Message("user", "What is 2x = 6?"),
        Message(
            "assistant",
            "Let us solve it.",
            reasoning=hidden_reasoning,
            extras={"local": {"cache_slot": 3}, "cloud": {"cloud_cache_id": "cc-1"}},
        ),
        Message("user", "Go on."),
    ]
    data = config(cloud__enabled=True, roles__coach__prefer="local")
    local_down = local([{"error": {"status": 404, "body": {"error": {"message": "model not found"}}}}] * 2)
    fake_cloud = ScriptedProvider([{"reply": reply("x = 3")}], kind="cloud")
    result = run(router(local_down, fake_cloud, data, cloud_on=lambda role: True).complete("coach", history))
    assert result.turn.text == "x = 3"
    sent = json.dumps(fake_cloud.requests[0])
    assert hidden_reasoning not in sent and "cache_slot" not in sent and "cc-1" in sent
    sent_local = json.dumps(local_down.requests)
    assert hidden_reasoning not in sent_local and "cc-1" not in sent_local and "cache_slot" in sent_local


# --- MDL-03 ------------------------------------------------------------------------------------------------


def mdl03_layer_precedence():
    reported = default_capabilities("local", context=32768)
    reported = ModelCapabilities(**{**reported.__dict__, "tools": False, "family": "reported"})
    recommended = {"capabilities": {"tools": True, "context_for_agents": 8192, "family": "recommended"}}
    override = {"context_for_agents": 6144}
    merged = layered(reported, recommended, override)
    assert merged.tools is True  # recommendation beats the provider
    assert merged.family == "recommended"
    assert merged.context_for_agents == 6144  # override beats both
    assert merged.context_window == 32768  # unset in both upper layers: the provider's value
    assert layered(reported, recommended, override, memory_context_cap=4096).context_for_agents == 4096
    assert layered(reported, recommended).context_for_agents == 8192


# --- MDL-05 ------------------------------------------------------------------------------------------------


def mdl05_local_candidate_required():
    assert load(ROUTER_YAML).tiers["fast"][0].locality == "local"
    bad = config(tiers__strong=["cloud:primary/strong-model", "cloud:fallback/strong-model"])
    with pytest.raises(RouterConfigError, match="tier strong has no local candidate"):
        load(bad)


def mdl05_no_egress_when_off():
    rng = random.Random(5)
    fake_cloud = ScriptedProvider(lambda m, msgs, body: {"reply": reply("cloud")}, kind="cloud")
    local_model = local(lambda m, msgs, body: {"reply": reply("local reply")})
    roles = ["coach", "diagnoser", "solver", "checker", "reflector"]
    # The adult setting would allow the cloud; disabling the router's cloud tier still prevents all egress.
    the_router = router(local_model, fake_cloud, config(cloud__enabled=False), cloud_on=lambda role: True)

    async def session() -> None:
        for turn in range(500):
            with turn_scope(f"t-{turn}"):
                result = await the_router.complete(rng.choice(roles), [Message("user", f"turn {turn}")])
                assert result.turn.text == "local reply"
                assert all(a["provider_kind"] == "local" for a in result.record.attempts)

    asyncio.run(session())
    assert fake_cloud.requests == [] and len(local_model.requests) == 500


# --- MDL-07 ------------------------------------------------------------------------------------------------


def mdl07_error_table_fixtures():
    rows = yaml.safe_load((FIXTURES / "mdl07_errors.yaml").read_text())
    assert {r["reason"] for r in rows} == set(REASONS)
    settings = Settings()
    for row in rows:
        failure = row["input"]
        if "status" in failure:
            reason = classify_http(failure["status"], failure.get("body"))
        elif "transport" in failure:
            reason = classify_transport(failure["transport"], failure["locality"] if "locality" in failure else "cloud")
        else:
            reason = "bad_response"
        assert reason == row["reason"], failure
        expected = row["actions"]
        assert [a for a in actions(reason, settings) if a != "none"] == expected, reason

        if "status" not in failure:
            continue
        # Through the router: the same model is tried retries+1 times, then the next candidate or a failure.
        retries = expected.count("retry")
        failing = local([{"error": failure}] * (retries + 1) + [{"reply": reply("second model")}])
        hooks = Hooks(compact=_same, shrink=_same, restart_runtime=_yes, lower_context=_yes_model)
        output = ("diagnosis", DIAGNOSIS_SCHEMA, DIAGNOSIS) if reason == "grammar_rejected" else None
        call = router(failing, hooks=hooks).complete("diagnoser", [Message("user", "x")], output=output)
        if expected[-1] == "fail":
            with pytest.raises(RouterError) as raised:
                run(call)
            assert raised.value.reason == reason and len(failing.requests) == retries + 1
        else:
            result = run(call)
            assert result.turn.text == "second model"
            assert [r["model"] for r in failing.requests] == ["qwen3-vl-8b"] * (retries + 1) + ["gemma-4-12b"], reason


async def _same(messages):
    return messages


async def _yes() -> bool:
    return True


async def _yes_model(model: str) -> bool:
    return True


# --- MDL-08 ------------------------------------------------------------------------------------------------


def mdl08_backoff_bounds():
    delays: list[float] = []
    phases: list[str] = []

    async def sleep(seconds: float) -> None:
        delays.append(seconds)

    limited = {"error": {"status": 429, "body": {"error": {"message": "slow down"}}}}
    provider = local([limited, limited, {"reply": reply("finally")}])
    hooks = Hooks(on_status=lambda phase, info: phases.append(phase))
    result = run(
        router(provider, sleep=sleep, hooks=hooks, rng=random.Random(3)).complete("diagnoser", [Message("user", "x")])
    )
    assert result.turn.text == "finally" and len(provider.requests) == 3
    backoff = Backoff(Settings(), random.Random(0))
    assert len(delays) == 2
    for index, delay in enumerate(delays):
        low, high = backoff.bounds(index)
        assert low <= delay <= high, (index, delay)
    assert (1.5, 2.5) == backoff.bounds(0) and (3.0, 5.0) == backoff.bounds(1)
    assert "retrying" in phases

    # Retry-After is honoured, up to the maximum.
    delays.clear()
    told = {"error": {"status": 429, "headers": {"Retry-After": "7"}}}
    run(router(local([told, {"reply": reply("ok")}]), sleep=sleep).complete("diagnoser", [Message("user", "x")]))
    assert delays == [7.0]

    # A wait that would break the Coach's first-token budget falls back instead of waiting.
    delays.clear()
    provider = local([limited, {"reply": reply("other model")}])
    result = run(router(provider, sleep=sleep).complete("coach", [Message("user", "x")], first_token_budget_s=1.0))
    assert delays == [] and result.turn.text == "other model"
    assert [r["model"] for r in provider.requests] == ["qwen3-vl-8b", "gemma-4-12b"]


# --- MDL-09 ------------------------------------------------------------------------------------------------


def mdl09_empty_twice_fallback():
    empty = {"reply": reply("   ")}
    provider = local([empty, empty, {"reply": reply("from the second model")}])
    result = run(router(provider).complete("coach", [Message("user", "hello")]))
    assert result.turn.text == "from the second model"
    assert [r["model"] for r in provider.requests] == ["qwen3-vl-8b", "qwen3-vl-8b", "gemma-4-12b"]  # never a third try
    assert {"event": "fallback", "from": "local:qwen3-vl-8b", "reason": "empty_twice"} in result.record.events

    # Text-written tool calls that cannot be salvaged, twice, fall back the same way.
    garbled = {"reply": reply('<tool_call>{"name": "math_solve", "arguments": {"equ</tool_call>')}
    provider = local([garbled, garbled, {"reply": reply("ok")}])
    result = run(router(provider).complete("solver", [Message("user", "solve")], [SOLVE]))
    assert result.turn.text == "ok" and len(provider.requests) == 3


# --- MDL-10 ------------------------------------------------------------------------------------------------


def mdl10_tools_not_rerun():
    executed: list[str] = []
    provider = local(
        [
            {"reply": reply("", [("call_a", "math_solve", '{"equations": ["2x=6"]}')])},
            {"error": {"status": 500, "body": "internal"}},
            {"reply": reply("x = 3")},
        ]
    )
    the_router = router(provider)

    async def engine_turn() -> str:
        messages = [Message("user", "Solve 2x = 6.")]
        for _ in range(3):
            result = await the_router.complete("solver", messages, [SOLVE])
            if not result.turn.tool_calls:
                return result.turn.text
            messages.append(Message("assistant", result.turn.text, tool_calls=tuple(result.turn.tool_calls)))
            for call in result.turn.tool_calls:  # tools run only after the call finished and was normalised
                executed.append(call.id)
                messages.append(Message("tool", '{"x": 3}', tool_call_id=call.id, name=call.name))
        return ""

    assert run(engine_turn()) == "x = 3"
    assert executed == ["call_a"]  # the failure after the tool round did not re-run the tool
    failed, retried = provider.requests[1], provider.requests[2]
    assert failed["messages"] == retried["messages"]
    assert retried["messages"][-1] == {
        "role": "tool",
        "content": '{"x": 3}',
        "tool_call_id": "call_a",
        "name": "math_solve",
    }


# --- MDL-13 ------------------------------------------------------------------------------------------------


def mdl13_split_tag_scrub():
    events = [
        {"choices": [{"delta": {"content": piece}}]}
        for piece in [
            "Sure. <thi",
            "nk>the answer is 42",
            " so hint</th",
            "ink>Try halving",
            " both sides.",
            " <think>left open",
        ]
    ]
    events.append({"choices": [{"delta": {}, "finish_reason": "stop"}]})
    seen: list[str] = []
    provider = local([{"events": events}])
    result = run(router(provider).complete("coach", [Message("user", "help")], on_text=seen.append))
    shown = "".join(seen)
    assert "<" not in shown and "think" not in shown and "42" not in shown and "left open" not in shown
    assert shown.startswith("Sure. Try halving both sides.")
    assert result.turn.text == "Sure. Try halving both sides."
    assert "the answer is 42" in result.turn.reasoning and "left open" in result.turn.reasoning

    # Every recorded inline-think stream: no tag or thought ever reaches a visible delta.
    for cassette in load_cassettes():
        if ".inline-think" not in cassette["scenario"]:
            continue
        seen.clear()
        replay = local(lambda m, msgs, body, events=cassette["events"]: {"events": events})
        try:
            run(router(replay).complete("coach", [Message("user", "x")], on_text=seen.append))
        except RouterError as error:  # a reply that is all thought is empty: it falls back, then fails
            assert error.reason == "bad_response", cassette["scenario"]
            assert error.trigger in ("empty_twice", "unparsed_tool_call_twice"), cassette["scenario"]
        assert "<think" not in "".join(seen) and "</think" not in "".join(seen), cassette["scenario"]


# --- MDL-14 ------------------------------------------------------------------------------------------------


def mdl14_salvage_offered_only():
    written = '<tool_call>{"name": "math_solve", "arguments": {"equations": ["x+1=3"]}}</tool_call>'
    found = salvage(written, {"math_solve"})
    assert found.calls == [ToolCall("", "math_solve", {"equations": ["x+1=3"]})] and found.text == ""
    unoffered = salvage(written.replace("math_solve", "python_run"), {"math_solve"})
    assert unoffered.calls == [] and unoffered.text.startswith("<tool_call>") and unoffered.unparsed
    assert salvage(written, set()).calls == []  # no tools offered: never salvaged
    bare = salvage('{"name": "math_solve", "arguments": {"equations": ["y=2"]}}', {"math_solve"})
    assert bare.calls[0].arguments == {"equations": ["y=2"]}

    # Through the router: ids are unique per turn, and an unoffered text call stays text (and counts as unparsed).
    two = written + written.replace("x+1=3", "x+2=3")
    result = run(router(local([{"reply": reply(two)}])).complete("solver", [Message("user", "x")], [SOLVE]))
    ids = [c.id for c in result.turn.tool_calls]
    assert len(ids) == 2 and len(set(ids)) == 2
    stray = {"reply": reply(written.replace("math_solve", "python_run"))}
    provider = local([stray, stray, {"reply": reply("plain")}])
    result = run(router(provider).complete("solver", [Message("user", "x")], [SOLVE]))
    assert result.turn.tool_calls == [] and result.turn.text == "plain"


# --- MDL-15 ------------------------------------------------------------------------------------------------

DIAGNOSIS = validator("agents/diagnosis")
DIAGNOSIS_SCHEMA = json.loads(
    (REPO_ROOT / "services/agent-core/agent_core/contracts/schemas/agents/diagnosis.schema.json").read_text()
)


def _valid_diagnosis() -> dict:
    examples = DIAGNOSIS_SCHEMA.get("examples")
    if examples:
        return examples[0]
    fixtures = sorted((REPO_ROOT / "evals" / "contracts" / "agents" / "diagnosis" / "valid").glob("*.json"))
    return json.loads(fixtures[0].read_text())


def mdl15_correction_without_schema():
    good = _valid_diagnosis()
    assert DIAGNOSIS.is_valid(good)
    provider = local([{"reply": reply('{"not": "a diagnosis"}')}, {"reply": reply(json.dumps(good))}])
    output = ("diagnosis", DIAGNOSIS_SCHEMA, DIAGNOSIS)
    result = run(
        router(provider).complete("diagnoser", [Message("user", "The student wrote 2x = 8, x = 6.")], output=output)
    )
    assert result.schema_valid is True and result.structured == good
    correction = provider.requests[1]["messages"][-1]
    assert correction["role"] == "user" and correction["content"].startswith(CORRECTION)
    schema_text = json.dumps(DIAGNOSIS_SCHEMA)
    assert schema_text not in json.dumps(provider.requests[1]["messages"])
    assert '"properties"' not in correction["content"] and "$schema" not in correction["content"]
    # The schema went to the decoder (grammar mode on a local model), not into the conversation.
    assert provider.requests[0]["response_format"]["type"] == "json_schema"
    assert [a["structured_mode"] for a in result.record.attempts] == ["grammar", "grammar"]
    assert [a["correction_retry"] for a in result.record.attempts] == [False, True]
    # The decoder schema keeps small limits and character-class patterns, so a model cannot overrun what validation
    # would refuse; large limits and rich patterns stay out (the runtime drops a grammar it cannot compile).
    cite = {"type": "string", "pattern": "^[a-z0-9][a-z0-9._-]{2,80}$"}
    decoded = decode_schema({"type": "object", "properties": {
        "check_id": {"type": "string", "pattern": "^chk_[A-Za-z0-9]{3,32}$"},
        "cites": {"type": "array", "maxItems": 4, "items": cite},
        "say": {"type": "string", "pattern": "^[^\\\\$]*$", "maxLength": 400},
        "notes": {"type": "array", "maxItems": 40, "items": {"type": "string", "maxLength": 5000}}}})  # fmt: skip
    assert decoded["properties"] == {
        "check_id": {"type": "string", "pattern": "^chk_[A-Za-z0-9]{3,32}$"},
        "cites": {"type": "array", "maxItems": 4, "items": cite},
        "say": {"type": "string", "maxLength": 400},
        "notes": {"type": "array", "items": {"type": "string"}}}  # fmt: skip

    # A second failure on the last candidate returns the raw text, marked invalid, with the errors.
    bad = {"reply": reply("not json at all")}
    only_one = config(tiers__fast=["local:qwen3-vl-8b"])
    result = run(router(local([bad, bad]), data=only_one).complete("diagnoser", [Message("user", "x")], output=output))
    assert result.schema_valid is False and result.structured is None and result.errors
    assert result.turn.text == "not json at all"


# --- MDL-30 ------------------------------------------------------------------------------------------------


def mdl30_trace_complete():
    student_text = "My name is Ama and I think x = 7"
    records = []
    limited = {"error": {"status": 429}}
    provider = local(
        [
            limited,
            {"reply": reply("first answer")},  # retry then success
            {"reply": reply("  ")},
            {"reply": reply("")},
            {"reply": reply("fallback")},  # empty twice, fallback
            {"reply": reply("{}")},
            {"reply": reply(json.dumps(_valid_diagnosis()))},  # correction turn
        ]
    )
    the_router = router(provider, hooks=Hooks(on_trace=records.append))

    async def session() -> None:
        with turn_scope("t-1"):
            await the_router.complete("coach", [Message("user", student_text)])
            await the_router.complete("coach", [Message("user", student_text)])
            await the_router.complete(
                "diagnoser", [Message("user", student_text)], output=("diagnosis", DIAGNOSIS_SCHEMA, DIAGNOSIS)
            )

    asyncio.run(session())
    assert len(records) == 3
    for record in records:
        assert record.candidates and record.tier and record.prompt_mode
        for attempt in record.attempts:
            assert contract_errors(TRACE_ITEM, attempt) == [], attempt
            for name in (
                "role",
                "tier",
                "model_requested",
                "model_served",
                "provider_kind",
                "tokens",
                "latency",
                "cost_usd",
                "finish_reason",
                "effort_requested",
                "effort_effective",
            ):
                assert name in attempt
        assert student_text not in json.dumps([record.attempts, record.events, record.dropped])
    assert [a.get("error_class") for a in records[0].attempts] == ["rate_limit", None]
    assert [e["event"] for e in records[1].events] == ["retry", "fallback"]
    assert records[1].attempts[-1]["fallback_from"] == "local:qwen3-vl-8b"
    assert [e["event"] for e in records[2].events] == ["correction"]


# --- pulled forward from M11: MDL-18 and MDL-20 subsets -----------------------------------------------------


def mdl18_context_rung_choice(tmp_path: Path):
    model = tmp_path / "fast-model.gguf"
    write_header(
        model,
        {
            "general.architecture": "qwen3",
            "qwen3.context_length": 40960,
            "qwen3.block_count": 36,
            "qwen3.embedding_length": 2560,
            "qwen3.attention.head_count": 32,
            "qwen3.attention.head_count_kv": 8,
            "qwen3.attention.key_length": 128,
            "qwen3.attention.value_length": 128,
        },
        pad_to=3 * GB,
    )
    info = read_header(model)
    settings = Settings()
    ladder = load(ROUTER_YAML).local["ladder"]
    local_cfg = load(ROUTER_YAML).local
    eight = 8 * GB
    chosen = choose_context(
        info,
        eight,
        hardware_class(8),
        ladder,
        local_cfg["memory_headroom_gb"],
        local_cfg["min_agent_context"],
        settings,
    )
    assert hardware_class(8) == "low" and chosen == 6144
    args = launch_arguments(str(tmp_path), chosen, 18080, str(tmp_path / "key"), slots=1)
    assert args[args.index("--ctx-size") + 1] == "6144" and args[args.index("--host") + 1] == "127.0.0.1"
    sixteen = choose_context(info, 16 * GB, hardware_class(16), ladder, 2, 6144, settings)
    assert sixteen == 8192
    assert choose_context(info, int(6.5 * GB), "low", ladder, 2, 6144, settings) is None  # cannot fit 6,144


def mdl20_health_is_not_ready():
    async def scenario() -> None:
        async with FakeLlamaServer(
            ["qwen3-1.7b"], script=lambda body: {"status": 500, "body": {"error": {"message": "failed to load model"}}}
        ) as server:
            provider = LlamaServerProvider(server.url, server.api_key)
            health = await provider.client.get("/health")
            assert health.status == 200
            assert await provider.ready("qwen3-1.7b") is False
            server.script = lambda body: {"reply": reply("OK", model="qwen3-1.7b")}
            assert await provider.ready("qwen3-1.7b") is True
            ready_request = server.requests[-1]
            assert ready_request["max_tokens"] == 8 and ready_request["tools"]  # through the tool template
            await provider.close()

    asyncio.run(scenario())


def test_router_yaml_matches_keys():
    """The shipped router configuration's retry values equal the declared configuration keys (no second source)."""
    retry = load(ROUTER_YAML).retry
    settings = Settings()
    assert retry["same_model"] == settings.router_retry_same_model
    assert retry["backoff"] == {
        "initial_s": settings.router_backoff_initial_s,
        "factor": settings.router_backoff_factor,
        "max_s": settings.router_backoff_max_s,
        "jitter": settings.router_backoff_jitter,
    }
    assert copy.deepcopy(load(ROUTER_YAML).cloud)["enabled"] is True  # Hackathon fork; runtime consent still gates it.


def test_hybrid_gguf_layers_preserve_exact_kv_heads_instead_of_crashing_launch(tmp_path: Path):
    model = tmp_path / "hybrid.gguf"
    write_header(
        model,
        {
            "general.architecture": "gemma4",
            "gemma4.block_count": 2,
            "gemma4.context_length": 8192,
            "gemma4.embedding_length": 3840,
            "gemma4.attention.head_count": 16,
            "gemma4.attention.head_count_kv": [1, 8],
            "gemma4.attention.key_length": 512,
            "gemma4.attention.value_length": 512,
            "general.file_type": 15,
        },
    )
    info = read_header(model)
    assert info.kv_heads_per_layer == (1, 8) and info.file_type == 15
    assert info.kv_bytes_per_token() == 9 * (512 + 512) * 2
    assert choose_context(info, 128 * GB, "high", [6144, 8192], 2, 6144, Settings()) == 8192


@pytest.mark.parametrize("heads", [[1], [0, 8], [1, 32]])
def test_malformed_hybrid_heads_are_a_handled_header_error(tmp_path: Path, heads):
    from agent_core.providers.gguf import GgufError

    model = tmp_path / "invalid-hybrid.gguf"
    write_header(
        model,
        {
            "general.architecture": "gemma4",
            "gemma4.block_count": 2,
            "gemma4.attention.head_count": 16,
            "gemma4.attention.head_count_kv": heads,
        },
    )
    with pytest.raises(GgufError, match="per-layer"):
        read_header(model)
