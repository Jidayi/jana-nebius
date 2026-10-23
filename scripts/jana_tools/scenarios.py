"""The scenario runner (EVL-03): YAML suites, validated strictly against the scenario contract, run through the real
engine (assembled exactly as the app assembles it) with the sandboxed tool worker and, per commit, a scripted
provider whose synthetic replies sit beside the suite in `scripts/<scenario id>.yaml` (or, for a suite whose
scenarios share their replies, `scripts/<suite>.yaml`).

Expectations are typed and deterministic; wording is the only thing a judge would decide, and judged criteria run in
the nightly harness with a real model (M7). A scenario whose stage is beyond the build's stage is skipped; a
`critical` scenario passes only if every repeat passes."""

from __future__ import annotations

import asyncio
import json
import re
import tempfile
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

import yaml

from . import REPO_ROOT

SUITES = REPO_ROOT / "evals" / "scenarios"
STAGES = ("S1", "S2", "S3", "S4", "S5")
SUPPORTED_S1 = frozenset(
    {
        "tool_call",
        "gate",
        "no_answer_leak",
        "answer_revealed",
        "hint_rung",
        "mode",
        "event",
        "board_step",
        "template",
        "reply",
        "network_calls",
    }
)
GATE_OUTCOMES = {
    "passed": ("passed",),
    "regenerated": ("passed_after_nudge",),
    "fallback_template": ("exhausted_canned", "exhausted_fallback", "exhausted_pending_used"),
}


@dataclass
class Check:
    expectation: dict[str, Any]
    passed: bool | None  # None: not run in this build
    detail: str = ""


@dataclass
class ScenarioResult:
    scenario_id: str
    status: str  # passed, failed, skipped
    checks: list[Check] = field(default_factory=list)
    reason: str = ""
    traces: list[dict[str, Any]] = field(default_factory=list)
    numbers_total: int = 0  # board steps showing a number (EVL-17a: traced to a check_id)
    numbers_traced: int = 0
    leaks: int = 0  # no_answer_leak expectations that failed
    model_context: dict[str, Any] = field(default_factory=dict)  # PRV-29 metadata only, no request content


def suite_errors(suite: dict[str, Any]) -> list[str]:
    from agent_core.contracts import errors as contract_errors

    return contract_errors("evals/scenario", suite)


def load_suite(path: Path) -> dict[str, Any]:
    suite = yaml.safe_load(path.read_text())
    problems = suite_errors(suite)
    if problems:
        raise ValueError(f"{path.name}: {problems[0]}")
    return suite


def _scripted(script: dict[str, list[Any]]) -> dict[str, list[Any]]:
    """Synthetic replies as provider steps; `{{last_check_id}}` and `{{task_check_ids}}` are filled from the request."""

    def step_for(entry: dict[str, Any]) -> Any:
        def build(body: dict[str, Any]) -> dict[str, Any]:
            message: dict[str, Any] = {"role": "assistant", "content": ""}
            finish = "stop"
            if "tool_calls" in entry:
                message["tool_calls"] = [
                    {
                        "id": f"c{n}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": json.dumps(c["args"])},
                    }
                    for n, c in enumerate(entry["tool_calls"])
                ]
                finish = "tool_calls"
            elif "json" in entry:
                message["content"] = _fill(json.dumps(entry["json"]), body)
            else:
                message["content"] = _fill(entry["text"], body)
            return {
                "reply": {
                    "model": "scripted",
                    "choices": [{"message": message, "finish_reason": finish}],
                    "usage": {"prompt_tokens": 40, "completion_tokens": 20},
                }
            }

        return build

    return {role: [step_for(e) for e in steps] for role, steps in script.items()}


def _fill(text: str, body: dict[str, Any]) -> str:
    tool_ids = [
        json.loads(m["content"])["check_id"]
        for m in body["messages"]
        if m["role"] == "tool" and m["content"].startswith("{") and "check_id" in m["content"]
    ]
    task = next((m["content"] for m in body["messages"] if m["role"] == "user"), "")
    task_ids = sorted(set(re.findall(r"chk_[0-9A-Za-z]+", task)))
    text = text.replace("{{last_check_id}}", tool_ids[-1] if tool_ids else "chk_missing")
    return text.replace('"{{task_check_ids}}"', json.dumps(task_ids or ["chk_missing"]))


