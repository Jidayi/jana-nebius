"""The worker's limits hold (SEC-08, TOL-24): every numeric power is bounded before it is evaluated, each call runs
within its CPU and memory budget, and the worker starts where the platform has no `resource` module (Windows),
reporting which limits it cannot enforce there."""

from __future__ import annotations

import json
import subprocess
import sys
import time

import pytest
from tool_worker import grammar
from tool_worker.budget import BudgetExceeded, call_budget, peak_rss_mb


@pytest.mark.parametrize("text", ["4^(10^9+1/2)", "4^(2000000001/2)", "(1/3)^(-9999)", "1^(10^9+1/2)"])
def test_sec08_rational_powers_bounded(text: str) -> None:
    began = time.monotonic()
    with pytest.raises(grammar.TooLarge):
        grammar.parse(text)
    assert time.monotonic() - began < 2.0


def test_sec08_small_powers_still_evaluate() -> None:
    assert str(grammar.parse("4^(5/2)").tree) == "32"
    assert str(grammar.parse("2^(1/2)").tree) == "sqrt(2)"


def _spin(n: int) -> int:
    return n + 1


def test_sec08_call_cpu_budget_enforced() -> None:
    began = time.monotonic()
    with pytest.raises(BudgetExceeded) as over, call_budget(cpu_ms=100, memory_mb=100_000):
        n = 0
        while True:
            n = _spin(n)
    assert over.value.limit == "cpu" and time.monotonic() - began < 5.0


def _grow(kept: list[bytes]) -> None:
    kept.append(b"x" * (1024 * 1024))


@pytest.mark.skipif(peak_rss_mb() is None, reason="no memory reading on this platform (reported at start)")
def test_sec08_call_memory_budget_enforced() -> None:
    kept: list[bytes] = []
    with pytest.raises(BudgetExceeded) as over, call_budget(cpu_ms=60_000, memory_mb=64):
        for _ in range(4096):
            _grow(kept)
            for _ in range(300):
                _spin(0)  # Python calls between allocations, where the budget is checked
    assert over.value.limit == "memory"


def test_sec08_worker_starts_without_resource_module() -> None:
    """With `resource` absent, as on Windows, the worker's modules import, the OS limits are reported unsupported
    instead of failing, and a ping still answers."""
    script = (
        "import sys, json\n"
        "sys.modules['resource'] = None\n"
        "from tool_worker import guard, budget\n"
        "from tool_worker.server import Server, Limits\n"
        "problems = guard.set_limits({})\n"
        "pong = Server({}, sys.stdout.buffer, Limits()).pong()\n"
        "print(json.dumps({'problems': problems, 'pong': pong}))\n"
    )
    run = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=120)
    out = json.loads(run.stdout.strip().splitlines()[-1])
    assert "RLIMIT_AS" in out["problems"] and "per_call_memory_mb" in out["problems"]
    assert out["pong"]["kind"] == "pong" and "rss_mb" not in out["pong"]
