"""M11.c: reasoning effort mapping, learned feature rejections and the parameter-fix retry, auxiliary slots, local
scheduling with per-role limits, and the model-tier tool profiles (MDL-04, MDL-06, MDL-11, MDL-12, MDL-22, TOL-17).
Every provider and fixture here is synthetic."""

import asyncio
import json
import time
from dataclasses import replace
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.contracts import validator
from agent_core.engine import job_scope, turn_scope
from agent_core.engine.events import new_id
from agent_core.engine.state import BoardStep, SessionState
from agent_core.engine.ui import update_board
from agent_core.providers.base import Message
from agent_core.providers.errors import rejected_parameter
from agent_core.providers.llama import LlamaServerProvider
from agent_core.providers.scripted import ScriptedProvider, default_capabilities
from agent_core.router import Hooks, Router, RouterError, Shared, tool_profile
from agent_core.router.config import Candidate, load
from agent_core.router.effort import plan
from agent_core.router.features import FeatureRejections
from agent_core.router.fit import launch_arguments
from agent_core.router.structured import OUTPUT_TOOL
from agent_core.router.trace import CONTRACT as TRACE_ITEM
from agent_core.tools.catalogue import Availability, role_tools, visible_tools
from agent_core.tools.generated.register import REGISTER
from agent_core.tools.registry import register_entries
from agent_core.tools.spec import SessionCtx, ToolMeta, ToolSpec
from engine_harness import STATEMENT, checker_steps, close, make_engine, solver_steps, tutor
from jana_tools import REPO_ROOT
from jana_tools.fakes import FakeLlamaServer

CORE = REPO_ROOT / "services" / "agent-core" / "agent_core"
ROUTER_YAML = CORE / "router" / "router.yaml"
GOLDEN_BOARD = Path(__file__).parent / "fixtures" / "update_board_golden.yaml"
SOLVER_MANIFEST = REPO_ROOT / "content" / "agent" / "roles" / "solver.md"
DIAGNOSIS = validator("agents/diagnosis")
DIAGNOSIS_SCHEMA = json.loads((CORE / "contracts" / "schemas" / "agents" / "diagnosis.schema.json").read_text())
OUTPUT = ("diagnosis", DIAGNOSIS_SCHEMA, DIAGNOSIS)
MODELS = ["qwen3-vl-8b", "gemma-4-12b"]
SAFE = "Which quantities does the question give you, and which one does it ask for?"


def reply(content: str = "", calls: list[tuple[str, str, str]] = (), model: str = "qwen3-vl-8b") -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": i, "type": "function", "function": {"name": n, "arguments": a}} for i, n, a in calls
        ]
    return {
        "model": model,
        "choices": [{"message": message, "finish_reason": "tool_calls" if calls else "stop"}],
        "usage": {"prompt_tokens": 40, "completion_tokens": 12},
    }


def config(**changes: Any) -> dict:
    data = yaml.safe_load(ROUTER_YAML.read_text())
    for path, value in changes.items():
        node = data
        *parents, last = path.split("__")
        for part in parents:
            node = node[part]
        node[last] = value
    return data


async def _no_sleep(_: float) -> None:
    return None


def make_router(provider: Any, data: dict | None = None, **kwargs: Any) -> Router:
    providers = {"local": provider, **kwargs.pop("providers", {})}
    return Router(load(data or config()), kwargs.pop("settings", Settings()), providers, sleep=_no_sleep, **kwargs)


def scripted(script: Any, models: list[str] = MODELS, **kwargs: Any) -> ScriptedProvider:
    return ScriptedProvider(script, kind="local", installed_models=list(models), **kwargs)


def in_turn(coro: Any) -> Any:
    async def scoped() -> Any:
        with turn_scope("t-m11c"):
            return await coro

    return asyncio.run(scoped())


def _valid_diagnosis() -> dict:
    examples = DIAGNOSIS_SCHEMA.get("examples")
    if examples:
        return examples[0]
    fixtures = sorted((REPO_ROOT / "evals" / "contracts" / "agents" / "diagnosis" / "valid").glob("*.json"))
    return json.loads(fixtures[0].read_text())