async def run_scenario(
    scenario: dict[str, Any],
    suite_dir: Path,
    build_stage: str = "S1",
    disabled_gates: frozenset[str] = frozenset(),
    suite: str | None = None,
    hardware_class: str | None = None,
    engine_stage: str = "S1",
) -> ScenarioResult:
    """`hardware_class` overrides the scenario's own, for a suite that must pass on every class (EVL-11).
    `engine_stage` is the stage the engine runs (`Settings.build_stage`): the per-commit scripts are S1 dialogues
    (no Diagnoser, input-guard or rule-matcher replies) until a suite's scripts carry the S2 roles' replies."""
    if STAGES.index(scenario["stage"]) > STAGES.index(build_stage):
        return ScenarioResult(scenario["id"], "skipped", reason=f"stage {scenario['stage']} is beyond {build_stage}")
    script_path = suite_dir / "scripts" / f"{scenario['id']}.yaml"
    if not script_path.is_file() and suite is not None:
        script_path = suite_dir / "scripts" / f"{suite}.yaml"
    if not script_path.is_file():
        return ScenarioResult(scenario["id"], "skipped", reason="no scripted replies for the per-commit run")
    repeats = int(scenario["setup"].get("repeats", 1))
    results = [await _run_once(scenario, script_path, disabled_gates, hardware_class, engine_stage)
               for _ in range(repeats)]  # fmt: skip
    failed = [r for r in results if r.status == "failed"]
    if failed and (scenario["critical"] or len(failed) == len(results)):
        return failed[0]
    return results[0]


async def _run_once(
    scenario: dict[str, Any],
    script_path: Path,
    disabled_gates: frozenset[str],
    hardware_class: str | None = None,
    engine_stage: str = "S1",
) -> ScenarioResult:
    from agent_core.config import Settings
    from agent_core.engine.assembly import assemble
    from agent_core.engine.events import new_id
    from agent_core.engine.state import SessionState
    from agent_core.providers.scripted import ScriptedProvider
    from agent_core.tools.worker import WorkerSupervisor
    from agent_core.tools.worker.launch import process_factory

    setup = scenario["setup"]
    # A long worker handshake allowance: a busy evaluation machine must not turn a scenario into a tool outage.
    settings = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0,
                        build_stage=engine_stage)  # fmt: skip
    script = _scripted(yaml.safe_load(script_path.read_text()))
    local = ScriptedProvider(script, kind="local", installed_models=["qwen3-vl-8b", "gemma-4-12b"])
    cloud = ScriptedProvider([], kind="cloud")
    hardware = hardware_class or setup.get("model", {}).get("hardware_class", "mid")
    state = SessionState(
        new_id("ses"),
        subject=setup["profile"]["subjects"][0],
        level=setup["profile"]["level"],
        mode=setup["mode"],
        hardware_class=hardware if hardware != "content_only" else "low",
    )
    with tempfile.TemporaryDirectory() as scratch:
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=Path(scratch) / "w"), settings)

        async def no_sleep(_: float) -> None:
            return None

        engine = None
        result = ScenarioResult(scenario["id"], "passed")
        try:
            await supervisor.start()
            engine = assemble(
                {"local": local, "cloud": cloud},
                settings,
                state,
                REPO_ROOT / "content" / "agent",
                REPO_ROOT / "skills",
                Path(scratch) / "spill",
                supervisor,
                sleep=no_sleep,
                disabled_gates=disabled_gates,
            )
            # A `photo` scenario's question text stands for a confirmed photo reading (OCR text, PRM-18).
            source = "ocr_text" if "photo" in scenario.get("tags", []) else "student_text"
            await engine.start_problem(setup["question"]["text"], source=source)
            final = numbers_of(engine.state.plan.final_value) if engine.state.plan else []
            for turn in scenario["turns"]:
                before = set(engine.state.student_lines)
                if "student" in turn:
                    outcome = await engine.student_turn(turn["student"])
                elif turn["action"]["kind"] in ("stuck", "hint_request"):
                    outcome = await engine.student_turn("I'm stuck, can I have a hint?")
                else:
                    result.checks += [
                        Check(e, None, f"action {turn['action']['kind']} is not in S1") for e in turn["expect"]
                    ]
                    continue
                for expectation in turn["expect"]:
                    result.checks.append(_check(expectation, engine, outcome.turn_id, final, before, cloud))
            for expectation in scenario.get("final", []):
                result.checks.append(_check(expectation, engine, None, final, set(), cloud))
        except Exception as error:  # one scenario's failure is a result, never the end of the run
            traces = engine.traces if engine else []
            tools = [f"{c['name']}={c['status']}" for t in traces for c in t.get("tool_calls", [])
                     if c.get("status") != "ok"]  # fmt: skip
            result.status = "failed"
            result.reason = f"{type(error).__name__}: {str(error)[:200]}" + (
                f" (tool calls not ok: {', '.join(tools)})" if tools else "")  # fmt: skip
        finally:
            await supervisor.close()
        if engine is not None:
            result.traces = list(engine.traces)
            result.numbers_total, result.numbers_traced = traced_numbers(engine)
        from .harness.context import audit_requests

        result.model_context = audit_requests(
            [*local.requests, *cloud.requests], max_image_side=settings.photo_downscale_side_px
        )
        if result.model_context["failures"]:
            result.status, result.reason = "failed", "model_context_invalid"
        result.leaks = sum(1 for c in result.checks if "no_answer_leak" in c.expectation and c.passed is False)
        if result.status == "failed":
            return result
    if any(c.passed is False for c in result.checks):
        result.status = "failed"
    return result


