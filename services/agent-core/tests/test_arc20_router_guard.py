"""ARC-20: only the engine calls the router."""

import asyncio
import threading

import pytest
from agent_core import router
from agent_core.engine import job_scope, turn_scope
from agent_core.trace import current_scope


def arc20_router_requires_engine_context():
    for call in (router.complete, router.stream):
        with pytest.raises(router.RouterOutsideEngineContextError):
            call({"messages": []})
        for scope in (turn_scope("t-1"), job_scope("compaction-1")):
            with scope, pytest.raises(router.NoProviderError):
                call({"messages": []})

    # The scope ends with the block, and does not leak into other threads or tasks.
    with turn_scope("t-2"):
        seen: list[object] = []
        worker = threading.Thread(target=lambda: seen.append(current_scope()))
        worker.start()
        worker.join()
        assert seen == [None]
    assert current_scope() is None

    async def outside_task() -> None:
        with pytest.raises(router.RouterOutsideEngineContextError):
            router.complete({})

    async def main() -> None:
        task = asyncio.get_running_loop().create_task(outside_task())
        with turn_scope("t-3"):
            await task

    asyncio.run(main())
