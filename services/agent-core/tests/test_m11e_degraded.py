"""M11.e: degraded modes (ARC-26, TABLE ARC-26a), each failure injected for real and read back where the client reads
it: the model runtime gone for good, the tool worker gone, the network gone with the online tier on, a content pack
that fails verification, and a computer below the minimum laptop. Every scenario's events are searched for a number
the tutor shows that no check produced. The notices' wording is the client's (`packages/ui`); here the core's side:
the condition each notice reads, and what still works. Synthetic problems, packs and models only."""

from __future__ import annotations

import asyncio
import json
import re
from fractions import Fraction
from pathlib import Path
from typing import Any

from agent_core.config import Settings
from agent_core.config.environments import Environment
from agent_core.engine.marking import mark_choice
from agent_core.engine.runtime_link import RuntimeLink, write_launch_plan
from agent_core.providers.scripted import ScriptedProvider
from agent_core.router.probe import Probe
from agent_core.store.pack_index import PackIndex
from agent_core.store.packs import TABLES, list_packs, table_sha256, write_pack
from api_harness import STATEMENT, ask, scripted, start_core, stop_core
from engine_harness import checker_steps, close, make_engine, reply, solver_steps, tutor
from jana_tools import REPO_ROOT
from pack_builder.build import load_source
from pack_builder.signing import sign
from signing_service.keys import DEV_KEY_ID, dev_key

SETTINGS = Settings(worker_pool_size=1, worker_respawn_backoff_s=(0.0,))
SAFE = "Which quantities does the question give you, and which one does it ask for?"
PROBES = Path(__file__).parent / "fixtures" / "probe"
NUMBER = re.compile(r"(?<![A-Za-z_])\d+(?:\.\d+)?")


def _shown_text(frames: list[dict[str, Any]]) -> str:
    """Everything the student is shown in the tutor's words or on the board, from the session's events."""
    out = []
    for frame in frames:
        event = frame["event"]
        if event["type"] in ("text.delta",):
            out.append(event["delta"])
        elif event["type"] == "board.step":
            out.append(json.dumps({k: v for k, v in event.items() if k in ("latex", "text", "value", "unit")}))
    return " ".join(out)


def _unverified_numbers(engine: Any) -> list[str]:
    """Numbers shown that are neither in the question or the student's lines nor produced by a check this session (the
    engine's provenance set, the one the API-10 gates read)."""
    allowed = engine.state.provenance()
    return [n for n in NUMBER.findall(_shown_text(engine.events.frames)) if Fraction(n) not in allowed]


def _plan_script() -> dict[str, list[Any]]:
    return {"solver": solver_steps(), "checker": checker_steps(), "coach": [tutor(SAFE)]}


# --- the model runtime ------------------------------------------------------------------------------------------


async def _runtime_gone(tmp_path: Path) -> dict[str, Any]:
    spy = scripted({"coach": [], "solver": [], "checker": []})
    r = await start_core(tmp_path / "data", provider=spy, settings=SETTINGS, worker=False)
    try:
        plan = {"model": "synthetic-large", "attempts": [{"model": "synthetic-large", "context": 6144, "args": []}],
                "restart": {"backoff_s": [0.0], "max_restarts": 0, "window_s": 60.0}}  # fmt: skip
        link = RuntimeLink(SETTINGS, plan)

        def report(readiness: str, component: str) -> None:  # what `api.__main__` does with the link's changes
            r.core.readiness, r.core.components["runtime"] = readiness, component

        link.on_change = report
        r.runtime.link, r.runtime.plan = link, {**plan, "hardware_class": "low", "hardware_reason": "measured"}
        generation = link.attaching("synthetic-large")
        link.attached(generation, True)
        link.lost(generation)  # the restart policy is spent and no smaller model is left (MDL-19)
        session = await r.session()
        turn = await r.post(f"/v1/sessions/{session}/turns", ask(STATEMENT))
        health = (await r.get("/v1/health")).json()
        packs = await r.get("/v1/packs")
        return {"state": link.state, "health": health, "turn": turn, "packs": packs.status_code,
                "calls": len(spy.requests)}  # fmt: skip
    finally:
        await stop_core(r)


# --- the tool worker ---------------------------------------------------------------------------------------------


def _unchecked_plan() -> dict[str, Any]:
    """With no worker the Solver is offered no checking tool; its plan carries a number nothing checked, citing a check
    that was never made."""
    return reply(json.dumps({
        "status": "complete", "method_summary": "Use v^2 = u^2 + 2as with v = 0 at the top.",
        "steps": [{"index": 1, "latex": "0 = 14^2 - 2(9.8)s", "reason": "substitute", "check_id": None,
                   "kc_ref": None, "value": "10", "unit": "m"}],
        "final_answer": {"latex": "s = 10\\,m", "value": "10", "unit": "m", "check_id": "chk_never_made",
                         "plausible": True},
        "blocked_step": None, "blocked_reason": None}))  # fmt: skip


