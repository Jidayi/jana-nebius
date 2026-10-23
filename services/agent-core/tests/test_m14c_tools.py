"""M14.c, tools half: dedupe and the terminal-failure guard (TOL-13), interruption receipts (TOL-14). The real worker
and the shipped registry; arguments are synthetic."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.engine import turn_scope
from agent_core.engine.events import EventStream
from agent_core.engine.receipts import default_receipts
from agent_core.engine.state import SessionState
from agent_core.engine.toolround import ToolRound
from agent_core.router import ToolCall as ModelCall
from agent_core.tools.dedupe import call_key, canonical
from agent_core.tools.executor import ToolCall, ToolExecutor
from agent_core.tools.results import envelope_errors
from agent_core.tools.spec import SessionCtx
from agent_core.tools.specs import registry
from agent_core.tools.spill import SpillStore
from agent_core.tools.worker import WorkerSupervisor
from agent_core.tools.worker.launch import process_factory
from agent_core.trace.record import TraceBuilder

LOOP = asyncio.new_event_loop()
SESSION_ID = "ses_01JZ0000000000000000000014"


def run(coro: Any) -> Any:
    return LOOP.run_until_complete(coro)


def _settings() -> Settings:
    return Settings(worker_pool_size=2, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=10.0)


async def _executor(tmp_path: Path) -> ToolExecutor:
    settings = _settings()
    supervisor = WorkerSupervisor(process_factory(settings, scratch_root=tmp_path / "scratch"), settings)
    await supervisor.start()
    return ToolExecutor(registry(), settings, SpillStore(tmp_path / "spill"), supervisor)


def _session(subject: str, role: str = "solver") -> SessionCtx:
    return SessionCtx(subject=subject, level="O", session_id=SESSION_ID, role=role, stage="S2")


def test_pack_conventions_reach_live_worker(tmp_path: Path) -> None:
    async def scenario() -> None:
        executor = await _executor(tmp_path)
        assert executor.supervisor is not None
        try:
            chemistry = replace(_session("chemistry"), conventions={"chem.ar_h": "2", "chem.ar_o": "16"})
            result = await executor.run_one(
                ToolCall("call_pack_1", "chem_molar_mass", {"formula": "H2O"}), "solver", chemistry
            )
            assert result["status"] == "ok", result
            assert result["data"]["value"]["molar_mass"]["text"] == "20", result
            physics = replace(_session("physics"), conventions={"phy.g": "10"})
            args = {"expression": "2*g"}
            result = await executor.run_one(ToolCall("call_pack_2", "math_evaluate", args), "solver", physics)
            assert result["status"] == "ok", result
            checked = result["data"]
            assert checked["value"]["exact"]["text"] == "20", result
            assert any(c["source"] == "pack" for c in checked["check"]["constants"])
            stated = {"expression": "2*g", "constants": [{"symbol": "g", "value": "9.8", "source": "question"}]}
            result = await executor.run_one(ToolCall("call_question_3", "math_evaluate", stated), "solver", physics)
            checked = result["data"]
            assert checked["value"]["exact"]["text"] == "98/5", result
            assert checked["check"]["constants"][0]["source"] == "question"
            assert args == {"expression": "2*g"}, "enrichment does not mutate the model's arguments"
            changed = replace(physics, conventions={"phy.g": "9"})
            result = await executor.run_one(ToolCall("call_changed_4", "math_evaluate", args), "solver", changed)
            assert result["data"]["value"]["exact"]["text"] == "18", "changed conventions invalidate dedupe"
            solve = {"equations": ["2*g=20"], "unknowns": ["g"]}
            result = await executor.run_one(ToolCall("call_unknown_5", "math_solve", solve), "solver", physics)
            assert result["status"] == "ok", result
        finally:
            await executor.supervisor.close()

    run(scenario())


def _counting(executor: ToolExecutor) -> list[str]:
    """Count the calls that reach the worker."""
    assert executor.supervisor is not None
    reached: list[str] = []
    original = executor.supervisor.call

    async def call(name: str, *args: Any, **kwargs: Any) -> Any:
        reached.append(name)
        return await original(name, *args, **kwargs)

    executor.supervisor.call = call  # type: ignore[method-assign]
    return reached


def _round(executor: ToolExecutor, settings: Settings, cancelled: asyncio.Event | None = None) -> ToolRound:
    state = SessionState(SESSION_ID, subject="mathematics")
    events = EventStream(SESSION_ID, "epoch-m14c")
    events.begin_turn("trn_01JZ0000000000000000000014")
    trace = TraceBuilder(SESSION_ID, "prof_local", turn_id="trn_01JZ0000000000000000000014")
    return ToolRound(executor, settings, events, trace, state, 1)


# --- TOL-13 ---------------------------------------------------------------------------------------------------------


def tol13_dedupe_same_check_id(tmp_path: Path) -> None:
    async def scenario() -> tuple[list[dict[str, Any]], list[str]]:
        executor = await _executor(tmp_path)
        reached = _counting(executor)
        session = _session("chemistry")
        first = await executor.run_one(ToolCall("call_d_1", "chem_molar_mass", {"formula": "H2O"}), "solver", session)
        # The same call again, written differently: keys in another order would not change it, nor would spaces.
        second = await executor.run_one(
            ToolCall("call_d_2", "chem_molar_mass", {"formula": " H2O "}), "solver", session
        )
        await executor.supervisor.close()  # type: ignore[union-attr]
        return [first, second], reached

    (first, second), reached = run(scenario())
    assert first["status"] == "ok" and second["status"] == "ok", (first, second)
    assert reached == ["chem_molar_mass"], "the worker is called once"
    assert second["meta"]["cached"] is True and "cached" not in first["meta"]
    assert second["meta"]["checks"] == first["meta"]["checks"]
    assert second["meta"]["checks"][0]["check_id"] == first["meta"]["checks"][0]["check_id"]
    assert second["meta"]["call_id"] == "call_d_2" and second["meta"]["dedupe_key"] == first["meta"]["dedupe_key"]
    assert envelope_errors(second) == []


def test_tol13_canonical_arguments() -> None:
    assert canonical({"b": 2.0, "a": " x "}) == {"a": "x", "b": 2}
    assert call_key("math_solve", 1, {"x": 1, "y": [1.0, " a"]}) == call_key("math_solve", 1, {"y": [1, "a"], "x": 1.0})
    assert call_key("math_solve", 1, {"x": 1}) != call_key("math_solve", 2, {"x": 1})


def test_tol13_dedupe_keyed_by_the_session_bands(tmp_path: Path) -> None:
    """A worker result depends on the plausibility bands sent with it (VER-26): a repeat after the pushed skill's bands
    change runs again and carries the new warning; a repeat under the same bands is still served from the store."""
    import json

    band = ({"quantity": "height", "unit": "m", "min": 0.5, "max": 50},)
    thrown = {"motion": "vertical", "speed": 198, "direction": "up", "g": 9.8, "g_source": "question", "points": 3}

    async def scenario() -> tuple[list[dict[str, Any]], list[str]]:
        executor = await _executor(tmp_path)
        reached = _counting(executor)
        out = []
        for n, bands in enumerate(((), band, band, ())):
            session = SessionCtx(subject="physics", level="O", session_id=SESSION_ID, stage="S2", plausibility=bands)
            out.append(await executor.run_one(ToolCall(f"call_b_{n}", "phys_projectile", thrown), "solver", session))
        await executor.supervisor.close()  # type: ignore[union-attr]
        return out, reached

    (plain, banded, banded_again, plain_again), reached = run(scenario())
    assert reached == ["phys_projectile", "phys_projectile"], "one worker call per set of bands"
    assert "warnings" not in json.loads(plain["output"])
    assert [w["code"] for w in json.loads(banded["output"])["warnings"]] == ["implausible"]
    assert banded_again["meta"]["cached"] is True and banded_again["output"] == banded["output"]
    assert plain_again["meta"]["cached"] is True and "warnings" not in json.loads(plain_again["output"])
    # The tool-result `dedupe_key` stays the TOL-13 key of the call itself; only the store also covers the bands.
    assert banded["meta"]["dedupe_key"] == plain["meta"]["dedupe_key"]
    key = call_key("phys_projectile", 1, thrown)
    assert call_key("phys_projectile", 1, thrown, {}) == key != call_key("phys_projectile", 1, thrown, {"a": 1})


def test_tol13_dedupe_bounded_per_session(tmp_path: Path) -> None:
    from agent_core.tools.dedupe import DedupeCache

    cache = DedupeCache(2)
    for n in range(3):
        cache.put("ses_a", f"k{n}", {"status": "ok", "output": str(n), "meta": {}})
    assert cache.size("ses_a") == 2 and cache.get("ses_a", "k0") is None and cache.get("ses_b", "k2") is None
    assert Settings().tool_dedupe_entries == 512


def tol13_terminal_failure_not_retried(tmp_path: Path) -> None:
    settings = _settings()

    async def scenario() -> tuple[list[Any], list[Any], list[str]]:
        executor = await _executor(tmp_path)
        reached = _counting(executor)
        tools = _round(executor, settings)
        session = _session("mathematics")
        # math_solve takes equations only: an inequality is a domain error (not retryable).
        args = {"equations": ["x > 2"], "unknowns": ["x"]}
        with turn_scope("trn_01JZ0000000000000000000014"):
            first = await tools.run([ModelCall("m1", "math_solve", args)], "solver", session, ["math_solve"], False)
            again = await tools.run(
                [ModelCall("m2", "math_solve", dict(reversed(list(args.items()))))],
                "solver",
                session,
                ["math_solve"],
                False,
            )
        await executor.supervisor.close()  # type: ignore[union-attr]
        return first, again, reached

    first, again, reached = run(scenario())
    error = first[0].result["error"]
    if error["code"] != "domain_error":
        # The worker may report an empty real solution set as a result; force the guard with a known domain error.
        raise AssertionError(f"expected domain_error from the worker, got {first[0].result}")
    assert reached == ["math_solve"], "the repeat never reaches the worker"
    blocked = again[0].result
    assert blocked["error"]["code"] == "repeated_failure_blocked"
    assert error["message"][:60] in blocked["output"], "the first error is quoted"
    assert "change the arguments" in blocked["output"].lower()


# --- TOL-14 ---------------------------------------------------------------------------------------------------------


def test_tol14_receipts_cover_table() -> None:
    receipts = default_receipts()
    for name, executor in (
        ("math_solve", "worker"),
        ("update_board", "host"),
        ("ask_student", "client"),
        ("show_visual", "client"),
        ("memory_note", "host"),
        ("content_search", "host"),
    ):
        assert receipts.text(name, executor, "not_started") != receipts.text(name, executor, "running")
    assert receipts.tool_class("math_solve", "worker") == "compute"
    assert receipts.text("ask_student", None, "running").startswith("The question was shown but not answered")


def test_tol14_running_compute_receipt(tmp_path: Path) -> None:
    """A batch stopped mid-run: the running call is abandoned and a call not yet started never runs; each gets its
    receipt as a `cancelled` result and a `tool.state` that carries it."""
    settings = _settings()

    async def scenario() -> tuple[list[Any], ToolRound]:
        executor = await _executor(tmp_path)
        started = asyncio.Event()

        async def slow(args: dict[str, Any], context: Any) -> str:
            started.set()
            await asyncio.sleep(5)
            return "late"

        executor.host_executors["content_search"] = slow
        executor.available = lambda spec, session: True  # type: ignore[method-assign]
        tools = _round(executor, settings)
        cancelled = asyncio.Event()
        session = _session("mathematics", role="coach")

        async def stop() -> None:
            await started.wait()
            cancelled.set()

        stopper = asyncio.ensure_future(stop())
        calls = [ModelCall("m1", "content_search", {"query": "gradient"})]
        with turn_scope("trn_01JZ0000000000000000000014"):
            outcomes = await tools.run(calls, "coach", session, ["content_search"], False, cancelled)
        await stopper
        await executor.supervisor.close()  # type: ignore[union-attr]
        return outcomes, tools

    outcomes, tools = run(scenario())
    by_name = {o.name: o.result for o in outcomes}
    assert by_name["content_search"]["status"] == "cancelled"
    assert by_name["content_search"]["output"] == default_receipts().text("content_search", "host", "running")
    assert envelope_errors(by_name["content_search"]) == []
    states = [e["event"]["state"] for e in tools.events.frames if e["event"]["type"] == "tool.state"]  # type: ignore[union-attr]
    assert any(s["status"] == "cancelled" and s["receipt"] for s in states)
    assert tools.receipts()["call_1_0"] == "abandoned"


def test_tol14_not_started_compute_receipt(tmp_path: Path) -> None:
    """A stop that comes before the batch runs: the worker is never called and the call says nothing was computed."""
    settings = _settings()

    async def scenario() -> tuple[list[Any], list[str]]:
        executor = await _executor(tmp_path)
        reached = _counting(executor)
        tools = _round(executor, settings)
        cancelled = asyncio.Event()
        cancelled.set()
        with turn_scope("trn_01JZ0000000000000000000014"):
            outcomes = await tools.run(
                [ModelCall("m1", "math_evaluate", {"expression": "2+3"})],
                "solver",
                _session("mathematics"),
                ["math_evaluate"],
                False,
                cancelled,
            )
        await executor.supervisor.close()  # type: ignore[union-attr]
        return outcomes, reached

    outcomes, reached = run(scenario())
    assert reached == []
    assert outcomes[0].result["status"] == "cancelled"
    assert outcomes[0].result["output"] == default_receipts().text("math_evaluate", "worker", "not_started")
