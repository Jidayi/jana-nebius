"""M2.a: worker framing, handshake, methods, error codes and supervision (TOL-24, TOL-25, TOL-26)."""

import asyncio
import io
import json
import sys
from pathlib import Path
from typing import get_args

import pytest
from agent_core.config import Settings
from agent_core.contracts import errors as contract_errors
from agent_core.contracts.tools.tool_result import ToolErrorCode
from agent_core.tools.worker import WorkerCallError, WorkerProcess, WorkerSupervisor, tool_error_code
from agent_core.tools.worker.errors import APPLICATION_CODES
from agent_core.tools.worker.launch import worker_argv
from tool_worker.protocol import Code
from tool_worker.registry import Function
from tool_worker.server import Limits, Server

HARNESS = Path(__file__).resolve().parents[2] / "tool-worker" / "tests" / "harness.py"
CHECK = "chk_01JZ0000000000000000000001"


def _settings(**overrides) -> Settings:
    base = {"worker_pool_size": 1, "worker_respawn_backoff_s": (0.0,), "worker_warm_target_s": 10.0}
    return Settings(**{**base, **overrides})


def _harness(*extra: str) -> list[str]:
    return [sys.executable, str(HARNESS), *extra]


def _call(name: str, args: dict | None = None, call_id: str = "c1") -> dict:
    return {"call_id": call_id, "name": name, "version": 1, "args": args or {}, "check_id": CHECK, "deadline_ms": 5000}


async def _process(argv: list[str]) -> WorkerProcess:
    process = WorkerProcess(argv)
    await process.start()
    return process


def tol24_one_frame_per_line():
    out = io.BytesIO()
    server = Server(
        {
            "multiline": Function(
                "multiline",
                1,
                {"type": "object"},
                lambda a, c: (
                    "one\ntwo\r\nthree four",
                    {"latex": "a\\\\\nb", "method": "exact", "confidence": "proved"},
                ),
            )
        },
        out,
    )
    server.handle_line(
        b'{"jsonrpc":"2.0","id":"1","method":"worker.hello","params":{"protocol":{"major":1,"minor":0},"host_version":"t","placement":"device"}}'
    )
    server.handle_line(
        json.dumps({"jsonrpc": "2.0", "id": "2", "method": "fn.call", "params": _call("multiline")}).encode()
    )
    server.serve(io.BytesIO(b""))
    frames = out.getvalue().split(b"\n")
    assert frames[-1] == b"" and len(frames) == 3, "one frame per message, each ending in a newline"
    assert all(frame.isascii() for frame in frames)
    reply = json.loads(frames[1])
    assert reply["result"]["value"] == "one\ntwo\r\nthree four"

    async def real() -> None:
        process = await _process(_harness())
        await process.hello()
        result = await process.request("fn.call", _call("multiline"), timeout=10)
        assert result["value"] == "line one\nline two\r\nline three"
        await process.close()

    asyncio.run(real())


def tol24_stray_lines_dropped(tmp_path: Path):
    async def scenario() -> None:
        # A library print inside the real worker goes to stderr, never into the stream.
        process = await _process(_harness())
        await process.hello()
        assert (await process.request("fn.call", _call("noisy"), timeout=10))["value"] == "quiet"
        assert (await process.request("worker.ping", {}, timeout=10))["kind"] == "pong"
        await process.close()
        # And the host drops (and counts) any line that is not a JSON object.
        fake = tmp_path / "fake_worker.py"
        fake.write_text(
            "import sys, json\n"
            "for line in sys.stdin:\n"
            "    req = json.loads(line)\n"
            "    print('Traceback junk'); print('[1, 2]'); sys.stdout.flush()\n"
            "    print(json.dumps({'jsonrpc': '2.0', 'id': req['id'], 'result': {'kind': 'pong', 'uptime_ms': 1,"
            " 'busy': False}}), flush=True)\n"
        )
        noisy = await _process([sys.executable, str(fake)])
        assert (await noisy.request("worker.ping", {}, timeout=10))["kind"] == "pong"
        assert noisy.dropped_lines == 2
        noisy.kill()
        await noisy.close()

    asyncio.run(scenario())