# --- MDL-12 ------------------------------------------------------------------------------------------------


def mdl12_effort_mapping():
    # The mapping is checked with a class that allows thinking; the shipped budget has it off on every class (D6).
    settings = Settings(router_thinking_budget=(0, 0, 1000))
    toggle = default_capabilities("local")
    assert toggle.reasoning == "toggle"
    high_class_budget = settings.router_thinking_budget[2]
    shipped_off = plan("high", toggle, "high", Settings())
    assert (shipped_off.effective, shipped_off.control, shipped_off.budget_tokens) == ("none", "off", 0)
    on = plan("high", toggle, "high", settings)
    assert (on.requested, on.effective, on.control, on.budget_tokens) == ("high", "high", "on", high_class_budget)
    for hardware in ("low", "mid"):  # thinking off for every role on the low and mid classes
        off = plan("high", toggle, hardware, settings)
        assert (off.requested, off.effective, off.control) == ("high", "none", "off")
    # An unsupported level maps to the nearest supported one: an effort-level endpoint has no "off".
    effort_model = replace(default_capabilities("cloud"), reasoning="effort")
    assert plan("none", effort_model, None, settings).effective == "low"
    assert plan("medium", effort_model, None, settings).control == "medium"
    budget_model = replace(toggle, reasoning="budget")
    capped = plan("high", budget_model, "high", settings)
    assert capped.control == "budget"
    assert capped.budget_tokens == min(settings.router_effort_budget[3], high_class_budget)
    assert plan("high", replace(toggle, reasoning="none"), "high", settings).effective == "none"

    async def scenario() -> tuple[list[dict], list[Any]]:
        records: list[Any] = []
        async with FakeLlamaServer(["gemma-4-12b"]) as server:  # a toggle-only local model behind llama-server
            provider = LlamaServerProvider(server.url, server.api_key)
            for hardware in ("high", "mid"):
                server.script.append({"reply": reply("A plan.", model="gemma-4-12b")})
                the_router = make_router(provider, hardware_class=hardware, hooks=Hooks(on_trace=records.append),
                                         settings=settings)  # fmt: skip
                with turn_scope("t-effort"):
                    await the_router.complete("solver", [Message("user", "Plan the solution.")])  # solver: high
            await provider.close()
            return server.requests, records

    requests, records = asyncio.run(scenario())
    assert [r["chat_template_kwargs"] for r in requests] == [{"enable_thinking": True}, {"enable_thinking": False}]
    assert records[0].efforts[0]["control"] == "on" and records[0].efforts[0]["budget_tokens"] == high_class_budget
    assert records[1].efforts[0]["control"] == "off"
    high_call, mid_call = (record.model_calls()[0] for record in records)
    assert (high_call["effort_requested"], high_call["effort_effective"]) == ("high", "high")
    assert (mid_call["effort_requested"], mid_call["effort_effective"]) == ("high", "none")
    for call in (high_call, mid_call):
        assert contract_errors(TRACE_ITEM, call) == [], call
    # The class budget is fixed when the runtime is launched, and the router configuration mirrors the key.
    args = launch_arguments("models", 16384, 18080, "key", slots=2, thinking_budget=high_class_budget)
    assert args[args.index("--reasoning-budget") + 1] == str(high_class_budget)
    shipped = load(ROUTER_YAML).local["thinking_budget"]
    assert shipped == dict(zip(("low", "mid", "high"), Settings().router_thinking_budget, strict=True))


# --- MDL-04 ------------------------------------------------------------------------------------------------

REFUSED_FORMAT = {
    "status": 400,
    "body": {
        "error": {
            "message": "Unsupported parameter: 'response_format' is not supported with this model.",
            "type": "invalid_request_error",
            "param": "response_format",
        }
    },
}


