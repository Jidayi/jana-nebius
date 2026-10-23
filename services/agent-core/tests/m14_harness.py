"""Shared helpers of the M14.g to M14.j tests: the engine harness with a handshake allowance for a busy machine (the
tests check behaviour, not the warm-start budget of TOL-26, which has its own test)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from agent_core.config import Settings
from engine_harness import make_engine


def busy_settings() -> Settings:
    return Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,), worker_warm_target_s=20.0)


async def engine_for(tmp_path: Path, script: dict[str, list[Any]], **kw: Any) -> Any:
    return await make_engine(tmp_path, script, settings=busy_settings(), **kw)