def tol24_version_mismatch_blocks():
    async def scenario() -> None:
        # A worker of another major blocks every compute call.
        newer = json.dumps({"major": 2, "minor": 0})
        supervisor = WorkerSupervisor(lambda: WorkerProcess(_harness("--protocol", newer)), _settings())
        await supervisor.start()
        assert supervisor.circuit_open and not supervisor.compute_available()
        for name in ("math_parse", "slow"):
            outcome = await supervisor.call(name, 1, {"text": "x"} if name == "math_parse" else {}, CHECK, 5000)
            assert (outcome.error, outcome.action_taken) == ("worker_unavailable", False)
        await supervisor.close()
        # A worker with a higher minor of the same major serves a 1.0 host (minors are additive).
        additive = json.dumps({"major": 1, "minor": 1})
        supervisor = WorkerSupervisor(lambda: WorkerProcess(_harness("--protocol", additive)), _settings())
        await supervisor.start()
        assert supervisor.compute_available()
        served = await supervisor.call("math_parse", 1, {"text": "x"}, CHECK, 5000)
        assert served.error is None
        await supervisor.close()

    asyncio.run(scenario())


def tol25_protocol_conformance():
    async def scenario() -> None:
        notifications: list[dict] = []
        process = WorkerProcess(
            _harness("--limits", json.dumps({"progress_ms": 50})), on_notification=notifications.append
        )
        await process.start()
        replies = [await process.hello()]
        replies.append(await process.request("worker.ping", {}, timeout=10))
        replies.append(await process.request("fn.call", _call("math_parse", {"text": "2x(x+1)"}), timeout=10))
        slow = asyncio.create_task(process.request("fn.call", _call("slow", {"seconds": 0.4}, "c9"), timeout=10))
        await asyncio.sleep(0.2)
        replies.append(await process.request("fn.cancel", {"call_id": "c9"}, timeout=10))
        with pytest.raises(WorkerCallError) as cancelled:
            await slow
        assert cancelled.value.code == Code.CANCELLED
        for method, params in (
            ("exec.run", {"cell_id": "cell_1", "code": "1+1", "timeout_ms": 100}),
            ("exec.interrupt", {"cell_id": "cell_1"}),
            ("exec.reset", {}),
        ):
            with pytest.raises(WorkerCallError) as refused:
                await process.request(method, params, timeout=10)
            assert refused.value.code == Code.EXEC_DISABLED
        assert process.process and process.process.stdin
        process.process.stdin.write(b"not json\n")
        replies.append(await process.request("worker.shutdown", {"grace_ms": 100}, timeout=10))
        await process.close()

        kinds = [r["kind"] for r in replies]
        assert kinds == ["hello", "pong", "fn", "ack", "ack"]
        for reply in replies:
            envelope = {"jsonrpc": "2.0", "id": "x", "result": reply}
            assert contract_errors("tools/worker-protocol#/$defs/Response", envelope) == []
        methods = {n["method"] for n in notifications}
        assert {"fn.progress", "worker.log"} <= methods
        assert not methods & {"exec.progress", "exec.stream"}  # a device worker has no exec path
        for note in notifications:
            assert contract_errors("tools/worker-protocol#/$defs/Notification", note) == []

    asyncio.run(scenario())


def tol25_error_code_mapping():
    allowed = set(get_args(get_args(ToolErrorCode.__value__)[0]))
    assert "worker_crashed" in allowed
    application = [c for c in Code if c > 0] + [11]  # 11 WORKER_RESTARTED is host-side only
    assert sorted(APPLICATION_CODES) == sorted(int(c) for c in application)
    for code in application:
        assert tool_error_code(int(code)) in allowed, code
    expected = {
        1: "worker_unavailable",
        2: "unavailable",
        3: "invalid_args",
        4: "domain_error",
        5: "limit_exceeded",
        6: "cancelled",
        8: "unavailable",
        9: "execution_error",
        10: "execution_error",
        11: "worker_crashed",
        12: "policy_denied",
    }
    assert {c: tool_error_code(c) for c in expected} == expected