def mdl04_feature_rejection_remembered():
    good = _valid_diagnosis()
    assert DIAGNOSIS.is_valid(good)

    def endpoint(model: str, messages: list, body: dict) -> dict:
        if "response_format" in body:
            return {"error": REFUSED_FORMAT}
        assert body["tool_choice"]["function"]["name"] == OUTPUT_TOOL  # the next structured mode: a forced tool
        return {"reply": reply("", [("c1", OUTPUT_TOOL, json.dumps(good))])}

    saved: list[dict] = []
    provider = scripted(endpoint)
    the_router = make_router(provider, shared=Shared(rejections=FeatureRejections(on_change=saved.append)))
    first = in_turn(the_router.complete("diagnoser", [Message("user", "2x = 8, x = 6")], output=OUTPUT))
    assert first.schema_valid is True and first.structured == good
    assert ["response_format" in r for r in provider.requests] == [True, False]
    assert [a["structured_mode"] for a in first.record.attempts] == ["grammar", "tool"]
    assert [e["event"] for e in first.record.events] == ["reissue"]
    # Later requests to that model start in the next mode: no second rejection.
    second = in_turn(the_router.complete("diagnoser", [Message("user", "2x = 8, x = 6")], output=OUTPUT))
    assert second.schema_valid is True and len(provider.requests) == 3
    assert "response_format" not in provider.requests[2]
    assert [a["structured_mode"] for a in second.record.attempts] == ["tool"]
    # The pair is kept for the install: the saved state given back after a restart holds.
    assert saved[-1] == {"local:qwen3-vl-8b": {"response_format": None}}
    restarted = scripted(endpoint)
    again = make_router(restarted, shared=Shared(rejections=FeatureRejections(fixes=saved[-1])))
    in_turn(again.complete("diagnoser", [Message("user", "2x = 8, x = 6")], output=OUTPUT))
    assert len(restarted.requests) == 1 and "response_format" not in restarted.requests[0]
    # Another model of the same tier is untouched.
    learned = Shared(rejections=FeatureRejections(saved[-1]))
    other = make_router(scripted(endpoint, models=["gemma-4-12b"]), shared=learned)
    result = in_turn(other.complete("diagnoser", [Message("user", "x")], output=OUTPUT))
    assert result.record.attempts[0]["structured_mode"] == "grammar"


# --- MDL-11 ------------------------------------------------------------------------------------------------

RENAMED = "Unsupported parameter: 'max_tokens' is not supported with this model. Use 'max_completion_tokens' instead."


def _refusal(param: str, message: str) -> dict:
    return {"status": 400, "body": {"error": {"message": message, "type": "invalid_request_error", "param": param,
                                              "code": "unsupported_parameter"}}}  # fmt: skip


def mdl11_param_fix_once():
    # The rejected parameter and its suggested replacement are read once, at the provider boundary.
    assert rejected_parameter(_refusal("max_tokens", RENAMED)["body"]) == ("max_tokens", "max_completion_tokens")
    assert rejected_parameter({"error": {"message": RENAMED}}) == ("max_tokens", "max_completion_tokens")
    assert rejected_parameter({"error": {"message": "Unknown parameter: 'seed'."}}) == ("seed", None)

    def endpoint(model: str, messages: list, body: dict) -> dict:
        if "max_tokens" in body:
            return {"error": _refusal("max_tokens", RENAMED)}
        return {"reply": reply("Speed is distance over time.")}

    provider = scripted(endpoint)
    the_router = make_router(provider)
    result = in_turn(the_router.complete("coach", [Message("user", "What is speed?")], max_tokens=300))
    assert result.turn.text == "Speed is distance over time."
    assert len(provider.requests) == 2  # the single fixed retry
    fixed = provider.requests[1]
    assert fixed["max_completion_tokens"] == 300 and "max_tokens" not in fixed
    assert fixed["messages"] == provider.requests[0]["messages"]  # exactly that parameter changed
    assert result.record.events == [{"event": "retry", "reason": "format_error", "preparation": "param_fix"}]
    assert [a.get("reason") for a in result.record.attempts] == ["format_error", None]
    # Remembered (MDL-04): the next call is sent fixed.
    in_turn(the_router.complete("coach", [Message("user", "And velocity?")], max_tokens=300))
    assert len(provider.requests) == 3 and provider.requests[2]["max_completion_tokens"] == 300

    # Only once per call: an endpoint that still refuses after the fix is not retried a third time.
    def stubborn(model: str, messages: list, body: dict) -> dict:
        return {"error": _refusal("temperature", "Unsupported parameter: 'temperature'.")}

    refusing = scripted(stubborn, models=["qwen3-vl-8b"])
    one_model = config(tiers__fast=["local:qwen3-vl-8b", "cloud:primary/fast-model"])
    with pytest.raises(RouterError) as failed:
        in_turn(make_router(refusing, one_model).complete("coach", [Message("user", "x")]))
    assert failed.value.reason == "format_error"
    assert len(refusing.requests) == 2 and "temperature" not in refusing.requests[1]