EXPONENT = re.compile(r"\^\s*(\{[^}]*\}|-?\d+)")
STRUCTURAL = {Fraction(0), Fraction(1), Fraction(2)}  # constants of a formula, as the build verifier allows them
MARKED = ("correct", "incorrect", "equivalent_unsimplified")


def traced_numbers(engine: Any) -> tuple[int, int]:
    """Board steps that show a computed or given number, and how many of them are traced: a check id, or, for the
    student's own line, a verdict given by code (correct or incorrect). Exponents and the structural constants 0, 1
    and 2 of a formula ("v^2 = u^2 + 2as") are not numbers to trace (CUR-20)."""
    total = traced = 0
    for frame in engine.events.frames:
        event = frame["event"]
        if event.get("type") != "board.step":
            continue
        shown = [n for n in numbers_of(EXPONENT.sub("", str(event.get("latex", "")))) if n not in STRUCTURAL]
        if shown:
            total += 1
            judged = event.get("owner") == "student" and event.get("status") in MARKED
            traced += bool(event.get("check_id")) or judged
    return total, traced


def numbers_of(text: str) -> list[Fraction]:
    from agent_core.engine.state import numbers_in

    return numbers_in(text)


def _visible(engine: Any, turn_id: str | None) -> tuple[str, list[dict[str, Any]]]:
    events = [f["event"] for f in engine.events.frames if turn_id is None or f["turn_id"] == turn_id]
    surfaces = []
    for event in events:
        if event["type"] == "text.delta":
            surfaces.append(event["delta"])
        elif event["type"] == "board.step":
            surfaces.append(event["latex"])
        elif event["type"] == "card.open":
            surfaces.append(json.dumps(event["card"]))
    return "\n".join(surfaces), events


def _count_ok(value: int, spec: dict[str, Any]) -> bool:
    return (
        value >= spec.get("min", value)
        and value <= spec.get("max", value)
        and ("eq" not in spec or value == spec["eq"])
    )


