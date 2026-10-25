"""The shared core for the M25 journey tests (JRN-02 to JRN-11): the shipped core over its local API, wired as the
app wires it at start (`agent_core.api.__main__`), with development-signed packs built from the repository's own
curriculum sources, a scripted provider as the deterministic fake model, and the connectivity layer with every
online feature off. The journey runner (`jana_tools.journeys.runner`) plays each probe inside the egress monitor;
an online branch reaches only the stand-in services of `net_harness`, on loopback. Every learner is synthetic.

`WIRED` names what this core wires beyond `api_harness.start_core`; `test_m25a_journeys` checks it against what the
app's start wires, so a journey never runs on a core the app would not build."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.router import ScriptedProvider
from api_harness import Running, cli, start_core, stop_core
from jana_tools.journeys import runner
from jana_tools.journeys.scripts import Script, script
from test_m10a_profiles import Api, student
from test_m13g_learn import Client, install

SETTINGS = Settings(
    worker_pool_size=1,
    worker_respawn_backoff_s=(0.0,),
    api_command_burst_per_s=1000,
    worker_ping_interval_s=30.0,
    worker_missed_pings_recycle=10,
    worker_warm_target_s=60.0,
    consent_dpia_ref="dpia-journey",
)
MODELS = ["qwen3-vl-8b", "gemma-4-12b"]
# What the app's start wires on the core that `start_core` leaves out, and this core adds (see the module docstring).
WIRED = (
    "assessments",
    "planner",
    "mock_active",
    "retention",
    "start_benchmark",
    "online",
    "release",
    "knowledge",
    "ask_cloud",
)


def scripted(script_: dict[str, list[Any]] | list[Any]) -> ScriptedProvider:
    """The deterministic fake model: replies per role, in order, with the router's models installed."""
    return ScriptedProvider(script_, kind="local", installed_models=MODELS)


async def start(data_dir: Path, *, provider: Any = None, subjects: tuple[str, ...] = ("phy",),
                settings: Settings = SETTINGS, stage: str = "S2", worker: bool = True,
                online: bool = True) -> Running:  # fmt: skip
    """A core over `data_dir` as the app starts it; the subjects' packs are installed once, before the first start
    (a restart keeps what is installed, as a power cut would)."""
    for subject in subjects:
        if not (data_dir / "packs" / f"pack.{subject}.o.pack").exists():  # PackStore.active_path
            install(data_dir, subject)
    r = await start_core(data_dir, provider=provider, settings=settings, stage=stage, worker=worker)
    r.core.assessments = r.runtime.assessments
    r.core.planner = r.runtime.planner
    r.core.mock_active = lambda: bool((opened := r.runtime.assessments()) and opened.mock_active())
    r.core.retention = r.runtime.retention_pass
    r.core.start_benchmark = lambda: r.runtime.start_benchmark(r.runtime.providers.get("local"))
    r.core.knowledge = r.runtime.knowledge  # the one Home input routes against the installed packs (UXS-67)
    if online:  # the connectivity layer (ARC-06): zero egress until a feature is switched on (PRV-02)
        layer = r.runtime.attach_online()
        r.core.online, r.core.release = layer, False
        r.core.ask_cloud = layer.ask_client(
            lambda: r.core.records_profile,
            lambda: getattr(r.core.store, "conn", None) if r.core.records_profile else None,
        )
        layer.publish.append(r.core.publish_app)
        r.core.closers.insert(0, layer.stop)
        layer.start()
    return r


@contextlib.asynccontextmanager
async def core(data_dir: Path, **kw: Any) -> AsyncIterator[Running]:
    r = await start(data_dir, **kw)
    try:
        yield r
    finally:
        await stop_core(r)


async def restart(r: Running, **kw: Any) -> Running:
    """The app closed (or the power cut) and started again on the same data folder."""
    await stop_core(r)
    return await start(r.data_dir, **kw)


async def learner(r: Running, name: str = "Ama", **profile: Any) -> tuple[Client, str]:
    """A student added and opened with a tap (no PIN, D86): (a client holding the profile token, the profile id)."""
    api = Api(r)
    profile_id = await api.add({**student(name), **profile})
    return Client(r, await api.token(profile_id)), profile_id


async def session(c: Client, *, subject: str = "physics", mode: str = "guided", origin: dict[str, Any] | None = None,
                  ) -> str:  # fmt: skip
    body = {"client_session_id": cli(), "mode": mode, "subject": subject, "level": "O",
            "origin": origin or {"kind": "ask", "ref": None}}  # fmt: skip
    return str((await c.ok("POST", "/v1/sessions", body))["session_id"])


async def turn(c: Client, session_id: str, text: str, intent: str = "ask", timeout: float = 60.0) -> Any:
    """One student turn, waited for to the end; the session's engine after it."""
    sent = {"client_message_id": cli(), "intent": intent, "content": [{"type": "text", "text": text}]}
    accepted = await c.send("POST", f"/v1/sessions/{session_id}/turns", sent)
    assert accepted.status_code == 202, accepted.text
    await c.r.wait_idle(session_id, timeout)
    return c.r.core.sessions[session_id].engine


# Every case played in this test session, by its end-to-end id: prd03_core_journeys_offline reads what the journey
# tests already played and plays only what they did not.
RESULTS: dict[str, runner.CaseResult] = {}


def play(journey: str, part: str, probe: runner.Probe) -> runner.CaseResult:
    """Run one case of a journey on the runner and fail the test with the runner's reason."""
    result = asyncio.run(runner.run_case(script(journey), part, probe))
    RESULTS[result.case_id] = result
    assert result.status == "passed", f"{result.case_id}: {result.reason}"
    return result


def branches(journey: str) -> list[str]:
    return [b.id for b in script(journey).branches]


def journey_script(journey: str) -> Script:
    return script(journey)