# --- MDL-06 ------------------------------------------------------------------------------------------------


def mdl06_slot_inheritance():
    provider = scripted(lambda model, messages, body: {"reply": reply("Motion under gravity", model=model)})
    unset = config()
    del unset["auxiliary"]["title"]
    the_router = make_router(provider, unset)
    coach_model = asyncio.run(the_router.main_local_model())
    assert coach_model == Candidate.parse("local:qwen3-vl-8b")
    title = asyncio.run(the_router.resolve_slot("title"))
    assert title.inherited and title.candidates[0] == coach_model and not title.disabled and title.notice is None
    result = in_turn(the_router.complete("title", [Message("user", "Name this session in six words.")]))
    assert provider.requests[-1]["model"] == "qwen3-vl-8b"
    call = result.record.model_calls()[0]
    assert (call["role"], call["slot"], call["tier"]) == ("title", "title", "fast")
    assert contract_errors(TRACE_ITEM, call) == [], call
    # A slot set to a tier uses that tier.
    judge = asyncio.run(the_router.resolve_slot("judge"))
    assert judge.tier == "judge" and not judge.inherited

    # A text-only main model and no vision slot: photo input is off, with its notice (PRM-17).
    no_vision = config()
    del no_vision["auxiliary"]["vision"]
    off = asyncio.run(make_router(provider, no_vision).resolve_slot("vision"))
    assert off.disabled and off.notice == "Photo reading isn't available on this computer yet."
    assert off.dropped == {"local:qwen3-vl-8b": "lacks vision"}
    # With a configured photo-reading model as the fallback, the slot resolves to it.
    reader_caps = replace(default_capabilities("local"), vision=True)
    readers = scripted(lambda m, ms, b: {"reply": reply("x")}, models=[*MODELS, "photo-reader-8b"],
                       caps={"photo-reader-8b": reader_caps})  # fmt: skip
    with_reader = config(auxiliary__vision={"inherit": True, "model": "local:photo-reader-8b"})
    on = asyncio.run(make_router(readers, with_reader).resolve_slot("vision"))
    assert [str(c) for c in on.candidates] == ["local:photo-reader-8b"] and not on.inherited and on.notice is None
    # A main model with its projector reads photos itself.
    seeing = scripted(lambda m, ms, b: {"reply": reply("x")}, caps={"qwen3-vl-8b": reader_caps})
    assert asyncio.run(make_router(seeing, no_vision).resolve_slot("vision")).inherited


# --- MDL-22 ------------------------------------------------------------------------------------------------