async def _worker_gone(tmp_path: Path) -> tuple[Any, Any, Any]:
    script = {"solver": [_unchecked_plan() for _ in range(4)], "checker": checker_steps(),
              "coach": [tutor(SAFE), tutor(SAFE)]}  # fmt: skip
    engine, provider = await make_engine(tmp_path, script, worker=False)
    result = await engine.start_problem(STATEMENT)
    await close(engine)
    return engine, provider, result


# --- the network, with the online tier on -----------------------------------------------------------------------


async def _network_gone(tmp_path: Path) -> tuple[Any, Any, Any, Any]:
    cloud = ScriptedProvider(lambda model, messages, body: {"transport": "connect"}, kind="cloud")

    def enable(data: dict[str, Any]) -> None:
        data["cloud"]["enabled"] = True
        data["roles"]["coach"]["prefer"] = "cloud"

    engine, local = await make_engine(tmp_path, _plan_script(), overrides=enable, cloud=cloud)
    engine.deps.router.cloud_on = lambda role: True  # type: ignore[method-assign]
    result = await engine.start_problem(STATEMENT)
    await close(engine)
    return engine, local, cloud, result


# --- a content pack that fails verification ---------------------------------------------------------------------


def _pack(folder: Path, subject: str, pack_id: str) -> Path:
    tables = load_source(REPO_ROOT / "content" / "curriculum" / subject / "o").tables
    manifest = {"pack_id": pack_id, "version": "0.1.0",
                "tables": [{"name": t, "sha256": table_sha256(t, tables.get(t, [])), "rows": len(tables.get(t, []))}
                           for t in TABLES]}  # fmt: skip
    path = folder / f"{pack_id}-0.1.0.pack"
    write_pack(path, sign(manifest, dev_key(), DEV_KEY_ID), {t: tables.get(t, []) for t in TABLES})
    return path


def arc26_degraded_modes(tmp_path: Path) -> None:
    # Model runtime unavailable: final, so the tutor is not attempted; lessons' and practice's deterministic parts,
    # packs and progress still answer, and the client shows the "model cannot run" notice from this health answer.
    gone = asyncio.run(_runtime_gone(tmp_path / "runtime"))
    assert gone["state"] == "gave_up"
    assert gone["health"]["readiness"] == "degraded" and gone["health"]["components"]["runtime"] == "down"
    assert gone["turn"].status_code == 503 and gone["turn"].json()["error"]["code"] == "model_unavailable"
    assert gone["calls"] == 0 and gone["packs"] == 200
    part = {"marks": 2, "answer": {"options": [{"id": "a", "correct": True}, {"id": "b", "correct": False}]}}
    assert mark_choice(part, "a").marks_awarded == 2.0

    # Tool worker unavailable: the conversation goes on without numbers and the Coach says it cannot check.
    engine, _, result = asyncio.run(_worker_gone(tmp_path / "worker"))
    assert result.degraded and result.degraded_reason == "plan_unverified", result
    shown = _shown_text(engine.events.frames)
    assert "can't check" in shown, shown
    assert _unverified_numbers(engine) == [], shown
    assert "10" not in NUMBER.findall(shown)  # the Solver's unchecked answer never reaches the student
    assert Fraction(10) not in engine.state.provenance()  # and the search above would have named it

    # The network gone with the online tier on: the cloud call fails at once and the turn runs on this computer.
    engine, local, cloud, result = asyncio.run(_network_gone(tmp_path / "network"))
    assert result.status == "complete" and not result.degraded, result
    assert any(r.get("_role") == "coach" for r in local.requests)
    assert cloud.requests, "the online tier was tried first"
    assert _unverified_numbers(engine) == []

    # A content pack fails verification: that subject is refused, the others still load.
    packs = tmp_path / "packs"
    packs.mkdir()
    good = _pack(packs, "phy", "pack.phy.o")
    bad = _pack(packs, "chm", "pack.chm.o")
    data = bytearray(bad.read_bytes())
    data[len(data) // 2] ^= 0xFF  # one changed byte
    bad.write_bytes(bytes(data))
    listed = {p["pack_id"]: p["signature_ok"] for p in list_packs(packs, Environment.DEV)}
    assert listed.pop("pack.phy.o") is True
    [(damaged, ok)] = listed.items()  # too damaged to read its manifest: named from its file
    assert damaged.startswith("pack.chm.o") and ok is False
    index = PackIndex.load([good, bad], Environment.DEV)
    assert index.kc_statement("kc.phy.o.motion.average_speed") and index.rejected

    # Below the minimum laptop: the content-only class, the same refusal before any model call (PLT-29).
    probe = Probe.from_json(json.loads((PROBES / "below_minimum.json").read_text())["probe"])
    plan = write_launch_plan(tmp_path / "below", SETTINGS, False, "0123456789abcdef", probe=probe)
    assert plan["model"] is None
