"""D128: the lean turn on the low hardware class and the runtime that keeps every role's prompt prefix cached (AGT-28,
MDL-16a, MDL-22, ARC-22, DAT-14). Engine replies are scripted; the runtime is the loopback fake."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from agent_core.assets.skills import SkillSet
from agent_core.config import Settings
from agent_core.contracts import validator
from agent_core.engine import lean
from agent_core.engine.assembly import DEV_SKILL_STATUSES, bundled_schemas
from agent_core.prompts.builder import Message, PromptSession, build_prompt
from agent_core.providers.base import Message as ProviderMessage
from agent_core.providers.llama import LlamaServerProvider
from agent_core.router.fit import launch_arguments
from engine_harness import STATEMENT, close, reply, solver_steps, tutor
from engine_harness import make_engine as harness_engine
from jana_tools import REPO_ROOT
from jana_tools.fakes import FakeLlamaServer
from m14_harness import busy_settings
from test_m4e_prompts import OUTPUTS, SCHEMAS, assets

MODEL = "qwen3-vl-8b"
LEAN_DIAGNOSIS = {"in_scope": True, "subject": "physics", "topic_ref": None, "kc_refs": [],
                  "question_kind": "calculation",
                  "knowns": [{"symbol": "u", "value": "14", "unit": "m/s"}], "unknowns": ["height"],
                  "clarifying_question": None, "misconception_ref": None, "evidence": []}  # fmt: skip


LOOP = asyncio.new_event_loop()


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def test_agt28_lean_decode_shape_completes_to_the_full_contract() -> None:
    """The low class decodes the Diagnoser without the fields the engine only stores; the engine's values complete
    the reply and it meets the full contract. A photo's knowns keep their quotes (photo givens quote the text)."""
    schemas = bundled_schemas()
    full = schemas["agents/diagnosis"]
    shape = lean.decode_schema("agents/diagnosis", full)
    assert {"inference", "prerequisite_gap_refs", "confidence"}.isdisjoint(shape["properties"])
    assert "quote" not in shape["properties"]["knowns"]["items"]["properties"]
    assert "quote" in lean.decode_schema("agents/diagnosis", full, keep_quotes=True)["properties"]["knowns"]["items"][
        "required"]  # fmt: skip
    assert "inference" in full["properties"]  # the shared contract itself is untouched
    assert list(validator("agents/diagnosis").iter_errors(LEAN_DIAGNOSIS))  # the lean reply alone is not a diagnosis
    completed = lean.completed("agents/diagnosis", LEAN_DIAGNOSIS)
    assert not list(validator("agents/diagnosis").iter_errors(completed)), completed
    assert completed["knowns"][0]["quote"] == "" and completed["confidence"] == "medium"
    # The Coach decodes no visual on the low class.
    turn = lean.decode_schema("agents/tutor-turn", schemas["agents/tutor-turn"])
    assert turn["properties"]["visual"]["maxItems"] == 0


def _lean_diagnosis_reply() -> dict[str, Any]:
    return reply(json.dumps(LEAN_DIAGNOSIS))


def test_agt28_low_class_turn_is_lean(tmp_path: Path) -> None:
    """On the low class a new problem costs one Diagnoser call with the lean shape, and the Coach opens it in one call
    with no tools offered; a reply with two asks is repaired to its first, not regenerated (PED-28)."""
    script = {"input_guard": [reply(json.dumps({"class": "in_scope", "confidence": 0.9}))],
              "diagnoser": [_lean_diagnosis_reply()], "solver": solver_steps(),
              "coach": [tutor("How fast is it going at the top? And what does the question ask for?")]}  # fmt: skip
    engine, provider = run(harness_engine(tmp_path, script, settings=busy_settings(), hardware_class="low", stage="S2"))
    try:
        result = run(engine.start_problem(STATEMENT))
    finally:
        run(close(engine))
    assert result.status == "complete", result
    assert engine.diagnosis is not None and engine.diagnosis.output["inference"] == ""
    coach = [r for r in provider.requests if r["_role"] == "coach"]
    assert len(coach) == 1 and not coach[0].get("tools")
    assert engine.events.student_text(result.turn_id).endswith("How fast is it going at the top?")
    diagnoser = [r for r in provider.requests if r["_role"] == "diagnoser"]
    assert len(diagnoser) == 1 and "Misconceptions:" not in json.dumps(diagnoser[0]["messages"])


def test_prm09_low_class_topic_opens_the_first_user_message() -> None:
    """On the low class the pushed teaching skill (tier 5) opens the first user message, so the system prompt (and the
    tools the template renders after it) is one prefix for the whole session; elsewhere it stays in the system."""
    skill = SkillSet.load(REPO_ROOT / "skills", DEV_SKILL_STATUSES).skills["phy-o-motion"]
    loaded = assets()
    for hardware, inside in (("low", False), ("mid", True)):
        session = PromptSession(teaching_skill=skill, task="Solve it.", hardware_class=hardware)
        built = build_prompt("solver", "qwen3", session, [], set(), set(), loaded, Settings(),
                             SCHEMAS[OUTPUTS["solver"]])  # fmt: skip
        system, task = built.messages[0].content, built.messages[1].content
        assert ("phy-o-motion" in system) is inside, hardware
        assert ("phy-o-motion" in task) is not inside and task.endswith("Solve it."), hardware
    bare = PromptSession(task="Solve it.", hardware_class="low")
    other = PromptSession(teaching_skill=skill, task="Solve another.", hardware_class="low")
    first = build_prompt("solver", "qwen3", bare, [], set(), set(), loaded, Settings(), SCHEMAS[OUTPUTS["solver"]])
    second = build_prompt("solver", "qwen3", other, [], set(), set(), loaded, Settings(), SCHEMAS[OUTPUTS["solver"]])
    assert first.messages[0].content == second.messages[0].content  # the warm-up's prefix is the turn's
    assert isinstance(first.messages[1], Message)