def tol25_no_exec_on_device():
    hello = {
        "jsonrpc": "2.0",
        "id": "1",
        "method": "worker.hello",
        "params": {
            "protocol": {"major": 1, "minor": 0},
            "host_version": "t",
            "placement": "device",
            "exec_enabled": True,
        },
    }
    assert contract_errors("tools/worker-protocol#/$defs/Request", hello) != []

    async def scenario() -> None:
        process = await _process(worker_argv(_settings()))
        with pytest.raises(ValueError, match="breaks the worker protocol"):
            await process.request("worker.hello", hello["params"], timeout=10)
        result = await process.hello()
        assert result["exec_available"] is False and result["placement"] == "device"
        with pytest.raises(WorkerCallError) as refused:
            await process.request("exec.run", {"cell_id": "cell_1", "code": "print(1)", "timeout_ms": 100}, timeout=10)
        assert refused.value.code == Code.EXEC_DISABLED
        await process.close()

    asyncio.run(scenario())


def tol26_respawn_after_crash():
    async def scenario() -> None:
        supervisor = WorkerSupervisor(lambda: WorkerProcess(_harness()), _settings())
        await supervisor.start()
        crashed = await supervisor.call("crash", 1, {}, CHECK, 5000)
        assert (crashed.error, crashed.action_taken) == ("worker_crashed", False)
        fresh = await supervisor.call("math_parse", 1, {"text": "x+1"}, CHECK, 5000)
        assert fresh.ok and fresh.result and fresh.result["value"]["text"] == "x + 1"
        timed_out = await supervisor.call("slow", 1, {"seconds": 5}, CHECK, 200)
        assert timed_out.error == "timeout"
        assert (await supervisor.call("math_parse", 1, {"text": "y"}, CHECK, 5000)).ok
        assert len(supervisor.restarts) == 2
        await supervisor.close()

    asyncio.run(scenario())


def tol26_circuit_opens():
    async def scenario() -> None:
        now = [1000.0]
        supervisor = WorkerSupervisor(lambda: WorkerProcess(_harness()), _settings(), clock=lambda: now[0])
        await supervisor.start()
        for _ in range(5):
            assert (await supervisor.call("crash", 1, {}, CHECK, 5000)).error == "worker_crashed"
            now[0] += 5
        assert not supervisor.circuit_open and supervisor.compute_available()
        assert (await supervisor.call("crash", 1, {}, CHECK, 5000)).error == "worker_crashed"  # the sixth in 60 s
        assert supervisor.circuit_open and not supervisor.compute_available()
        assert (await supervisor.call("math_parse", 1, {"text": "x"}, CHECK, 5000)).error == "worker_unavailable"
        now[0] += 61
        assert not supervisor.circuit_open
        assert (await supervisor.call("math_parse", 1, {"text": "x"}, CHECK, 5000)).ok
        await supervisor.close()

    asyncio.run(scenario())


def test_ping_round_recycles_dead_worker():
    async def scenario() -> None:
        supervisor = WorkerSupervisor(lambda: WorkerProcess(_harness()), _settings(worker_missed_pings_recycle=1))
        await supervisor.start()
        supervisor._all[0].kill()
        await asyncio.sleep(0.2)
        await supervisor.ping_round()
        assert len(supervisor.restarts) == 1
        assert (await supervisor.call("math_parse", 1, {"text": "x"}, CHECK, 5000)).ok
        await supervisor.close()

    asyncio.run(scenario())


def test_limits_reach_the_worker():
    limits = Limits(max_expression_chars=10)
    out = io.BytesIO()
    from tool_worker.functions import FUNCTIONS

    server = Server(FUNCTIONS, out, limits)
    server.handle_line(
        b'{"jsonrpc":"2.0","id":"1","method":"worker.hello","params":{"protocol":{"major":1,"minor":0},"host_version":"t","placement":"device"}}'
    )
    server.handle_line(
        json.dumps(
            {"jsonrpc": "2.0", "id": "2", "method": "fn.call", "params": _call("math_parse", {"text": "x+" * 10})}
        ).encode()
    )
    reply = json.loads(out.getvalue().splitlines()[-1])
    assert reply["error"]["code"] == Code.LIMIT_EXCEEDED and reply["error"]["data"]["limit"] == "expression_chars"
