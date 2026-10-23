"""The real engine with a scripted provider, for M4 tests: the shipped registry, router, prompt files, skills and the
sandboxed tool worker. Replies are synthetic; the S1 problem is invented for the tests."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.engine.assembly import assemble
from agent_core.engine.events import new_id
from agent_core.engine.state import SessionState
from agent_core.engine.turn import Engine
from agent_core.providers.scripted import ScriptedProvider
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from jana_tools import REPO_ROOT

CORE = REPO_ROOT / "services" / "agent-core" / "agent_core"
STATEMENT = "A ball is thrown straight up at 14 m/s. Take g = 9.8 m/s^2. How high does it rise?"
SCHEMAS = CORE / "contracts" / "schemas"


def bundled_schemas() -> dict[str, dict[str, Any]]:
    out = {}
    for path in SCHEMAS.glob("*/*.schema.json"):
        out[f"{path.parent.name}/{path.name.removesuffix('.schema.json')}"] = json.loads(path.read_text())
    return out


def reply(content: str = "", calls: list[tuple[str, str, dict[str, Any]]] = (), finish: str = "stop") -> dict:
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if calls:
        message["tool_calls"] = [
            {"id": i, "type": "function", "function": {"name": n, "arguments": json.dumps(a)}} for i, n, a in calls
        ]
        finish = "tool_calls"
    return {
        "reply": {
            "model": "qwen3-vl-8b",
            "choices": [{"message": message, "finish_reason": finish}],
            "usage": {"prompt_tokens": 50, "completion_tokens": 20},
        }
    }


def tutor(say: str, **fields: Any) -> dict:
    turn = {
        "say_spoken": None,
        "say": say,
        "board": [],
        "visual": [],
        "card": None,
        "hint_rung": 0,
        "expects": "student_answer",
        "numbers_from": [],
        "cites": [],
        "reveals": "none",
        "confidence": "medium",
    }
    turn.update(fields)
    # The contract's annotate-only fields (VSL-40, D103) are null on every other op; a fixture names them only to set.
    turn["board"] = [{"mark": None, "part": None, "to": None, **op} for op in turn["board"]]
    return reply(json.dumps(turn))


def last_check_id(body: dict[str, Any]) -> str:
    for message in reversed(body["messages"]):
        if message["role"] == "tool":
            try:
                return json.loads(message["content"])["check_id"]
            except (json.JSONDecodeError, KeyError) as error:
                raise AssertionError(
                    "expected a checked worker result, received: " + message["content"][:400]
                ) from error
    raise AssertionError("no tool result in the request")


def solver_steps() -> list[Any]:
    """The Solver calls math_solve, then hands over a plan citing the check id the worker returned."""

    def plan(body: dict[str, Any]) -> dict:
        check = last_check_id(body)
        return reply(
            json.dumps(
                {
                    "status": "complete",
                    "method_summary": "Use v^2 = u^2 + 2as with v = 0 at the top.",
                    "steps": [
                        {
                            "index": 1,
                            "latex": "v^2 = u^2 + 2as",
                            "reason": "links u, v, a and s",
                            "check_id": None,
                            "kc_ref": None,
                            "value": None,
                            "unit": None,
                        },
                        {
                            "index": 2,
                            "latex": "0 = 14^2 - 2(9.8)s",
                            "reason": "substitute with up positive",
                            "check_id": check,
                            "kc_ref": None,
                            "value": "10",
                            "unit": "m",
                        },
                    ],
                    "final_answer": {
                        "latex": "s = 10\\,m",
                        "value": "10",
                        "unit": "m",
                        "check_id": check,
                        "plausible": True,
                    },
                    "blocked_step": None,
                    "blocked_reason": None,
                }
            )
        )

    return [reply("", [("c0", "math_solve", {"equations": ["0 = 14^2 - 2*9.8*s"], "unknowns": ["s"]})]), plan]


def checker_steps(verdict: str = "correct") -> list[Any]:
    """The Checker cites the check ids of the claimed steps it was given."""

    def judge(body: dict[str, Any]) -> dict:
        task = next(m["content"] for m in body["messages"] if m["role"] == "user")
        ids = sorted(set(re.findall(r"chk_[0-9A-Za-z]+", task)))
        return reply(
            json.dumps(
                {
                    "subject_of_check": "solver_plan",
                    "verdict": verdict,
                    "first_wrong_step": None,
                    "error_category": "none",
                    "why": "each step re-derived",
                    "counterexample": None,
                    "misconception_ref": None,
                    "method": "re_derive",
                    "step_marks": [{"step": 2, "status": "valid", "check_id": ids[0]}],
                    "check_ids": ids,
                }
            )
        )

    return [judge]


async def make_engine(
    tmp_path: Path,
    script: dict[str, list[Any]],
    settings: Settings | None = None,
    hardware_class: str = "mid",
    worker: bool = True,
    overrides: Callable[[dict[str, Any]], None] | None = None,
    disabled_gates: frozenset[str] = frozenset(),
    cloud: ScriptedProvider | None = None,
    device_class: str | None = None,
    local_kind: str = "local",
    stage: str = "S1",
) -> tuple[Engine, ScriptedProvider]:
    """`stage` is the release stage the engine runs (`Settings.build_stage`, AGT-15): this harness's scripts are S1
    dialogues unless a test names S2; the app runs the stage its build is configured for."""
    settings = (settings or Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))).model_copy(
        update={"build_stage": stage}
    )
    supervisor = None
    if worker:
        supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path / "scratch"), settings)
        await supervisor.start()
    provider = ScriptedProvider(script, kind=local_kind, installed_models=["qwen3-vl-8b", "gemma-4-12b"])
    providers: dict[str, Any] = {"local": provider}
    if cloud is not None:
        providers["cloud"] = cloud

    async def no_sleep(_: float) -> None:
        return None

    state = SessionState(new_id("ses"), subject="physics", level="O", hardware_class=hardware_class)
    engine = assemble(
        providers,
        settings,
        state,
        REPO_ROOT / "content" / "agent",
        REPO_ROOT / "skills",
        tmp_path / "spill",
        supervisor,
        router_overrides=overrides,
        sleep=no_sleep,
        session_date="2026-10-09",
        disabled_gates=disabled_gates,
        device_class=device_class,
    )
    return engine, provider


async def close(engine: Engine) -> None:
    if engine.deps.executor.supervisor is not None:
        await engine.deps.executor.supervisor.close()