def test_mdl22_launch_keeps_role_prefixes_and_erases_everything() -> None:
    """One slot per pinned role in a unified f16 pool with room for their prefixes, each request still limited to
    the agent context; no host prompt cache and no idle-slot spill, so an erase leaves no tokens (DAT-14), and the
    slot save path that enables the erase action."""
    args = launch_arguments("models", 6144, 18080, "key", slots=1, settings=Settings(), slot_dir="/data/kv")
    value = {a: args[i + 1] for i, a in enumerate(args[:-1])}
    assert value["--kv-unified-per-slot"] == "6144" and value["--ctx-size"] == str(6144 + 2048)
    assert value["--parallel"] == "4" and value["--cache-ram"] == "0" and value["--slot-save-path"] == "/data/kv"
    assert value["--cache-type-k"] == value["--cache-type-v"] == "f16"
    assert "--kv-unified" in args and "--no-cache-idle-slots" in args
    plain = launch_arguments("models", 6144, 18080, "key", slots=1)
    assert plain[plain.index("--ctx-size") + 1] == "6144" and "--kv-unified" not in plain


def test_mdl22_warm_up_yields_to_real_calls() -> None:
    """The warm-up reads each role's prefix into the role's pinned slot with a one-token request; a real call that
    starts meanwhile goes first, and the abandoned prefix is read again after it (ARC-22, D123)."""

    def answer(body: dict[str, Any]) -> dict[str, Any]:
        content = "OK" if body.get("max_tokens") == 1 else "real"
        return {"stall_s": 0.4 if body.get("max_tokens") == 1 else 0.0,
                "reply": {"choices": [{"index": 0, "finish_reason": "stop",
                                       "message": {"role": "assistant", "content": content}}],
                          "usage": {"prompt_tokens": 5, "completion_tokens": 1}}}  # fmt: skip

    async def scenario() -> tuple[list[dict[str, Any]], int, str]:
        props = {MODEL: {"default_generation_settings": {"n_ctx": 6144}, "total_slots": 4, "chat_template": "",
                         "chat_template_caps": {"supports_tools": True}}}  # fmt: skip
        async with FakeLlamaServer([MODEL], props=props, script=answer) as server:
            provider = LlamaServerProvider(server.url, server.api_key)
            requests = [(role, [ProviderMessage("system", f"{role} prompt")], []) for role in ("coach", "solver")]
            provider.start_warming(MODEL, requests)
            await asyncio.sleep(0.1)  # the Coach's prefix is being read
            real = await provider.complete(MODEL, [ProviderMessage("user", "hi")], [], role="diagnoser")
            assert provider.warming is not None
            warmed = await provider.warming
            await provider.close()
            return list(server.requests), warmed, real.text

    seen, warmed, text = run(scenario())
    assert text == "real" and warmed == 2
    warm = [r for r in seen if r.get("max_tokens") == 1]
    assert [r["id_slot"] for r in warm] == [0, 0, 1]  # the Coach's prefix again after the real call, then the Solver's
    assert all(r["messages"][-1] == {"role": "user", "content": "."} for r in warm)
    real_at = next(i for i, r in enumerate(seen) if r.get("max_tokens") != 1)
    assert real_at == 1  # the real call went before the rest of the warm-up


def test_plt08_low_class_needs_reading_and_writing_speed() -> None:
    """D128: after the benchmark's realistic prompt the low class needs both reading and writing speed; the minimum
    laptop measured on the low reference VM (about 25 tokens/s reading, 5.5 writing) is content-only, the tutor going
    online or to a school server, and a machine that could not finish the benchmark measured nothing."""
    from agent_core.router.probe import BENCHMARK_PROMPT, Benchmark, Probe, choose_class

    data = json.loads((Path(__file__).parent / "fixtures" / "probe" / "low.json").read_text())
    probe = Probe.from_json(data["probe"])
    settings = Settings()
    assert 1000 <= len(BENCHMARK_PROMPT) // 4 <= 1500  # about 1,200 tokens: the prompt length of a tutor turn
    assert choose_class(probe, Benchmark("qwen3-vl-8b", 55.0, 9.5, 28.6), settings).hardware_class == "low"
    vm = choose_class(probe, Benchmark("qwen3-vl-8b", 25.0, 5.5, 60.0), settings)
    assert vm.hardware_class == "content_only" and not vm.provisional
    assert [(s.check, s.unit) for s in vm.shortfalls] == [("speed", "tokens/s reading"), ("speed", "tokens/s writing")]
    writing = choose_class(probe, Benchmark("qwen3-vl-8b", 55.0, 6.0, 30.0), settings)
    assert writing.hardware_class == "content_only" and [s.unit for s in writing.shortfalls] == ["tokens/s writing"]
    assert choose_class(probe, Benchmark("qwen3-vl-8b", 0.0, 0.0, 90.0), settings).hardware_class == "content_only"


def test_plt08_benchmark_timeout_is_below_the_low_class() -> None:
    """A runtime too slow to finish the benchmark within `benchmark_max_s` measures no speed (D128)."""
    from agent_core.providers.base import ProviderError
    from agent_core.router.probe import run_benchmark

    class Slow:
        async def benchmark(self, model: str, prompt: str, generate: int, timeout_s: float) -> dict[str, float]:
            raise ProviderError("timeout", "the benchmark did not finish")

    bench = run(run_benchmark(Slow(), "qwen3-vl-8b", Settings()))
    assert (bench.prompt_tokens_s, bench.generation_tokens_s) == (0.0, 0.0)