def mdl22_foreground_preempts():
    settings = Settings()
    started: dict[str, list[float]] = {"reflector": [], "coach": []}

    def reflector_step(body: dict) -> dict:
        started["reflector"].append(time.monotonic())
        stall = 30 if len(started["reflector"]) == 1 else 0  # the first generation would run long
        return {"stall_s": stall, "reply": reply("A note for next time.", model="gemma-4-12b")}

    def coach_step(body: dict) -> dict:
        started["coach"].append(time.monotonic())
        return {"reply": reply("Which quantity does the question ask for?")}

    provider = scripted({"reflector": [reflector_step, reflector_step], "coach": [coach_step]})
    the_router = make_router(provider, hardware_class="mid")  # one local slot

    async def scenario() -> tuple[float, Any, Any]:
        with job_scope("j-reflect"):
            background = asyncio.ensure_future(the_router.complete("reflector", [Message("user", "Reflect.")]))
        while not started["reflector"]:
            await asyncio.sleep(0.005)
        asked = time.monotonic()
        with turn_scope("t-coach"):
            coach = await the_router.complete("coach", [Message("user", "s = 3 m")])
        return asked, coach, await background

    asked, coach, reflection = asyncio.run(scenario())
    assert started["coach"][0] - asked < settings.router_preempt_start_ms / 1000
    assert coach.turn.text == "Which quantity does the question ask for?"
    # The Reflector was cancelled and queued again behind the Coach; it still completes.
    assert len(started["reflector"]) == 2 and started["reflector"][1] >= started["coach"][0]
    assert reflection.turn.text == "A note for next time."
    scheduler = the_router.shared.scheduler
    assert scheduler is not None and scheduler.preemptions == 1 and not scheduler.running and not scheduler.waiting
    assert coach.record.model_calls()[0]["latency"]["queue_ms"] < settings.router_preempt_start_ms
    # Per-role limits come from the configuration, which mirrors the keys.
    assert scheduler.limits == {"coach": settings.router_concurrency_coach,
                                "checker": settings.router_concurrency_checker,
                                "reflector": settings.router_concurrency_reflector}  # fmt: skip

    # The queue is ordered by priority: with the slot busy, the Diagnoser goes before an earlier title request.
    order: list[str] = []

    def step_for(role: str, stall: float = 0.0) -> Any:
        def step(body: dict) -> dict:
            order.append(role)
            return {"stall_s": stall, "reply": reply(f"{role} reply")}

        return step

    queued = scripted({"solver": [step_for("solver", 0.2)], "title": [step_for("title")],
                       "diagnoser": [step_for("diagnoser")]}, models=["qwen3-vl-8b"])  # fmt: skip
    busy = make_router(queued, hardware_class="mid")

    async def queue() -> None:
        with turn_scope("t-queue"):
            first = asyncio.ensure_future(busy.complete("solver", [Message("user", "plan")]))
            while not order:
                await asyncio.sleep(0.005)
            title = asyncio.ensure_future(busy.complete("title", [Message("user", "name it")]))
            await asyncio.sleep(0.02)
            diagnosis = asyncio.ensure_future(busy.complete("diagnoser", [Message("user", "diagnose")]))
            await asyncio.gather(first, title, diagnosis)

    asyncio.run(queue())
    assert order == ["solver", "diagnoser", "title"]

    # The Checker's limit holds on the cloud too; usage and cost are accounted per role.
    peak = [0]

    def checker_step(body: dict) -> dict:
        return {"stall_s": 0.05, "reply": reply("verdict", model="primary-small")}

    cloud = ScriptedProvider({"checker": [checker_step] * 6}, kind="cloud", price_per_mtok=(1.0, 2.0))
    online = make_router(scripted([]), config(cloud__enabled=True, roles__checker__prefer="cloud"),
                         providers={"cloud": cloud}, cloud_on=lambda role: True)  # fmt: skip

    async def checks() -> None:
        async def watch() -> None:
            while True:
                scheduler = online.shared.scheduler
                if scheduler is not None:
                    peak[0] = max(peak[0], scheduler.in_flight("checker"))
                await asyncio.sleep(0.002)

        watcher = asyncio.ensure_future(watch())
        with turn_scope("t-checks"):
            await asyncio.gather(*(online.complete("checker", [Message("user", f"check {n}")]) for n in range(6)))
        watcher.cancel()

    asyncio.run(checks())
    assert peak[0] == settings.router_concurrency_checker
    usage = online.shared.usage["checker"]
    assert usage.calls == 6 and usage.input_tokens == 6 * 40 and usage.cost_usd > 0
    assert the_router.shared.usage["coach"].calls == 1 and the_router.shared.usage["reflector"].calls == 1


# --- TOL-17 ------------------------------------------------------------------------------------------------


