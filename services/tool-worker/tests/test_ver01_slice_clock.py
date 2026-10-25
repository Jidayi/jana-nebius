"""VER-01 and VER-27: a symbolic time slice is measured in the thread's CPU time, so a busy machine does not turn a
verdict into `unknown`/`timeout`; real work past the slice still ends in `SliceExpired`."""

from __future__ import annotations

import threading
import time

import pytest
from tool_worker.budget import SliceExpired, time_slice


def _work(calls: int) -> None:
    def step() -> None:
        return None

    for _ in range(calls):
        step()


def test_ver01_slice_ignores_time_the_thread_spends_waiting() -> None:
    # Wall time passes (another process or thread has the CPU), CPU time does not: the slice still has room.
    with time_slice(0.2):
        time.sleep(0.4)
        _work(10_000)


def test_ver01_slice_ignores_another_thread_holding_the_cpu() -> None:
    stop = threading.Event()

    def spin() -> None:
        while not stop.is_set():
            sum(range(1_000))

    other = threading.Thread(target=spin)
    other.start()
    try:
        started = time.monotonic()
        with time_slice(0.05):
            while time.monotonic() - started < 0.2:  # four slices of wall time, shared with the spinning thread
                _work(100)
                time.sleep(0.001)
    finally:
        stop.set()
        other.join()


def test_ver27_slice_still_ends_cpu_work_past_it() -> None:
    with pytest.raises(SliceExpired), time_slice(0.05):
        _work(10**9)
