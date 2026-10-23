"""M11.e: low-power mode (PLT-22) and background jobs (ARC-32). Scripted models and synthetic batteries only; the
battery budgets per class are judged on the device lab's runs (`JANA_DEVLAB_RESULTS`)."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

import pytest
from agent_core.config import Settings
from agent_core.router.power import Battery, PowerPlan, plan, saving
from api_harness import STATEMENT, ask, scripted, stop_core
from engine_harness import checker_steps, close, make_engine, solver_steps, tutor
from jana_tools.harness import devlab
from memory_harness import DAY, core_with_reflector, note, reflection, requests_of, wait_for
from test_m15e_reflector import STUCK, _stuck

SETTINGS = Settings()
SAFE = "Which quantities does the question give you, and which one does it ask for?"
MODELS = ["gemma-4-12b", "qwen3-vl-8b"]  # a plan's models, largest first (MDL-19)


# --- PLT-22 ------------------------------------------------------------------------------------------------------


def test_plt22_when_the_app_saves_power() -> None:
    low = SETTINGS.low_power_battery_pct - 5
    assert saving(SETTINGS, True, None) == "preference"
    assert saving(SETTINGS, False, Battery(low, discharging=True)) == "battery"
    assert saving(SETTINGS, False, Battery(low, discharging=False)) is None  # plugged in
    assert saving(SETTINGS, False, Battery(SETTINGS.low_power_battery_pct + 5, discharging=True)) is None
    assert saving(SETTINGS, False, None) is None  # no battery
    # The next smaller installed model; on the smallest (the 8B-class floor, D58) only outputs and thinking change.
    assert plan(SETTINGS, True, None, MODELS, "gemma-4-12b") == PowerPlan(
        "preference", "qwen3-vl-8b", SETTINGS.low_power_max_output_tokens)  # fmt: skip
    smallest = plan(SETTINGS, False, Battery(low, True), MODELS, "qwen3-vl-8b")
    assert smallest is not None and smallest.model is None
    assert plan(SETTINGS, False, None, MODELS, "gemma-4-12b") is None


def test_plt22_router_uses_the_smaller_model_shorter_answers_and_no_thinking(tmp_path: Path) -> None:
    def pin(data: dict[str, Any]) -> None:
        for tier in data["tiers"]:
            data["tiers"][tier] = ["local:gemma-4-12b"]
        data["roles"]["solver"]["reasoning"] = "high"

    async def go(saving_now: bool) -> Any:
        engine, provider = await make_engine(tmp_path / str(saving_now), _fresh(), overrides=pin)
        if saving_now:
            engine.deps.router.power = lambda: PowerPlan("battery", "qwen3-vl-8b", 256)
        records: list[Any] = []
        engine.deps.router.hooks.on_trace = records.append
        await engine.start_problem(STATEMENT)
        await close(engine)
        return provider, records

    normal, normal_records = asyncio.run(go(False))
    saved, saved_records = asyncio.run(go(True))
    assert {r["model"] for r in normal.requests} == {"gemma-4-12b"}
    assert {r["model"] for r in saved.requests} == {"qwen3-vl-8b"}
    coach = [r for r in saved.requests if r.get("_role") == "coach"]
    assert coach and all(r.get("max_tokens", 10**9) <= 256 for r in coach)
    solver_effort = [e for rec in normal_records if rec.role == "solver" for e in rec.efforts]
    assert any(e.get("requested") not in (None, "none") for e in solver_effort), solver_effort
    saved_effort = [e for rec in saved_records for e in rec.efforts]
    assert saved_effort and all(e.get("requested") == "none" for e in saved_effort), saved_effort


def _fresh() -> dict[str, list[Any]]:
    return {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)]}


def test_plt22_banner_condition(tmp_path: Path) -> None:
    """The client's low-battery banner reads the `power` health condition."""
    from agent_core.engine.assembly import AppRuntime
    from jana_tools import REPO_ROOT

    runtime = AppRuntime(SETTINGS, REPO_ROOT / "content" / "agent", REPO_ROOT / "skills", tmp_path)
    runtime.read_battery = lambda: Battery(80.0, True)
    assert runtime.health_components()["power"] == "ok" and runtime.power_plan() is None
    runtime._battery = None
    runtime.read_battery = lambda: Battery(SETTINGS.low_power_battery_pct - 10, True)
    assert runtime.health_components()["power"] == "degraded"
    runtime.plan = {"attempts": [{"model": m} for m in MODELS]}
    runtime.model = "gemma-4-12b"
    saved = runtime.power_plan()
    assert saved is not None and saved.reason == "battery" and saved.model == "qwen3-vl-8b"