def tol17_small_profile_filtered():
    settings = Settings()
    assert tool_profile("fast", "local") == "small"
    assert tool_profile("strong", "local") == tool_profile("fast", "cloud") == "full"
    assert tool_profile("strong", "local", fast_model=True) == "small"
    provider = scripted([])
    # D128: with only fast-tier models installed the strong tier falls back to one of them, the same small model.
    assert asyncio.run(make_router(provider).profile("solver")) == "small"
    large = scripted([], models=["gemma-4-26b-a4b", *MODELS])
    assert asyncio.run(make_router(large).profile("solver")) == "full"  # the strong tier's own local model
    assert asyncio.run(make_router(provider).profile("coach")) == "small"  # the local fast tier
    assert asyncio.run(make_router(provider, config(roles__solver__tier="fast")).profile("solver")) == "small"

    # The S2 catalogue from the tool register (the S2 compute tools' argument schemas are not built yet).
    specs = {name: ToolSpec(name, toolset, 1, entry["stage"], f"{name}.", {"type": "object", "properties": {}},
                            ToolMeta.from_register(entry))
             for name, (toolset, entry) in register_entries(REGISTER, "S2").items()}  # fmt: skip
    catalogue: Any = SimpleNamespace(specs=specs)
    manifest = yaml.safe_load(SOLVER_MANIFEST.read_text().split("---")[1])
    names = role_tools("solver", manifest["tools"], catalogue, REGISTER["roleGrants"])
    assert any(n.startswith("acc_") for n in names) and any(n.startswith("chem_") for n in names)
    session = SessionCtx(profile="small", subject="chemistry", level="O", role="solver", stage="S2")
    grants = REGISTER["roleGrants"]
    small = visible_tools("solver", names, catalogue, session, Availability(lambda s, c: True, 0), grants, settings)
    assert 0 < len(small) <= settings.tool_small_max_tools
    assert not [s.name for s in small if s.name.startswith("acc_") or "accounting" in s.meta.subjects]
    assert all(s.meta.small_model_friendly and s.meta.risk != "ui" for s in small)
    full = visible_tools("solver", names, catalogue, replace(session, profile="full"),
                         Availability(lambda s, c: True, 0), grants, settings)  # fmt: skip
    assert len(full) > len(small) and not [s.name for s in full if s.name.startswith("acc_")]


def _normalised(events: list[dict]) -> list[dict]:
    """Board events with their ids replaced by kind and order of first appearance (brd_1, stp_1, ...)."""
    names: dict[str, str] = {}

    def name(value: str) -> str:
        kind = value[:3]
        if value not in names:
            names[value] = f"{kind}_{sum(1 for v in names.values() if v.startswith(kind)) + 1}"
        return names[value]

    out = []
    for event in events:
        event = dict(event)
        for key in ("board_id", "step_id"):
            if key in event:
                event[key] = name(event[key])
        if "step_ids" in event:
            event["step_ids"] = [name(s) for s in event["step_ids"]]
        out.append(event)
    return out


def tol17_board_paths_equivalent(tmp_path: Path):
    golden = yaml.safe_load(GOLDEN_BOARD.read_text())
    # The update_board handler on its own.
    state = SessionState(new_id("ses"), subject="physics", level="O")
    for line in golden["board_before"]:
        state.board.steps.append(
            BoardStep(new_id("stp"), len(state.board.steps), line["latex"], None, line["owner"], line["status"])
        )
    handled = update_board(golden["ops"], state, {Fraction(n) for n in range(1, 6)})
    assert handled.applied and _normalised(handled.events) == golden["events"]

    # The same ops in a Coach tutor turn, applied in Finalise.
    student_line = golden["board_before"][0]["latex"]

    async def scenario() -> list[dict]:
        coach = [tutor(SAFE), tutor(SAFE, board=golden["ops"])]
        engine, _ = await make_engine(tmp_path, {"solver": solver_steps(), "checker": checker_steps(), "coach": coach})
        try:
            await engine.start_problem(STATEMENT)
            before = len(engine.events.frames)
            result = await engine.student_turn(student_line)
            assert result.status == "complete"
            frames = [f["event"] for f in engine.events.frames[before:]]
        finally:
            await close(engine)
        board_parts = [f["part_id"] for f in frames if f["type"] == "part.start" and f["kind"] == "board"]
        last = board_parts[-1]
        inside, events = False, []
        for frame in frames:
            if frame["type"] == "part.start" and frame.get("part_id") == last:
                inside = True
            elif frame["type"] == "part.end" and frame.get("part_id") == last:
                break
            elif inside and frame["type"].startswith("board."):
                events.append(frame)
        return events

    finalised = asyncio.run(scenario())
    assert _normalised(finalised) == golden["events"]