def _check(
    expectation: dict[str, Any],
    engine: Any,
    turn_id: str | None,
    final: list[Fraction],
    derived_before: set[str],
    cloud: Any,
) -> Check:
    from agent_core.engine.gates import leak_findings

    ((key, spec),) = expectation.items()
    if key not in SUPPORTED_S1:
        return Check(expectation, None, f"{key} is checked in the nightly harness (M7)")
    text, events = _visible(engine, turn_id)
    log = next((t for t in engine.turn_log if t["turn_id"] == turn_id), {"tools": [], "template": None})
    trace = next((t for t in engine.traces if turn_id and t.get("turn_id") == turn_id.split("_", 1)[-1]), None)
    student_numbers = {v for line in derived_before for v in numbers_of(line)}
    if key == "no_answer_leak":
        withheld = [(v, None) for v in final if v not in student_numbers]
        found = leak_findings({"visible": text}, withheld, engine.deps.settings)
        return Check(expectation, not found, f"leaks: {[f.kind for f in found]}")
    if key == "answer_revealed":
        found = leak_findings({"visible": text}, [(v, None) for v in final], engine.deps.settings)
        return Check(expectation, bool(found))
    if key == "tool_call":
        matches = [
            c
            for c in _all_tools(engine, turn_id)
            if c["name"] == spec["name"]
            and ("role" not in spec or c["role"] == spec["role"])
            and ("status" not in spec or _status(c["status"]) == spec["status"])
            and all(c["args"].get(k) == v for k, v in spec.get("args", {}).items())
        ]
        return Check(expectation, (not matches) if spec.get("absent") else bool(matches))
    if key == "gate":
        gate = next((g for g in (trace or {}).get("gates", []) if g["gate"] == spec["name"]), None)
        if gate is None:
            return Check(expectation, False, "gate not evaluated")
        ok = ("fired" not in spec or gate["fired"] == spec["fired"]) and (
            "outcome" not in spec or gate["outcome"] in GATE_OUTCOMES[spec["outcome"]]
        )
        return Check(expectation, ok, f"{gate}")
    if key == "hint_rung":
        return Check(expectation, _count_ok(engine.state.rung, spec), f"rung {engine.state.rung}")
    if key == "mode":
        return Check(expectation, engine.state.mode == spec)
    if key == "event":
        hits = [
            e
            for e in events
            if e["type"] == spec["type"] and all(e.get(k) == v for k, v in spec.get("match", {}).items())
        ]
        if spec.get("absent"):
            return Check(expectation, not hits)
        return Check(expectation, _count_ok(len(hits), spec["count"]) if "count" in spec else bool(hits))
    if key == "board_step":
        steps = [e for e in events if e["type"] == "board.step"]
        hits = [
            e
            for e in steps
            if ("owner" not in spec or e["owner"] == spec["owner"])
            and ("status" not in spec or e["status"] == spec["status"])
            and (not spec.get("requires_check_id") or e["check_id"])
        ]
        return Check(expectation, bool(hits), f"{[(e['owner'], e['status'], e['check_id']) for e in steps]}")
    if key == "template":
        return Check(expectation, log.get("template") == spec, f"template {log.get('template')}")
    if key == "reply":
        reply = text
        ok = True
        if "max_words" in spec:
            ok &= len(reply.split()) <= spec["max_words"]
        if "must_mention_any" in spec:
            ok &= any(w.lower() in reply.lower() for w in spec["must_mention_any"])
        if "must_not_mention" in spec:
            ok &= not any(w.lower() in reply.lower() for w in spec["must_not_mention"])
        if spec.get("ends_with_question"):
            ok &= reply.rstrip().endswith("?")
        return Check(expectation, ok, reply[:200])
    if key == "network_calls":
        return Check(expectation, _count_ok(len(cloud.requests), spec), f"{len(cloud.requests)} cloud requests")
    return Check(expectation, None)


def _all_tools(engine: Any, turn_id: str | None) -> list[dict[str, Any]]:
    turns = engine.turn_log if turn_id is None else [t for t in engine.turn_log if t["turn_id"] == turn_id]
    return [c for t in turns for c in t["tools"]]


def _status(status: str) -> str:
    return {"ok": "ok", "error": "error", "partial": "ok", "cancelled": "failed"}.get(status, status)


def run_suites(root: Path = SUITES, build_stage: str = "S1") -> list[ScenarioResult]:
    results = []
    for path in sorted(root.glob("*.yaml")):
        if path.name.endswith(".meta.yaml"):  # item metadata beside the suite (EVL-24), not a suite
            continue
        suite = load_suite(path)
        for scenario in suite["scenarios"]:
            results.append(asyncio.run(run_scenario(scenario, path.parent, build_stage, suite=suite["suite"])))
    return results