def test_plt22_battery_budgets_per_class() -> None:
    def laptop(hw: str, normal: float, low: float) -> dict[str, Any]:
        return {"name": f"synthetic-{hw}", "hardware_class": hw, "battery": {"normal_w": normal, "low_power_w": low}}

    assert devlab.battery_errors(laptop("low", 14.0, 9.5)) == []
    assert any("saves" in e for e in devlab.battery_errors(laptop("mid", 17.0, 14.0)))
    assert any("normal mode" in e for e in devlab.battery_errors(laptop("high", 30.0, 16.0)))
    lab = os.environ.get("JANA_DEVLAB_RESULTS")
    if lab is None:
        pytest.skip("needs the reference laptops' battery runs (device lab: JANA_DEVLAB_RESULTS)")
    laptops = [json.loads(p.read_text()) for p in sorted(Path(lab).glob("*.json"))]
    runs = [lap for lap in laptops if lap.get("battery")]
    if not runs:
        pytest.skip("the device lab has no battery runs yet")
    assert [e for lap in runs for e in devlab.battery_errors(lap)] == []


# --- ARC-32 ------------------------------------------------------------------------------------------------------


def test_arc32_background_job_cancelled_when_a_turn_starts_and_held_during_a_mock(tmp_path: Path) -> None:
    reflector = [reflection(note("Checks units before dividing", [1], date=DAY), stall=30.0) for _ in range(3)]
    coach = [*STUCK, *(tutor("Not quite yet. Look at the top again.") for _ in range(3))]
    provider = scripted({"solver": solver_steps(), "checker": checker_steps(), "coach": coach,
                         "reflector": reflector})  # fmt: skip
    budget = SETTINGS.background_cancel_budget_s

    async def scenario() -> dict[str, Any]:
        r = await core_with_reflector(tmp_path, provider)
        queue = r.core.reflector
        assert queue is not None
        try:
            session = await r.session()
            await _stuck(r, session)  # learning evidence a note can cite
            await queue.idle()
            # A job runs at idle; a turn starting cancels it within the budget.
            assert queue.trigger("idle", "prof_local", session, session_date=DAY, subject="physics")
            await wait_for(lambda: len(requests_of(provider, "reflector")) == 1)
            assert queue.running is not None
            started = time.monotonic()
            second = await r.post(f"/v1/sessions/{session}/turns", ask("s = 6 m", "answer"))
            assert second.status_code == 202, second.text
            await wait_for(lambda: queue.running is None, timeout=budget * 5)
            cancelled_s = time.monotonic() - started
            await r.wait_idle(session)
            # A mock sitting in progress: the queued job does not start, however idle the app is.
            sitting = [True]
            r.core.mock_active = lambda: sitting[0]
            r.core.mock_started()
            await asyncio.sleep(budget)
            held = len(requests_of(provider, "reflector"))
            await asyncio.sleep(budget)
            still_held = len(requests_of(provider, "reflector")) == held and queue.running is None
            sitting[0] = False
            await wait_for(lambda: len(requests_of(provider, "reflector")) > held)
            return {"cancelled_s": cancelled_s, "still_held": still_held}
        finally:
            await stop_core(r)

    out = asyncio.run(scenario())
    assert out["cancelled_s"] <= budget, out
    assert out["still_held"], "no background job during a mock sitting"
